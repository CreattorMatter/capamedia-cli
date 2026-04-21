"""Tests de soporte para pipeline batch."""

from __future__ import annotations

import json
from pathlib import Path

from capamedia_cli.commands.fabrics import _artifact_env_from_mcp, _resolve_legacy_root
from capamedia_cli.commands.init import scaffold_project
from capamedia_cli.core.mcp_launcher import locate


def test_scaffold_project_generates_codex_assets(tmp_path: Path) -> None:
    target = tmp_path / "wsclientes0007"

    total_files, warnings = scaffold_project(
        target_dir=target,
        service_name="wsclientes0007",
        harnesses=["codex"],
        artifact_token=None,
    )

    assert total_files > 0
    assert isinstance(warnings, list)
    assert (target / ".capamedia" / "config.yaml").exists()
    assert (target / ".codex" / "prompts" / "migrate.md").exists()
    assert (target / "AGENTS.md").exists()
    assert (target / ".mcp.json").exists()
    assert '"command": "npx"' in (target / ".mcp.json").read_text(encoding="utf-8")


def test_resolve_legacy_root_prefers_workspace_then_local_fallback(tmp_path: Path) -> None:
    workspace = tmp_path / "CapaMedia" / "wsclientes0007"
    local_fallback = tmp_path / "CapaMedia" / "0007" / "legacy" / "sqb-msa-wsclientes0007"
    local_fallback.mkdir(parents=True)
    workspace.mkdir(parents=True)

    assert _resolve_legacy_root("WSClientes0007", workspace) == local_fallback

    local_workspace_legacy = workspace / "legacy" / "sqb-msa-wsclientes0007"
    local_workspace_legacy.mkdir(parents=True)
    assert _resolve_legacy_root("WSClientes0007", workspace) == local_workspace_legacy


def test_artifact_env_from_mcp_uses_home_when_workspace_has_placeholder(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "CapaMedia" / "wsclientes0007"
    workspace.mkdir(parents=True)
    (workspace / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fabrics": {
                        "command": "cmd",
                        "args": ["/c", "npx", "@pichincha/fabrics-project@latest"],
                        "env": {
                            "ARTIFACT_USERNAME": "BancoPichinchaEC",
                            "ARTIFACT_TOKEN": "${CAPAMEDIA_ARTIFACT_TOKEN}",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    home.mkdir()
    (home / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fabrics": {
                        "command": "cmd",
                        "args": ["/c", "npx", "@pichincha/fabrics-project@latest"],
                        "env": {
                            "ARTIFACT_USERNAME": "BancoPichinchaEC",
                            "ARTIFACT_TOKEN": "real-token",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.delenv("CAPAMEDIA_ARTIFACT_TOKEN", raising=False)

    env = _artifact_env_from_mcp(workspace)

    assert env["ARTIFACT_TOKEN"] == "real-token"


def test_locate_resolves_placeholder_from_env(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "CapaMedia" / "wsclientes0008"
    workspace.mkdir(parents=True)
    (workspace / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fabrics": {
                        "command": "cmd",
                        "args": ["/c", "npx", "@pichincha/fabrics-project@latest"],
                        "env": {
                            "ARTIFACT_USERNAME": "BancoPichinchaEC",
                            "ARTIFACT_TOKEN": "${CAPAMEDIA_ARTIFACT_TOKEN}",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAPAMEDIA_ARTIFACT_TOKEN", "token-from-env")

    spec = locate(workspace, prefer_cache=False)

    assert spec.source == "mcp.json-project"
    assert spec.env["ARTIFACT_TOKEN"] == "token-from-env"


def test_locate_finds_cached_mcp_in_unix_npm_cache(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    cached = home / ".npm" / "_npx" / "abc123" / "node_modules" / "@pichincha" / "fabrics-project" / "dist"
    cached.mkdir(parents=True)
    (cached / "index.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    spec = locate(tmp_path, prefer_cache=True)

    assert spec.source == "cache"
    assert spec.command[0] == "node"
    assert spec.command[1].endswith("index.js")
