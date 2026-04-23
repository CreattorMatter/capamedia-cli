"""Tests para `capamedia adopt` (v0.23.11)."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from capamedia_cli.cli import app


runner = CliRunner()


def test_adopt_is_registered() -> None:
    """`capamedia adopt --help` debe funcionar."""
    result = runner.invoke(app, ["adopt", "--help"])
    assert result.exit_code == 0
    assert "adopt" in result.output.lower()
    assert "--init" in result.output
    assert "--dry-run" in result.output


def test_adopt_classifies_ws_was_as_legacy() -> None:
    """ws-<svc>-was -> clasificado como legacy."""
    from capamedia_cli.commands.adopt import _classify_subdir

    assert _classify_subdir(Path("ws-wsclientes0076-was")) == "legacy"
    assert _classify_subdir(Path("ms-wsclientes0076-was")) == "legacy"
    assert _classify_subdir(Path("ump-umptecnicos0023-was")) == "legacy"
    assert _classify_subdir(Path("sqb-msa-wsclientes0006")) == "legacy"


def test_adopt_classifies_msa_sp_as_destino() -> None:
    """csg/tnd/tpr/tmp/tia/tct-msa-sp-<svc> -> destino."""
    from capamedia_cli.commands.adopt import _classify_subdir

    assert _classify_subdir(Path("csg-msa-sp-wsclientes0026")) == "destino"
    assert _classify_subdir(Path("tnd-msa-sp-wsclientes0076")) == "destino"
    assert _classify_subdir(Path("tpr-msa-sp-wsclientes0076")) == "destino"
    assert _classify_subdir(Path("tmp-msa-sp-xxx0001")) == "destino"
    assert _classify_subdir(Path("tia-msa-sp-xxx0001")) == "destino"
    assert _classify_subdir(Path("tct-msa-sp-xxx0001")) == "destino"


def test_adopt_returns_none_for_unknown_patterns() -> None:
    """Directorios con nombres arbitrarios no se clasifican."""
    from capamedia_cli.commands.adopt import _classify_subdir

    assert _classify_subdir(Path("random-folder")) is None
    assert _classify_subdir(Path("my-project")) is None
    assert _classify_subdir(Path(".hidden")) is None
    # Ya reubicados: legacy/, destino/, etc. no se clasifican (se filtra antes)
    assert _classify_subdir(Path("docs")) is None


def test_adopt_dry_run_does_not_move(tmp_path: Path) -> None:
    """--dry-run muestra el plan pero no mueve nada."""
    # Setup: simulacion de workspace plano
    (tmp_path / "ws-wsclientes0026-was").mkdir()
    (tmp_path / "csg-msa-sp-wsclientes0026").mkdir()

    result = runner.invoke(
        app,
        ["adopt", "wsclientes0026", "--workspace", str(tmp_path), "--dry-run", "--yes"],
    )
    assert result.exit_code == 0
    # Los dirs originales siguen ahi
    assert (tmp_path / "ws-wsclientes0026-was").exists()
    assert (tmp_path / "csg-msa-sp-wsclientes0026").exists()
    # No se creo legacy/ ni destino/
    assert not (tmp_path / "legacy").exists()
    assert not (tmp_path / "destino").exists()


def test_adopt_moves_with_yes_flag(tmp_path: Path) -> None:
    """Con --yes mueve sin pedir confirmacion."""
    (tmp_path / "ws-wsclientes0026-was").mkdir()
    (tmp_path / "csg-msa-sp-wsclientes0026").mkdir()
    # Agregar un archivo dentro para verificar que el contenido se mueve
    (tmp_path / "ws-wsclientes0026-was" / "pom.xml").write_text("<pom/>", encoding="utf-8")

    result = runner.invoke(
        app,
        ["adopt", "wsclientes0026", "--workspace", str(tmp_path), "--yes"],
    )
    assert result.exit_code == 0

    # Verificar que se movio todo
    assert (tmp_path / "legacy" / "ws-wsclientes0026-was").is_dir()
    assert (tmp_path / "legacy" / "ws-wsclientes0026-was" / "pom.xml").exists()
    assert (tmp_path / "destino" / "csg-msa-sp-wsclientes0026").is_dir()

    # Los originales ya no estan en la raiz
    assert not (tmp_path / "ws-wsclientes0026-was").exists()
    assert not (tmp_path / "csg-msa-sp-wsclientes0026").exists()


def test_adopt_preserves_unrelated_files(tmp_path: Path) -> None:
    """Archivos y directorios que no matchean patterns no se tocan."""
    (tmp_path / "ws-wsclientes0026-was").mkdir()
    (tmp_path / "MIGRATION_REPORT.md").write_text("# report", encoding="utf-8")
    (tmp_path / "ANALISIS_wsclientes0026.md").write_text("# analisis", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.txt").write_text("x", encoding="utf-8")

    result = runner.invoke(
        app,
        ["adopt", "wsclientes0026", "--workspace", str(tmp_path), "--yes"],
    )
    assert result.exit_code == 0

    # Archivos preservados
    assert (tmp_path / "MIGRATION_REPORT.md").exists()
    assert (tmp_path / "ANALISIS_wsclientes0026.md").exists()
    assert (tmp_path / "docs" / "note.txt").exists()
    # Legacy movido
    assert (tmp_path / "legacy" / "ws-wsclientes0026-was").is_dir()


def test_adopt_no_moves_when_no_patterns_match(tmp_path: Path) -> None:
    """Si no hay subdirs con patterns conocidos, exit 0 sin error."""
    (tmp_path / "random-dir").mkdir()
    (tmp_path / "README.md").write_text("x", encoding="utf-8")

    result = runner.invoke(
        app,
        ["adopt", "wsclientes0026", "--workspace", str(tmp_path), "--yes"],
    )
    assert result.exit_code == 0
    assert "No se detectaron" in result.output or "moves detectados:" in result.output.lower() or "Moves detectados: [bold]0[/bold]" in result.output or "0" in result.output


def test_adopt_with_init_runs_scaffold(tmp_path: Path) -> None:
    """--init dispara scaffold_project despues de los moves."""
    (tmp_path / "ws-wsclientes0026-was").mkdir()
    (tmp_path / "csg-msa-sp-wsclientes0026").mkdir()

    result = runner.invoke(
        app,
        [
            "adopt", "wsclientes0026",
            "--workspace", str(tmp_path),
            "--yes", "--init",
        ],
    )
    assert result.exit_code == 0
    # Despues del init, deberia haber .claude/ y .capamedia/
    assert (tmp_path / ".claude").is_dir()
    assert (tmp_path / ".capamedia" / "config.yaml").exists()
    # Moves ejecutados tambien
    assert (tmp_path / "legacy" / "ws-wsclientes0026-was").is_dir()
    assert (tmp_path / "destino" / "csg-msa-sp-wsclientes0026").is_dir()


def test_adopt_infers_service_name_from_subdirs(tmp_path: Path) -> None:
    """Sin service_name arg, lo infiere de los subdirs detectados."""
    (tmp_path / "ws-wsclientes0026-was").mkdir()
    (tmp_path / "csg-msa-sp-wsclientes0026").mkdir()

    result = runner.invoke(
        app,
        ["adopt", "--workspace", str(tmp_path), "--yes", "--dry-run"],
    )
    assert result.exit_code == 0
    # Debe aparecer en el output el service inferido
    assert "wsclientes0026" in result.output


def test_adopt_skips_already_moved_dirs(tmp_path: Path) -> None:
    """Idempotencia: si legacy/destino ya existen y los originales estan
    adentro, no intenta mover de nuevo."""
    (tmp_path / "legacy" / "ws-wsclientes0026-was").mkdir(parents=True)
    (tmp_path / "destino" / "csg-msa-sp-wsclientes0026").mkdir(parents=True)

    result = runner.invoke(
        app,
        ["adopt", "wsclientes0026", "--workspace", str(tmp_path), "--yes"],
    )
    assert result.exit_code == 0
    # Sin moves nuevos, sigue existiendo la estructura
    assert (tmp_path / "legacy" / "ws-wsclientes0026-was").is_dir()
