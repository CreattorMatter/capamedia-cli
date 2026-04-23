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


# ---------------------------------------------------------------------------
# v0.20.5 - Bug fixes reportados en wsclientes0076
# ---------------------------------------------------------------------------


def test_project_name_uses_selected_namespace_not_hardcoded_tnd() -> None:
    """Bug v0.20.4: project_name quedaba hardcodeado 'tnd-msa-sp-{svc}' aunque
    el usuario eligiera otro namespace (tpr/csg/tmp/tia/tct). v0.20.5: usa el
    namespace elegido como prefix."""
    # Verificacion unitaria: inspeccionar el codigo fuente para garantizar
    # que el projectName se construye DESPUES de resolver el namespace.
    import capamedia_cli.commands.fabrics as fabrics_module

    source = Path(fabrics_module.__file__).read_text(encoding="utf-8")

    # El string hardcodeado "tnd-msa-sp-" no debe aparecer como prefijo del projectName
    assert 'f"tnd-msa-sp-{service_name' not in source, (
        "project_name NO debe hardcodear 'tnd-msa-sp-': debe usar "
        "{namespace}-msa-sp-{service_name}"
    )
    # Debe aparecer la version correcta con namespace variable
    assert 'f"{namespace}-msa-sp-{service_name' in source, (
        "project_name debe usar {namespace}-msa-sp-{service_name}"
    )


def test_synthetic_wsdl_generates_placeholder_for_mcp() -> None:
    """Bug v0.20.4-5 fixeado en v0.20.6: cuando analyze_legacy sintetiza
    Path('<inferred-from-java>') porque el WAS no tiene .wsdl fisico, el CLI
    debe generar un WSDL placeholder minimo para pasar al MCP.

    Intentar omitir wsdlFilePath (v0.20.5) hacia que el MCP fallara con
    "path argument must be of type string. Received undefined" porque espera
    el campo siempre presente.
    """
    import capamedia_cli.commands.fabrics as fabrics_module

    source = Path(fabrics_module.__file__).read_text(encoding="utf-8")

    # Debe aparecer el check por el prefix "<inferred"
    assert "<inferred" in source
    # Debe aparecer la funcion que genera el placeholder
    assert "_write_wsdl_placeholder" in source
    # Debe aparecer wsdl_is_synthetic
    assert "wsdl_is_synthetic" in source


def test_write_wsdl_placeholder_creates_valid_file(tmp_path: Path) -> None:
    """_write_wsdl_placeholder escribe un XML valido en .capamedia/tmp/."""
    from capamedia_cli.commands.fabrics import _write_wsdl_placeholder

    out = _write_wsdl_placeholder(tmp_path, "wsclientes0076")
    assert out.exists()
    assert out.parent == tmp_path / ".capamedia" / "tmp"
    assert out.name == "wsclientes0076-placeholder.wsdl"

    content = out.read_text(encoding="utf-8")
    # Valido XML + WSDL minimo
    assert content.startswith('<?xml version="1.0"')
    assert "<wsdl:definitions" in content
    assert "<wsdl:portType" in content
    # Usa el service_name en el naming
    assert "Wsclientes0076" in content  # PascalCase del service name
    # Explica que es un placeholder
    assert "PLACEHOLDER" in content.upper()


def test_write_wsdl_placeholder_honors_target_namespace(tmp_path: Path) -> None:
    """Si se pasa target_namespace, el placeholder lo usa."""
    from capamedia_cli.commands.fabrics import _write_wsdl_placeholder

    out = _write_wsdl_placeholder(
        tmp_path,
        "wsclientes0076",
        target_namespace="http://custom.pichincha.com/svc",
    )
    content = out.read_text(encoding="utf-8")
    assert 'targetNamespace="http://custom.pichincha.com/svc"' in content


def test_write_wsdl_placeholder_default_namespace(tmp_path: Path) -> None:
    """Sin target_namespace, usa un default razonable."""
    from capamedia_cli.commands.fabrics import _write_wsdl_placeholder

    out = _write_wsdl_placeholder(tmp_path, "wsclientes0076")
    content = out.read_text(encoding="utf-8")
    assert "pichincha.com" in content
    assert "wsclientes0076" in content


def test_success_message_does_not_suggest_init_inside_destino() -> None:
    """v0.20.7: el mensaje de exito de fabrics NO debe sugerir correr
    `init --here dentro de destino/` (bug UX: eso ensuciaria el repo Java
    del banco con assets de Claude).

    En lugar, debe mandar al usuario al workspace root para claude + /migrate.
    """
    import capamedia_cli.commands.fabrics as fabrics_module

    source = Path(fabrics_module.__file__).read_text(encoding="utf-8")
    # El mensaje erroneo anterior NO debe aparecer
    assert "init --here` dentro de destino" not in source, (
        "El mensaje de exito no debe sugerir init --here dentro de destino/ - "
        "eso duplicaria configs de Claude dentro del repo Java del banco"
    )
    # Y debe mandar a correr claude desde el workspace
    assert "claude ." in source or "claude `." in source
