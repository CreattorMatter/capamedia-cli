"""Tests para `capamedia status`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import typer

from capamedia_cli.commands.status import (
    StatusCheck,
    _check_artifacts_token,
    _check_azure_pat,
    _check_binary,
    _check_codex_model_config,
    _check_engines,
    status_command,
)

# ---------------------------------------------------------------------------
# StatusCheck
# ---------------------------------------------------------------------------


def test_status_check_dataclass() -> None:
    c = StatusCheck(name="x", ok=True, detail="all good")
    assert c.required is True
    assert c.ok is True


# ---------------------------------------------------------------------------
# _check_binary
# ---------------------------------------------------------------------------


def test_check_binary_not_in_path() -> None:
    with patch("capamedia_cli.commands.status.shutil.which", return_value=None):
        result = _check_binary("nonexistent")
    assert result.ok is False
    assert "PATH" in result.detail


def test_check_binary_found_without_version() -> None:
    with patch(
        "capamedia_cli.commands.status.shutil.which",
        return_value="/usr/bin/git",
    ):
        result = _check_binary("git")
    assert result.ok is True
    assert "encontrado" in result.detail


def test_check_binary_with_version_output() -> None:
    class _Proc:
        returncode = 0
        stdout = "git version 2.47.1.windows.2\n"
        stderr = ""

    with (
        patch(
            "capamedia_cli.commands.status.shutil.which",
            return_value="/usr/bin/git",
        ),
        patch(
            "capamedia_cli.commands.status.subprocess.run",
            return_value=_Proc(),
        ),
    ):
        result = _check_binary("git", ["--version"])
    assert result.ok is True
    assert "2.47.1" in result.detail


# ---------------------------------------------------------------------------
# _check_engines — nunca usa OPENAI_API_KEY
# ---------------------------------------------------------------------------


def test_check_engines_ok_when_claude_available() -> None:
    with patch(
        "capamedia_cli.commands.status.available_engines",
        return_value={
            "claude": (True, "claude 0.5.0"),
            "codex": (False, "no login"),
        },
    ):
        result = _check_engines()
    assert result.ok is True
    assert "claude=OK" in result.detail
    assert "codex=no" in result.detail


def test_check_engines_ok_when_only_codex_available() -> None:
    with patch(
        "capamedia_cli.commands.status.available_engines",
        return_value={
            "claude": (False, "no binary"),
            "codex": (True, "codex 0.1.0"),
        },
    ):
        result = _check_engines()
    assert result.ok is True


def test_check_engines_fail_when_no_engine_available() -> None:
    with patch(
        "capamedia_cli.commands.status.available_engines",
        return_value={
            "claude": (False, "no"),
            "codex": (False, "no"),
        },
    ):
        result = _check_engines()
    assert result.ok is False


def test_check_engines_never_looks_at_openai_api_key(monkeypatch) -> None:
    """Prueba que el check de engines NO dependa de OPENAI_API_KEY."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with patch(
        "capamedia_cli.commands.status.available_engines",
        return_value={"claude": (True, "ok"), "codex": (False, "no")},
    ):
        result = _check_engines()

    assert result.ok is True
    assert "OPENAI" not in result.detail.upper()


def test_check_codex_model_config_detects_gpt55_xhigh(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text(
        'model = "gpt-5.5"\nmodel_reasoning_effort = "xhigh"\n',
        encoding="utf-8",
    )

    with patch("capamedia_cli.commands.status.Path.home", return_value=tmp_path):
        result = _check_codex_model_config()

    assert result.ok is True
    assert result.required is False
    assert "gpt-5.5" in result.detail
    assert "xhigh" in result.detail


def test_check_codex_model_config_marks_legacy_defaults_optional(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text(
        'model = "gpt-5.1-codex"\nmodel_reasoning_effort = "high"\n',
        encoding="utf-8",
    )

    with patch("capamedia_cli.commands.status.Path.home", return_value=tmp_path):
        result = _check_codex_model_config()

    assert result.ok is False
    assert result.required is False
    assert "gpt-5.1-codex" in result.detail


# ---------------------------------------------------------------------------
# _check_azure_pat / _check_artifacts_token
# ---------------------------------------------------------------------------


def test_azure_pat_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CAPAMEDIA_AZDO_PAT", "ghp_xxxxxx")
    monkeypatch.delenv("AZURE_DEVOPS_EXT_PAT", raising=False)
    result = _check_azure_pat()
    assert result.ok is True
    assert "CAPAMEDIA_AZDO_PAT" in result.detail


def test_azure_pat_missing(monkeypatch) -> None:
    monkeypatch.delenv("CAPAMEDIA_AZDO_PAT", raising=False)
    monkeypatch.delenv("AZURE_DEVOPS_EXT_PAT", raising=False)
    result = _check_azure_pat()
    assert result.ok is False
    assert "sin env var" in result.detail


def test_artifacts_token_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CAPAMEDIA_ARTIFACT_TOKEN", "xxxxxx")
    monkeypatch.delenv("ARTIFACT_TOKEN", raising=False)
    result = _check_artifacts_token()
    assert result.ok is True
    assert "CAPAMEDIA_ARTIFACT_TOKEN" in result.detail


def test_artifacts_token_alternative_env(monkeypatch) -> None:
    monkeypatch.delenv("CAPAMEDIA_ARTIFACT_TOKEN", raising=False)
    monkeypatch.setenv("ARTIFACT_TOKEN", "xxxx")
    result = _check_artifacts_token()
    assert result.ok is True


def test_artifacts_token_missing(monkeypatch) -> None:
    monkeypatch.delenv("CAPAMEDIA_ARTIFACT_TOKEN", raising=False)
    monkeypatch.delenv("ARTIFACT_TOKEN", raising=False)
    result = _check_artifacts_token()
    assert result.ok is False


# ---------------------------------------------------------------------------
# status_command integracion
# ---------------------------------------------------------------------------


def test_status_command_exits_1_when_required_missing() -> None:
    """Si hay al menos un required ok=False -> exit 1."""
    with (
        patch(
            "capamedia_cli.commands.status._check_binary",
            return_value=StatusCheck("x", ok=False, detail="missing"),
        ),
        patch(
            "capamedia_cli.commands.status._check_engines",
            return_value=StatusCheck("engine", ok=False, detail="none"),
        ),
        patch(
            "capamedia_cli.commands.status._check_azure_pat",
            return_value=StatusCheck("pat", ok=False, detail="none"),
        ),
        patch(
            "capamedia_cli.commands.status._check_artifacts_token",
            return_value=StatusCheck("art", ok=False, detail="none"),
        ),
        patch(
            "capamedia_cli.commands.status._check_fabrics_mcp",
            return_value=StatusCheck("fab", ok=False, detail="none"),
        ),
        patch(
            "capamedia_cli.commands.status._check_java21",
            return_value=StatusCheck("java", ok=False, detail="none"),
        ),
    ):
        with pytest.raises(typer.Exit) as exc:
            status_command()
        assert exc.value.exit_code == 1


def test_status_command_no_exit_when_all_ok() -> None:
    """Si todos los checks son OK -> termina sin raise."""
    ok = StatusCheck("x", ok=True, detail="all good")
    with (
        patch("capamedia_cli.commands.status._check_binary", return_value=ok),
        patch("capamedia_cli.commands.status._check_engines", return_value=ok),
        patch("capamedia_cli.commands.status._check_azure_pat", return_value=ok),
        patch("capamedia_cli.commands.status._check_artifacts_token", return_value=ok),
        patch("capamedia_cli.commands.status._check_fabrics_mcp", return_value=ok),
        patch("capamedia_cli.commands.status._check_java21", return_value=ok),
    ):
        # No raise
        status_command()
