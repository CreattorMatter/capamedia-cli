"""capamedia clone <servicio> - clonado determinista de legacy + UMPs + TX.

Trae solo lo especifico del servicio:
  CWD/
    legacy/sqb-msa-<servicio>/            (codigo legacy IIB)
    legacy/_repo/<servicio>-aplicacion/   (codigo legacy WAS clasico)
    legacy/_repo/<servicio>-infraestructura/
    umps/sqb-msa-umpclientes<NNNN>/       (dependencias directas)
    tx/sqb-cfg-<NNNNNN>-TX/               (contratos BANCS de cada TX invocado)
    COMPLEXITY_<servicio>.md              (reporte de analisis)

Decision de diseño (v0.2.2):
- NO se traen catalogos globales (codigosBackend, errores).
- NO se trae gold reference (wsclientes0024/0015).
El conocimiento de esos referentes ya esta embebido en los prompts canonicos
del CLI (migrate-rest-full.md, migrate-soap-full.md, checklist-rules.md).
El CLI debe saber migrar bien por si mismo, sin copiar de un servicio-ejemplo
cada vez. Si en algun servicio particular hace falta un catalogo, el usuario
puede clonarlo manual una vez.
"""

from __future__ import annotations

import os
import re as _clone_re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli.core.auth import build_azure_git_env, resolve_azure_devops_pat
from capamedia_cli.core.azure_search import AzureCodeSearch, AzureSearchError
from capamedia_cli.core.dossier import (
    build_dossier,
    render_dossier_prompt_appendix,
    write_dossier,
)
from capamedia_cli.core.legacy_analyzer import analyze_legacy

console = Console()

AZURE_ORG = "BancoPichinchaEC"

# Mapeo de tipo de repo -> proyecto Azure DevOps
AZURE_PROJECTS = {
    "bus": "tpl-bus-omnicanal",                # legacy IIB + UMPs + ORQs
    "was": "tpl-integration-services-was",      # legacy WAS (ws-<svc>-was, ms-<svc>-was)
    "config": "tpl-integrationbus-config",      # TX repos + catalogos
    "middleware": "tpl-middleware",             # gold/migrados (tnd/tia/tpr/csg-msa-sp-*)
}


def _azure_url(project_key: str, repo_name: str) -> str:
    """Build the Azure DevOps clone URL for a given project key."""
    project = AZURE_PROJECTS[project_key]
    return f"https://dev.azure.com/{AZURE_ORG}/{project}/_git/{repo_name}"


# Regex para normalizar nombres de servicios con padding de 4 digitos.
# Convencion Banco Pichincha: todos los servicios terminan en 4 digitos
# (wsclientes0076, wstecnicos0008, orq0027, umpclientes0023, etc.).
_SERVICE_NAME_PADDING_RE = _clone_re.compile(r"^([a-z][a-z]*?)(\d{1,3})$", _clone_re.IGNORECASE)


def normalize_service_name(name: str) -> tuple[str, bool]:
    """Auto-padea el sufijo numerico a 4 digitos.

    Ejemplos:
      wsclientes76     -> wsclientes0076  (padded)
      wstecnicos8      -> wstecnicos0008  (padded)
      orq27            -> orq0027         (padded)
      wsclientes0076   -> wsclientes0076  (no padded, ya tiene 4)
      wstecnicos12345  -> wstecnicos12345 (no padded, >4 se respeta)
      foo              -> foo             (no termina en digitos)

    Returns:
      (normalized, was_padded)
    """
    clean = name.strip().lower()
    m = _SERVICE_NAME_PADDING_RE.match(clean)
    if not m:
        return clean, False
    prefix, digits = m.group(1), m.group(2)
    if len(digits) >= 4:
        return clean, False
    padded = f"{prefix}{digits.zfill(4)}"
    return padded, True


# Combinaciones (proyecto, patron) probadas en orden cuando un servicio no esta local.
# Patron usa {svc} como placeholder para el nombre lowercase del servicio.
AZURE_FALLBACK_PATTERNS: list[tuple[str, str]] = [
    ("bus", "sqb-msa-{svc}"),                # IIB tipico
    ("was", "ws-{svc}-was"),                 # WAS tipico
    ("was", "ms-{svc}-was"),                 # WAS variante "ms"
]

WAS_SPLIT_REPO_SUFFIXES = ("aplicacion", "infraestructura")


# UMPs pueden vivir en distintos proyectos segun el tipo del servicio que las
# consume:
#   - IIB/ORQ: UMPs en `tpl-bus-omnicanal/sqb-msa-<ump>` (patron clasico)
#   - WAS:     UMPs en `tpl-integration-services-was/ump-<ump>-was`
# El CLI intenta primero el patron correspondiente al source_kind del servicio
# principal, despues los otros como fallback.
UMP_AZURE_FALLBACK_PATTERNS_IIB: list[tuple[str, str]] = [
    ("bus", "sqb-msa-{ump}"),                # IIB/ORQ clasico
    ("was", "ump-{ump}-was"),                # por si una UMP se movio a WAS
]

UMP_AZURE_FALLBACK_PATTERNS_WAS: list[tuple[str, str]] = [
    ("was", "ump-{ump}-was"),                # WAS (caso wstecnicos0008/umptecnicos0023)
    ("was", "ms-{ump}-was"),                 # variante "ms"
    ("bus", "sqb-msa-{ump}"),                # fallback IIB (por si la UMP vive aun alla)
]


def _ump_name_variants(ump_name: str) -> list[str]:
    """Return UMP repo-name variants preserving the legacy reference casing."""
    raw = ump_name.strip()
    lower = raw.lower()
    variants: list[str] = []

    def add(value: str) -> None:
        if value and value not in variants:
            variants.append(value)

    add(raw)
    if raw[:3].lower() == "ump" and len(raw) > 3:
        add("ump" + raw[3:])
    add(lower)
    return variants


def _resolve_azure_repo(service_name: str, dest_root: Path, shallow: bool) -> tuple[Path | None, str, str]:
    """Intenta clonar el servicio probando todos los patrones Azure conocidos.

    Returns:
      (path_clonado, project_key, repo_name) o (None, "", "") si nada funciona.
    """
    svc = service_name.lower()
    for project_key, pattern in AZURE_FALLBACK_PATTERNS:
        repo_name = pattern.format(svc=svc)
        dest = dest_root / "legacy" / repo_name
        ok, _err = _git_clone(repo_name, dest, project_key=project_key, shallow=shallow)
        if ok:
            return (dest, project_key, repo_name)
    split_root = dest_root / "legacy" / "_repo"
    split_repos: list[str] = []
    for suffix in WAS_SPLIT_REPO_SUFFIXES:
        repo_name = f"{svc}-{suffix}"
        dest = split_root / repo_name
        ok, _err = _git_clone(repo_name, dest, project_key="was", shallow=shallow)
        if ok:
            split_repos.append(repo_name)
    if split_repos:
        return (split_root, "was", " + ".join(split_repos))
    return (None, "", "")


def _resolve_ump_repo(
    ump_name: str,
    dest_root: Path,
    shallow: bool,
    *,
    parent_kind: str = "iib",
) -> tuple[Path | None, str, str]:
    """Intenta clonar un repo de UMP probando los patrones conocidos.

    `parent_kind`: tipo del servicio que usa la UMP (iib/was/orq). Determina
    el orden de prueba. UMPs de servicios WAS suelen vivir en
    `tpl-integration-services-was/ump-<ump>-was`; UMPs de IIB/ORQ en
    `tpl-bus-omnicanal/sqb-msa-<ump>`.

    Returns: (path_clonado, project_key, repo_name) o (None, "", "").
    """
    patterns = (
        UMP_AZURE_FALLBACK_PATTERNS_WAS
        if parent_kind == "was"
        else UMP_AZURE_FALLBACK_PATTERNS_IIB
    )
    tried: set[tuple[str, str]] = set()
    for project_key, pattern in patterns:
        for ump in _ump_name_variants(ump_name):
            repo_name = pattern.format(ump=ump)
            key = (project_key, repo_name)
            if key in tried:
                continue
            tried.add(key)
            dest = dest_root / "umps" / repo_name
            ok, _err = _git_clone(
                repo_name, dest, project_key=project_key, shallow=shallow
            )
            if ok:
                return (dest, project_key, repo_name)
    return (None, "", "")


@dataclass
class TxCloneResult:
    """Resultado de clonar un repo de TX especifico."""

    tx_code: str
    repo_name: str
    status: str  # "cloned" | "not_found" | "error" | "skipped"
    path: Path | None = None
    error: str = ""


@dataclass
class MigratedCloneResult:
    """Resultado de clonar un repo migrado desde tpl-middleware."""

    namespace: str
    repo_name: str
    status: str  # "cloned" | "already_present" | "not_found" | "error"
    path: Path | None = None
    branch: str = ""
    error: str = ""


MIGRATED_NAMESPACES = ("tnd", "tpr", "csg", "tmp", "tia", "tct")
DEFAULT_BRANCH_NAMES = {"main", "master"}


def _git_error_tail(result: subprocess.CompletedProcess[str]) -> str:
    output = result.stderr or result.stdout or ""
    return output.strip().split("\n")[-1] if output else "unknown error"


def _looks_like_auth_or_repo_visibility_error(error: str) -> bool:
    lowered = error.lower()
    return any(
        token in lowered
        for token in (
            "tf401019",
            "not found",
            "repository not found",
            "does not exist",
            "no tienes permisos",
            "no tiene permisos",
            "authentication failed",
            "could not read username",
            "terminal prompts disabled",
        )
    )


def _git_credential_manager_env() -> dict[str, str]:
    """Allow cached Git Credential Manager auth without prompting interactively."""
    return {
        **os.environ,
        "GCM_INTERACTIVE": "Never",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _git_clone(
    repo_name: str,
    dest: Path,
    project_key: str = "bus",
    shallow: bool = False,
    no_single_branch: bool = False,
) -> tuple[bool, str]:
    """Clone a repo from Azure DevOps. Returns (success, error_msg).

    `project_key` debe ser "bus" | "config" segun donde vive el repo.
    """
    if dest.exists() and any(dest.iterdir()):
        return (True, "already cloned")
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = _azure_url(project_key, repo_name)
    cmd = ["git", "clone"]
    if shallow:
        cmd += ["--depth", "1"]
        if no_single_branch:
            cmd += ["--no-single-branch"]
    cmd += [url, str(dest)]
    git_env = build_azure_git_env()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
            env={**os.environ, **git_env} if git_env else None,
        )
        if result.returncode == 0:
            return (True, "")
        first_error = _git_error_tail(result)
        if git_env and _looks_like_auth_or_repo_visibility_error(first_error):
            retry = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
                env=_git_credential_manager_env(),
            )
            if retry.returncode == 0:
                return (True, "")
            return (
                False,
                f"{first_error} (retry sin CAPAMEDIA_AZDO_PAT: {_git_error_tail(retry)})",
            )
        return (False, first_error)
    except subprocess.TimeoutExpired:
        return (False, "timeout")
    except FileNotFoundError:
        return (False, "git no disponible en PATH")


def _list_remote_branches(repo_path: Path) -> list[str]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "for-each-ref",
                "refs/remotes/origin",
                "--format=%(refname:short)",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    branches: list[str] = []
    for raw in result.stdout.splitlines():
        branch = raw.strip()
        if not branch or branch == "origin/HEAD":
            continue
        if branch.startswith("origin/"):
            branch = branch.removeprefix("origin/")
        branches.append(branch)
    return sorted(set(branches))


def _checkout_branch(repo_path: Path, branch: str) -> tuple[bool, str]:
    clean_branch = branch.removeprefix("origin/").strip()
    if not clean_branch:
        return (False, "branch vacio")
    result = subprocess.run(
        ["git", "-C", str(repo_path), "checkout", "-B", clean_branch, f"origin/{clean_branch}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode == 0:
        return (True, "")
    return (False, (result.stderr or result.stdout or "git checkout failed").strip())


def _auto_checkout_migrated_branch(repo_path: Path, requested_branch: str | None) -> tuple[str, str, str]:
    """Checkout de rama para repos migrados.

    Returns: (branch, mode, error). mode: explicit | auto | default | ambiguous.
    """
    if requested_branch:
        ok, err = _checkout_branch(repo_path, requested_branch)
        return (requested_branch, "explicit", "" if ok else err)

    branches = _list_remote_branches(repo_path)
    non_default = [b for b in branches if b not in DEFAULT_BRANCH_NAMES]
    feature_branches = [b for b in non_default if b.startswith("feature/")]

    candidate = ""
    if len(non_default) == 1:
        candidate = non_default[0]
    elif len(feature_branches) == 1:
        candidate = feature_branches[0]

    if candidate:
        ok, err = _checkout_branch(repo_path, candidate)
        return (candidate, "auto", "" if ok else err)

    if non_default:
        return ("", "ambiguous", f"multiples ramas candidatas: {', '.join(non_default[:8])}")
    return ("", "default", "")


def _clone_migrated_repos(
    service_name: str,
    workspace: Path,
    *,
    shallow: bool = False,
    namespace: str | None = None,
    branch: str | None = None,
) -> list[MigratedCloneResult]:
    """Clone migrated middleware repos under `destino/`.

    If namespace is omitted, tries every known namespace and keeps every repo
    that exists. This supports services already migrated under `tnd`, `tia`,
    `tpr`, `csg`, `tmp`, or `tct`.
    """
    namespaces = [namespace.lower()] if namespace else list(MIGRATED_NAMESPACES)
    results: list[MigratedCloneResult] = []
    svc = service_name.lower()

    for ns in namespaces:
        repo_name = f"{ns}-msa-sp-{svc}"
        dest = workspace / "destino" / repo_name
        was_present = dest.exists() and any(dest.iterdir())
        ok, err = _git_clone(
            repo_name,
            dest,
            project_key="middleware",
            shallow=shallow,
            no_single_branch=True,
        )
        if not ok:
            status = (
                "not_found"
                if "not found" in err.lower()
                or "does not exist" in err.lower()
                or "repository not found" in err.lower()
                or "404" in err
                else "error"
            )
            results.append(MigratedCloneResult(ns, repo_name, status, error=err))
            continue

        checkout_branch = ""
        checkout_error = ""
        if branch or not was_present:
            checkout_branch, _mode, checkout_error = _auto_checkout_migrated_branch(dest, branch)

        results.append(
            MigratedCloneResult(
                ns,
                repo_name,
                "already_present" if was_present else "cloned",
                path=dest,
                branch=checkout_branch,
                error=checkout_error,
            )
        )
    return results


def _resolve_legacy_repo_name(service_name: str) -> str:
    """Map service name to Azure DevOps repo name."""
    return f"sqb-msa-{service_name.lower()}"


def _clone_tx_repos(tx_codes: set[str], workspace: Path, shallow: bool = True) -> list[TxCloneResult]:
    """Clone sqb-cfg-<TX>-TX repos for each TX code detected. Viven en tpl-integrationbus-config."""
    results: list[TxCloneResult] = []
    for tx_code in sorted(tx_codes):
        repo_name = f"sqb-cfg-{tx_code}-TX"
        dest = workspace / "tx" / repo_name
        ok, err = _git_clone(repo_name, dest, project_key="config", shallow=shallow)
        if ok:
            results.append(TxCloneResult(tx_code=tx_code, repo_name=repo_name, status="cloned", path=dest))
        elif "not found" in err.lower() or "does not exist" in err.lower() or "404" in err:
            results.append(TxCloneResult(tx_code=tx_code, repo_name=repo_name, status="not_found", error=err))
        else:
            results.append(TxCloneResult(tx_code=tx_code, repo_name=repo_name, status="error", error=err))
    return results


def _write_complexity_report(
    analysis,
    service_name: str,
    workspace: Path,
    tx_results: list[TxCloneResult],
    legacy_root: Path | None = None,
    discovery_entry=None,
) -> Path:
    """Write COMPLEXITY_<service>.md with the deterministic analysis."""
    from capamedia_cli.core.caveats import (
        Caveat,
        caveats_summary,
        caveats_to_markdown_table,
        detect_external_endpoints,
        detect_non_bancs_caveats,
        detect_orq_dependencies,
        detect_ump_caveats,
    )

    # Detectar caveats
    caveats: list[Caveat] = []
    caveats.extend(detect_ump_caveats(analysis))
    if legacy_root:
        caveats.extend(detect_non_bancs_caveats(legacy_root))
        caveats.extend(detect_external_endpoints(legacy_root))
    orq_deps, is_orq = detect_orq_dependencies(legacy_root or workspace, service_name)
    dest = workspace / f"COMPLEXITY_{service_name}.md"
    lines: list[str] = []
    lines.append(f"# Complexity Report: {service_name}\n")
    lines.append("Generado por `capamedia clone` (v0.2.2). Sin AI - solo analisis determinista.\n")
    lines.append("")
    lines.append("## Resumen")
    lines.append("")
    lines.append(f"- **Tipo de fuente:** `{analysis.source_kind}`")
    if analysis.wsdl:
        lines.append(f"- **Operaciones WSDL:** `{analysis.wsdl.operation_count}`")
        lines.append(f"- **targetNamespace:** `{analysis.wsdl.target_namespace}`")
        lines.append(f"- **Operaciones detectadas:** `{', '.join(analysis.wsdl.operation_names)}`")
    else:
        lines.append("- **WSDL:** NO encontrado")
    lines.append(f"- **UMPs detectados:** `{len(analysis.umps)}`")
    lines.append(f"- **BD detectada:** `{'SI' if analysis.has_database else 'NO'}`")
    lines.append(f"- **Framework recomendado:** `{analysis.framework_recommendation.upper()}`")
    lines.append(f"- **Complejidad:** `{analysis.complexity.upper()}`")
    lines.append("")

    if discovery_entry is not None:
        from capamedia_cli.core.discovery import render_discovery_markdown

        lines.append(render_discovery_markdown(discovery_entry))

    # UMPs con columna de extraccion
    if analysis.umps:
        lines.append("## UMPs y TX codes")
        lines.append("")
        lines.append("| UMP | TX code | Extraido | Fuente | Nota |")
        lines.append("|---|---|---|---|---|")
        for u in analysis.umps:
            if u.tx_codes:
                tx_str = ", ".join(u.tx_codes)
                extraido = "SI"
                fuente = "ESQL"
                nota = ""
            else:
                tx_str = "-"
                extraido = "NO"
                fuente = "-"
                nota = "No visto en ESQL. Mirar `deploy-*-config.bat` del UMP o pedir el TX al equipo"
            lines.append(f"| {u.name} | {tx_str} | {extraido} | {fuente} | {nota} |")
        lines.append("")

    # TX repos clonados
    if tx_results:
        lines.append("## TX repos clonados")
        lines.append("")
        lines.append("| TX code | Repo | Status | Path |")
        lines.append("|---|---|---|---|")
        for tr in tx_results:
            status_label = {
                "cloned": "clonado",
                "not_found": "no existe repo",
                "error": "error",
                "skipped": "saltado",
            }.get(tr.status, tr.status)
            path_str = str(tr.path.relative_to(workspace)) if tr.path else "-"
            lines.append(f"| {tr.tx_code} | {tr.repo_name} | {status_label} | {path_str} |")
        lines.append("")

    if analysis.has_database and analysis.db_evidence:
        lines.append("## Evidencia de BD (WAS)")
        lines.append("")
        for ev in analysis.db_evidence:
            lines.append(f"- {ev}")
        lines.append("")

    if analysis.warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in analysis.warnings:
            lines.append(f"- {w}")
        lines.append("")

    # Seccion de caveats (v0.3.1)
    lines.append("## Caveats detectados (requieren intervencion manual)")
    lines.append("")
    summary = caveats_summary(caveats)
    if summary:
        for kind, count in sorted(summary.items()):
            lines.append(f"- **{kind}:** {count}")
        lines.append("")
        lines.append(caveats_to_markdown_table(caveats))
    else:
        lines.append("_(ninguno)_\n")

    # Seccion de dependencias ORQ (v0.3.1)
    if is_orq:
        lines.append("## Dependencias ORQ")
        lines.append("")
        lines.append(f"Este servicio es un **orquestador**. Delega a {len(orq_deps)} servicio(s):")
        lines.append("")
        for d in orq_deps:
            lines.append(f"- {d} (verificar si esta migrado antes de poner el ORQ en produccion)")
        lines.append("")

    lines.append("## Proximo paso")
    lines.append("")
    lines.append("- Corre `capamedia fabrics generate` desde el workspace para generar el arquetipo")
    lines.append("- Luego corre `capamedia ai migrate` y `capamedia ai doublecheck`")
    lines.append("")

    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def _run_deep_scan(
    *,
    service_name: str,
    workspace: Path,
    wsdl_namespace: str | None,
    tx_codes: list[str],
    umps: list[str],
) -> Path | None:
    """Deep-scan Azure DevOps Code Search. Escribe DOSSIER_<svc>.md."""
    pat = resolve_azure_devops_pat()
    if not pat:
        console.print(
            "  [yellow]SKIP[/yellow] CAPAMEDIA_AZDO_PAT no configurado. "
            "Correr `capamedia auth bootstrap` para habilitar deep-scan."
        )
        return None

    try:
        client = AzureCodeSearch(pat=pat, org="bancopichincha")
    except AzureSearchError as exc:
        console.print(f"  [red]FAIL[/red] {exc}")
        return None

    console.print(
        f"  [dim]Queries: servicio '{service_name}'"
        + (f" + ns '{wsdl_namespace}'" if wsdl_namespace else "")
        + f" + {len(tx_codes)} TX + {len(umps)} UMP[/dim]"
    )

    try:
        dossier = build_dossier(
            service=service_name,
            client=client,
            wsdl_namespace=wsdl_namespace,
            tx_codes=tx_codes,
            umps=umps,
        )
    except AzureSearchError as exc:
        console.print(f"  [red]FAIL[/red] deep-scan incompleto: {exc}")
        return None

    dossier_path = write_dossier(workspace, dossier)
    console.print(
        f"  [green]OK[/green] {dossier.total_hits} hits · "
        f"{len(dossier.ce_vars)} CE_* · {len(dossier.ccc_vars)} CCC_* · "
        f"escrito en [cyan]{dossier_path.name}[/cyan]"
    )

    # Persistir el appendix para que FABRICS_PROMPT / batch migrate lo inyecten
    cache_dir = workspace / ".capamedia"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "dossier-appendix.md").write_text(
        render_dossier_prompt_appendix(dossier),
        encoding="utf-8",
    )

    return dossier_path


def clone_service(
    service_name: Annotated[
        str,
        typer.Argument(help="Nombre del servicio (ej: wsclientes0008, orqtransferencias0003)"),
    ],
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Carpeta raiz del workspace (default: CWD)",
        ),
    ] = None,
    shallow: Annotated[
        bool,
        typer.Option("--shallow", help="Clone superficial (--depth 1) para ahorrar tiempo"),
    ] = False,
    skip_tx: Annotated[
        bool,
        typer.Option("--skip-tx", help="No clonar los repos de TX individuales (sqb-cfg-<TX>-TX)"),
    ] = False,
    deep_scan: Annotated[
        bool,
        typer.Option(
            "--deep-scan",
            help="Recolecta evidencia de Azure DevOps Code Search (cross-refs, ConfigMaps, "
            "variables CE_*/CCC_*) y genera DOSSIER_<svc>.md para inyectar al FABRICS_PROMPT.",
        ),
    ] = False,
    discovery_xlsx: Annotated[
        Path | None,
        typer.Option(
            "--discovery-xlsx",
            envvar="CAPAMEDIA_DISCOVERY_XLSX",
            help=(
                "Override del Excel Discovery OLA. Si falta, se busca el archivo "
                "canonico en workspace/.capamedia/discovery/ancestros/paquete CLI/Downloads."
            ),
        ),
    ] = None,
    discovery_sheet: Annotated[
        str,
        typer.Option("--discovery-sheet", help="Hoja del Excel Discovery"),
    ] = "Validacion de servicios",
    init: Annotated[
        bool,
        typer.Option(
            "--init",
            help="v0.23.0: al terminar el clone, ejecutar capamedia init automaticamente. "
            "Por defecto usa Claude Code como harness. Equivale a "
            "`capamedia clone <svc>` + `capamedia init <svc> --ai claude` en una sola linea.",
        ),
    ] = False,
    init_ai: Annotated[
        str,
        typer.Option(
            "--init-ai",
            help="Harness AI para el init automatico. Default: `claude` (Claude Code). "
            "Otras opciones: `codex`, `copilot`, `cursor`, `windsurf`, `opencode`, `all`. "
            "CSV permitido (ej. `claude,codex`). Solo se usa si --init esta activado.",
        ),
    ] = "claude",
) -> None:
    """Clona el legacy + UMPs + TX repos y analiza complejidad del servicio."""
    ws = workspace or Path.cwd()
    ws.mkdir(parents=True, exist_ok=True)

    # v0.20.1: auto-padding a 4 digitos segun convencion del banco
    original_name = service_name
    service_name, was_padded = normalize_service_name(service_name)
    if was_padded:
        console.print(
            f"[yellow]Tip:[/yellow] [cyan]{original_name}[/cyan] -> "
            f"[cyan]{service_name}[/cyan] (auto-padded a 4 digitos; "
            "convencion Banco Pichincha)"
        )

    console.print(
        Panel.fit(
            f"[bold]CapaMedia clone[/bold]\nServicio: [cyan]{service_name}[/cyan]\nWorkspace: [cyan]{ws}[/cyan]",
            border_style="cyan",
        )
    )

    # --- Step 1: Resolver legacy (local primero, despues clonar de Azure) ---
    from capamedia_cli.core.local_resolver import find_local_legacy

    capa_media_root = ws.parent  # padre del workspace = donde viven los <NNNN>-* locales
    legacy_dest: Path | None = find_local_legacy(service_name, capa_media_root)

    if legacy_dest:
        console.print(
            f"\n[bold]1. Legacy detectado LOCALMENTE[/bold] (no requiere clone): {legacy_dest}"
        )
    else:
        console.print("\n[bold]1. Legacy no esta local. Probando proyectos Azure...[/bold]")
        legacy_dest, project_key, repo_name = _resolve_azure_repo(service_name, ws, shallow)
        if legacy_dest is None:
            console.print("[red]FAIL[/red] no se encontro en ningun proyecto Azure conocido")
            console.print(
                "[yellow]Tip:[/yellow] verifica que el servicio exista o agrega un nuevo "
                "patron a AZURE_FALLBACK_PATTERNS en clone.py."
            )
            raise typer.Exit(1)
        console.print(f"[green]OK[/green] {project_key}/{repo_name} clonado en {legacy_dest}")

    # --- Step 2: Detect UMPs (WAS busca en pom.xml + Java; IIB/ORQ en ESQL) ---
    from capamedia_cli.core.legacy_analyzer import (
        detect_source_kind,
        detect_ump_references,
        detect_ump_references_was,
    )

    pre_kind = detect_source_kind(legacy_dest, service_name)
    if pre_kind == "was":
        console.print(
            "\n[bold]2. Detectando UMPs en pom.xml + imports Java (WAS)...[/bold]"
        )
        ump_names = detect_ump_references_was(legacy_dest)
    else:
        console.print(
            "\n[bold]2. Detectando UMPs referenciados en ESQL/msgflow...[/bold]"
        )
        ump_names = detect_ump_references(legacy_dest)

    if ump_names:
        console.print(f"[green]OK[/green] {len(ump_names)} UMP(s) detectado(s): {', '.join(ump_names)}")
    else:
        console.print("[dim]No se detectaron UMPs[/dim]")

    # --- Step 3: Clone UMPs (fallback multi-patron segun tipo del servicio) ---
    if ump_names:
        console.print("\n[bold]3. Clonando UMPs...[/bold]")
        for ump in ump_names:
            resolved, proj, repo_name = _resolve_ump_repo(
                ump, ws, shallow=shallow, parent_kind=pre_kind
            )
            if resolved:
                console.print(
                    f"  [green]OK[/green] {proj}/{repo_name}"
                )
            else:
                console.print(
                    f"  [yellow]SKIP[/yellow] {ump}: no encontrado en "
                    f"ninguno de los patrones ({pre_kind} parent)"
                )

    # --- Step 4: Analyze (UMPs -> TX codes) ---
    console.print("\n[bold]4. Analizando WSDL + extrayendo TX codes de UMPs clonados...[/bold]")
    analysis = analyze_legacy(
        legacy_dest,
        service_name=service_name,
        umps_root=ws / "umps" if ump_names else None,
    )

    all_tx_codes: set[str] = set()
    for u in analysis.umps:
        all_tx_codes.update(u.tx_codes)
    console.print(
        f"  [green]OK[/green] {len(all_tx_codes)} TX code(s) extraidos: "
        f"{', '.join(sorted(all_tx_codes)) or '(ninguno)'}"
    )

    # --- Step 5: Clone TX repos ---
    tx_results: list[TxCloneResult] = []
    if not skip_tx and all_tx_codes:
        console.print(f"\n[bold]5. Clonando repos de TX individuales[/bold] ({len(all_tx_codes)} repos)...")
        tx_results = _clone_tx_repos(all_tx_codes, ws, shallow=True)
        for tr in tx_results:
            if tr.status == "cloned":
                console.print(f"  [green]OK[/green] sqb-cfg-{tr.tx_code}-TX")
            elif tr.status == "not_found":
                console.print(f"  [yellow]NO EXISTE[/yellow] sqb-cfg-{tr.tx_code}-TX (posible legacy sin repo propio)")
            else:
                console.print(f"  [red]ERROR[/red] sqb-cfg-{tr.tx_code}-TX: {tr.error[:50]}")
    elif skip_tx:
        console.print("\n[dim]5. TX repos saltados (--skip-tx)[/dim]")
    else:
        console.print("\n[dim]5. No hay TX codes extraidos para clonar[/dim]")

    # --- Step 6: Report ---
    discovery_entry = None
    from capamedia_cli.core.discovery import find_discovery_workbook, load_discovery_entry

    resolved_discovery = find_discovery_workbook(ws, explicit=discovery_xlsx)
    if resolved_discovery:
        try:
            discovery_entry = load_discovery_entry(
                resolved_discovery,
                service_name,
                sheet_name=discovery_sheet,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            console.print(f"[yellow]Discovery:[/yellow] no se pudo leer {resolved_discovery}: {exc}")
        if discovery_entry is None:
            console.print(f"[yellow]Discovery:[/yellow] {service_name} no encontrado en {resolved_discovery}")
        else:
            console.print(
                "[green]Discovery[/green] "
                f"{len(discovery_entry.edge_cases)} edge case(s), "
                f"spec path: {discovery_entry.spec_path or '?'}"
            )

    report = _write_complexity_report(
        analysis,
        service_name,
        ws,
        tx_results,
        legacy_root=legacy_dest,
        discovery_entry=discovery_entry,
    )
    console.print(f"\n[bold]6. Reporte[/bold] escrito en [cyan]{report.name}[/cyan]")

    # --- Step 7: Deep-scan Azure DevOps (opcional, --deep-scan) ---
    if deep_scan:
        console.print("\n[bold]7. Deep-scan Azure DevOps Code Search[/bold]")
        _run_deep_scan(
            service_name=service_name,
            workspace=ws,
            wsdl_namespace=(analysis.wsdl.target_namespace if analysis.wsdl else None),
            tx_codes=sorted(all_tx_codes),
            umps=[u.name for u in analysis.umps],
        )

    # --- Step 8: Properties references report (v0.19.0) ---
    _write_properties_report(analysis, ws)
    _show_properties_table(analysis)

    # --- Step 9: Secrets audit (v0.23.0) — solo WAS con BD ---
    _write_secrets_report(analysis, ws, legacy_dest)
    _show_secrets_table(analysis, ws, legacy_dest)

    # --- Final summary table ---
    console.print()
    table = Table(title=f"Resumen: {service_name}", title_style="bold green")
    table.add_column("Dimension", style="cyan")
    table.add_column("Valor", style="bold")
    table.add_row("Tipo de fuente", analysis.source_kind.upper())
    table.add_row("Operaciones WSDL", str(analysis.wsdl.operation_count) if analysis.wsdl else "?")
    table.add_row("Framework recomendado", analysis.framework_recommendation.upper() or "?")
    table.add_row("UMPs detectados", str(len(analysis.umps)))
    table.add_row("UMPs con TX extraido", f"{sum(1 for u in analysis.umps if u.tx_codes)}/{len(analysis.umps)}")
    table.add_row("TX codes unicos", str(len(all_tx_codes)))
    table.add_row("TX repos clonados", f"{sum(1 for t in tx_results if t.status == 'cloned')}/{len(tx_results)}")
    table.add_row("BD presente", "SI" if analysis.has_database else "NO")
    table.add_row("Complejidad", analysis.complexity.upper())
    pending_props = sum(
        1 for p in analysis.properties_refs if p.status == "PENDING_FROM_BANK"
    )
    table.add_row(
        ".properties pendientes del banco",
        f"[bold red]{pending_props}[/bold red]" if pending_props else "[green]0[/green]",
    )
    console.print(table)

    if pending_props > 0:
        console.print(
            f"\n[bold yellow]ATENCION:[/bold yellow] hay [bold red]{pending_props}[/bold red] "
            ".properties especificos del servicio/UMP que NO estan en el repo. "
            "Antes de [cyan]capamedia ai migrate[/cyan], pedir estos archivos al owner del "
            "servicio para evitar placeholders en application.yml.\n"
            f"  Detalle: [cyan].capamedia/properties-report.yaml[/cyan]"
        )

    # --- Step 10: Init automatico si --init fue pasado (v0.23.0) ---
    if init:
        console.print("\n[bold]9. Init automatico (--init)[/bold]")
        try:
            from capamedia_cli.commands.init import scaffold_project
            from capamedia_cli.harnesses import resolve_harnesses

            harnesses = resolve_harnesses(init_ai)
            total, warnings = scaffold_project(
                target_dir=ws,
                service_name=service_name,
                harnesses=harnesses,
            )
            console.print(
                f"  [green]OK[/green] init completado: {total} archivos "
                f"({', '.join(harnesses)})"
            )
            for w in warnings[:5]:
                console.print(f"  [yellow]warn[/yellow] {w}")
        except Exception as exc:
            console.print(
                f"  [red]FAIL[/red] init automatico fallo: {exc}\n"
                "  Ejecutalo manualmente: "
                f"[cyan]capamedia init {service_name} --ai {init_ai}[/cyan]"
            )

    console.print("\n[bold]Siguiente paso:[/bold]")
    if init:
        console.print("  [cyan]capamedia fabrics generate[/cyan]  (desde este mismo workspace)")
    else:
        console.print("  [cyan]capamedia fabrics generate[/cyan]  (desde este mismo workspace)")


def clone_migrated_service(
    service_name: Annotated[
        str,
        typer.Argument(help="Nombre del servicio (ej: wsclientes0076, wstecnicos0006)"),
    ],
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Carpeta raiz del workspace (default: CWD)",
        ),
    ] = None,
    namespace: Annotated[
        str | None,
        typer.Option(
            "--namespace",
            "-n",
            help="Namespace migrado a clonar. Si se omite, prueba tnd/tpr/csg/tmp/tia/tct.",
        ),
    ] = None,
    branch: Annotated[
        str | None,
        typer.Option(
            "--branch",
            "-b",
            help="Rama del repo migrado a dejar checked out (ej: feature/dev-BTHCCC-5077).",
        ),
    ] = None,
    shallow: Annotated[
        bool,
        typer.Option("--shallow", help="Clone superficial (--depth 1) para ahorrar tiempo"),
    ] = False,
    skip_tx: Annotated[
        bool,
        typer.Option("--skip-tx", help="No clonar los repos de TX individuales del clone base"),
    ] = False,
    deep_scan: Annotated[
        bool,
        typer.Option("--deep-scan", help="Ejecutar deep-scan igual que `capamedia clone`"),
    ] = False,
    init: Annotated[
        bool,
        typer.Option("--init", help="Ejecutar init automatico igual que `capamedia clone --init`"),
    ] = False,
    init_ai: Annotated[
        str,
        typer.Option("--init-ai", help="Harness AI para el init automatico. Solo se usa si --init esta activo."),
    ] = "claude",
) -> None:
    """Clona legacy/UMPs/TX y tambien el repo migrado existente en tpl-middleware."""
    ws = workspace or Path.cwd()
    ws.mkdir(parents=True, exist_ok=True)

    original_name = service_name
    service_name, was_padded = normalize_service_name(service_name)
    if was_padded:
        console.print(
            f"[yellow]Tip:[/yellow] [cyan]{original_name}[/cyan] -> "
            f"[cyan]{service_name}[/cyan] (auto-padded a 4 digitos)"
        )

    console.print(
        Panel.fit(
            f"[bold]CapaMedia clone-migrated[/bold]\n"
            f"Servicio: [cyan]{service_name}[/cyan]\n"
            f"Workspace: [cyan]{ws}[/cyan]",
            border_style="cyan",
        )
    )

    console.print("\n[bold]A. Clone base legacy + UMPs + TX[/bold]")
    clone_service(
        service_name,
        workspace=ws,
        shallow=shallow,
        skip_tx=skip_tx,
        deep_scan=deep_scan,
        init=init,
        init_ai=init_ai,
    )

    console.print("\n[bold]B. Clonando repos migrados desde tpl-middleware[/bold]")
    results = _clone_migrated_repos(
        service_name,
        ws,
        shallow=shallow,
        namespace=namespace,
        branch=branch,
    )

    found = [r for r in results if r.status in {"cloned", "already_present"}]
    table = Table(title="Migrados detectados", title_style="bold cyan")
    table.add_column("Namespace", style="cyan")
    table.add_column("Repo")
    table.add_column("Status", style="bold")
    table.add_column("Branch")
    table.add_column("Path / detalle")

    for r in results:
        if r.status == "cloned":
            status = "[green]clonado[/green]"
        elif r.status == "already_present":
            status = "[cyan]existente[/cyan]"
        elif r.status == "not_found":
            status = "[yellow]no existe[/yellow]"
        else:
            status = "[red]error[/red]"
        detail = str(r.path) if r.path else r.error[:90]
        if r.error and r.path:
            detail = f"{detail} ({r.error[:80]})"
        table.add_row(r.namespace, r.repo_name, status, r.branch or "-", detail)
    console.print(table)

    if not found:
        console.print(
            "\n[red]FAIL[/red] no se encontro ningun repo migrado en tpl-middleware "
            "para este servicio. Si conoces el namespace exacto, reintenta con "
            "`--namespace <tnd|tpr|csg|tmp|tia|tct>`."
        )
        raise typer.Exit(1)

    console.print("\n[bold]Workspace listo:[/bold]")
    console.print(f"  Legacy : [cyan]{ws / 'legacy'}[/cyan]")
    console.print(f"  Migrado: [cyan]{ws / 'destino'}[/cyan]")
    console.print("\n[bold]Siguiente paso sugerido:[/bold]")
    console.print("  [cyan]capamedia ai doublecheck --engine codex[/cyan]")
    console.print("  [cyan]capamedia review[/cyan]")


# ---------------------------------------------------------------------------
# Properties references report (v0.19.0)
# ---------------------------------------------------------------------------


_STATUS_ICONS = {
    "SHARED_CATALOG": "✓",
    "SAMPLE_IN_REPO": "✓",
    "PENDING_FROM_BANK": "✗",
}


_STATUS_DESCRIPTIONS = {
    "SHARED_CATALOG": "[green]resuelto por catalogo embebido (v0.18.0)[/green]",
    "SAMPLE_IN_REPO": "[cyan]sample encontrado en repo[/cyan]",
    "PENDING_FROM_BANK": "[bold red]PENDIENTE - pedir al owner del servicio[/bold red]",
}


def _show_properties_table(analysis) -> None:
    """Muestra tabla con los .properties referenciados y su estado."""
    if not analysis.properties_refs:
        return

    console.print("\n[bold]7. Properties referenciados por el legacy[/bold]")
    table = Table(title=".properties detectados", title_style="bold cyan")
    table.add_column("Archivo", style="cyan", no_wrap=True)
    table.add_column("Estado")
    table.add_column("Origen", style="dim")
    table.add_column("# Keys", justify="right")

    for p in analysis.properties_refs:
        icon = _STATUS_ICONS.get(p.status, "?")
        desc = _STATUS_DESCRIPTIONS.get(p.status, p.status)
        table.add_row(
            f"{icon} {p.file_name}",
            desc,
            p.source_hint or "-",
            str(len(p.keys_used)),
        )
    console.print(table)


def _write_properties_report(analysis, ws: Path) -> Path | None:
    """Persiste el reporte de properties en .capamedia/properties-report.yaml."""
    if not analysis.properties_refs:
        return None

    capamedia_dir = ws / ".capamedia"
    capamedia_dir.mkdir(exist_ok=True)
    out = capamedia_dir / "properties-report.yaml"

    data = {
        "generated_by": "capamedia clone",
        "shared_catalog_embedded": [
            "generalservices.properties",
            "catalogoaplicaciones.properties",
        ],
        "service_specific_properties": [
            {
                "file": p.file_name,
                "status": p.status,
                "source": p.source_hint,
                "physical_path_hint": p.physical_path_hint,
                "referenced_from": p.referenced_from[:10],
                "keys_used": p.keys_used,
                "sample_values": p.sample_values if p.status == "SAMPLE_IN_REPO" else {},
                "action": _action_for_status(p.status),
            }
            for p in analysis.properties_refs
            if p.status != "SHARED_CATALOG"
        ],
        "shared_catalog_keys_used": {
            p.file_name: p.keys_used
            for p in analysis.properties_refs
            if p.status == "SHARED_CATALOG"
        },
    }

    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, width=100)

    return out


def _action_for_status(status: str) -> str:
    if status == "PENDING_FROM_BANK":
        return (
            "Pedir al owner del servicio antes de capamedia ai migrate. "
            "Sin este archivo, las keys quedan como ${CCC_*} placeholder en application.yml."
        )
    if status == "SAMPLE_IN_REPO":
        return (
            "Usar los sample_values como defaults en application.yml. "
            "El owner puede confirmar si cambian por ambiente (dev/test/prod)."
        )
    if status == "SHARED_CATALOG":
        return "No action - valores literales embebidos en bank-shared-properties.md"
    return ""


# ---------------------------------------------------------------------------
# Secrets audit (v0.23.0) - WAS con BD
# ---------------------------------------------------------------------------


def _show_secrets_table(analysis, ws: Path, legacy_dest: Path) -> None:
    """Muestra tabla con secretos KV requeridos (si el servicio los necesita)."""
    from capamedia_cli.core.secrets_detector import audit_secrets

    umps_roots = []
    umps_base = ws / "umps"
    if umps_base.is_dir():
        for u in analysis.umps:
            if u.repo_path and u.repo_path.exists():
                umps_roots.append(u.repo_path)

    audit = audit_secrets(
        legacy_dest,
        umps_roots=umps_roots,
        service_kind=analysis.source_kind,
        has_database=analysis.has_database,
    )

    if not audit.applies:
        return  # BUS / ORQ / WAS-sin-BD no generan tabla

    console.print("\n[bold]8. Secretos Azure Key Vault (WAS con BD)[/bold]")
    table = Table(title="Secretos requeridos (BPTPSRE-Secretos)", title_style="bold cyan")
    table.add_column("JNDI legacy", style="cyan", no_wrap=True)
    table.add_column("BD", style="dim")
    table.add_column("Secreto USER")
    table.add_column("Secreto PASSWORD")

    for sr in audit.secrets_required:
        table.add_row(
            sr.jndi, sr.db_label, sr.user_secret, sr.password_secret,
        )
    console.print(table)

    if audit.jndi_references_unknown:
        unique = sorted({h.jndi for h in audit.jndi_references_unknown})
        console.print(
            f"\n[yellow]Aviso:[/yellow] {len(unique)} JNDI detectado(s) pero "
            "NO estan en el catalogo oficial: "
            f"[dim]{', '.join(unique)}[/dim]\n"
            "  Consultar con SRE y/o agregar al catalogo en "
            "[cyan]bank-secrets.md[/cyan] si es un JNDI nuevo."
        )


def _write_secrets_report(analysis, ws: Path, legacy_dest: Path) -> Path | None:
    """Persiste el reporte de secretos KV en .capamedia/secrets-report.yaml."""
    from capamedia_cli.core.secrets_detector import audit_secrets

    umps_roots = []
    umps_base = ws / "umps"
    if umps_base.is_dir():
        for u in analysis.umps:
            if u.repo_path and u.repo_path.exists():
                umps_roots.append(u.repo_path)

    audit = audit_secrets(
        legacy_dest,
        umps_roots=umps_roots,
        service_kind=analysis.source_kind,
        has_database=analysis.has_database,
    )

    if not audit.applies:
        return None  # no genera archivo si no aplica

    capamedia_dir = ws / ".capamedia"
    capamedia_dir.mkdir(exist_ok=True)
    out = capamedia_dir / "secrets-report.yaml"

    data = {
        "generated_by": "capamedia clone",
        "service_kind": audit.service_kind,
        "has_database": audit.has_database,
        "secrets_required": [
            {
                "base_de_datos": sr.db_label,
                "jndi": sr.jndi,
                "user_secret": sr.user_secret,
                "password_secret": sr.password_secret,
                "detected_from": sr.detected_from[:10],
            }
            for sr in audit.secrets_required
        ],
        "jndi_references_unknown": [
            {"jndi": h.jndi, "source_file": h.source_file, "source_kind": h.source_kind}
            for h in audit.jndi_references_unknown[:20]
        ],
    }

    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, width=100)

    return out
