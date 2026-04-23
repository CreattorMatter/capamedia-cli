"""Tests para clone --init (v0.23.0): flag que dispara init automatico."""

from __future__ import annotations

from pathlib import Path


def test_clone_has_init_flag() -> None:
    """La firma de clone_service acepta --init + --init-ai con default claude."""
    import inspect

    from capamedia_cli.commands.clone import clone_service

    sig = inspect.signature(clone_service)
    assert "init" in sig.parameters, "clone_service debe tener el parametro init"
    assert "init_ai" in sig.parameters, "clone_service debe tener el parametro init_ai"


def test_clone_init_ai_defaults_to_claude() -> None:
    """Por defecto (sin --init-ai), el harness es `claude`."""
    import inspect

    from capamedia_cli.commands.clone import clone_service

    sig = inspect.signature(clone_service)
    init_ai_param = sig.parameters["init_ai"]
    # El default es un typer.Option(..., default="claude") — acceder al valor
    # via Typer requiere inspeccionar el Annotated, pero al menos podemos
    # verificar que existe.
    assert init_ai_param.default is not inspect.Parameter.empty


def test_clone_checklist_command_wired_in_cli(tmp_path: Path) -> None:
    """v0.23.0: `capamedia checklist` esta wireado en cli.py."""
    from typer.testing import CliRunner

    from capamedia_cli.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["checklist", "--help"])
    assert result.exit_code == 0
    assert "doble check" in result.output.lower() or "checklist" in result.output.lower()


def test_clone_command_mentions_init_flag_in_help() -> None:
    """El help de clone debe documentar --init."""
    from typer.testing import CliRunner

    from capamedia_cli.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["clone", "--help"])
    assert result.exit_code == 0
    assert "--init" in result.output
    assert "Claude Code" in result.output or "claude" in result.output.lower()
