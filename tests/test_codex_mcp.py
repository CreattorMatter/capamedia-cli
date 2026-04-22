"""Tests for the internal Codex MCP integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from capamedia_cli.commands.mcp import setup_mcp
from capamedia_cli.core.codex_mcp import (
    DEFAULT_CAPAMEDIA_MCP_SERVER,
    build_capamedia_mcp_server_config,
    load_codex_config,
)
from capamedia_cli.core.mcp_client import MCPClient


def test_build_capamedia_mcp_server_config_pins_workspace_root(tmp_path: Path) -> None:
    config = build_capamedia_mcp_server_config(tmp_path)

    assert config["enabled"] is True
    assert "--root" in config["args"]
    assert str(tmp_path.resolve()) in config["args"]


def test_setup_mcp_writes_project_scoped_codex_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    setup_mcp(scope="project", config=None, root=None, force=False, required=False)

    config_path = tmp_path / ".codex" / "config.toml"
    data = load_codex_config(config_path)
    assert DEFAULT_CAPAMEDIA_MCP_SERVER in data["mcp_servers"]
    assert str(tmp_path.resolve()) in data["mcp_servers"][DEFAULT_CAPAMEDIA_MCP_SERVER]["args"]


def test_capamedia_mcp_server_smoke() -> None:
    with MCPClient(
        [sys.executable, "-m", "capamedia_cli.mcp_server"],
        cwd=str(Path.cwd()),
    ) as client:
        info = client.initialize()
        tools = client.list_tools()
        tool_names = {tool.name for tool in tools}
        search = client.call_tool("search_corpus", {"query": "fabrics", "limit": 3})
        schema = client.call_tool("get_schema", {})

    assert info["serverInfo"]["name"] == "capamedia"
    assert {"search_corpus", "get_asset", "list_assets", "get_schema", "get_workspace_overview"} <= tool_names

    search_payload = json.loads(search["content"][0]["text"])
    assert search_payload["results"]
    assert any(item["uri"].startswith("capamedia://") for item in search_payload["results"])

    schema_payload = json.loads(schema["content"][0]["text"])
    assert isinstance(schema_payload, dict)
