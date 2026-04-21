"""Tests para el detector de caveats (v0.3.1)."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.caveats import (
    Caveat,
    caveats_summary,
    caveats_to_markdown_table,
    detect_external_endpoints,
    detect_non_bancs_caveats,
    detect_orq_dependencies,
    detect_ump_caveats,
)
from capamedia_cli.core.legacy_analyzer import LegacyAnalysis, UmpInfo


def test_detect_ump_caveats_not_cloned() -> None:
    analysis = LegacyAnalysis(
        source_kind="iib",
        wsdl=None,
        umps=[
            UmpInfo(name="UMPGood", tx_codes=["060480"], repo_path=Path("/tmp/x")),
            UmpInfo(name="UMPBroken", tx_codes=[], repo_path=None),
        ],
        framework_recommendation="rest",
        complexity="medium",
    )
    caveats = detect_ump_caveats(analysis)
    assert any(c.kind == "ump_not_cloned" and c.target == "UMPBroken" for c in caveats)
    assert not any(c.target == "UMPGood" for c in caveats)


def test_detect_ump_caveats_tx_not_extracted() -> None:
    analysis = LegacyAnalysis(
        source_kind="iib",
        wsdl=None,
        umps=[UmpInfo(name="UMPNoTx", tx_codes=[], repo_path=Path("/tmp/x"))],
        framework_recommendation="rest",
        complexity="low",
    )
    caveats = detect_ump_caveats(analysis)
    assert any(c.kind == "tx_not_extracted" and c.target == "UMPNoTx" for c in caveats)


def test_detect_external_endpoints_skips_bank_domain(tmp_path: Path) -> None:
    esql = tmp_path / "test.esql"
    esql.write_text(
        """
        SET url = 'https://internal.bpichincha.com/api/v1';
        SET externalUrl = 'https://api.equifax.com/v2/score';
        SET local = 'http://localhost:8080/test';
        """,
        encoding="utf-8",
    )
    caveats = detect_external_endpoints(tmp_path)
    targets = [c.target for c in caveats]
    assert "api.equifax.com" in targets
    assert not any("bpichincha" in t for t in targets)
    assert not any("localhost" in t for t in targets)


def test_detect_orq_dependencies_finds_delegations(tmp_path: Path) -> None:
    msgflow = tmp_path / "orq.msgflow"
    msgflow.write_text(
        """
        <node>IniciarOrquestacionSOAP</node>
        <target>WSClientes0007</target>
        <target>WSCuentas0012</target>
        """,
        encoding="utf-8",
    )
    deps, is_orq = detect_orq_dependencies(tmp_path, "ORQTransferencias0003")
    assert is_orq is True
    assert "WSClientes0007" in deps
    assert "WSCuentas0012" in deps


def test_detect_orq_dependencies_non_orq_returns_empty(tmp_path: Path) -> None:
    esql = tmp_path / "ws.esql"
    esql.write_text("SET ump = 'UMPClientes0002';", encoding="utf-8")
    deps, is_orq = detect_orq_dependencies(tmp_path, "WSClientes0007")
    assert is_orq is False


def test_caveats_summary_counts_by_kind() -> None:
    caveats = [
        Caveat("ump_not_cloned", "UMP1", "", ""),
        Caveat("ump_not_cloned", "UMP2", "", ""),
        Caveat("tx_not_extracted", "UMP3", "", ""),
    ]
    summary = caveats_summary(caveats)
    assert summary["ump_not_cloned"] == 2
    assert summary["tx_not_extracted"] == 1


def test_caveats_to_markdown_table_empty() -> None:
    md = caveats_to_markdown_table([])
    assert "(ninguno)" in md


def test_caveats_to_markdown_table_with_data() -> None:
    md = caveats_to_markdown_table(
        [Caveat("ump_not_cloned", "UMPX", "detail", "fix manual")]
    )
    assert "UMPX" in md
    assert "ump_not_cloned" in md


def test_read_xlsx_services_skips_header(tmp_path: Path) -> None:
    """Smoke test: si openpyxl esta instalado, podemos leer xlsx."""
    try:
        from openpyxl import Workbook
    except ImportError:
        return  # openpyxl no instalado, skip

    wb = Workbook()
    ws = wb.active
    ws.append(["servicio"])  # header
    ws.append(["wsclientes0007"])
    ws.append(["wsclientes0030"])
    ws.append([None])  # empty
    ws.append(["# comentario"])
    xlsx_path = tmp_path / "services.xlsx"
    wb.save(xlsx_path)

    from capamedia_cli.commands.batch import _read_services_file

    result = _read_services_file(xlsx_path)
    assert result == ["wsclientes0007", "wsclientes0030"]
