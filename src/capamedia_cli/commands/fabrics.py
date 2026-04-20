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
from rich.table import Table

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


NAMESPACE_OPTIONS = ["tnd", "tpr", "csg", "tmp", "tia", "tct"]


@app.command("generate")
def generate(
    service_name: str = typer.Argument(..., help="Nombre del servicio (ej: wsclientes0008)"),
    workspace: Path | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace root (default: CWD)",
    ),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        "-n",
        help=f"Namespace del catalogo: {' | '.join(NAMESPACE_OPTIONS)}. Si se omite, se pregunta interactivamente.",
    ),
    group_id: str = typer.Option(
        "com.pichincha.sp",
        "--group-id",
        help="Maven groupId del proyecto",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="No invocar el MCP, solo mostrar los parametros que se usarian",
    ),
) -> None:
    """Invoca el MCP Fabrics del banco y genera el arquetipo en ./destino/.

    Analiza el legacy clonado por `capamedia clone`, deduce los parametros del MCP,
    lo invoca via stdio JSON-RPC y deja la carpeta `destino/` con el proyecto generado.
    """
    from capamedia_cli.core.legacy_analyzer import analyze_legacy
    from capamedia_cli.core.mcp_client import MCPClient, MCPError
    from capamedia_cli.core.mcp_launcher import locate as locate_mcp

    ws = (workspace or Path.cwd()).resolve()

    console.print(
        Panel.fit(
            f"[bold]CapaMedia fabrics generate[/bold]\n"
            f"Servicio: [cyan]{service_name}[/cyan]\n"
            f"Workspace: [cyan]{ws}[/cyan]",
            border_style="cyan",
        )
    )

    # Step 1: Find legacy folder
    legacy_root = ws / "legacy" / f"sqb-msa-{service_name.lower()}"
    if not legacy_root.exists():
        candidates = list((ws / "legacy").glob("*")) if (ws / "legacy").exists() else []
        if candidates:
            legacy_root = candidates[0]
        else:
            console.print(f"[red]FAIL[/red] no se encontro legacy en {ws / 'legacy'}")
            console.print("[yellow]Tip:[/yellow] corre 'capamedia clone <servicio>' antes")
            raise typer.Exit(1)

    console.print(f"  [green]OK[/green] legacy encontrado en: {legacy_root}")

    # Step 2: Analyze
    umps_root = ws / "umps" if (ws / "umps").exists() else None
    analysis = analyze_legacy(legacy_root, service_name=service_name, umps_root=umps_root)

    if not analysis.wsdl:
        console.print("[red]FAIL[/red] no se pudo analizar el WSDL del legacy")
        raise typer.Exit(1)

    # Step 3: Deduce MCP params
    project_type = analysis.framework_recommendation or "soap"
    web_framework = "webflux" if project_type == "rest" else "mvc"
    tecnologia = "bus" if analysis.source_kind == "iib" else ("was" if analysis.source_kind == "was" else "bus")
    invoca_bancs = bool(analysis.umps)
    wsdl_abs = str(analysis.wsdl.path.resolve())
    project_name = f"tnd-msa-sp-{service_name.lower()}"
    project_path = str((ws / "destino").resolve())

    # Step 4: Resolve namespace (enum MCP)
    if namespace is None:
        console.print()
        console.print("[bold yellow]Namespace del catalogo[/bold yellow] (obligatorio, no inferible)")
        console.print(f"  Opciones: {', '.join(NAMESPACE_OPTIONS)}")
        namespace = Prompt.ask(
            "  Elegi el namespace",
            choices=NAMESPACE_OPTIONS,
            default="tnd",
        )

    # Show summary
    console.print()
    table = Table(title="Parametros deducidos para el MCP", title_style="bold cyan")
    table.add_column("Parametro", style="cyan")
    table.add_column("Valor", style="bold")
    table.add_column("Origen", style="dim")
    table.add_row("projectName", project_name, "derivado de service_name")
    table.add_row("projectPath", project_path, "ws/destino")
    table.add_row("wsdlFilePath", wsdl_abs, "legacy WSDL")
    table.add_row("groupId", group_id, "--group-id")
    table.add_row("namespace", namespace, "interactivo / --namespace")
    table.add_row("tecnologia", tecnologia, f"source_kind={analysis.source_kind}")
    table.add_row("projectType", project_type, f"{analysis.wsdl.operation_count} ops")
    table.add_row("webFramework", web_framework, "matriz oficial")
    table.add_row("invocaBancs", str(invoca_bancs).lower(), f"{len(analysis.umps)} UMPs")
    console.print(table)

    mcp_args = {
        "projectName": project_name,
        "projectPath": project_path,
        "wsdlFilePath": wsdl_abs,
        "groupId": group_id,
        "namespace": namespace,
        "tecnologia": tecnologia,
        "projectType": project_type,
        "webFramework": web_framework,
        "invocaBancs": invoca_bancs,
    }

    if dry_run:
        console.print("\n[yellow]--dry-run: no invoco el MCP.[/yellow]")
        console.print("Argumentos que se enviarian:")
        console.print_json(data=mcp_args)
        return

    # Step 5: Locate + launch MCP
    console.print("\n[bold]Arrancando MCP Fabrics...[/bold]")
    try:
        spec = locate_mcp(cwd=ws)
    except FileNotFoundError as e:
        console.print(f"[red]FAIL[/red] {e}")
        raise typer.Exit(1) from None
    console.print(f"  source: [dim]{spec.source}[/dim]")

    mcp_error_msg: str | None = None
    result: dict = {}
    try:
        with MCPClient(spec.command, env=spec.env, cwd=str(ws)) as client:
            info = client.initialize(client_name="capamedia-cli", client_version="0.2.3")
            console.print(
                f"  [green]OK[/green] MCP conectado: {info.get('serverInfo', {}).get('name')} "
                f"v{info.get('serverInfo', {}).get('version')}"
            )

            # Step 6: Invoke the tool
            console.print("\n[bold]Invocando create_project_with_wsdl...[/bold]")
            try:
                result = client.call_tool("create_project_with_wsdl", mcp_args)
            except MCPError as e:
                # El MCP puede reportar error pero igual haber creado el scaffold.
                # Lo tratamos como warning si destino/ existe.
                mcp_error_msg = str(e)
    except MCPError as e:
        console.print(f"[red]FAIL[/red] error conectando al MCP: {e}")
        raise typer.Exit(1) from None

    # Step 7: Parse result
    content_items = result.get("content", [])
    text_parts = [c.get("text", "") for c in content_items if c.get("type") == "text"]
    if text_parts:
        # Sanitize emojis/unicode that cp1252 (Windows default) cannot encode
        def _safe_text(s: str) -> str:
            return s.encode("ascii", errors="replace").decode("ascii")

        console.print("\n[bold]Respuesta del MCP:[/bold]")
        for part in text_parts:
            console.print(f"  {_safe_text(part[:600])}")

    destino = ws / "destino"
    proj_dir = destino / project_name
    generated_ok = destino.exists() and any(destino.iterdir())

    if generated_ok and mcp_error_msg:
        # Exito parcial: scaffold existe pero el MCP reporto error (tipicamente
        # el paso final de `gradlew generateFromWsdl` fallo)
        console.print()
        def _safe(s: str) -> str:
            return s.encode("ascii", errors="replace").decode("ascii")
        short_err = _safe(mcp_error_msg[:300])
        console.print(
            Panel(
                f"Scaffold generado en [cyan]{proj_dir}[/cyan]\n"
                f"pero el MCP reporto un error en el paso final:\n\n"
                f"[dim]{short_err}[/dim]\n\n"
                f"Esto suele pasar cuando el MCP intenta correr `gradlew generateFromWsdl`\n"
                f"pero el wrapper todavia no es ejecutable.\n\n"
                f"Completa el paso manualmente:\n"
                f"  cd {proj_dir}\n"
                f"  ./gradlew generateFromWsdl",
                border_style="yellow",
                title="Exito parcial",
            )
        )
    elif generated_ok:
        console.print()
        console.print(
            Panel(
                f"Arquetipo generado en [cyan]{proj_dir}[/cyan]\n\n"
                f"Proximos pasos:\n"
                f"  1. Revisa `{proj_dir.name}/build.gradle` y aplica workarounds conocidos.\n"
                f"  2. Corre `capamedia init --here` dentro de destino/{project_name}/ para sumar .claude/ y CLAUDE.md.\n"
                f"  3. Abri en Claude Code y corre `/migrate` en el chat.",
                border_style="green",
                title="OK",
            )
        )
    else:
        console.print(
            f"[red]FAIL[/red] el MCP respondio pero {destino} esta vacio."
        )
        if mcp_error_msg:
            def _safe(s: str) -> str:
                return s.encode("ascii", errors="replace").decode("ascii")
            console.print(f"Error MCP: {_safe(mcp_error_msg[:500])}")
        raise typer.Exit(1)


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
