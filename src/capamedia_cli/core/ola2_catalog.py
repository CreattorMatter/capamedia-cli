"""Loader del catalogo de Discovery Ola 2.

El catalogo (`data/catalog/ola2_entrega1.json`) se genera desde el `.numbers` del
banco con `tools/build_ola2_catalog.py`. Aqui SOLO se lee el JSON (el CLI en runtime
no depende de `numbers-parser`). Da al analisis de orquestadores el mapa REAL
orquestador->downstream + la ficha de cada servicio, en vez de adivinarlos del ESQL.

El catalogo es CONTEXTO, no ARBITRO: aporta la LISTA de downstreams y su metadata,
nunca la semantica mandatory/best-effort (esa sale del `RETURN FALSE` del ESQL).
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
# Prefijo del nombre migrado: `tpr-msa-sp-orqproductos0019` -> `orqproductos0019`.
_MIGRATED_PREFIX_RE = re.compile(r"(?i)^[a-z]{3}-msa-[a-z]{2}-")


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """Carga el catalogo Ola 2 (cacheado). Estructura vacia si el JSON no existe."""
    if not _CATALOG_PATH.exists():
        return {"meta": {}, "orchestrators": [], "services": {}}
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _name_index() -> dict[str, str]:
    """{nombre en minusculas -> key canonico} para lookup robusto al case."""
    return {k.lower(): k for k in load_catalog()["services"]}


def _resolve(name: str) -> str | None:
    """Key del servicio en el catalogo que matchea `name`, o None.

    Robusto al case (compara en minusculas, SIN reconstruir el nombre — asi no
    rompe camelCase interno como `WSCuentaCorriente0033`) y a la forma del nombre
    migrado (pela el prefijo `tpr-msa-sp-`). `ORQProductos0019`, `orqproductos0019`
    y `tpr-msa-sp-orqproductos0019` resuelven todos al mismo servicio.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    idx = _name_index()
    stripped = _MIGRATED_PREFIX_RE.sub("", name.strip())
    for cand in (name.strip().lower(), stripped.lower()):
        if cand in idx:
            return idx[cand]
    return None


def get_service(name: str) -> dict[str, Any] | None:
    """Entrada completa de un servicio (base + discovery + downstreams), o None."""
    key = _resolve(name)
    return load_catalog()["services"].get(key) if key else None


def is_known(name: str) -> bool:
    """True si el servicio esta en el catalogo Ola 2 (en cualquier forma del nombre)."""
    return _resolve(name) is not None


def list_orchestrators() -> list[str]:
    """Nombres canonicos de los orquestadores del catalogo."""
    return list(load_catalog()["orchestrators"])


def is_orchestrator(name: str) -> bool:
    """True si el servicio es un orquestador conocido (robusto al case/forma)."""
    key = _resolve(name)
    return key is not None and key in set(load_catalog()["orchestrators"])


def get_downstreams(orchestrator: str) -> list[dict[str, Any]]:
    """Downstreams de un orquestador: lista de `{service, in_discovery, in_ola1}`.

    Vacia si el servicio no es orquestador o no esta en el catalogo. OJO: `[]` NO
    distingue 'ORQ sin downstreams' de 'ORQ ausente del catalogo' (entrega 2+):
    consultar `is_known()` primero cuando la distincion importe.
    """
    svc = get_service(orchestrator)
    return list(svc.get("downstreams", [])) if svc else []


def get_discovery(name: str) -> dict[str, Any] | None:
    """Ficha de discovery (34 campos: tribu, tecnologia, metodos, links, ...) o None."""
    svc = get_service(name)
    return svc.get("discovery") if svc else None
