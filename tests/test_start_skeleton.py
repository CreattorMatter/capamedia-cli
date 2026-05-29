"""Tests del esqueleto de `capamedia start` (Fase 1 del wizard).

Verifica que la fachada NO-interactiva orqueste el pipeline existente con los
kwargs correctos (Opus forzado), persista las decisiones en wizard.json y
propague --resume. Mockea _process_pipeline_service: la Fase 1 es cableado, no
logica nueva.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import capamedia_cli.commands.batch as batch_mod
import capamedia_cli.commands.start as start_mod
from capamedia_cli.commands.batch import BatchRow
from capamedia_cli.commands.start import load_wizard_decisions, start_command


class _FakeEngine:
    name = "claude"
    subscription_type = "max"


@pytest.fixture
def captured(monkeypatch, tmp_path):
    """Mockea el backbone y captura los kwargs con que se invoca el pipeline."""
    grabbed: dict = {}

    def fake_pipeline(service, root, schema_path, **kwargs):
        grabbed["service"] = service
        grabbed["root"] = root
        grabbed["schema_path"] = schema_path
        grabbed.update(kwargs)
        return BatchRow(service, "ok", "pipeline ok (mock)", {"project": "tnd-msa-sp-x"})

    monkeypatch.setattr(batch_mod, "_process_pipeline_service", fake_pipeline)
    monkeypatch.setattr(batch_mod, "_ensure_migrate_schema", lambda ws: ws / "schema.json")
    monkeypatch.setattr(start_mod, "select_engine", lambda *a, **k: _FakeEngine())
    monkeypatch.setattr(start_mod, "engine_from_env", lambda: None)
    return grabbed


def test_start_forces_opus_and_orchestrates_pipeline(captured, tmp_path):
    start_command(service="wsclientes0076", namespace="tnd", root=tmp_path)

    assert captured["service"] == "wsclientes0076"
    assert captured["namespace"] == "tnd"
    # Decision owner: SIEMPRE Opus 4.8, el wizard no pregunta modelo.
    assert captured["model"] == "claude-opus-4-8"
    assert captured["resume"] is False
    assert "claude" in captured["harnesses"]
    assert captured["group_id"] == "com.pichincha.sp"
    # reasoning lo ignora claude/opus en Fase 1.
    assert captured["reasoning_effort"] is None


def test_start_persists_wizard_decisions(captured, tmp_path):
    start_command(service="wsclientes0099", namespace="csg", branch="feature/dev-X", root=tmp_path)

    decisions = load_wizard_decisions(tmp_path / "wsclientes0099")
    assert decisions["service"] == "wsclientes0099"
    assert decisions["namespace"] == "csg"
    assert decisions["branch"] == "feature/dev-X"
    assert decisions["model"] == "claude-opus-4-8"
    assert decisions["engine"] == "claude"
    assert decisions["phase"] == "1-skeleton"


def test_start_branch_persisted_but_not_passed_to_pipeline(captured, tmp_path):
    """Fase 1: el branch se registra pero su integracion real es una fase posterior."""
    start_command(service="wstecnicos0006", namespace="tct", branch="feature/x", root=tmp_path)

    # El pipeline NO recibe branch (clone_service no lo soporta aun).
    assert "branch" not in captured
    # Pero queda persistido para la fase que lo use.
    assert load_wizard_decisions(tmp_path / "wstecnicos0006")["branch"] == "feature/x"


def test_start_resume_propagates(captured, tmp_path):
    start_command(service="wsclientes0076", namespace="tnd", root=tmp_path, resume=True)
    assert captured["resume"] is True


def test_start_exits_nonzero_on_pipeline_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(
        batch_mod,
        "_process_pipeline_service",
        lambda service, root, schema_path, **kw: BatchRow(service, "fail", "clone failed", {}),
    )
    monkeypatch.setattr(batch_mod, "_ensure_migrate_schema", lambda ws: ws / "schema.json")
    monkeypatch.setattr(start_mod, "select_engine", lambda *a, **k: _FakeEngine())
    monkeypatch.setattr(start_mod, "engine_from_env", lambda: None)

    import typer

    with pytest.raises(typer.Exit):
        start_command(service="wsx0001", namespace="tnd", root=tmp_path)
