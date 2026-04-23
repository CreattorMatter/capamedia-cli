"""Discovery workbook ingestion and dependency inventory.

This module powers `capamedia discovery <name> <excel>`.
It reads the bank Discovery workbook, clones the relevant repositories when
requested, enriches dependencies by scanning cloned sources, and writes an
internal workbook report.
"""

from __future__ import annotations

import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from capamedia_cli.commands.clone import _git_clone

RepoKind = Literal["service", "ump", "tx"]
CloneStatus = Literal["pending", "cloned", "already_exists", "skipped", "failed"]

SERVICE_RE = re.compile(r"\b(?:WS|ORQ)[A-Za-z]+\d{4}\b", re.IGNORECASE)
UMP_RE = re.compile(r"\bUMP[A-Za-z]+\d{4}\b", re.IGNORECASE)
TX_RE = re.compile(r"\bTX\s*0?([0-9]{6})\b|\b(?<!\d)(0[0-9]{5})(?!\d)\b", re.IGNORECASE)
JNDI_RE = re.compile(r"\b(?:jndi|jdni|jdint)\.[A-Za-z0-9_.-]+\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://([^/\"'\s,;)]+)", re.IGNORECASE)
DB_HINT_RE = re.compile(r"\b(?:BDD|DB|ESQUEMA|SCHEMA)\s*[:=]\s*([^/\n\t\r]+)", re.IGNORECASE)
PROPERTY_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*[:=]\s*(.*?)\s*$")
SECRET_KEY_RE = re.compile(r"(password|passwd|pwd|secret|token|apikey|api-key|user|usuario|credential|key)", re.IGNORECASE)
BANK_DOMAIN_RE = re.compile(r"(bpichincha|pichincha\.com|bancsubsider|dev\.azure\.com)", re.IGNORECASE)
INTERNAL_DOMAIN_RE = re.compile(r"^(localhost|127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)")

TEXT_SUFFIXES = {
    ".bat",
    ".cmd",
    ".conf",
    ".config",
    ".esql",
    ".java",
    ".json",
    ".msgflow",
    ".properties",
    ".sh",
    ".subflow",
    ".txt",
    ".wsdl",
    ".xml",
    ".xsd",
    ".yaml",
    ".yml",
}

DISCOVERY_HEADERS = [
    "Servicios",
    "Responsable",
    "Complejidad",
    "Observaciones",
    "Observación Discovery",
    "LINK WSDL",
    "LINK CODIGO",
    "# Integraciones",
    "Integraciones / Consume",
    "Nuevo nombre",
    "Descripción / Funcionalidad",
    "TRIBU",
    "ACRONIMO",
    "Tecnologia",
    "Tipo",
    "Tecnologia del backend",
    "Tecnologia para despliegue de servicio migrado",
    "Protocolos de consumo",
    "Cache Adicional al config",
    "Archivo o servicio de donde obtiene informacion para cache",
    "Interacción con proveedores externos",
    "Metodos que expone",
    "OLA",
    "Consumen tecnologia deprecada",
]


@dataclass
class DiscoveryRow:
    """One normalized row from the Discovery sheet."""

    row_number: int
    service: str
    responsible: str = ""
    complexity: str = ""
    observations: str = ""
    discovery_observation: str = ""
    wsdl_link: str = ""
    code_link: str = ""
    integrations_count: str = ""
    integrations: str = ""
    migration_repo: str = ""
    description: str = ""
    tribe: str = ""
    acronym: str = ""
    technology: str = ""
    kind: str = ""
    backend_technology: str = ""
    deploy_technology: str = ""
    protocols: str = ""
    cache: str = ""
    cache_source: str = ""
    external_interaction: str = ""
    exposed_methods: str = ""
    wave: str = ""
    deprecated_technology: str = ""
    legacy_repo: str = ""
    legacy_repo_inferred: bool = False
    excel_umps: set[str] = field(default_factory=set)
    excel_txs: set[str] = field(default_factory=set)
    excel_downstream_services: set[str] = field(default_factory=set)
    excel_jndi: set[str] = field(default_factory=set)
    excel_db_hints: set[str] = field(default_factory=set)
    excel_external_domains: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class RepoTask:
    """A repository that discovery may clone or inspect."""

    kind: RepoKind
    name: str
    repo_name: str
    project_key: str
    dest: Path
    source: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.project_key, self.repo_name.lower())


@dataclass
class RepoResult:
    """Clone/inspection status for a repository."""

    kind: RepoKind
    name: str
    repo_name: str
    project_key: str
    dest: Path
    status: CloneStatus
    detail: str = ""
    source: str = ""


@dataclass
class RepoScan:
    """Dependency facts found by scanning a cloned repository."""

    repo_name: str
    path: Path
    umps: set[str] = field(default_factory=set)
    txs: set[str] = field(default_factory=set)
    services: set[str] = field(default_factory=set)
    jndi: set[str] = field(default_factory=set)
    property_files: set[str] = field(default_factory=set)
    property_keys: set[str] = field(default_factory=set)
    secret_keys: set[str] = field(default_factory=set)
    external_domains: set[str] = field(default_factory=set)
    config_files: set[str] = field(default_factory=set)


@dataclass
class DiscoveryResult:
    """Full result returned by `run_discovery`."""

    name: str
    source_excel: Path
    sheet_name: str
    output_dir: Path
    report_path: Path
    rows: list[DiscoveryRow]
    repo_results: list[RepoResult]
    scans: dict[str, RepoScan]
    dependencies: list[dict[str, str]]
    caveats: list[dict[str, str]]


def _norm_header(value: object) -> str:
    raw = str(value or "").strip().lower()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
    }
    for src, dest in replacements.items():
        raw = raw.replace(src, dest)
    return re.sub(r"\s+", " ", raw)


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _canonical_service(value: str) -> str:
    raw = value.strip()
    match = re.match(r"^(WS|ORQ)([A-Za-z]+)(\d{4})$", raw, re.IGNORECASE)
    if not match:
        return raw
    prefix, domain, number = match.groups()
    normalized_prefix = prefix.upper()
    normalized_domain = domain[:1].upper() + domain[1:].lower()
    return f"{normalized_prefix}{normalized_domain}{number}"


def _canonical_ump(value: str) -> str:
    raw = value.strip()
    match = re.match(r"^(UMP)([A-Za-z]+)(\d{4})$", raw, re.IGNORECASE)
    if not match:
        return raw
    prefix, domain, number = match.groups()
    return f"{prefix.upper()}{domain[:1].upper()}{domain[1:].lower()}{number}"


def _canonical_tx(value: str) -> str:
    return value.strip().zfill(6)


def _looks_like_date(value: str) -> bool:
    return bool(re.match(r"^20\d{4}$", value))


def _extract_txs(text: str) -> set[str]:
    txs: set[str] = set()
    for match in TX_RE.finditer(text or ""):
        raw = match.group(1) or match.group(2)
        if raw and not _looks_like_date(raw):
            txs.add(_canonical_tx(raw))
    return txs


def _extract_external_domains(text: str) -> set[str]:
    domains: set[str] = set()
    for match in URL_RE.finditer(text or ""):
        domain = match.group(1).strip().lower()
        if not domain:
            continue
        if BANK_DOMAIN_RE.search(domain) or INTERNAL_DOMAIN_RE.search(domain):
            continue
        domains.add(domain)
    return domains


def _extract_db_hints(text: str) -> set[str]:
    hints: set[str] = set()
    for match in DB_HINT_RE.finditer(text or ""):
        hint = re.sub(r"\s+", " ", match.group(1).strip(" /:-"))
        if hint and hint.lower() not in {"ninguna", "ninguno", "no aplica"}:
            hints.add(hint[:120])
    return hints


def _repo_from_link(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered.startswith("no se encuentra") or lowered in {"no", "ninguno", "ninguna"}:
        return ""
    if "_git/" in value:
        tail = unquote(value.split("_git/", 1)[1]).strip()
        return re.split(r"\s+|[?#]", tail, maxsplit=1)[0].strip(" /")
    match = re.search(r"\b((?:sqb|ws|ms|tnd|tia|tpr|csg|tmp)-[A-Za-z0-9_.-]+)\b", value, re.IGNORECASE)
    return match.group(1) if match else ""


def infer_legacy_repo(service: str, technology: str = "") -> tuple[str, str]:
    """Infer the most likely Azure project key and repository name for a service."""
    svc = service.lower()
    tech = technology.lower()
    if "was" in tech:
        return ("was", f"ws-{svc}-was")
    return ("bus", f"sqb-msa-{svc}")


def project_key_for_repo(repo_name: str, fallback: str = "bus") -> str:
    repo = repo_name.lower()
    if repo.startswith("sqb-cfg-"):
        return "config"
    if (repo.startswith("ws-") or repo.startswith("ms-")) and repo.endswith("-was"):
        return "was"
    return fallback


def choose_discovery_sheet(workbook_path: Path, sheet_name: str | None = None) -> str:
    wb = load_workbook(workbook_path, read_only=True, data_only=True)
    if sheet_name:
        if sheet_name not in wb.sheetnames:
            available = ", ".join(wb.sheetnames)
            raise ValueError(f"la hoja '{sheet_name}' no existe. Hojas disponibles: {available}")
        return sheet_name
    if "Discovery" in wb.sheetnames:
        return "Discovery"
    if len(wb.sheetnames) == 1:
        return wb.sheetnames[0]
    available = ", ".join(wb.sheetnames)
    raise ValueError(f"no encontre hoja 'Discovery'. Hojas disponibles: {available}")


def read_discovery_rows(workbook_path: Path, sheet_name: str | None = None) -> tuple[str, list[DiscoveryRow]]:
    """Read Discovery rows from an Excel workbook."""
    selected_sheet = choose_discovery_sheet(workbook_path, sheet_name)
    wb = load_workbook(workbook_path, read_only=True, data_only=True)
    ws = wb[selected_sheet]
    headers = [_cell_text(ws.cell(1, c).value) for c in range(1, ws.max_column + 1)]
    header_index = {_norm_header(header): i + 1 for i, header in enumerate(headers) if header}

    def get(row: int, header: str) -> str:
        idx = header_index.get(_norm_header(header))
        if not idx:
            return ""
        return _cell_text(ws.cell(row, idx).value)

    service_header = header_index.get(_norm_header("Servicios")) or header_index.get(_norm_header("Servicio"))
    if not service_header:
        raise ValueError("el Excel no tiene columna 'Servicios'")

    rows: list[DiscoveryRow] = []
    for row_number in range(2, ws.max_row + 1):
        service = _canonical_service(_cell_text(ws.cell(row_number, service_header).value))
        if not service:
            continue

        all_text = " / ".join(_cell_text(ws.cell(row_number, c).value) for c in range(1, ws.max_column + 1))
        integrations = get(row_number, "Integraciones / Consume")
        cache_source = get(row_number, "Archivo o servicio de donde obtiene informacion para cache")
        downstream_source = f"{integrations}\n{cache_source}"
        repo = _repo_from_link(get(row_number, "LINK CODIGO"))
        inferred = False
        if not repo:
            _, repo = infer_legacy_repo(service, get(row_number, "Tecnologia"))
            inferred = True

        downstream = {
            s
            for s in SERVICE_RE.findall(downstream_source)
            if s.lower() != service.lower()
        }

        rows.append(
            DiscoveryRow(
                row_number=row_number,
                service=service,
                responsible=get(row_number, "Responsable"),
                complexity=get(row_number, "Complejidad"),
                observations=get(row_number, "Observaciones"),
                discovery_observation=get(row_number, "Observación Discovery"),
                wsdl_link=get(row_number, "LINK WSDL"),
                code_link=get(row_number, "LINK CODIGO"),
                integrations_count=get(row_number, "# Integraciones"),
                integrations=integrations,
                migration_repo=get(row_number, "Nuevo nombre"),
                description=get(row_number, "Descripción / Funcionalidad"),
                tribe=get(row_number, "TRIBU"),
                acronym=get(row_number, "ACRONIMO"),
                technology=get(row_number, "Tecnologia"),
                kind=get(row_number, "Tipo"),
                backend_technology=get(row_number, "Tecnologia del backend"),
                deploy_technology=get(row_number, "Tecnologia para despliegue de servicio migrado"),
                protocols=get(row_number, "Protocolos de consumo"),
                cache=get(row_number, "Cache Adicional al config"),
                cache_source=cache_source,
                external_interaction=get(row_number, "Interacción con proveedores externos"),
                exposed_methods=get(row_number, "Metodos que expone"),
                wave=get(row_number, "OLA"),
                deprecated_technology=get(row_number, "Consumen tecnologia deprecada"),
                legacy_repo=repo,
                legacy_repo_inferred=inferred,
                excel_umps={_canonical_ump(u) for u in UMP_RE.findall(all_text)},
                excel_txs=_extract_txs(all_text),
                excel_downstream_services={_canonical_service(s) for s in downstream},
                excel_jndi=set(JNDI_RE.findall(all_text)),
                excel_db_hints=_extract_db_hints(all_text),
                excel_external_domains=_extract_external_domains(get(row_number, "Interacción con proveedores externos")),
            )
        )
    return selected_sheet, rows


def _dedupe_tasks(tasks: list[RepoTask]) -> list[RepoTask]:
    by_key: dict[tuple[str, str], RepoTask] = {}
    for task in tasks:
        by_key.setdefault(task.key, task)
    return sorted(by_key.values(), key=lambda item: (item.kind, item.repo_name.lower()))


def _service_task(service: str, repo_name: str, root: Path, source: str, technology: str = "") -> RepoTask:
    fallback_project, fallback_repo = infer_legacy_repo(service, technology)
    repo = repo_name or fallback_repo
    return RepoTask(
        kind="service",
        name=service,
        repo_name=repo,
        project_key=project_key_for_repo(repo, fallback_project),
        dest=root / "legacy" / repo,
        source=source,
    )


def initial_repo_tasks(rows: list[DiscoveryRow], output_dir: Path) -> list[RepoTask]:
    """Build the first clone plan from Excel data."""
    tasks: list[RepoTask] = []
    for row in rows:
        tasks.append(
            _service_task(
                row.service,
                row.legacy_repo,
                output_dir,
                f"Discovery row {row.row_number}",
                row.technology,
            )
        )
        for service in row.excel_downstream_services:
            project_key, repo_name = infer_legacy_repo(service)
            tasks.append(
                RepoTask(
                    kind="service",
                    name=service,
                    repo_name=repo_name,
                    project_key=project_key,
                    dest=output_dir / "legacy" / repo_name,
                    source=f"downstream of {row.service}",
                )
            )
        for ump in row.excel_umps:
            repo_name = f"sqb-msa-{ump.lower()}"
            tasks.append(
                RepoTask(
                    kind="ump",
                    name=ump,
                    repo_name=repo_name,
                    project_key="bus",
                    dest=output_dir / "umps" / repo_name,
                    source=f"UMP from {row.service}",
                )
            )
        for tx in row.excel_txs:
            repo_name = f"sqb-cfg-{tx}-TX"
            tasks.append(
                RepoTask(
                    kind="tx",
                    name=tx,
                    repo_name=repo_name,
                    project_key="config",
                    dest=output_dir / "tx" / repo_name,
                    source=f"TX from {row.service}",
                )
            )
    return _dedupe_tasks(tasks)


def _clone_task(task: RepoTask, shallow: bool, enabled: bool) -> RepoResult:
    if task.dest.exists() and any(task.dest.iterdir()):
        return RepoResult(task.kind, task.name, task.repo_name, task.project_key, task.dest, "already_exists", "ya existia", task.source)
    if not enabled:
        return RepoResult(task.kind, task.name, task.repo_name, task.project_key, task.dest, "skipped", "clone deshabilitado", task.source)

    ok, detail = _git_clone(task.repo_name, task.dest, project_key=task.project_key, shallow=shallow)
    if ok:
        status: CloneStatus = "already_exists" if detail == "already cloned" else "cloned"
        return RepoResult(task.kind, task.name, task.repo_name, task.project_key, task.dest, status, detail, task.source)
    return RepoResult(task.kind, task.name, task.repo_name, task.project_key, task.dest, "failed", detail, task.source)


def clone_repo_tasks(
    tasks: list[RepoTask],
    *,
    shallow: bool,
    enabled: bool,
    workers: int,
) -> list[RepoResult]:
    """Clone repositories concurrently, returning one result per task."""
    if not tasks:
        return []
    results: list[RepoResult] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(_clone_task, task, shallow, enabled) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: (item.kind, item.repo_name.lower()))


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts or "build" in path.parts or ".gradle" in path.parts:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > 1_000_000:
                continue
        except OSError:
            continue
        yield path


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def scan_repo(repo_name: str, path: Path) -> RepoScan:
    """Scan a cloned repository for dependencies and config references."""
    scan = RepoScan(repo_name=repo_name, path=path)
    if not path.exists() or not path.is_dir():
        return scan

    for file_path in _iter_text_files(path):
        rel = _safe_relative(file_path, path)
        suffix = file_path.suffix.lower()
        if suffix == ".properties":
            scan.property_files.add(rel)
        if suffix in {".bat", ".cmd", ".yml", ".yaml", ".xml", ".properties"}:
            lowered_name = file_path.name.lower()
            if (
                "deploy" in lowered_name
                or "config" in lowered_name
                or suffix in {".properties", ".yml", ".yaml"}
            ):
                scan.config_files.add(rel)

        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        scan.umps.update(_canonical_ump(u) for u in UMP_RE.findall(text))
        scan.txs.update(_extract_txs(text))
        scan.jndi.update(JNDI_RE.findall(text))
        scan.services.update(_canonical_service(s) for s in SERVICE_RE.findall(text))
        scan.external_domains.update(_extract_external_domains(text))

        if suffix == ".properties":
            for line in text.splitlines():
                if not line.strip() or line.lstrip().startswith(("#", "!")):
                    continue
                match = PROPERTY_LINE_RE.match(line)
                if not match:
                    continue
                key = match.group(1).strip()
                if key:
                    scan.property_keys.add(key)
                    if SECRET_KEY_RE.search(key):
                        scan.secret_keys.add(key)
        else:
            for line in text.splitlines():
                if SECRET_KEY_RE.search(line) and ("=" in line or ":" in line):
                    redacted = re.split(r"[:=]", line.strip(), maxsplit=1)[0].strip()
                    if redacted and len(redacted) <= 120:
                        scan.secret_keys.add(redacted)

    return scan


def _scan_results(repo_results: list[RepoResult]) -> dict[str, RepoScan]:
    scans: dict[str, RepoScan] = {}
    for result in repo_results:
        if result.status in {"cloned", "already_exists"} and result.dest.exists():
            scans[result.repo_name.lower()] = scan_repo(result.repo_name, result.dest)
    return scans


def _known_result_keys(results: list[RepoResult]) -> set[tuple[str, str]]:
    return {(r.project_key, r.repo_name.lower()) for r in results}


def _new_ump_tasks(rows: list[DiscoveryRow], scans: dict[str, RepoScan], output_dir: Path, existing: set[tuple[str, str]]) -> list[RepoTask]:
    tasks: list[RepoTask] = []
    for row in rows:
        service_scan = scans.get(row.legacy_repo.lower())
        if not service_scan:
            continue
        for ump in service_scan.umps:
            repo_name = f"sqb-msa-{ump.lower()}"
            key = ("bus", repo_name.lower())
            if key not in existing:
                tasks.append(
                    RepoTask("ump", ump, repo_name, "bus", output_dir / "umps" / repo_name, f"repo scan {row.service}")
                )
    return _dedupe_tasks(tasks)


def _new_tx_tasks(scans: dict[str, RepoScan], output_dir: Path, existing: set[tuple[str, str]]) -> list[RepoTask]:
    tasks: list[RepoTask] = []
    for scan in scans.values():
        for tx in scan.txs:
            repo_name = f"sqb-cfg-{tx}-TX"
            key = ("config", repo_name.lower())
            if key not in existing:
                tasks.append(
                    RepoTask("tx", tx, repo_name, "config", output_dir / "tx" / repo_name, f"repo scan {scan.repo_name}")
                )
    return _dedupe_tasks(tasks)


def _join(values: set[str] | list[str], limit: int = 1200) -> str:
    ordered = sorted({str(v) for v in values if str(v).strip()})
    text = ", ".join(ordered)
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip(", ") + " ...[truncated]"


def _repo_status(repo_name: str, results_by_repo: dict[str, RepoResult]) -> str:
    result = results_by_repo.get(repo_name.lower())
    return result.status if result else ""


def build_dependency_rows(
    rows: list[DiscoveryRow],
    repo_results: list[RepoResult],
    scans: dict[str, RepoScan],
) -> list[dict[str, str]]:
    results_by_repo = {r.repo_name.lower(): r for r in repo_results}
    dependencies: list[dict[str, str]] = []

    def add(service: str, dep_type: str, value: str, source: str, repo_name: str = "", status: str = "", evidence: str = "") -> None:
        if not value:
            return
        dependencies.append(
            {
                "servicio": service,
                "tipo_dependencia": dep_type,
                "valor": value,
                "fuente": source,
                "repo": repo_name,
                "estado_repo": status,
                "evidencia": evidence,
            }
        )

    for row in rows:
        service_scan = scans.get(row.legacy_repo.lower())
        umps = set(row.excel_umps)
        txs = set(row.excel_txs)
        downstream = set(row.excel_downstream_services)
        jndi = set(row.excel_jndi)
        external_domains = set(row.excel_external_domains)
        property_files: set[str] = set()
        property_keys: set[str] = set()
        secret_keys: set[str] = set()
        config_files: set[str] = set()
        db_hints = set(row.excel_db_hints)

        if service_scan:
            umps.update(service_scan.umps)
            txs.update(service_scan.txs)
            downstream.update(s for s in service_scan.services if s.lower() != row.service.lower())
            jndi.update(service_scan.jndi)
            external_domains.update(service_scan.external_domains)
            property_files.update(service_scan.property_files)
            property_keys.update(service_scan.property_keys)
            secret_keys.update(service_scan.secret_keys)
            config_files.update(service_scan.config_files)

        for ump in sorted(umps):
            repo_name = f"sqb-msa-{ump.lower()}"
            status = _repo_status(repo_name, results_by_repo)
            add(row.service, "UMP", ump, "excel/repo", repo_name, status)
            ump_scan = scans.get(repo_name.lower())
            if ump_scan:
                txs.update(ump_scan.txs)
                jndi.update(ump_scan.jndi)
                external_domains.update(ump_scan.external_domains)
                property_files.update(f"{repo_name}/{p}" for p in ump_scan.property_files)
                property_keys.update(ump_scan.property_keys)
                secret_keys.update(ump_scan.secret_keys)
                config_files.update(f"{repo_name}/{p}" for p in ump_scan.config_files)

        for tx in sorted(txs):
            repo_name = f"sqb-cfg-{tx}-TX"
            add(row.service, "TX", tx, "excel/repo", repo_name, _repo_status(repo_name, results_by_repo))

        for dep_service in sorted(downstream):
            project_key, repo_name = infer_legacy_repo(dep_service)
            del project_key
            add(row.service, "SERVICIO_DOWNSTREAM", dep_service, "excel/repo", repo_name, _repo_status(repo_name, results_by_repo))

        for item in sorted(jndi):
            add(row.service, "JNDI_JDINT", item, "excel/repo")
        for item in sorted(property_files):
            add(row.service, "PROPERTY_FILE", item, "repo")
        for item in sorted(list(property_keys)[:80]):
            add(row.service, "PROPERTY_KEY", item, "repo")
        for item in sorted(secret_keys):
            add(row.service, "SECRET_KEY_REDACTED", item, "repo")
        for item in sorted(config_files):
            add(row.service, "CONFIG_FILE", item, "repo")
        for item in sorted(db_hints):
            add(row.service, "BDD_SCHEMA_HOST", item, "excel")
        for item in sorted(external_domains):
            add(row.service, "TERCERO_ENDPOINT", item, "excel/repo")
    return dependencies


def build_caveats(rows: list[DiscoveryRow], repo_results: list[RepoResult]) -> list[dict[str, str]]:
    caveats: list[dict[str, str]] = []
    seen: dict[str, int] = {}
    for row in rows:
        key = row.service.lower()
        seen[key] = seen.get(key, 0) + 1
        if row.legacy_repo_inferred:
            caveats.append(
                {
                    "servicio": row.service,
                    "tipo": "repo_legacy_inferido",
                    "detalle": f"LINK CODIGO vacio o no parseable; se infirio {row.legacy_repo}",
                    "accion": "Validar manualmente el repo antes de migrar",
                }
            )
        if not row.technology:
            caveats.append(
                {
                    "servicio": row.service,
                    "tipo": "tecnologia_vacia",
                    "detalle": "La columna Tecnologia esta vacia",
                    "accion": "Confirmar si es Bus, WAS u otro tipo antes de clonar/migrar",
                }
            )
        if row.discovery_observation:
            caveats.append(
                {
                    "servicio": row.service,
                    "tipo": "observacion_discovery",
                    "detalle": row.discovery_observation,
                    "accion": "Revisar observacion del Excel",
                }
            )

    for service_key, count in seen.items():
        if count > 1:
            service_name = next(row.service for row in rows if row.service.lower() == service_key)
            caveats.append(
                {
                    "servicio": service_name,
                    "tipo": "servicio_duplicado",
                    "detalle": f"Aparece {count} veces en Discovery",
                    "accion": "Consolidar filas o validar si representan operaciones distintas",
                }
            )

    for result in repo_results:
        if result.status == "failed":
            caveats.append(
                {
                    "servicio": result.name,
                    "tipo": f"clone_failed_{result.kind}",
                    "detalle": f"{result.repo_name}: {result.detail}",
                    "accion": "Validar permisos Azure, nombre del repo o proyecto origen",
                }
            )
    return caveats


def _append_table(ws, headers: list[str], rows: list[list[Any]]) -> None:
    ws.append(headers)
    for row in rows:
        ws.append(row)
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col_idx, header in enumerate(headers, 1):
        max_len = len(str(header))
        for row_idx in range(2, min(ws.max_row, 250) + 1):
            value = ws.cell(row_idx, col_idx).value
            max_len = max(max_len, len(str(value or "")))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 2, 12), 60)
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def write_discovery_workbook(
    *,
    name: str,
    source_excel: Path,
    sheet_name: str,
    output_dir: Path,
    rows: list[DiscoveryRow],
    repo_results: list[RepoResult],
    scans: dict[str, RepoScan],
    dependencies: list[dict[str, str]],
    caveats: list[dict[str, str]],
) -> Path:
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{name}.xlsx"
    wb = Workbook()
    wb.remove(wb.active)

    repo_status_counts: dict[str, int] = {}
    for result in repo_results:
        repo_status_counts[result.status] = repo_status_counts.get(result.status, 0) + 1

    summary = wb.create_sheet("Resumen")
    summary_rows = [
        ["Nombre discovery", name],
        ["Excel fuente", str(source_excel)],
        ["Hoja leida", sheet_name],
        ["Generado", dt.datetime.now().isoformat(timespec="seconds")],
        ["Servicios filas", len(rows)],
        ["Servicios unicos", len({row.service.lower() for row in rows})],
        ["UMPs unicos", len({dep["valor"] for dep in dependencies if dep["tipo_dependencia"] == "UMP"})],
        ["TX unicos", len({dep["valor"] for dep in dependencies if dep["tipo_dependencia"] == "TX"})],
        ["Repos planificados", len(repo_results)],
        ["Repos clonados", repo_status_counts.get("cloned", 0)],
        ["Repos existentes", repo_status_counts.get("already_exists", 0)],
        ["Repos fallidos", repo_status_counts.get("failed", 0)],
        ["Caveats", len(caveats)],
    ]
    _append_table(summary, ["Metrica", "Valor"], summary_rows)

    service_headers = [
        "fila_discovery",
        "servicio",
        "responsable",
        "complejidad",
        "tecnologia",
        "tipo",
        "repo_legacy",
        "repo_legacy_inferido",
        "repo_migracion",
        "umps_involucrados",
        "txs_involucrados",
        "servicios_downstream",
        "properties_involucrados",
        "jndi_jdint_involucrados",
        "secret_keys_redacted",
        "terceros_involucrados",
        "bdd_schema_host",
        "cache",
        "cache_source",
        "observaciones",
        "observacion_discovery",
        "tribu",
        "descripcion",
    ]
    deps_by_service: dict[str, dict[str, set[str]]] = {}
    for dep in dependencies:
        by_type = deps_by_service.setdefault(dep["servicio"].lower(), {})
        by_type.setdefault(dep["tipo_dependencia"], set()).add(dep["valor"])

    service_rows: list[list[Any]] = []
    for row in rows:
        depmap = deps_by_service.get(row.service.lower(), {})
        service_rows.append(
            [
                row.row_number,
                row.service,
                row.responsible,
                row.complexity,
                row.technology,
                row.kind,
                row.legacy_repo,
                "SI" if row.legacy_repo_inferred else "NO",
                row.migration_repo,
                _join(depmap.get("UMP", set())),
                _join(depmap.get("TX", set())),
                _join(depmap.get("SERVICIO_DOWNSTREAM", set())),
                _join(depmap.get("PROPERTY_FILE", set()) | depmap.get("PROPERTY_KEY", set())),
                _join(depmap.get("JNDI_JDINT", set())),
                _join(depmap.get("SECRET_KEY_REDACTED", set())),
                _join(depmap.get("TERCERO_ENDPOINT", set())),
                _join(depmap.get("BDD_SCHEMA_HOST", set())),
                row.cache,
                row.cache_source,
                row.observations,
                row.discovery_observation,
                row.tribe,
                row.description,
            ]
        )
    _append_table(wb.create_sheet("Servicios"), service_headers, service_rows)

    dep_headers = ["servicio", "tipo_dependencia", "valor", "fuente", "repo", "estado_repo", "evidencia"]
    dep_rows = [[dep.get(header, "") for header in dep_headers] for dep in dependencies]
    _append_table(wb.create_sheet("Dependencias"), dep_headers, dep_rows)

    repo_headers = ["tipo", "nombre", "repo", "proyecto_azure", "estado", "detalle", "fuente", "ruta_local"]
    repo_rows = [
        [
            result.kind,
            result.name,
            result.repo_name,
            result.project_key,
            result.status,
            result.detail,
            result.source,
            str(result.dest),
        ]
        for result in repo_results
    ]
    _append_table(wb.create_sheet("Repos"), repo_headers, repo_rows)

    caveat_headers = ["servicio", "tipo", "detalle", "accion"]
    caveat_rows = [[c.get(header, "") for header in caveat_headers] for c in caveats]
    _append_table(wb.create_sheet("Caveats"), caveat_headers, caveat_rows)

    scan_headers = [
        "repo",
        "ruta",
        "umps",
        "txs",
        "servicios",
        "jndi_jdint",
        "property_files",
        "property_keys",
        "secret_keys_redacted",
        "external_domains",
        "config_files",
    ]
    scan_rows = [
        [
            scan.repo_name,
            str(scan.path),
            _join(scan.umps),
            _join(scan.txs),
            _join(scan.services),
            _join(scan.jndi),
            _join(scan.property_files),
            _join(scan.property_keys),
            _join(scan.secret_keys),
            _join(scan.external_domains),
            _join(scan.config_files),
        ]
        for scan in scans.values()
    ]
    _append_table(wb.create_sheet("Repo Scan"), scan_headers, scan_rows)

    wb.save(report_path)
    return report_path


def run_discovery(
    *,
    name: str,
    workbook_path: Path,
    root: Path,
    sheet_name: str | None = None,
    clone: bool = True,
    shallow: bool = True,
    workers: int = 4,
) -> DiscoveryResult:
    """Execute discovery end-to-end and return the generated report path."""
    source_excel = workbook_path.resolve()
    output_dir = (root / name).resolve()
    for subdir in ("legacy", "umps", "tx", "reports", ".capamedia/discovery"):
        (output_dir / subdir).mkdir(parents=True, exist_ok=True)

    selected_sheet, rows = read_discovery_rows(source_excel, sheet_name)

    all_results: list[RepoResult] = []
    initial_tasks = initial_repo_tasks(rows, output_dir)
    all_results.extend(clone_repo_tasks(initial_tasks, shallow=shallow, enabled=clone, workers=workers))
    scans = _scan_results(all_results)

    known = _known_result_keys(all_results)
    discovered_ump_tasks = _new_ump_tasks(rows, scans, output_dir, known)
    if discovered_ump_tasks:
        extra_results = clone_repo_tasks(discovered_ump_tasks, shallow=shallow, enabled=clone, workers=workers)
        all_results.extend(extra_results)
        scans.update(_scan_results(extra_results))

    known = _known_result_keys(all_results)
    discovered_tx_tasks = _new_tx_tasks(scans, output_dir, known)
    if discovered_tx_tasks:
        extra_results = clone_repo_tasks(discovered_tx_tasks, shallow=shallow, enabled=clone, workers=workers)
        all_results.extend(extra_results)
        scans.update(_scan_results(extra_results))

    dependencies = build_dependency_rows(rows, all_results, scans)
    caveats = build_caveats(rows, all_results)
    report_path = write_discovery_workbook(
        name=name,
        source_excel=source_excel,
        sheet_name=selected_sheet,
        output_dir=output_dir,
        rows=rows,
        repo_results=all_results,
        scans=scans,
        dependencies=dependencies,
        caveats=caveats,
    )

    return DiscoveryResult(
        name=name,
        source_excel=source_excel,
        sheet_name=selected_sheet,
        output_dir=output_dir,
        report_path=report_path,
        rows=rows,
        repo_results=all_results,
        scans=scans,
        dependencies=dependencies,
        caveats=caveats,
    )
