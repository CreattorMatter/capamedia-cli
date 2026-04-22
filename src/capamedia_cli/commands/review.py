"""capamedia review <path> - review end-to-end de un proyecto migrado externamente.

Diseñado para servicios migrados por el equipo usando los prompts de
CapaMedia **sin pasar por el CLI**. El comando apunta al proyecto terminado,
corre el checklist completo, aplica autofixes en loop, valida contra el
script oficial del banco y entrega un reporte consolidado.

Flujo:

    [Fase 1] Nuestro checklist (blocks 0/1/2/5/7/13/14/15/16)
             → autofix loop (hasta max_iterations o convergencia)
    [Fase 2] Bank autofix (reglas 4, 6, 7, 8, 9 del script oficial)
    [Fase 3] Re-corrida de nuestro checklist tras bank autofix
    [Fase 4] Validador oficial del banco (validate_hexagonal.py)
    [Fase 5] Reporte consolidado + verdicto global

Uso:

    capamedia review ./destino/tnd-msa-sp-wsclientes0007 \
        --legacy ./legacy/sqb-msa-wsclientes0007 \
        --bank-description "Consulta contacto transaccional" \
        --bank-owner jusoria@pichincha.com

Idempotente: se puede correr varias veces. No toca nada si no encuentra FAILs
autofixeables.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli.core.autofix import run_autofix_loop
from capamedia_cli.core.bank_autofix import run_bank_autofix
from capamedia_cli.core.checklist_rules import CheckContext, run_all_blocks

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summarize_results(results: list) -> dict[str, int]:
    """Cuenta status + severidad de los CheckResults."""
    summary = {"pass": 0, "fail_high": 0, "fail_medium": 0, "fail_low": 0}
    for r in results:
        if r.status == "pass":
            summary["pass"] += 1
        else:
            key = f"fail_{(r.severity or 'low').lower()}"
            summary[key] = summary.get(key, 0) + 1
    return summary


def _verdict_from_summary(summary: dict[str, int]) -> str:
    """READY_TO_MERGE | READY_WITH_FOLLOW_UP | BLOCKED_BY_HIGH."""
    if summary.get("fail_high", 0) > 0:
        return "BLOCKED_BY_HIGH"
    if summary.get("fail_medium", 0) > 0:
        return "READY_WITH_FOLLOW_UP"
    return "READY_TO_MERGE"


def _run_official_validator(project_path: Path) -> tuple[int, int, str]:
    """Invoca el validador oficial del banco via subprocess.

    Retorna (passed, total, report_path). El report_path queda en el
    proyecto para que el usuario lo lea. Si falla el invocado, retorna
    (0, 0, "") y muestra el error.
    """
    script = (
        Path(__file__).resolve().parent.parent
        / "data" / "vendor" / "validate_hexagonal.py"
    )
    if not script.exists():
        console.print(
            f"[red]vendor script no encontrado:[/red] {script}. "
            "Correr `capamedia validate-hexagonal sync --from <path>`."
        )
        return (0, 0, "")

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    try:
        result = subprocess.run(
            [sys.executable, str(script), str(project_path), "--threshold", "3"],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        console.print(f"[red]fallo invocando validador oficial:[/red] {exc}")
        return (0, 0, "")

    # El script imprime "Resultado: N/M checks pasados" al final, pero con
    # codigos ANSI de color que rompen el match directo. Los limpiamos.
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    clean_stdout = ansi_re.sub("", result.stdout)
    m = re.search(r"Resultado:\s*(\d+)\s*/\s*(\d+)\s*checks", clean_stdout)
    if m:
        passed = int(m.group(1))
        total = int(m.group(2))
    else:
        passed, total = 0, 0

    # El reporte .md queda en el proyecto
    md_files = sorted(
        project_path.glob("hexagonal_validation_*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    report_path = str(md_files[0]) if md_files else ""
    return (passed, total, report_path)


def _write_review_log(
    project_path: Path,
    phases: list[dict[str, Any]],
    final_verdict: str,
) -> Path:
    """Escribe `.capamedia/review/<ts>.json` con todas las fases."""
    log_dir = project_path / ".capamedia" / "review"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"{ts}.json"
    log_data = {
        "timestamp": ts,
        "project_path": str(project_path),
        "phases": phases,
        "final_verdict": final_verdict,
    }
    log_path.write_text(
        json.dumps(log_data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return log_path


# ---------------------------------------------------------------------------
# Comando principal
# ---------------------------------------------------------------------------


def review(
    project_path: Annotated[
        Path,
        typer.Argument(
            help="Ruta al proyecto Java migrado (destino/tnd-msa-sp-<svc>/).",
        ),
    ],
    legacy: Annotated[
        Path | None,
        typer.Option(
            "--legacy",
            "-l",
            help="Path al legacy original (opcional, habilita cross-check block 0).",
        ),
    ] = None,
    max_iterations: Annotated[
        int,
        typer.Option(
            "--max-iterations",
            help="Max rondas del autofix loop (default 5).",
        ),
    ] = 5,
    bank_description: Annotated[
        str | None,
        typer.Option(
            "--bank-description",
            help="Descripcion para catalog-info.yaml (regla 9 del banco).",
        ),
    ] = None,
    bank_owner: Annotated[
        str | None,
        typer.Option(
            "--bank-owner",
            help="Email @pichincha.com para spec.owner (regla 9 del banco).",
        ),
    ] = None,
    skip_official: Annotated[
        bool,
        typer.Option(
            "--skip-official",
            help="No correr el validador oficial del banco. Util para debug.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Solo corre los checks, no aplica autofixes.",
        ),
    ] = False,
) -> None:
    """Review end-to-end de un proyecto migrado externamente.

    Aplica nuestro checklist completo + autofixes en loop + validador oficial
    del banco. Pensado para proyectos que el equipo migra sin pasar por el
    CLI y necesitan un pase de limpieza antes del PR.
    """
    project_path = project_path.resolve()
    if not project_path.is_dir():
        console.print(f"[red]El proyecto no existe:[/red] {project_path}")
        raise typer.Exit(code=2)

    legacy_path = legacy.resolve() if legacy else None

    console.print(
        Panel.fit(
            "[bold]capamedia review[/bold] — pipeline completo\n"
            f"Proyecto: [cyan]{project_path}[/cyan]\n"
            f"Legacy:   [cyan]{legacy_path or '(no provisto)'}[/cyan]\n"
            f"Max iter: {max_iterations}\n"
            f"Dry run:  {'SI (sin autofix)' if dry_run else 'NO'}\n"
            f"Validator oficial: {'SKIP' if skip_official else 'ON'}",
            border_style="cyan",
        )
    )

    phases_log: list[dict[str, Any]] = []

    # ── Fase 1: Nuestro checklist con autofix loop ──────────────────────────
    console.print("\n[bold cyan]Fase 1[/bold cyan] Nuestro checklist + autofix loop")

    ctx = CheckContext(migrated_path=project_path, legacy_path=legacy_path)

    def _rerun() -> list:
        return run_all_blocks(ctx)

    if dry_run:
        initial = _rerun()
        phase1_summary = _summarize_results(initial)
        console.print(
            f"  [dim]dry-run:[/dim] {phase1_summary['pass']} PASS, "
            f"{phase1_summary['fail_high']} HIGH, "
            f"{phase1_summary['fail_medium']} MEDIUM, "
            f"{phase1_summary['fail_low']} LOW"
        )
        phases_log.append({"phase": "1-checklist", "dry_run": True, "summary": phase1_summary})
        autofix_report = None
    else:
        log_dir = project_path / ".capamedia" / "autofix"
        autofix_report = run_autofix_loop(
            project_path, _rerun, max_iter=max_iterations, log_dir=log_dir
        )
        console.print(
            f"  Iteraciones: {autofix_report.iterations} · "
            f"Fixes aplicados: {autofix_report.total_applied} · "
            f"{'[green]CONVERGED[/green]' if autofix_report.converged else '[yellow]NEEDS_HUMAN[/yellow]'}"
        )
        if autofix_report.log_path:
            console.print(f"  [dim]Log: {autofix_report.log_path}[/dim]")
        after_results = _rerun()
        phase1_summary = _summarize_results(after_results)
        phases_log.append(
            {
                "phase": "1-checklist-autofix",
                "iterations": autofix_report.iterations,
                "fixes_applied": autofix_report.total_applied,
                "converged": autofix_report.converged,
                "summary_after": phase1_summary,
            }
        )

    # ── Fase 2: Bank autofix (reglas 4, 6, 7, 8, 9) ─────────────────────────
    bank_summary: dict[str, Any] = {"skipped": dry_run}
    if not dry_run:
        console.print("\n[bold cyan]Fase 2[/bold cyan] Bank autofix (reglas 4/6/7/8/9)")
        bank_results = run_bank_autofix(
            project_path,
            description=bank_description,
            owner=bank_owner,
        )
        applied_by_rule = {r.rule: r.applied for r in bank_results}
        total_applied = sum(1 for r in bank_results if r.applied)
        console.print(
            f"  Reglas aplicadas: {total_applied}/{len(bank_results)} "
            f"· Por regla: {applied_by_rule}"
        )
        manual_notes = [
            f"Regla {r.rule}: {r.notes}"
            for r in bank_results
            if r.applied and r.notes
        ]
        if manual_notes:
            console.print("  [yellow]Revisar manualmente:[/yellow]")
            for n in manual_notes:
                console.print(f"    - {n}")
        bank_summary = {
            "total_applied": total_applied,
            "total_rules": len(bank_results),
            "by_rule": applied_by_rule,
            "manual_review": manual_notes,
        }
        phases_log.append({"phase": "2-bank-autofix", **bank_summary})

    # ── Fase 3: Re-corrida de nuestro checklist tras bank autofix ──────────
    console.print(
        "\n[bold cyan]Fase 3[/bold cyan] Re-corrida del checklist tras bank autofix"
    )
    final_results = _rerun()
    phase3_summary = _summarize_results(final_results)
    our_verdict = _verdict_from_summary(phase3_summary)
    _print_summary_table("Nuestro checklist (final)", phase3_summary, our_verdict)
    phases_log.append(
        {"phase": "3-checklist-final", "summary": phase3_summary, "verdict": our_verdict}
    )

    # ── Fase 4: Validador oficial del banco ─────────────────────────────────
    official_passed = official_total = 0
    official_report = ""
    if not skip_official:
        console.print(
            "\n[bold cyan]Fase 4[/bold cyan] Validador oficial del banco "
            "(validate_hexagonal.py)"
        )
        official_passed, official_total, official_report = _run_official_validator(
            project_path
        )
        color = "green" if official_passed == official_total and official_total > 0 else "red"
        console.print(
            f"  Resultado: [{color}]{official_passed}/{official_total} checks pasados[/{color}]"
        )
        if official_report:
            console.print(f"  [dim]Reporte: {official_report}[/dim]")
        phases_log.append(
            {
                "phase": "4-official-validator",
                "passed": official_passed,
                "total": official_total,
                "report": official_report,
            }
        )

    # ── Veredicto final ─────────────────────────────────────────────────────
    console.print("\n[bold cyan]Veredicto final[/bold cyan]")
    pr_ready = (
        phase3_summary.get("fail_high", 0) == 0
        and (skip_official or (official_total > 0 and official_passed == official_total))
    )
    final_verdict = "PR_READY" if pr_ready else "NEEDS_WORK"
    color = "green" if pr_ready else "red"

    table = Table(title="Review summary", title_style="bold cyan")
    table.add_column("Gate")
    table.add_column("Resultado")
    table.add_row("Nuestro checklist", f"{phase3_summary['pass']} PASS, "
                  f"{phase3_summary['fail_high']} HIGH, "
                  f"{phase3_summary['fail_medium']} MEDIUM, "
                  f"{phase3_summary['fail_low']} LOW "
                  f"→ {our_verdict}")
    if not skip_official:
        official_status = (
            f"{official_passed}/{official_total} PASS"
            if official_total > 0
            else "no ejecutado"
        )
        table.add_row("Validador oficial banco", official_status)
    table.add_row("PR ready", f"[{color}]{final_verdict}[/{color}]")
    console.print(table)

    log_path = _write_review_log(project_path, phases_log, final_verdict)
    console.print(f"\n[dim]Log consolidado: {log_path}[/dim]")

    if not pr_ready:
        console.print(
            "\n[yellow]El proyecto NO esta listo para PR.[/yellow] "
            "Revisar los FAIL HIGH y las violaciones del validador oficial."
        )
        raise typer.Exit(code=1)


def _print_summary_table(title: str, summary: dict[str, int], verdict: str) -> None:
    table = Table(title=title, title_style="bold")
    table.add_column("Estado")
    table.add_column("Count", justify="right")
    table.add_row("[green]PASS[/green]", str(summary.get("pass", 0)))
    table.add_row("[red]FAIL HIGH[/red]", str(summary.get("fail_high", 0)))
    table.add_row("[yellow]FAIL MEDIUM[/yellow]", str(summary.get("fail_medium", 0)))
    table.add_row("FAIL LOW", str(summary.get("fail_low", 0)))
    console.print(table)
    color = (
        "green"
        if verdict == "READY_TO_MERGE"
        else "yellow"
        if verdict == "READY_WITH_FOLLOW_UP"
        else "red"
    )
    console.print(f"  Veredicto: [{color}]{verdict}[/{color}]")
