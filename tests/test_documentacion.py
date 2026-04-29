from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from capamedia_cli.cli import app
from capamedia_cli.core.documentacion import (
    build_service_documentation,
    render_html,
    render_markdown,
)


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "wsclientes9999"
    migrated = workspace / "destino" / "tnd-msa-sp-wsclientes9999"
    resources = migrated / "src" / "main" / "resources"
    tests = migrated / "src" / "test" / "java" / "com" / "pichincha" / "sp"
    resources.mkdir(parents=True)
    tests.mkdir(parents=True)
    (workspace / "legacy" / "sqb-msa-wsclientes9999").mkdir(parents=True)

    (migrated / "build.gradle").write_text(
        "plugins { id 'org.springframework.boot' version '3.5.13' }\n"
        "dependencies { implementation 'org.springframework.boot:spring-boot-starter-webflux' }\n",
        encoding="utf-8",
    )
    (migrated / "gradle" / "wrapper").mkdir(parents=True)
    (migrated / "gradle" / "wrapper" / "gradle-wrapper.properties").write_text(
        "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.14-bin.zip\n",
        encoding="utf-8",
    )
    (resources / "application.yml").write_text(
        "bancs:\n"
        "  webclients:\n"
        "    ws-tx067186:\n"
        "      base-url: ${CCC_BANCS_BASE_URL:http://localhost:9999}\n"
        "      connect-timeout: ${CCC_BANCS_CONNECT_TIMEOUT:2000}\n",
        encoding="utf-8",
    )
    (resources / "service.wsdl").write_text(
        """<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" targetNamespace="http://bpichincha.com/servicios">
  <wsdl:portType name="WSClientes9999Port">
    <wsdl:operation name="ActualizarContactoTransaccional31"/>
  </wsdl:portType>
</wsdl:definitions>
""",
        encoding="utf-8",
    )
    (tests / "CustomerServiceTest.java").write_text(
        "class CustomerServiceTest { @org.junit.jupiter.api.Test void cifVacioRetornaError() {} }\n",
        encoding="utf-8",
    )
    (workspace / "COMPLEXITY_wsclientes9999.md").write_text(
        "## Explicacion de la Logica de Negocio\n"
        "Valida CIF, normaliza telefono y llama TX067186.\n",
        encoding="utf-8",
    )
    return workspace


def test_build_service_documentation_collects_project_evidence(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    migrated = workspace / "destino" / "tnd-msa-sp-wsclientes9999"

    doc = build_service_documentation(start=workspace, migrated=migrated)

    assert doc.service_name == "WSClientes9999"
    assert doc.migrated_name == "tnd-msa-sp-wsclientes9999"
    assert doc.spring_boot_version == "3.5.13"
    assert doc.gradle_version == "8.14"
    assert doc.framework == "Spring WebFlux"
    assert doc.operations == ["ActualizarContactoTransaccional31"]
    assert doc.namespace == "http://bpichincha.com/servicios"
    assert "067186" in doc.tx_codes
    assert {var.name for var in doc.env_vars} >= {"CCC_BANCS_BASE_URL", "CCC_BANCS_CONNECT_TIMEOUT"}


def test_render_documentation_outputs_google_docs_friendly_tables(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    migrated = workspace / "destino" / "tnd-msa-sp-wsclientes9999"
    doc = build_service_documentation(start=workspace, migrated=migrated)

    html = render_html(doc)
    markdown = render_markdown(doc)

    assert "<table>" in html
    assert "Referencias del Proyecto" in html
    assert "Configurar credenciales para Azure Artifacts" in html
    assert "Generar clases desde WSDL" in html
    assert "CCC_BANCS_BASE_URL" in html
    assert "Params (entrada bodyIn)" in html
    assert "Cada contactosTransaccional" in html
    assert "Ejemplo de request" in html
    assert "Validaciones de Entrada" in html
    assert "Operaciones BANCS" in html
    assert "Normalizaciones" in html
    assert "TX 067186" in html
    assert "TX 067186 - Request" in html
    assert "TX 067186 - Response (Query)" in html
    assert "| # | Variable | Descripción | Valor por defecto | Fuente |" in markdown


def test_documentacion_command_writes_html(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    output = tmp_path / "doc.html"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "documentacion",
            "wsclientes9999",
            "--workspace",
            str(workspace),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "WSClientes9999 - Documentación de Servicio" in text
    assert "Google Docs" in result.stdout
