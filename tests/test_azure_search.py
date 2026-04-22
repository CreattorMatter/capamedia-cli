"""Tests para core/azure_search.py (wrapper Azure DevOps Code Search API)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from capamedia_cli.core.azure_search import (
    AzureCodeSearch,
    AzureSearchError,
    SearchHit,
    group_hits_by_repo,
)

# ---------------------------------------------------------------------------
# SearchHit.from_api_result
# ---------------------------------------------------------------------------


def test_search_hit_from_minimal_api_result() -> None:
    raw = {
        "project": {"name": "tpl-bus-omnicanal"},
        "repository": {"name": "sqb-msa-wsclientes0010"},
        "path": "src/main/esql/foo.esql",
    }
    hit = SearchHit.from_api_result(raw)
    assert hit.project == "tpl-bus-omnicanal"
    assert hit.repo == "sqb-msa-wsclientes0010"
    assert hit.file_path == "src/main/esql/foo.esql"
    assert hit.matches == []


def test_search_hit_extracts_snippets() -> None:
    raw = {
        "project": {"name": "tpl-bus-omnicanal"},
        "repository": {"name": "repo-x"},
        "path": "config.yaml",
        "matches": {
            "content": [
                {"line": {"textRepr": "  ce_bancs_host: ${CE_BANCS_HOST}"}},
                {"line": {"textRepr": "  ccc_timeout: ${CCC_TIMEOUT}"}},
            ]
        },
    }
    hit = SearchHit.from_api_result(raw)
    assert len(hit.matches) == 2
    assert "CE_BANCS_HOST" in hit.matches[0]


def test_search_hit_uses_branch_from_versions() -> None:
    raw = {
        "project": {"name": "p"},
        "repository": {"name": "r"},
        "path": "x",
        "versions": [{"branchName": "develop"}],
    }
    hit = SearchHit.from_api_result(raw)
    assert hit.branch == "develop"


# ---------------------------------------------------------------------------
# AzureCodeSearch
# ---------------------------------------------------------------------------


def test_azure_code_search_requires_pat() -> None:
    with pytest.raises(AzureSearchError, match="PAT requerido"):
        AzureCodeSearch(pat="")
    with pytest.raises(AzureSearchError, match="PAT requerido"):
        AzureCodeSearch(pat="   ")


def test_azure_code_search_endpoint_format() -> None:
    client = AzureCodeSearch(pat="abc", org="bancopichincha")
    endpoint = client._endpoint()
    assert "almsearch.dev.azure.com" in endpoint
    assert "bancopichincha" in endpoint
    assert "api-version=7.1" in endpoint


def test_azure_code_search_auth_header_basic() -> None:
    client = AzureCodeSearch(pat="mysecret", org="x")
    # base64(":mysecret") = Om15c2VjcmV0
    assert client._auth.startswith("Basic ")
    assert "Om15c2VjcmV0" in client._auth


def test_azure_code_search_success(monkeypatch) -> None:
    client = AzureCodeSearch(pat="abc")

    fake_response_body = {
        "count": 2,
        "results": [
            {
                "project": {"name": "p1"},
                "repository": {"name": "r1"},
                "path": "f1",
                "matches": {"content": [{"line": {"textRepr": "hit1"}}]},
            },
            {
                "project": {"name": "p2"},
                "repository": {"name": "r2"},
                "path": "f2",
                "matches": {"content": [{"line": {"textRepr": "hit2"}}]},
            },
        ],
    }

    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps(fake_response_body).encode("utf-8")
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda self, *args: None

    with patch(
        "capamedia_cli.core.azure_search.urllib.request.urlopen",
        return_value=fake_resp,
    ):
        resp = client.search("wsclientes0010", projects=["tpl-bus-omnicanal"])

    assert resp.count == 2
    assert len(resp.hits) == 2
    assert resp.hits[0].project == "p1"


def test_azure_code_search_http_error(monkeypatch) -> None:
    import urllib.error

    client = AzureCodeSearch(pat="abc")
    err = urllib.error.HTTPError(
        url="x", code=401, msg="Unauthorized", hdrs=None, fp=None
    )
    err.read = lambda: b"invalid PAT"

    with (
        patch(
            "capamedia_cli.core.azure_search.urllib.request.urlopen",
            side_effect=err,
        ),
        pytest.raises(AzureSearchError, match="HTTP 401"),
    ):
        client.search("x")


def test_azure_code_search_network_error(monkeypatch) -> None:
    import urllib.error

    client = AzureCodeSearch(pat="abc")
    with (
        patch(
            "capamedia_cli.core.azure_search.urllib.request.urlopen",
            side_effect=urllib.error.URLError("DNS fail"),
        ),
        pytest.raises(AzureSearchError, match="Red"),
    ):
        client.search("x")


# ---------------------------------------------------------------------------
# group_hits_by_repo
# ---------------------------------------------------------------------------


def test_group_hits_by_repo() -> None:
    hits = [
        SearchHit(project="p1", repo="r1", file_path="f1"),
        SearchHit(project="p1", repo="r1", file_path="f2"),
        SearchHit(project="p2", repo="r3", file_path="f3"),
    ]
    grouped = group_hits_by_repo(hits)
    assert len(grouped) == 2
    assert len(grouped["p1/r1"]) == 2
    assert len(grouped["p2/r3"]) == 1
