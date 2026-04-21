"""capamedia init - inicializa un proyecto con scaffolding para el/los harness(es).

Genera en la carpeta destino:
  - .claude/commands/*.md       (si se eligio claude)
  - .cursor/rules/*.mdc         (si se eligio cursor)
  - .windsurf/rules/*.md        (si se eligio windsurf)
  - .github/prompts/*.md        (si se eligio copilot)
  - .codex/prompts/*.md         (si se eligio codex)
  - .opencode/prompts/*.md      (si se eligio opencode)
  - CLAUDE.md / AGENTS.md       (contexto general)
  - .mcp.json                   (config del MCP Fabrics con placeholder)
  - .sonarlint/connectedMode.json (template para SonarLint)
  - .gitignore                  (con exclusiones de CapaMedia y secrets)

Por defecto corre INTERACTIVO: te pregunta uno por uno cuales harnesses activar.
Usa --ai <csv> para saltar el prompt (ej: --ai claude,cursor).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Optional

import typer
import yaml
from rich.console import Console
from rich.prompt import Confirm, Prompt

from capamedia_cli import __version__
from capamedia_cli.adapters import ADAPTERS, ALL_HARNESSES, get_adapter, resolve_harnesses
from capamedia_cli.core.canonical import DATA_ROOT, load_canonical_assets

console = Console()

LOGO = """
[bold cyan]
   CCCC   AAAA  PPPP    AA   M   M EEEEE DDDD  III  AAAA
  C      A    A P   P  A  A  MM MM E     D   D  I  A    A
  C      AAAAAA PPPP  AAAAAA M M M EEEE  D   D  I  AAAAAA
  C      A    A P     A    A M   M E     D   D  I  A    A
   CCCC  A    A P     A    A M   M EEEEE DDDD  III A    A
[/bold cyan]
[dim]   v{version} - multi-harness toolkit para migraciones legacy -> hexagonal OLA1[/dim]
"""


HARNESS_DESCRIPTIONS = {
    "claude": "Claude Code (Anthropic CLI) - el mas integrado, soporta MCP nativo",
    "cursor": "Cursor IDE - rules files + MCP",
    "windsurf": "Windsurf IDE - rules + MCP",
    "copilot": "GitHub Copilot - prompts via .github/prompts/",
    "codex": "OpenAI Codex CLI - .codex/prompts/ + AGENTS.md",
    "opencode": "opencode - .opencode/ + AGENTS.md",
}


def _interactive_harness_picker() -> list[str]:
    """Ask the user one by one which harnesses to enable."""
    console.print("[bold]Selecciona los harnesses AI para este proyecto:[/bold]")
    console.print("[dim]Podes usar mas de uno. Claude Code es el mas completo.[/dim]\n")

    chosen: list[str] = []
    for harness_name in ALL_HARNESSES:
        desc = HARNESS_DESCRIPTIONS.get(harness_name, "")
        default = harness_name == "claude"
        if Confirm.ask(f"  [cyan]{harness_name}[/cyan] - {desc}", default=default):
            chosen.append(harness_name)

    if not chosen:
        console.print("\n[yellow]No seleccionaste ninguno.[/yellow]")
        if Confirm.ask("Queres continuar sin harnesses AI (solo scaffolding base)?", default=False):
            return []
        raise typer.Exit(1)

    return chosen


def _update_gitignore(target_dir: Path) -> None:
    gi = target_dir / ".gitignore"
    block = (
        "\n# CapaMedia CLI - NO commitear secrets\n"
        ".mcp.json\n"
        ".capamedia/\n"
        "legacy/\n"
        "umps/\n"
        "tx/\n"
        "gold-ref/\n"
        "destino/build/\n"
        "destino/.gradle/\n"
        "ANALISIS_*.md\n"
        "COMPLEXITY_*.md\n"
        "CHECKLIST_*.md\n"
        "FABRICS_PROMPT*.md\n"
    )
    if gi.exists():
        current = gi.read_text(encoding="utf-8")
        if "# CapaMedia CLI" in current:
            return
        gi.write_text(current + block, encoding="utf-8")
    else:
        gi.write_text(block.lstrip("\n"), encoding="utf-8")


def _create_layout(target_dir: Path, service_name: str) -> None:
    """Create the expected folder structure for a migration workspace."""
    for d in (".capamedia",):
        (target_dir / d).mkdir(parents=True, exist_ok=True)


def _copy_templates(target_dir: Path, service_name: str, artifact_token_placeholder: str) -> None:
    """Render templates (CLAUDE.md, .mcp.json, .sonarlint/, etc.) into target."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    tpl_dir = DATA_ROOT / "templates"
    if not tpl_dir.exists():
        return

    env = Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )
    ctx = {
        "service_name": service_name,
        "artifact_token_placeholder": artifact_token_placeholder,
        "cli_version": __version__,
    }

    # Nota: CLAUDE.md / AGENTS.md lo generan los adapters. Aca renderizamos
    # solo los templates que NO son cubiertos por adapters.
    rendered_map = {
        "mcp.json.j2": ".mcp.json",
        "sonarlint-connectedMode.json.j2": ".sonarlint/connectedMode.json",
    }
    for src_name, dest_rel in rendered_map.items():
        src = tpl_dir / src_name
        if not src.exists():
            continue
        dest = target_dir / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(env.get_template(src_name).render(**ctx), encoding="utf-8")


def _post_process_agent_docs(target_dir: Path, service_name: str, cli_version: str) -> None:
    """Prepend service-specific metadata header to CLAUDE.md / AGENTS.md.

    Los adapters (Claude/Codex/opencode) generan CLAUDE.md o AGENTS.md concatenando
    los archivos de context. Aca le agregamos al principio un header con el nombre
    del servicio y el flujo esperado, para que cada proyecto tenga su identidad.
    """
    header = (
        f"# {service_name} - Migracion CapaMedia OLA1\n\n"
        f"Proyecto generado por `capamedia init` (v{cli_version}).\n\n"
        f"- **Servicio:** `{service_name}`\n"
        f"- **Flujo esperado:** `/clone {service_name}` -> `/fabric` -> `/migrate` -> `/check`\n\n"
        f"El contenido siguiente es contexto comun para toda migracion CapaMedia.\n\n"
        f"---\n\n"
    )

    for candidate in ("CLAUDE.md", "AGENTS.md"):
        path = target_dir / candidate
        if not path.exists():
            continue
        existing = path.read_text(encoding="utf-8")
        # Avoid duplicating header on repeated runs
        if existing.startswith(f"# {service_name} - Migracion CapaMedia OLA1"):
            continue
        path.write_text(header + existing, encoding="utf-8")


def _save_config(target_dir: Path, service_name: str, harnesses: list[str]) -> None:
    config = {
        "version": __version__,
        "service_name": service_name,
        "ai": harnesses,
    }
    (target_dir / ".capamedia").mkdir(exist_ok=True)
    (target_dir / ".capamedia" / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def scaffold_project(
    target_dir: Path,
    service_name: str,
    harnesses: list[str],
    artifact_token: str | None = None,
) -> tuple[int, list[str]]:
    """Render the non-interactive project scaffold into an explicit target dir."""
    target_dir = target_dir.resolve()
    token_val = artifact_token or "${CAPAMEDIA_ARTIFACT_TOKEN}"

    _create_layout(target_dir, service_name)
    _copy_templates(target_dir, service_name, token_val)
    _update_gitignore(target_dir)

    assets = load_canonical_assets()
    total_files = 0
    all_warnings: list[str] = []
    for harness_name in harnesses:
        adapter = get_adapter(harness_name)
        written, warnings = adapter.render_all(assets, target_dir)
        total_files += len(written)
        all_warnings.extend(warnings)

    _post_process_agent_docs(target_dir, service_name, __version__)
    _save_config(target_dir, service_name, harnesses)
    return total_files, all_warnings


def init_project(
    service_name: Annotated[
        Optional[str],
        typer.Argument(help="Nombre del servicio a migrar (ej: wsclientes0008) o '.' para CWD"),
    ] = None,
    ai: Annotated[
        Optional[str],
        typer.Option(
            "--ai",
            help=f"Harness(es): {', '.join(ALL_HARNESSES)}, all, none. CSV permitido. Si se omite, pregunta interactivamente.",
        ),
    ] = None,
    here: Annotated[
        bool,
        typer.Option("--here", help="Inicializar en el directorio actual"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="No preguntar si el directorio no esta vacio"),
    ] = False,
    artifact_token: Annotated[
        Optional[str],
        typer.Option(
            "--artifact-token",
            help="Token de Azure Artifacts para el MCP Fabrics. Si se omite, usa el placeholder ${CAPAMEDIA_ARTIFACT_TOKEN}",
        ),
    ] = None,
) -> None:
    """Inicializa un proyecto CapaMedia con los slash commands del harness elegido."""
    # Resolve target dir
    if here or service_name == ".":
        target_dir = Path.cwd()
        if service_name == "." or not service_name:
            service_name = target_dir.name
    elif service_name:
        target_dir = Path.cwd() / service_name
    else:
        console.print("[red]Error:[/red] pasa el nombre del servicio o usa --here")
        raise typer.Exit(1)

    console.print(LOGO.format(version=__version__))

    # Resolve harnesses
    try:
        if ai is None:
            harnesses = _interactive_harness_picker()
        else:
            harnesses = resolve_harnesses(ai)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # Check empty
    if target_dir.exists() and any(target_dir.iterdir()):
        if not force and not here:
            console.print(f"[yellow]Advertencia:[/yellow] '{target_dir}' no esta vacio")
            if not Confirm.ask("Continuar igual?", default=False):
                raise typer.Exit(0)

    target_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"  Servicio : [bold]{service_name}[/bold]")
    console.print(f"  Path     : [bold]{target_dir}[/bold]")
    if harnesses:
        console.print(f"  Harnesses: [bold]{', '.join(harnesses)}[/bold]")
    else:
        console.print("  Harnesses: [dim]ninguno (solo scaffold base)[/dim]")
    console.print()

    total_files, all_warnings = scaffold_project(
        target_dir=target_dir,
        service_name=service_name,
        harnesses=harnesses,
        artifact_token=artifact_token,
    )

    for harness_name in harnesses:
        adapter = get_adapter(harness_name)
        console.print(
            f"  [green]OK[/green] {adapter.display_name}: scaffold listo"
        )

    if all_warnings:
        console.print()
        console.print("[yellow]Warnings:[/yellow]")
        for w in all_warnings:
            console.print(f"  - {w}")

    console.print()
    console.print(f"[green]OK[/green] Proyecto inicializado ({total_files} archivos AI)")
    console.print()
    console.print("[bold]Proximos pasos:[/bold]")
    console.print(f"  1. [cyan]cd {target_dir}[/cyan]")
    console.print(f"  2. Abri el IDE preferido ([cyan]code .[/cyan], [cyan]claude[/cyan], [cyan]cursor .[/cyan])")
    console.print(f"  3. En el chat del IDE, ejecuta los slash commands:")
    console.print(f"     [cyan]/clone {service_name}[/cyan]  - trae legacy + UMPs + TX")
    console.print(f"     [cyan]/fabric[/cyan]               - genera arquetipo con el MCP")
    console.print(f"     [cyan]/migrate[/cyan]              - migra la logica al destino")
    console.print(f"     [cyan]/check[/cyan]                - ejecuta checklist post-migracion")
    console.print()
    if (artifact_token or "${CAPAMEDIA_ARTIFACT_TOKEN}") == "${CAPAMEDIA_ARTIFACT_TOKEN}":
        console.print(
            "[yellow]Recordatorio:[/yellow] el .mcp.json usa ${CAPAMEDIA_ARTIFACT_TOKEN}. "
            "Expone esa env var o edita .mcp.json con tu token de Azure Artifacts antes de usar el MCP."
        )
