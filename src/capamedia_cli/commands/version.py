"""capamedia version - muestra la version instalada + metadata util.

Existe ademas el flag `--version` / `-V` a nivel global (registrado en
`cli.py`), pero este subcomando da mas contexto: version, Python
interprete, location del package, ultima fecha de instalacion.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from capamedia_cli import __version__

console = Console()


def _package_location() -> Path:
    """Path al package del CLI instalado."""
    return Path(__file__).resolve().parent.parent


def version_command() -> None:
    """Muestra la version instalada, interprete Python y ubicacion."""
    pkg_path = _package_location()
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    console.print(
        Panel.fit(
            f"[bold cyan]capamedia-cli[/bold cyan] v{__version__}\n"
            f"Python: [dim]{python_version}[/dim] ({platform.python_implementation()})\n"
            f"Platform: [dim]{platform.system()} {platform.release()}[/dim]\n"
            f"Location: [dim]{pkg_path}[/dim]\n"
            f"Executable: [dim]{sys.executable}[/dim]",
            border_style="cyan",
            title="Version info",
            title_align="left",
        )
    )
