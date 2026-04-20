"""capamedia upgrade - agrega/quita harnesses en un proyecto ya inicializado."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.prompt import Confirm

from capamedia_cli import __version__
from capamedia_cli.adapters import ALL_HARNESSES, get_adapter, resolve_harnesses
from capamedia_cli.core.canonical import load_canonical_assets

console = Console()

HARNESS_DIRS = {
    "claude": [".claude"],
    "cursor": [".cursor"],
    "windsurf": [".windsurf", ".windsurfrules"],
    "copilot": [".github/prompts", ".github/copilot-instructions.md"],
    "codex": [".codex", "AGENTS.md"],
    "opencode": [".opencode", "opencode.json"],
}


def upgrade_project(
    add: Annotated[
        str | None,
        typer.Option("--add", help=f"Harness(es) a agregar. Opciones: {', '.join(ALL_HARNESSES)}, all. CSV ok."),
    ] = None,
    remove: Annotated[
        str | None,
        typer.Option("--remove", help="Harness(es) a quitar. CSV ok."),
    ] = None,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Regenerar todos los harnesses activos desde el canonical actual"),
    ] = False,
) -> None:
    """Agrega o quita harnesses de un proyecto ya inicializado."""
    config_path = Path.cwd() / ".capamedia" / "config.yaml"
    if not config_path.exists():
        console.print("[red]Error:[/red] no encontre .capamedia/config.yaml. Corre primero [bold]capamedia init[/bold].")
        raise typer.Exit(1)

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    current: list[str] = list(config.get("ai", []))

    if add is None and remove is None and not refresh:
        console.print(f"Harnesses activos: [cyan]{', '.join(current) if current else '(ninguno)'}[/cyan]")
        console.print("Usa --add, --remove o --refresh.")
        raise typer.Exit(0)

    target_dir = Path.cwd()

    # Remove
    if remove:
        to_remove = resolve_harnesses(remove)
        for h in to_remove:
            if h not in current:
                console.print(f"[yellow]Skip:[/yellow] {h} no estaba activo")
                continue
            for d in HARNESS_DIRS.get(h, []):
                path = target_dir / d
                if not path.exists():
                    continue
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                console.print(f"  [red]-[/red] borrado {path}")
            current.remove(h)
            console.print(f"[green]OK[/green] quitado {h}")

    # Add (or refresh)
    if add or refresh:
        if refresh:
            to_add = current.copy()
        else:
            requested = resolve_harnesses(add)
            to_add = [h for h in requested if h not in current]
            for h in requested:
                if h in current and not refresh:
                    console.print(f"[yellow]Skip:[/yellow] {h} ya estaba activo (usa --refresh para regenerar)")

        assets = load_canonical_assets()
        total = 0
        for h in to_add:
            adapter = get_adapter(h)
            written, warnings = adapter.render_all(assets, target_dir)
            console.print(f"  [green]OK[/green] {adapter.display_name}: {len(written)} archivo(s)")
            total += len(written)
            for w in warnings:
                console.print(f"     [yellow]- {w}[/yellow]")
            if h not in current:
                current.append(h)

        console.print(f"\nTotal: {total} archivo(s) generado(s)")

    # Save config
    config["ai"] = current
    config["version"] = __version__
    config_path.write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    console.print(f"\nHarnesses activos: [cyan]{', '.join(current) if current else '(ninguno)'}[/cyan]")
