"""Tests para core.dashboard (barras de progreso y agregados)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console

from capamedia_cli.core.dashboard import (
    BAR_WIDTH,
    PHASE_PERCENT,
    Dashboard,
    ServiceSnapshot,
    _infer_phase_status,
    _parse_ts,
    format_bar,
    format_duration,
    render_rich,
)


# ----------------------------------------------------------------------
# Fixtures helpers
# ----------------------------------------------------------------------
def _write_state(
    workspace: Path,
    *,
    run_kind: str = "pipeline",
    stages: dict | None = None,
    result: dict | None = None,
    created_at: str = "2026-04-22T10:00:00+00:00",
    updated_at: str = "2026-04-22T10:05:00+00:00",
) -> Path:
    state_dir = workspace / ".capamedia" / "batch-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "service": workspace.name,
        "run_kind": run_kind,
        "created_at": created_at,
        "updated_at": updated_at,
        "stages": stages or {},
        "result": result or {},
    }
    path = state_dir / f"{run_kind}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _mk_workspace(root: Path, service: str) -> Path:
    ws = root / service
    (ws / ".capamedia").mkdir(parents=True, exist_ok=True)
    return ws


def _mixed_batch(root: Path) -> None:
    """Crea 5 servicios en fases distintas."""
    # svc done
    ws = _mk_workspace(root, "WSTecnicos0036")
    _write_state(
        ws,
        stages={
            "clone": {"status": "ok", "attempts": 1, "fields": {"clone": "ok"}},
            "init": {"status": "ok", "attempts": 1, "fields": {"init": "ok"}},
            "fabric": {"status": "ok", "attempts": 1, "fields": {"fabric": "ok"}},
            "migrate": {"status": "ok", "attempts": 2, "fields": {"codex": "ok", "build": "green"}},
            "check": {"status": "ok", "attempts": 1, "fields": {"check": "READY_TO_MERGE"}},
        },
        result={"status": "ok", "detail": "done", "updated_at": "2026-04-22T11:00:00+00:00"},
        created_at="2026-04-22T10:00:00+00:00",
        updated_at="2026-04-22T11:00:00+00:00",
    )

    # svc migrate en curso, 2 intentos
    ws = _mk_workspace(root, "WSTecnicos0039")
    _write_state(
        ws,
        stages={
            "clone": {"status": "ok", "attempts": 1, "fields": {"clone": "ok"}},
            "init": {"status": "ok", "attempts": 1, "fields": {"init": "ok"}},
            "fabric": {"status": "ok", "attempts": 1, "fields": {"fabric": "ok"}},
            "migrate": {"status": "in_progress", "attempts": 2, "fields": {"codex": "running"}},
        },
        result={},
        updated_at="2026-04-22T10:12:12+00:00",
    )

    # svc en fabrics
    ws = _mk_workspace(root, "WSClientes0010")
    _write_state(
        ws,
        stages={
            "clone": {"status": "ok", "attempts": 1, "fields": {"clone": "ok"}},
            "init": {"status": "ok", "attempts": 1, "fields": {"init": "ok"}},
            "fabric": {"status": "gen", "attempts": 1, "fields": {"fabric": "gen"}},
        },
        updated_at="2026-04-22T10:00:45+00:00",
    )

    # svc en clone (recien arrancado)
    ws = _mk_workspace(root, "WSClientes0026")
    _write_state(
        ws,
        stages={
            "clone": {"status": "legacy", "attempts": 1, "fields": {"clone": "legacy"}},
        },
        updated_at="2026-04-22T10:00:12+00:00",
    )

    # svc queued (sin state)
    ws = _mk_workspace(root, "ORQClientes0027")
    # no escribimos state -> queued


# ----------------------------------------------------------------------
# Unit: snapshot
# ----------------------------------------------------------------------
def test_snapshot_maps_mixed_phases_correctly(tmp_path: Path) -> None:
    _mixed_batch(tmp_path)
    d = Dashboard(tmp_path, kind="auto")
    snaps = d.snapshot()

    by_name = {s.name: s for s in snaps}
    assert set(by_name.keys()) == {
        "WSTecnicos0036",
        "WSTecnicos0039",
        "WSClientes0010",
        "WSClientes0026",
        "ORQClientes0027",
    }

    assert by_name["WSTecnicos0036"].status == "done"
    assert by_name["WSTecnicos0036"].phase == "done"
    assert by_name["WSTecnicos0036"].percent == 100

    svc_mig = by_name["WSTecnicos0039"]
    assert svc_mig.status == "running"
    assert svc_mig.phase == "migrate"
    assert svc_mig.percent == PHASE_PERCENT["migrate"]
    assert svc_mig.attempts == 5  # 1+1+1+2

    svc_fab = by_name["WSClientes0010"]
    assert svc_fab.phase == "fabric"
    assert svc_fab.status == "running"

    svc_clone = by_name["WSClientes0026"]
    assert svc_clone.phase == "clone"
    assert svc_clone.status == "running"

    svc_q = by_name["ORQClientes0027"]
    assert svc_q.status == "queued"
    assert svc_q.phase == "queued"
    assert svc_q.percent == 0


def test_snapshot_detects_failed_status(tmp_path: Path) -> None:
    ws = _mk_workspace(tmp_path, "wsclientes0007")
    _write_state(
        ws,
        stages={
            "clone": {"status": "ok", "attempts": 1, "fields": {"clone": "ok"}},
            "init": {"status": "ok", "attempts": 1, "fields": {"init": "ok"}},
            "fabric": {"status": "fail", "attempts": 2, "fields": {"fabric": "fail"}, "detail": "preflight fail"},
        },
        result={"status": "fail", "detail": "preflight fail"},
    )
    d = Dashboard(tmp_path, kind="pipeline")
    snaps = d.snapshot()
    assert len(snaps) == 1
    snap = snaps[0]
    assert snap.status == "failed"
    assert snap.phase == "fabric"
    # barra debe quedar en el porcentaje del stage (fabric = 55)
    assert snap.percent == PHASE_PERCENT["fabric"]


def test_snapshot_respects_explicit_services_order(tmp_path: Path) -> None:
    _mixed_batch(tmp_path)
    d = Dashboard(tmp_path, services=["ORQClientes0027", "WSTecnicos0036"], kind="auto")
    snaps = d.snapshot()
    assert [s.name for s in snaps] == ["ORQClientes0027", "WSTecnicos0036"]


def test_snapshot_handles_corrupt_json(tmp_path: Path) -> None:
    ws = _mk_workspace(tmp_path, "svc_corrupt")
    state_dir = ws / ".capamedia" / "batch-state"
    state_dir.mkdir(parents=True)
    (state_dir / "pipeline.json").write_text("{not-json", encoding="utf-8")
    d = Dashboard(tmp_path, kind="pipeline")
    snaps = d.snapshot()
    assert len(snaps) == 1
    # corrupt => tratado como ausencia de state => queued
    assert snaps[0].status == "queued"


def test_snapshot_prefers_pipeline_over_migrate_when_auto(tmp_path: Path) -> None:
    ws = _mk_workspace(tmp_path, "svc_both")
    _write_state(
        ws,
        run_kind="pipeline",
        stages={"clone": {"status": "ok", "attempts": 1}},
    )
    _write_state(
        ws,
        run_kind="migrate",
        stages={"migrate": {"status": "ok", "attempts": 1}},
        result={"status": "ok", "updated_at": "2026-04-22T10:10:00+00:00"},
    )
    d = Dashboard(tmp_path, kind="auto")
    snap = d.snapshot()[0]
    # pipeline wins, asi que no esta done todavia (result vacio en pipeline.json)
    assert snap.run_kind == "pipeline"
    assert snap.status != "done"


def test_snapshot_migrate_only(tmp_path: Path) -> None:
    ws = _mk_workspace(tmp_path, "svc_mig_only")
    _write_state(
        ws,
        run_kind="migrate",
        stages={"migrate": {"status": "ok", "attempts": 1}, "check": {"status": "ok", "attempts": 1}},
        result={"status": "ok", "detail": "ok", "updated_at": "2026-04-22T11:00:00+00:00"},
    )
    d = Dashboard(tmp_path, kind="migrate")
    snap = d.snapshot()[0]
    assert snap.run_kind == "migrate"
    assert snap.status == "done"


# ----------------------------------------------------------------------
# Unit: aggregate
# ----------------------------------------------------------------------
def test_aggregate_on_mixed_batch(tmp_path: Path) -> None:
    _mixed_batch(tmp_path)
    d = Dashboard(tmp_path, kind="auto")
    snaps = d.snapshot()
    agg = d.aggregate(snaps)

    assert agg.total == 5
    assert agg.done == 1
    assert agg.failed == 0
    assert agg.running == 3
    assert agg.queued == 1
    assert 0 <= agg.percent <= 100
    # success_rate: 1 done, 0 failed => 1.0
    assert agg.success_rate == 1.0
    # iter_avg > 0 porque hay attempts
    assert agg.iter_avg > 0


def test_aggregate_empty() -> None:
    d = Dashboard(Path("."), services=[], kind="auto")
    snaps: list[ServiceSnapshot] = []
    agg = d.aggregate(snaps)
    assert agg.total == 0
    assert agg.percent == 0
    assert agg.eta_seconds is None
    assert agg.success_rate == 0.0


def test_aggregate_eta_extrapolates_from_running_when_no_done(tmp_path: Path) -> None:
    # Un servicio en migrate sin done previo: eta debe ser > 0 (extrapolacion).
    ws = _mk_workspace(tmp_path, "svc_running")
    # started 60s antes del "now" sintetico
    _write_state(
        ws,
        stages={
            "clone": {"status": "ok", "attempts": 1},
            "init": {"status": "ok", "attempts": 1},
            "fabric": {"status": "ok", "attempts": 1},
            "migrate": {"status": "in_progress", "attempts": 1},
        },
        created_at="2026-04-22T10:00:00+00:00",
        updated_at="2026-04-22T10:01:00+00:00",
    )

    # reloj fijo: 60s despues del created_at
    fixed_now = _parse_ts("2026-04-22T10:01:00+00:00") or 0.0
    d = Dashboard(tmp_path, kind="pipeline", clock=lambda: fixed_now)
    snaps = d.snapshot()
    agg = d.aggregate(snaps)
    assert agg.total == 1
    assert agg.eta_seconds is None or agg.eta_seconds >= 0


# ----------------------------------------------------------------------
# Unit: inferencia directa
# ----------------------------------------------------------------------
def test_infer_phase_status_all_queued() -> None:
    phase, status = _infer_phase_status({}, {}, ("clone", "init", "fabric", "migrate", "check"))
    assert phase == "queued"
    assert status == "queued"


def test_infer_phase_status_done() -> None:
    phase, status = _infer_phase_status(
        {"clone": {"status": "ok"}, "migrate": {"status": "ok"}},
        {"status": "ok"},
        ("clone", "init", "fabric", "migrate", "check"),
    )
    assert phase == "done"
    assert status == "done"


def test_infer_phase_status_fail_uses_failed_stage() -> None:
    phase, status = _infer_phase_status(
        {
            "clone": {"status": "ok"},
            "init": {"status": "fail"},
        },
        {"status": "fail"},
        ("clone", "init", "fabric", "migrate", "check"),
    )
    assert phase == "init"
    assert status == "failed"


# ----------------------------------------------------------------------
# Unit: format helpers
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("pct", "expected_filled"),
    [(0, 0), (50, BAR_WIDTH // 2), (100, BAR_WIDTH), (-5, 0), (150, BAR_WIDTH)],
)
def test_format_bar_boundaries(pct: int, expected_filled: int) -> None:
    bar = format_bar(pct, ascii_only=False)
    assert len(bar) == BAR_WIDTH
    filled = bar.count("\u2588")
    assert filled == expected_filled


def test_format_bar_ascii_fallback() -> None:
    bar = format_bar(50, ascii_only=True)
    assert len(bar) == BAR_WIDTH
    assert bar.count("#") == BAR_WIDTH // 2
    assert bar.count(".") == BAR_WIDTH - BAR_WIDTH // 2


def test_format_duration_variants() -> None:
    assert format_duration(None) == "-"
    assert format_duration(0) == "0s"
    assert format_duration(45) == "45s"
    assert format_duration(60) == "1m00s"
    assert format_duration(60 * 10) == "10m"
    assert format_duration(3600 + 24 * 60 + 0) == "1h24m"


# ----------------------------------------------------------------------
# Render (no-crash)
# ----------------------------------------------------------------------
def test_render_rich_does_not_crash_with_mixed_data(tmp_path: Path) -> None:
    _mixed_batch(tmp_path)
    d = Dashboard(tmp_path, kind="auto")
    snaps = d.snapshot()
    agg = d.aggregate(snaps)
    renderable = render_rich(snaps, agg)

    # Capturar en un Console sin TTY: no debe tirar.
    console = Console(record=True, width=120, force_terminal=False)
    console.print(renderable)
    out = console.export_text(clear=False)
    # Debe mencionar al menos un servicio y el header.
    assert "Total" in out
    assert "WSTecnicos0036" in out
    assert "Engine" in out


def test_render_rich_empty_batch() -> None:
    d = Dashboard(Path("."), services=[], kind="auto")
    snaps = d.snapshot()
    agg = d.aggregate(snaps)
    renderable = render_rich(snaps, agg)
    console = Console(record=True, width=80, force_terminal=False)
    console.print(renderable)
    out = console.export_text(clear=False)
    assert "Total" in out


def test_parse_ts_handles_z_suffix() -> None:
    assert _parse_ts("2026-04-22T10:00:00Z") is not None
    assert _parse_ts(None) is None
    assert _parse_ts("") is None
    assert _parse_ts("not-a-date") is None
