"""CapaMedia CLI - entry point.

Comandos disponibles:
  capamedia install        - instala toolchain (Java, Node, Git, etc.) via winget
  capamedia check-install  - verifica que todo el toolchain este OK
  capamedia setup machine  - bootstrap reproducible de la maquina runner
  capamedia auth           - bootstrap de credenciales para Fabrics/Azure/Codex
  capamedia init           - inicializa un proyecto con scaffolding para el harness elegido
  capamedia mcp            - registra el MCP interno de CapaMedia en Codex
  capamedia fabrics        - gestiona el MCP Fabrics (setup y preflight)
  capamedia doctor         - diagnostico del CLI y el entorno
  capamedia worker run     - loop local para ejecutar la fabrica unattended
  capamedia upgrade        - agrega o actualiza harnesses en un proyecto ya inicializado

Los comandos de trabajo diario (clone, fabric, migrate, check) son SLASH COMMANDS
ejecutados desde el chat del IDE (Claude Code, Cursor, Windsurf, Copilot, etc.),
no comandos shell. El CLI solo genera los slash commands en la carpeta correcta.
"""

from __future__ import annotations

import sys
from contextlib import suppress

import typer
from rich.console import Console

from capamedia_cli import __version__
from capamedia_cli.commands import (
    auth,
    batch,
    check,
    check_install,
    clone,
    doctor,
    fabrics,
    init,
    install,
    mcp,
    setup,
    upgrade,
    worker,
)


def _configure_stdio_utf8() -> None:
    """Forzar UTF-8 en stdout/stderr para evitar problemas en Windows cp1252."""
    for stream in (sys.stdout, sys.stderr):
        with suppress(AttributeError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


_configure_stdio_utf8()

console = Console()

app = typer.Typer(
    name="capamedia",
    help=(
        "CLI multi-harness para migrar servicios legacy (IIB/WAS/ORQ) "
        "de Banco Pichincha a Java 21 + Spring Boot hexagonal OLA1."
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold cyan]capamedia[/bold cyan] v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """CapaMedia - toolkit de migracion legacy -> hexagonal OLA1."""


app.command("install")(install.install_toolchain)
app.command("check-install")(check_install.check_install)
app.add_typer(setup.app, name="setup", help="Bootstrap reproducible de maquina runner")
app.add_typer(auth.app, name="auth", help="Bootstrap de credenciales")
app.command("init")(init.init_project)
app.command("clone")(clone.clone_service)
app.command("check")(check.check_project)
app.add_typer(batch.app, name="batch", help="Procesar N servicios en paralelo")
app.add_typer(worker.app, name="worker", help="Loop local para ejecutar la fabrica unattended")
app.add_typer(mcp.app, name="mcp", help="Gestion del MCP interno de CapaMedia para Codex")
app.add_typer(fabrics.app, name="fabrics", help="Gestion del MCP Fabrics del banco")
app.command("doctor")(doctor.doctor)
app.command("upgrade")(upgrade.upgrade_project)


if __name__ == "__main__":
    app()
