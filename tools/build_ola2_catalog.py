"""Genera el catalogo Ola 2 (JSON) desde el .numbers de Discovery del banco.

DEV-ONLY: requiere `numbers-parser` (no es dependencia del CLI en runtime; el CLI
solo lee el JSON generado). Reproducible: correr de nuevo cuando el banco actualice
el .numbers.

    python tools/build_ola2_catalog.py \
        tools/ola2/servicios-ola2.numbers \
        src/capamedia_cli/data/catalog/ola2.json

Estrategia deliberada (leccion del Check 5.13): NO se parsea el texto libre de la
columna "Integraciones / Consume" con un mini-parser fragil. El mapa
orquestador->downstream sale de la TABLA DE RELACIONES ya extraida a mano en la
hoja "Servicios"; del texto libre solo se extraen codigos `WS*/ORQ*` con un regex
simple (complemento) y se conserva el crudo para el humano/LLM.
"""

from __future__ import annotations

import json
import re
import sys

from numbers_parser import Document  # dev-only

_CODE_RE = re.compile(r"\b((?:WS|ORQ)[A-Za-z]+\d{3,4})\b")
_NAME_RE = re.compile(r"(?i)^(ws|orq)([a-z]+?)(\d{3,4})$")
_COMPLEXITIES = {"alta", "media", "baja"}

# Nombre canonico: `WSclientes0047` -> `WSClientes0047`, `orqproductos0015` -> `ORQProductos0015`.
def canon(name: str) -> str:
    s = (name or "").strip()
    m = _NAME_RE.match(s)
    if not m:
        return s
    # Preserva el camelCase interno (WSCuentaCorriente0033 -> igual); solo normaliza
    # el prefijo (WS/ORQ) y la inicial. `.capitalize()` destruiria el camelCase.
    mid = m.group(2)
    return f"{m.group(1).upper()}{mid[:1].upper()}{mid[1:]}{m.group(3)}"


def truthy(v: str) -> bool:
    return str(v).strip().lower() in {"sí", "si", "yes", "true", "x", "1"}


def cells(row) -> list[str]:
    return [("" if x is None else str(x).strip()) for x in row]


# Columna de la hoja "Descubrimiento servicios" -> clave del JSON.
_DISCOVERY_KEYMAP = {
    "Servicio": "name_raw",
    "Nuevo nombre": "new_name",
    "Descripción / Funcionalidad": "descripcion",
    "TRIBU": "tribu",
    "ACRONIMO": "acronimo",
    "Tecnologia": "tecnologia",
    "Tipo": "tipo",
    "Estado del análisis": "estado_analisis",
    "Estado del servicio": "estado_servicio",
    "Integraciones / Consume": "integraciones_raw",
    "Tecnologia del backend": "tecnologia_backend",
    "Tecnologia para despliegue de servicio migrado": "tecnologia_despliegue",
    "# Integraciones": "n_integraciones",
    "Protocolos de consumo": "protocolos",
    "# Protocolos": "n_protocolos",
    "Transformaciones de datos": "transformaciones",
    "# de transformaciones": "n_transformaciones",
    "Cache Adicional al config": "cache",
    "Archivo o servicio de donde obtiene informacion para cache": "cache_fuente",
    "Volumen de datos / Request": "volumen_request",
    "Volumen de datos / Response time": "response_time",
    "TPM promedio (rango 2 horas)": "tpm_promedio",
    "TPM hora pico (rango 2 horas)": "tpm_pico",
    "Impacto en otros servicios": "impacto",
    "Tribu consumidor": "tribu_consumidor",
    "Consumidores / Servicios": "consumidores_servicios",
    "Consumidores / Sitios": "consumidores_sitios",
    "# de consumidores": "n_consumidores",
    "Interacción con proveedores externos": "proveedores_externos",
    "Metodos que expone": "metodos_expone",
    "LINK ICEPANEL": "link_icepanel",
    "LINK WSDL": "link_wsdl",
    "LINK CODIGO": "link_codigo",
}


def parse_servicios(rows) -> tuple[dict, list]:
    """Hoja 'Servicios': catalogo base + tabla de relaciones ORQ->downstream."""
    catalog: dict[str, dict] = {}
    relations: list[dict] = []
    mode = "catalog"
    for row in rows[2:]:  # saltar header vacio (0) + header real (1)
        c = cells(row)
        if len(c) < 2:
            continue
        if c[0].lower() == "nombre" and len(c) > 1 and c[1].lower() == "servicios":
            mode = "relations"  # header de la sub-tabla: [orquestador, downstream, obs, OLA1]
            continue
        if mode == "catalog":
            if not c[1] or c[0].lower() not in _COMPLEXITIES:
                continue
            name = canon(c[1])
            catalog[name] = {
                "name": name,
                "complexity": c[0],
                "legacy_type": c[2] if len(c) > 2 else "",
                "responsable": c[3] if len(c) > 3 else "",
                "tramas": truthy(c[5]) if len(c) > 5 else False,
                "casos_uso": truthy(c[6]) if len(c) > 6 else False,
                "new_name": c[7] if len(c) > 7 else "",
            }
        else:  # relations: [orquestador, downstream, observacion, OLA1]
            if not c[1]:
                continue
            obs = c[2] if len(c) > 2 else ""
            relations.append(
                {
                    "orchestrator": canon(c[0]),
                    "downstream": canon(c[1]),
                    "in_discovery": "sí está" in obs.lower() or "si está" in obs.lower(),
                    "in_ola1": truthy(c[3]) if len(c) > 3 else False,
                    "obs": obs,
                }
            )
    return catalog, relations


def parse_descubrimiento(rows) -> dict:
    """Hoja 'Descubrimiento servicios': una ficha de 34 campos por servicio."""
    header = cells(rows[1])
    fichas: dict[str, dict] = {}
    for row in rows[2:]:
        c = cells(row)
        if len(c) < 2 or not c[1]:
            continue
        name = canon(c[1])
        ficha: dict[str, str | list] = {}
        for i, h in enumerate(header):
            key = _DISCOVERY_KEYMAP.get(h)
            if key and i < len(c):
                ficha[key] = c[i]
        integ = str(ficha.get("integraciones_raw", ""))
        ficha["integraciones_codes"] = sorted({canon(x) for x in _CODE_RE.findall(integ)} - {name})
        fichas[name] = ficha
    return fichas


def build(numbers_path: str) -> dict:
    doc = Document(numbers_path)
    sheets = {s.name: s.tables[0].rows(values_only=True) for s in doc.sheets}
    catalog, relations = parse_servicios(sheets["Servicios"])
    discovery = parse_descubrimiento(sheets["Descubrimiento servicios"])

    downs_by_orch: dict[str, list] = {}
    for rel in relations:
        downs_by_orch.setdefault(rel["orchestrator"], []).append(
            {
                "service": rel["downstream"],
                "in_discovery": rel["in_discovery"],
                "in_ola1": rel["in_ola1"],
            }
        )

    if not relations:
        raise SystemExit(
            "ERROR: 0 relaciones orquestador->downstream parseadas. ¿Cambio el header "
            "'nombre'/'servicios' de la sub-tabla en la hoja 'Servicios'?"
        )

    services: dict[str, dict] = {}
    for name in sorted(set(catalog) | set(discovery) | set(downs_by_orch)):
        entry = dict(catalog.get(name, {"name": name}))
        entry.setdefault("name", name)
        if name in discovery:
            entry["discovery"] = discovery[name]
        if name in downs_by_orch:
            entry["downstreams"] = downs_by_orch[name]
        services[name] = entry

    # Filtrar integraciones_codes (regex del texto libre) a los nombres realmente
    # conocidos: descarta codigos espurios capturados de URLs (ej. WSOR845.asmx).
    known = (
        set(services)
        | {r["downstream"] for r in relations}
        | {r["orchestrator"] for r in relations}
    )
    for entry in services.values():
        disc = entry.get("discovery")
        if disc:
            disc["integraciones_codes"] = [
                c for c in disc.get("integraciones_codes", []) if c in known
            ]

    orchestrators = sorted(
        n
        for n, e in services.items()
        if e.get("legacy_type") == "ORQ"
        or e.get("discovery", {}).get("tipo") == "ORQ"
        or n in downs_by_orch
    )
    return {
        "meta": {
            "ola": 2,
            "source": numbers_path.split("/")[-1],
            "n_services": len(services),
            "n_orchestrators": len(orchestrators),
            "n_relations": len(relations),
        },
        "orchestrators": orchestrators,
        "services": services,
    }


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(f"uso: {sys.argv[0]} <input.numbers> <output.json>")
    data = build(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    m = data["meta"]
    print(
        f"OK {sys.argv[2]}: {m['n_services']} servicios, "
        f"{m['n_orchestrators']} orquestadores, {m['n_relations']} relaciones"
    )


if __name__ == "__main__":
    main()
