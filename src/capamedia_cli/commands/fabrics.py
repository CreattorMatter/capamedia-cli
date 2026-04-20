"""capamedia fabrics - gestion del MCP Fabrics del banco.

Subcomandos:
  - setup        Registra el MCP Fabrics en ~/.claude/settings.json o .mcp.json local
  - preflight    Verifica que el MCP este conectado y que la version sea reciente
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()

app = typer.Typer(
    help="Gestion del MCP Fabrics del Banco Pichincha (@pichincha/fabrics-project).",
    no_args_is_help=True,
)


MCP_FABRICS_CONFIG = {
    "command": "cmd",
    "args": ["/c", "npx", "@pichincha/fabrics-project@latest"],
    "env": {
        "ARTIFACT_USERNAME": "BancoPichinchaEC",
        "ARTIFACT_TOKEN": "",
    },
}


def _load_or_create_mcp_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            console.print(f"[yellow]Warning:[/yellow] no pude parsear {path}, voy a crear uno nuevo")
    return {"mcpServers": {}}


@app.command("setup")
def setup(
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            "-s",
            help="Donde registrar: 'global' (~/.mcp.json) o 'project' (./.mcp.json)",
        ),
    ] = "project",
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            help="Token de Azure Artifacts. Si se omite, se pide interactivamente.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Sobrescribir si ya existe"),
    ] = False,
) -> None:
    """Registra el MCP Fabrics del banco en la configuracion de Claude Code.

    El MCP `@pichincha/fabrics-project` se instala via `npx` (ya lo hace solo).
    Lo que hay que registrar es la URL y el ARTIFACT_TOKEN para Azure Artifacts.
    """
    if scope == "global":
        target = Path.home() / ".mcp.json"
    elif scope == "project":
        target = Path.cwd() / ".mcp.json"
    else:
        console.print(f"[red]Error:[/red] scope invalido: {scope}. Usa 'global' o 'project'")
        raise typer.Exit(1)

    config = _load_or_create_mcp_json(target)
    servers = config.setdefault("mcpServers", {})

    if "fabrics" in servers and not force:
        console.print(f"[yellow]MCP fabrics ya existe en {target}[/yellow]")
        if not Confirm.ask("Sobrescribir?", default=False):
            console.print("[dim]Cancelado.[/dim]")
            raise typer.Exit(0)

    # Token: prioridad 1) --token, 2) env var, 3) prompt
    if token is None:
        token = os.environ.get("CAPAMEDIA_ARTIFACT_TOKEN")
    if token is None or token.strip() == "":
        console.print(
            Panel(
                (
                    "Necesitas un [bold]Azure Artifacts PAT[/bold] con scope [cyan]Packaging (Read)[/cyan] "
                    "para descargar @pichincha/fabrics-project.\n\n"
                    "Crearlo: https://dev.azure.com/BancoPichinchaEC/_usersSettings/tokens\n"
                    "-> New Token -> Scopes -> Packaging (Read) -> Create -> Copy"
                ),
                border_style="yellow",
                title="Como obtener el token",
            )
        )
        token = Prompt.ask(
            "Pega aca tu token",
            password=True,
        )

    if not token or not token.strip():
        console.print("[red]Token vacio. Cancelando.[/red]")
        raise typer.Exit(1)

    fabric_config = {
        "command": MCP_FABRICS_CONFIG["command"],
        "args": list(MCP_FABRICS_CONFIG["args"]),
        "env": {
            "ARTIFACT_USERNAME": "BancoPichinchaEC",
            "ARTIFACT_TOKEN": token.strip(),
        },
    }
    servers["fabrics"] = fabric_config

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    console.print(f"[green]OK[/green] MCP Fabrics registrado en {target}")
    console.print()
    if scope == "project":
        console.print(
            "[yellow]IMPORTANTE:[/yellow] el archivo .mcp.json contiene tu token. "
            "Ya esta en .gitignore si usaste 'capamedia init', pero verifica antes de commit."
        )


@app.command("preflight")
def preflight() -> None:
    """Verifica que el MCP Fabrics este configurado y accesible.

    Chequea:
      - .mcp.json o ~/.claude/settings.json tiene el server 'fabrics'
      - El token no esta vacio
      - npx esta disponible (necesario para invocar el MCP)
      - Puede hacer un dry-run del MCP para verificar conectividad
    """
    from shutil import which

    console.print("[bold]Preflight MCP Fabrics[/bold]\n")

    # 1) npx available?
    if which("npx") is None:
        console.print("[red]FAIL[/red] npx no esta disponible (instala Node.js LTS)")
        raise typer.Exit(1)
    console.print("[green]OK[/green] npx disponible")

    # 2) config exists?
    candidates = [
        Path.cwd() / ".mcp.json",
        Path.home() / ".mcp.json",
        Path.home() / ".claude" / "settings.json",
    ]
    config_path = None
    for c in candidates:
        if not c.exists():
            continue
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "fabrics" in data.get("mcpServers", {}):
            config_path = c
            break

    if config_path is None:
        console.print("[red]FAIL[/red] MCP fabrics no esta registrado en ninguna ubicacion conocida")
        console.print("       Corre: [bold]capamedia fabrics setup[/bold]")
        raise typer.Exit(1)

    console.print(f"[green]OK[/green] config encontrada en {config_path}")

    # 3) token not empty?
    data = json.loads(config_path.read_text(encoding="utf-8"))
    token = (
        data.get("mcpServers", {})
        .get("fabrics", {})
        .get("env", {})
        .get("ARTIFACT_TOKEN", "")
    )
    if not token or "${" in token or "<" in token:
        console.print(
            f"[yellow]WARN[/yellow] el ARTIFACT_TOKEN parece ser un placeholder: [dim]{token[:20]}...[/dim]"
        )
        console.print("       Edita el archivo o corre [bold]capamedia fabrics setup[/bold]")
    else:
        console.print(f"[green]OK[/green] ARTIFACT_TOKEN presente ({len(token)} chars)")

    # 4) Reminder to verify version
    console.print()
    console.print(
        Panel(
            (
                "[bold]Recordatorio[/bold] (Julio Soria, 2026-04-17):\n"
                "> [italic]Siempre hay que mirar la ultima version del MCP.[/italic]\n\n"
                "El MCP se instala con [cyan]@latest[/cyan], asi que en teoria es siempre el ultimo.\n"
                "Pero antes de invocar [cyan]/fabric[/cyan] desde Claude Code:\n"
                "  1. Verifica que el tool [cyan]mcp__fabrics__create_project_with_wsdl[/cyan] aparezca\n"
                "  2. Revisa el schema del tool por parametros nuevos\n"
                "  3. Registra en [cyan].capamedia/config.yaml[/cyan] la fecha de scaffolding"
            ),
            border_style="cyan",
            title="Preflight check",
        )
    )
