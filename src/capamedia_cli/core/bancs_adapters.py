"""Loader del catalogo de adaptadores BANCS (Core Adapter).

El catalogo (`data/catalog/bancs_adapters.json`) se genera desde el .numbers de
relevamiento del banco con `tools/build_bancs_adapters.py` (dev-only). Mapea cada
TX BANCS (`0NNNNN`) al adaptador del Core Adapter que la sirve, con sus URLs
(dev/test externas + interna pod-a-pod). Relevado para OLA 2; los adaptadores
sirven para cualquier ola.

Es CONTEXTO, no ARBITRO: la URL real de cada ambiente va SIEMPRE via `${CCC_*}`
env vars (regla del banco); estas URLs son referenciales de dev/test.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "catalog" / "bancs_adapters.json"
)
_TX_RE = re.compile(r"(?i)^(?:T(?:RX|X))?\s*(\d{1,6})$")


def _norm_tx(tx: str) -> str | None:
    """Normaliza una TX a 6 digitos: acepta `060480`, `TX060480`, `TRX 60480`,
    `60480` (zero-pad). None si no parece una TX."""
    if not isinstance(tx, str):
        return None
    m = _TX_RE.match(tx.strip())
    return m.group(1).zfill(6) if m else None


@lru_cache(maxsize=1)
def load_adapters_catalog() -> dict[str, Any]:
    """Carga el catalogo de adaptadores (cacheado). Vacio si el JSON no existe."""
    if not _CATALOG_PATH.exists():
        return {"meta": {}, "adapters": {}, "tx_map": {}}
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def list_adapters() -> list[dict[str, Any]]:
    """Todos los adaptadores relevados (name, url_dev, url_test, url_internal)."""
    return list(load_adapters_catalog()["adapters"].values())


def get_adapter(name: str) -> dict[str, Any] | None:
    """Entrada de un adaptador por nombre exacto, o None."""
    return load_adapters_catalog()["adapters"].get((name or "").strip())


def get_adapter_for_tx(tx: str) -> dict[str, Any] | None:
    """Adaptador que sirve una TX: `{tx, adapter, operation, obs, url_internal,
    url_dev, url_test}` o None si la TX no esta relevada."""
    cat = load_adapters_catalog()
    norm = _norm_tx(tx)
    entry = cat["tx_map"].get(norm) if norm else None
    if not entry:
        return None
    adapter = cat["adapters"].get(entry["adapter"], {})
    return {
        "tx": norm,
        "adapter": entry["adapter"],
        "operation": entry.get("operation", ""),
        "obs": entry.get("obs", ""),
        "url_internal": adapter.get("url_internal", ""),
        "url_dev": adapter.get("url_dev", ""),
        "url_test": adapter.get("url_test", ""),
    }


def known_tx_codes() -> list[str]:
    """Todas las TX relevadas (6 digitos, ordenadas)."""
    return sorted(load_adapters_catalog()["tx_map"])
