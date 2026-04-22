"""capamedia mcp - registra y sirve el MCP local de CapaMedia para Codex."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from capamedia_cli.core.codex_mcp import (
    ensure_capamedia_mcp_server,
    load_codex_config,
    write_codex_config,
)
from capamedia_cli.mcp_server import main as mcp_server_main

console = Console()

app = typer.Typer(
    help="Gestion del MCP interno de CapaMedia para Codex.",
    no_args_is_help=True,
)


def _resolve_codex_config_path(scope: str, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    if scope == "global":
        return (Path.home() / ".codex" / "config.toml").resolve()
    return (Path.cwd() / ".codex" / "config.toml").resolve()


@app.command("setup")
def setup_mcp(
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            help="Donde registrar el MCP de CapaMedia: 'project' (.codex/config.toml local) o 'global' (~/.codex/config.toml).",
            case_sensitive=False,
        ),
    ] = "project",
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="Path explicito al config.toml de Codex a actualizar.",
        ),
    ] = None,
    root: Annotated[
        Path | None,
        typer.Option(
            "--root",
            help="Workspace root a fijar en el MCP. Default: CWD para scope=project; omitido para scope=global.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Sobrescribe un server `capamedia` ya existente."),
    ] = False,
    required: Annotated[
        bool,
        typer.Option("--required", help="Marca el server como requerido para que Codex falle si no inicia."),
    ] = False,
) -> None:
    """Registra el MCP local de CapaMedia en config.toml de Codex."""
    scope = scope.strip().lower()
    if scope not in {"project", "global"}:
        raise typer.BadParameter("scope debe ser 'project' o 'global'")

    config_path = _resolve_codex_config_path(scope, config)
    server_root = root.resolve() if root is not None else (Path.cwd().resolve() if scope == "project" else None)

    data = load_codex_config(config_path)
    changed = ensure_capamedia_mcp_server(
        data,
        root=server_root,
        overwrite=force,
        required=required,
    )
    write_codex_config(config_path, data)

    if changed:
        console.print(f"[green]OK[/green] MCP `capamedia` registrado en {config_path}")
    else:
        console.print(f"[yellow]Skip[/yellow] MCP `capamedia` ya existia en {config_path}")
    if server_root is not None:
        console.print(f"Workspace fijado: [cyan]{server_root}[/cyan]")
    console.print("Reabre Codex o corre `codex mcp list` para verificarlo.")


@app.command("serve", hidden=True)
def serve_mcp(
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Workspace root a exponer junto con el corpus canonico."),
    ] = None,
) -> None:
    """Entrypoint stdio del MCP local usado por Codex."""
    raise typer.Exit(mcp_server_main(["--root", str(root.resolve())]) if root else mcp_server_main([]))
