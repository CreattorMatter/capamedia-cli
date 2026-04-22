"""Tests de la matriz de decision MCP Fabrics (v0.9.0).

Cubre:
  - 7 filas de la matriz (IIB con/sin BANCS x 1/2+ ops, WAS 1/2+ endpoints, ORQ)
  - 3 tests de `detect_bancs_connection`
  - 3 tests de `count_was_endpoints`
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from capamedia_cli.core.legacy_analyzer import (
    analyze_legacy,
    count_was_endpoints,
    detect_bancs_connection,
)


def _write_wsdl(path: Path, op_names: list[str], with_binding: bool = True) -> None:
    """Escribe un WSDL minimo con las ops solicitadas en portType."""
    ops_portType = "\n".join(f'    <wsdl:operation name="{n}"/>' for n in op_names)
    ops_binding = ""
    if with_binding:
        ops_binding_lines = "\n".join(f'    <wsdl:operation name="{n}"/>' for n in op_names)
        ops_binding = f"""
  <wsdl:binding name="B" type="tns:P">
{ops_binding_lines}
  </wsdl:binding>
"""
    path.write_text(
        f"""<?xml version="1.0"?>
<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" targetNamespace="urn:test">
  <wsdl:portType name="P">
{ops_portType}
  </wsdl:portType>{ops_binding}
</wsdl:definitions>
""",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Matriz de decision: 7 filas
# ---------------------------------------------------------------------------


def test_iib_con_bancs_1_op(tmp_path: Path) -> None:
    """IIB + BANCS + 1 op -> rest (natural por op count tambien)."""
    legacy = tmp_path / "legacy"
    (legacy / "src").mkdir(parents=True)
    (legacy / "src" / "flow.esql").write_text(
        "CREATE COMPUTE MODULE T SET x = UMPClientes0002; END MODULE;", encoding="utf-8"
    )
    _write_wsdl(legacy / "svc.wsdl", ["op1"])
    analysis = analyze_legacy(legacy, "wsclientes0001")
    assert analysis.source_kind == "iib"
    assert analysis.has_bancs is True
    assert analysis.framework_recommendation == "rest"


def test_iib_con_bancs_2_ops_override(tmp_path: Path) -> None:
    """IIB + BANCS + 2+ ops -> rest (override gana sobre op count)."""
    legacy = tmp_path / "legacy"
    (legacy / "src").mkdir(parents=True)
    (legacy / "src" / "flow.esql").write_text(
        "SET ump = 'UMPClientes0002'; CALL UMPClientes0020.doStuff();", encoding="utf-8"
    )
    _write_wsdl(legacy / "svc.wsdl", ["op1", "op2"])
    analysis = analyze_legacy(legacy, "wsclientes0001")
    assert analysis.source_kind == "iib"
    assert analysis.has_bancs is True
    assert analysis.framework_recommendation == "rest"


def test_iib_sin_bancs_1_op(tmp_path: Path) -> None:
    """IIB sin BANCS + 1 op -> rest (por op count)."""
    legacy = tmp_path / "legacy"
    (legacy / "src").mkdir(parents=True)
    (legacy / "src" / "flow.esql").write_text(
        "CREATE COMPUTE MODULE Noop END MODULE;", encoding="utf-8"
    )
    _write_wsdl(legacy / "svc.wsdl", ["op1"])
    analysis = analyze_legacy(legacy, "wsclientes0001")
    assert analysis.source_kind == "iib"
    assert analysis.has_bancs is False
    assert analysis.framework_recommendation == "rest"


def test_iib_sin_bancs_2_ops_soap(tmp_path: Path) -> None:
    """IIB sin BANCS + 2+ ops -> soap (op count decide)."""
    legacy = tmp_path / "legacy"
    (legacy / "src").mkdir(parents=True)
    (legacy / "src" / "flow.esql").write_text(
        "CREATE COMPUTE MODULE Simple END MODULE;", encoding="utf-8"
    )
    _write_wsdl(legacy / "svc.wsdl", ["op1", "op2"])
    analysis = analyze_legacy(legacy, "wsclientes0001")
    assert analysis.source_kind == "iib"
    assert analysis.has_bancs is False
    assert analysis.framework_recommendation == "soap"


def test_was_con_1_endpoint_rest(tmp_path: Path) -> None:
    """WAS + 1 endpoint -> rest (framework recommendation rest)."""
    legacy = tmp_path / "legacy"
    src = legacy / "src" / "main" / "java" / "com" / "pichincha" / "svc"
    src.mkdir(parents=True)
    (src / "Foo.java").write_text(
        "package com.pichincha.svc; public class Foo { }", encoding="utf-8"
    )
    web_inf = legacy / "WebContent" / "WEB-INF"
    web_inf.mkdir(parents=True)
    (web_inf / "web.xml").write_text(
        "<web-app><servlet><servlet-class>com.pichincha.svc.Foo</servlet-class></servlet></web-app>",
        encoding="utf-8",
    )
    _write_wsdl(legacy / "svc.wsdl", ["op1"])
    analysis = analyze_legacy(legacy, "wsclientes0045")
    assert analysis.source_kind == "was"
    assert analysis.framework_recommendation == "rest"


def test_was_con_2_endpoints_soap(tmp_path: Path) -> None:
    """WAS + 2+ endpoints -> soap."""
    legacy = tmp_path / "legacy"
    src = legacy / "src" / "main" / "java" / "com" / "pichincha" / "svc"
    src.mkdir(parents=True)
    (src / "Foo.java").write_text(
        "package com.pichincha.svc; public class Foo { }", encoding="utf-8"
    )
    web_inf = legacy / "WebContent" / "WEB-INF"
    web_inf.mkdir(parents=True)
    (web_inf / "web.xml").write_text(
        "<web-app><servlet><servlet-class>com.pichincha.svc.Foo</servlet-class></servlet></web-app>",
        encoding="utf-8",
    )
    _write_wsdl(legacy / "svc.wsdl", ["op1", "op2"])
    analysis = analyze_legacy(legacy, "wsclientes0045")
    assert analysis.source_kind == "was"
    assert analysis.framework_recommendation == "soap"


def test_orq_always_rest(tmp_path: Path) -> None:
    """ORQ siempre rest, sin importar op count."""
    legacy = tmp_path / "legacy"
    (legacy / "src").mkdir(parents=True)
    (legacy / "src" / "orq.msgflow").write_text(
        "<msgflow>IniciarOrquestacionSOAP</msgflow>", encoding="utf-8"
    )
    _write_wsdl(legacy / "svc.wsdl", ["op1", "op2", "op3"])
    analysis = analyze_legacy(legacy, "orqclientes0037")
    assert analysis.source_kind == "orq"
    assert analysis.framework_recommendation == "rest"


# ---------------------------------------------------------------------------
# detect_bancs_connection: 3 senales distintas
# ---------------------------------------------------------------------------


def test_detect_bancs_por_ump(tmp_path: Path) -> None:
    """UMP referenciada en ESQL -> True."""
    (tmp_path / "a.esql").write_text("CALL UMPCuentas0005.x();", encoding="utf-8")
    has_bancs, evidence = detect_bancs_connection(tmp_path)
    assert has_bancs is True
    assert any("UMP" in e for e in evidence)


def test_detect_bancs_por_tx_literal(tmp_path: Path) -> None:
    """TX literal 0NNNNN en ESQL (sin UMPs) -> True."""
    (tmp_path / "a.esql").write_text(
        "CREATE COMPUTE MODULE M SET txId = '067010'; END MODULE;", encoding="utf-8"
    )
    has_bancs, evidence = detect_bancs_connection(tmp_path)
    assert has_bancs is True
    assert any("TX literal" in e for e in evidence)


def test_detect_bancs_por_bancsclient_java(tmp_path: Path) -> None:
    """BancsClient en Java -> True (caso WAS con adapter banco)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "Adapter.java").write_text(
        "import com.pichincha.BancsClient; class A { BancsClient c; }", encoding="utf-8"
    )
    has_bancs, evidence = detect_bancs_connection(tmp_path)
    assert has_bancs is True
    assert any("BancsClient" in e for e in evidence)


def test_detect_bancs_sin_senales(tmp_path: Path) -> None:
    """Nada indica BANCS -> False, evidencia vacia."""
    (tmp_path / "plain.esql").write_text("CREATE MODULE X END MODULE;", encoding="utf-8")
    has_bancs, evidence = detect_bancs_connection(tmp_path)
    assert has_bancs is False
    assert evidence == []


# ---------------------------------------------------------------------------
# count_was_endpoints: WSDL embebido / @WebMethod / metodos publicos
# ---------------------------------------------------------------------------


def test_count_was_endpoints_webmethod_annotation(tmp_path: Path) -> None:
    """Con @WebMethod se cuentan esas anotaciones."""
    web_inf = tmp_path / "WebContent" / "WEB-INF"
    web_inf.mkdir(parents=True)
    (web_inf / "web.xml").write_text(
        "<web-app><servlet><servlet-class>com.pichincha.MiSvc</servlet-class></servlet></web-app>",
        encoding="utf-8",
    )
    src = tmp_path / "src" / "com" / "pichincha"
    src.mkdir(parents=True)
    (src / "MiSvc.java").write_text(
        """
        package com.pichincha;
        public class MiSvc {
            @WebMethod
            public String a() { return ""; }
            @WebMethod
            public String b() { return ""; }
            @WebMethod
            public String c() { return ""; }
        }
        """,
        encoding="utf-8",
    )
    count, source = count_was_endpoints(tmp_path)
    assert count == 3
    assert "MiSvc.java" in source


def test_count_was_endpoints_wsdl_embebido_en_ear(tmp_path: Path) -> None:
    """WSDL embebido en .ear gana sobre la cascada."""
    ear_path = tmp_path / "svc.ear"
    wsdl_content = (
        '<?xml version="1.0"?>'
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">'
        '<wsdl:portType name="P">'
        '<wsdl:operation name="alpha"/>'
        '<wsdl:operation name="beta"/>'
        "</wsdl:portType>"
        "</wsdl:definitions>"
    )
    with zipfile.ZipFile(ear_path, "w") as z:
        z.writestr("META-INF/svc.wsdl", wsdl_content)
    count, source = count_was_endpoints(tmp_path)
    assert count == 2
    assert "svc.ear" in source


def test_count_was_endpoints_publicos_fallback(tmp_path: Path) -> None:
    """Sin @WebMethod cae al fallback de metodos publicos no-getter/setter."""
    web_inf = tmp_path / "WebContent" / "WEB-INF"
    web_inf.mkdir(parents=True)
    (web_inf / "web.xml").write_text(
        "<web-app><servlet><servlet-class>com.pichincha.Plain</servlet-class></servlet></web-app>",
        encoding="utf-8",
    )
    src = tmp_path / "src" / "com" / "pichincha"
    src.mkdir(parents=True)
    (src / "Plain.java").write_text(
        """
        package com.pichincha;
        public class Plain {
            public String consultar(String id) { return ""; }
            public void actualizar(String id) { }
            public String getX() { return ""; }
            public void setX(String v) { }
        }
        """,
        encoding="utf-8",
    )
    count, source = count_was_endpoints(tmp_path)
    assert count == 2
    assert "Plain.java" in source


def test_count_was_endpoints_no_se_puede(tmp_path: Path) -> None:
    """Sin web.xml ni archives -> count 0 y mensaje claro."""
    (tmp_path / "other.txt").write_text("nada", encoding="utf-8")
    count, source = count_was_endpoints(tmp_path)
    assert count == 0
    assert source == "no se pudo determinar"
