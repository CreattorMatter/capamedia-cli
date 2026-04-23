"""Tests para `capamedia review orq|bus|was` (v0.23.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import typer

from capamedia_cli.commands.review import app as review_app
from capamedia_cli.commands.review import review


def _make_workspace(tmp_path: Path) -> Path:
    """Workspace minimo con destino/<svc>/ + legacy/<svc>/ para autodetect."""
    ws = tmp_path / "svc"
    (ws / "destino" / "tpr-msa-sp-svc" / "src" / "main" / "java").mkdir(parents=True)
    (ws / "legacy" / "legacy-svc").mkdir(parents=True)
    return ws


# ---------------------------------------------------------------------------
# Subcomandos wireados en el Typer app
# ---------------------------------------------------------------------------


def test_review_app_has_orq_bus_was_subcommands() -> None:
    """El Typer app de review debe exponer 3 subcomandos: orq, bus, was."""
    from typer.main import get_command

    cmd = get_command(review_app)
    sub_names = set(cmd.commands.keys())
    assert "orq" in sub_names
    assert "bus" in sub_names
    assert "was" in sub_names


def test_review_help_mentions_subcommands() -> None:
    """`capamedia review --help` debe mencionar los subcomandos."""
    from typer.testing import CliRunner

    from capamedia_cli.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["review", "--help"])
    assert result.exit_code == 0
    # Los 3 subcomandos aparecen en el help
    assert "orq" in result.output
    assert "bus" in result.output
    assert "was" in result.output


def test_review_orq_help_explains_block_20() -> None:
    from typer.testing import CliRunner

    from capamedia_cli.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["review", "orq", "--help"])
    assert result.exit_code == 0
    # Explicar que activa Block 20
    assert "orq" in result.output.lower()


# ---------------------------------------------------------------------------
# Paso de --kind / force_kind al core review
# ---------------------------------------------------------------------------


class _FakeResult:
    """Stub de CheckResult para los mocks del review end-to-end."""

    def __init__(self, status: str = "pass", severity: str = ""):
        self.status = status
        self.severity = severity
        self.id = "x"
        self.block = "Block 0"
        self.title = "stub"
        self.detail = ""
        self.suggested_fix = ""


def _run_review_with_mocks(review_fn, **kwargs) -> None:
    """Corre review() bajo mocks del pipeline interno para no depender del MCP/fs."""

    class _AutofixReport:
        iterations = 1
        total_applied = 0
        converged = True
        log_path = None

    with (
        patch(
            "capamedia_cli.commands.review.run_autofix_loop",
            return_value=_AutofixReport(),
        ),
        patch("capamedia_cli.commands.review.run_bank_autofix", return_value=[]),
        patch(
            "capamedia_cli.commands.review.run_all_blocks",
            return_value=[_FakeResult("pass")],
        ),
    ):
        review_fn(skip_official=True, **kwargs)


def test_review_force_kind_orq_sets_source_type_in_context(tmp_path: Path) -> None:
    """Correr `review` con force_kind='orq' debe setear source_type='orq' en el
    CheckContext que se pasa a run_all_blocks."""
    project = tmp_path / "destino" / "tpr-msa-sp-x"
    project.mkdir(parents=True)

    captured: dict[str, object] = {}

    def _capture(ctx_arg):
        captured["source_type"] = ctx_arg.source_type
        return [_FakeResult("pass")]

    with (
        patch(
            "capamedia_cli.commands.review.run_all_blocks",
            side_effect=_capture,
        ),
        patch("capamedia_cli.commands.review.run_bank_autofix", return_value=[]),
        patch(
            "capamedia_cli.commands.review.run_autofix_loop",
            return_value=type("A", (), {
                "iterations": 1, "total_applied": 0,
                "converged": True, "log_path": None,
            })(),
        ),
    ):
        review(project_path=project, skip_official=True, force_kind="orq")

    assert captured["source_type"] == "orq"


def test_review_force_kind_was_sets_source_type(tmp_path: Path) -> None:
    project = tmp_path / "destino" / "tpr-msa-sp-x"
    project.mkdir(parents=True)
    captured: dict[str, object] = {}

    def _capture(ctx_arg):
        captured["source_type"] = ctx_arg.source_type
        return [_FakeResult("pass")]

    with (
        patch("capamedia_cli.commands.review.run_all_blocks", side_effect=_capture),
        patch("capamedia_cli.commands.review.run_bank_autofix", return_value=[]),
        patch(
            "capamedia_cli.commands.review.run_autofix_loop",
            return_value=type("A", (), {
                "iterations": 1, "total_applied": 0,
                "converged": True, "log_path": None,
            })(),
        ),
    ):
        review(project_path=project, skip_official=True, force_kind="was")

    assert captured["source_type"] == "was"


def test_review_force_kind_bus_sets_source_type(tmp_path: Path) -> None:
    project = tmp_path / "destino" / "tpr-msa-sp-x"
    project.mkdir(parents=True)
    captured: dict[str, object] = {}

    def _capture(ctx_arg):
        captured["source_type"] = ctx_arg.source_type
        return [_FakeResult("pass")]

    with (
        patch("capamedia_cli.commands.review.run_all_blocks", side_effect=_capture),
        patch("capamedia_cli.commands.review.run_bank_autofix", return_value=[]),
        patch(
            "capamedia_cli.commands.review.run_autofix_loop",
            return_value=type("A", (), {
                "iterations": 1, "total_applied": 0,
                "converged": True, "log_path": None,
            })(),
        ),
    ):
        review(project_path=project, skip_official=True, force_kind="bus")

    assert captured["source_type"] == "bus"


def test_review_force_kind_invalid_exits_2(tmp_path: Path) -> None:
    """--kind con valor invalido (ej 'foo') -> exit 2."""
    project = tmp_path / "destino" / "tpr-msa-sp-x"
    project.mkdir(parents=True)

    with pytest.raises(typer.Exit) as exc:
        review(project_path=project, skip_official=True, force_kind="foo")
    assert exc.value.exit_code == 2


def test_review_force_kind_overrides_autodetected(tmp_path: Path) -> None:
    """Si el legacy dice 'was' pero forzamos 'orq', usar 'orq'."""
    ws = _make_workspace(tmp_path)
    project = ws / "destino" / "tpr-msa-sp-svc"
    legacy = ws / "legacy" / "legacy-svc"
    # Crear signos de WAS en el legacy (Java + web.xml)
    (legacy / "src" / "main" / "webapp" / "WEB-INF").mkdir(parents=True)
    (legacy / "src" / "main" / "webapp" / "WEB-INF" / "web.xml").write_text(
        "<web-app/>", encoding="utf-8",
    )
    (legacy / "src" / "main" / "java" / "X.java").parent.mkdir(parents=True)
    (legacy / "src" / "main" / "java" / "X.java").write_text(
        "public class X {}", encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def _capture(ctx_arg):
        captured["source_type"] = ctx_arg.source_type
        return [_FakeResult("pass")]

    with (
        patch("capamedia_cli.commands.review.run_all_blocks", side_effect=_capture),
        patch("capamedia_cli.commands.review.run_bank_autofix", return_value=[]),
        patch(
            "capamedia_cli.commands.review.run_autofix_loop",
            return_value=type("A", (), {
                "iterations": 1, "total_applied": 0,
                "converged": True, "log_path": None,
            })(),
        ),
    ):
        review(
            project_path=project, legacy=legacy,
            skip_official=True, force_kind="orq",
        )

    # Aunque el legacy parezca WAS, --kind orq manda
    assert captured["source_type"] == "orq"


def test_review_without_force_kind_uses_autodetected(tmp_path: Path) -> None:
    """Sin --kind, el source_type viene del detector del legacy."""
    ws = _make_workspace(tmp_path)
    project = ws / "destino" / "tpr-msa-sp-svc"
    legacy = ws / "legacy" / "legacy-svc"
    # Firmar el legacy como WAS
    (legacy / "src" / "main" / "webapp" / "WEB-INF").mkdir(parents=True)
    (legacy / "src" / "main" / "webapp" / "WEB-INF" / "web.xml").write_text(
        "<web-app/>", encoding="utf-8",
    )
    (legacy / "src" / "main" / "java" / "X.java").parent.mkdir(parents=True)
    (legacy / "src" / "main" / "java" / "X.java").write_text(
        "public class X {}", encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def _capture(ctx_arg):
        captured["source_type"] = ctx_arg.source_type
        return [_FakeResult("pass")]

    with (
        patch("capamedia_cli.commands.review.run_all_blocks", side_effect=_capture),
        patch("capamedia_cli.commands.review.run_bank_autofix", return_value=[]),
        patch(
            "capamedia_cli.commands.review.run_autofix_loop",
            return_value=type("A", (), {
                "iterations": 1, "total_applied": 0,
                "converged": True, "log_path": None,
            })(),
        ),
    ):
        review(project_path=project, legacy=legacy, skip_official=True)

    assert captured["source_type"] == "was"
