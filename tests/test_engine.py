"""Tests para core/engine.py (ClaudeEngine + CodexEngine + select_engine)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from capamedia_cli.core.engine import (
    ClaudeEngine,
    CodexEngine,
    EngineInput,
    EngineResult,
    _detect_rate_limit,
    _last_json_block,
    available_engines,
    select_engine,
)

# ---------------------------------------------------------------------------
# _detect_rate_limit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected_hit,expected_retry",
    [
        ("", False, None),
        ("random stderr", False, None),
        ("rate_limit_error: 429", True, None),
        ("429 Too Many Requests", True, None),
        ("quota exceeded for your plan", True, None),
        ("rate limit hit, retry-after: 120", True, 120),
        ("Retry After: 45", True, 45),
        ("usage limit reached", True, None),
    ],
)
def test_detect_rate_limit(text: str, expected_hit: bool, expected_retry: int | None) -> None:
    hit, retry = _detect_rate_limit(text)
    assert hit is expected_hit
    assert retry == expected_retry


# ---------------------------------------------------------------------------
# _last_json_block
# ---------------------------------------------------------------------------


def test_last_json_block_empty() -> None:
    assert _last_json_block("") is None


def test_last_json_block_from_backticks() -> None:
    text = 'Aqui el resultado:\n```json\n{"a": 1}\n```\nFin.'
    assert json.loads(_last_json_block(text)) == {"a": 1}


def test_last_json_block_multiple_blocks_returns_last() -> None:
    text = '```json\n{"a": 1}\n```\nluego\n```json\n{"b": 2}\n```'
    assert json.loads(_last_json_block(text)) == {"b": 2}


def test_last_json_block_fallback_balanced_braces() -> None:
    text = 'prefix noise {"ok": true} suffix'
    assert json.loads(_last_json_block(text)) == {"ok": True}


# ---------------------------------------------------------------------------
# CodexEngine
# ---------------------------------------------------------------------------


def test_codex_engine_unavailable_when_binary_missing() -> None:
    engine = CodexEngine(bin_path="nonexistent-codex-binary-xyz")
    ok, reason = engine.is_available()
    assert ok is False
    assert "no encontrado" in reason.lower() or "not found" in reason.lower()


def test_codex_engine_unavailable_when_binary_access_denied() -> None:
    engine = CodexEngine(bin_path="codex")
    with patch("capamedia_cli.core.engine.subprocess.run", side_effect=PermissionError("denied")):
        ok, reason = engine.is_available()

    assert ok is False
    assert "no ejecutable" in reason


def test_codex_engine_run_headless_missing_binary(tmp_path: Path) -> None:
    engine = CodexEngine(bin_path="nonexistent-codex-binary-xyz")
    einput = EngineInput(
        workspace=tmp_path,
        prompt="do the thing",
        schema_path=None,
        output_path=tmp_path / "out.json",
        timeout_seconds=5,
    )
    result = engine.run_headless(einput)
    assert result.exit_code == 127
    assert "no encontrado" in (result.failure_reason or "").lower()


def test_codex_engine_run_headless_success(tmp_path: Path) -> None:
    engine = CodexEngine(bin_path="codex")
    einput = EngineInput(
        workspace=tmp_path,
        prompt="do the thing",
        schema_path=None,
        output_path=tmp_path / "out.json",
        timeout_seconds=5,
    )

    fake_completed = subprocess.CompletedProcess(
        args=["codex"], returncode=0, stdout="ok", stderr=""
    )
    with patch("capamedia_cli.core.engine.subprocess.run", return_value=fake_completed):
        result = engine.run_headless(einput)

    assert result.exit_code == 0
    assert result.rate_limited is False


def test_codex_engine_run_headless_forwards_model_and_reasoning(tmp_path: Path) -> None:
    engine = CodexEngine(bin_path="codex")
    einput = EngineInput(
        workspace=tmp_path,
        prompt="do the thing",
        schema_path=None,
        output_path=tmp_path / "out.json",
        timeout_seconds=5,
        model="gpt-5.5",
        reasoning_effort="xhigh",
    )
    fake_completed = subprocess.CompletedProcess(
        args=["codex"], returncode=0, stdout="ok", stderr=""
    )

    with patch("capamedia_cli.core.engine.subprocess.run", return_value=fake_completed) as run:
        engine.run_headless(einput)

    cmd = run.call_args.args[0]
    assert cmd[0].lower().endswith(("codex", "codex.cmd", "codex.exe"))
    assert cmd[1] == "exec"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-5.5"
    assert "-c" in cmd
    assert 'model_reasoning_effort="xhigh"' in cmd


def test_codex_engine_detects_rate_limit_in_stderr(tmp_path: Path) -> None:
    engine = CodexEngine(bin_path="codex")
    einput = EngineInput(
        workspace=tmp_path,
        prompt="x",
        schema_path=None,
        output_path=tmp_path / "o.json",
        timeout_seconds=5,
    )
    fake = subprocess.CompletedProcess(
        args=["codex"], returncode=1, stdout="", stderr="429 rate limit hit, retry-after: 60"
    )
    with patch("capamedia_cli.core.engine.subprocess.run", return_value=fake):
        result = engine.run_headless(einput)

    assert result.rate_limited is True
    assert result.retry_after_seconds == 60


# ---------------------------------------------------------------------------
# ClaudeEngine
# ---------------------------------------------------------------------------


def test_claude_engine_unavailable_when_binary_missing() -> None:
    engine = ClaudeEngine(bin_path="nonexistent-claude-binary-xyz")
    ok, _ = engine.is_available()
    assert ok is False


def test_claude_engine_extracts_structured_output(tmp_path: Path) -> None:
    """Claude --output-format json devuelve envelope con `result` string que tiene JSON."""
    output_path = tmp_path / "final.json"
    envelope = {
        "type": "result",
        "result": 'blah blah\n```json\n{"status":"ok","summary":"done"}\n```\nend',
    }
    ClaudeEngine._extract_structured_output(json.dumps(envelope), output_path)
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "status": "ok",
        "summary": "done",
    }


def test_claude_engine_ignores_invalid_envelope(tmp_path: Path) -> None:
    output_path = tmp_path / "o.json"
    ClaudeEngine._extract_structured_output("", output_path)
    assert not output_path.exists()


def test_claude_engine_injects_schema_into_prompt(tmp_path: Path) -> None:
    engine = ClaudeEngine(bin_path="claude")
    schema_file = tmp_path / "schema.json"
    schema_file.write_text('{"type":"object"}', encoding="utf-8")
    enriched = engine._prompt_with_schema("original prompt", schema_file)
    assert "original prompt" in enriched
    assert "Formato de salida OBLIGATORIO" in enriched
    assert '{"type":"object"}' in enriched


def test_claude_engine_no_schema_passthrough() -> None:
    engine = ClaudeEngine(bin_path="claude")
    assert engine._prompt_with_schema("hello", None) == "hello"


# ---------------------------------------------------------------------------
# select_engine
# ---------------------------------------------------------------------------


def _mock_engine_available(available: bool, reason: str = "ok") -> MagicMock:
    m = MagicMock()
    m.is_available.return_value = (available, reason)
    return m


def test_select_engine_explicit_claude_available() -> None:
    with patch("capamedia_cli.core.engine.ClaudeEngine") as MockCE:
        MockCE.return_value.is_available.return_value = (True, "claude ok")
        engine = select_engine("claude")
        assert engine is MockCE.return_value


def test_select_engine_explicit_claude_unavailable_raises() -> None:
    with patch("capamedia_cli.core.engine.ClaudeEngine") as MockCE:
        MockCE.return_value.is_available.return_value = (False, "no claude")
        with pytest.raises(RuntimeError, match="claude no disponible"):
            select_engine("claude")


def test_select_engine_auto_prefers_claude() -> None:
    with (
        patch("capamedia_cli.core.engine.ClaudeEngine") as MockClaude,
        patch("capamedia_cli.core.engine.CodexEngine") as MockCodex,
    ):
        MockClaude.return_value.is_available.return_value = (True, "ok")
        MockCodex.return_value.is_available.return_value = (True, "ok")
        engine = select_engine("auto")
        assert engine is MockClaude.return_value


def test_select_engine_auto_falls_back_to_codex() -> None:
    with (
        patch("capamedia_cli.core.engine.ClaudeEngine") as MockClaude,
        patch("capamedia_cli.core.engine.CodexEngine") as MockCodex,
    ):
        MockClaude.return_value.is_available.return_value = (False, "no claude")
        MockCodex.return_value.is_available.return_value = (True, "ok")
        engine = select_engine("auto")
        assert engine is MockCodex.return_value


def test_select_engine_auto_no_engines_available() -> None:
    with (
        patch("capamedia_cli.core.engine.ClaudeEngine") as MockClaude,
        patch("capamedia_cli.core.engine.CodexEngine") as MockCodex,
    ):
        MockClaude.return_value.is_available.return_value = (False, "x")
        MockCodex.return_value.is_available.return_value = (False, "y")
        with pytest.raises(RuntimeError, match="ningun engine disponible"):
            select_engine("auto")


def test_select_engine_invalid_name_raises() -> None:
    with pytest.raises(ValueError):
        select_engine("gpt-5-turbo")


def test_available_engines_reports_both() -> None:
    with (
        patch("capamedia_cli.core.engine.ClaudeEngine") as MockClaude,
        patch("capamedia_cli.core.engine.CodexEngine") as MockCodex,
    ):
        MockClaude.return_value.is_available.return_value = (True, "claude X")
        MockCodex.return_value.is_available.return_value = (False, "codex missing")
        status = available_engines()
        assert status["claude"] == (True, "claude X")
        assert status["codex"] == (False, "codex missing")


# ---------------------------------------------------------------------------
# EngineResult constructor smoke
# ---------------------------------------------------------------------------


def test_engine_result_basic() -> None:
    r = EngineResult(exit_code=0, stdout="ok", stderr="", duration_seconds=1.0)
    assert r.exit_code == 0
    assert r.rate_limited is False
    assert r.retry_after_seconds is None
    assert r.failure_reason is None
