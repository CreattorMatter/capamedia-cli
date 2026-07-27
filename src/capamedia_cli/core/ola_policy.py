"""Politica OLA: que servicios pertenecen a OLA 2 y que version de
`lib-bnc-api-client` corresponde a cada uno.

Contexto (plan de comunicacion de librerias del Adaptador BANCS, 2026-05):

- `lib-bnc-api-client:1.1.0` es la linea base de **OLA 1**.
- `lib-bnc-api-client:2.0.0` es la linea base **obligatoria desde OLA 2**
  (disponible 2026-05-25; suma soporte de token y transacciones financieras).

Un servicio usa `2.0.0` si y solo si esta en `OLA2_SERVICES`. Cualquier otro
servicio usa `1.1.0`.

`OLA2_SERVICES` es la lista oficial del banco — hoja "Servicios" del archivo
`Servicios ola 2 entrega 1`. Para agregar una entrega futura, sumar los
nombres normalizados (minusculas, sin prefijos de repo) a `OLA2_SERVICES`.
"""

from __future__ import annotations

import re

# Namespaces de catalogo del banco (prefijo del repo migrado
# `<ns>-msa-sp-<servicio>`). FUENTE UNICA: la elige el usuario en
# `capamedia fabrics generate` y de ahi salen el `projectName`, la deteccion de
# repos migrados en `clone`/`adopt` y el `_infer_repo_name` de bank_autofix.
#
# Historial: la lista estaba duplicada en 4 modulos y divergio — `tmi` (v0.30.1)
# se agrego solo al prompt de fabrics, asi que un `tmi-msa-sp-*` no lo detectaba
# ni `clone --migrated` ni `adopt`. Al sumar un namespace nuevo, tocar SOLO esta
# constante; el test test_namespace_options_single_source lo verifica.
BANK_NAMESPACES: tuple[str, ...] = (
    "tnd",
    "tpr",
    "csg",
    "tmp",
    "tia",
    "tct",
    "tmi",
    "taa",
)

# Versiones de lib-bnc-api-client por OLA.
LIB_BNC_API_CLIENT_OLA1 = "1.1.0"
LIB_BNC_API_CLIENT_OLA2 = "2.0.0"

# Servicios OLA 2 — entrega 1 (25). Nombres normalizados a minusculas.
# Fuente: xlsx oficial `Servicios ola 2 entrega 1`, hoja "Servicios".
OLA2_SERVICES: frozenset[str] = frozenset(
    {
        # ORQ (5)
        "orqproductos0015",
        "orqproductos0019",
        "orqproductos0044",
        "orqproductos0052",
        "orqproductos0061",
        # WSClientes (7)
        "wsclientes0042",
        "wsclientes0043",
        "wsclientes0044",
        "wsclientes0047",
        "wsclientes0068",
        "wsclientes0097",
        "wsclientes0106",
        # WSProductos (10)
        "wsproductos0033",
        "wsproductos0039",
        "wsproductos0040",
        "wsproductos0041",
        "wsproductos0044",
        "wsproductos0056",
        "wsproductos0081",
        "wsproductos0101",
        "wsproductos0102",
        "wsproductos0163",
        # WSSeguridad (1)
        "wsseguridad0028",
        # WSTecnicos (2)
        "wstecnicos0011",
        "wstecnicos0082",
    }
)

# Token de servicio dentro de un nombre de repo/carpeta/spring.application.name.
# Ej: `tnd-msa-sp-wsclientes0011` -> `wsclientes0011`.
_SERVICE_TOKEN_RE = re.compile(r"\b(?:ws|orq)[a-z]+\d{3,}", re.IGNORECASE)


def normalize_service(service: str | None) -> str:
    """Normaliza un nombre de servicio a la forma usada en `OLA2_SERVICES`.

    Acepta nombres con prefijos/sufijos de repo y extrae el token de servicio:
      - `tnd-msa-sp-wsclientes0011` -> `wsclientes0011`
      - `sqb-msa-orqproductos0015`  -> `orqproductos0015`
      - `WSClientes0011`            -> `wsclientes0011`
    Si no encuentra un token reconocible, devuelve el input en minusculas.
    """
    raw = (service or "").strip().lower()
    if not raw:
        return ""
    match = _SERVICE_TOKEN_RE.search(raw)
    return match.group(0) if match else raw


def is_ola2(service: str | None) -> bool:
    """True si el servicio pertenece a OLA 2 (entrega vigente)."""
    return normalize_service(service) in OLA2_SERVICES


def lib_bnc_api_client_version(service: str | None) -> str:
    """Version de `lib-bnc-api-client` que corresponde al OLA del servicio.

    OLA 2 -> `2.0.0`; cualquier otro servicio -> `1.1.0`.
    """
    return LIB_BNC_API_CLIENT_OLA2 if is_ola2(service) else LIB_BNC_API_CLIENT_OLA1


def ola_label(service: str | None) -> str:
    """Etiqueta legible del OLA del servicio: `OLA 2` o `OLA 1`."""
    return "OLA 2" if is_ola2(service) else "OLA 1"
