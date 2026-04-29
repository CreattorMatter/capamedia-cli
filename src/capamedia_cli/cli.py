"""CapaMedia CLI - entry point.

Comandos disponibles:
  capamedia install        - instala toolchain (Java, Node, Git, etc.) via winget
  capamedia check-install  - verifica que todo el toolchain este OK
  capamedia auth           - bootstrap de credenciales para Fabrics/Azure/Codex
  capamedia init           - inicializa un proyecto con scaffolding para el harness elegido
  capamedia fabrics        - gestiona el MCP Fabrics (setup y generate)
  capamedia ai migrate     - migra con un engine AI headless (Codex/Claude)
  capamedia ai doublecheck - corre el doble check AI post-migracion
  capamedia documentacion  - genera documentacion de servicio para Google Docs
  capamedia qa pack        - prepara QA de equivalencia funcional para Copilot
  capamedia clone-migrated - clona legacy + repos migrados existentes
  capamedia doctor         - diagnostico del CLI y el entorno
  capamedia upgrade        - agrega o actualiza harnesses en un proyecto ya inicializado

Flujo recomendado:
  capamedia clone -> capamedia fabrics generate -> capamedia ai migrate
  -> capamedia ai doublecheck -> capamedia review

Los assets nativos de cada harness se siguen generando, pero el flujo operativo
portable vive en comandos shell para que Codex, Claude y futuros engines usen
la misma entrada.
"""

from __future__ import annotations

import sys
from contextlib import suppress

import typer
from rich.console import Console

from capamedia_cli import __version__
from capamedia_cli.commands import (
    adopt as adopt_cmd,
)
from capamedia_cli.commands import (
    ai,
    auth,
    batch,
    canonical,
    check,
    check_install,
    clone,
    discovery,
    doctor,
    documentacion,
    fabrics,
    init,
    install,
    qa,
    review,
    status,
    uninstall,
    upgrade,
    validate,
)
from capamedia_cli.commands import (
    info as info_cmd,
)
from capamedia_cli.commands import (
    update as update_cmd,
)
from capamedia_cli.commands import (
    version as version_cmd,
)

# Forzar UTF-8 en stdout/stderr para que emojis y acentos no exploten en Windows cp1252.
# Esto se ejecuta al import, antes de cualquier print del CLI.
for stream in (sys.stdout, sys.stderr):
    with suppress(AttributeError, OSError):
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

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
app.command("uninstall")(uninstall.uninstall_command)
app.command("update")(update_cmd.update_command)
app.command("version")(version_cmd.version_command)
app.command("status")(status.status_command)
app.command("check-install")(check_install.check_install)
app.add_typer(auth.app, name="auth", help="Bootstrap de credenciales")
app.command("init")(init.init_project)
app.command("clone")(clone.clone_service)
app.command("clone-migrated")(clone.clone_migrated_service)
app.command("clon-migrado")(clone.clone_migrated_service)
app.command("documentacion")(documentacion.generate_documentation)
app.command("documentación", hidden=True)(documentacion.generate_documentation)
app.command("documentation", hidden=True)(documentacion.generate_documentation)
app.command("adopt")(adopt_cmd.adopt)  # v0.23.11: adopt workspaces no-canonicos
app.command("info")(info_cmd.info)    # v0.23.12: dashboard de pendientes
app.command("check")(check.check_project)
app.command("checklist")(check.checklist_project)  # v0.23.0: alias doble-check
# v0.23.2: review con subcomandos `review orq|bus|was` para forzar el source_type
app.add_typer(review.app, name="review")
app.add_typer(ai.app, name="ai", help="Etapas AI headless: migrate y doublecheck")
app.add_typer(qa.app, name="qa", help="QA de equivalencia funcional con Copilot")
app.add_typer(batch.app, name="batch", help="Procesar N servicios en paralelo")
app.add_typer(discovery.app, name="discovery", help="Leer Discovery OLA y extraer edge cases")
app.add_typer(fabrics.app, name="fabrics", help="Gestion del MCP Fabrics del banco")
app.add_typer(canonical.app, name="canonical", help="Gestion del canonical de prompts/skills/agents/context")
app.add_typer(validate.app, name="validate-hexagonal", help="Validador oficial del banco (9 checks formales)")
app.command("doctor")(doctor.doctor)
app.command("upgrade")(upgrade.upgrade_project)


if __name__ == "__main__":
    app()
