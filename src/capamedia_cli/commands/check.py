"""capamedia check - corre el checklist BPTPSRE deterministico sobre un proyecto migrado.

Ejecuta todos los BLOQUES de `core/checklist_rules.py` sin AI y genera:
  - CHECKLIST_<servicio>.md con dialogo conversacional y severidad
  - Exit code 0 si todo PASS o solo MEDIUM/LOW
  - Exit code 1 si hay HIGH
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli.core.checklist_rules import CheckContext, run_all_blocks

console = Console()


def _resolve_paths(
    migrated: Path | None,
    legacy: Path | None,
) -> tuple[Path, Path | None]:
    """Resolve migrated and legacy paths with sensible defaults."""
    ctx_path = migrated or Path.cwd()
    ctx_path = ctx_path.resolve()

    # Auto-discover legacy if not given: sibling folder or parent/legacy/
    legacy_path: Path | None = legacy.resolve() if legacy else None
    if legacy_path is None:
        # Try common layouts
        candidates = [
            ctx_path.parent / "legacy",
            ctx_path.parent.parent / "legacy",
        ]
        for c in candidates:
            if c.exists() and c.is_dir():
                legacy_path = c
                break
    return ctx_path, legacy_path


def _read_service_name(migrated: Path) -> str:
    """Try to infer service name from .capamedia/config.yaml or folder name."""
    cfg = migrated / ".capamedia" / "config.yaml"
    if cfg.exists():
        try:
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            name = data.get("service_name")
            if name:
                return str(name)
        except (OSError, yaml.YAMLError):
            pass
    return migrated.name


def _write_report(service: str, results, migrated: Path, legacy: Path | None) -> Path:
    """Write CHECKLIST_<service>.md with summary + detailed findings."""
    dest = migrated / f"CHECKLIST_{service}.md"

    # Aggregate counts per block
    from collections import defaultdict
    by_block = defaultdict(lambda: {"pass": 0, "high": 0, "medium": 0, "low": 0})
    for r in results:
        if r.status == "pass":
            by_block[r.block]["pass"] += 1
        else:
            by_block[r.block][r.severity or "low"] += 1

    total_pass = sum(1 for r in results if r.status == "pass")
    total_high = sum(1 for r in results if r.status == "fail" and r.severity == "high")
    total_medium = sum(1 for r in results if r.status == "fail" and r.severity == "medium")
    total_low = sum(1 for r in results if r.status == "fail" and r.severity == "low")

    # Verdict
    if total_high > 0:
        verdict = "BLOCKED_BY_HIGH"
    elif total_medium > 0:
        verdict = "READY_WITH_FOLLOW_UP"
    else:
        verdict = "READY_TO_MERGE"

    lines: list[str] = []
    lines.append(f"# Post-Migration Checklist Report: {service}\n")
    lines.append(f"**Migrated path:** `{migrated}`")
    lines.append(f"**Legacy path:** `{legacy or '(no provisto)'}`")
    lines.append(f"**Verdict:** `{verdict}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Block | Pass | HIGH | MEDIUM | LOW |")
    lines.append("|---|---|---|---|---|")
    for block, counts in by_block.items():
        lines.append(f"| {block} | {counts['pass']} | {counts['high']} | {counts['medium']} | {counts['low']} |")
    lines.append(f"| **TOTAL** | **{total_pass}** | **{total_high}** | **{total_medium}** | **{total_low}** |")
    lines.append("")

    # Detail per check
    lines.append("## Detalle")
    lines.append("")
    current_block = None
    for r in results:
        if r.block != current_block:
            lines.append(f"\n### {r.block}\n")
            current_block = r.block
        icon = "PASS" if r.status == "pass" else f"FAIL-{r.severity.upper()}"
        lines.append(f"**{r.id} {r.title}** - `{icon}`")
        if r.detail:
            lines.append(f"  - Detail: {r.detail}")
        if r.suggested_fix:
            lines.append(f"  - Fix: {r.suggested_fix}")
        lines.append("")

    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def check_project(
    migrated: Annotated[
        Path | None,
        typer.Argument(help="Path al proyecto migrado (default: CWD)"),
    ] = None,
    legacy: Annotated[
        Path | None,
        typer.Option("--legacy", "-l", help="Path al legacy original para cross-check del BLOQUE 0"),
    ] = None,
    fail_on_medium: Annotated[
        bool,
        typer.Option("--fail-on-medium", help="Exit 1 tambien si hay findings MEDIUM"),
    ] = False,
) -> None:
    """Corre el checklist BPTPSRE deterministico y escribe CHECKLIST_*.md."""
    migrated_path, legacy_path = _resolve_paths(migrated, legacy)
    service = _read_service_name(migrated_path)

    console.print(
        Panel.fit(
            f"[bold]CapaMedia check[/bold]\n"
            f"Migrated: [cyan]{migrated_path}[/cyan]\n"
            f"Legacy:   [cyan]{legacy_path or '(no provisto - 0.3/0.4 se saltan)'}[/cyan]\n"
            f"Servicio: [cyan]{service}[/cyan]",
            border_style="cyan",
        )
    )

    ctx = CheckContext(migrated_path=migrated_path, legacy_path=legacy_path)
    results = run_all_blocks(ctx)

    # Render table
    table = Table(title="Resultados", title_style="bold cyan")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Block", style="dim")
    table.add_column("Title")
    table.add_column("Status", style="bold", width=8)
    table.add_column("Severidad", width=9)
    table.add_column("Detalle")

    for r in results:
        if r.status == "pass":
            status_str = "[green]PASS[/green]"
            sev_str = "-"
        else:
            status_str = "[red]FAIL[/red]"
            sev_str = f"[red]{r.severity.upper()}[/red]" if r.severity == "high" else f"[yellow]{r.severity.upper()}[/yellow]"
        table.add_row(r.id, r.block, r.title, status_str, sev_str, r.detail[:60])
    console.print(table)

    report_path = _write_report(service, results, migrated_path, legacy_path)
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{report_path}[/cyan]")

    # Verdict
    total_high = sum(1 for r in results if r.status == "fail" and r.severity == "high")
    total_medium = sum(1 for r in results if r.status == "fail" and r.severity == "medium")
    total_low = sum(1 for r in results if r.status == "fail" and r.severity == "low")

    if total_high > 0:
        verdict_color = "red"
        verdict = f"BLOCKED_BY_HIGH ({total_high} HIGH, {total_medium} MEDIUM, {total_low} LOW)"
    elif total_medium > 0:
        verdict_color = "yellow"
        verdict = f"READY_WITH_FOLLOW_UP ({total_medium} MEDIUM, {total_low} LOW)"
    else:
        verdict_color = "green"
        verdict = "READY_TO_MERGE"

    console.print(f"\n[bold {verdict_color}]Veredicto: {verdict}[/bold {verdict_color}]")

    if total_high > 0 or (fail_on_medium and total_medium > 0):
        raise typer.Exit(1)
