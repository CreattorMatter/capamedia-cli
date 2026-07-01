"""Loader del catalogo de Discovery Ola 2.

El catalogo (`data/catalog/ola2_entrega1.json`) se genera desde el `.numbers` del
banco con `tools/build_ola2_catalog.py`. Aqui SOLO se lee el JSON (el CLI en runtime
no depende de `numbers-parser`). Da al analisis de orquestadores el mapa REAL
orquestador->downstream + la ficha de cada servicio, en vez de adivinarlos desde el
ESQL.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "catalog" / "ola2_entrega1.json"
)
_NAME_RE = re.compile(r"(?i)^(ws|orq)([a-z]+?)(\d{3,4})$")


def _canon(name: str) -> str:
    """Nombre canonico para consultar sin importar el case: `wsclientes0047` ->
    `WSClientes0047`. Deja intacto lo que no matchea el patron WS*/ORQ*."""
    s = (name or "").strip()
    m = _NAME_RE.match(s)
    if not m:
        return s
    return f"{m.group(1).upper()}{m.group(2).capitalize()}{m.group(3)}"


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """Carga el catalogo Ola 2 (cacheado). Estructura vacia si el JSON no existe."""
    if not _CATALOG_PATH.exists():
        return {"meta": {}, "orchestrators": [], "services": {}}
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def get_service(name: str) -> dict[str, Any] | None:
    """Entrada completa de un servicio (base + discovery + downstreams), o None."""
    return load_catalog()["services"].get(_canon(name))


def is_known(name: str) -> bool:
    """True si el servicio esta en el catalogo Ola 2."""
    return _canon(name) in load_catalog()["services"]


def list_orchestrators() -> list[str]:
    """Nombres de los orquestadores del catalogo."""
    return list(load_catalog()["orchestrators"])


def is_orchestrator(name: str) -> bool:
    """True si el servicio es un orquestador conocido."""
    return _canon(name) in load_catalog()["orchestrators"]


def get_downstreams(orchestrator: str) -> list[dict[str, Any]]:
    """Downstreams de un orquestador: lista de `{service, in_discovery, in_ola1}`.
    Vacia si el servicio no es orquestador o no esta en el catalogo."""
    svc = get_service(orchestrator)
    return list(svc.get("downstreams", [])) if svc else []


def get_discovery(name: str) -> dict[str, Any] | None:
    """Ficha de discovery (34 campos: tribu, tecnologia, metodos, links, ...) o None."""
    svc = get_service(name)
    return svc.get("discovery") if svc else None
