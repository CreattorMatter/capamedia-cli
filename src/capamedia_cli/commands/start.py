"""capamedia start - wizard orquestador "un click" (alias: go, wizard).

North Star (docs/BLUEPRINT_WIZARD_GO.md): un comando que migra un servicio de
0 a 100 con subagentes de punta a punta. Se construye por fases incrementales.

- **Fase 1**: fachada NO-interactiva sobre `batch._process_pipeline_service`
  (clone -> init -> fabrics -> migrate, con resume idempotente). Fuerza Opus 4.8.
- **Fase 2 (esta version)**: capa de entrada interactiva — Panel "Bienvenido a
  Capa Media", preflight verde/rojo NO-bloqueante (PAT + engine), menú raíz
  numerado (estilo Claude Code, sin deps nuevas: `rich.Prompt.ask(choices=...)`),
  y detección de `wizard.json` para reanudar. El sub-wizard de inputs (pedir
  servicio/OLA/rama interactivamente) llega en la Fase 3.

Reglas firmes: modelo SIEMPRE Opus 4.8 (el wizard nunca pregunta modelo); no se
reimplementa lógica (se reusan funciones existentes); el wizard CONVIVE con los
comandos shell/batch, no los reemplaza.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from capamedia_cli import __version__
from capamedia_cli.commands.init import LOGO
from capamedia_cli.core.auth import probe_azure_devops_pat
from capamedia_cli.core.engine import available_engines, engine_from_env, select_engine
from capamedia_cli.core.model_policy import anthropic_model, engine_model

console = Console()

WIZARD_STATE_FILE = "wizard.json"
# Modelo mostrado en la bienvenida (claude-first). El modelo REAL que se pasa al
# pipeline se deriva del engine activo con engine_model("opus", engine.name) —
# claude -> claude-opus-4-8, codex -> gpt-5.5 (el tope de cada engine).
OPUS_MODEL = anthropic_model("opus")


# ── Persistencia de decisiones (contrato para las fases siguientes) ──────────


def _save_wizard_decisions(service_workspace: Path, decisions: dict) -> Path:
    """Persiste las decisiones del wizard en <service_workspace>/.capamedia/wizard.json.

    NO es el state de progreso del pipeline (eso lo maneja batch_state con
    run_kind="pipeline"); son las decisiones de entrada para no re-preguntar.
    """
    cap = service_workspace / ".capamedia"
    cap.mkdir(parents=True, exist_ok=True)
    dest = cap / WIZARD_STATE_FILE
    dest.write_text(json.dumps(decisions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def load_wizard_decisions(service_workspace: Path) -> dict:
    """Lee las decisiones guardadas; {} si no existe o esta corrupto."""
    dest = service_workspace / ".capamedia" / WIZARD_STATE_FILE
    if dest.is_file():
        try:
            data = json.loads(dest.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _find_resumable(root: Path) -> list[str]:
    """Servicios con un wizard.json previo bajo `root` (para ofrecer reanudar)."""
    found: list[str] = []
    if not root.is_dir():
        return found
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / ".capamedia" / WIZARD_STATE_FILE).is_file():
            found.append(child.name)
    return found


# ── Bienvenida + preflight (Fase 2) ──────────────────────────────────────────


def _welcome_panel() -> None:
    console.print(LOGO.format(version=__version__))
    console.print(
        Panel.fit(
            "[bold cyan]Bienvenido a Capa Media[/bold cyan]\n"
            f"Orquestador de migracion · v{__version__}\n"
            f"Modelo: [magenta]{OPUS_MODEL}[/magenta] [dim](siempre Opus — calidad sobre costo)[/dim]",
            border_style="cyan",
        )
    )


def _run_preflight(claude_bin: str, codex_bin: str) -> dict:
    """Chequeo verde/rojo NO-bloqueante de los prerequisitos. Solo informa.

    Devuelve un dict con el estado para que el menu lo muestre sin re-chequear.
    """
    pat_status, pat_detail = probe_azure_devops_pat()
    engines = available_engines(claude_bin=claude_bin, codex_bin=codex_bin)
    return {"pat": (pat_status, pat_detail), "engines": engines}


def _render_preflight(preflight: dict) -> None:
    table = Table(title="Preflight (no bloquea — solo avisa)", title_style="bold cyan")
    table.add_column("Check")
    table.add_column("Estado")
    table.add_column("Detalle")

    pat_status, pat_detail = preflight["pat"]
    pat_ok = pat_status == "ok"
    table.add_row(
        "Azure DevOps PAT",
        "[green]OK[/green]" if pat_ok else f"[yellow]{pat_status.upper()}[/yellow]",
        pat_detail if not pat_ok else "PAT con acceso de lectura",
    )

    for name, (ok, detail) in preflight["engines"].items():
        marker = "[green]OK[/green]" if ok else "[yellow]no disponible[/yellow]"
        table.add_row(f"Engine {name}", marker, detail)

    console.print(table)
    if not preflight["engines"].get("claude", (False, ""))[0]:
        console.print(
            "[yellow]Aviso:[/yellow] el engine 'claude' no esta disponible; la "
            "migracion con Opus requiere Claude CLI. Instalalo o usa --engine codex."
        )


# ── Menu raiz (Fase 2) ────────────────────────────────────────────────────────

_MENU_OPTIONS = [
    ("1", "Iniciar migracion guiada"),
    ("2", "Configuracion: Harnesses (read-only)"),
    ("3", "Configuracion: Credenciales (read-only)"),
    ("4", "Engine y modelo (read-only)"),
    ("0", "Salir"),
]


def _root_menu() -> str:
    table = Table(show_header=False, box=None, padding=(0, 2))
    for key, label in _MENU_OPTIONS:
        table.add_row(f"[bold cyan]{key}[/bold cyan]", label)
    console.print(table)
    return Prompt.ask(
        "Elegi una opcion",
        choices=[k for k, _ in _MENU_OPTIONS],
        default="1",
    )


def _show_harnesses_readonly() -> None:
    from capamedia_cli.adapters import ALL_HARNESSES

    console.print(
        Panel.fit(
            "Harnesses soportados (edicion interactiva en una fase futura):\n"
            + ", ".join(ALL_HARNESSES),
            title="Harnesses",
            border_style="cyan",
        )
    )


def _show_engine_model_readonly(preflight: dict) -> None:
    lines = [f"Modelo: [magenta]{OPUS_MODEL}[/magenta] (siempre Opus — no configurable)"]
    for name, (ok, detail) in preflight["engines"].items():
        lines.append(f"Engine {name}: {'disponible' if ok else 'no disponible'} — {detail}")
    console.print(Panel.fit("\n".join(lines), title="Engine y modelo", border_style="cyan"))


# ── Fachada Fase 1 (reusable desde flags y desde el menu) ────────────────────


def _run_pipeline_facade(
    *,
    service: str,
    namespace: str,
    branch: str | None,
    ws: Path,
    engine_name: str,
    claude_bin: str,
    codex_bin: str,
    ai: str,
    group_id: str,
    artifact_token: str | None,
    timeout_minutes: int,
    shallow: bool,
    skip_tx: bool,
    skip_check: bool,
    unsafe: bool,
    resume: bool,
) -> None:
    """Orquesta el pipeline existente para UN servicio, forzando Opus 4.8.

    No reimplementa logica: importa y llama `batch._process_pipeline_service`.
    """
    from capamedia_cli.adapters import resolve_harnesses
    from capamedia_cli.commands.batch import (
        _ensure_migrate_schema,
        _process_pipeline_service,
    )

    env_pref = engine_from_env()
    eff_engine_name = env_pref or engine_name
    try:
        engine = select_engine(eff_engine_name, claude_bin=claude_bin, codex_bin=codex_bin)
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None

    harnesses = resolve_harnesses(ai)
    if engine.name not in harnesses:
        harnesses.append(engine.name)

    # Tier "opus" SIEMPRE (decision owner), traducido al modelo del engine activo:
    # claude -> claude-opus-4-8, codex -> gpt-5.5. Evita pasarle un modelo Claude
    # a Codex (o viceversa).
    model = engine_model("opus", engine.name)

    schema_path = _ensure_migrate_schema(ws)

    decisions = {
        "service": service,
        "namespace": namespace,
        "branch": branch,
        "engine": engine.name,
        "model": model,
        "harnesses": harnesses,
        "group_id": group_id,
        "root": str(ws),
        "phase": "1-skeleton",
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    wizard_path = _save_wizard_decisions(ws / service, decisions)

    console.print(
        Panel.fit(
            "[bold]capamedia start[/bold]\n"
            f"Servicio: [cyan]{service}[/cyan] · Namespace: {namespace} · "
            f"Rama: {branch or '[dim](pendiente integracion)[/dim]'}\n"
            f"Engine: [green]{engine.name}[/green] · Modelo: [magenta]{model}[/magenta] "
            "[dim](tier opus del engine activo)[/dim]\n"
            f"Harnesses: {', '.join(harnesses)} · Resume: {'SI' if resume else 'NO'}\n"
            f"Decisiones: [dim]{wizard_path}[/dim]",
            border_style="cyan",
        )
    )

    row = _process_pipeline_service(
        service,
        ws,
        schema_path,
        harnesses=harnesses,
        artifact_token=artifact_token,
        namespace=namespace,
        group_id=group_id,
        engine=engine,
        model=model,
        prompt_file=None,
        timeout_minutes=timeout_minutes,
        skip_tx=skip_tx,
        shallow=shallow,
        skip_check=skip_check,
        unsafe=unsafe,
        reasoning_effort=None,
        resume=resume,
        scheduler=None,
    )

    status_color = "green" if row.status == "ok" else "red"
    console.print(f"\n[bold {status_color}]start {row.status}[/bold {status_color}]: {row.detail}")
    if row.status != "ok":
        raise typer.Exit(1)


def start_command(
    service: Annotated[
        str | None,
        typer.Option("--service", "-s", help="Servicio a migrar (ej: wsclientes0076)"),
    ] = None,
    namespace: Annotated[
        str | None,
        typer.Option("--namespace", "-n", help="Acronimo de nomenclatura: tnd|tpr|csg|tmp|tia|tct"),
    ] = None,
    branch: Annotated[
        str | None,
        typer.Option(
            "--branch",
            "-b",
            help="Rama destino. Se registra; su integracion (verificar/crear/posicionar) llega en una fase posterior.",
        ),
    ] = None,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Carpeta raiz del workspace (default: CWD)"),
    ] = None,
    engine_name: Annotated[
        str,
        typer.Option("--engine", help="Engine AI headless: claude | codex | auto (default claude)"),
    ] = "claude",
    claude_bin: Annotated[str, typer.Option("--claude-bin", help="Binario de Claude Code CLI")] = "claude",
    codex_bin: Annotated[str, typer.Option("--codex-bin", help="Binario de Codex CLI")] = "codex",
    ai: Annotated[str, typer.Option("--ai", help="Harness(es) CSV para el scaffold (default claude)")] = "claude",
    group_id: Annotated[str, typer.Option("--group-id")] = "com.pichincha.sp",
    artifact_token: Annotated[
        str | None,
        typer.Option("--artifact-token", help="Override del token para renderizar .mcp.json"),
    ] = None,
    timeout_minutes: Annotated[int, typer.Option("--timeout-minutes", help="Timeout maximo de migrate")] = 90,
    shallow: Annotated[bool, typer.Option("--shallow", help="Clone superficial")] = False,
    skip_tx: Annotated[bool, typer.Option("--skip-tx", help="No clonar repos de TX")] = False,
    skip_check: Annotated[bool, typer.Option("--skip-check", help="No ejecutar checklist post-migracion")] = False,
    unsafe: Annotated[bool, typer.Option("--unsafe", help="Permisos full para el engine")] = False,
    resume: Annotated[bool, typer.Option("--resume", help="Reanuda saltando etapas ya exitosas")] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="No-interactivo (CI/SSH): corre sin menu ni confirmaciones."),
    ] = False,
) -> None:
    """Wizard orquestador "un click" (Fase 2: bienvenida + menu; fachada no-interactiva con flags).

    Modo no-interactivo: con --service y --namespace (o --yes), corre el pipeline
    directo, forzando Opus 4.8. Modo interactivo (TTY, sin flags completos):
    bienvenida + preflight + menu. El sub-wizard de inputs llega en la Fase 3.
    """
    ws = (root or Path.cwd()).resolve()
    ws.mkdir(parents=True, exist_ok=True)

    facade_kwargs = {
        "branch": branch,
        "ws": ws,
        "engine_name": engine_name,
        "claude_bin": claude_bin,
        "codex_bin": codex_bin,
        "ai": ai,
        "group_id": group_id,
        "artifact_token": artifact_token,
        "timeout_minutes": timeout_minutes,
        "shallow": shallow,
        "skip_tx": skip_tx,
        "skip_check": skip_check,
        "unsafe": unsafe,
    }

    is_tty = sys.stdin.isatty()
    interactive = is_tty and not yes and not (service and namespace)

    # Modo no-interactivo: flags completos, --yes, o sin TTY (CI/SSH).
    if not interactive:
        if not (service and namespace):
            raise typer.BadParameter(
                "Modo no-interactivo (--yes o sin TTY): se requieren --service y --namespace. "
                "El sub-wizard interactivo de inputs llega en una fase posterior."
            )
        _run_pipeline_facade(service=service, namespace=namespace, resume=resume, **facade_kwargs)
        return

    # ── Modo interactivo (Fase 2) ──
    _welcome_panel()
    preflight = _run_preflight(claude_bin, codex_bin)
    _render_preflight(preflight)

    resumable = _find_resumable(ws)
    if resumable:
        console.print(
            f"[dim]Servicios con sesion previa (wizard.json) en este root: "
            f"{', '.join(resumable)}[/dim]"
        )

    while True:
        choice = _root_menu()
        if choice == "0":
            console.print("[dim]Hasta luego.[/dim]")
            return
        if choice == "2":
            _show_harnesses_readonly()
            continue
        if choice == "3":
            _render_preflight(preflight)
            continue
        if choice == "4":
            _show_engine_model_readonly(preflight)
            continue
        if choice == "1":
            # Fase 2: si ya hay service+namespace por flag, corre. Si no, el
            # sub-wizard de inputs es Fase 3 -> guiar al usuario, sin colgar.
            if service and namespace:
                _run_pipeline_facade(
                    service=service, namespace=namespace, resume=resume, **facade_kwargs
                )
                return
            # Solo ofrecemos reanudar otro servicio si el usuario NO especifico
            # uno por flag (evita reanudar X cuando pediste migrar Y).
            if resumable and not service:
                svc = resumable[0]
                prev = load_wizard_decisions(ws / svc)
                ns = prev.get("namespace")
                if ns:
                    console.print(f"[cyan]Reanudando[/cyan] {svc} (namespace={ns})")
                    _run_pipeline_facade(
                        service=svc, namespace=ns, resume=True, **facade_kwargs
                    )
                    return
            console.print(
                "[yellow]El sub-wizard interactivo de inputs (servicio, OLA, rama) "
                "llega en la proxima fase.[/yellow]\n"
                "Por ahora, inicia con flags: "
                "[cyan]capamedia start --service <svc> --namespace <ns>[/cyan]"
            )
            return
