"""capamedia update - actualiza el CLI a la ultima version del repo.

Detecta como se instalo el CLI y aplica el upgrade correspondiente:

- Si se instalo con `uv tool`: `uv tool upgrade capamedia-cli`
- Si se instalo con `pip install -e .` desde source (editable):
    `git pull` + `pip install -e . --force-reinstall`
- Si se instalo con `pip install capamedia-cli` desde registry:
    `pip install --upgrade capamedia-cli`

Todos los caminos terminan mostrando la version nueva con `version_command`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from capamedia_cli import __version__

console = Console()


def _is_editable_install() -> Path | None:
    """Si se instalo con `pip install -e .`, retorna la ruta del source.

    Estrategia: el package esta en `<source>/src/capamedia_cli/` y tiene
    `pyproject.toml` dos directorios arriba.
    """
    pkg = Path(__file__).resolve().parent.parent  # capamedia_cli/
    src_dir = pkg.parent  # src/
    source_root = src_dir.parent  # raiz del repo
    pyproject = source_root / "pyproject.toml"
    if pyproject.exists() and (source_root / ".git").exists():
        return source_root
    return None


def _has_uv_tool() -> bool:
    try:
        out = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and "capamedia-cli" in (out.stdout or "")


def _run(cmd: list[str], *, cwd: Path | None = None) -> int:
    console.print(f"  [dim]$ {' '.join(cmd)}[/dim]")
    try:
        result = subprocess.run(
            cmd, check=False, cwd=str(cwd) if cwd else None, timeout=300
        )
        return result.returncode
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        console.print(f"  [red]fallo: {exc}[/red]")
        return 1


def update_command(
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Muestra los comandos sin ejecutarlos",
        ),
    ] = False,
) -> None:
    """Actualiza capamedia-cli a la ultima version del repo."""
    console.print(
        Panel.fit(
            f"[bold]capamedia update[/bold]\n"
            f"Version actual: v{__version__}\n"
            f"Dry run: {'SI' if dry_run else 'NO'}",
            border_style="cyan",
        )
    )

    editable_source = _is_editable_install()
    uv_installed = _has_uv_tool()

    # Prioridad: uv > editable desde source > pip registry
    if uv_installed:
        console.print("\n[bold]Fuente detectada:[/bold] uv tool")
        if dry_run:
            console.print("  [dim]$ uv tool upgrade capamedia-cli[/dim]")
        else:
            rc = _run(["uv", "tool", "upgrade", "capamedia-cli"])
            if rc != 0:
                console.print(
                    f"[red]uv tool upgrade fallo (exit {rc}).[/red] "
                    "Probá manual: `uv tool uninstall capamedia-cli` + "
                    "`uv tool install capamedia-cli --from <source>`"
                )
                raise typer.Exit(code=rc)
    elif editable_source:
        console.print(f"\n[bold]Fuente detectada:[/bold] pip editable desde {editable_source}")

        if dry_run:
            console.print(f"  [dim]$ git -C {editable_source} pull[/dim]")
            console.print(f"  [dim]$ pip install -e {editable_source} --force-reinstall[/dim]")
        else:
            console.print("\n[bold]1. git pull[/bold]")
            rc = _run(["git", "pull"], cwd=editable_source)
            if rc != 0:
                console.print(
                    "[yellow]git pull fallo.[/yellow] Podes tener cambios "
                    "locales sin commitear o el remote no accesible."
                )
                raise typer.Exit(code=rc)

            console.print("\n[bold]2. pip install -e . --force-reinstall[/bold]")
            rc = _run(
                ["pip", "install", "-e", str(editable_source), "--force-reinstall"]
            )
            if rc != 0:
                console.print(f"[red]pip install fallo (exit {rc}).[/red]")
                raise typer.Exit(code=rc)
    else:
        console.print("\n[bold]Fuente detectada:[/bold] pip registry (no-editable)")
        if dry_run:
            console.print("  [dim]$ pip install --upgrade capamedia-cli[/dim]")
        else:
            rc = _run(["pip", "install", "--upgrade", "capamedia-cli"])
            if rc != 0:
                console.print(f"[red]pip install --upgrade fallo (exit {rc}).[/red]")
                raise typer.Exit(code=rc)

    if not dry_run:
        console.print("\n[green]Actualizacion completa.[/green]")
        console.print(
            "Corré `capamedia version` en una [bold]shell nueva[/bold] para ver "
            "la version actualizada (el interprete Python ya cargó la anterior "
            "en esta sesion)."
        )
