"""Resolver de servicios legacy en filesystem local.

Antes de intentar clonar de Azure DevOps, busca el legacy del servicio en
`<capa-media-root>/<NNNN>-<SUF>/legacy/...` con varias estrategias:

  1. `<NNNN>-<SUF>/legacy/_repo/<svc>-aplicacion`  (WAS clasico, mas comun)
  2. `<NNNN>-<SUF>/legacy/_repo/<svc>`              (IIB clonado a mano)
  3. `<NNNN>-<SUF>/legacy/_variants/<prefix>-msa-sp-<svc>`  (gold/migrado)
  4. `<NNNN>/legacy/...`                            (sin sufijo si no hay ambiguedad)
  5. `<NNNN>-<SUF>/legacy/sqb-msa-<svc>`            (clone CLI standar)

El sufijo en el directorio se deduce del nombre del servicio:
  - WSClientes -> WSC
  - WSCuentas -> WSCU
  - WSReglas -> WSR
  - WSTecnicos -> WST
  - WSTarjetas -> WSTa
  - ORQClientes -> ORQ
  - etc.
"""

from __future__ import annotations

import re
from pathlib import Path

# Mapeo prefijo del servicio -> sufijo de carpeta esperado en CapaMedia/
SERVICE_PREFIX_TO_FOLDER_SUFFIX = {
    "wsclientes": "WSC",
    "wscuentas": "WSCU",
    "wsreglas": "WSR",
    "wstecnicos": "WST",
    "wstarjetas": "WSTa",
    "wsproductos": "WSP",
    "wstransferencias": "WSTR",
    "wspagos": "WSPA",
    "orqclientes": "ORQ",
    "orqcuentas": "ORQ",
    "orqreglas": "ORQ",
    "orqtransferencias": "ORQ",
    "orqpagos": "ORQ",
    "orqtecnicos": "ORQ",
}


def _split_service(service: str) -> tuple[str, str]:
    """`WSClientes0010` -> (`wsclientes`, `0010`)"""
    svc_lower = service.lower()
    m = re.match(r"^([a-z]+)(\d{4})$", svc_lower)
    if not m:
        return (svc_lower, "")
    return (m.group(1), m.group(2))


def _candidate_folders(capa_media_root: Path, num: str, suffix_hint: str) -> list[Path]:
    """Lista de carpetas candidatas en CapaMedia/ para un servicio.

    Prioriza la carpeta con el sufijo correcto, despues la sin sufijo, despues
    cualquier `<NNNN>-*` con un solo match.
    """
    candidates: list[Path] = []
    if not capa_media_root.exists():
        return candidates

    # 1. Match exacto con sufijo
    target = capa_media_root / f"{num}-{suffix_hint}"
    if target.exists():
        candidates.append(target)

    # 2. Sin sufijo
    target = capa_media_root / num
    if target.exists():
        candidates.append(target)

    # 3. Cualquier `<num>-*` (fallback)
    for d in capa_media_root.glob(f"{num}-*"):
        if d.is_dir() and d not in candidates:
            candidates.append(d)

    return candidates


def find_local_legacy(
    service: str, capa_media_root: Path, prefer_original: bool = True
) -> Path | None:
    """Busca el legacy del servicio en la estructura local de CapaMedia/.

    Retorna el path al directorio que actua como `legacy_root` para el analisis,
    o None si no encuentra nada.

    Si `prefer_original=True` (default), los `_variants/` (versiones migradas)
    se ignoran — solo se retorna legacy original. Esto fuerza al caller a clonar
    de Azure si el original no esta local. Util para que `batch complexity` no
    tome un variant migrado como si fuera el legacy.
    """
    prefix, num = _split_service(service)
    if not num:
        return None

    suffix_hint = SERVICE_PREFIX_TO_FOLDER_SUFFIX.get(prefix, "")
    svc_lower = service.lower()

    folders = _candidate_folders(capa_media_root, num, suffix_hint)

    for folder in folders:
        # Estrategia 1 (WAS clasico): hay <svc>-aplicacion + <svc>-infraestructura hermanos
        # en legacy/_repo/. Retornar el _repo/ para que el analyzer vea ambos.
        repo_dir = folder / "legacy" / "_repo"
        if repo_dir.exists():
            apl = repo_dir / f"{svc_lower}-aplicacion"
            infra = repo_dir / f"{svc_lower}-infraestructura"
            if apl.exists() or infra.exists():
                return repo_dir

            # Estrategia 2: legacy/_repo/<svc>  (sin -aplicacion/-infraestructura)
            single = repo_dir / svc_lower
            if single.exists() and single.is_dir():
                return single

            # Estrategia 2b (NUEVA v0.3.3): legacy/_repo/ con archivos directos
            # (ej. WSReglas0010.wsdl, com/, pom.xml). Detectar indicios de IIB/WAS legacy.
            has_indicators = (
                any(repo_dir.glob("*.wsdl"))
                or any(repo_dir.glob("*.esql"))
                or (repo_dir / "pom.xml").exists()
                or (repo_dir / "com").exists()
                or (repo_dir / "IBMdefined").exists()
                or any(repo_dir.glob("*.msgflow"))
                or any(repo_dir.rglob("**/web.xml"))
            )
            if has_indicators:
                return repo_dir

        # Estrategia 3: legacy/_variants/*<svc>* (variant migrado, solo si prefer_original=False)
        if not prefer_original:
            variants_dir = folder / "legacy" / "_variants"
            if variants_dir.exists():
                for variant in variants_dir.iterdir():
                    if variant.is_dir() and svc_lower in variant.name.lower():
                        return variant

        # Estrategia 4: legacy/sqb-msa-<svc>  (clone CLI standar)
        candidate = folder / "legacy" / f"sqb-msa-{svc_lower}"
        if candidate.exists() and candidate.is_dir():
            return candidate

        # Estrategia 5: legacy/  (a veces el legacy esta directo, sin subdir)
        legacy_dir = folder / "legacy"
        if legacy_dir.exists() and legacy_dir.is_dir():
            has_indicators = (
                any(legacy_dir.glob("*.wsdl"))
                or any(legacy_dir.glob("*.esql"))
                or any(legacy_dir.glob("*-aplicacion"))
                or any(legacy_dir.glob("**/web.xml"))
            )
            if has_indicators:
                return legacy_dir

    return None
