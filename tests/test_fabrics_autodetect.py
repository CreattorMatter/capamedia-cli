"""Tests para autodeteccion de service_name en `capamedia fabrics generate` (v0.20.4)."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from capamedia_cli.commands.fabrics import (
    _autodetect_service_name_from_config,
    generate,
)


def test_autodetect_reads_service_name_from_config(tmp_path: Path) -> None:
    """Si .capamedia/config.yaml tiene service_name, devolverlo."""
    capamedia = tmp_path / ".capamedia"
    capamedia.mkdir()
    (capamedia / "config.yaml").write_text(
        "version: 0.20.3\nservice_name: wsclientes0076\nai:\n- claude\n",
        encoding="utf-8",
    )
    assert _autodetect_service_name_from_config(tmp_path) == "wsclientes0076"


def test_autodetect_returns_none_when_config_absent(tmp_path: Path) -> None:
    assert _autodetect_service_name_from_config(tmp_path) is None


def test_autodetect_returns_none_when_service_name_missing(tmp_path: Path) -> None:
    """Config valido pero sin service_name -> None (no crashea)."""
    capamedia = tmp_path / ".capamedia"
    capamedia.mkdir()
    (capamedia / "config.yaml").write_text(
        "version: 0.20.3\nai:\n- claude\n",
        encoding="utf-8",
    )
    assert _autodetect_service_name_from_config(tmp_path) is None


def test_autodetect_returns_none_on_invalid_yaml(tmp_path: Path) -> None:
    """YAML malformado -> None, no exception."""
    capamedia = tmp_path / ".capamedia"
    capamedia.mkdir()
    (capamedia / "config.yaml").write_text(
        "[[[not valid yaml",
        encoding="utf-8",
    )
    # No debe crashear
    result = _autodetect_service_name_from_config(tmp_path)
    assert result is None


def test_autodetect_strips_whitespace(tmp_path: Path) -> None:
    capamedia = tmp_path / ".capamedia"
    capamedia.mkdir()
    (capamedia / "config.yaml").write_text(
        'service_name: "  wsclientes0076  "\n',
        encoding="utf-8",
    )
    assert _autodetect_service_name_from_config(tmp_path) == "wsclientes0076"


def test_generate_without_service_name_fails_when_no_config(tmp_path: Path, monkeypatch) -> None:
    """Correr desde carpeta sin .capamedia/config.yaml -> exit 2 con mensaje claro."""
    from typer.testing import CliRunner

    from capamedia_cli.commands.fabrics import app as fabrics_app

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(fabrics_app, ["generate"])
    assert result.exit_code == 2
    assert "SERVICE_NAME" in result.output or "autodetectar" in result.output


def test_generate_autodetects_and_proceeds_to_preflight(tmp_path: Path, monkeypatch) -> None:
    """Con .capamedia/config.yaml presente, generate autodetecta el nombre
    y sigue hasta el preflight (donde va a fallar por falta de MCP, pero YA
    paso la autodeteccion - ese es el punto que queremos verificar)."""
    from typer.testing import CliRunner

    from capamedia_cli.commands.fabrics import app as fabrics_app

    # Crear workspace con config.yaml
    capamedia = tmp_path / ".capamedia"
    capamedia.mkdir()
    (capamedia / "config.yaml").write_text(
        "version: 0.20.4\nservice_name: wsclientes0076\nai:\n- claude\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(fabrics_app, ["generate"])
    # Exit != 0 porque no hay MCP Fabrics, pero el output debe mostrar
    # que autodetecto el service name
    assert "wsclientes0076" in result.output
    assert "Autodetectado" in result.output or "autodetect" in result.output.lower()
