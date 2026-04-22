"""capamedia clone <servicio> - clonado determinista de legacy + UMPs + TX.

Trae solo lo especifico del servicio:
  CWD/
    legacy/sqb-msa-<servicio>/            (codigo legacy IIB o WAS)
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
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
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


# Combinaciones (proyecto, patron) probadas en orden cuando un servicio no esta local.
# Patron usa {svc} como placeholder para el nombre lowercase del servicio.
AZURE_FALLBACK_PATTERNS: list[tuple[str, str]] = [
    ("bus", "sqb-msa-{svc}"),                # IIB tipico
    ("was", "ws-{svc}-was"),                 # WAS tipico
    ("was", "ms-{svc}-was"),                 # WAS variante "ms"
    ("middleware", "tnd-msa-sp-{svc}"),     # gold REST/SOAP migrado
    ("middleware", "tia-msa-sp-{svc}"),     # gold variante tia
    ("middleware", "tpr-msa-sp-{svc}"),     # gold variante tpr
    ("middleware", "csg-msa-sp-{svc}"),     # gold variante csg
]


def _resolve_azure_repo(service_name: str, dest_root: Path, shallow: bool) -> tuple[Path | None, str, str]:
    """Intenta clonar el servicio probando todos los patrones Azure conocidos.

    Returns:
      (path_clonado, project_key, repo_name) o (None, "", "") si nada funciona.
    """
    svc = service_name.lower()
    for project_key, pattern in AZURE_FALLBACK_PATTERNS:
        repo_name = pattern.format(svc=svc)
        dest = dest_root / "legacy" / repo_name
        ok, err = _git_clone(repo_name, dest, project_key=project_key, shallow=shallow)
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


def _git_clone(repo_name: str, dest: Path, project_key: str = "bus", shallow: bool = False) -> tuple[bool, str]:
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
        return (False, result.stderr.strip().split("\n")[-1] if result.stderr else "unknown error")
    except subprocess.TimeoutExpired:
        return (False, "timeout")
    except FileNotFoundError:
        return (False, "git no disponible en PATH")


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
    lines.append("- Abri este workspace en Claude Code / Cursor / Windsurf")
    lines.append("- Ejecuta `/fabric` en el chat para generar el arquetipo")
    lines.append("- Alternativamente, corre `capamedia fabrics generate` en shell para armar el prompt")
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
) -> None:
    """Clona el legacy + UMPs + TX repos y analiza complejidad del servicio."""
    ws = workspace or Path.cwd()
    ws.mkdir(parents=True, exist_ok=True)

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

    # --- Step 3: Clone UMPs ---
    if ump_names:
        console.print("\n[bold]3. Clonando UMPs...[/bold]")
        for ump in ump_names:
            ump_repo = f"sqb-msa-{ump.lower()}"
            ump_dest = ws / "umps" / ump_repo
            ok, err = _git_clone(ump_repo, ump_dest, project_key="bus", shallow=shallow)
            if ok:
                console.print(f"  [green]OK[/green] {ump_repo}")
            else:
                console.print(f"  [yellow]SKIP[/yellow] {ump_repo}: {err}")

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
    report = _write_complexity_report(analysis, service_name, ws, tx_results, legacy_root=legacy_dest)
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
    console.print(table)

    console.print("\n[bold]Siguiente paso:[/bold]")
    console.print("  Abri el workspace en tu IDE (Claude Code, Cursor, Windsurf)")
    console.print("  Ejecuta [cyan]/fabric[/cyan] en el chat, o [cyan]capamedia fabrics generate[/cyan] en shell")
