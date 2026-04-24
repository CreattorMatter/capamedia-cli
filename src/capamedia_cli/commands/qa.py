"""capamedia qa - prepara QA de equivalencia funcional en VDI.

El flujo QA vive en VS Code/Copilot mediante prompt files. El CLI solo prepara
el workspace con legacy + destino + TRAMAS.txt + `.github/prompts/qa.prompt.md`.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli import __version__
from capamedia_cli.commands.clone import (
    AZURE_FALLBACK_PATTERNS,
    _git_clone,
    normalize_service_name,
)
from capamedia_cli.commands.fabrics import (
    NAMESPACE_OPTIONS,
    _autodetect_service_name_from_config,
)

console = Console()

app = typer.Typer(
    help="Prepara QA de equivalencia funcional para VS Code/Copilot en VDI.",
    no_args_is_help=True,
)


@dataclass(frozen=True)
class QaWorkspace:
    service: str
    workspace: Path
    legacy_path: Path | None
    destino_path: Path | None
    tramas_path: Path
    prompt_path: Path


def _has_gradle_build(path: Path) -> bool:
    return (path / "build.gradle").exists() or (path / "build.gradle.kts").exists()


def _safe_rel(path: Path | None, root: Path) -> str:
    if path is None:
        return "(no encontrado)"
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _infer_service_name(service_name: str | None, workspace: Path) -> str:
    raw = (
        service_name
        or _autodetect_service_name_from_config(workspace)
        or workspace.name
    )
    service, _ = normalize_service_name(raw)
    return service


def _write_config(workspace: Path, service: str) -> Path:
    capamedia_dir = workspace / ".capamedia"
    capamedia_dir.mkdir(parents=True, exist_ok=True)
    path = capamedia_dir / "config.yaml"

    data: dict[str, object] = {}
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                data = dict(loaded)
        except (OSError, yaml.YAMLError):
            data = {}

    data["service_name"] = service
    data.setdefault("version", __version__)
    data.setdefault("ai", ["copilot"])
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def _find_existing_legacy(workspace: Path, service: str) -> Path | None:
    base = workspace / "legacy"
    if not base.is_dir():
        return None
    candidates = sorted(p for p in base.iterdir() if p.is_dir())
    if not candidates:
        return None
    preferred_names = (
        f"sqb-msa-{service}",
        f"ws-{service}-was",
        f"ms-{service}-was",
    )
    for name in preferred_names:
        candidate = base / name
        if candidate.is_dir():
            return candidate
    preferred = [p for p in candidates if service in p.name.lower()]
    return preferred[0] if preferred else candidates[0]


def _find_existing_destino(workspace: Path, service: str) -> Path | None:
    base = workspace / "destino"
    if not base.is_dir():
        return None
    candidates = sorted(p for p in base.iterdir() if p.is_dir())
    if not candidates:
        return None
    with_gradle = [p for p in candidates if _has_gradle_build(p)]
    pool = with_gradle or candidates
    preferred = [p for p in pool if service in p.name.lower()]
    return preferred[0] if preferred else pool[0]


def _clone_legacy(workspace: Path, service: str, *, shallow: bool) -> Path:
    errors: list[str] = []
    for project_key, pattern in AZURE_FALLBACK_PATTERNS:
        if project_key not in {"bus", "was"}:
            continue
        repo_name = pattern.format(svc=service)
        dest = workspace / "legacy" / repo_name
        ok, err = _git_clone(repo_name, dest, project_key=project_key, shallow=shallow)
        if ok:
            return dest
        if err:
            errors.append(f"{project_key}/{repo_name}: {err}")
    detail = "; ".join(errors[-3:]) if errors else "sin candidatos"
    raise RuntimeError(f"no se pudo clonar legacy para {service}: {detail}")


def _candidate_destino_repos(
    service: str,
    *,
    namespace: str | None,
    destino_repo: str | None,
) -> list[str]:
    if destino_repo:
        return [destino_repo]
    namespaces = [namespace] if namespace else NAMESPACE_OPTIONS
    return [f"{ns}-msa-sp-{service}" for ns in namespaces if ns]


def _clone_destino(
    workspace: Path,
    service: str,
    *,
    namespace: str | None,
    destino_repo: str | None,
    shallow: bool,
) -> Path:
    errors: list[str] = []
    for repo_name in _candidate_destino_repos(
        service,
        namespace=namespace,
        destino_repo=destino_repo,
    ):
        dest = workspace / "destino" / repo_name
        ok, err = _git_clone(repo_name, dest, project_key="middleware", shallow=shallow)
        if ok:
            return dest
        if err:
            errors.append(f"middleware/{repo_name}: {err}")
    detail = "; ".join(errors[-4:]) if errors else "sin candidatos"
    raise RuntimeError(f"no se pudo clonar destino migrado para {service}: {detail}")


def _tramas_path(workspace: Path) -> Path:
    for name in ("TRAMAS.txt", "tramas.txt", "Tramas.txt"):
        candidate = workspace / name
        if candidate.exists():
            return candidate
    return workspace / "TRAMAS.txt"


def _write_tramas_placeholder(workspace: Path) -> Path:
    path = _tramas_path(workspace)
    if path.exists():
        return path
    path.write_text(
        "# TRAMAS.txt\n"
        "# Pega aca las tramas oficiales del legacy.\n"
        "# Puede ser formato libre; el prompt /qa debe interpretarlo sin inventar expected.\n"
        "\n"
        "=== CASE: happy_path ===\n"
        "REQUEST:\n"
        "<!-- pegar request/body si esta disponible -->\n"
        "\n"
        "EXPECTED_RESPONSE:\n"
        "<!-- pegar response legacy esperado -->\n"
        "=== END CASE ===\n",
        encoding="utf-8",
    )
    return path


def _write_status_placeholder(workspace: Path, service: str) -> Path:
    path = workspace / "QA_STATUS.md"
    if path.exists():
        return path
    path.write_text(
        f"# QA Status: {service}\n\n"
        "Estado inicial generado por `capamedia qa pack`.\n\n"
        "- Pendiente: completar `TRAMAS.txt` con respuestas legacy.\n"
        "- Pendiente: ejecutar `/qa` desde Copilot Chat en VS Code.\n",
        encoding="utf-8",
    )
    return path


def _write_command_prompt_notes(workspace: Path) -> Path:
    qa_dir = workspace / ".capamedia" / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    path = qa_dir / "README.md"
    path.write_text(
        "# CapaMedia QA\n\n"
        "Este circuito esta pensado para VDI con Command Prompt disponible.\n\n"
        "- No se generan scripts PowerShell.\n"
        "- No se requieren comandos Bash.\n"
        "- Ejecuta `/qa` en Copilot Chat desde VS Code.\n"
        "- Si necesitas terminal, usa Command Prompt (`cmd.exe`) y `curl.exe`.\n"
        "- `TRAMAS.txt` es el oraculo de respuestas legacy; no lo modifiques desde la IA.\n",
        encoding="utf-8",
    )
    return path


def _write_vscode_cmd_settings(workspace: Path) -> Path:
    settings_dir = workspace / ".vscode"
    settings_dir.mkdir(parents=True, exist_ok=True)
    path = settings_dir / "settings.json"

    data: dict[str, object] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = dict(loaded)
        except (OSError, json.JSONDecodeError):
            data = {}

    profiles_raw = data.get("terminal.integrated.profiles.windows")
    profiles = dict(profiles_raw) if isinstance(profiles_raw, dict) else {}
    profiles["Command Prompt"] = {
        "path": "C:\\Windows\\System32\\cmd.exe",
        "args": [],
    }
    data["terminal.integrated.profiles.windows"] = profiles
    data["terminal.integrated.defaultProfile.windows"] = "Command Prompt"
    data["terminal.integrated.automationProfile.windows"] = {
        "path": "C:\\Windows\\System32\\cmd.exe",
        "args": [],
    }
    data["chat.tools.terminal.terminalProfile.windows"] = "Command Prompt"

    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _prompt_text(
    *,
    service: str,
    workspace: Path,
    legacy_path: Path | None,
    destino_path: Path | None,
    tramas_path: Path,
) -> str:
    legacy_rel = _safe_rel(legacy_path, workspace)
    destino_rel = _safe_rel(destino_path, workspace)
    tramas_rel = _safe_rel(tramas_path, workspace)
    return (
        "---\n"
        "name: qa\n"
        "description: QA de equivalencia funcional CapaMedia contra TRAMAS.txt\n"
        "agent: agent\n"
        "tools: ['search/codebase', 'execute/runInTerminal', 'execute/getTerminalOutput', 'edit/editFiles']\n"
        "---\n"
        "\n"
        f"# CapaMedia QA - {service}\n"
        "\n"
        "Sos un agente de QA de equivalencia funcional para una migracion CapaMedia.\n"
        "Este prompt debe funcionar con cualquier modelo disponible en Copilot Chat.\n"
        "\n"
        "## Workspace\n"
        "\n"
        f"- Legacy: [{legacy_rel}]({legacy_rel})\n"
        f"- Migrado: [{destino_rel}]({destino_rel})\n"
        f"- Tramas legacy: [{tramas_rel}]({tramas_rel})\n"
        "- Estado QA: [QA_STATUS.md](../../QA_STATUS.md)\n"
        "\n"
        "## Reglas duras\n"
        "\n"
        "- Usa Command Prompt (`cmd.exe`) para comandos de terminal.\n"
        "- No uses PowerShell. No ejecutes `powershell.exe`, `pwsh`, `Get-Content`, `Select-String` ni scripts `.ps1`.\n"
        "- No uses Bash como requisito; este workspace esta preparado para `cmd.exe`.\n"
        "- Para leer archivos usa `type`, para listar usa `dir`, para variables usa `set VAR=valor`.\n"
        "- Si Copilot muestra `Cannot create process` con `powershell.exe`, avisa que el usuario debe correr `capamedia qa prepare`, cerrar/reabrir VS Code y reintentar. No sigas insistiendo con PowerShell.\n"
        "- No modifiques `legacy/`.\n"
        "- No modifiques `TRAMAS.txt`; es el oraculo de respuestas legacy.\n"
        "- No inventes respuestas esperadas. Si una trama no permite identificar request o expected, marca BLOCKED y pregunta.\n"
        "- Solo modifica archivos dentro de `destino/` y `QA_STATUS.md`.\n"
        "- No declares OK si existe una diferencia funcional.\n"
        "\n"
        "## Objetivo\n"
        "\n"
        "1. Lee `TRAMAS.txt` completo e identifica los casos de prueba disponibles.\n"
        "2. Inspecciona `legacy/` solo para entender reglas que puedan faltar en el migrado.\n"
        "3. Ubica el proyecto Spring Boot dentro de `destino/`.\n"
        "4. Si el usuario paso `target=...` junto a `/qa`, usa ese endpoint.\n"
        "5. Si no hay `target`, intenta levantar el migrado localmente desde Command Prompt o pregunta una sola vez por la URL.\n"
        "6. Ejecuta `curl.exe` para cada request encontrado en `TRAMAS.txt`.\n"
        "7. Compara cada response migrada contra la response legacy esperada del mismo archivo.\n"
        "8. Si hay diferencias, corrige `destino/`, recompila y repite los curls hasta PASS o BLOCKED.\n"
        "9. Actualiza `QA_STATUS.md` con casos, comandos ejecutados, diferencias y cambios aplicados.\n"
        "\n"
        "## Normalizacion permitida\n"
        "\n"
        "Podes ignorar solamente diferencias tecnicas no funcionales:\n"
        "\n"
        "- whitespace XML/JSON\n"
        "- orden de atributos XML\n"
        "- orden de claves JSON\n"
        "- timestamps\n"
        "- traceId, requestId, correlationId u otros identificadores dinamicos\n"
        "- duraciones, hostnames y detalles internos de infraestructura\n"
        "\n"
        "No ignores diferencias funcionales:\n"
        "\n"
        "- codigo\n"
        "- mensaje visible de negocio\n"
        "- tipo\n"
        "- backend\n"
        "- recurso\n"
        "- componente\n"
        "- payload funcional\n"
        "- cardinalidad de listas\n"
        "- campos faltantes o extras visibles para el consumidor\n"
        "\n"
        "## Comandos Command Prompt sugeridos\n"
        "\n"
        "Para compilar:\n"
        "\n"
        "```bat\n"
        "cd /d destino\\<proyecto>\n"
        "gradlew.bat generateFromWsdl clean build --no-daemon\n"
        "```\n"
        "\n"
        "Si Gradle falla por cache/permisos, usa un home local:\n"
        "\n"
        "```bat\n"
        "cd /d destino\\<proyecto>\n"
        "set GRADLE_USER_HOME=%CD%\\.gradle-home\n"
        "gradle generateFromWsdl clean build --no-daemon --offline\n"
        "```\n"
        "\n"
        "Para ejecutar curl con body temporal:\n"
        "\n"
        "```bat\n"
        "if not exist .capamedia\\qa\\results mkdir .capamedia\\qa\\results\n"
        "set TARGET_URL=http://localhost:8080\n"
        "curl.exe -sS -X POST \"%TARGET_URL%\" -H \"Content-Type: text/xml; charset=utf-8\" --data-binary @.capamedia\\qa\\tmp\\request.xml -o .capamedia\\qa\\results\\<case-id>.response.xml\n"
        "type .capamedia\\qa\\results\\<case-id>.response.xml\n"
        "```\n"
        "\n"
        "Si el terminal intenta abrir PowerShell y falla, no sigas intentando PowerShell. Usa el perfil `Command Prompt` de VS Code. Este workspace debe tener `chat.tools.terminal.terminalProfile.windows = Command Prompt` en `.vscode/settings.json`; si no esta, pide ejecutar `capamedia qa prepare` y reabrir VS Code.\n"
        "\n"
        "## Fallback si Copilot no puede crear procesos\n"
        "\n"
        "Si la VDI bloquea la herramienta de terminal de Copilot por GPO/antivirus, no inventes resultados.\n"
        "Pide al usuario ejecutar manualmente los comandos `cmd.exe` necesarios en una ventana externa de Command Prompt y pegar el output en el chat.\n"
        "Mientras tanto, podes usar lectura/edicion de archivos desde VS Code para preparar fixes, pero no podes declarar PASS sin evidencia de `curl.exe` o build.\n"
        "\n"
        "## Criterio de cierre\n"
        "\n"
        "Termina con `PASS` solo si todos los casos de `TRAMAS.txt` matchean funcionalmente.\n"
        "Si falta informacion externa o el endpoint no responde, termina con `BLOCKED` y deja claro que falta.\n"
    )


def _write_prompt(
    *,
    service: str,
    workspace: Path,
    legacy_path: Path | None,
    destino_path: Path | None,
    tramas_path: Path,
) -> Path:
    prompts_dir = workspace / ".github" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    path = prompts_dir / "qa.prompt.md"
    path.write_text(
        _prompt_text(
            service=service,
            workspace=workspace,
            legacy_path=legacy_path,
            destino_path=destino_path,
            tramas_path=tramas_path,
        ),
        encoding="utf-8",
    )
    return path


def _write_pack_metadata(qw: QaWorkspace) -> Path:
    qa_dir = qw.workspace / ".capamedia" / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    path = qa_dir / "pack.json"
    payload = {
        "generated_by": "capamedia qa pack",
        "cli_version": __version__,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "service": qw.service,
        "workspace": str(qw.workspace),
        "legacy_path": str(qw.legacy_path) if qw.legacy_path else "",
        "destino_path": str(qw.destino_path) if qw.destino_path else "",
        "tramas_path": str(qw.tramas_path),
        "prompt_path": str(qw.prompt_path),
        "shell": "cmd",
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _render_summary(qw: QaWorkspace) -> None:
    table = Table(title="CapaMedia QA pack", title_style="bold cyan")
    table.add_column("Item", style="cyan")
    table.add_column("Estado")
    table.add_column("Path")
    table.add_row(
        "legacy",
        "[green]OK[/green]" if qw.legacy_path else "[red]MISSING[/red]",
        _safe_rel(qw.legacy_path, qw.workspace),
    )
    table.add_row(
        "destino",
        "[green]OK[/green]" if qw.destino_path else "[red]MISSING[/red]",
        _safe_rel(qw.destino_path, qw.workspace),
    )
    table.add_row("tramas", "[green]OK[/green]", _safe_rel(qw.tramas_path, qw.workspace))
    table.add_row("prompt /qa", "[green]OK[/green]", _safe_rel(qw.prompt_path, qw.workspace))
    table.add_row("shell QA", "[green]Command Prompt[/green]", "cmd.exe")
    console.print(table)


def _prepare_workspace(
    *,
    service: str,
    workspace: Path,
    legacy_path: Path | None,
    destino_path: Path | None,
) -> QaWorkspace:
    _write_config(workspace, service)
    tramas = _write_tramas_placeholder(workspace)
    _write_status_placeholder(workspace, service)
    _write_command_prompt_notes(workspace)
    _write_vscode_cmd_settings(workspace)
    prompt = _write_prompt(
        service=service,
        workspace=workspace,
        legacy_path=legacy_path,
        destino_path=destino_path,
        tramas_path=tramas,
    )
    qw = QaWorkspace(
        service=service,
        workspace=workspace,
        legacy_path=legacy_path,
        destino_path=destino_path,
        tramas_path=tramas,
        prompt_path=prompt,
    )
    _write_pack_metadata(qw)
    return qw


@app.command("pack")
def pack(
    service_name: Annotated[
        str | None,
        typer.Argument(
            help="Servicio a preparar. Si se omite, usa .capamedia/config.yaml o el nombre del CWD.",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", "-w", help="Workspace root (default: CWD)"),
    ] = None,
    namespace: Annotated[
        str | None,
        typer.Option(
            "--namespace",
            "-n",
            help="Namespace del repo migrado (tnd/tpr/csg/tmp/tia/tct). Si se omite, prueba todos.",
        ),
    ] = None,
    destino_repo: Annotated[
        str | None,
        typer.Option("--destino-repo", help="Nombre exacto del repo migrado en middleware."),
    ] = None,
    shallow: Annotated[
        bool,
        typer.Option("--shallow/--full", help="Usa git clone --depth 1 para los repos."),
    ] = True,
    no_clone: Annotated[
        bool,
        typer.Option("--no-clone", help="No intenta clonar; solo prepara prompt con lo local."),
    ] = False,
) -> None:
    """Trae/ubica legacy + destino y genera el slash command `/qa` para Copilot."""
    ws = (workspace or Path.cwd()).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    service = _infer_service_name(service_name, ws)

    if namespace and namespace not in NAMESPACE_OPTIONS:
        raise typer.BadParameter(
            f"namespace invalido: {namespace}. Opciones: {', '.join(NAMESPACE_OPTIONS)}"
        )

    console.print(
        Panel.fit(
            f"[bold]CapaMedia QA pack[/bold]\n"
            f"Servicio: [cyan]{service}[/cyan]\n"
            f"Workspace: [cyan]{ws}[/cyan]\n"
            "Shell QA: [green]Command Prompt[/green]",
            border_style="cyan",
        )
    )

    legacy_path = _find_existing_legacy(ws, service)
    destino_path = _find_existing_destino(ws, service)

    if not no_clone and legacy_path is None:
        console.print("[bold]Clonando legacy[/bold] (BUS/WAS)...")
        try:
            legacy_path = _clone_legacy(ws, service, shallow=shallow)
            console.print(f"  [green]OK[/green] {_safe_rel(legacy_path, ws)}")
        except RuntimeError as exc:
            console.print(f"  [red]FAIL[/red] {exc}")

    if not no_clone and destino_path is None:
        console.print("[bold]Clonando destino migrado[/bold] (middleware)...")
        try:
            destino_path = _clone_destino(
                ws,
                service,
                namespace=namespace,
                destino_repo=destino_repo,
                shallow=shallow,
            )
            console.print(f"  [green]OK[/green] {_safe_rel(destino_path, ws)}")
        except RuntimeError as exc:
            console.print(f"  [red]FAIL[/red] {exc}")

    qw = _prepare_workspace(
        service=service,
        workspace=ws,
        legacy_path=legacy_path,
        destino_path=destino_path,
    )
    _render_summary(qw)

    if qw.legacy_path is None or qw.destino_path is None:
        console.print(
            "\n[yellow]Pack parcial:[/yellow] completa legacy/ y destino/ y luego corre "
            "[cyan]capamedia qa prepare[/cyan]."
        )
    console.print(
        "\n[bold]Siguiente paso:[/bold]\n"
        "  1. Completa [cyan]TRAMAS.txt[/cyan] si sigue con placeholder.\n"
        "  2. Abri VS Code: [cyan]code .[/cyan]\n"
        "  3. En Copilot Chat ejecuta: [cyan]/qa target=http://localhost:8080[/cyan]\n"
    )


@app.command("prepare")
def prepare(
    service_name: Annotated[
        str | None,
        typer.Argument(
            help="Servicio a preparar. Si se omite, usa .capamedia/config.yaml o el nombre del CWD.",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", "-w", help="Workspace root (default: CWD)"),
    ] = None,
) -> None:
    """Regenera `.github/prompts/qa.prompt.md` sin clonar repos."""
    ws = (workspace or Path.cwd()).resolve()
    service = _infer_service_name(service_name, ws)
    legacy_path = _find_existing_legacy(ws, service)
    destino_path = _find_existing_destino(ws, service)
    qw = _prepare_workspace(
        service=service,
        workspace=ws,
        legacy_path=legacy_path,
        destino_path=destino_path,
    )
    _render_summary(qw)
    if qw.legacy_path is None or qw.destino_path is None:
        raise typer.Exit(1)
