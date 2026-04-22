"""Tests para los comandos `capamedia version` y `capamedia uninstall`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import typer

from capamedia_cli.commands.uninstall import (
    _has_pip_install,
    _has_uv_tool,
    _purge_user_files,
    uninstall_command,
)
from capamedia_cli.commands.version import version_command

# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


def test_version_command_prints_version(capsys) -> None:
    """Smoke: version_command no crashea y menciona la version."""
    from capamedia_cli import __version__

    version_command()
    out = capsys.readouterr().out
    assert __version__ in out
    assert "capamedia-cli" in out


# ---------------------------------------------------------------------------
# uninstall - detection
# ---------------------------------------------------------------------------


def test_has_uv_tool_true_when_listed() -> None:
    class _Proc:
        returncode = 0
        stdout = "capamedia-cli v0.13.0 (/usr/local/bin/capamedia)\n"

    with patch(
        "capamedia_cli.commands.uninstall.subprocess.run",
        return_value=_Proc(),
    ):
        assert _has_uv_tool() is True


def test_has_uv_tool_false_when_missing() -> None:
    class _Proc:
        returncode = 0
        stdout = "some-other-tool\n"

    with patch(
        "capamedia_cli.commands.uninstall.subprocess.run",
        return_value=_Proc(),
    ):
        assert _has_uv_tool() is False


def test_has_uv_tool_false_when_uv_not_found() -> None:
    with patch(
        "capamedia_cli.commands.uninstall.subprocess.run",
        side_effect=FileNotFoundError(),
    ):
        assert _has_uv_tool() is False


def test_has_pip_install_true() -> None:
    class _Proc:
        returncode = 0
        stdout = "Name: capamedia-cli\nVersion: 0.13.0\n"

    with patch(
        "capamedia_cli.commands.uninstall.subprocess.run",
        return_value=_Proc(),
    ):
        assert _has_pip_install() is True


def test_has_pip_install_false() -> None:
    class _Proc:
        returncode = 1
        stdout = ""

    with patch(
        "capamedia_cli.commands.uninstall.subprocess.run",
        return_value=_Proc(),
    ):
        assert _has_pip_install() is False


# ---------------------------------------------------------------------------
# uninstall - purge
# ---------------------------------------------------------------------------


def test_purge_removes_mcp_json_in_cwd(tmp_path: Path, monkeypatch) -> None:
    """Simula que ./.mcp.json existe en cwd y se borra."""
    monkeypatch.chdir(tmp_path)
    mcp = tmp_path / ".mcp.json"
    mcp.write_text('{"mcpServers": {}}', encoding="utf-8")
    assert mcp.exists()

    # Mock Path.home() a un dir vacio para no tocar configs reales
    with patch("capamedia_cli.commands.uninstall.Path.home", return_value=tmp_path / "fakehome"):
        deleted = _purge_user_files(dry_run=False)

    assert str(mcp) in deleted
    assert not mcp.exists()


def test_purge_dry_run_does_not_delete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    mcp = tmp_path / ".mcp.json"
    mcp.write_text("{}", encoding="utf-8")

    with patch("capamedia_cli.commands.uninstall.Path.home", return_value=tmp_path / "fakehome"):
        deleted = _purge_user_files(dry_run=True)

    # Dry-run: path listado, pero el archivo sigue existiendo
    assert str(mcp) in deleted
    assert mcp.exists()


# ---------------------------------------------------------------------------
# uninstall - command flow
# ---------------------------------------------------------------------------


def test_uninstall_exits_zero_when_nothing_installed() -> None:
    """Sin uv ni pip install, no deberia levantar excepcion si no hay --purge."""
    with (
        patch("capamedia_cli.commands.uninstall._has_uv_tool", return_value=False),
        patch("capamedia_cli.commands.uninstall._has_pip_install", return_value=False),
    ):
        with pytest.raises(typer.Exit) as exc:
            uninstall_command(purge=False, yes=True, dry_run=True)
        assert exc.value.exit_code == 0


def test_uninstall_dry_run_does_not_call_uninstall_commands() -> None:
    """Con --dry-run, no ejecuta los comandos reales."""
    with (
        patch("capamedia_cli.commands.uninstall._has_uv_tool", return_value=True),
        patch("capamedia_cli.commands.uninstall._has_pip_install", return_value=False),
        patch("capamedia_cli.commands.uninstall.subprocess.run") as mock_run,
    ):
        uninstall_command(purge=False, yes=True, dry_run=True)
        # En dry-run no deberia haber llamada a subprocess.run
        mock_run.assert_not_called()
