"""Tests para core/dossier.py (build + render del deep-scan)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from capamedia_cli.core.azure_search import (
    AzureSearchError,
    SearchHit,
    SearchResponse,
)
from capamedia_cli.core.dossier import (
    Dossier,
    DossierSection,
    build_dossier,
    render_dossier_markdown,
    render_dossier_prompt_appendix,
    write_dossier,
)


def _hit(project="p", repo="r", file_path="f", snippets=None) -> SearchHit:
    return SearchHit(
        project=project, repo=repo, file_path=file_path, matches=snippets or []
    )


def _fake_client_with_responses(responses: dict[str, list[SearchHit]]) -> MagicMock:
    """Simula un AzureCodeSearch que devuelve lo que le indico por query."""
    client = MagicMock()

    def search(query: str, *, projects=None, top=50):
        hits = responses.get(query, [])
        return SearchResponse(count=len(hits), hits=hits)

    client.search.side_effect = search
    return client


def test_build_dossier_happy_path() -> None:
    client = _fake_client_with_responses(
        {
            "wsclientes0010": [
                _hit(
                    project="tpl-bus-omnicanal",
                    repo="sqb-msa-wsclientes0010",
                    file_path="config.yaml",
                    snippets=["ccc_timeout: ${CCC_TIMEOUT_MS}"],
                ),
            ],
            "060480": [
                _hit(
                    project="tpl-integrationbus-config",
                    repo="sqb-cfg-060480-TX",
                    file_path="tx.xml",
                    snippets=["<trxCode>060480</trxCode>"],
                ),
            ],
        }
    )

    dossier = build_dossier(
        "wsclientes0010",
        client,
        tx_codes=["060480"],
        umps=[],
    )

    assert dossier.service == "wsclientes0010"
    assert dossier.total_hits == 2
    assert "CCC_TIMEOUT_MS" in dossier.ccc_vars
    # 2 secciones: servicio + 1 TX
    assert len(dossier.sections) == 2


def test_build_dossier_extracts_ce_vars() -> None:
    client = _fake_client_with_responses(
        {
            "wsclientes0010": [
                _hit(
                    snippets=[
                        "bancs_host: ${CE_BANCS_HOST}",
                        "timeout: ${CE_BANCS_TIMEOUT_MS}",
                    ]
                ),
            ],
        }
    )
    dossier = build_dossier("wsclientes0010", client, umps=[], tx_codes=[])
    assert "CE_BANCS_HOST" in dossier.ce_vars
    assert "CE_BANCS_TIMEOUT_MS" in dossier.ce_vars


def test_build_dossier_handles_search_error() -> None:
    client = MagicMock()
    client.search.side_effect = AzureSearchError("network fail")
    dossier = build_dossier("svc", client, umps=[], tx_codes=[])
    # No raise; seccion con warning
    assert all(s.warning is not None for s in dossier.sections)
    assert dossier.total_hits == 0


def test_build_dossier_caps_tx_and_umps() -> None:
    """No mas de 10 TX y 10 UMPs por dossier (prevenir abuso)."""
    client = _fake_client_with_responses({})
    many_tx = [f"0{i:05d}" for i in range(20)]
    many_umps = [f"UMPTest00{i:02d}" for i in range(20)]
    dossier = build_dossier("svc", client, tx_codes=many_tx, umps=many_umps)
    # 1 (servicio) + 10 (TX) + 10 (UMP) = 21 secciones max
    assert len(dossier.sections) == 21


def test_render_dossier_markdown_with_hits() -> None:
    dossier = Dossier(
        service="svc-test",
        sections=[
            DossierSection(
                title="Referencias",
                query="svc-test",
                hits=[_hit(project="p1", repo="r1", file_path="a.yaml")],
            )
        ],
        ce_vars={"CE_TEST"},
    )
    md = render_dossier_markdown(dossier)
    assert "# Dossier deep-scan" in md
    assert "svc-test" in md
    assert "CE_TEST" in md
    assert "Referencias" in md
    assert "p1" in md


def test_render_dossier_markdown_empty() -> None:
    dossier = Dossier(service="svc", sections=[])
    md = render_dossier_markdown(dossier)
    assert "svc" in md
    assert "Total hits" in md


def test_render_prompt_appendix_with_evidence() -> None:
    dossier = Dossier(
        service="svc",
        sections=[
            DossierSection(
                title="t",
                query="q",
                hits=[_hit(project="p", repo="r", file_path="f")],
            )
        ],
        ce_vars={"CE_FOO"},
        ccc_vars={"CCC_BAR"},
    )
    appendix = render_dossier_prompt_appendix(dossier)
    assert "Deep-scan: evidencia externa real" in appendix
    assert "CE_FOO" in appendix
    assert "CCC_BAR" in appendix
    assert "NEEDS_HUMAN_CONFIG" in appendix


def test_render_prompt_appendix_empty_evidence() -> None:
    dossier = Dossier(service="svc")
    appendix = render_dossier_prompt_appendix(dossier)
    assert "sin evidencia externa" in appendix.lower()


def test_write_dossier_creates_file(tmp_path: Path) -> None:
    dossier = Dossier(service="svc")
    dossier.sections.append(
        DossierSection(title="t", query="q", hits=[_hit()])
    )
    target = write_dossier(tmp_path, dossier)
    assert target.exists()
    assert target.name == "DOSSIER_svc.md"
    content = target.read_text(encoding="utf-8")
    assert "svc" in content
