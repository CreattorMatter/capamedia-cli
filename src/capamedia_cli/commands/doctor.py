"""capamedia doctor - diagnostico rapido del entorno."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from capamedia_cli import __version__
from capamedia_cli.core.canonical import CANONICAL_ROOT, load_canonical_assets

console = Console()


def doctor() -> None:
    """Muestra info del entorno y sanity check del CLI."""
    table = Table(title="CapaMedia Doctor", title_style="bold cyan")
    table.add_column("Item", style="cyan")
    table.add_column("Valor", style="bold")

    table.add_row("CLI version", f"capamedia v{__version__}")
    table.add_row("Python", f"{sys.version.split()[0]} ({platform.python_implementation()})")
    table.add_row("Platform", f"{platform.system()} {platform.release()}")
    table.add_row("CWD", str(Path.cwd()))
    table.add_row("Canonical root", str(CANONICAL_ROOT))

    assets = load_canonical_assets()
    table.add_row("Prompts", str(len(assets.get("prompt", []))))
    table.add_row("Agents", str(len(assets.get("agent", []))))
    table.add_row("Skills", str(len(assets.get("skill", []))))
    table.add_row("Context files", str(len(assets.get("context", []))))

    # Project config if present
    proj_cfg = Path.cwd() / ".capamedia" / "config.yaml"
    if proj_cfg.exists():
        table.add_row("Project config", str(proj_cfg))
    else:
        table.add_row("Project config", "[dim]no encontrado (no es un proyecto inicializado)[/dim]")

    # MCP
    mcp_local = Path.cwd() / ".mcp.json"
    mcp_global = Path.home() / ".mcp.json"
    if mcp_local.exists():
        table.add_row("MCP config", str(mcp_local))
    elif mcp_global.exists():
        table.add_row("MCP config", str(mcp_global))
    else:
        table.add_row("MCP config", "[dim]no encontrado (corre capamedia fabrics setup)[/dim]")

    console.print(table)
