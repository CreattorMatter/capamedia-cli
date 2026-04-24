"""capamedia ai - comandos headless para engines AI.

El CLI deterministico prepara el workspace (clone/init/fabrics/info/review).
Estos comandos ejecutan solo las etapas que necesitan razonamiento de IA:
`migrate` y `doublecheck`.
"""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli.commands.batch import (
    DEFAULT_CODEX_REASONING_EFFORT,
    BatchRow,
    _as_text,
    _ensure_migrate_schema,
    _find_migrated_project,
    _find_project_from_fabrics_metadata,
    _normalize_reasoning_effort,
    _process_migrate_workspace,
    _read_structured_message,
    _run_service_with_retries,
)
from capamedia_cli.commands.clone import normalize_service_name
from capamedia_cli.commands.fabrics import _autodetect_service_name_from_config
from capamedia_cli.core.batch_state import (
    load_state,
    mark_stage,
    save_state,
    set_result,
    stage_ok,
)
from capamedia_cli.core.canonical import CANONICAL_ROOT
from capamedia_cli.core.engine import Engine, EngineInput, engine_from_env, select_engine
from capamedia_cli.core.frontmatter import parse_frontmatter
from capamedia_cli.core.gradle_properties import remove_committed_gradle_java_home
from capamedia_cli.core.self_correction import (
    build_correction_appendix,
    load_failure_context,
)

console = Console()

app = typer.Typer(
    help="Ejecuta etapas AI headless sobre el workspace actual: migrate y doublecheck.",
    no_args_is_help=True,
)

DOUBLECHECK_FIELD_ORDER = [
    "engine",
    "result",
    "verdict",
    "high",
    "medium",
    "low",
    "fixes",
    "seconds",
    "project",
]

DOUBLECHECK_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "status",
        "summary",
        "checklist_verdict",
        "autofixes_applied",
        "high",
        "medium",
        "low",
        "report",
        "next_step",
    ],
    "properties": {
        "status": {
            "type": "string",
            "enum": ["ok", "partial", "blocked", "failed"],
        },
        "summary": {"type": "string"},
        "checklist_verdict": {"type": "string"},
        "autofixes_applied": {"type": "integer"},
        "high": {"type": "integer"},
        "medium": {"type": "integer"},
        "low": {"type": "integer"},
        "report": {"type": "string"},
        "next_step": {"type": "string"},
    },
}


def _resolve_workspace(workspace: Path | None) -> Path:
    return (workspace or Path.cwd()).resolve()


def _resolve_service_name(workspace: Path, service_name: str | None) -> str:
    raw = service_name or _autodetect_service_name_from_config(workspace) or workspace.name
    normalized, was_padded = normalize_service_name(raw)
    if was_padded:
        console.print(f"[yellow]Tip:[/yellow] [cyan]{raw}[/cyan] -> [cyan]{normalized}[/cyan]")
    return normalized


def _select_engine_or_exit(
    engine_name: str,
    *,
    claude_bin: str,
    codex_bin: str,
) -> Engine:
    env_pref = engine_from_env()
    effective_engine = env_pref or engine_name
    try:
        return select_engine(effective_engine, claude_bin=claude_bin, codex_bin=codex_bin)
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None


def _validate_prompt_file(prompt_file: Path | None) -> Path | None:
    if prompt_file is None:
        return None
    resolved = prompt_file.resolve()
    if not resolved.exists():
        raise typer.BadParameter(f"prompt no existe: {resolved}")
    return resolved


def _project_for_workspace(workspace: Path, service: str) -> Path | None:
    return _find_project_from_fabrics_metadata(workspace) or _find_migrated_project(workspace, service)


def _render_result(command: str, row: BatchRow, field_order: list[str]) -> None:
    table = Table(title=f"CapaMedia AI {command}", title_style="bold cyan")
    table.add_column("Servicio", style="cyan")
    table.add_column("Status", style="bold")
    for field in field_order:
        table.add_column(field)
    table.add_column("Detail")
    status = "[green]OK[/green]" if row.status == "ok" else "[red]FAIL[/red]"
    table.add_row(
        row.service,
        status,
        *(row.fields.get(field, "") for field in field_order),
        row.detail[:80],
    )
    console.print(table)


def _ensure_doublecheck_schema(workspace: Path) -> Path:
    runtime_dir = workspace / ".capamedia" / "ai"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    schema_path = runtime_dir / "doublecheck.schema.json"
    schema_json = json.dumps(DOUBLECHECK_OUTPUT_SCHEMA, ensure_ascii=True, indent=2) + "\n"
    if not schema_path.exists() or schema_path.read_text(encoding="utf-8") != schema_json:
        schema_path.write_text(schema_json, encoding="utf-8")
    return schema_path


def _read_prompt_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    try:
        _, body = parse_frontmatter(text)
        return body.strip()
    except Exception:
        return text


def _load_doublecheck_prompt(workspace: Path, prompt_file: Path | None = None) -> str:
    candidates = [
        prompt_file,
        workspace / ".codex" / "prompts" / "doublecheck.md",
        workspace / ".claude" / "commands" / "doublecheck.md",
        workspace / ".github" / "prompts" / "doublecheck.prompt.md",
        workspace / ".cursor" / "rules" / "doublecheck.mdc",
        workspace / ".windsurf" / "rules" / "doublecheck.md",
        workspace / ".opencode" / "commands" / "doublecheck.md",
        CANONICAL_ROOT / "prompts" / "doublecheck.md",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return _read_prompt_body(candidate)
    return (
        "# doublecheck\n\n"
        "Ejecuta `capamedia checklist` desde el workspace root, aplica solo los "
        "autofixes seguros que el checklist habilite, re-ejecuta el checklist y "
        "devuelve el resumen final."
    )


def _build_doublecheck_prompt(
    service: str,
    workspace: Path,
    migrated_project: Path,
    prompt_body: str,
) -> str:
    return (
        "# CapaMedia AI doublecheck\n\n"
        f"Servicio objetivo: {service}\n"
        f"Workspace root: {workspace}\n"
        f"Proyecto migrado: {migrated_project}\n\n"
        "Estas corriendo como engine headless invocado por `capamedia ai doublecheck`.\n"
        "Responsabilidad: cerrar la etapa de doble check despues de la migracion.\n\n"
        "Reglas duras:\n"
        "- Trabaja desde el workspace root, no desde `destino/`.\n"
        "- Ejecuta `capamedia checklist` y respeta sus autofixes/logs.\n"
        "- No ejecutes `capamedia ai migrate`, `capamedia batch migrate`, `/migrate` ni `capamedia review`.\n"
        "- Nunca agregues ni mantengas `org.gradle.java.home` en `gradle.properties`; rompe CI si apunta a un JDK local.\n"
        "- No inventes secretos, URLs de Confluence, Sonar keys ni valores PENDING_FROM_BANK.\n"
        "- Si queda un residual que depende del owner/SRE, reportalo como handoff, no como bug.\n\n"
        "Prompt operativo:\n\n"
        f"{prompt_body.strip()}\n\n"
        "Salida final obligatoria: responde solo JSON, sin markdown ni texto adicional. "
        "Inclui `status`, `summary`, `checklist_verdict`, `autofixes_applied`, "
        "`high`, `medium`, `low`, `report` y `next_step`."
    )


def _positive_int(value: str) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _process_doublecheck_workspace(
    service: str,
    workspace: Path,
    schema_path: Path,
    *,
    engine: Engine,
    model: str | None,
    prompt_file: Path | None,
    timeout_minutes: int,
    unsafe: bool,
    reasoning_effort: str | None = None,
    resume: bool = False,
    stream_output: bool = False,
) -> BatchRow:
    if not workspace.exists():
        return BatchRow(service, "fail", f"workspace no existe: {workspace}", {})

    state = load_state(workspace, "doublecheck", service, reset=not resume)
    state_result = state.get("result", {}) if isinstance(state.get("result"), dict) else {}
    base_fields = {
        "engine": engine.name,
        "result": "pending",
        "verdict": "?",
        "high": "?",
        "medium": "?",
        "low": "?",
        "fixes": "0",
        "seconds": "0.0",
        "project": "?",
    }

    migrated_project = _project_for_workspace(workspace, service)
    if migrated_project is None:
        detail = "no se encontro proyecto migrado en destino/; ejecuta `capamedia fabrics generate` antes"
        fields = dict(base_fields)
        set_result(state, status="fail", detail=detail, fields=fields)
        mark_stage(state, "doublecheck", status="fail", detail=detail, fields=fields)
        save_state(workspace, "doublecheck", state)
        return BatchRow(service, "fail", detail, fields)

    remove_committed_gradle_java_home(migrated_project)

    if resume and state_result.get("status") == "ok" and stage_ok(state, "doublecheck"):
        saved_fields = state_result.get("fields", {})
        fields = {**base_fields, **(saved_fields if isinstance(saved_fields, dict) else {})}
        fields["project"] = migrated_project.name
        return BatchRow(
            service,
            "ok",
            _as_text(state_result.get("detail"), "doublecheck already completed"),
            fields,
        )

    prompt_body = _load_doublecheck_prompt(workspace, prompt_file)
    prompt = _build_doublecheck_prompt(service, workspace, migrated_project, prompt_body)
    failure_ctx = load_failure_context(state)
    if failure_ctx is not None:
        prompt = build_correction_appendix(failure_ctx, prompt)

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = workspace / ".capamedia" / "ai-doublecheck"
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = run_dir / f"{engine.name}-prompt-{ts}.md"
    output_path = run_dir / f"{engine.name}-last-message-{ts}.json"
    stdout_path = run_dir / f"{engine.name}-stdout-{ts}.log"
    stderr_path = run_dir / f"{engine.name}-stderr-{ts}.log"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    started = time.perf_counter()
    einput = EngineInput(
        workspace=workspace,
        prompt=prompt,
        schema_path=schema_path,
        output_path=output_path,
        timeout_seconds=timeout_minutes * 60,
        model=model,
        reasoning_effort=reasoning_effort,
        unsafe=unsafe,
        stream_output=stream_output,
    )
    try:
        eres = engine.run_headless(einput)
    finally:
        remove_committed_gradle_java_home(migrated_project)
    elapsed = eres.duration_seconds or (time.perf_counter() - started)

    stdout_path.write_text(eres.stdout, encoding="utf-8")
    stderr_path.write_text(eres.stderr, encoding="utf-8")

    if eres.failure_reason:
        fields = dict(base_fields)
        fields["seconds"] = f"{elapsed:.1f}"
        fields["project"] = migrated_project.name
        detail = f"engine {engine.name}: {eres.failure_reason}"
        set_result(state, status="fail", detail=detail, fields=fields)
        mark_stage(state, "doublecheck", status="fail", detail=detail, fields=fields)
        save_state(workspace, "doublecheck", state)
        return BatchRow(service, "fail", detail, fields)

    payload = _read_structured_message(output_path)
    result_status = _as_text(payload.get("status"), "ok" if eres.exit_code == 0 else "failed").lower()
    summary = _as_text(payload.get("summary")).strip()
    if not summary:
        summary = eres.stderr.strip() or eres.stdout.strip() or f"{engine.name} termino sin resumen"

    verdict = _as_text(payload.get("checklist_verdict"), _as_text(payload.get("verdict"), "?"))
    high = _as_text(payload.get("high"), "?")
    medium = _as_text(payload.get("medium"), "?")
    low = _as_text(payload.get("low"), "?")
    fixes = _as_text(payload.get("autofixes_applied"), _as_text(payload.get("fixes"), "0"))
    fields = {
        "engine": engine.name,
        "result": result_status,
        "verdict": verdict or "?",
        "high": high,
        "medium": medium,
        "low": low,
        "fixes": fixes,
        "seconds": f"{elapsed:.1f}",
        "project": migrated_project.name,
    }
    if payload.get("report"):
        fields["report"] = _as_text(payload.get("report"))
    if eres.rate_limited:
        fields["rate_limited"] = "yes"

    row_status = "ok"
    if (
        eres.exit_code != 0
        or result_status in {"blocked", "failed"}
        or verdict.startswith("BLOCKED_BY_HIGH")
        or _positive_int(high)
    ):
        row_status = "fail"

    detail = summary.splitlines()[0][:160]
    mark_stage(state, "doublecheck", status=row_status, detail=detail, fields=fields)
    set_result(state, status=row_status, detail=detail, fields=fields)
    save_state(workspace, "doublecheck", state)
    return BatchRow(service, row_status, detail, fields)


@app.command("migrate")
def ai_migrate(
    service_name: Annotated[
        str | None,
        typer.Argument(
            help="Servicio. Si se omite, autodetecta .capamedia/config.yaml o usa el nombre del workspace.",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", "-w", help="Workspace root. Default: CWD"),
    ] = None,
    engine_name: Annotated[
        str,
        typer.Option(
            "--engine",
            help="Engine AI headless: claude | codex | auto (default codex; CAPAMEDIA_ENGINE puede overridear)",
        ),
    ] = "codex",
    claude_bin: Annotated[
        str, typer.Option("--claude-bin", help="Binario de Claude Code CLI")
    ] = "claude",
    codex_bin: Annotated[str, typer.Option("--codex-bin", help="Binario de Codex CLI")] = "codex",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override del modelo del engine seleccionado"),
    ] = None,
    reasoning_effort: Annotated[
        str | None,
        typer.Option(
            "--reasoning-effort",
            help="Override de razonamiento para Codex CLI: low | medium | high | xhigh",
        ),
    ] = DEFAULT_CODEX_REASONING_EFFORT,
    prompt_file: Annotated[
        Path | None,
        typer.Option(
            "--prompt-file",
            help="Prompt base alternativo. Default: <workspace>/.codex/prompts/migrate.md",
        ),
    ] = None,
    timeout_minutes: Annotated[
        int, typer.Option("--timeout-minutes", help="Timeout maximo para migrate")
    ] = 90,
    check: Annotated[
        bool,
        typer.Option(
            "--check/--no-check",
            help="Ejecuta checklist al final. Default: no, porque `ai doublecheck` es la etapa separada.",
        ),
    ] = False,
    resume: Annotated[
        bool, typer.Option("--resume", help="Reanuda si migrate ya termino OK")
    ] = False,
    retries: Annotated[
        int, typer.Option("--retries", help="Reintentos adicionales")
    ] = 0,
    unsafe: Annotated[
        bool,
        typer.Option("--unsafe", help="Usa permisos full para el engine"),
    ] = False,
    stream: Annotated[
        bool,
        typer.Option("--stream/--no-stream", help="Muestra salida live del engine en consola"),
    ] = True,
) -> None:
    """Migra el workspace actual usando un engine AI headless."""
    ws = _resolve_workspace(workspace)
    service = _resolve_service_name(ws, service_name)
    prompt_file = _validate_prompt_file(prompt_file)
    engine = _select_engine_or_exit(engine_name, claude_bin=claude_bin, codex_bin=codex_bin)
    eff_reasoning = _normalize_reasoning_effort(reasoning_effort if engine.name == "codex" else None)
    schema_path = _ensure_migrate_schema(ws)

    console.print(
        Panel.fit(
            f"[bold]CapaMedia AI migrate[/bold]\n"
            f"Servicio: [cyan]{service}[/cyan]\n"
            f"Workspace: [cyan]{ws}[/cyan]\n"
            f"Engine: [green]{engine.name}[/green] ({engine.subscription_type})\n"
            f"Model: {model or '(default)'} | Reasoning: {eff_reasoning or '(engine default)'}\n"
            f"Checklist final: {'SI' if check else 'NO'} | Resume: {'SI' if resume else 'NO'} | Retries: {retries}\n"
            f"Stream: {'SI' if stream else 'NO'}",
            border_style="cyan",
        )
    )

    def runner(_: str, attempt: int) -> BatchRow:
        return _process_migrate_workspace(
            service,
            ws,
            schema_path,
            engine=engine,
            model=model,
            reasoning_effort=eff_reasoning,
            prompt_file=prompt_file,
            timeout_minutes=timeout_minutes,
            run_check=check,
            unsafe=unsafe,
            resume=resume or attempt > 0,
            stream_output=stream,
        )

    row = _run_service_with_retries(
        service,
        runner,
        retries=retries,
        workspace_resolver=lambda _svc: ws,
        project_resolver=lambda svc, wsp: _project_for_workspace(wsp, svc),
        run_kind="migrate",
    )
    _render_result("migrate", row, ["engine", "codex", "result", "framework", "build", "check", "seconds", "project"])
    if row.status != "ok":
        raise typer.Exit(1)


@app.command("doublecheck")
def ai_doublecheck(
    service_name: Annotated[
        str | None,
        typer.Argument(
            help="Servicio. Si se omite, autodetecta .capamedia/config.yaml o usa el nombre del workspace.",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", "-w", help="Workspace root. Default: CWD"),
    ] = None,
    engine_name: Annotated[
        str,
        typer.Option(
            "--engine",
            help="Engine AI headless: claude | codex | auto (default codex; CAPAMEDIA_ENGINE puede overridear)",
        ),
    ] = "codex",
    claude_bin: Annotated[
        str, typer.Option("--claude-bin", help="Binario de Claude Code CLI")
    ] = "claude",
    codex_bin: Annotated[str, typer.Option("--codex-bin", help="Binario de Codex CLI")] = "codex",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override del modelo del engine seleccionado"),
    ] = None,
    reasoning_effort: Annotated[
        str | None,
        typer.Option(
            "--reasoning-effort",
            help="Override de razonamiento para Codex CLI: low | medium | high | xhigh",
        ),
    ] = DEFAULT_CODEX_REASONING_EFFORT,
    prompt_file: Annotated[
        Path | None,
        typer.Option(
            "--prompt-file",
            help="Prompt doublecheck alternativo. Default: assets del workspace o canonical incluido.",
        ),
    ] = None,
    timeout_minutes: Annotated[
        int, typer.Option("--timeout-minutes", help="Timeout maximo para doublecheck")
    ] = 45,
    resume: Annotated[
        bool, typer.Option("--resume", help="Reanuda si doublecheck ya termino OK")
    ] = False,
    retries: Annotated[
        int, typer.Option("--retries", help="Reintentos adicionales")
    ] = 0,
    unsafe: Annotated[
        bool,
        typer.Option("--unsafe", help="Usa permisos full para el engine"),
    ] = False,
    stream: Annotated[
        bool,
        typer.Option("--stream/--no-stream", help="Muestra salida live del engine en consola"),
    ] = True,
) -> None:
    """Ejecuta el doble check AI post-migracion y deja el review para `capamedia review`."""
    ws = _resolve_workspace(workspace)
    service = _resolve_service_name(ws, service_name)
    prompt_file = _validate_prompt_file(prompt_file)
    engine = _select_engine_or_exit(engine_name, claude_bin=claude_bin, codex_bin=codex_bin)
    eff_reasoning = _normalize_reasoning_effort(reasoning_effort if engine.name == "codex" else None)
    schema_path = _ensure_doublecheck_schema(ws)

    console.print(
        Panel.fit(
            f"[bold]CapaMedia AI doublecheck[/bold]\n"
            f"Servicio: [cyan]{service}[/cyan]\n"
            f"Workspace: [cyan]{ws}[/cyan]\n"
            f"Engine: [green]{engine.name}[/green] ({engine.subscription_type})\n"
            f"Model: {model or '(default)'} | Reasoning: {eff_reasoning or '(engine default)'}\n"
            f"Resume: {'SI' if resume else 'NO'} | Retries: {retries}\n"
            f"Stream: {'SI' if stream else 'NO'}",
            border_style="cyan",
        )
    )

    def runner(_: str, attempt: int) -> BatchRow:
        return _process_doublecheck_workspace(
            service,
            ws,
            schema_path,
            engine=engine,
            model=model,
            reasoning_effort=eff_reasoning,
            prompt_file=prompt_file,
            timeout_minutes=timeout_minutes,
            unsafe=unsafe,
            resume=resume or attempt > 0,
            stream_output=stream,
        )

    row = _run_service_with_retries(
        service,
        runner,
        retries=retries,
        workspace_resolver=lambda _svc: ws,
        project_resolver=lambda svc, wsp: _project_for_workspace(wsp, svc),
        run_kind="doublecheck",
    )
    _render_result("doublecheck", row, DOUBLECHECK_FIELD_ORDER)
    if row.status != "ok":
        raise typer.Exit(1)
