"""Tests for the deterministic legacy analyzer."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.legacy_analyzer import (
    BANCS_UMP_PREFIXES,
    _has_bancs_ump,
    analyze_wsdl,
    detect_bancs_connection,
    detect_ump_references,
    extract_tx_codes,
    score_complexity,
)

SAMPLE_WSDL = """<?xml version="1.0" encoding="UTF-8"?>
<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
                  targetNamespace="http://pichincha.com/ws/test">
  <wsdl:types>
    <xsd:schema>
      <xsd:import schemaLocation="common.xsd"/>
    </xsd:schema>
  </wsdl:types>
  <wsdl:portType name="TestPortType">
    <wsdl:operation name="ConsultarCliente01">
      <wsdl:input message="tns:ConsultarClienteRequest"/>
      <wsdl:output message="tns:ConsultarClienteResponse"/>
    </wsdl:operation>
    <wsdl:operation name="ActualizarCliente01">
      <wsdl:input message="tns:ActualizarClienteRequest"/>
    </wsdl:operation>
  </wsdl:portType>
  <wsdl:binding name="TestBinding" type="tns:TestPortType">
    <wsdl:operation name="ConsultarCliente01">
      <soap:operation/>
    </wsdl:operation>
    <wsdl:operation name="ActualizarCliente01">
      <soap:operation/>
    </wsdl:operation>
  </wsdl:binding>
</wsdl:definitions>
"""


def test_wsdl_counts_portType_only_not_binding(tmp_path: Path) -> None:
    """Critical: must count ops in <portType> only, not the binding duplication."""
    wsdl = tmp_path / "test.wsdl"
    wsdl.write_text(SAMPLE_WSDL, encoding="utf-8")
    info = analyze_wsdl(wsdl)
    assert info.operation_count == 2
    assert sorted(info.operation_names) == ["ActualizarCliente01", "ConsultarCliente01"]


def test_wsdl_extracts_namespace(tmp_path: Path) -> None:
    wsdl = tmp_path / "test.wsdl"
    wsdl.write_text(SAMPLE_WSDL, encoding="utf-8")
    assert analyze_wsdl(wsdl).target_namespace == "http://pichincha.com/ws/test"


def test_wsdl_extracts_schema_locations(tmp_path: Path) -> None:
    wsdl = tmp_path / "test.wsdl"
    wsdl.write_text(SAMPLE_WSDL, encoding="utf-8")
    assert "common.xsd" in analyze_wsdl(wsdl).schema_locations


def test_detect_umps_from_esql(tmp_path: Path) -> None:
    esql = tmp_path / "test.esql"
    esql.write_text(
        """
        CREATE COMPUTE MODULE Test
            SET Environment.UMPSubflow.ump = 'UMPClientes0002';
            SET Environment.UMPSubflow.ump = 'UMPClientes0020';
            SET Environment.UMPSubflow.ump = 'UMPCuentas0005';
        END MODULE;
        """,
        encoding="utf-8",
    )
    umps = detect_ump_references(tmp_path)
    assert "UMPClientes0002" in umps
    assert "UMPClientes0020" in umps
    assert "UMPCuentas0005" in umps


def test_extract_tx_codes_from_esql(tmp_path: Path) -> None:
    repo = tmp_path / "ump-repo"
    repo.mkdir()
    esql = repo / "main.esql"
    esql.write_text(
        """
        SET transactionId = '060480';
        SET transactionId = '061404';
        -- Esto no debe contarse como TX (es fecha 2026):
        SET date = '202601';
        """,
        encoding="utf-8",
    )
    codes = extract_tx_codes(repo)
    assert "060480" in codes
    assert "061404" in codes


def test_score_complexity_boundaries() -> None:
    assert score_complexity(1, 0, False) == "low"
    assert score_complexity(1, 2, False) == "medium"
    assert score_complexity(3, 4, True) == "high"


# ---------------------------------------------------------------------------
# detect_bancs_connection — la senal 1 solo cuenta UMPs BANCS (fix WSReglas0010)
# ---------------------------------------------------------------------------


def _write_legacy(tmp_path: Path, name: str, body: str) -> Path:
    f = tmp_path / "legacy" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    return tmp_path / "legacy"


def test_has_bancs_ump_prefix_matching() -> None:
    assert _has_bancs_ump(["UMPClientes0002"]) is True
    assert _has_bancs_ump(["umptransacciones0010"]) is True  # lowercase WAS
    assert _has_bancs_ump(["UMPSeguridad0085"]) is False
    assert _has_bancs_ump(["UMPAutorizadores0001"]) is False
    assert _has_bancs_ump([]) is False
    # nombre compuesto: cuenta como su prefijo base (startswith), no igualdad
    assert _has_bancs_ump(["UMPCuentasAhorro0010"]) is True
    assert _has_bancs_ump(["UMPClientesNaturales0002"]) is True
    assert _has_bancs_ump(["UMPSeguridadAvanzada0085"]) is False
    assert "umpclientes" in BANCS_UMP_PREFIXES


def test_bancs_false_positive_non_bancs_ump(tmp_path: Path) -> None:
    """Caso WSReglas0010: ESQL con solo UMPs no-BANCS y sin TX -> NO es BANCS."""
    legacy = _write_legacy(
        tmp_path,
        "ConsultarSeguridad.esql",
        "CALL UMPSeguridad0085.consultar();\nSET x = UMPGenerico0002;\n",
    )
    has_bancs, evidence = detect_bancs_connection(legacy)
    assert has_bancs is False
    assert evidence == []


def test_bancs_true_with_bancs_ump(tmp_path: Path) -> None:
    """UMP de prefijo BANCS conocido -> es BANCS."""
    legacy = _write_legacy(tmp_path, "flow.esql", "CALL UMPClientes0002.consultar();\n")
    has_bancs, evidence = detect_bancs_connection(legacy)
    assert has_bancs is True
    assert any("UMP BANCS" in e for e in evidence)


def test_bancs_true_with_tx_literal_even_if_ump_unknown(tmp_path: Path) -> None:
    """UMP no-BANCS pero con TX literal 0NNNNN -> la senal 2 (TX) manda."""
    legacy = _write_legacy(
        tmp_path,
        "flow.esql",
        "CALL UMPSeguridad0085.consultar();\nSET tx = '060480';\n",
    )
    has_bancs, evidence = detect_bancs_connection(legacy)
    assert has_bancs is True
    assert any("TX literal" in e for e in evidence)


def test_bancs_true_httprequest_bancs_msgflow(tmp_path: Path) -> None:
    """HTTPRequest a bancs en msgflow -> senal 3 intacta."""
    legacy = _write_legacy(
        tmp_path, "flow.msgflow", "<node type='HTTPRequest' url='http://bancs/core'/>"
    )
    has_bancs, evidence = detect_bancs_connection(legacy)
    assert has_bancs is True
    assert any("HTTPRequest" in e for e in evidence)


def test_bancs_true_bancsclient_java(tmp_path: Path) -> None:
    """BancsClient en Java -> senal 4 intacta."""
    legacy = _write_legacy(tmp_path, "Foo.java", "class Foo { BancsClient c; }")
    has_bancs, evidence = detect_bancs_connection(legacy)
    assert has_bancs is True
    assert any("BancsClient" in e for e in evidence)
