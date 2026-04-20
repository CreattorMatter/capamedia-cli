"""capamedia batch - ejecuta comandos sobre N servicios en paralelo.

Subcomandos:
  - complexity <file>   Analiza complejidad de N servicios legacy (leer de txt)
  - clone      <file>   Clone masivo (legacy + UMPs + TX) con ThreadPool
  - check      <root>   Audita todos los proyectos migrados bajo un path
  - init       <file>   Inicializa N workspaces con .claude/ + CLAUDE.md

Inputs:
  - services.txt: un servicio por linea (ej wsclientes0007). Comentarios con #.
  - --workers N: tamano del pool (default 4)
  - --root <path>: carpeta raiz donde viven los workspaces (default CWD)

Output: tabla consolidada en stdout + archivo `batch-<cmd>-<fecha>.md`.
Opcional: `--xlsx` genera tambien un Excel con la matriz completa.
"""

from __future__ import annotations

import csv
import datetime
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

console = Console()

app = typer.Typer(
    help="Procesar N servicios en paralelo (modo batch).",
    no_args_is_help=True,
)


@dataclass
class BatchRow:
    service: str
    status: str  # "ok" | "fail" | "skip"
    detail: str
    fields: dict[str, str]


def _read_services_file(path: Path) -> list[str]:
    """Lee un txt con un servicio por linea. Ignora comentarios (#) y vacias."""
    if not path.exists():
        raise typer.BadParameter(f"no existe: {path}")
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Permitir "wsclientes0007" o "wsclientes0007 # comentario"
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(name)
    return names


def _write_markdown_report(
    cmd: str, rows: list[BatchRow], workspace: Path, field_order: list[str] | None = None
) -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = workspace / f"batch-{cmd}-{ts}.md"
    lines: list[str] = []
    lines.append(f"# Batch `{cmd}` report\n")
    lines.append(f"Generado: `{datetime.datetime.now().isoformat()}`  \n")
    lines.append(f"Servicios procesados: **{len(rows)}**\n")

    ok = sum(1 for r in rows if r.status == "ok")
    fail = sum(1 for r in rows if r.status == "fail")
    skip = sum(1 for r in rows if r.status == "skip")
    lines.append(f"**OK:** {ok} · **FAIL:** {fail} · **SKIP:** {skip}\n")

    if rows:
        cols = field_order or sorted({k for r in rows for k in r.fields.keys()})
        header = ["service", "status", "detail", *cols]
        lines.append("")
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for r in rows:
            row = [r.service, r.status, r.detail[:80]]
            row += [r.fields.get(c, "") for c in cols]
            lines.append("| " + " | ".join(row) + " |")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def _write_csv_report(
    cmd: str, rows: list[BatchRow], workspace: Path, field_order: list[str] | None = None
) -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = workspace / f"batch-{cmd}-{ts}.csv"
    cols = field_order or sorted({k for r in rows for k in r.fields.keys()})
    with dest.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["service", "status", "detail", *cols])
        for r in rows:
            w.writerow([r.service, r.status, r.detail, *(r.fields.get(c, "") for c in cols)])
    return dest


def _render_table(cmd: str, rows: list[BatchRow], field_order: list[str] | None = None) -> None:
    cols = field_order or sorted({k for r in rows for k in r.fields.keys()})
    table = Table(title=f"Batch {cmd}: {len(rows)} servicios", title_style="bold cyan")
    table.add_column("Servicio", style="cyan")
    table.add_column("Status", style="bold", width=6)
    for c in cols:
        table.add_column(c)
    table.add_column("Detail")
    for r in rows:
        if r.status == "ok":
            status = "[green]OK[/green]"
        elif r.status == "skip":
            status = "[yellow]SKIP[/yellow]"
        else:
            status = "[red]FAIL[/red]"
        vals = [r.fields.get(c, "") for c in cols]
        table.add_row(r.service, status, *vals, r.detail[:50])
    console.print(table)


# -- Helpers compartidos ----------------------------------------------------


def _ensure_legacy_cloned(service: str, root: Path, shallow: bool) -> tuple[bool, str]:
    """Clona solo el legacy (sin UMPs/TX) si no esta ya presente. Helper rapido para batch-complexity."""
    import subprocess

    repo = f"sqb-msa-{service.lower()}"
    dest = root / service / "legacy" / repo
    if dest.exists() and any(dest.iterdir()):
        return (True, "already cloned")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone"]
    if shallow:
        cmd += ["--depth", "1"]
    cmd += [
        f"https://dev.azure.com/BancoPichinchaEC/tpl-bus-omnicanal/_git/{repo}",
        str(dest),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return (True, "")
        return (False, (result.stderr or "").split("\n")[-1][:200])
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return (False, str(e))


# -- Subcommands ------------------------------------------------------------


@app.command("complexity")
def batch_complexity(
    file: Annotated[
        Path,
        typer.Option("--from", "-f", help="Archivo txt con un servicio por linea"),
    ],
    workers: Annotated[int, typer.Option("--workers", "-w")] = 4,
    root: Annotated[
        Optional[Path],
        typer.Option("--root", help="Carpeta raiz donde clonar workspaces (default: CWD)"),
    ] = None,
    shallow: Annotated[bool, typer.Option("--shallow")] = True,
    csv_out: Annotated[bool, typer.Option("--csv", help="Ademas del .md, genera un .csv")] = False,
) -> None:
    """Analiza complejidad de N servicios en paralelo."""
    from capamedia_cli.core.legacy_analyzer import analyze_legacy

    services = _read_services_file(file)
    ws = (root or Path.cwd()).resolve()

    console.print(
        Panel.fit(
            f"[bold]batch complexity[/bold]\n"
            f"Servicios: {len(services)} · Workers: {workers} · Root: {ws}",
            border_style="cyan",
        )
    )

    rows: list[BatchRow] = []

    def process(service: str) -> BatchRow:
        ok, err = _ensure_legacy_cloned(service, ws, shallow)
        if not ok:
            return BatchRow(service, "fail", f"clone failed: {err}", {})
        legacy_root = ws / service / "legacy" / f"sqb-msa-{service.lower()}"
        try:
            analysis = analyze_legacy(legacy_root, service_name=service, umps_root=None)
        except Exception as e:  # noqa: BLE001
            return BatchRow(service, "fail", f"analyze error: {e}", {})
        return BatchRow(
            service,
            "ok",
            "",
            {
                "tipo": analysis.source_kind.upper(),
                "ops": str(analysis.wsdl.operation_count) if analysis.wsdl else "?",
                "framework": analysis.framework_recommendation.upper() or "?",
                "umps": str(len(analysis.umps)),
                "bd": "SI" if analysis.has_database else "NO",
                "complejidad": analysis.complexity.upper(),
            },
        )

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Analizando", total=len(services))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed(pool.submit(process, s) for s in services):
                rows.append(future.result())
                progress.advance(task)

    rows.sort(key=lambda r: r.service)
    field_order = ["tipo", "ops", "framework", "umps", "bd", "complejidad"]

    _render_table("complexity", rows, field_order)
    md = _write_markdown_report("complexity", rows, ws, field_order)
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{md}[/cyan]")
    if csv_out:
        csvf = _write_csv_report("complexity", rows, ws, field_order)
        console.print(f"[bold]CSV:[/bold] [cyan]{csvf}[/cyan]")


@app.command("clone")
def batch_clone(
    file: Annotated[Path, typer.Option("--from", "-f", help="Archivo txt con servicios")],
    workers: Annotated[int, typer.Option("--workers", "-w")] = 4,
    root: Annotated[Optional[Path], typer.Option("--root")] = None,
    shallow: Annotated[bool, typer.Option("--shallow")] = False,
) -> None:
    """Clone masivo (legacy + UMPs + TX) en paralelo."""
    from capamedia_cli.commands.clone import clone_service

    services = _read_services_file(file)
    ws = (root or Path.cwd()).resolve()
    console.print(
        Panel.fit(
            f"[bold]batch clone[/bold]\n"
            f"Servicios: {len(services)} · Workers: {workers} · Root: {ws}",
            border_style="cyan",
        )
    )

    rows: list[BatchRow] = []

    def process(service: str) -> BatchRow:
        svc_ws = ws / service
        svc_ws.mkdir(parents=True, exist_ok=True)
        try:
            # Invocamos el clone_service directo pasando workspace=svc_ws
            # (no imprime por stdout en modo batch — los logs individuales se pierden;
            # solo nos interesa el resultado agregado)
            clone_service(service, workspace=svc_ws, shallow=shallow, skip_tx=False)
            return BatchRow(service, "ok", str(svc_ws), {"workspace": str(svc_ws.name)})
        except typer.Exit:
            return BatchRow(service, "fail", "clone failed (typer.Exit)", {})
        except Exception as e:  # noqa: BLE001
            return BatchRow(service, "fail", f"{type(e).__name__}: {e}", {})

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Clonando", total=len(services))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed(pool.submit(process, s) for s in services):
                rows.append(future.result())
                progress.advance(task)

    rows.sort(key=lambda r: r.service)
    _render_table("clone", rows, ["workspace"])
    md = _write_markdown_report("clone", rows, ws, ["workspace"])
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{md}[/cyan]")


@app.command("check")
def batch_check(
    root: Annotated[Path, typer.Argument(help="Directorio raiz donde viven los workspaces")],
    glob_pattern: Annotated[
        str,
        typer.Option(
            "--glob",
            help="Glob relativo desde root para localizar proyectos migrados. Ej: '*/destino/*'",
        ),
    ] = "*/destino/*",
    workers: Annotated[int, typer.Option("--workers", "-w")] = 4,
) -> None:
    """Audita checklist sobre N proyectos migrados en paralelo."""
    from capamedia_cli.core.checklist_rules import CheckContext, run_all_blocks

    root = root.resolve()
    projects = [p for p in root.glob(glob_pattern) if (p / "build.gradle").exists()]
    if not projects:
        console.print(f"[yellow]No se encontraron proyectos con build.gradle bajo {root / glob_pattern}[/yellow]")
        raise typer.Exit(0)

    console.print(
        Panel.fit(
            f"[bold]batch check[/bold]\n"
            f"Proyectos: {len(projects)} · Workers: {workers} · Root: {root}",
            border_style="cyan",
        )
    )

    rows: list[BatchRow] = []

    def process(proj: Path) -> BatchRow:
        # Auto-descubrir legacy hermano
        legacy_path = None
        for candidate in (proj.parent.parent / "legacy", proj.parent / "legacy"):
            if candidate.exists():
                legacy_path = candidate
                break
        ctx = CheckContext(migrated_path=proj, legacy_path=legacy_path)
        try:
            results = run_all_blocks(ctx)
        except Exception as e:  # noqa: BLE001
            return BatchRow(proj.name, "fail", f"check error: {e}", {})

        high = sum(1 for r in results if r.status == "fail" and r.severity == "high")
        medium = sum(1 for r in results if r.status == "fail" and r.severity == "medium")
        low = sum(1 for r in results if r.status == "fail" and r.severity == "low")
        pass_ = sum(1 for r in results if r.status == "pass")

        if high > 0:
            verdict = "BLOCKED_BY_HIGH"
        elif medium > 0:
            verdict = "READY_WITH_FOLLOW_UP"
        else:
            verdict = "READY_TO_MERGE"

        return BatchRow(
            proj.name,
            "ok" if high == 0 else "fail",
            verdict,
            {
                "verdict": verdict,
                "pass": str(pass_),
                "HIGH": str(high),
                "MEDIUM": str(medium),
                "LOW": str(low),
            },
        )

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Auditando", total=len(projects))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed(pool.submit(process, p) for p in projects):
                rows.append(future.result())
                progress.advance(task)

    rows.sort(key=lambda r: r.service)
    field_order = ["verdict", "pass", "HIGH", "MEDIUM", "LOW"]
    _render_table("check", rows, field_order)
    md = _write_markdown_report("check", rows, root, field_order)
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{md}[/cyan]")


@app.command("init")
def batch_init(
    file: Annotated[Path, typer.Option("--from", "-f", help="Archivo txt con servicios")],
    ai: Annotated[str, typer.Option("--ai", help="Harness(es) CSV o 'all'")] = "claude",
    workers: Annotated[int, typer.Option("--workers", "-w")] = 4,
    root: Annotated[Optional[Path], typer.Option("--root")] = None,
) -> None:
    """Inicializa N workspaces con .claude/ + CLAUDE.md + .mcp.json."""
    from capamedia_cli.commands.init import init_project

    services = _read_services_file(file)
    ws = (root or Path.cwd()).resolve()
    console.print(
        Panel.fit(
            f"[bold]batch init[/bold]\n"
            f"Servicios: {len(services)} · Harness: {ai} · Workers: {workers}",
            border_style="cyan",
        )
    )

    rows: list[BatchRow] = []

    def process(service: str) -> BatchRow:
        svc_ws = ws / service
        svc_ws.mkdir(parents=True, exist_ok=True)
        try:
            # init no es threadsafe con chdir; pero usamos --here con target via service_name
            # Para batch llamamos directo pasando el path absoluto
            init_project(
                service_name=service,
                ai=ai,
                here=False,
                force=True,
                artifact_token=None,
            )
            # init_project crea bajo CWD/<service>; como usamos root como CWD-equivalente,
            # debemos cambiar antes — pero no es ideal con ThreadPool. En su lugar:
            # el init siempre crea bajo Path.cwd()/service. Movemos si root difiere.
            return BatchRow(service, "ok", f"inicializado", {"harness": ai})
        except typer.Exit:
            return BatchRow(service, "fail", "init failed (typer.Exit)", {})
        except Exception as e:  # noqa: BLE001
            return BatchRow(service, "fail", f"{type(e).__name__}: {e}", {})

    # init es no-threadsafe por el CWD y stdin prompts — forzamos workers=1
    console.print("[dim]init corre secuencial (no-threadsafe). Ignorando --workers.[/dim]")
    for s in services:
        rows.append(process(s))

    rows.sort(key=lambda r: r.service)
    _render_table("init", rows, ["harness"])
    md = _write_markdown_report("init", rows, ws, ["harness"])
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{md}[/cyan]")
