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
    main_java = migrated / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "application"
    resources = migrated / "src" / "main" / "resources"
    tests = migrated / "src" / "test" / "java" / "com" / "pichincha" / "sp"
    main_java.mkdir(parents=True)
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
        """<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" xmlns:xsd="http://www.w3.org/2001/XMLSchema" targetNamespace="http://bpichincha.com/servicios">
  <wsdl:types>
    <xsd:schema targetNamespace="http://bpichincha.com/servicios">
      <xsd:element name="ActualizarContactoTransaccional31">
        <xsd:complexType>
          <xsd:sequence>
            <xsd:element name="headerIn">
              <xsd:complexType>
                <xsd:sequence>
                  <xsd:element name="empresa" type="xsd:string"/>
                  <xsd:element name="canal" type="xsd:string"/>
                  <xsd:element name="medio" type="xsd:string"/>
                  <xsd:element name="aplicacion" type="xsd:string"/>
                  <xsd:element name="tipoTransaccion" type="xsd:string"/>
                  <xsd:element name="usuario" type="xsd:string"/>
                  <xsd:element name="idioma" type="xsd:string"/>
                  <xsd:element name="ip" type="xsd:string"/>
                  <xsd:element name="bancs" minOccurs="0">
                    <xsd:complexType>
                      <xsd:sequence>
                        <xsd:element name="teller" type="xsd:string"/>
                        <xsd:element name="terminal" type="xsd:string"/>
                        <xsd:element name="institucion" type="xsd:string"/>
                      </xsd:sequence>
                    </xsd:complexType>
                  </xsd:element>
                </xsd:sequence>
              </xsd:complexType>
            </xsd:element>
            <xsd:element name="bodyIn">
              <xsd:complexType>
                <xsd:sequence>
                  <xsd:element name="cif" type="xsd:string"/>
                  <xsd:element name="contactosTransaccionales">
                    <xsd:complexType>
                      <xsd:sequence>
                        <xsd:element name="contactosTransaccional">
                          <xsd:complexType>
                            <xsd:sequence>
                              <xsd:element name="tipo" type="xsd:string"/>
                              <xsd:element name="email" type="xsd:string" minOccurs="0"/>
                              <xsd:element name="celular" type="xsd:string"/>
                              <xsd:element name="activar" type="xsd:boolean"/>
                            </xsd:sequence>
                          </xsd:complexType>
                        </xsd:element>
                      </xsd:sequence>
                    </xsd:complexType>
                  </xsd:element>
                </xsd:sequence>
              </xsd:complexType>
            </xsd:element>
          </xsd:sequence>
        </xsd:complexType>
      </xsd:element>
    </xsd:schema>
  </wsdl:types>
  <wsdl:portType name="WSClientes9999Port">
    <wsdl:operation name="ActualizarContactoTransaccional31"/>
  </wsdl:portType>
</wsdl:definitions>
""",
        encoding="utf-8",
    )
    (tests / "happy.xml").write_text(
        "<headerIn><canal>02</canal><medio>020001</medio><aplicacion>00114</aplicacion><tipoTransaccion>201006701</tipoTransaccion></headerIn>",
        encoding="utf-8",
    )
    (tests / "CustomerServiceTest.java").write_text(
        "class CustomerServiceTest { @org.junit.jupiter.api.Test void cifVacioRetornaError() {} @org.junit.jupiter.api.Test void normalizaTelefonoOk() {} }\n",
        encoding="utf-8",
    )
    (main_java / "CustomerService.java").write_text(
        "class CustomerService { void execute() { validarCif(); normalizarTelefono(); invocarTX067186(); } }\n",
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
    assert doc.framework == "WebFlux"
    assert doc.operations == ["ActualizarContactoTransaccional31"]
    assert doc.namespace == "http://bpichincha.com/servicios"
    assert {field.name for field in doc.body_fields} >= {"cif", "contactosTransaccionales"}
    assert doc.happy_path is not None
    assert "020001" in doc.happy_path.curl
    assert "<cif>4667888</cif>" in doc.happy_path.curl
    assert "067186" in doc.tx_codes
    assert {var.name for var in doc.env_vars} >= {"CCC_BANCS_BASE_URL", "CCC_BANCS_CONNECT_TIMEOUT"}
    assert doc.test_classes == ["src/test/java/com/pichincha/sp/CustomerServiceTest.java"]
    cases = {test.case for test in doc.tests}
    assert "Cif vacio retorna error" not in cases
    assert "Normaliza telefono ok" not in cases
    assert any("CIF" in case for case in cases)
    assert "Validar reglas funcionales del servicio" in cases
    assert "Normalizar datos de contacto" in cases
    assert any("TX067186" in case for case in cases)


def test_render_documentation_outputs_confluence_tables_and_happy_path(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    migrated = workspace / "destino" / "tnd-msa-sp-wsclientes9999"
    doc = build_service_documentation(start=workspace, migrated=migrated)

    html = render_html(doc)
    markdown = render_markdown(doc)

    assert 'class="confluenceTable"' in html
    assert 'ac:name="info"' in html
    assert "Referencias del Proyecto" in html
    assert "Adaptador entrada REST" in html
    assert "Configurar credenciales para Azure Artifacts" in html
    assert "Generar clases desde WSDL" in html
    assert "No aplica" in html
    assert "CCC_BANCS_BASE_URL" in html
    assert "Params (entrada bodyIn)" in html
    assert "Curl del Happy Path (ambiente OpenShift)" in html
    assert "https://tnd-msa-sp-wsclientes9999-enp.apps.ocptest.uiotest.bpichinchatest.test/IntegrationBus/soap/WSClientes9999" in html
    assert "020001" in html
    assert "&lt;cif&gt;4667888&lt;/cif&gt;" in html
    assert "Análisis del happy path" in html
    assert "Validaciones de Entrada" in html
    assert "Operaciones BANCS" in html
    assert "Normalizaciones" in html
    assert "Pendiente" in html
    assert "TX 067186" in html
    assert "Cif vacio retorna error" not in html
    assert "Normaliza telefono ok" not in html
    assert "TX 067186 - Request" in html
    assert "TX 067186 - Response" in html
    assert "Curl del Happy Path (ambiente OpenShift)" in markdown
    assert "020001" in markdown


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
    assert "Confluence" in result.stdout
