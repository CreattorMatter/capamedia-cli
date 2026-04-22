"""capamedia uninstall - desinstala el CLI detectando la fuente (uv / pip).

Estrategia:
  1. Detecta si el CLI esta instalado via `uv tool list`. Si aparece,
     `uv tool uninstall capamedia-cli`.
  2. Sino, detecta si `pip show capamedia-cli` lo encuentra. Si si,
     `pip uninstall -y capamedia-cli`.
  3. Si ninguno lo reconoce, tira error.

Opcionalmente `--purge` borra tambien:
  - `~/.capamedia/` (auth.env, cache)
  - `~/.mcp.json` / `./.mcp.json` (registro de Fabrics)

Flag `--dry-run` solo muestra que ejecutaria sin tocar nada.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

console = Console()


def _has_uv_tool() -> bool:
    """True si `uv tool list` muestra `capamedia-cli`."""
    try:
        out = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        return False
    except subprocess.TimeoutExpired:
        return False
    return out.returncode == 0 and "capamedia-cli" in (out.stdout or "")


def _has_pip_install() -> bool:
    """True si `pip show capamedia-cli` lo encuentra."""
    try:
        out = subprocess.run(
            [
                "pip",
                "show",
                "capamedia-cli",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        return False
    except subprocess.TimeoutExpired:
        return False
    return out.returncode == 0 and "Name:" in (out.stdout or "")


def _uninstall_uv_tool(dry_run: bool) -> bool:
    cmd = ["uv", "tool", "uninstall", "capamedia-cli"]
    console.print(f"  [dim]$ {' '.join(cmd)}[/dim]")
    if dry_run:
        return True
    try:
        out = subprocess.run(cmd, check=False, timeout=60)
        return out.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _uninstall_pip(dry_run: bool) -> bool:
    cmd = ["pip", "uninstall", "-y", "capamedia-cli"]
    console.print(f"  [dim]$ {' '.join(cmd)}[/dim]")
    if dry_run:
        return True
    try:
        out = subprocess.run(cmd, check=False, timeout=60)
        return out.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _purge_user_files(dry_run: bool) -> list[str]:
    """Borra configs del usuario. Retorna lista de paths borrados."""
    borrados: list[str] = []
    home = Path.home()

    targets = [
        home / ".capamedia",
        home / ".mcp.json",
        Path.cwd() / ".mcp.json",
    ]

    for t in targets:
        if not t.exists():
            continue
        console.print(f"  [dim]rm -rf {t}[/dim]")
        if dry_run:
            borrados.append(str(t))
            continue
        try:
            if t.is_dir():
                shutil.rmtree(t)
            else:
                t.unlink()
            borrados.append(str(t))
        except OSError as e:
            console.print(f"    [yellow]warning:[/yellow] no se pudo borrar {t}: {e}")

    return borrados


def uninstall_command(
    purge: Annotated[
        bool,
        typer.Option(
            "--purge",
            help=(
                "Ademas de desinstalar el package, borra ~/.capamedia/, "
                "~/.mcp.json y ./.mcp.json (configs + credenciales)."
            ),
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="No pedir confirmacion (modo unattended)",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Muestra lo que ejecutaria sin modificar nada",
        ),
    ] = False,
) -> None:
    """Desinstala capamedia-cli del sistema.

    Detecta si se instalo con `uv tool` o `pip` y ejecuta el comando
    apropiado. Con `--purge` borra ademas configs del usuario.
    """
    console.print(
        Panel.fit(
            "[bold]capamedia uninstall[/bold]\n"
            f"Purge configs: {'SI' if purge else 'NO'}\n"
            f"Dry run: {'SI' if dry_run else 'NO'}",
            border_style="cyan",
        )
    )

    # Deteccion
    uv_ok = _has_uv_tool()
    pip_ok = _has_pip_install()

    if not uv_ok and not pip_ok:
        console.print(
            "\n[yellow]No se encontro `capamedia-cli` instalado via `uv tool` "
            "ni `pip`.[/yellow]"
        )
        if purge:
            console.print("Continuo con --purge para limpiar configs...")
        else:
            console.print(
                "Nada que desinstalar. Si corriste con `pip install -e .` "
                "desde el repo, borra la carpeta manualmente."
            )
            raise typer.Exit(code=0)

    console.print("\n[bold]Fuentes detectadas:[/bold]")
    console.print(
        f"  uv tool:  {'[green]SI[/green]' if uv_ok else '[dim]no[/dim]'}"
    )
    console.print(
        f"  pip:      {'[green]SI[/green]' if pip_ok else '[dim]no[/dim]'}"
    )

    # Confirmacion
    if (
        not yes
        and not dry_run
        and not Confirm.ask(
            "\n[yellow]Proceder con la desinstalacion?[/yellow]", default=False
        )
    ):
        console.print("[yellow]Cancelado.[/yellow]")
        raise typer.Exit(code=0)

    # Ejecucion
    console.print("\n[bold]Desinstalando package...[/bold]")
    any_success = False
    if uv_ok:
        ok = _uninstall_uv_tool(dry_run)
        console.print(f"  uv tool uninstall: {'[green]OK[/green]' if ok else '[red]FAIL[/red]'}")
        any_success = any_success or ok
    if pip_ok:
        ok = _uninstall_pip(dry_run)
        console.print(f"  pip uninstall: {'[green]OK[/green]' if ok else '[red]FAIL[/red]'}")
        any_success = any_success or ok

    # Purge opcional
    if purge:
        console.print("\n[bold]Purge configs del usuario...[/bold]")
        borrados = _purge_user_files(dry_run)
        if borrados:
            console.print(f"  {len(borrados)} path(s) {'a borrar' if dry_run else 'borrados'}")
        else:
            console.print("  [dim]sin configs que borrar[/dim]")

    if dry_run:
        console.print("\n[yellow]--dry-run: nada fue modificado.[/yellow]")
    elif any_success or purge:
        console.print("\n[green]Desinstalacion completa.[/green]")
    else:
        console.print("\n[red]No se pudo desinstalar.[/red] Revisar los errores arriba.")
        raise typer.Exit(code=1)
