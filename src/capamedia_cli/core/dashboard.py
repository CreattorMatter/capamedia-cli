"""Dashboard en tiempo real para `capamedia batch watch`.

Lee los JSON persistentes en `<workspace>/.capamedia/batch-state/*.json`
(escritos por `core.batch_state`) y sintetiza un panel con barras de
progreso por servicio + totales agregados. NO modifica orquestacion.

Fases conocidas (alineadas con mark_stage() de commands/batch.py):
    queued -> clone -> init -> fabric -> migrate -> check -> done

Mapping fase -> porcentaje (monotonic, basado en proxy de duracion):
    queued=0, clone=20, init=35, fabric=55, migrate=80, check=95, done=100

Los sinonimos (codex_exec, codex, codex-exec) se normalizan a 'migrate'.
Si `status == "failed"` (derivado de result.status o stage.status), la
barra queda en el ultimo porcentaje conocido y se pinta en rojo.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Orden canonico de fases y su porcentaje de completado visual.
PHASE_ORDER: tuple[str, ...] = ("queued", "clone", "init", "fabric", "migrate", "check", "done")

PHASE_PERCENT: dict[str, int] = {
    "queued": 0,
    "clone": 20,
    "init": 35,
    "fabric": 55,
    "migrate": 80,
    "codex_exec": 80,  # sinonimo
    "codex": 80,  # sinonimo
    "check": 95,
    "done": 100,
}

# Stages que se evaluan en orden para inferir fase cuando no hay result.ok.
_STAGES_PIPELINE: tuple[str, ...] = ("clone", "init", "fabric", "migrate", "check")
_STAGES_MIGRATE: tuple[str, ...] = ("migrate", "check")

# Ancho de la barra (caracteres).
BAR_WIDTH = 22
BAR_FILLED = "\u2588"  # full block (UTF-8)
BAR_EMPTY = "\u2591"  # light shade (UTF-8)
BAR_FILLED_ASCII = "#"
BAR_EMPTY_ASCII = "."


def _supports_unicode_bars() -> bool:
    """Detecta si stdout soporta UTF-8/los glyphs de bloque.

    Windows antiguas con code page 1252 pintan bonito con caja Rich pero
    revientan con U+2588/U+2591. En ese caso caemos a ASCII.
    """
    import sys

    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    # Cualquier otra cosa (cp1252, cp850, latin-1) => ASCII seguro.
    return "utf" in encoding


@dataclass
class ServiceSnapshot:
    """Foto instantanea del estado de un servicio."""

    name: str
    phase: str  # queued|clone|init|fabric|migrate|check|done
    status: str  # queued|running|done|failed
    attempts: int
    started_at: float | None  # epoch seconds
    finished_at: float | None  # epoch seconds
    last_update: float  # epoch seconds
    run_kind: str = "pipeline"
    percent: int = 0
    detail: str = ""


@dataclass
class AggregateStats:
    """Totales agregados de una lista de snapshots."""

    total: int
    done: int
    failed: int
    running: int
    queued: int
    percent: int  # promedio ponderado
    eta_seconds: float | None
    success_rate: float  # done / (done + failed), 0..1 (si no hay finales, 0)
    iter_avg: float  # attempts promedio
    engine: str = "codex"
    elapsed_seconds: float = 0.0
    per_phase: dict[str, int] = field(default_factory=dict)


class Dashboard:
    """Agregador de estado batch.

    Parameters
    ----------
    root:
        Directorio que contiene subdirectorios por servicio.
    services:
        Opcional. Lista explicita de nombres a mirar. Si es None se
        autodescubren los subdirectorios que tengan `.capamedia/`, `legacy/`
        o `destino/`.
    kind:
        auto | pipeline | migrate. Controla que `*.json` leer.
    engine:
        Etiqueta del engine (codex / cursor / etc) usada solo en render.
    clock:
        Inyectable para tests; por defecto `time.time`.
    """

    def __init__(
        self,
        root: Path,
        *,
        services: list[str] | None = None,
        kind: str = "auto",
        engine: str = "codex",
        clock=time.time,
    ) -> None:
        self.root = root
        self._explicit_services = services
        self.kind = kind if kind in {"auto", "pipeline", "migrate"} else "auto"
        self.engine = engine
        self._clock = clock

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def _discover_services(self) -> list[str]:
        if self._explicit_services is not None:
            return list(self._explicit_services)
        if not self.root.exists() or not self.root.is_dir():
            return []
        found: list[str] = []
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if any((entry / marker).exists() for marker in (".capamedia", "legacy", "destino")):
                found.append(entry.name)
        return found

    def _resolve_state_path(self, workspace: Path) -> tuple[Path | None, str]:
        base = workspace / ".capamedia" / "batch-state"
        if self.kind == "pipeline":
            return base / "pipeline.json", "pipeline"
        if self.kind == "migrate":
            return base / "migrate.json", "migrate"
        pipeline_path = base / "pipeline.json"
        migrate_path = base / "migrate.json"
        if pipeline_path.exists():
            return pipeline_path, "pipeline"
        if migrate_path.exists():
            return migrate_path, "migrate"
        return None, "pipeline"

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------
    def snapshot(self) -> list[ServiceSnapshot]:
        snaps: list[ServiceSnapshot] = []
        for service in self._discover_services():
            snaps.append(self._snapshot_for(service))
        return snaps

    def _snapshot_for(self, service: str) -> ServiceSnapshot:
        workspace = self.root / service
        state_path, run_kind = self._resolve_state_path(workspace)
        data = _load_state_json(state_path) if state_path is not None else None
        if data is None:
            return ServiceSnapshot(
                name=service,
                phase="queued",
                status="queued",
                attempts=0,
                started_at=None,
                finished_at=None,
                last_update=self._clock(),
                run_kind=run_kind,
                percent=PHASE_PERCENT["queued"],
                detail="",
            )

        stages = data.get("stages", {}) if isinstance(data.get("stages"), dict) else {}
        result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}

        order = _STAGES_PIPELINE if run_kind == "pipeline" else _STAGES_MIGRATE
        phase, status = _infer_phase_status(stages, result, order)
        percent = _phase_percent(phase)

        attempts = 0
        for stage_data in stages.values():
            if isinstance(stage_data, dict):
                try:
                    attempts += int(stage_data.get("attempts", 0) or 0)
                except (TypeError, ValueError):
                    continue

        started_at = _parse_ts(data.get("created_at"))
        last_update = _parse_ts(data.get("updated_at")) or self._clock()
        finished_at: float | None = None
        if status == "done":
            finished_at = _parse_ts(result.get("updated_at")) or last_update

        detail = ""
        if isinstance(result.get("detail"), str):
            detail = result["detail"]
        if not detail and phase in stages and isinstance(stages[phase], dict):
            stage_detail = stages[phase].get("detail")
            if isinstance(stage_detail, str):
                detail = stage_detail

        return ServiceSnapshot(
            name=service,
            phase=phase,
            status=status,
            attempts=attempts,
            started_at=started_at,
            finished_at=finished_at,
            last_update=last_update,
            run_kind=run_kind,
            percent=percent,
            detail=detail,
        )

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------
    def aggregate(self, snaps: list[ServiceSnapshot]) -> AggregateStats:
        total = len(snaps)
        done = sum(1 for s in snaps if s.status == "done")
        failed = sum(1 for s in snaps if s.status == "failed")
        running = sum(1 for s in snaps if s.status == "running")
        queued = sum(1 for s in snaps if s.status == "queued")
        percent = int(sum(s.percent for s in snaps) / total) if total else 0

        finalized = done + failed
        success_rate = (done / finalized) if finalized else 0.0

        running_snaps = [s for s in snaps if s.status == "running"]
        attempts_sample = [s.attempts for s in snaps if s.attempts > 0]
        iter_avg = (sum(attempts_sample) / len(attempts_sample)) if attempts_sample else 0.0

        elapsed_values = [
            self._clock() - s.started_at for s in snaps if s.started_at is not None
        ]
        elapsed_seconds = max(elapsed_values) if elapsed_values else 0.0

        eta_seconds = _estimate_eta(snaps, done, total, self._clock())

        per_phase: dict[str, int] = {}
        for s in snaps:
            per_phase[s.phase] = per_phase.get(s.phase, 0) + 1
        # silencia warning "unused" cuando no haya running
        _ = running_snaps

        return AggregateStats(
            total=total,
            done=done,
            failed=failed,
            running=running,
            queued=queued,
            percent=percent,
            eta_seconds=eta_seconds,
            success_rate=success_rate,
            iter_avg=iter_avg,
            engine=self.engine,
            elapsed_seconds=elapsed_seconds,
            per_phase=per_phase,
        )


# ----------------------------------------------------------------------
# Helpers de inferencia
# ----------------------------------------------------------------------
def _normalize_phase(name: str) -> str:
    lowered = name.strip().lower().replace("-", "_")
    if lowered in {"codex", "codex_exec", "codex_run"}:
        return "migrate"
    return lowered


def _phase_percent(phase: str) -> int:
    return PHASE_PERCENT.get(_normalize_phase(phase), 0)


def _infer_phase_status(
    stages: dict, result: dict, order: tuple[str, ...]
) -> tuple[str, str]:
    """Inferir (phase, status) a partir de stages+result.

    Regla:
    - Si result.status=='ok' (o 'done') => ('done','done').
    - Si algun stage status=='fail' o result.status=='fail' => phase=ultimo
      stage con progreso, status='failed'.
    - Si ningun stage todavia tiene entry => ('queued','queued').
    - Si el ultimo stage con entry tiene status='ok', fase avanza al
      siguiente stage pendiente; status='running'.
    - Otros valores (in_progress, pending, ...) => phase=ese stage, running.
    """
    result_status = str(result.get("status") or "").lower()

    # Detectar fail primero.
    fail_phase: str | None = None
    for stage_name in order:
        stage_data = stages.get(stage_name)
        if isinstance(stage_data, dict) and str(stage_data.get("status") or "").lower() == "fail":
            fail_phase = stage_name
            break
    if result_status in {"fail", "failed", "error"} and fail_phase is None:
        # Sin stage fallido pero result=fail: usar el ultimo que tenia data.
        for stage_name in reversed(order):
            if isinstance(stages.get(stage_name), dict):
                fail_phase = stage_name
                break
        if fail_phase is None:
            fail_phase = order[0]
    if fail_phase is not None:
        return fail_phase, "failed"

    # Done.
    if result_status in {"ok", "done", "success"}:
        return "done", "done"

    # Sin evidencia => queued.
    if not any(isinstance(stages.get(name), dict) for name in order):
        return "queued", "queued"

    # Primer stage pendiente (sin ok).
    current = order[0]
    for stage_name in order:
        stage_data = stages.get(stage_name)
        if not isinstance(stage_data, dict):
            current = stage_name
            break
        status = str(stage_data.get("status") or "").lower()
        if status == "ok":
            # avanzar; current queda por si es el ultimo ok.
            current = stage_name
            continue
        current = stage_name
        break
    else:
        # todos los stages ok sin result.ok => asumimos running en ultimo.
        current = order[-1]

    # Si el stage actual quedo en 'ok' implica que ya termino y estamos
    # esperando al siguiente; movemos current al siguiente pendiente.
    stage_data = stages.get(current, {})
    if isinstance(stage_data, dict) and str(stage_data.get("status") or "").lower() == "ok":
        idx = order.index(current)
        if idx + 1 < len(order):
            current = order[idx + 1]
    return current, "running"


def _load_state_json(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _parse_ts(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    # Python 3.11+ soporta fromisoformat con offset y 'Z' desde 3.11.
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.timestamp()


def _estimate_eta(
    snaps: list[ServiceSnapshot], done: int, total: int, now: float
) -> float | None:
    """ETA agregada simple.

    Usa el promedio de duracion de los servicios `done` y lo multiplica por
    los pendientes. Si ningun servicio termino aun, fallback a la duracion
    del running mas viejo extrapolada.
    """
    if total == 0 or done == total:
        return None

    pending = total - done
    durations = [
        s.finished_at - s.started_at
        for s in snaps
        if s.status == "done" and s.started_at is not None and s.finished_at is not None
        and s.finished_at >= s.started_at
    ]
    if durations:
        avg = sum(durations) / len(durations)
        return max(0.0, avg * pending)

    # Fallback: extrapolar por porcentaje running mas avanzado.
    running = [s for s in snaps if s.status == "running" and s.started_at is not None]
    if not running:
        return None
    best = max(running, key=lambda s: s.percent)
    if best.percent <= 0:
        return None
    elapsed = now - (best.started_at or now)
    if elapsed <= 0:
        return None
    projected_total = elapsed * 100.0 / best.percent
    remaining_best = max(0.0, projected_total - elapsed)
    return remaining_best * pending


# ----------------------------------------------------------------------
# Formato humano
# ----------------------------------------------------------------------
def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    total = int(max(0, round(seconds)))
    if total < 60:
        return f"{total}s"
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes < 10:
        return f"{minutes}m{secs:02d}s"
    return f"{minutes}m"


def format_bar(percent: int, *, width: int = BAR_WIDTH, ascii_only: bool | None = None) -> str:
    pct = max(0, min(100, int(percent)))
    filled = round(width * pct / 100)
    filled = max(0, min(width, filled))
    use_ascii = ascii_only if ascii_only is not None else not _supports_unicode_bars()
    full = BAR_FILLED_ASCII if use_ascii else BAR_FILLED
    empty = BAR_EMPTY_ASCII if use_ascii else BAR_EMPTY
    return full * filled + empty * (width - filled)


def _status_style(snap: ServiceSnapshot) -> str:
    if snap.status == "failed":
        return "red"
    if snap.status == "done":
        return "green"
    if snap.status == "running":
        return "cyan"
    return "white"


def _phase_short(snap: ServiceSnapshot) -> str:
    if snap.status == "failed":
        return f"{snap.phase}:fail"
    if snap.status == "queued":
        return "queued"
    return snap.phase


def _extra_label(snap: ServiceSnapshot) -> str:
    if snap.status == "done":
        return "READY"
    if snap.status == "failed":
        return "FAIL"
    if snap.status == "queued":
        return "-"
    if snap.attempts > 1:
        return f"iter {snap.attempts}"
    return "run"


def _elapsed_label(snap: ServiceSnapshot, now: float) -> str:
    if snap.started_at is None:
        return "-"
    if snap.finished_at is not None:
        return format_duration(snap.finished_at - snap.started_at)
    return format_duration(now - snap.started_at)


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------
def render_rich(
    snaps: list[ServiceSnapshot],
    aggregate: AggregateStats,
    *,
    title: str | None = None,
    now: float | None = None,
) -> RenderableType:
    """Renderiza panel con totales + lista de servicios."""
    timestamp = now if now is not None else time.time()

    header_table = Table.grid(expand=True, padding=(0, 1))
    header_table.add_column(justify="left", ratio=1)
    header_table.add_column(justify="right", ratio=1)

    total_bar = format_bar(aggregate.percent)
    eta_txt = format_duration(aggregate.eta_seconds)
    total_line = Text.assemble(
        ("Total   ", "bold"),
        (f"{total_bar} ", "cyan"),
        (f"{aggregate.done}/{aggregate.total}   ", "bold"),
        (f"{aggregate.percent}%  ", "bold green" if aggregate.percent == 100 else "bold"),
        (f"eta {eta_txt}", "dim"),
    )
    header_table.add_row(total_line, Text(""))

    body = Table.grid(expand=True, padding=(0, 1))
    body.add_column(style="cyan", no_wrap=True, min_width=16)
    body.add_column(no_wrap=True)
    body.add_column(justify="left", no_wrap=True, min_width=10)
    body.add_column(justify="left", no_wrap=True, min_width=10)
    body.add_column(justify="right", no_wrap=True, min_width=8)

    for snap in snaps:
        style = _status_style(snap)
        bar = format_bar(snap.percent)
        body.add_row(
            Text(snap.name),
            Text(bar, style=style),
            Text(_phase_short(snap), style=style),
            Text(_extra_label(snap), style=style),
            Text(_elapsed_label(snap, timestamp), style="dim"),
        )

    success_pct = round(aggregate.success_rate * 100) if (aggregate.done + aggregate.failed) else 0
    success_txt = (
        f"{aggregate.done}/{aggregate.done + aggregate.failed} ({success_pct}%)"
        if (aggregate.done + aggregate.failed) > 0
        else "-"
    )
    footer = Text.assemble(
        ("Engine: ", "dim"),
        (aggregate.engine, "bold"),
        ("  Iter avg: ", "dim"),
        (f"{aggregate.iter_avg:.1f}", "bold"),
        ("  Success rate: ", "dim"),
        (success_txt, "bold"),
    )

    panel_title = title or f"Batch migration: {aggregate.total} servicios"
    group = Group(header_table, Text(""), body, Text(""), footer)
    return Panel(group, title=panel_title, border_style="cyan", padding=(1, 2))


__all__ = [
    "BAR_EMPTY",
    "BAR_FILLED",
    "BAR_WIDTH",
    "PHASE_ORDER",
    "PHASE_PERCENT",
    "AggregateStats",
    "Dashboard",
    "ServiceSnapshot",
    "format_bar",
    "format_duration",
    "render_rich",
]
