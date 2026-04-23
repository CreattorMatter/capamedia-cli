"""capamedia discovery - arma un inventario interno desde el Excel Discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli.core.discovery import run_discovery

console = Console()


def discovery(
    name: Annotated[
        str,
        typer.Argument(help="Nombre del discovery/lote. Ej: OLA1"),
    ],
    excel: Annotated[
        Path,
        typer.Argument(help="Ruta al Excel fuente. Usa hoja Discovery si existe."),
    ],
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Directorio donde crear la carpeta <name>. Default: CWD"),
    ] = None,
    sheet: Annotated[
        str | None,
        typer.Option("--sheet", help="Hoja a leer. Default: Discovery, o la unica hoja si hay una sola."),
    ] = None,
    clone: Annotated[
        bool,
        typer.Option(
            "--clone/--no-clone",
            help="Clonar repos Azure. Con --no-clone solo parsea y genera el Excel.",
        ),
    ] = True,
    shallow: Annotated[
        bool,
        typer.Option("--shallow/--full", help="Usar git clone --depth 1 para ahorrar tiempo."),
    ] = True,
    workers: Annotated[
        int,
        typer.Option("--workers", "-w", min=1, max=16, help="Repos a clonar en paralelo."),
    ] = 4,
) -> None:
    """Lee Discovery, clona legacy/UMPs/TX y genera un Excel interno del lote."""
    source = excel.expanduser().resolve()
    if not source.exists():
        console.print(f"[red]Error:[/red] no existe el Excel: {source}")
        raise typer.Exit(1)

    base_root = (root or Path.cwd()).expanduser().resolve()
    console.print(
        Panel.fit(
            f"[bold]CapaMedia discovery[/bold]\n"
            f"Nombre: [cyan]{name}[/cyan]\n"
            f"Excel: [cyan]{source}[/cyan]\n"
            f"Root: [cyan]{base_root}[/cyan]\n"
            f"Clone: [cyan]{'SI' if clone else 'NO'}[/cyan] · Shallow: [cyan]{'SI' if shallow else 'NO'}[/cyan]",
            border_style="cyan",
        )
    )

    try:
        result = run_discovery(
            name=name,
            workbook_path=source,
            root=base_root,
            sheet_name=sheet,
            clone=clone,
            shallow=shallow,
            workers=workers,
        )
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from None

    repo_status_counts: dict[str, int] = {}
    for repo in result.repo_results:
        repo_status_counts[repo.status] = repo_status_counts.get(repo.status, 0) + 1

    unique_services = {row.service.lower() for row in result.rows}
    unique_umps = {d["valor"] for d in result.dependencies if d["tipo_dependencia"] == "UMP"}
    unique_txs = {d["valor"] for d in result.dependencies if d["tipo_dependencia"] == "TX"}

    table = Table(title="Discovery generado", title_style="bold cyan")
    table.add_column("Metrica", style="cyan")
    table.add_column("Valor", style="bold")
    table.add_row("Hoja leida", result.sheet_name)
    table.add_row("Carpeta", str(result.output_dir))
    table.add_row("Servicios filas", str(len(result.rows)))
    table.add_row("Servicios unicos", str(len(unique_services)))
    table.add_row("UMPs unicos", str(len(unique_umps)))
    table.add_row("TX unicos", str(len(unique_txs)))
    table.add_row("Repos planificados", str(len(result.repo_results)))
    table.add_row("Repos clonados", str(repo_status_counts.get("cloned", 0)))
    table.add_row("Repos existentes", str(repo_status_counts.get("already_exists", 0)))
    table.add_row("Repos saltados", str(repo_status_counts.get("skipped", 0)))
    table.add_row("Repos fallidos", str(repo_status_counts.get("failed", 0)))
    table.add_row("Caveats", str(len(result.caveats)))
    console.print(table)

    console.print(f"\n[bold]Excel discovery:[/bold] [cyan]{result.report_path}[/cyan]")
    if repo_status_counts.get("failed", 0):
        console.print(
            "[yellow]Hay repos fallidos. Revisar la pestaña Caveats/Repos del Excel generado.[/yellow]"
        )
