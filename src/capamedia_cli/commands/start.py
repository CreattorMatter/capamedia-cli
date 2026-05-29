"""capamedia start - wizard orquestador "un click" (alias: go, wizard).

North Star (docs/BLUEPRINT_WIZARD_GO.md): un comando que migra un servicio de
0 a 100 con subagentes de punta a punta. Se construye por fases incrementales.

**Fase 1 (esqueleto, esta version)**: fachada NO-interactiva sobre el pipeline
YA probado (`batch._process_pipeline_service`: clone -> init -> fabrics ->
migrate, con resume idempotente). NO reimplementa logica: importa y llama
funciones existentes. Fuerza Opus 4.8 (decision owner, siempre Opus). Persiste
las decisiones en `<ws>/<service>/.capamedia/wizard.json` para que las fases
siguientes (menu, sub-wizard de inputs, rama interactiva, resumen visual) las
reusen. Los prompts interactivos NO existen todavia; el comando corre con flags.

El `--branch` se acepta y se registra pero su integracion real (verificar/crear/
posicionar la rama) llega en una fase posterior del blueprint; hoy NO se pasa al
pipeline. Honestidad alfa.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from capamedia_cli.core.engine import engine_from_env, select_engine
from capamedia_cli.core.model_policy import anthropic_model

console = Console()

WIZARD_STATE_FILE = "wizard.json"


def _save_wizard_decisions(service_workspace: Path, decisions: dict) -> Path:
    """Persiste las decisiones del wizard en <service_workspace>/.capamedia/wizard.json.

    Es el contrato que las fases siguientes leen para no re-preguntar. NO es el
    state de progreso del pipeline (eso lo maneja batch_state con run_kind="pipeline").
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


def start_command(
    service: Annotated[
        str,
        typer.Option("--service", "-s", help="Servicio a migrar (ej: wsclientes0076)"),
    ],
    namespace: Annotated[
        str,
        typer.Option("--namespace", "-n", help="Acronimo de nomenclatura: tnd|tpr|csg|tmp|tia|tct"),
    ],
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
        typer.Option(
            "--engine",
            help="Engine AI headless: claude | codex | auto (default claude — siempre Opus en la nube)",
        ),
    ] = "claude",
    claude_bin: Annotated[
        str, typer.Option("--claude-bin", help="Binario de Claude Code CLI")
    ] = "claude",
    codex_bin: Annotated[
        str, typer.Option("--codex-bin", help="Binario de Codex CLI")
    ] = "codex",
    ai: Annotated[
        str,
        typer.Option("--ai", help="Harness(es) CSV para el scaffold (default claude)"),
    ] = "claude",
    group_id: Annotated[str, typer.Option("--group-id")] = "com.pichincha.sp",
    artifact_token: Annotated[
        str | None,
        typer.Option("--artifact-token", help="Override del token para renderizar .mcp.json"),
    ] = None,
    timeout_minutes: Annotated[
        int, typer.Option("--timeout-minutes", help="Timeout maximo de migrate")
    ] = 90,
    shallow: Annotated[
        bool, typer.Option("--shallow", help="Clone superficial para legacy/UMPs/TX")
    ] = False,
    skip_tx: Annotated[
        bool, typer.Option("--skip-tx", help="No clonar repos individuales de TX")
    ] = False,
    skip_check: Annotated[
        bool, typer.Option("--skip-check", help="No ejecutar checklist post-migracion")
    ] = False,
    unsafe: Annotated[
        bool,
        typer.Option("--unsafe", help="Permisos full para el engine (bypass sandbox/approvals)"),
    ] = False,
    resume: Annotated[
        bool, typer.Option("--resume", help="Reanuda saltando etapas ya exitosas")
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="No-interactivo (CI/SSH): corre sin confirmaciones. Reservado para las fases con prompts.",
        ),
    ] = False,
) -> None:
    """Wizard orquestador "un click" (Fase 1: fachada no-interactiva sobre el pipeline).

    Orquesta clone -> init -> fabrics -> migrate para UN servicio, forzando
    Opus 4.8. No reimplementa logica: reusa `batch._process_pipeline_service`.
    """
    # Imports locales: el pipeline vive en batch.py y evitamos ciclos a nivel modulo.
    from capamedia_cli.adapters import resolve_harnesses
    from capamedia_cli.commands.batch import (
        _ensure_migrate_schema,
        _process_pipeline_service,
    )

    ws = (root or Path.cwd()).resolve()
    ws.mkdir(parents=True, exist_ok=True)

    # Engine: env -> flag. El default de start es claude (siempre Opus en la nube).
    env_pref = engine_from_env()
    eff_engine_name = env_pref or engine_name
    try:
        engine = select_engine(eff_engine_name, claude_bin=claude_bin, codex_bin=codex_bin)
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None

    # MODELO SIEMPRE OPUS (decision owner 2026-05-28). El wizard nunca pregunta modelo.
    model = anthropic_model("opus")

    harnesses = resolve_harnesses(ai)
    if engine.name not in harnesses:
        harnesses.append(engine.name)

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
            "[bold]capamedia start[/bold] [dim](Fase 1 — fachada no-interactiva)[/dim]\n"
            f"Servicio: [cyan]{service}[/cyan] · Namespace: {namespace} · "
            f"Rama: {branch or '[dim](pendiente integracion)[/dim]'}\n"
            f"Engine: [green]{engine.name}[/green] · Modelo: [magenta]{model}[/magenta] "
            "[dim](siempre Opus)[/dim]\n"
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
        reasoning_effort=None,  # Opus/claude ignora reasoning; se deriva por complejidad en fase futura
        resume=resume,
        scheduler=None,
    )

    status_color = "green" if row.status == "ok" else "red"
    console.print(
        f"\n[bold {status_color}]start {row.status}[/bold {status_color}]: {row.detail}"
    )
    if row.status != "ok":
        raise typer.Exit(1)
