"""Tests de la politica de esfuerzo del orquestador (core/effort_policy.py)."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.effort_policy import (
    ALWAYS_OPUS_TIER,
    DEFAULT_COMPLEXITY,
    EffortProfile,
    effort_for,
    resolve_service_complexity,
)


def test_always_opus_regardless_of_complexity() -> None:
    """Decision owner 2026-05-28: el modelo es opus en las tres complejidades."""
    for c in ("low", "medium", "high"):
        assert effort_for(c).model_tier == ALWAYS_OPUS_TIER == "opus"


def test_retries_escalate_with_complexity() -> None:
    assert effort_for("low").extra_retries == 0
    assert effort_for("medium").extra_retries == 1
    assert effort_for("high").extra_retries == 2


def test_human_gate_only_for_high() -> None:
    assert effort_for("low").needs_human_gate is False
    assert effort_for("medium").needs_human_gate is False
    assert effort_for("high").needs_human_gate is True


def test_reasoning_effort_gradient() -> None:
    assert effort_for("low").reasoning_effort == "high"
    assert effort_for("medium").reasoning_effort == "xhigh"
    assert effort_for("high").reasoning_effort == "xhigh"


def test_unknown_complexity_defaults_to_medium() -> None:
    prof = effort_for("banana")
    assert prof.complexity == DEFAULT_COMPLEXITY
    assert prof == effort_for("medium")
    assert effort_for(None).complexity == DEFAULT_COMPLEXITY


def test_profile_is_frozen() -> None:
    prof = effort_for("high")
    assert isinstance(prof, EffortProfile)


def test_resolve_complexity_from_report(tmp_path: Path) -> None:
    """Lee el campo del COMPLEXITY_<svc>.md generado por clone."""
    ws = tmp_path / "wsclientes0099"
    ws.mkdir()
    (ws / "COMPLEXITY_wsclientes0099.md").write_text(
        "# Analisis\n\n- **Tipo:** `BUS`\n- **Complejidad:** `HIGH`\n",
        encoding="utf-8",
    )
    assert resolve_service_complexity(ws, "wsclientes0099") == "high"


def test_resolve_complexity_case_insensitive(tmp_path: Path) -> None:
    ws = tmp_path / "svc"
    ws.mkdir()
    (ws / "COMPLEXITY_svc.md").write_text("Complejidad: low\n", encoding="utf-8")
    assert resolve_service_complexity(ws, "svc") == "low"


def test_resolve_complexity_defaults_when_no_evidence(tmp_path: Path) -> None:
    ws = tmp_path / "empty"
    ws.mkdir()
    assert resolve_service_complexity(ws, "empty") == DEFAULT_COMPLEXITY


def test_resolve_complexity_ignores_unrelated_lines(tmp_path: Path) -> None:
    """No debe confundir 'low' en otras lineas con el campo Complejidad."""
    ws = tmp_path / "svc"
    ws.mkdir()
    (ws / "COMPLEXITY_svc.md").write_text(
        "- **Riesgo:** low priority overall\n- **Complejidad:** `HIGH`\n",
        encoding="utf-8",
    )
    assert resolve_service_complexity(ws, "svc") == "high"
