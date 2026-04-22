"""capamedia batch - ejecuta comandos sobre N servicios en paralelo.

Subcomandos:
  - complexity <file>   Analiza complejidad de N servicios legacy (leer de txt)
  - clone      <file>   Clone masivo (legacy + UMPs + TX) con ThreadPool
  - check      <root>   Audita todos los proyectos migrados bajo un path
  - init       <file>   Inicializa N workspaces con el scaffold AI del proyecto
  - pipeline   <file>   Ejecuta clone -> init -> fabric -> migrate -> check
  - migrate    <file>   Ejecuta `codex exec` sobre N workspaces listos
  - watch      <root>   Mirador operativo de estados persistentes del batch

Inputs:
  - services.txt: un servicio por linea (ej wsclientes0007). Comentarios con #.
  - --workers N: tamano del pool (default 4)
  - --root <path>: carpeta raiz donde viven los workspaces (default CWD)

Output: tabla consolidada en stdout + archivo `batch-<cmd>-<fecha>.md`.
Opcional: `--xlsx` genera tambien un Excel con la matriz completa.
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import shutil
import subprocess
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from capamedia_cli.core.auth import (
    resolve_artifact_token,
    resolve_azure_devops_pat,
    resolve_codex_api_key,
)
from capamedia_cli.core.batch_state import (
    load_state,
    mark_stage,
    save_state,
    set_result,
    stage_ok,
    state_file,
)

console = Console()

app = typer.Typer(
    help="Procesar N servicios en paralelo (modo batch).",
    no_args_is_help=True,
)


@dataclass
class BatchRow:
    service: str
    status: str  # "ok" | "fail" | "skip" | "wait"
    detail: str
    fields: dict[str, str]


@dataclass
class RunnerExecution:
    provider: str
    returncode: int
    stdout_text: str
    stderr_text: str
    payload: dict[str, Any]
    session_id: str | None = None
    summary_fallback: str = ""


MIGRATE_FIELD_ORDER = ["codex", "result", "framework", "build", "check", "seconds", "project"]
PIPELINE_FIELD_ORDER = [
    "clone",
    "init",
    "fabric",
    "codex",
    "result",
    "build",
    "check",
    "seconds",
    "project",
]
WATCH_FIELD_ORDER = [
    "kind",
    "phase",
    "clone",
    "init",
    "fabric",
    "codex",
    "result",
    "build",
    "check",
    "attempts",
    "updated",
    "project",
]

DEFAULT_CODEX_MODEL = "gpt-5.4"
DEFAULT_CODEX_REASONING_EFFORT = "high"
DEFAULT_CLAUDE_MODEL = "opus"
DEFAULT_CLAUDE_EFFORT = "high"

MIGRATE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "status",
        "summary",
        "framework",
        "build_status",
        "migrated_project",
        "artifacts",
        "notes",
    ],
    "properties": {
        "status": {
            "type": "string",
            "enum": ["ok", "partial", "blocked", "failed"],
        },
        "summary": {"type": "string"},
        "framework": {"type": "string"},
        "build_status": {"type": "string"},
        "migrated_project": {"type": "string"},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}

FALLBACK_MIGRATE_PROMPT = textwrap.dedent(
    """
    Completa la migracion del servicio legacy a Java 21 + Spring Boot hexagonal siguiendo
    las instrucciones del workspace. Lee primero AGENTS.md y cualquier prompt local del
    proyecto, despues implementa los cambios minimos necesarios dentro de `destino/`.

    Requisitos:
    - trabaja solo dentro del workspace actual;
    - preserva la matriz oficial del proyecto (1 op -> REST/WebFlux, 2+ ops -> SOAP/MVC);
    - intenta validar con un build real del proyecto migrado si existe;
    - si el sandbox no tiene Java/JDK/Gradle o no permite correr el build real, eso NO bloquea
      las ediciones: igual debes completar la migracion y reportar ese limite en `build_status`;
    - usa `status=blocked` solo cuando falten insumos esenciales o no puedas completar la
      migracion de codigo de forma confiable;
    - no uses sub-agentes ni esperes interaccion del usuario; resuelve todo dentro de esta misma
      ejecucion;
    - si hay una ambiguedad menor, toma la mejor decision con la evidencia del workspace y
      documentala en `notes` en lugar de preguntar;
    - no te detengas antes de editar solo porque el build no corre dentro del sandbox.
    - devuelve SIEMPRE todos los campos del schema; usa string vacio ("") o lista vacia ([])
      cuando un dato no aplique o no este disponible.

    Tu respuesta final debe ser SOLO un JSON valido segun el schema provisto.
    """
).strip()

KNOWN_CODEX_BIN_PATHS = (
    "/Applications/Codex.app/Contents/Resources/codex",
    "/opt/homebrew/bin/codex",
    "/usr/local/bin/codex",
)

KNOWN_CLAUDE_BIN_PATHS = (
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
)


def _ensure_workspace_git_repo(workspace: Path) -> None:
    """Initialize a lightweight git repo so Codex can attach normal repo context."""
    if (workspace / ".git").exists():
        return

    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if probe.returncode == 0:
        return

    init = subprocess.run(
        ["git", "init", "-q"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if init.returncode != 0:
        detail = (init.stderr or init.stdout or "git init fallo").strip()
        raise RuntimeError(detail.splitlines()[-1] if detail else "git init fallo")


def _resolve_cli_bin(bin_name: str, known_paths: tuple[str, ...]) -> str:
    resolved = shutil.which(bin_name)
    if resolved:
        return resolved

    candidate = Path(bin_name).expanduser()
    if candidate.exists():
        return str(candidate)

    for raw in known_paths:
        known = Path(raw)
        if known.exists():
            return str(known)

    return bin_name


def _resolve_codex_bin(codex_bin: str) -> str:
    return _resolve_cli_bin(codex_bin, KNOWN_CODEX_BIN_PATHS)


def _resolve_claude_bin(claude_bin: str) -> str:
    return _resolve_cli_bin(claude_bin, KNOWN_CLAUDE_BIN_PATHS)


def _build_codex_exec_env() -> dict[str, str]:
    env = os.environ.copy()
    api_key = resolve_codex_api_key()
    if api_key and not env.get("CODEX_API_KEY"):
        env["CODEX_API_KEY"] = api_key
    return env


def _build_claude_exec_env() -> dict[str, str]:
    return os.environ.copy()


def _resolve_java21_home() -> str | None:
    try:
        from capamedia_cli.commands.fabrics import _find_java21_home
    except Exception:
        return None
    return _find_java21_home()


def _needs_host_build_fallback(summary: str, build_detail: str) -> bool:
    haystack = f"{summary}\n{build_detail}".lower()
    blockers = (
        "unable to locate a java runtime",
        "no java runtime",
        "no hay un java runtime",
        "no hay jdk",
        "no jdk available",
        "missing a required build prerequisite: no java runtime is available",
        "falta un runtime de java",
        "falta un prerequisito operativo critico: no hay jdk",
    )
    return any(token in haystack for token in blockers)


def _reported_no_edits(summary: str, notes: list[str]) -> bool:
    haystack = "\n".join([summary, *notes]).lower()
    markers = (
        "no realicé ediciones",
        "no realice ediciones",
        "no hice ediciones",
        "no edite archivos",
        "no edité archivos",
        "before any file edits",
        "before edits",
        "before file edits",
        "migration blocked before edits",
        "migracion no iniciada",
        "migración no iniciada",
        "detuve el proceso antes de editar",
        "prerequisite failure detected before any file edits",
    )
    return any(marker in haystack for marker in markers)


def _run_host_build_fallback(migrated_project: Path, *, ts: str) -> tuple[str, str]:
    java_home = _resolve_java21_home()
    if not java_home:
        return ("blocked", "blocked: no se encontro Java 21 local para ejecutar el build host-side")

    gradle_cmd = ["./gradlew", "clean", "build", "jacocoTestReport", "--no-daemon"]
    if not (migrated_project / "gradlew").exists():
        gradle_cmd = ["gradle", "clean", "build", "jacocoTestReport", "--no-daemon"]

    env = os.environ.copy()
    env["JAVA_HOME"] = java_home
    env["PATH"] = f"{java_home}/bin:{env.get('PATH', '')}"
    env["GRADLE_USER_HOME"] = str(migrated_project / ".gradle-user-home-host")

    artifact_token = resolve_artifact_token() or resolve_azure_devops_pat()
    if artifact_token and not env.get("ARTIFACT_TOKEN"):
        env["ARTIFACT_TOKEN"] = artifact_token
    env.setdefault("ARTIFACT_USERNAME", "BancoPichinchaEC")

    workspace = migrated_project.parent.parent if migrated_project.parent.name == "destino" else migrated_project.parent
    run_dir = workspace / ".capamedia" / "batch-migrate"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / f"host-build-{ts}.log"

    try:
        result = subprocess.run(
            gradle_cmd,
            cwd=migrated_project,
            capture_output=True,
            text=True,
            check=False,
            timeout=20 * 60,
            env=env,
        )
    except FileNotFoundError:
        return ("blocked", f"blocked: no se encontro `{gradle_cmd[0]}` para validar el build host-side")
    except subprocess.TimeoutExpired:
        return ("blocked", "blocked: el build host-side excedio 20 minutos")

    combined = "\n".join(
        chunk for chunk in (result.stdout or "", result.stderr or "") if chunk
    ).strip()
    if combined:
        log_path.write_text(combined + "\n", encoding="utf-8")
    log_hint = f" Log: `{log_path}`." if log_path.exists() else ""

    if result.returncode == 0:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        command = " ".join(gradle_cmd)
        return (
            "green",
            (
                f"green: build real host-side ejecutado con exito el {stamp} en "
                f"`{migrated_project}` usando `{command}`.{log_hint}"
            ),
        )

    tail = (result.stderr or result.stdout or "build host-side fallo").strip().splitlines()
    last_line = tail[-1].strip() if tail else "build host-side fallo"
    return (
        "red",
        f"red: build host-side fallo con `{gradle_cmd[0]}`: {last_line[:220]}.{log_hint}",
    )


def _iter_codex_jsonl(stdout_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw_line in stdout_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _extract_codex_session_id(stdout_text: str) -> str | None:
    for payload in _iter_codex_jsonl(stdout_text):
        session_id = payload.get("session_id") or payload.get("thread_id")
        if isinstance(session_id, str) and session_id.strip():
            return session_id.strip()
        item = payload.get("item")
        if isinstance(item, dict):
            nested = item.get("session_id") or item.get("thread_id")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def _extract_codex_agent_message(stdout_text: str) -> str:
    last_message = ""
    for payload in _iter_codex_jsonl(stdout_text):
        item = payload.get("item")
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                last_message = text.strip()
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            last_message = text.strip()
    return last_message


def _extract_claude_execution(stdout_text: str) -> tuple[dict[str, Any], str | None, str]:
    raw = stdout_text.strip()
    if not raw:
        return ({}, None, "")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ({}, None, "")

    items: list[dict[str, Any]]
    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = [item for item in data if isinstance(item, dict)]
    else:
        items = []

    payload: dict[str, Any] = {}
    session_id: str | None = None
    summary = ""
    for item in items:
        if session_id is None:
            candidate = item.get("session_id") or item.get("sessionId")
            if isinstance(candidate, str) and candidate.strip():
                session_id = candidate.strip()
        structured = item.get("structured_output")
        if isinstance(structured, dict):
            payload = structured
        elif not payload and isinstance(item.get("result"), dict):
            payload = item["result"]
        if not summary:
            text = item.get("result")
            if isinstance(text, str) and text.strip():
                summary = text.strip()
        if not summary:
            message = item.get("message")
            if isinstance(message, str) and message.strip():
                summary = message.strip()
    return (payload, session_id, summary)


def _read_services_file(path: Path, sheet: str | None = None) -> list[str]:
    """Lee servicios desde txt, csv o xlsx.

    - .txt: una linea por servicio. Comentarios con #.
    - .csv: primera columna es el servicio. Header opcional ("servicio" en row 1).
    - .xlsx: hoja `sheet` (default primera). Primera columna = servicio.
      Si la primera celda es literal "servicio", se asume header.
    """
    if not path.exists():
        raise typer.BadParameter(f"no existe: {path}")

    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return _read_xlsx_services(path, sheet)
    if suffix == ".csv":
        return _read_csv_services(path)

    # Default: .txt
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(name)
    return names


def _read_csv_services(path: Path) -> list[str]:
    names: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if not row or not row[0].strip():
                continue
            cell = row[0].strip()
            if i == 0 and cell.lower() in ("servicio", "service", "name", "nombre"):
                continue  # header
            if cell.startswith("#"):
                continue
            names.append(cell)
    return names


def _read_xlsx_services(path: Path, sheet: str | None) -> list[str]:
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise typer.BadParameter(
            "openpyxl no disponible. Instalar con: pip install openpyxl"
        ) from e

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
    names: list[str] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if not row or row[0] is None:
            continue
        cell = str(row[0]).strip()
        if not cell:
            continue
        if i == 0 and cell.lower() in ("servicio", "service", "name", "nombre"):
            continue  # header
        if cell.startswith("#"):
            continue
        names.append(cell)
    return names


def _write_markdown_report(
    cmd: str, rows: list[BatchRow], workspace: Path, field_order: list[str] | None = None
) -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = workspace / f"batch-{cmd}-{ts}.md"
    lines: list[str] = []
    lines.append(f"# Batch `{cmd}` report\n")
    lines.append(f"Generado: `{datetime.datetime.now().isoformat()}`  \n")
    lines.append(f"Servicios procesados: **{len(rows)}**\n")

    ok = sum(1 for r in rows if r.status == "ok")
    fail = sum(1 for r in rows if r.status == "fail")
    skip = sum(1 for r in rows if r.status == "skip")
    wait = sum(1 for r in rows if r.status == "wait")
    lines.append(f"**OK:** {ok} · **FAIL:** {fail} · **WAIT:** {wait} · **SKIP:** {skip}\n")

    if rows:
        cols = field_order or sorted({k for r in rows for k in r.fields})
        header = ["service", "status", "detail", *cols]
        lines.append("")
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for r in rows:
            row = [r.service, r.status, r.detail[:80]]
            row += [r.fields.get(c, "") for c in cols]
            lines.append("| " + " | ".join(row) + " |")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def _write_csv_report(
    cmd: str, rows: list[BatchRow], workspace: Path, field_order: list[str] | None = None
) -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = workspace / f"batch-{cmd}-{ts}.csv"
    cols = field_order or sorted({k for r in rows for k in r.fields})
    with dest.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["service", "status", "detail", *cols])
        for r in rows:
            w.writerow([r.service, r.status, r.detail, *(r.fields.get(c, "") for c in cols)])
    return dest


def _render_table(cmd: str, rows: list[BatchRow], field_order: list[str] | None = None) -> None:
    cols = field_order or sorted({k for r in rows for k in r.fields})
    table = Table(title=f"Batch {cmd}: {len(rows)} servicios", title_style="bold cyan")
    table.add_column("Servicio", style="cyan")
    table.add_column("Status", style="bold", width=6)
    for c in cols:
        table.add_column(c)
    table.add_column("Detail")
    for r in rows:
        if r.status == "ok":
            status = "[green]OK[/green]"
        elif r.status == "wait":
            status = "[cyan]WAIT[/cyan]"
        elif r.status == "skip":
            status = "[yellow]SKIP[/yellow]"
        else:
            status = "[red]FAIL[/red]"
        vals = [r.fields.get(c, "") for c in cols]
        table.add_row(r.service, status, *vals, r.detail[:50])
    console.print(table)


# -- Helpers compartidos ----------------------------------------------------


def _ensure_batch_runtime_dir(root: Path) -> Path:
    runtime_dir = root / ".capamedia" / "batch"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def _ensure_migrate_schema(root: Path) -> Path:
    runtime_dir = _ensure_batch_runtime_dir(root)
    schema_path = runtime_dir / "codex-batch-migrate.schema.json"
    schema_json = json.dumps(MIGRATE_OUTPUT_SCHEMA, ensure_ascii=True, indent=2) + "\n"
    if not schema_path.exists() or schema_path.read_text(encoding="utf-8") != schema_json:
        schema_path.write_text(schema_json, encoding="utf-8")
    return schema_path


def _has_gradle_build(path: Path) -> bool:
    return (path / "build.gradle").exists() or (path / "build.gradle.kts").exists()


def _find_migrated_project(workspace: Path, service: str) -> Path | None:
    destino = workspace / "destino"
    if not destino.exists():
        return None

    expected_names = (
        f"tnd-msa-sp-{service.lower()}",
        service.lower(),
        service,
    )
    for name in expected_names:
        candidate = destino / name
        if candidate.is_dir() and _has_gradle_build(candidate):
            return candidate

    candidates = sorted(p for p in destino.iterdir() if p.is_dir() and _has_gradle_build(p))
    if not candidates:
        return None

    preferred = [p for p in candidates if service.lower() in p.name.lower()]
    if preferred:
        return preferred[0]
    return candidates[0]


def _find_legacy_root(workspace: Path, service: str | None = None) -> Path | None:
    for candidate in (workspace / "legacy", workspace.parent / "legacy"):
        if candidate.exists() and candidate.is_dir():
            return candidate
    if service:
        from capamedia_cli.core.local_resolver import find_local_legacy

        return find_local_legacy(service, workspace.parent)
    return None


def _has_complexity_report(workspace: Path, service: str) -> bool:
    return (workspace / f"COMPLEXITY_{service}.md").exists()


def _has_init_material(workspace: Path) -> bool:
    return (workspace / ".capamedia" / "config.yaml").exists()


def _load_fabrics_metadata(workspace: Path) -> dict[str, Any] | None:
    from capamedia_cli.commands.fabrics import load_fabrics_metadata

    data = load_fabrics_metadata(workspace)
    return data if isinstance(data, dict) else None


def _has_fabrics_material(workspace: Path) -> bool:
    data = _load_fabrics_metadata(workspace)
    if not data:
        return False
    project_path = _as_text(data.get("project_path"))
    project_name = _as_text(data.get("project_name"))
    return bool(project_path or project_name)


def _find_project_from_fabrics_metadata(workspace: Path) -> Path | None:
    data = _load_fabrics_metadata(workspace)
    if not data:
        return None
    project_path = _as_text(data.get("project_path")).strip()
    if project_path:
        candidate = Path(project_path)
        if candidate.is_dir() and _has_gradle_build(candidate):
            return candidate
    project_name = _as_text(data.get("project_name")).strip()
    if project_name:
        candidate = workspace / "destino" / project_name
        if candidate.is_dir() and _has_gradle_build(candidate):
            return candidate
    return None


def _format_ts(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    return value.replace("T", " ")[:19]


def _read_state_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _watch_stage_value(state: dict[str, Any], stage: str, field_key: str, default: str = "") -> str:
    stage_data = state.get("stages", {}).get(stage, {})
    if not isinstance(stage_data, dict):
        return default
    fields = stage_data.get("fields", {})
    if isinstance(fields, dict) and fields.get(field_key) is not None:
        return _as_text(fields.get(field_key))
    return _as_text(stage_data.get("status"), default)


def _watch_phase(run_kind: str, state: dict[str, Any]) -> str:
    order = ["clone", "init", "fabric", "migrate", "check"] if run_kind == "pipeline" else ["migrate", "check"]
    stages = state.get("stages", {})
    for stage in order:
        stage_data = stages.get(stage, {})
        if not isinstance(stage_data, dict):
            return stage
        status = _as_text(stage_data.get("status")).strip().lower()
        if status == "fail":
            return f"{stage}:fail"
        if not status:
            return stage
        if status != "ok":
            return f"{stage}:{status}"
    result_status = _as_text(state.get("result", {}).get("status")).strip().lower()
    if result_status == "ok":
        return "done"
    return result_status or "pending"


def _watch_row_for_service(workspace: Path, service: str, run_kind: str) -> BatchRow:
    state = _read_state_snapshot(state_file(workspace, run_kind))
    fabrics = _load_fabrics_metadata(workspace) or {}
    project_hint = _as_text(fabrics.get("project_name")) or _as_text(
        state.get("result", {}).get("fields", {}).get("project") if state else ""
    )

    if state is None:
        return BatchRow(
            service,
            "wait",
            _as_text(fabrics.get("detail"), "sin estado batch"),
            {
                "kind": run_kind,
                "phase": "no_state",
                "clone": "",
                "init": "",
                "fabric": _as_text(fabrics.get("status"), "-"),
                "codex": "",
                "result": "",
                "build": "",
                "check": "",
                "attempts": "0",
                "updated": "",
                "project": project_hint,
            },
        )

    result = state.get("result", {}) if isinstance(state.get("result"), dict) else {}
    attempts = 0
    for stage_data in state.get("stages", {}).values():
        if isinstance(stage_data, dict):
            attempts += int(stage_data.get("attempts", 0) or 0)

    fields = {
        "kind": run_kind,
        "phase": _watch_phase(run_kind, state),
        "clone": _watch_stage_value(state, "clone", "clone"),
        "init": _watch_stage_value(state, "init", "init"),
        "fabric": _watch_stage_value(state, "fabric", "fabric", _as_text(fabrics.get("status"), "")),
        "codex": _watch_stage_value(state, "migrate", "codex"),
        "result": _as_text(result.get("fields", {}).get("result")) if isinstance(result.get("fields"), dict) else _as_text(result.get("status")),
        "build": _watch_stage_value(state, "migrate", "build"),
        "check": _watch_stage_value(state, "check", "check"),
        "attempts": str(attempts),
        "updated": _format_ts(_as_text(state.get("updated_at"))),
        "project": _as_text(
            (result.get("fields", {}) if isinstance(result.get("fields"), dict) else {}).get("project"),
            project_hint,
        ),
    }

    failed_stage_detail = ""
    for stage_name in ("clone", "init", "fabric", "migrate", "check"):
        stage_data = state.get("stages", {}).get(stage_name, {})
        if isinstance(stage_data, dict) and _as_text(stage_data.get("status")).lower() == "fail":
            failed_stage_detail = _as_text(stage_data.get("detail"))
            break

    result_status = _as_text(result.get("status")).lower()
    if result_status == "ok":
        status = "ok"
    elif failed_stage_detail:
        status = "fail"
    else:
        status = "wait"

    detail = _as_text(result.get("detail")) or failed_stage_detail or _as_text(fabrics.get("detail"), "en progreso")
    return BatchRow(service, status, detail, fields)


def _collect_watch_rows(root: Path, services: list[str], kind: str) -> list[BatchRow]:
    rows: list[BatchRow] = []
    for service in services:
        workspace = root / service
        if kind == "pipeline":
            rows.append(_watch_row_for_service(workspace, service, "pipeline"))
            continue
        if kind == "migrate":
            rows.append(_watch_row_for_service(workspace, service, "migrate"))
            continue
        pipeline_state = state_file(workspace, "pipeline")
        migrate_state = state_file(workspace, "migrate")
        if pipeline_state.exists():
            rows.append(_watch_row_for_service(workspace, service, "pipeline"))
        elif migrate_state.exists():
            rows.append(_watch_row_for_service(workspace, service, "migrate"))
        else:
            rows.append(_watch_row_for_service(workspace, service, "pipeline"))
    rows.sort(key=lambda r: r.service)
    return rows


def _hydrate_fields(base: dict[str, str], saved: dict[str, Any] | None) -> dict[str, str]:
    fields = dict(base)
    if not isinstance(saved, dict):
        return fields
    for key, value in saved.items():
        fields[str(key)] = _as_text(value)
    return fields


def _load_migrate_prompt(workspace: Path, prompt_file: Path | None = None) -> str:
    candidate = prompt_file or (workspace / ".codex" / "prompts" / "migrate.md")
    if candidate.exists():
        return candidate.read_text(encoding="utf-8").strip()
    return FALLBACK_MIGRATE_PROMPT


def _build_batch_migrate_prompt(
    service: str,
    workspace: Path,
    migrated_project: Path,
    prompt_body: str,
) -> str:
    legacy_root = _find_legacy_root(workspace, service)
    legacy_hint = str(legacy_root) if legacy_root else "(no encontrado)"
    return textwrap.dedent(
        f"""
        Servicio objetivo: {service}
        Workspace root: {workspace}
        Legacy root: {legacy_hint}
        Proyecto migrado esperado: {migrated_project}

        Ejecuta la migracion de forma no interactiva en este workspace ya preparado.
        Antes de editar:
        1. Lee `AGENTS.md` si existe.
        2. Usa el prompt base incluido abajo como fuente principal del workflow.
        3. Estas reglas de batch tienen prioridad sobre el prompt base si hay conflicto.

        Requisitos operativos:
        - Trabaja solo dentro de este workspace.
        - Intenta correr al menos un build real del proyecto migrado si el proyecto existe.
        - Si el sandbox no tiene Java/JDK/Gradle o no permite correr Gradle, eso NO es un
          prerequisito bloqueante para editar el codigo.
        - En ese caso igual completa la migracion y devuelve `build_status` explicando el
          bloqueo del sandbox para que el host valide despues.
        - Usa `status=blocked` solo cuando falten insumos esenciales o no puedas completar la
          migracion del codigo de forma confiable.
        - No uses sub-agentes ni esperes interaccion del usuario; resuelve la migracion dentro
          de esta misma ejecucion no interactiva.
        - Si el prompt base pide preguntar al usuario o escalar por una ambiguedad menor, toma
          la mejor decision con la evidencia del workspace y documentala en `notes`.
        - No incluyas Markdown ni explicaciones fuera del JSON final.
        - La respuesta final debe ser SOLO el objeto JSON pedido por el schema.

        Prompt base del proyecto:
        ---
        {prompt_body}
        ---
        """
    ).strip()


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    if not raw.startswith("```"):
        return raw
    lines = raw.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return raw


def _read_structured_message(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    raw = _strip_code_fence(path.read_text(encoding="utf-8").strip())
    if not raw:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}

    return data if isinstance(data, dict) else {}


def _run_codex_migrate_execution(
    *,
    codex_bin: str,
    model: str | None,
    workspace: Path,
    schema_path: Path,
    output_path: Path,
    prompt: str,
    timeout_minutes: int,
    unsafe: bool,
) -> RunnerExecution:
    resolved_model = model or DEFAULT_CODEX_MODEL
    resolved_codex_bin = _resolve_codex_bin(codex_bin)
    cmd = [
        resolved_codex_bin,
        "exec",
        "--cd",
        str(workspace),
        "--ignore-user-config",
        "--ephemeral",
        "--model",
        resolved_model,
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        "--json",
        "--color",
        "never",
        "--config",
        f'model_reasoning_effort="{DEFAULT_CODEX_REASONING_EFFORT}"',
    ]
    if unsafe:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd.append("--full-auto")
    cmd.append("-")

    result = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_minutes * 60,
        env=_build_codex_exec_env(),
    )
    stdout_text = result.stdout or ""
    payload = _read_structured_message(output_path)
    return RunnerExecution(
        provider="codex",
        returncode=result.returncode,
        stdout_text=stdout_text,
        stderr_text=result.stderr or "",
        payload=payload,
        session_id=_extract_codex_session_id(stdout_text),
        summary_fallback=_extract_codex_agent_message(stdout_text),
    )


def _run_claude_migrate_execution(
    *,
    claude_bin: str,
    model: str | None,
    workspace: Path,
    schema_path: Path,
    output_path: Path,
    prompt: str,
    timeout_minutes: int,
    unsafe: bool,
) -> RunnerExecution:
    resolved_model = model or DEFAULT_CLAUDE_MODEL
    resolved_claude_bin = _resolve_claude_bin(claude_bin)
    schema_text = schema_path.read_text(encoding="utf-8")
    query = (
        "Lee la instruccion completa desde stdin, ejecutala dentro del workspace actual y "
        "devuelve solo la salida estructurada requerida por el schema."
    )
    cmd = [
        resolved_claude_bin,
        "-p",
        query,
        "--output-format",
        "json",
        "--json-schema",
        schema_text,
        "--cwd",
        str(workspace),
        "--max-turns",
        "40",
        "--model",
        resolved_model,
        "--effort",
        DEFAULT_CLAUDE_EFFORT,
    ]
    if unsafe:
        cmd.append("--dangerously-skip-permissions")
    else:
        cmd.extend(["--permission-mode", "bypassPermissions"])

    result = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_minutes * 60,
        env=_build_claude_exec_env(),
    )
    stdout_text = result.stdout or ""
    payload, session_id, summary_fallback = _extract_claude_execution(stdout_text)
    if payload:
        output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return RunnerExecution(
        provider="claude",
        returncode=result.returncode,
        stdout_text=stdout_text,
        stderr_text=result.stderr or "",
        payload=payload,
        session_id=session_id,
        summary_fallback=summary_fallback,
    )


def _run_migrate_execution(
    *,
    provider: str,
    runner_bin: str,
    model: str | None,
    workspace: Path,
    schema_path: Path,
    output_path: Path,
    prompt: str,
    timeout_minutes: int,
    unsafe: bool,
) -> RunnerExecution:
    if provider == "claude":
        return _run_claude_migrate_execution(
            claude_bin=runner_bin,
            model=model,
            workspace=workspace,
            schema_path=schema_path,
            output_path=output_path,
            prompt=prompt,
            timeout_minutes=timeout_minutes,
            unsafe=unsafe,
        )
    return _run_codex_migrate_execution(
        codex_bin=runner_bin,
        model=model,
        workspace=workspace,
        schema_path=schema_path,
        output_path=output_path,
        prompt=prompt,
        timeout_minutes=timeout_minutes,
        unsafe=unsafe,
    )


def _as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_build_status(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"green", "ok", "passed", "pass", "success", "successful"}:
        return "green"
    if lowered.startswith(("green:", "ok:", "passed:", "pass:", "success:", "successful:")):
        return "green"
    if lowered in {"red", "fail", "failed", "error"}:
        return "red"
    if lowered.startswith(("red:", "fail:", "failed:", "error:")):
        return "red"
    if lowered in {"", "unknown", "not_run", "not run"}:
        return "unknown"
    if lowered.startswith(("unknown:", "not_run:", "not run:")):
        return "unknown"
    return value.strip() or "unknown"


def _run_batch_check(service: str, migrated_project: Path, legacy_root: Path | None) -> dict[str, str]:
    from capamedia_cli.commands.check import _write_report
    from capamedia_cli.core.checklist_rules import CheckContext, run_all_blocks

    ctx = CheckContext(migrated_path=migrated_project, legacy_path=legacy_root)
    results = run_all_blocks(ctx)
    report_path = _write_report(service, results, migrated_project, legacy_root)

    high = sum(1 for r in results if r.status == "fail" and r.severity == "high")
    medium = sum(1 for r in results if r.status == "fail" and r.severity == "medium")
    low = sum(1 for r in results if r.status == "fail" and r.severity == "low")

    if high > 0:
        verdict = "BLOCKED_BY_HIGH"
    elif medium > 0:
        verdict = "READY_WITH_FOLLOW_UP"
    else:
        verdict = "READY_TO_MERGE"

    return {
        "verdict": verdict,
        "HIGH": str(high),
        "MEDIUM": str(medium),
        "LOW": str(low),
        "report": str(report_path),
    }


def _process_migrate_service(
    service: str,
    root: Path,
    schema_path: Path,
    *,
    provider: str = "codex",
    runner_bin: str | None = None,
    codex_bin: str | None = None,
    model: str | None,
    prompt_file: Path | None,
    timeout_minutes: int,
    run_check: bool,
    unsafe: bool,
    resume: bool = False,
) -> BatchRow:
    if runner_bin is None:
        runner_bin = codex_bin or provider

    workspace = root / service
    if not workspace.exists():
        return BatchRow(service, "fail", f"workspace no existe: {workspace}", {})

    state = load_state(workspace, "migrate", service, reset=not resume)
    state_result = state.get("result", {}) if isinstance(state.get("result"), dict) else {}
    base_fields = {
        "codex": "pending",
        "result": "pending",
        "framework": "?",
        "build": "unknown",
        "check": "not_run" if run_check else "skip",
        "seconds": "0.0",
        "project": "?",
    }

    fabrics_meta = _load_fabrics_metadata(workspace)
    if not fabrics_meta:
        fields = _hydrate_fields(base_fields, state_result.get("fields"))
        detail = (
            "no hay evidencia de Fabrics en .capamedia/fabrics.json "
            "(corre `capamedia fabrics generate` o `batch pipeline` antes de migrate)"
        )
        set_result(state, status="fail", detail=detail, fields=fields)
        mark_stage(state, "migrate", status="fail", detail=detail, fields=fields)
        save_state(workspace, "migrate", state)
        return BatchRow(service, "fail", detail, fields)

    migrated_project = _find_project_from_fabrics_metadata(workspace) or _find_migrated_project(workspace, service)
    if migrated_project is None:
        fields = _hydrate_fields(base_fields, state_result.get("fields"))
        detail = "no se encontro proyecto migrado en destino/ pese a tener metadata de Fabrics"
        set_result(state, status="fail", detail=detail, fields=fields)
        mark_stage(state, "migrate", status="fail", detail=detail, fields=fields)
        save_state(workspace, "migrate", state)
        return BatchRow(
            service,
            "fail",
            detail,
            fields,
        )

    if resume and state_result.get("status") == "ok" and stage_ok(state, "migrate"):
        check_is_done = (not run_check) or stage_ok(state, "check")
        if check_is_done:
            fields = _hydrate_fields(base_fields, state_result.get("fields"))
            fields["project"] = migrated_project.name
            return BatchRow(
                service,
                "ok",
                _as_text(state_result.get("detail"), "already completed (resume)") or "already completed (resume)",
                fields,
            )

    prompt_body = _load_migrate_prompt(workspace, prompt_file)
    prompt = _build_batch_migrate_prompt(service, workspace, migrated_project, prompt_body)

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = workspace / ".capamedia" / "batch-migrate"
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = run_dir / f"codex-prompt-{ts}.md"
    output_path = run_dir / f"codex-last-message-{ts}.json"
    stdout_path = run_dir / f"codex-stdout-{ts}.log"
    stderr_path = run_dir / f"codex-stderr-{ts}.log"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    try:
        _ensure_workspace_git_repo(workspace)
    except RuntimeError as exc:
        fields = _hydrate_fields(base_fields, state_result.get("fields"))
        fields["project"] = migrated_project.name
        detail = f"no se pudo preparar git en workspace: {exc}"
        set_result(state, status="fail", detail=detail, fields=fields)
        mark_stage(state, "migrate", status="fail", detail=detail, fields=fields)
        save_state(workspace, "migrate", state)
        return BatchRow(service, "fail", detail, fields)

    started = time.perf_counter()
    skip_migrate = resume and stage_ok(state, "migrate")
    project_name = migrated_project.name
    result_status = "ok"
    build_status = "unknown"
    summary = ""
    elapsed = 0.0
    if skip_migrate:
        saved_fields = {}
        stage_data = state.get("stages", {}).get("migrate", {})
        if isinstance(stage_data, dict):
            saved_fields = stage_data.get("fields", {})
            summary = _as_text(stage_data.get("detail"), "migrate already completed")
        project_name = _as_text(saved_fields.get("project"), migrated_project.name) or migrated_project.name
        result_status = _as_text(saved_fields.get("result"), "ok").lower()
        build_status = _normalize_build_status(_as_text(saved_fields.get("build"), "green"))
    else:
        try:
            execution = _run_migrate_execution(
                provider=provider,
                runner_bin=runner_bin,
                model=model,
                workspace=workspace,
                schema_path=schema_path,
                output_path=output_path,
                prompt=prompt,
                timeout_minutes=timeout_minutes,
                unsafe=unsafe,
            )
        except FileNotFoundError:
            fields = _hydrate_fields(base_fields, state_result.get("fields"))
            fields["project"] = migrated_project.name
            detail = f"no se encontro el binario `{runner_bin}`"
            set_result(state, status="fail", detail=detail, fields=fields)
            mark_stage(state, "migrate", status="fail", detail=detail, fields=fields)
            save_state(workspace, "migrate", state)
            return BatchRow(service, "fail", detail, fields)
        except subprocess.TimeoutExpired as exc:
            stdout_text = _as_text(exc.stdout)
            stderr_text = _as_text(exc.stderr)
            stdout_path.write_text(stdout_text, encoding="utf-8")
            stderr_path.write_text(stderr_text, encoding="utf-8")
            fields = _hydrate_fields(base_fields, state_result.get("fields"))
            fields.update(
                {
                    "codex": "timeout",
                    "result": "failed",
                    "framework": "?",
                    "build": "unknown",
                    "check": "not_run" if run_check else "skip",
                    "seconds": f"{time.perf_counter() - started:.1f}",
                    "project": migrated_project.name,
                }
            )
            set_result(state, status="fail", detail=f"timeout despues de {timeout_minutes}m", fields=fields)
            mark_stage(state, "migrate", status="fail", detail=f"timeout despues de {timeout_minutes}m", fields=fields)
            save_state(workspace, "migrate", state)
            return BatchRow(service, "fail", f"timeout despues de {timeout_minutes}m", fields)

        elapsed = time.perf_counter() - started
        stdout_text = execution.stdout_text
        stderr_text = execution.stderr_text
        stdout_path.write_text(stdout_text, encoding="utf-8")
        stderr_path.write_text(stderr_text, encoding="utf-8")

        payload = execution.payload or _read_structured_message(output_path)
        session_id = execution.session_id
        result_status = _as_text(payload.get("status"), "ok" if execution.returncode == 0 else "failed").lower()
        summary = _as_text(payload.get("summary")).strip()
        if not summary:
            summary = (
                stderr_text.strip()
                or execution.summary_fallback
                or f"{provider} termino sin resumen estructurado"
            )
        framework = _as_text(payload.get("framework"), "?").strip() or "?"
        notes = payload.get("notes")
        reported_notes = []
        if isinstance(notes, list):
            reported_notes = [_as_text(item).strip() for item in notes if _as_text(item).strip()]
        reported_build = _as_text(payload.get("build_status"), "unknown").strip() or "unknown"
        build_status = _normalize_build_status(reported_build)
        reported_project = _as_text(payload.get("migrated_project"), str(migrated_project)).strip()
        reported_project_path = Path(reported_project) if reported_project else migrated_project
        if not reported_project_path.is_absolute():
            reported_project_path = workspace / reported_project_path
        if not reported_project_path.exists():
            reported_project_path = migrated_project
        project_name = reported_project_path.name

        if _needs_host_build_fallback(summary, reported_build):
            host_build_status, host_build_detail = _run_host_build_fallback(reported_project_path, ts=ts)
            build_status = host_build_status
            reported_build = host_build_detail
            if host_build_status == "green":
                if _reported_no_edits(summary, reported_notes):
                    summary = (
                        f"{summary} Validacion host-side: {host_build_detail} "
                        "Codex reporto que no hizo ediciones; requiere reintento."
                    ).strip()
                else:
                    result_status = "ok"
                    summary = (
                        f"{summary} Validacion host-side: {host_build_detail}"
                        if summary
                        else host_build_detail
                    )
            elif host_build_detail:
                summary = (
                    f"{summary} Validacion host-side: {host_build_detail}"
                    if summary
                    else host_build_detail
                )

        migrate_fields = {
            "codex": (
                "ok"
                if provider == "codex" and execution.returncode == 0
                else (
                    f"exit_{execution.returncode}"
                    if provider == "codex"
                    else (
                        f"{provider}:ok"
                        if execution.returncode == 0
                        else f"{provider}:exit_{execution.returncode}"
                    )
                )
            ),
            "result": result_status,
            "framework": framework,
            "build": reported_build,
            "check": "not_run" if run_check else "skip",
            "seconds": f"{elapsed:.1f}",
            "project": project_name,
        }
        if session_id:
            migrate_fields["session_id"] = session_id
        migrate_stage_status = "ok" if execution.returncode == 0 and result_status == "ok" and build_status == "green" else "fail"
        mark_stage(state, "migrate", status=migrate_stage_status, detail=summary.splitlines()[0][:160], fields=migrate_fields)
        save_state(workspace, "migrate", state)

    saved_migrate_fields = {}
    migrate_stage_data = state.get("stages", {}).get("migrate", {})
    if isinstance(migrate_stage_data, dict):
        saved_migrate_fields = migrate_stage_data.get("fields", {})

    fields = _hydrate_fields(base_fields, saved_migrate_fields or state_result.get("fields"))
    fields["project"] = project_name
    if not skip_migrate and elapsed > 0:
        fields["seconds"] = f"{elapsed:.1f}"

    check_status = fields.get("check", "not_run" if run_check else "skip")
    if run_check:
        if resume and stage_ok(state, "check"):
            stage_data = state.get("stages", {}).get("check", {})
            if isinstance(stage_data, dict):
                saved_check_fields = stage_data.get("fields", {})
                fields["check"] = _as_text(saved_check_fields.get("check"), _as_text(stage_data.get("detail"), "READY_TO_MERGE"))
            check_status = fields["check"]
        else:
            try:
                check_result = _run_batch_check(service, migrated_project, _find_legacy_root(workspace, service))
                check_status = check_result["verdict"]
                fields["check"] = check_status
                mark_stage(
                    state,
                    "check",
                    status="ok" if not check_status.startswith("BLOCKED_BY_HIGH") else "fail",
                    detail=check_status,
                    fields={"check": check_status, "report": check_result["report"]},
                )
            except Exception as exc:
                check_status = f"CHECK_ERROR: {type(exc).__name__}"
                fields["check"] = check_status
                mark_stage(state, "check", status="fail", detail=check_status, fields={"check": check_status})
            save_state(workspace, "migrate", state)

    row_status = "ok"
    if (
        (
            fields.get("codex", "") not in {"ok"}
            and not fields.get("codex", "").endswith(":ok")
        )
        or result_status != "ok"
        or build_status != "green"
        or check_status.startswith("BLOCKED_BY_HIGH")
        or check_status.startswith("CHECK_ERROR")
    ):
        row_status = "fail"

    detail = (summary or _as_text(state_result.get("detail")) or "migrate completed").splitlines()[0][:160]
    set_result(state, status=row_status, detail=detail, fields=fields)
    save_state(workspace, "migrate", state)
    return BatchRow(service, row_status, detail, fields)


def _process_pipeline_service(
    service: str,
    root: Path,
    schema_path: Path,
    *,
    harnesses: list[str],
    artifact_token: str | None,
    namespace: str,
    group_id: str,
    provider: str = "codex",
    runner_bin: str | None = None,
    codex_bin: str | None = None,
    model: str | None,
    prompt_file: Path | None,
    timeout_minutes: int,
    skip_tx: bool,
    shallow: bool,
    skip_check: bool,
    unsafe: bool,
    resume: bool = False,
) -> BatchRow:
    if runner_bin is None:
        runner_bin = codex_bin or provider

    from capamedia_cli.commands.clone import clone_service
    from capamedia_cli.commands.fabrics import generate, inspect_fabrics_workspace
    from capamedia_cli.commands.init import scaffold_project

    workspace = root / service
    workspace.mkdir(parents=True, exist_ok=True)
    state = load_state(workspace, "pipeline", service, reset=not resume)

    fields = {
        "clone": "pending",
        "init": "pending",
        "fabric": "pending",
        "codex": "pending",
        "result": "pending",
        "build": "pending",
        "check": "pending",
        "seconds": "0.0",
        "project": "?",
    }

    started = time.perf_counter()

    if not (resume and stage_ok(state, "clone") and _find_legacy_root(workspace, service) and _has_complexity_report(workspace, service)):
        try:
            clone_service(service, workspace=workspace, shallow=shallow, skip_tx=skip_tx)
            fields["clone"] = "ok"
            mark_stage(state, "clone", status="ok", detail="clone completed", fields={"clone": "ok"})
            save_state(workspace, "pipeline", state)
        except typer.Exit:
            fields["clone"] = "fail"
            fields["seconds"] = f"{time.perf_counter() - started:.1f}"
            mark_stage(state, "clone", status="fail", detail="clone failed", fields={"clone": "fail"})
            set_result(state, status="fail", detail="clone failed", fields=fields)
            save_state(workspace, "pipeline", state)
            return BatchRow(service, "fail", "clone failed", fields)
        except Exception as exc:
            fields["clone"] = "fail"
            fields["seconds"] = f"{time.perf_counter() - started:.1f}"
            detail = f"clone error: {type(exc).__name__}: {exc}"
            mark_stage(state, "clone", status="fail", detail=detail, fields={"clone": "fail"})
            set_result(state, status="fail", detail=detail, fields=fields)
            save_state(workspace, "pipeline", state)
            return BatchRow(service, "fail", detail, fields)
    else:
        fields["clone"] = "ok"

    if not (resume and stage_ok(state, "init") and _has_init_material(workspace)):
        try:
            scaffold_project(
                target_dir=workspace,
                service_name=service,
                harnesses=harnesses,
                artifact_token=artifact_token,
            )
            fields["init"] = "ok"
            mark_stage(state, "init", status="ok", detail="init completed", fields={"init": "ok"})
            save_state(workspace, "pipeline", state)
        except Exception as exc:
            fields["init"] = "fail"
            fields["seconds"] = f"{time.perf_counter() - started:.1f}"
            detail = f"init error: {type(exc).__name__}: {exc}"
            mark_stage(state, "init", status="fail", detail=detail, fields={"init": "fail"})
            set_result(state, status="fail", detail=detail, fields=fields)
            save_state(workspace, "pipeline", state)
            return BatchRow(service, "fail", detail, fields)
    else:
        fields["init"] = "ok"

    if not (resume and stage_ok(state, "fabric") and _has_fabrics_material(workspace)):
        fabrics_ready = inspect_fabrics_workspace(workspace)
        if fabrics_ready["status"] != "ok":
            fields["fabric"] = "fail"
            fields["seconds"] = f"{time.perf_counter() - started:.1f}"
            detail = f"fabrics preflight failed: {fabrics_ready['detail']}"
            mark_stage(state, "fabric", status="fail", detail=detail, fields={"fabric": "fail"})
            set_result(state, status="fail", detail=detail, fields=fields)
            save_state(workspace, "pipeline", state)
            return BatchRow(service, "fail", detail, fields)
        try:
            generate(
                service_name=service,
                workspace=workspace,
                namespace=namespace,
                group_id=group_id,
                dry_run=False,
            )
            fabrics_meta = _load_fabrics_metadata(workspace)
            if not fabrics_meta:
                raise RuntimeError("Fabrics no dejo metadata en .capamedia/fabrics.json")
            fabric_status = _as_text(fabrics_meta.get("status"), "ok") or "ok"
            fabric_detail = _as_text(fabrics_meta.get("detail"), "fabric completed") or "fabric completed"
            fields["fabric"] = fabric_status
            fields["project"] = _as_text(fabrics_meta.get("project_name"), fields["project"])
            mark_stage(
                state,
                "fabric",
                status="ok",
                detail=fabric_detail,
                fields={"fabric": fabric_status, "project": fields["project"]},
            )
            save_state(workspace, "pipeline", state)
        except typer.Exit:
            fields["fabric"] = "fail"
            fields["seconds"] = f"{time.perf_counter() - started:.1f}"
            mark_stage(state, "fabric", status="fail", detail="fabric failed", fields={"fabric": "fail"})
            set_result(state, status="fail", detail="fabric failed", fields=fields)
            save_state(workspace, "pipeline", state)
            return BatchRow(service, "fail", "fabric failed", fields)
        except Exception as exc:
            fields["fabric"] = "fail"
            fields["seconds"] = f"{time.perf_counter() - started:.1f}"
            detail = f"fabric error: {type(exc).__name__}: {exc}"
            mark_stage(state, "fabric", status="fail", detail=detail, fields={"fabric": "fail"})
            set_result(state, status="fail", detail=detail, fields=fields)
            save_state(workspace, "pipeline", state)
            return BatchRow(service, "fail", detail, fields)
    else:
        fabrics_meta = _load_fabrics_metadata(workspace)
        fields["fabric"] = _as_text((fabrics_meta or {}).get("status"), "ok")
        fields["project"] = _as_text((fabrics_meta or {}).get("project_name"), fields["project"])

    migrate_row = _process_migrate_service(
        service,
        root,
        schema_path,
        provider=provider,
        runner_bin=runner_bin,
        model=model,
        prompt_file=prompt_file,
        timeout_minutes=timeout_minutes,
        run_check=not skip_check,
        unsafe=unsafe,
        resume=resume,
    )
    fields.update(migrate_row.fields)
    fields["seconds"] = f"{time.perf_counter() - started:.1f}"
    mark_stage(state, "migrate", status="ok" if migrate_row.status == "ok" else "fail", detail=migrate_row.detail, fields=migrate_row.fields)
    if not skip_check:
        mark_stage(
            state,
            "check",
            status="ok" if migrate_row.fields.get("check", "").startswith("READY") else "fail",
            detail=migrate_row.fields.get("check", ""),
            fields={"check": migrate_row.fields.get("check", "")},
        )
    set_result(state, status=migrate_row.status, detail=migrate_row.detail, fields=fields)
    save_state(workspace, "pipeline", state)
    return BatchRow(service, migrate_row.status, migrate_row.detail, fields)


def _run_service_with_retries(
    service: str,
    runner,
    *,
    retries: int,
) -> BatchRow:
    last_row: BatchRow | None = None
    for attempt in range(retries + 1):
        row = runner(service, attempt)
        if row.status == "ok":
            return row
        last_row = row
    assert last_row is not None
    return last_row


def _ensure_legacy_available(service: str, root: Path, shallow: bool) -> tuple[Path | None, str]:
    """Resuelve el legacy del servicio: local first, fallback a Azure multi-project.

    Retorna (path_legacy, source_msg). Si path es None, source_msg indica el motivo de error.
    """
    from capamedia_cli.commands.clone import _resolve_azure_repo
    from capamedia_cli.core.local_resolver import find_local_legacy

    # 1. Buscar local primero
    capa_media_root = root.parent
    local = find_local_legacy(service, capa_media_root)
    if local:
        return (local, "local")

    # 2. Fallback a Azure DevOps multi-proyecto / multi-patron
    svc_workspace = root / service
    svc_workspace.mkdir(parents=True, exist_ok=True)
    legacy_dest, project_key, repo_name = _resolve_azure_repo(service, svc_workspace, shallow)
    if legacy_dest is None:
        return (None, "not local + no Azure project found")
    return (legacy_dest, f"azure: {project_key}/{repo_name}")


# Backward compat
def _ensure_legacy_cloned(service: str, root: Path, shallow: bool) -> tuple[bool, str]:
    """Wrapper legacy para tests viejos."""
    path, msg = _ensure_legacy_available(service, root, shallow)
    return (path is not None, msg)


# -- Subcommands ------------------------------------------------------------


@app.command("complexity")
def batch_complexity(
    file: Annotated[
        Path,
        typer.Option("--from", "-f", help="Archivo .txt / .csv / .xlsx con un servicio por linea"),
    ],
    sheet: Annotated[
        str | None,
        typer.Option("--sheet", help="Hoja del .xlsx (default: primera)"),
    ] = None,
    workers: Annotated[int, typer.Option("--workers", "-w")] = 4,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Carpeta raiz donde clonar workspaces (default: CWD)"),
    ] = None,
    shallow: Annotated[bool, typer.Option("--shallow")] = True,
    csv_out: Annotated[bool, typer.Option("--csv", help="Ademas del .md, genera un .csv")] = False,
) -> None:
    """Analiza complejidad de N servicios en paralelo."""
    from capamedia_cli.core.legacy_analyzer import analyze_legacy

    services = _read_services_file(file, sheet=sheet)
    ws = (root or Path.cwd()).resolve()

    console.print(
        Panel.fit(
            f"[bold]batch complexity[/bold]\n"
            f"Servicios: {len(services)} · Workers: {workers} · Root: {ws}",
            border_style="cyan",
        )
    )

    rows: list[BatchRow] = []

    def process(service: str) -> BatchRow:
        legacy_root, msg = _ensure_legacy_available(service, ws, shallow)
        if legacy_root is None:
            return BatchRow(service, "fail", msg, {})
        try:
            analysis = analyze_legacy(legacy_root, service_name=service, umps_root=None)
        except Exception as e:
            return BatchRow(service, "fail", f"analyze error: {e}", {})

        # Detectar dominios distintos via UMPs
        from capamedia_cli.core.domain_mapping import domains_for_umps

        ump_names = [u.name for u in analysis.umps]
        domains = domains_for_umps(ump_names)
        domain_str = "+".join(d.pascal for d in domains) if domains else "-"

        return BatchRow(
            service,
            "ok",
            f"source={msg}",
            {
                "tipo": analysis.source_kind.upper(),
                "ops": str(analysis.wsdl.operation_count) if analysis.wsdl else "?",
                "framework": analysis.framework_recommendation.upper() or "?",
                "umps": str(len(analysis.umps)),
                "dominios": domain_str,
                "bd": "SI" if analysis.has_database else "NO",
                "complejidad": analysis.complexity.upper(),
            },
        )

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Analizando", total=len(services))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed(pool.submit(process, s) for s in services):
                rows.append(future.result())
                progress.advance(task)

    rows.sort(key=lambda r: r.service)
    field_order = ["tipo", "ops", "framework", "umps", "dominios", "bd", "complejidad"]

    _render_table("complexity", rows, field_order)
    md = _write_markdown_report("complexity", rows, ws, field_order)
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{md}[/cyan]")
    if csv_out:
        csvf = _write_csv_report("complexity", rows, ws, field_order)
        console.print(f"[bold]CSV:[/bold] [cyan]{csvf}[/cyan]")


@app.command("clone")
def batch_clone(
    file: Annotated[
        Path, typer.Option("--from", "-f", help="Archivo .txt / .csv / .xlsx con servicios")
    ],
    sheet: Annotated[
        str | None, typer.Option("--sheet", help="Hoja del .xlsx (default: primera)")
    ] = None,
    workers: Annotated[int, typer.Option("--workers", "-w")] = 4,
    root: Annotated[Path | None, typer.Option("--root")] = None,
    shallow: Annotated[bool, typer.Option("--shallow")] = False,
) -> None:
    """Clone masivo (legacy + UMPs + TX) en paralelo."""
    from capamedia_cli.commands.clone import clone_service

    services = _read_services_file(file, sheet=sheet)
    ws = (root or Path.cwd()).resolve()
    console.print(
        Panel.fit(
            f"[bold]batch clone[/bold]\n"
            f"Servicios: {len(services)} · Workers: {workers} · Root: {ws}",
            border_style="cyan",
        )
    )

    rows: list[BatchRow] = []

    def process(service: str) -> BatchRow:
        svc_ws = ws / service
        svc_ws.mkdir(parents=True, exist_ok=True)
        try:
            # Invocamos el clone_service directo pasando workspace=svc_ws
            # (no imprime por stdout en modo batch — los logs individuales se pierden;
            # solo nos interesa el resultado agregado)
            clone_service(service, workspace=svc_ws, shallow=shallow, skip_tx=False)
            return BatchRow(service, "ok", str(svc_ws), {"workspace": str(svc_ws.name)})
        except typer.Exit:
            return BatchRow(service, "fail", "clone failed (typer.Exit)", {})
        except Exception as e:
            return BatchRow(service, "fail", f"{type(e).__name__}: {e}", {})

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Clonando", total=len(services))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed(pool.submit(process, s) for s in services):
                rows.append(future.result())
                progress.advance(task)

    rows.sort(key=lambda r: r.service)
    _render_table("clone", rows, ["workspace"])
    md = _write_markdown_report("clone", rows, ws, ["workspace"])
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{md}[/cyan]")


@app.command("check")
def batch_check(
    root: Annotated[Path, typer.Argument(help="Directorio raiz donde viven los workspaces")],
    glob_pattern: Annotated[
        str,
        typer.Option(
            "--glob",
            help="Glob relativo desde root para localizar proyectos migrados. Ej: '*/destino/*'",
        ),
    ] = "*/destino/*",
    workers: Annotated[int, typer.Option("--workers", "-w")] = 4,
) -> None:
    """Audita checklist sobre N proyectos migrados en paralelo."""
    from capamedia_cli.core.checklist_rules import CheckContext, run_all_blocks

    root = root.resolve()
    projects = [p for p in root.glob(glob_pattern) if (p / "build.gradle").exists()]
    if not projects:
        console.print(f"[yellow]No se encontraron proyectos con build.gradle bajo {root / glob_pattern}[/yellow]")
        raise typer.Exit(0)

    console.print(
        Panel.fit(
            f"[bold]batch check[/bold]\n"
            f"Proyectos: {len(projects)} · Workers: {workers} · Root: {root}",
            border_style="cyan",
        )
    )

    rows: list[BatchRow] = []

    def process(proj: Path) -> BatchRow:
        # Auto-descubrir legacy hermano
        legacy_path = None
        for candidate in (proj.parent.parent / "legacy", proj.parent / "legacy"):
            if candidate.exists():
                legacy_path = candidate
                break
        ctx = CheckContext(migrated_path=proj, legacy_path=legacy_path)
        try:
            results = run_all_blocks(ctx)
        except Exception as e:
            return BatchRow(proj.name, "fail", f"check error: {e}", {})

        high = sum(1 for r in results if r.status == "fail" and r.severity == "high")
        medium = sum(1 for r in results if r.status == "fail" and r.severity == "medium")
        low = sum(1 for r in results if r.status == "fail" and r.severity == "low")
        pass_ = sum(1 for r in results if r.status == "pass")

        if high > 0:
            verdict = "BLOCKED_BY_HIGH"
        elif medium > 0:
            verdict = "READY_WITH_FOLLOW_UP"
        else:
            verdict = "READY_TO_MERGE"

        return BatchRow(
            proj.name,
            "ok" if high == 0 else "fail",
            verdict,
            {
                "verdict": verdict,
                "pass": str(pass_),
                "HIGH": str(high),
                "MEDIUM": str(medium),
                "LOW": str(low),
            },
        )

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Auditando", total=len(projects))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed(pool.submit(process, p) for p in projects):
                rows.append(future.result())
                progress.advance(task)

    rows.sort(key=lambda r: r.service)
    field_order = ["verdict", "pass", "HIGH", "MEDIUM", "LOW"]
    _render_table("check", rows, field_order)
    md = _write_markdown_report("check", rows, root, field_order)
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{md}[/cyan]")


@app.command("init")
def batch_init(
    file: Annotated[
        Path, typer.Option("--from", "-f", help="Archivo .txt / .csv / .xlsx con servicios")
    ],
    sheet: Annotated[
        str | None, typer.Option("--sheet", help="Hoja del .xlsx (default: primera)")
    ] = None,
    ai: Annotated[str, typer.Option("--ai", help="Harness(es) CSV o 'all'")] = "claude",
    workers: Annotated[int, typer.Option("--workers", "-w")] = 4,
    root: Annotated[Path | None, typer.Option("--root")] = None,
) -> None:
    """Inicializa N workspaces con el scaffold AI del proyecto + .mcp.json."""
    from capamedia_cli.adapters import resolve_harnesses
    from capamedia_cli.commands.init import scaffold_project

    services = _read_services_file(file, sheet=sheet)
    ws = (root or Path.cwd()).resolve()
    harnesses = resolve_harnesses(ai)
    console.print(
        Panel.fit(
            f"[bold]batch init[/bold]\n"
            f"Servicios: {len(services)} · Harness: {ai} · Workers: {workers}",
            border_style="cyan",
        )
    )

    rows: list[BatchRow] = []

    def process(service: str) -> BatchRow:
        svc_ws = ws / service
        svc_ws.mkdir(parents=True, exist_ok=True)
        try:
            scaffold_project(
                target_dir=svc_ws,
                service_name=service,
                harnesses=harnesses,
                artifact_token=None,
            )
            return BatchRow(service, "ok", "inicializado", {"harness": ai})
        except Exception as e:
            return BatchRow(service, "fail", f"{type(e).__name__}: {e}", {})

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Inicializando", total=len(services))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed(pool.submit(process, s) for s in services):
                rows.append(future.result())
                progress.advance(task)

    rows.sort(key=lambda r: r.service)
    _render_table("init", rows, ["harness"])
    md = _write_markdown_report("init", rows, ws, ["harness"])
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{md}[/cyan]")


@app.command("watch")
def batch_watch(
    root: Annotated[Path, typer.Argument(help="Directorio raiz donde viven los workspaces")],
    file: Annotated[
        Path | None,
        typer.Option("--from", "-f", help="Archivo opcional .txt / .csv / .xlsx con servicios"),
    ] = None,
    sheet: Annotated[
        str | None, typer.Option("--sheet", help="Hoja del .xlsx (default: primera)")
    ] = None,
    kind: Annotated[
        str,
        typer.Option("--kind", help="Que estado mirar: auto | pipeline | migrate"),
    ] = "auto",
    failures_only: Annotated[
        bool, typer.Option("--failures-only", help="Mostrar solo servicios fallidos")
    ] = False,
    follow: Annotated[
        bool, typer.Option("--follow", help="Refresca periodicamente hasta Ctrl+C")
    ] = False,
    interval_seconds: Annotated[
        int, typer.Option("--interval-seconds", help="Intervalo de refresh en modo --follow")
    ] = 15,
) -> None:
    """Mirador operativo de lotes batch usando el estado persistente por servicio."""
    root = root.resolve()
    if kind not in {"auto", "pipeline", "migrate"}:
        raise typer.BadParameter("kind debe ser uno de: auto, pipeline, migrate")

    if file is not None:
        services = _read_services_file(file, sheet=sheet)
    else:
        services = sorted(
            p.name
            for p in root.iterdir()
            if p.is_dir()
            and not p.name.startswith(".")
            and any((p / marker).exists() for marker in (".capamedia", "legacy", "destino"))
        )

    if not services:
        console.print(f"[yellow]No se encontraron servicios bajo {root}[/yellow]")
        raise typer.Exit(0)

    def render_snapshot() -> list[BatchRow]:
        rows = _collect_watch_rows(root, services, kind)
        if failures_only:
            rows = [row for row in rows if row.status == "fail"]
        _render_table("watch", rows, WATCH_FIELD_ORDER)
        return rows

    if follow:
        try:
            while True:
                console.clear()
                console.print(
                    Panel.fit(
                        f"[bold]batch watch[/bold]\n"
                        f"Servicios: {len(services)} · Root: {root}\n"
                        f"Kind: {kind} · Failures only: {'SI' if failures_only else 'NO'} · Every: {interval_seconds}s",
                        border_style="cyan",
                    )
                )
                render_snapshot()
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            console.print("\n[yellow]watch cancelado por el usuario[/yellow]")
        return

    console.print(
        Panel.fit(
            f"[bold]batch watch[/bold]\n"
            f"Servicios: {len(services)} · Root: {root}\n"
            f"Kind: {kind} · Failures only: {'SI' if failures_only else 'NO'}",
            border_style="cyan",
        )
    )
    rows = render_snapshot()
    md = _write_markdown_report(f"watch-{kind}", rows, root, WATCH_FIELD_ORDER)
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{md}[/cyan]")


@app.command("pipeline")
def batch_pipeline(
    file: Annotated[
        Path,
        typer.Option("--from", "-f", help="Archivo .txt / .csv / .xlsx con servicios"),
    ],
    namespace: Annotated[
        str,
        typer.Option(
            "--namespace",
            "-n",
            help="Namespace del catalogo para Fabrics (obligatorio en modo batch)",
        ),
    ],
    sheet: Annotated[
        str | None, typer.Option("--sheet", help="Hoja del .xlsx (default: primera)")
    ] = None,
    ai: Annotated[
        str,
        typer.Option(
            "--ai",
            help="Harness(es) CSV para el scaffold. `codex` se agrega automaticamente si falta.",
        ),
    ] = "codex",
    workers: Annotated[int, typer.Option("--workers", "-w")] = 2,
    root: Annotated[Path | None, typer.Option("--root")] = None,
    group_id: Annotated[str, typer.Option("--group-id")] = "com.pichincha.sp",
    artifact_token: Annotated[
        str | None,
        typer.Option("--artifact-token", help="Override del token para renderizar .mcp.json"),
    ] = None,
    provider: Annotated[
        str,
        typer.Option("--provider", help="Runner headless: codex o claude.", case_sensitive=False),
    ] = "codex",
    runner_bin: Annotated[
        str,
        typer.Option("--runner-bin", help="Binario del runner seleccionado."),
    ] = "",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override del modelo para el runner seleccionado."),
    ] = None,
    prompt_file: Annotated[
        Path | None,
        typer.Option(
            "--prompt-file",
            help="Prompt base alternativo para todos los servicios. Default: <workspace>/.codex/prompts/migrate.md",
        ),
    ] = None,
    timeout_minutes: Annotated[
        int, typer.Option("--timeout-minutes", help="Timeout maximo por servicio para migrate")
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
    resume: Annotated[
        bool, typer.Option("--resume", help="Reanuda servicios saltando etapas ya exitosas")
    ] = False,
    retries: Annotated[
        int, typer.Option("--retries", help="Reintentos adicionales por servicio")
    ] = 0,
    unsafe: Annotated[
        bool,
        typer.Option(
            "--unsafe",
            help="Usa `--dangerously-bypass-approvals-and-sandbox` en `codex exec`",
        ),
    ] = False,
) -> None:
    """Ejecuta el pipeline completo por servicio en paralelo."""
    from capamedia_cli.adapters import resolve_harnesses

    provider = provider.strip().lower()
    if provider not in {"codex", "claude"}:
        raise typer.BadParameter("provider debe ser `codex` o `claude`")

    services = _read_services_file(file, sheet=sheet)
    ws = (root or Path.cwd()).resolve()

    if prompt_file is not None:
        prompt_file = prompt_file.resolve()
        if not prompt_file.exists():
            raise typer.BadParameter(f"prompt no existe: {prompt_file}")

    harnesses = resolve_harnesses(ai)
    if "codex" not in harnesses:
        harnesses.append("codex")

    schema_path = _ensure_migrate_schema(ws)

    console.print(
        Panel.fit(
            f"[bold]batch pipeline[/bold]\n"
            f"Servicios: {len(services)} · Workers: {workers} · Root: {ws}\n"
            f"Harnesses: {', '.join(harnesses)} · Namespace: {namespace} · Runner: {provider}\n"
            f"Model: {model or (DEFAULT_CLAUDE_MODEL if provider == 'claude' else DEFAULT_CODEX_MODEL)}\n"
            f"Resume: {'SI' if resume else 'NO'} · Retries: {retries}",
            border_style="cyan",
        )
    )

    rows: list[BatchRow] = []

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Pipeline", total=len(services))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    _run_service_with_retries,
                    service,
                    lambda svc, attempt: _process_pipeline_service(
                        svc,
                        ws,
                        schema_path,
                        harnesses=harnesses,
                        artifact_token=artifact_token,
                        namespace=namespace,
                        group_id=group_id,
                        provider=provider,
                        runner_bin=runner_bin or provider,
                        model=model,
                        prompt_file=prompt_file,
                        timeout_minutes=timeout_minutes,
                        skip_tx=skip_tx,
                        shallow=shallow,
                        skip_check=skip_check,
                        unsafe=unsafe,
                        resume=resume or attempt > 0,
                    ),
                    retries=retries,
                )
                for service in services
            ]
            for future in as_completed(futures):
                rows.append(future.result())
                progress.advance(task)

    rows.sort(key=lambda r: r.service)
    _render_table("pipeline", rows, PIPELINE_FIELD_ORDER)
    md = _write_markdown_report("pipeline", rows, ws, PIPELINE_FIELD_ORDER)
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{md}[/cyan]")


@app.command("migrate")
def batch_migrate(
    file: Annotated[
        Path,
        typer.Option("--from", "-f", help="Archivo .txt / .csv / .xlsx con servicios"),
    ],
    sheet: Annotated[
        str | None, typer.Option("--sheet", help="Hoja del .xlsx (default: primera)")
    ] = None,
    workers: Annotated[int, typer.Option("--workers", "-w")] = 2,
    root: Annotated[Path | None, typer.Option("--root")] = None,
    provider: Annotated[
        str,
        typer.Option("--provider", help="Runner headless: codex o claude.", case_sensitive=False),
    ] = "codex",
    runner_bin: Annotated[
        str,
        typer.Option("--runner-bin", help="Binario del runner seleccionado."),
    ] = "",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override del modelo para el runner seleccionado."),
    ] = None,
    prompt_file: Annotated[
        Path | None,
        typer.Option(
            "--prompt-file",
            help="Prompt base alternativo para todos los servicios. Default: <workspace>/.codex/prompts/migrate.md",
        ),
    ] = None,
    timeout_minutes: Annotated[
        int, typer.Option("--timeout-minutes", help="Timeout maximo por servicio")
    ] = 90,
    skip_check: Annotated[
        bool, typer.Option("--skip-check", help="No ejecutar checklist post-migracion")
    ] = False,
    resume: Annotated[
        bool, typer.Option("--resume", help="Reanuda servicios ya migrados exitosamente")
    ] = False,
    retries: Annotated[
        int, typer.Option("--retries", help="Reintentos adicionales por servicio")
    ] = 0,
    unsafe: Annotated[
        bool,
        typer.Option(
            "--unsafe",
            help="Usa `--dangerously-bypass-approvals-and-sandbox` en `codex exec`",
        ),
    ] = False,
) -> None:
    """Ejecuta `codex exec` en paralelo sobre workspaces ya preparados."""
    provider = provider.strip().lower()
    if provider not in {"codex", "claude"}:
        raise typer.BadParameter("provider debe ser `codex` o `claude`")

    services = _read_services_file(file, sheet=sheet)
    ws = (root or Path.cwd()).resolve()

    if prompt_file is not None:
        prompt_file = prompt_file.resolve()
        if not prompt_file.exists():
            raise typer.BadParameter(f"prompt no existe: {prompt_file}")

    schema_path = _ensure_migrate_schema(ws)

    console.print(
        Panel.fit(
            f"[bold]batch migrate[/bold]\n"
            f"Servicios: {len(services)} · Workers: {workers} · Root: {ws}\n"
            f"Runner: {provider} · Model: {model or (DEFAULT_CLAUDE_MODEL if provider == 'claude' else DEFAULT_CODEX_MODEL)} · Checklist: {'NO' if skip_check else 'SI'}\n"
            f"Resume: {'SI' if resume else 'NO'} · Retries: {retries}",
            border_style="cyan",
        )
    )

    rows: list[BatchRow] = []

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Migrando", total=len(services))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    _run_service_with_retries,
                    service,
                    lambda svc, attempt: _process_migrate_service(
                        svc,
                        ws,
                        schema_path,
                        provider=provider,
                        runner_bin=runner_bin or provider,
                        model=model,
                        prompt_file=prompt_file,
                        timeout_minutes=timeout_minutes,
                        run_check=not skip_check,
                        unsafe=unsafe,
                        resume=resume or attempt > 0,
                    ),
                    retries=retries,
                )
                for service in services
            ]
            for future in as_completed(futures):
                rows.append(future.result())
                progress.advance(task)

    rows.sort(key=lambda r: r.service)
    _render_table("migrate", rows, MIGRATE_FIELD_ORDER)
    md = _write_markdown_report("migrate", rows, ws, MIGRATE_FIELD_ORDER)
    console.print(f"\n[bold]Reporte:[/bold] [cyan]{md}[/cyan]")
