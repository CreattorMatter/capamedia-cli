"""Tests para `batch clone --init` y `batch review` (v0.23.4)."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from capamedia_cli.commands.batch import app as batch_app


runner = CliRunner()


# ---------------------------------------------------------------------------
# batch clone --init flag
# ---------------------------------------------------------------------------


def test_batch_clone_has_init_flag_in_help() -> None:
    """`capamedia batch clone --help` debe mencionar --init y --init-ai."""
    result = runner.invoke(batch_app, ["clone", "--help"])
    assert result.exit_code == 0
    assert "--init" in result.output
    assert "--init-ai" in result.output
    assert "claude" in result.output.lower()


# ---------------------------------------------------------------------------
# batch review subcomando
# ---------------------------------------------------------------------------


def test_batch_review_is_registered() -> None:
    """El subcomando batch review debe estar wireado."""
    result = runner.invoke(batch_app, ["review", "--help"])
    assert result.exit_code == 0
    assert "review" in result.output.lower()


def test_batch_review_fails_when_no_workspaces_found(tmp_path: Path) -> None:
    """Si CWD no tiene subcarpetas con destino/, debe exit 2 con mensaje claro."""
    result = runner.invoke(batch_app, ["review", str(tmp_path)])
    assert result.exit_code == 2
    assert "no se encontraron workspaces" in result.output.lower() or "workspaces" in result.output.lower()


def test_batch_review_autodetects_workspaces(tmp_path: Path) -> None:
    """Cuando la carpeta root tiene N subcarpetas con destino/, las detecta todas."""
    # Crear 3 workspaces, uno sin destino/ (debe ignorarse)
    for svc in ("wsa0001", "wsa0002", "wsa0003"):
        ws = tmp_path / svc
        (ws / "destino" / f"tpr-msa-sp-{svc}" / "src" / "main" / "java").mkdir(parents=True)
        # Agregar build.gradle para que sea "proyecto valido"
        (ws / "destino" / f"tpr-msa-sp-{svc}" / "build.gradle").write_text(
            "// stub", encoding="utf-8",
        )
        # Crear WSDL minimo para que Block 0 no crashee
        (ws / "destino" / f"tpr-msa-sp-{svc}" / "src" / "main" / "resources" / "svc.wsdl").parent.mkdir(parents=True, exist_ok=True)
        (ws / "destino" / f"tpr-msa-sp-{svc}" / "src" / "main" / "resources" / "svc.wsdl").write_text(
            '<?xml version="1.0"?>\n'
            '<definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">\n'
            '<wsdl:portType name="X"><wsdl:operation name="op1"/></wsdl:portType>\n'
            '</definitions>\n',
            encoding="utf-8",
        )

    # Una subcarpeta SIN destino/, debe ignorarse
    (tmp_path / "not-a-workspace").mkdir()

    result = runner.invoke(batch_app, ["review", str(tmp_path), "--workers", "1"])
    # El exit code puede ser 0 o 1 segun resultados, pero la invocacion debe
    # llegar al panel con "3 workspaces"
    assert "Workspaces: 3" in result.output or "Workspaces:  3" in result.output


def test_batch_review_from_file_reads_explicit_list(tmp_path: Path) -> None:
    """Con --from archivo.txt, lee nombres explicitos y los mapea a subcarpetas."""
    # Crear archivo .txt con 2 nombres
    services_file = tmp_path / "services.txt"
    services_file.write_text("wsfoo0001\nwsfoo0002\n", encoding="utf-8")

    # Crear solo 1 workspace (wsfoo0001); el otro no existe -> debe reportar fail
    ws = tmp_path / "wsfoo0001"
    (ws / "destino" / "tpr-msa-sp-wsfoo0001").mkdir(parents=True)
    (ws / "destino" / "tpr-msa-sp-wsfoo0001" / "build.gradle").write_text("", encoding="utf-8")
    (ws / "destino" / "tpr-msa-sp-wsfoo0001" / "src" / "main" / "resources" / "svc.wsdl").parent.mkdir(parents=True)
    (ws / "destino" / "tpr-msa-sp-wsfoo0001" / "src" / "main" / "resources" / "svc.wsdl").write_text(
        '<?xml version="1.0"?><definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">'
        '<wsdl:portType name="X"><wsdl:operation name="op"/></wsdl:portType></definitions>',
        encoding="utf-8",
    )

    result = runner.invoke(
        batch_app,
        ["review", str(tmp_path), "--from", str(services_file), "--workers", "1"],
    )
    # 2 servicios en el archivo, el panel debe decir 2
    assert "Workspaces: 2" in result.output or "Workspaces:  2" in result.output


def test_batch_review_writes_markdown_report(tmp_path: Path) -> None:
    """Al finalizar, batch review escribe un .md en el root."""
    # Setup minimo: 1 workspace
    ws = tmp_path / "wsx0001"
    (ws / "destino" / "tpr-msa-sp-wsx0001").mkdir(parents=True)
    (ws / "destino" / "tpr-msa-sp-wsx0001" / "build.gradle").write_text("", encoding="utf-8")
    resources = ws / "destino" / "tpr-msa-sp-wsx0001" / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "svc.wsdl").write_text(
        '<?xml version="1.0"?><definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">'
        '<wsdl:portType name="X"><wsdl:operation name="op"/></wsdl:portType></definitions>',
        encoding="utf-8",
    )

    result = runner.invoke(batch_app, ["review", str(tmp_path), "--workers", "1"])
    # Debe haber creado un reporte .md
    reports = list(tmp_path.rglob("batch-review-*.md"))
    assert len(reports) >= 1, f"esperaba 1+ reporte batch-review-*.md, got {reports}"
    # El reporte debe contener el nombre del servicio
    content = reports[0].read_text(encoding="utf-8")
    assert "wsx0001" in content
