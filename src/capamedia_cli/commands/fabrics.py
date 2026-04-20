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


@app.command("generate")
def generate(
    service_name: str = typer.Argument(..., help="Nombre del servicio (ej: wsclientes0008)"),
    workspace: Path | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace root (default: CWD)",
    ),
    no_clipboard: bool = typer.Option(
        False,
        "--no-clipboard",
        help="No copiar al clipboard (solo escribir archivo)",
    ),
) -> None:
    """Arma el prompt listo para pegar en Claude Code que invoca el MCP Fabrics.

    Hace preflight, analiza el legacy clonado, deduce los parametros del MCP
    (projectType, webFramework, wsdlPath), y genera FABRICS_PROMPT_<svc>.md +
    clipboard con el prompt completo.
    """
    from capamedia_cli.core.legacy_analyzer import analyze_legacy

    ws = (workspace or Path.cwd()).resolve()

    console.print(
        Panel.fit(
            f"[bold]CapaMedia fabric generate[/bold]\n"
            f"Servicio: [cyan]{service_name}[/cyan]\n"
            f"Workspace: [cyan]{ws}[/cyan]",
            border_style="cyan",
        )
    )

    # Step 1: Find legacy folder
    legacy_root = ws / "legacy" / f"sqb-msa-{service_name.lower()}"
    if not legacy_root.exists():
        # Try to find any legacy subfolder
        candidates = list((ws / "legacy").glob("*")) if (ws / "legacy").exists() else []
        if candidates:
            legacy_root = candidates[0]
        else:
            console.print(f"[red]FAIL[/red] no se encontro legacy en {ws / 'legacy'}")
            console.print("[yellow]Tip:[/yellow] corre 'capamedia clone <servicio>' antes")
            raise typer.Exit(1)

    console.print(f"  [green]OK[/green] legacy encontrado: {legacy_root}")

    # Step 2: Analyze
    umps_root = ws / "umps" if (ws / "umps").exists() else None
    analysis = analyze_legacy(legacy_root, service_name=service_name, umps_root=umps_root)

    if not analysis.wsdl:
        console.print("[red]FAIL[/red] no se pudo analizar el WSDL del legacy")
        raise typer.Exit(1)

    # Step 3: Deduce MCP params
    web_framework = "webflux" if analysis.framework_recommendation == "rest" else "mvc"
    project_type = analysis.framework_recommendation or "soap"
    wsdl_abs = analysis.wsdl.path.resolve()

    console.print()
    console.print(f"  Operaciones WSDL : [bold]{analysis.wsdl.operation_count}[/bold]")
    console.print(f"  projectType      : [bold]{project_type}[/bold]")
    console.print(f"  webFramework     : [bold]{web_framework}[/bold]")
    console.print(f"  wsdlPath         : [dim]{wsdl_abs}[/dim]")
    console.print(f"  UMPs detectados  : [bold]{len(analysis.umps)}[/bold]")
    console.print(f"  BD presente      : [bold]{'SI' if analysis.has_database else 'NO'}[/bold]")
    console.print(f"  Complejidad      : [bold]{analysis.complexity.upper()}[/bold]")

    # Step 4: Build prompt
    prompt_lines: list[str] = []
    prompt_lines.append(f"Invocar el MCP Fabrics para generar el arquetipo de `{service_name}`.")
    prompt_lines.append("")
    prompt_lines.append("## Parametros deducidos")
    prompt_lines.append("")
    prompt_lines.append("```")
    prompt_lines.append(f"wsdlPath     : {wsdl_abs}")
    prompt_lines.append(f"projectType  : {project_type}")
    prompt_lines.append(f"webFramework : {web_framework}")
    prompt_lines.append(f"serviceName  : {service_name}")
    prompt_lines.append(f"groupId      : com.pichincha.sp")
    prompt_lines.append(f"artifactId   : tnd-msa-sp-{service_name.lower()}")
    prompt_lines.append(f"javaVersion  : 21")
    prompt_lines.append(f"outputDir    : ./destino")
    prompt_lines.append("```")
    prompt_lines.append("")
    prompt_lines.append("## Pasos (ejecutar en orden)")
    prompt_lines.append("")
    prompt_lines.append("1. **Preflight**: confirmar que el tool `mcp__fabrics__create_project_with_wsdl` esta disponible.")
    prompt_lines.append("   Si no, detener y avisar al usuario que corra `capamedia fabrics preflight` en shell.")
    prompt_lines.append("")
    prompt_lines.append("2. **Invocar MCP** con los parametros de arriba.")
    prompt_lines.append("")
    prompt_lines.append("3. **Aplicar workarounds** conocidos (ver `prompts/migrate-soap-full.md` o `migrate-rest-full.md`):")
    if project_type == "soap":
        prompt_lines.append("   - Gap 1: agregar `spring-boot-starter-webflux` a `build.gradle` si falta")
        prompt_lines.append("   - Gap 2: agregar `com.sun.xml.ws:jaxws-rt:4.0.3` a `build.gradle`")
        prompt_lines.append("   - Gap 3: sincronizar versiones con `gold-ref/tnd-msa-sp-wsclientes0015/build.gradle`")
    else:
        prompt_lines.append("   - Sincronizar versiones con `gold-ref/tnd-msa-sp-wsclientes0024/build.gradle`")
    prompt_lines.append("")
    prompt_lines.append("4. **Completar scaffolding** copiando desde el workspace:")
    prompt_lines.append("   ```bash")
    prompt_lines.append("   cp -r .claude destino/tnd-msa-sp-" + service_name.lower() + "/")
    prompt_lines.append("   cp CLAUDE.md destino/tnd-msa-sp-" + service_name.lower() + "/")
    prompt_lines.append("   cp .mcp.json destino/tnd-msa-sp-" + service_name.lower() + "/")
    prompt_lines.append("   cp -r .sonarlint destino/tnd-msa-sp-" + service_name.lower() + "/ 2>/dev/null || true")
    prompt_lines.append("   ```")
    prompt_lines.append("")
    prompt_lines.append("5. **Registrar contexto** en `destino/tnd-msa-sp-" + service_name.lower() + "/migration-context.json`:")
    prompt_lines.append("   ```json")
    prompt_lines.append("   {")
    prompt_lines.append(f'     "service": "{service_name}",')
    prompt_lines.append(f'     "sourceKind": "{analysis.source_kind}",')
    prompt_lines.append(f'     "projectType": "{project_type}",')
    prompt_lines.append(f'     "webFramework": "{web_framework}",')
    prompt_lines.append(f'     "dbUsage": {str(analysis.has_database).lower()},')
    prompt_lines.append(f'     "operationsCount": {analysis.wsdl.operation_count},')
    prompt_lines.append(f'     "umps": [{", ".join(f'{{"name": "{u.name}", "tx": {u.tx_codes}}}' for u in analysis.umps)}],')
    prompt_lines.append('     "scaffolding": {')
    prompt_lines.append('       "mcp_version": "<pedir al usuario>",')
    prompt_lines.append('       "scaffold_date": "<ISO8601 ahora>",')
    prompt_lines.append('       "gaps_fixed_by_mcp": [],')
    prompt_lines.append('       "workarounds_applied": []')
    prompt_lines.append("     }")
    prompt_lines.append("   }")
    prompt_lines.append("   ```")
    prompt_lines.append("")
    prompt_lines.append("6. **Responder conversacionalmente** con un resumen de lo que hizo el MCP, que workarounds aplicaste, y la ruta del destino generado.")

    prompt_text = "\n".join(prompt_lines)

    # Step 5: Write file
    prompt_file = ws / f"FABRICS_PROMPT_{service_name}.md"
    prompt_file.write_text(prompt_text + "\n", encoding="utf-8")
    console.print(f"\n  [green]OK[/green] prompt escrito en [cyan]{prompt_file}[/cyan]")

    # Step 6: Clipboard
    if not no_clipboard:
        try:
            import pyperclip

            pyperclip.copy(prompt_text)
            console.print("  [green]OK[/green] prompt copiado al clipboard (pegalo en Claude Code)")
        except (ImportError, Exception) as e:  # noqa: BLE001
            console.print(f"  [yellow]SKIP[/yellow] clipboard no disponible: {e}")

    console.print()
    console.print(
        Panel(
            "Proximo paso:\n"
            "  1. Abri Claude Code en este workspace\n"
            "  2. Pega el prompt (Ctrl+V) en el chat\n"
            "  3. Claude ejecuta el MCP y genera destino/\n"
            "\n"
            "Alternativa: abri FABRICS_PROMPT_<svc>.md y pegalo manualmente.",
            border_style="green",
            title="Listo",
        )
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
