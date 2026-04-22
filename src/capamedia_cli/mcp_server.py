"""Local MCP stdio server exposing CapaMedia canonical migration knowledge."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from capamedia_cli import __version__
from capamedia_cli.core.canonical import (
    CANONICAL_ROOT,
    CanonicalAsset,
    load_canonical_assets,
    load_schema,
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "capamedia"


@dataclass(frozen=True)
class IndexedAsset:
    asset_type: str
    name: str
    title: str
    description: str
    body: str
    source: str
    uri: str
    frontmatter: dict[str, Any]
    extra_files: tuple[str, ...]


def _flatten_assets(root: Path | None = None) -> list[IndexedAsset]:
    grouped = load_canonical_assets(root)
    result: list[IndexedAsset] = []
    canonical_root = (root or CANONICAL_ROOT).resolve()
    for asset_type, assets in grouped.items():
        for asset in assets:
            result.append(_index_asset(asset, asset_type, canonical_root))
    return sorted(result, key=lambda item: (item.asset_type, item.name))


def _index_asset(asset: CanonicalAsset, asset_type: str, canonical_root: Path) -> IndexedAsset:
    relative_source = asset.source.resolve().relative_to(canonical_root)
    return IndexedAsset(
        asset_type=asset_type,
        name=asset.name,
        title=asset.title,
        description=asset.description,
        body=asset.body,
        source=relative_source.as_posix(),
        uri=f"capamedia://{asset_type}/{asset.name}",
        frontmatter=dict(asset.frontmatter),
        extra_files=tuple(
            p.resolve().relative_to(canonical_root).as_posix() for p in sorted(asset.extra_files)
        ),
    )


def _match_score(asset: IndexedAsset, query: str) -> int:
    haystacks = [
        asset.name.lower(),
        asset.title.lower(),
        asset.description.lower(),
        asset.source.lower(),
        asset.body.lower(),
    ]
    q = query.lower()
    score = 0
    for idx, haystack in enumerate(haystacks):
        weight = 10 - idx * 2
        if q in haystack:
            score += max(weight, 1)
        score += haystack.count(q)
    return score


def _build_snippet(body: str, query: str, width: int = 240) -> str:
    if not body.strip():
        return ""
    compact = re.sub(r"\s+", " ", body.strip())
    q = query.strip().lower()
    if not q:
        return compact[:width]
    idx = compact.lower().find(q)
    if idx < 0:
        return compact[:width]
    start = max(0, idx - width // 3)
    end = min(len(compact), start + width)
    snippet = compact[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(compact):
        snippet = snippet + "..."
    return snippet


class CapaMediaMCPServer:
    """Very small MCP server tailored to Codex migration workflows."""

    def __init__(self, *, root: Path | None = None, canonical_root: Path | None = None) -> None:
        self.workspace_root = (root or Path.cwd()).resolve()
        self.assets = _flatten_assets(canonical_root)
        self.asset_by_uri = {asset.uri: asset for asset in self.assets}
        self.asset_by_type_name = {(asset.asset_type, asset.name): asset for asset in self.assets}
        self.schema = load_schema()

    def handle(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        params = params or {}
        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"listChanged": False, "subscribe": False},
                },
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self._list_tools()}
        if method == "tools/call":
            return self._call_tool(params)
        if method == "resources/list":
            return {"resources": self._list_resources()}
        if method == "resources/read":
            return self._read_resource(params)
        if method == "logging/setLevel":
            return {}
        raise ValueError(f"Metodo MCP no soportado: {method}")

    def _list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_corpus",
                "description": (
                    "Busca prompts, agentes, skills y contexto canonicos de CapaMedia por texto libre."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "asset_type": {
                            "type": "string",
                            "enum": ["prompt", "agent", "skill", "context"],
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_asset",
                "description": "Devuelve el contenido completo y metadata de un asset canonico.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "uri": {"type": "string"},
                        "name": {"type": "string"},
                        "asset_type": {
                            "type": "string",
                            "enum": ["prompt", "agent", "skill", "context"],
                        },
                    },
                },
            },
            {
                "name": "list_assets",
                "description": "Lista los assets canonicos disponibles para la migracion.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "asset_type": {
                            "type": "string",
                            "enum": ["prompt", "agent", "skill", "context"],
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                    },
                },
            },
            {
                "name": "get_schema",
                "description": "Devuelve el schema canonico del toolkit CapaMedia.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_workspace_overview",
                "description": (
                    "Resume el estado del workspace actual: servicio, harnesses activos y metadata de Fabrics."
                ),
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name", "")).strip()
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("arguments debe ser un objeto")

        if name == "search_corpus":
            payload = self._tool_search(arguments)
        elif name == "get_asset":
            payload = self._tool_get_asset(arguments)
        elif name == "list_assets":
            payload = self._tool_list_assets(arguments)
        elif name == "get_schema":
            payload = self.schema
        elif name == "get_workspace_overview":
            payload = self._tool_workspace_overview()
        else:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Tool desconocido: {name}"}],
            }

        return {
            "content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=True)}]
        }

    def _tool_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("query es requerido")
        limit = max(1, min(int(arguments.get("limit", 5)), 20))
        asset_type = str(arguments.get("asset_type", "")).strip()
        candidates = self.assets
        if asset_type:
            candidates = [asset for asset in candidates if asset.asset_type == asset_type]

        ranked = [(asset, _match_score(asset, query)) for asset in candidates]
        ranked = [item for item in ranked if item[1] > 0]
        ranked.sort(key=lambda item: (-item[1], item[0].asset_type, item[0].name))

        return {
            "query": query,
            "results": [
                {
                    "asset_type": asset.asset_type,
                    "name": asset.name,
                    "title": asset.title,
                    "description": asset.description,
                    "uri": asset.uri,
                    "source": asset.source,
                    "score": score,
                    "snippet": _build_snippet(asset.body, query),
                }
                for asset, score in ranked[:limit]
            ],
        }

    def _tool_get_asset(self, arguments: dict[str, Any]) -> dict[str, Any]:
        uri = str(arguments.get("uri", "")).strip()
        name = str(arguments.get("name", "")).strip()
        asset_type = str(arguments.get("asset_type", "")).strip()

        asset: IndexedAsset | None = None
        if uri:
            asset = self.asset_by_uri.get(uri)
        elif name and asset_type:
            asset = self.asset_by_type_name.get((asset_type, name))
        elif name:
            matches = [entry for entry in self.assets if entry.name == name]
            if len(matches) == 1:
                asset = matches[0]
            elif len(matches) > 1:
                raise ValueError(f"El nombre '{name}' es ambiguo; pasa asset_type o uri")
        if asset is None:
            raise ValueError("No encontre el asset pedido")

        return {
            "asset_type": asset.asset_type,
            "name": asset.name,
            "title": asset.title,
            "description": asset.description,
            "uri": asset.uri,
            "source": asset.source,
            "frontmatter": asset.frontmatter,
            "extra_files": list(asset.extra_files),
            "body": asset.body,
        }

    def _tool_list_assets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        asset_type = str(arguments.get("asset_type", "")).strip()
        limit = max(1, min(int(arguments.get("limit", 50)), 200))
        assets = self.assets
        if asset_type:
            assets = [asset for asset in assets if asset.asset_type == asset_type]
        return {
            "count": len(assets),
            "items": [
                {
                    "asset_type": asset.asset_type,
                    "name": asset.name,
                    "title": asset.title,
                    "description": asset.description,
                    "uri": asset.uri,
                    "source": asset.source,
                }
                for asset in assets[:limit]
            ],
        }

    def _tool_workspace_overview(self) -> dict[str, Any]:
        workspace = self.workspace_root
        config_path = workspace / ".capamedia" / "config.yaml"
        fabrics_path = workspace / ".capamedia" / "fabrics.json"
        service_name = workspace.name
        active_ai: list[str] = []
        if config_path.exists():
            try:
                data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                service_name = str(data.get("service_name") or service_name)
                active_ai = [str(item) for item in data.get("ai", []) if item]
            except (OSError, yaml.YAMLError):
                pass

        fabrics: dict[str, Any] | None = None
        if fabrics_path.exists():
            try:
                raw = json.loads(fabrics_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    fabrics = raw
            except (OSError, json.JSONDecodeError):
                fabrics = None

        return {
            "workspace_root": str(workspace),
            "service_name": service_name,
            "active_ai": active_ai,
            "paths": {
                "capamedia_config": str(config_path) if config_path.exists() else None,
                "fabrics_metadata": str(fabrics_path) if fabrics_path.exists() else None,
                "codex_config": str(workspace / ".codex" / "config.toml")
                if (workspace / ".codex" / "config.toml").exists()
                else None,
            },
            "fabrics": fabrics,
        }

    def _list_resources(self) -> list[dict[str, Any]]:
        resources = [
            {
                "uri": "capamedia://schema",
                "name": "schema",
                "description": "Schema canonico del toolkit CapaMedia",
                "mimeType": "application/json",
            }
        ]
        for asset in self.assets:
            resources.append(
                {
                    "uri": asset.uri,
                    "name": asset.name,
                    "description": f"{asset.asset_type}: {asset.title}",
                    "mimeType": "text/markdown",
                }
            )
        return resources

    def _read_resource(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = str(params.get("uri", "")).strip()
        if uri == "capamedia://schema":
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(self.schema, indent=2, ensure_ascii=True),
                    }
                ]
            }
        asset = self.asset_by_uri.get(uri)
        if asset is None:
            raise ValueError(f"Resource no encontrado: {uri}")
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "text/markdown",
                    "text": self._render_asset_resource(asset),
                }
            ]
        }

    def _render_asset_resource(self, asset: IndexedAsset) -> str:
        parts = [
            f"# {asset.title}",
            "",
            f"- asset_type: `{asset.asset_type}`",
            f"- name: `{asset.name}`",
            f"- source: `{asset.source}`",
        ]
        if asset.description:
            parts.append(f"- description: {asset.description}")
        if asset.extra_files:
            parts.append(f"- extra_files: {', '.join(asset.extra_files)}")
        parts.append("")
        parts.append(asset.body)
        return "\n".join(parts)


def _write_message(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _error_payload(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _run_stdio_server(root: Path | None = None) -> int:
    server = CapaMediaMCPServer(root=root)
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue

        method = message.get("method")
        req_id = message.get("id")
        if not isinstance(method, str):
            if req_id is not None:
                _write_message(_error_payload(req_id, -32600, "Request invalido"))
            continue

        if req_id is None:
            if method == "notifications/initialized":
                continue
            if method == "exit":
                return 0
            continue

        try:
            result = server.handle(method, message.get("params"))
        except ValueError as exc:
            _write_message(_error_payload(req_id, -32602, str(exc)))
            continue
        except Exception as exc:
            _write_message(_error_payload(req_id, -32000, str(exc)))
            continue

        _write_message({"jsonrpc": "2.0", "id": req_id, "result": result})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CapaMedia MCP stdio server")
    parser.add_argument("--root", type=Path, help="Workspace root to inspect")
    args = parser.parse_args(argv)
    return _run_stdio_server(root=args.root)


if __name__ == "__main__":
    raise SystemExit(main())
