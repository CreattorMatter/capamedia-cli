"""Helpers to wire the local CapaMedia MCP server into Codex config.toml."""

from __future__ import annotations

import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

DEFAULT_CAPAMEDIA_MCP_SERVER = "capamedia"

_KEY_ALIASES = {
    "approval-policy": "approval_policy",
    "model-reasoning-effort": "model_reasoning_effort",
    "project-doc-fallback-filenames": "project_doc_fallback_filenames",
    "sandbox-mode": "sandbox_mode",
    "sandbox-workspace-write": "sandbox_workspace_write",
}


def resolve_capamedia_mcp_launcher() -> tuple[str, list[str]]:
    """Resolve the most stable command to launch the local MCP server."""
    capamedia_bin = shutil.which("capamedia")
    if capamedia_bin:
        return capamedia_bin, ["mcp", "serve"]
    return sys.executable, ["-m", "capamedia_cli.mcp_server"]


def build_capamedia_mcp_server_config(
    root: Path | None = None,
    *,
    required: bool = False,
) -> dict[str, Any]:
    """Build a Codex MCP stdio server config for the packaged CapaMedia server."""
    command, args = resolve_capamedia_mcp_launcher()
    payload: dict[str, Any] = {
        "command": command,
        "args": list(args),
        "enabled": True,
        "startup_timeout_sec": 15,
        "tool_timeout_sec": 90,
    }
    if root is not None:
        payload["args"] = [*payload["args"], "--root", str(root.resolve())]
    if required:
        payload["required"] = True
    return payload


def _normalize_aliases(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)
    for legacy_key, current_key in _KEY_ALIASES.items():
        if legacy_key in normalized and current_key not in normalized:
            normalized[current_key] = normalized.pop(legacy_key)
    return normalized


def load_codex_config(path: Path) -> dict[str, Any]:
    """Load config.toml if present, normalizing legacy key aliases."""
    if not path.exists():
        return {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    data = _normalize_aliases(raw)

    profiles = data.get("profiles")
    if isinstance(profiles, dict):
        data["profiles"] = {
            str(name): _normalize_aliases(profile)
            if isinstance(profile, dict)
            else profile
            for name, profile in profiles.items()
        }
    return data


def write_codex_config(path: Path, data: dict[str, Any]) -> None:
    """Write config.toml using TOML output compatible with Codex."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tomli_w.dumps(data).encode("utf-8"))


def ensure_capamedia_mcp_server(
    config: dict[str, Any],
    *,
    root: Path | None = None,
    overwrite: bool = False,
    required: bool = False,
) -> bool:
    """Ensure the CapaMedia MCP server is present in a Codex config payload."""
    servers = config.get("mcp_servers")
    if not isinstance(servers, dict):
        servers = {}
        config["mcp_servers"] = servers

    if DEFAULT_CAPAMEDIA_MCP_SERVER in servers and not overwrite:
        return False

    servers[DEFAULT_CAPAMEDIA_MCP_SERVER] = build_capamedia_mcp_server_config(
        root,
        required=required,
    )
    return True
