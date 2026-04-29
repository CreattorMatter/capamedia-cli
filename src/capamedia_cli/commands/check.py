"""capamedia check - corre el checklist BPTPSRE deterministico sobre un proyecto migrado.

Ejecuta todos los BLOQUES de `core/checklist_rules.py` sin AI y genera:
  - CHECKLIST_<servicio>.md con dialogo conversacional y severidad
  - Exit code 0 si todo PASS o solo MEDIUM/LOW
  - Exit code 1 si hay HIGH
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli.core.autofix import run_autofix_loop
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


def _populate_mcp_context(
    migrated_path: Path,
    legacy_path: Path | None,
    service_name: str,
) -> CheckContext:
    """Build a CheckContext with source_type + has_bancs populated from the
    legacy (v0.22.0). Alimenta la matriz MCP-driven del Block 0.

    Si no hay legacy disponible, los campos quedan en "" / False y Block 0
    cae al fallback por conteo de ops (comportamiento legacy).
    """
    source_type = ""
    has_bancs = False

    if legacy_path and legacy_path.is_dir():
        try:
            from capamedia_cli.core.legacy_analyzer import (
                detect_bancs_connection,
                detect_source_kind,
            )

            source_type = detect_source_kind(legacy_path, service_name)
            has_bancs, _ = detect_bancs_connection(legacy_path)
        except Exception:
            # Fallback silencioso: si algo falla en la deteccion, el Block 0
            # usa el fallback por conteo de ops.
            pass

    return CheckContext(
        migrated_path=migrated_path,
        legacy_path=legacy_path,
        source_type=source_type,
        has_bancs=has_bancs,
    )


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
    auto_fix: Annotated[
        bool,
        typer.Option(
            "--auto-fix",
            help=(
                "Aplica fixes deterministicos para HIGH/MEDIUM autofixeables "
                "(hasta 3 rondas). Lo que no converja queda NEEDS_HUMAN."
            ),
        ),
    ] = False,
    bank_fix: Annotated[
        bool,
        typer.Option(
            "--bank-fix",
            help=(
                "Ademas de --auto-fix, aplica los 4 autofixes del script oficial "
                "del banco (reglas 4, 7, 8, 9). Requiere --auto-fix."
            ),
        ),
    ] = False,
    bank_description: Annotated[
        str | None,
        typer.Option(
            "--bank-description",
            help="Descripcion del servicio para el catalog-info.yaml (regla 9)",
        ),
    ] = None,
    bank_owner: Annotated[
        str | None,
        typer.Option(
            "--bank-owner",
            help="Email @pichincha.com para spec.owner del catalog-info.yaml",
        ),
    ] = None,
) -> None:
    """Corre el checklist BPTPSRE deterministico y escribe CHECKLIST_*.md."""
    migrated_path, legacy_path = _resolve_paths(migrated, legacy)
    service = _read_service_name(migrated_path)

    console.print(
        Panel.fit(
            f"[bold]CapaMedia check[/bold]\n"
            f"Migrated: [cyan]{migrated_path}[/cyan]\n"
            f"Legacy:   [cyan]{legacy_path or '(no provisto - 0.3/0.4 se saltan)'}[/cyan]\n"
            f"Servicio: [cyan]{service}[/cyan]\n"
            f"Auto-fix: [cyan]{'on' if auto_fix else 'off'}[/cyan]",
            border_style="cyan",
        )
    )

    # v0.22.0: auto-populate source_type + has_bancs desde el legacy (si existe).
    # Esto alimenta la matriz MCP-driven del Block 0.
    def _build_context() -> CheckContext:
        return _populate_mcp_context(migrated_path, legacy_path, service)

    def _run() -> list:
        return run_all_blocks(_build_context())

    autofix_report = None
    if auto_fix:
        log_dir = migrated_path / ".capamedia" / "autofix"
        autofix_report = run_autofix_loop(migrated_path, _run, log_dir=log_dir)
        console.print(
            f"[bold]Autofix:[/bold] {autofix_report.total_applied} fix(es) aplicado(s) "
            f"en {autofix_report.iterations} iteracion(es); "
            f"{'CONVERGED' if autofix_report.converged else 'NEEDS_HUMAN'}"
        )
        if autofix_report.log_path:
            console.print(f"[dim]Log: {autofix_report.log_path}[/dim]")

        # --bank-fix encadena los 4 autofixes del script oficial
        if bank_fix:
            from capamedia_cli.core.bank_autofix import run_bank_autofix

            bank_ctx = _build_context()
            bank_results = run_bank_autofix(
                migrated_path,
                description=bank_description,
                owner=bank_owner,
                source_type=bank_ctx.source_type,
                has_bancs=bank_ctx.has_bancs,
            )
            applied = sum(1 for r in bank_results if r.applied)
            console.print(
                f"[bold]Bank autofix:[/bold] {applied}/{len(bank_results)} "
                f"reglas oficiales aplicadas (4, 7, 8, 9)"
            )
            for r in bank_results:
                style = "green" if r.applied else "dim"
                status = "applied" if r.applied else "skip"
                console.print(
                    f"  - Regla {r.rule}: [{style}]{status}[/{style}]"
                    + (f" - {r.notes}" if r.notes else "")
                )

    ctx = _build_context()
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

    if autofix_report is not None:
        auto_ids = [r["check_id"] for r in autofix_report.remaining if r["autofixable"]]
        manual_ids = [r["check_id"] for r in autofix_report.remaining if not r["autofixable"]]
        console.print(
            f"[dim]Autofix breakdown: applied={autofix_report.total_applied} "
            f"still-autofixable={len(auto_ids)} needs-human={len(manual_ids)}[/dim]"
        )
        if auto_ids:
            console.print(f"[dim]  no converge: {sorted(set(auto_ids))}[/dim]")
        if manual_ids:
            console.print(f"[dim]  sin autofix: {sorted(set(manual_ids))}[/dim]")

    if total_high > 0 or (fail_on_medium and total_medium > 0):
        raise typer.Exit(1)


def checklist_project(
    migrated: Annotated[
        Path | None,
        typer.Argument(help="Path al proyecto migrado (default: CWD)"),
    ] = None,
    legacy: Annotated[
        Path | None,
        typer.Option("--legacy", "-l", help="Path al legacy para cross-check del BLOQUE 0"),
    ] = None,
    bank_description: Annotated[
        str | None,
        typer.Option("--bank-description", help="Descripcion para catalog-info.yaml (regla 9)"),
    ] = None,
    bank_owner: Annotated[
        str | None,
        typer.Option("--bank-owner", help="Email @pichincha.com para spec.owner (regla 9)"),
    ] = None,
    fail_on_medium: Annotated[
        bool,
        typer.Option("--fail-on-medium", help="Exit 1 tambien si hay findings MEDIUM residuales"),
    ] = False,
) -> None:
    """Checklist (doble check): `check` + autofixes completos en una linea (v0.23.0).

    Equivale a `capamedia check --auto-fix --bank-fix`. Aplica TODO lo
    autofixeable de nuestras reglas + las 4 reglas deterministas del banco
    (4, 7, 8, 9). Lo que queda como FAIL es lo que NO se puede resolver
    automaticamente (ej. sonarcloud project-key, URLs Confluence, etc) —
    eso queda marcado como blocker de handoff al owner, no bug del codigo.
    """
    check_project(
        migrated=migrated,
        legacy=legacy,
        fail_on_medium=fail_on_medium,
        auto_fix=True,
        bank_fix=True,
        bank_description=bank_description,
        bank_owner=bank_owner,
    )
