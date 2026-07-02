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
# TX en la col TRX: `TRX009600`, `TX064020`, o crudo `60602.0` (float de Numbers).
_TX_LABEL_RE = re.compile(r"(?i)^T(?:RX|X)\s*(\d{6})$")
_ADAPTER_NAME_RE = re.compile(r"^[a-z]{3}-msa-ad-[a-z0-9-]+$")

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
        m = _HOST_RE.search(joined) or _SVC_RE.search(joined)
        entries.append(
            {
                "tx": tx,
                "adapter": m.group(1) if m else None,
                "operation": c[i_op] if i_op is not None and i_op < len(c) else "",
                "obs": c[i_obs] if i_obs is not None and i_obs < len(c) else "",
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
            tx_map.setdefault(e["tx"], {  # primera aparicion gana (dedupe)
                "adapter": e["adapter"],
                "operation": e["operation"],
                "obs": e["obs"],
            })
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
    # guardia de sanitizacion: jamas cookies/curl/bodies en el JSON
    dumped = json.dumps(data, ensure_ascii=False)
    for forbidden in ("Cookie", "curl ", "--header", "transactionId"):
        if forbidden in dumped:
            raise SystemExit(f"ERROR sanitizacion: '{forbidden}' se colo en el JSON")
    return data


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
