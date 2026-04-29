"""Commands for generating service documentation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from capamedia_cli.core.documentacion import (
    build_service_documentation,
    write_documentation,
)

console = Console()


def generate_documentation(
    service_name: Annotated[
        str | None,
        typer.Argument(help="Servicio legacy o nombre migrado. Ej: wsclientes0020"),
    ] = None,
    here: Annotated[
        bool,
        typer.Option("--here", help="Autodetecta workspace desde CWD, destino/ y legacy/."),
    ] = False,
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", "-w", help="Workspace raiz del servicio."),
    ] = None,
    migrated: Annotated[
        Path | None,
        typer.Option("--migrated", "-m", help="Path al proyecto migrado."),
    ] = None,
    legacy: Annotated[
        Path | None,
        typer.Option("--legacy", "-l", help="Path al servicio legacy."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Archivo de salida. Default: .capamedia/reports/DOCUMENTACION_<svc>.html"),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Formato de salida: html o md. HTML es importable en Google Docs."),
    ] = "html",
) -> None:
    """Genera documentacion de servicio en formato Google Docs friendly."""
    fmt = output_format.lower().strip()
    if fmt not in {"html", "md"}:
        console.print("[red]FAIL[/red] --format debe ser html o md")
        raise typer.Exit(2)

    start = (workspace or Path.cwd()).resolve() if here or workspace else Path.cwd().resolve()
    doc = build_service_documentation(
        start=start,
        service_name=service_name,
        migrated=migrated,
        legacy=legacy,
    )
    if not doc.service_name or doc.service_name == "Servicio":
        console.print("[red]FAIL[/red] no pude inferir el servicio. Usa <servicio> o --migrated.")
        raise typer.Exit(1)

    if output is None:
        suffix = "md" if fmt == "md" else "html"
        output = doc.workspace_root / ".capamedia" / "reports" / f"DOCUMENTACION_{doc.service_name.lower()}.{suffix}"

    written = write_documentation(doc, output.resolve(), fmt)
    console.print(
        Panel.fit(
            "[bold]Documentacion generada[/bold]\n"
            f"Servicio: [cyan]{doc.service_name}[/cyan]\n"
            f"Migrado:  [cyan]{doc.migrated_name}[/cyan]\n"
            f"Formato:  [cyan]{fmt}[/cyan]\n"
            f"Salida:   [cyan]{written}[/cyan]",
            border_style="cyan",
        )
    )
    if fmt == "html":
        console.print("[dim]El HTML se puede subir/importar en Google Docs manteniendo headings y tablas.[/dim]")
