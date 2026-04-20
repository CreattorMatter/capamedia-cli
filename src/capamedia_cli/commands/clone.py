"""capamedia clone <servicio> - clonado determinista de legacy + UMPs + TX + gold.

Version shell del slash command /clone. Hace exactamente lo mismo que la AI haria,
pero sin AI - solo git, grep y regex.

Estructura generada:
  CWD/
    legacy/sqb-msa-<servicio>/
    umps/sqb-msa-umpclientes<NNNN>/
    tx/sqb-cfg-<NNNNNN>-TX/               <- NUEVO en v0.2.1: repo por cada TX code
    catalogs/sqb-cfg-codigosBackend-config/  <- antes era tx/, renombrado
    catalogs/sqb-cfg-errores-errors/
    gold-ref/tnd-msa-sp-wsclientes0024/   (o 0015)
    COMPLEXITY_<servicio>.md
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli.core.legacy_analyzer import analyze_legacy

console = Console()

AZURE_ORG = "BancoPichinchaEC"

# Mapeo de tipo de repo -> proyecto Azure DevOps (verificado sobre repos reales del banco)
AZURE_PROJECTS = {
    "bus": "tpl-bus-omnicanal",          # legacy + UMPs (IIB)
    "config": "tpl-integrationbus-config",  # TX repos + catalogos
    "middleware": "tpl-middleware",      # gold references (tnd-msa-sp-*)
}


def _azure_url(project_key: str, repo_name: str) -> str:
    """Build the Azure DevOps clone URL for a given project key."""
    project = AZURE_PROJECTS[project_key]
    return f"https://dev.azure.com/{AZURE_ORG}/{project}/_git/{repo_name}"


CATALOG_REPOS = ["sqb-cfg-codigosBackend-config", "sqb-cfg-errores-errors"]
GOLD_REST = "tnd-msa-sp-wsclientes0024"
GOLD_SOAP = "tnd-msa-sp-wsclientes0015"


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

    `project_key` debe ser "bus" | "config" | "middleware" segun donde vive el repo.
    """
    if dest.exists() and any(dest.iterdir()):
        return (True, "already cloned")
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = _azure_url(project_key, repo_name)
    cmd = ["git", "clone"]
    if shallow:
        cmd += ["--depth", "1"]
    cmd += [url, str(dest)]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
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
    svc = service_name.lower()
    return f"sqb-msa-{svc}"


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
) -> Path:
    """Write COMPLEXITY_<service>.md with the deterministic analysis."""
    dest = workspace / f"COMPLEXITY_{service_name}.md"
    lines: list[str] = []
    lines.append(f"# Complexity Report: {service_name}\n")
    lines.append("Generado por `capamedia clone` (v0.2.1). Sin AI - solo analisis determinista.\n")
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
                nota = "No visto en ESQL. Mirar `deploy-*-config.bat` o `catalogs/sqb-cfg-codigosBackend-config/`"
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

    lines.append("## Proximo paso")
    lines.append("")
    lines.append("- Abri este workspace en Claude Code / Cursor / Windsurf")
    lines.append("- Ejecuta `/fabric` en el chat para generar el arquetipo")
    lines.append("- Alternativamente, corre `capamedia fabrics generate` en shell para armar el prompt")
    lines.append("")

    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


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
    skip_catalogs: Annotated[
        bool,
        typer.Option("--skip-catalogs", help="No clonar los catalogos (codigosBackend, errores)"),
    ] = False,
    skip_tx: Annotated[
        bool,
        typer.Option("--skip-tx", help="No clonar los repos de TX individuales (sqb-cfg-<TX>-TX)"),
    ] = False,
    skip_gold: Annotated[
        bool,
        typer.Option("--skip-gold", help="No clonar el gold standard reference"),
    ] = False,
) -> None:
    """Clona el legacy + UMPs + TX repos + catalogos + gold reference y analiza complejidad."""
    ws = workspace or Path.cwd()
    ws.mkdir(parents=True, exist_ok=True)

    console.print(
        Panel.fit(
            f"[bold]CapaMedia clone[/bold]\nServicio: [cyan]{service_name}[/cyan]\nWorkspace: [cyan]{ws}[/cyan]",
            border_style="cyan",
        )
    )

    # --- Step 1: Clone legacy ---
    legacy_repo = _resolve_legacy_repo_name(service_name)
    legacy_dest = ws / "legacy" / legacy_repo
    console.print(f"\n[bold]1. Clonando legacy[/bold] {legacy_repo}...")
    ok, err = _git_clone(legacy_repo, legacy_dest, project_key="bus", shallow=shallow)
    if not ok:
        console.print(f"[red]FAIL[/red] clone legacy: {err}")
        console.print(
            "[yellow]Tip:[/yellow] corre 'git clone' manual una vez para cachear el PAT via GCM, "
            "luego reintenta."
        )
        raise typer.Exit(1)
    console.print(f"[green]OK[/green] legacy clonado en {legacy_dest}")

    # --- Step 2: Detect UMPs ---
    console.print("\n[bold]2. Detectando UMPs referenciados en ESQL/msgflow...[/bold]")
    from capamedia_cli.core.legacy_analyzer import detect_ump_references

    ump_names = detect_ump_references(legacy_dest)
    if ump_names:
        console.print(f"[green]OK[/green] {len(ump_names)} UMP(s) detectado(s): {', '.join(ump_names)}")
    else:
        console.print("[dim]No se detectaron UMPs (servicio standalone o WAS)[/dim]")

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
    console.print(f"  [green]OK[/green] {len(all_tx_codes)} TX code(s) extraidos: {', '.join(sorted(all_tx_codes)) or '(ninguno)'}")

    # --- Step 5: Clone TX repos (nuevo en v0.2.1) ---
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

    # --- Step 6: Clone catalogs (renamed from tx/ in v0.2.1) ---
    if not skip_catalogs:
        console.print("\n[bold]6. Clonando catalogos comunes (codigosBackend, errores)...[/bold]")
        for cat in CATALOG_REPOS:
            cat_dest = ws / "catalogs" / cat
            ok, err = _git_clone(cat, cat_dest, project_key="config", shallow=True)
            if ok:
                console.print(f"  [green]OK[/green] {cat}")
            else:
                console.print(f"  [yellow]SKIP[/yellow] {cat}: {err}")
    else:
        console.print("\n[dim]6. Catalogos saltados (--skip-catalogs)[/dim]")

    # --- Step 7: Gold reference ---
    if not skip_gold and analysis.framework_recommendation:
        gold = GOLD_REST if analysis.framework_recommendation == "rest" else GOLD_SOAP
        gold_dest = ws / "gold-ref" / gold
        console.print(f"\n[bold]7. Clonando gold reference[/bold] {gold}...")
        ok, err = _git_clone(gold, gold_dest, project_key="middleware", shallow=True)
        if ok:
            console.print(f"  [green]OK[/green] {gold}")
        else:
            console.print(f"  [yellow]SKIP[/yellow] {gold}: {err}")

    # --- Step 8: Report ---
    report = _write_complexity_report(analysis, service_name, ws, tx_results)
    console.print(f"\n[bold]8. Reporte[/bold] escrito en [cyan]{report.name}[/cyan]")

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
