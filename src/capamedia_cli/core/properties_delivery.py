"""Properties delivery audit (v0.21.0).

Despues de que `capamedia clone` detecta los `.properties` PENDING_FROM_BANK
en `.capamedia/properties-report.yaml`, este modulo chequea si el owner del
servicio ya entrego los archivos, y opcionalmente inyecta los valores
literales al `application.yml` del proyecto migrado.

Convencion oficial de carpeta:

    <workspace>/.capamedia/inputs/<archivo>.properties

Como `.capamedia/` esta gitignored, los archivos no se filtran al repo del
banco. El cascade de busqueda tolera variantes (raiz del workspace, carpeta
`inputs/` sin `.capamedia/`, samples inline en `legacy/`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

DeliveryStatus = Literal["DELIVERED", "PARTIAL", "STILL_PENDING", "NOT_PENDING"]


@dataclass
class PropertyFileDelivery:
    """Estado de entrega de un archivo `.properties` del reporte de clone."""

    file_name: str                           # "umpclientes0025.properties"
    status: DeliveryStatus
    keys_declared: list[str] = field(default_factory=list)  # segun properties-report.yaml
    keys_delivered: list[str] = field(default_factory=list) # efectivamente en el archivo
    keys_missing: list[str] = field(default_factory=list)   # declared - delivered
    delivered_path: Path | None = None       # donde se encontro el archivo
    values: dict[str, str] = field(default_factory=dict)    # key -> value literal
    source_hint: str = ""                    # copia del report (ump:xxx | service)


@dataclass
class DeliveryAudit:
    """Resultado del audit sobre el workspace completo."""

    workspace: Path
    files: list[PropertyFileDelivery] = field(default_factory=list)
    report_missing: bool = False  # properties-report.yaml no existe

    @property
    def has_pending(self) -> bool:
        return any(f.status in ("STILL_PENDING", "PARTIAL") for f in self.files)

    @property
    def has_delivered(self) -> bool:
        return any(f.status == "DELIVERED" for f in self.files)


# ---------------------------------------------------------------------------
# Busqueda en cascada
# ---------------------------------------------------------------------------


def _candidate_paths(workspace: Path, file_name: str) -> list[Path]:
    """Ubicaciones donde buscar el archivo .properties, en orden de prioridad."""
    lower_name = file_name.lower()
    return [
        workspace / ".capamedia" / "inputs" / file_name,            # convencion oficial
        workspace / "inputs" / file_name,                           # sin .capamedia/
        workspace / file_name,                                      # raiz workspace
        # Case-insensitive fallback: glob con todos los casos posibles
        *(p for p in (workspace / ".capamedia" / "inputs").glob("*.properties")
          if p.name.lower() == lower_name),
        *(p for p in workspace.glob("*.properties") if p.name.lower() == lower_name),
    ]


def _find_delivered_file(workspace: Path, file_name: str) -> Path | None:
    """Busca el archivo .properties en el cascade. Retorna el primer match real."""
    for candidate in _candidate_paths(workspace, file_name):
        if candidate.exists() and candidate.is_file():
            return candidate
    # Ultimo recurso: busqueda recursiva en legacy/ por si el owner lo dejo
    # como sample inline (improbable pero barato)
    legacy_root = workspace / "legacy"
    if legacy_root.is_dir():
        for p in legacy_root.rglob(file_name):
            if p.is_file():
                return p
    return None


def _parse_properties_file(path: Path) -> dict[str, str]:
    """Parsea un archivo .properties y devuelve el dict key -> value."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
        elif ":" in line:
            key, _, value = line.partition(":")
        else:
            continue
        values[key.strip()] = value.strip()
    return values


# ---------------------------------------------------------------------------
# Audit principal
# ---------------------------------------------------------------------------


def audit_properties_delivery(workspace: Path) -> DeliveryAudit:
    """Lee `.capamedia/properties-report.yaml` y chequea entrega de cada archivo.

    Para cada entry con `status=PENDING_FROM_BANK` en el reporte de clone:
      1. Busca el archivo en ubicaciones cascade.
      2. Si lo encuentra: parsea keys, compara con `keys_used` del reporte.
      3. Clasifica: DELIVERED (todas), PARTIAL (faltan), STILL_PENDING (no hay archivo).

    Entries con status `SHARED_CATALOG` o `SAMPLE_IN_REPO` se marcan NOT_PENDING
    (no aplica audit).
    """
    audit = DeliveryAudit(workspace=workspace)
    report_path = workspace / ".capamedia" / "properties-report.yaml"

    if not report_path.is_file():
        audit.report_missing = True
        return audit

    try:
        data = yaml.safe_load(report_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        audit.report_missing = True
        return audit

    if not isinstance(data, dict):
        return audit

    specific = data.get("service_specific_properties") or []
    if not isinstance(specific, list):
        return audit

    for entry in specific:
        if not isinstance(entry, dict):
            continue
        file_name = str(entry.get("file") or "")
        if not file_name:
            continue

        entry_status = str(entry.get("status") or "")
        keys_declared = list(entry.get("keys_used") or [])
        source_hint = str(entry.get("source") or "")

        if entry_status != "PENDING_FROM_BANK":
            # Ya estaba resuelto desde el clone (SAMPLE_IN_REPO / SHARED_CATALOG)
            audit.files.append(
                PropertyFileDelivery(
                    file_name=file_name,
                    status="NOT_PENDING",
                    keys_declared=keys_declared,
                    source_hint=source_hint,
                )
            )
            continue

        found = _find_delivered_file(workspace, file_name)
        if found is None:
            audit.files.append(
                PropertyFileDelivery(
                    file_name=file_name,
                    status="STILL_PENDING",
                    keys_declared=keys_declared,
                    source_hint=source_hint,
                )
            )
            continue

        values = _parse_properties_file(found)
        delivered_keys = list(values.keys())
        missing = [k for k in keys_declared if k not in values]

        status: DeliveryStatus = "PARTIAL" if missing else "DELIVERED"

        audit.files.append(
            PropertyFileDelivery(
                file_name=file_name,
                status=status,
                keys_declared=keys_declared,
                keys_delivered=delivered_keys,
                keys_missing=missing,
                delivered_path=found,
                values=values,
                source_hint=source_hint,
            )
        )

    return audit


# ---------------------------------------------------------------------------
# Autofix - inyectar valores al application.yml
# ---------------------------------------------------------------------------


# Mapping LEGACY_KEY -> (CCC_env_var_posibles). Las CCC_ son las que el agente
# /migrate suele poner como placeholder cuando no hay valor disponible.
_KEY_TO_CCC_VARIANTS: dict[str, list[str]] = {
    "URL_XML": ["CCC_TX_ATTRIBUTES_XML_PATH", "CCC_URL_XML", "CCC_XML_PATH"],
    "RECURSO": ["CCC_TX_ATTRIBUTES_RESOURCE", "CCC_RECURSO", "CCC_RESOURCE"],
    "RECURSO_01": ["CCC_TX_ATTRIBUTES_RESOURCE_01", "CCC_RECURSO_01"],
    "RECURSO2": ["CCC_TX_ATTRIBUTES_RESOURCE_02", "CCC_RECURSO_02"],
    "COMPONENTE": ["CCC_TX_ATTRIBUTES_COMPONENT", "CCC_COMPONENTE"],
    "COMPONENTE_01": ["CCC_TX_ATTRIBUTES_COMPONENT_01", "CCC_COMPONENTE_01"],
    "COMPONENTE2": ["CCC_TX_ATTRIBUTES_COMPONENT_02", "CCC_COMPONENTE_02"],
    "GRUPO_CENTRALIZADA": ["CCC_GRUPO_CENTRALIZADA"],
    "UNIDAD_PERSISTENCIA": ["CCC_UNIDAD_PERSISTENCIA", "CCC_PERSISTENCE_UNIT"],
    "COD_DATOS_VACIOS": ["CCC_COD_DATOS_VACIOS", "CCC_EMPTY_DATA_CODE"],
    "DES_DATOS_VACIOS": ["CCC_DES_DATOS_VACIOS", "CCC_EMPTY_DATA_MESSAGE"],
}


def _find_application_yml(project_path: Path) -> list[Path]:
    """Encuentra application.yml, application-*.yml bajo src/main/resources/."""
    resources = project_path / "src" / "main" / "resources"
    if not resources.is_dir():
        return []
    yml_files: list[Path] = []
    for pattern in ("application.yml", "application-*.yml"):
        yml_files.extend(resources.glob(pattern))
    return yml_files


@dataclass
class InjectReport:
    """Resultado del autofix de inject properties -> application.yml."""

    files_modified: list[Path] = field(default_factory=list)
    replacements: list[str] = field(default_factory=list)  # human-readable log

    @property
    def total_replacements(self) -> int:
        return len(self.replacements)


def inject_delivered_properties(
    audit: DeliveryAudit,
    project_path: Path,
) -> InjectReport:
    """Para cada DELIVERED en el audit, reemplaza `${CCC_*}` en application.yml
    por el valor literal. Solo modifica placeholders — no toca valores ya seteados.

    Solo se ejecuta sobre archivos con status `DELIVERED`. Los `PARTIAL` se
    saltean (para evitar mezclar valores reales con placeholders residuales).
    """
    report = InjectReport()

    yml_files = _find_application_yml(project_path)
    if not yml_files:
        return report

    # Acumular todos los (key_legacy -> valor) de los archivos delivered
    legacy_to_value: dict[str, str] = {}
    for pf in audit.files:
        if pf.status != "DELIVERED":
            continue
        legacy_to_value.update(pf.values)

    if not legacy_to_value:
        return report

    # Por cada yml, reemplazar los ${CCC_*} conocidos por el valor literal
    for yml in yml_files:
        try:
            text = yml.read_text(encoding="utf-8")
        except OSError:
            continue

        original = text
        for legacy_key, value in legacy_to_value.items():
            ccc_variants = _KEY_TO_CCC_VARIANTS.get(legacy_key, [])
            if not ccc_variants:
                continue
            for ccc in ccc_variants:
                # ${CCC_X} o ${CCC_X:default}
                pattern = re.compile(
                    rf"\$\{{{re.escape(ccc)}(?::[^}}]*)?\}}",
                )
                matches = list(pattern.finditer(text))
                if not matches:
                    continue
                # Escapar comillas en el valor para YAML
                safe_value = value.replace("\\", "\\\\").replace('"', '\\"')
                replacement = f'"{safe_value}"'
                text = pattern.sub(replacement, text)
                report.replacements.append(
                    f"{yml.name}: ${{{ccc}}} -> \"{value}\" "
                    f"(desde {legacy_key})"
                )

        if text != original:
            yml.write_text(text, encoding="utf-8")
            report.files_modified.append(yml)

    return report
