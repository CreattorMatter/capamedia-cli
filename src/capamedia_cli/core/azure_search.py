"""Wrapper minimo del Azure DevOps Code Search API.

Usado por `capamedia clone --deep-scan` para recolectar evidencia sobre un
servicio: ConfigMaps, Helm values, YAMLs, variables CE_*/CCC_*, referencias
cruzadas de TX/UMPs, etc. Sin esto, la AI migra con lo que infiere del legacy
y alucina valores. Con esto, los valores son exactos.

Docs: https://learn.microsoft.com/en-us/rest/api/azure/devops/search/code-search-results
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

DEFAULT_ORG = "bancopichincha"
ALL_PROJECTS = (
    "tpl-bus-omnicanal",
    "tpl-integration-services-was",
    "tpl-integrationbus-config",
    "tpl-middleware",
)


@dataclass
class SearchHit:
    """Un match de Code Search."""

    project: str
    repo: str
    file_path: str
    line_numbers: list[int] = field(default_factory=list)
    matches: list[str] = field(default_factory=list)
    branch: str = "main"

    @classmethod
    def from_api_result(cls, result: dict[str, Any]) -> SearchHit:
        project = result.get("project", {}).get("name", "?")
        repo = result.get("repository", {}).get("name", "?")
        path = result.get("path", "?")
        branch = result.get("versions", [{}])[0].get("branchName", "main")
        # matches: list of {"charOffset": N, "length": M, "line": {"charOffset": ..., "length": ..., "textRepr": "..."}}
        matches_raw = result.get("matches", {}).get("content", [])
        lines: list[int] = []
        snippets: list[str] = []
        for m in matches_raw:
            line_info = m.get("line", {})
            text = line_info.get("textRepr") or m.get("textRepr") or ""
            if text:
                snippets.append(text.strip()[:200])
            # La API no siempre da line numbers directos; deduce por offset si existe
            char_offset = m.get("charOffset")
            if isinstance(char_offset, int):
                lines.append(char_offset)
        return cls(
            project=project,
            repo=repo,
            file_path=path,
            line_numbers=lines,
            matches=snippets,
            branch=branch,
        )


@dataclass
class SearchResponse:
    """Resultado agregado de una query."""

    count: int
    hits: list[SearchHit]
    raw: dict[str, Any] = field(default_factory=dict)


class AzureSearchError(Exception):
    """Error de red, auth o del API de Code Search."""


class AzureCodeSearch:
    """Cliente minimal. No side-effects, solo HTTP POST + parse.

    Uso:
        client = AzureCodeSearch(pat="...", org="bancopichincha")
        resp = client.search("WSClientes0010", projects=["tpl-bus-omnicanal"])
        for hit in resp.hits:
            ...
    """

    API_VERSION = "7.1"

    def __init__(
        self,
        pat: str,
        *,
        org: str = DEFAULT_ORG,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not pat or not pat.strip():
            raise AzureSearchError("PAT requerido para Code Search")
        self._pat = pat.strip()
        self._org = org
        self._timeout = timeout_seconds
        self._auth = self._build_auth_header()

    def _build_auth_header(self) -> str:
        basic = base64.b64encode(f":{self._pat}".encode()).decode("ascii")
        return f"Basic {basic}"

    def _endpoint(self) -> str:
        return (
            f"https://almsearch.dev.azure.com/{self._org}/"
            f"_apis/search/codesearchresults?api-version={self.API_VERSION}"
        )

    def search(
        self,
        query: str,
        *,
        projects: list[str] | None = None,
        top: int = 50,
        skip: int = 0,
    ) -> SearchResponse:
        """Ejecuta una query y devuelve hits parseados."""
        body: dict[str, Any] = {
            "searchText": query,
            "$skip": skip,
            "$top": min(top, 200),
            "includeFacets": False,
            "filters": {},
        }
        if projects:
            body["filters"]["Project"] = projects

        req = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": self._auth,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "capamedia-cli/deep-scan",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="ignore")[:300]
            except Exception:
                detail = ""
            raise AzureSearchError(
                f"HTTP {exc.code} al buscar '{query}': {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise AzureSearchError(f"Red: {exc.reason}") from exc
        except TimeoutError as exc:
            raise AzureSearchError(
                f"Timeout ({self._timeout:.0f}s) al buscar '{query}'"
            ) from exc
        except json.JSONDecodeError as exc:
            raise AzureSearchError(f"Response no es JSON: {exc}") from exc

        results = raw.get("results", [])
        hits = [SearchHit.from_api_result(r) for r in results]
        count = int(raw.get("count") or len(hits))
        return SearchResponse(count=count, hits=hits, raw=raw)

    def search_all_projects(self, query: str, *, top: int = 50) -> SearchResponse:
        """Search en los 4 proyectos conocidos del banco."""
        return self.search(query, projects=list(ALL_PROJECTS), top=top)


def group_hits_by_repo(hits: list[SearchHit]) -> dict[str, list[SearchHit]]:
    """Agrupa hits por `project/repo` para reporting."""
    out: dict[str, list[SearchHit]] = {}
    for h in hits:
        key = f"{h.project}/{h.repo}"
        out.setdefault(key, []).append(h)
    return out
