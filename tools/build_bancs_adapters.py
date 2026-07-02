"""Genera el catalogo de adaptadores BANCS (Core Adapter) desde el .numbers del banco.

DEV-ONLY: requiere `numbers-parser` (no es dependencia del CLI en runtime; el CLI
solo lee el JSON generado). Re-correr cuando el banco actualice el relevamiento:

    python tools/build_bancs_adapters.py \
        "<ruta al .numbers de adaptadores>" \
        src/capamedia_cli/data/catalog/bancs_adapters.json

Fuente: .numbers "Lista de Adaptadores" + hojas por adaptador (Profile, Details,
Product Compliance, Payments parameter, BNC-Catalogs, Insurances, Ownership).
Relevado para OLA 2; los adaptadores sirven para cualquier ola.

SANITIZACION deliberada: el .numbers trae curls con cookies de sesion y datos de
prueba (cedulas) — NADA de eso entra al JSON ni al repo (regla de secrets del
banco). Se extrae SOLO lo estructural: TX -> adaptador -> operacion + URLs. Por lo
mismo el .numbers fuente NO se versiona en el repo.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter

from numbers_parser import Document  # dev-only

# Host externo de un curl (`https://<adapter>-enp.apps...` o sin -enp) o URL
# interna (`service-<adapter>.arq-adaptadores...`).
_HOST_RE = re.compile(r"https?://([a-z0-9-]+?)(?:-enp)?\.apps\.")
_SVC_RE = re.compile(r"service-([a-z0-9-]+?)\.arq-adaptadores")
# TX en la col TRX: `TRX009600`, `TX064020`, corto `TRX67050`, o float `60602.0`.
_TX_LABEL_RE = re.compile(r"(?i)^T(?:RX|X)\s*(\d{4,6})$")
# TX que el curl ejecuta realmente (`/bancs/trx/NNNNNN`): ante typo del label, manda.
_CURL_TX_RE = re.compile(r"/bancs/trx/(\d{6})")
_ADAPTER_NAME_RE = re.compile(r"^[a-z]{3}-msa-ad-[a-z0-9-]+$")

# Guardia de sanitizacion ESTRUCTURAL (no strings sueltos): nada del material
# sensible del .numbers (curls, cookies, tokens, cedulas, emails, headers) puede
# llegar al JSON shipped. Case-insensitive + patrones de forma.
_FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cookie", re.compile(r"(?i)cookie")),
    ("curl", re.compile(r"(?i)\bcurl\b")),
    ("header-flag", re.compile(r"--header|\s-H\s")),
    ("body-bancs", re.compile(r"(?i)transactionid|bancsuser")),
    ("token-hex32", re.compile(r"(?i)\b[0-9a-f]{32}\b")),
    ("cedula-10dig", re.compile(r"\b\d{10}\b")),
    ("auth", re.compile(r"(?i)authorization|bearer")),
    ("x-headers", re.compile(r"(?i)x-guid|x-session|x-device")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
]

_ADAPTERS_SHEET = "Lista de Adaptadores"


def cells(row) -> list[str]:
    return [("" if c is None else str(c).strip()) for c in row]


def _tx_from_label(raw: str) -> str | None:
    """Normaliza la columna TRX a 6 digitos: `TX064020`/`TRX 009600`/`60602.0`."""
    s = raw.strip()
    m = _TX_LABEL_RE.match(s)
    if m:
        return m.group(1)
    try:
        n = int(float(s))
    except ValueError:
        return None
    return f"{n:06d}" if 0 < n < 1_000_000 else None


def parse_adapters_sheet(rows) -> tuple[dict[str, dict], list[str]]:
    """Hoja 'Lista de Adaptadores': pares de filas (externas DEV/TEST + interna)."""
    adapters: dict[str, dict] = {}
    notes: list[str] = []
    current: str | None = None
    for row in rows[1:]:  # fila 0 = header OLA 2 / DEV / TEST
        c = cells(row)
        if not any(c):
            continue
        if c[0].lower().startswith("nota"):
            current = None
            continue
        if _ADAPTER_NAME_RE.match(c[0]):
            current = c[0]
            adapters[current] = {
                "name": current,
                "url_dev": c[1] if len(c) > 1 else "",
                "url_test": c[2] if len(c) > 2 else "",
                "url_internal": "",
            }
        elif current and len(c) > 1 and "arq-adaptadores" in c[1]:
            adapters[current]["url_internal"] = c[1]
        elif c[0] and not _ADAPTER_NAME_RE.match(c[0]) and len(c[0]) > 40:
            notes.append(c[0])  # texto de la nota (rutas https vs service)
    return adapters, notes


def parse_tx_sheet(sheet_name: str, rows) -> list[dict]:
    """Hoja por-adaptador: una fila por TX. El adaptador se deriva del host del
    curl o de la col INTERNAL; las filas sin URL heredan el adaptador dominante
    de la hoja (cada hoja agrupa las TX de UN adaptador)."""
    header = [h.upper() for h in cells(rows[0])]

    def col(name: str) -> int | None:
        return header.index(name) if name in header else None

    i_trx, i_op = col("TRX"), col("OPERACION")
    i_obs = col("OBSERVACION")
    entries: list[dict] = []
    for row in rows[1:]:
        c = cells(row)
        if i_trx is None or i_trx >= len(c) or not c[i_trx]:
            continue
        tx = _tx_from_label(c[i_trx])
        if not tx:
            continue
        joined = " ".join(c)
        obs = c[i_obs] if i_obs is not None and i_obs < len(c) else ""
        # Si el curl ejecuta OTRA TX que la del label, manda el curl (typo del
        # banco, ej. label TX067728 con curl /bancs/trx/067228) y se audita en obs.
        curl_tx = _CURL_TX_RE.search(joined)
        if curl_tx and curl_tx.group(1) != tx:
            obs = f"(label decia TX{tx}) {obs}".strip()
            tx = curl_tx.group(1)
        m = _HOST_RE.search(joined) or _SVC_RE.search(joined)
        entries.append(
            {
                "tx": tx,
                "adapter": m.group(1) if m else None,
                "operation": c[i_op] if i_op is not None and i_op < len(c) else "",
                "obs": obs,
                "sheet": sheet_name,
            }
        )
    # fallback: adaptador dominante de la hoja para filas sin host detectable
    counts = Counter(e["adapter"] for e in entries if e["adapter"])
    dominant = counts.most_common(1)[0][0] if counts else None
    for e in entries:
        if e["adapter"] is None:
            e["adapter"] = dominant
    return [e for e in entries if e["adapter"]]


def build(numbers_path: str) -> dict:
    doc = Document(numbers_path)
    sheets = {s.name: s.tables[0].rows(values_only=True) for s in doc.sheets}
    adapters, notes = parse_adapters_sheet(sheets[_ADAPTERS_SHEET])

    tx_map: dict[str, dict] = {}
    for name, rows in sheets.items():
        if name == _ADAPTERS_SHEET:
            continue
        for e in parse_tx_sheet(name, rows):
            existing = tx_map.get(e["tx"])
            if existing is None:
                tx_map[e["tx"]] = {  # primera aparicion gana (dedupe)
                    "adapter": e["adapter"],
                    "operation": e["operation"],
                    "obs": e["obs"],
                }
            elif not existing["obs"] and e["obs"]:
                existing["obs"] = e["obs"]  # una fila duplicada puede traer la obs
            # completar adaptadores no listados en la hoja de adaptadores
            if e["adapter"] not in adapters:
                adapters[e["adapter"]] = {
                    "name": e["adapter"],
                    "url_dev": "",
                    "url_test": "",
                    "url_internal": (
                        f"http://service-{e['adapter']}.arq-adaptadores.svc.cluster.local"
                    ),
                }

    if not tx_map or not adapters:
        raise SystemExit("ERROR: 0 adaptadores o 0 TX parseadas. ¿Cambio el formato del .numbers?")

    data = {
        "meta": {
            "ola": 2,
            "scope": "Relevado para OLA 2; los adaptadores sirven para cualquier ola",
            "n_adapters": len(adapters),
            "n_tx": len(tx_map),
            "notes": notes,
        },
        "adapters": {k: adapters[k] for k in sorted(adapters)},
        "tx_map": {k: tx_map[k] for k in sorted(tx_map)},
    }
    _assert_sanitized(data, "$")
    return data


def _assert_sanitized(node, path: str) -> None:
    """Recorre el JSON y aborta con la RUTA exacta si algun patron sensible se
    colo (cookies, curls, tokens hex, cedulas, auth, x-headers, emails)."""
    if isinstance(node, dict):
        for k, v in node.items():
            _assert_sanitized(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _assert_sanitized(v, f"{path}[{i}]")
    elif isinstance(node, str):
        for label, pattern in _FORBIDDEN_PATTERNS:
            if pattern.search(node):
                raise SystemExit(
                    f"ERROR sanitizacion: patron '{label}' en {path}: {node[:80]!r}"
                )


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(f"uso: {sys.argv[0]} <input.numbers> <output.json>")
    data = build(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    m = data["meta"]
    print(f"OK {sys.argv[2]}: {m['n_adapters']} adaptadores, {m['n_tx']} TX mapeadas")


if __name__ == "__main__":
    main()
