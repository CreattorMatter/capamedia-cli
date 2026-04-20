"""Localiza y arranca el MCP Fabrics del banco.

Estrategia:
  1. Leer `.mcp.json` del workspace actual (o del home del usuario).
  2. Usar el `command + args + env` registrado ahi.
  3. Alternativamente, buscar el package cacheado por npx en
     ~/AppData/Local/npm-cache/_npx/<hash>/node_modules/@pichincha/fabrics-project/dist/index.js
     y lanzarlo con `node` directo (mas rapido y no requiere .npmrc fresco).

NOTA DE NAMING (inconsistencia interna del banco):
  - El npm package se llama `@pichincha/fabrics-project`.
  - El MCP server reporta internamente serverInfo.name = `azure-project-manager`.
  - El tool expuesto se llama `create_project_with_wsdl`.
  - Los tres nombres se refieren al MISMO componente (el "Fabrics" del banco).
  Si ves "azure-project-manager" en logs, es el MCP Fabrics.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import NamedTuple


class MCPLaunchSpec(NamedTuple):
    command: list[str]
    env: dict[str, str]
    source: str  # "cache" | "mcp.json-project" | "mcp.json-home"


MCP_PACKAGE = "@pichincha/fabrics-project"


def _find_cached_mcp() -> Path | None:
    """Busca el package cacheado por npx."""
    cache_root = Path.home() / "AppData" / "Local" / "npm-cache" / "_npx"
    if not cache_root.exists():
        return None
    for hash_dir in cache_root.iterdir():
        if not hash_dir.is_dir():
            continue
        entry = hash_dir / "node_modules" / "@pichincha" / "fabrics-project" / "dist" / "index.js"
        if entry.exists():
            return entry
    return None


def _read_mcp_config(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _candidate_mcp_jsons(cwd: Path) -> list[tuple[Path, str]]:
    return [
        (cwd / ".mcp.json", "mcp.json-project"),
        (cwd.parent / ".mcp.json", "mcp.json-project"),  # workspace padre
        (Path.home() / ".mcp.json", "mcp.json-home"),
    ]


def locate(cwd: Path | None = None, prefer_cache: bool = True) -> MCPLaunchSpec:
    """Find the MCP fabrics server and return how to launch it.

    Si `prefer_cache=True`, intenta primero el cache npx (no requiere .npmrc valido).
    Si no hay cache, cae a `.mcp.json` que usa `npx @latest` (requiere .npmrc valido).
    """
    base_cwd = cwd or Path.cwd()

    # 1. Intentar cache local (no requiere .npmrc)
    if prefer_cache:
        cached = _find_cached_mcp()
        if cached:
            env = os.environ.copy()
            # Si hay .mcp.json con token, inyectar al env (el MCP lo necesita para
            # operaciones Azure Artifacts posteriores aunque el paquete ya este bajado)
            for p, _ in _candidate_mcp_jsons(base_cwd):
                cfg = _read_mcp_config(p)
                if cfg and "fabrics" in cfg.get("mcpServers", {}):
                    fabric_env = cfg["mcpServers"]["fabrics"].get("env", {})
                    for k, v in fabric_env.items():
                        env[k] = v
                    break
            return MCPLaunchSpec(command=["node", str(cached)], env=env, source="cache")

    # 2. Caer a .mcp.json - requiere npx y .npmrc valido
    for p, src in _candidate_mcp_jsons(base_cwd):
        cfg = _read_mcp_config(p)
        if not cfg:
            continue
        servers = cfg.get("mcpServers", {})
        if "fabrics" not in servers:
            continue
        fabric = servers["fabrics"]
        cmd = [fabric["command"], *fabric.get("args", [])]
        env = os.environ.copy()
        env.update(fabric.get("env", {}))
        return MCPLaunchSpec(command=cmd, env=env, source=src)

    raise FileNotFoundError(
        "No se encontro el MCP Fabrics. Opciones:\n"
        "  1. Ejecuta 'capamedia fabrics setup' para registrar el MCP en .mcp.json\n"
        "  2. Ejecuta 'npx @pichincha/fabrics-project@latest' una vez para cachearlo\n"
        "     (requiere .npmrc con token Azure Artifacts valido)"
    )
