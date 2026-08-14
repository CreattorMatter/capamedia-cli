"""Localiza y arranca el MCP Fabrics del banco.

Estrategia (v0.35.1 - el default es SIEMPRE la ultima version publicada):
  1. Leer `.mcp.json` del workspace actual (o del home del usuario) y lanzar
     `npx -y @pichincha/fabrics-project@latest`. npx resuelve el tag `latest`
     contra el registry en cada corrida, asi que el arquetipo se genera con el
     MCP mas nuevo. Si el `.mcp.json` tiene una version pineada, se reescribe a
     `@latest` (ver `_force_latest_args`).
  2. Solo si eso no es viable (sin token / sin npx), caer al package cacheado
     por npx y lanzarlo con `node` directo. Ese fallback NO garantiza la ultima
     version, por eso elige el cache de MAYOR version (no el de mtime mas
     reciente, que es lo que antes hacia correr builds viejos).

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
import re
from pathlib import Path
from typing import NamedTuple


class MCPLaunchSpec(NamedTuple):
    command: list[str]
    env: dict[str, str]
    source: str  # "cache" | "mcp.json-project" | "mcp.json-home"
    version: str = ""  # version npm resuelta (vacio = la resuelve npx en runtime)


MCP_PACKAGE = "@pichincha/fabrics-project"
MCP_SPEC_LATEST = f"{MCP_PACKAGE}@latest"


def _resolve_env_placeholder(value: str) -> str:
    raw = (value or "").strip()
    if raw.startswith("${") and raw.endswith("}"):
        return os.environ.get(raw[2:-1], "").strip()
    return raw


def _is_usable_token(value: str) -> bool:
    """False para vacio, `${VAR}` sin resolver, o placeholders tipo `<pon-tu-token>`."""
    raw = (value or "").strip()
    if not raw:
        return False
    if raw.startswith("${") and raw.endswith("}"):
        return False
    return "<" not in raw


def _resolve_fabrics_env(raw_env: dict[str, str]) -> dict[str, str]:
    env = {str(k): str(v) for k, v in raw_env.items()}
    token = _resolve_env_placeholder(env.get("ARTIFACT_TOKEN", ""))
    if token:
        env["ARTIFACT_TOKEN"] = token
    return env


def _version_key(version: str) -> tuple:
    """Orden semver-ish: 1.0.0 > 1.0.0-alpha.2 > 1.0.0-alpha.1.

    Los builds del banco son `1.0.0-alpha.<timestamp>`, asi que el timestamp
    del prerelease es lo que desempata.
    """
    core, _, pre = (version or "").partition("-")
    core_parts = tuple(int(p) for p in re.findall(r"\d+", core))
    if pre:
        return (core_parts, 0, tuple(int(p) for p in re.findall(r"\d+", pre)))
    return (core_parts, 1, ())


def _read_package_version(pkg_root: Path) -> str:
    try:
        data = json.loads((pkg_root / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("version", "") or "")


def _find_cached_entries() -> list[tuple[str, Path]]:
    """Devuelve [(version, index.js)] de todas las copias cacheadas por npx.

    Ordenado de mayor a menor version. npx guarda cada spec resuelto en un
    `_npx/<hash>` distinto, asi que puede haber varias versiones conviviendo.
    """
    roots: list[Path] = []

    for env_var in ("npm_config_cache", "NPM_CONFIG_CACHE"):
        raw = os.environ.get(env_var, "").strip()
        if raw:
            roots.append(Path(raw))

    roots.extend(
        [
            Path.home() / "AppData" / "Local" / "npm-cache",
            Path.home() / ".npm",
        ]
    )

    seen: set[Path] = set()
    found: list[tuple[str, Path]] = []
    for cache_root in roots:
        if cache_root in seen or not cache_root.exists():
            continue
        seen.add(cache_root)
        npx_root = cache_root / "_npx"
        if not npx_root.exists():
            continue
        for hash_dir in [p for p in npx_root.iterdir() if p.is_dir()]:
            pkg_root = hash_dir / "node_modules" / "@pichincha" / "fabrics-project"
            entry = pkg_root / "dist" / "index.js"
            if entry.exists():
                found.append((_read_package_version(pkg_root), entry))

    found.sort(key=lambda item: _version_key(item[0]), reverse=True)
    return found


def latest_cached_version() -> str:
    """Version mas alta del MCP presente en el cache npx (o "" si no hay)."""
    entries = _find_cached_entries()
    return entries[0][0] if entries else ""


def _find_cached_mcp() -> Path | None:
    """Path al `dist/index.js` cacheado de MAYOR version (o None)."""
    entries = _find_cached_entries()
    return entries[0][1] if entries else None


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


def _force_latest_args(args: list[str], command: str) -> list[str]:
    """Reescribe cualquier spec pineado del MCP a `@latest` y asegura `-y`.

    Sin esto, un `.mcp.json` viejo con `@pichincha/fabrics-project@1.0.0-alpha.X`
    seguiria generando arquetipos con esa build.
    """
    out: list[str] = []
    for arg in args:
        text = str(arg)
        if text == MCP_PACKAGE or text.startswith(f"{MCP_PACKAGE}@"):
            out.append(MCP_SPEC_LATEST)
        else:
            out.append(text)

    if Path(command).name.lower().startswith("npx") and not ({"-y", "--yes"} & set(out)):
        out.insert(0, "-y")
    return out


def _npx_spec(base_cwd: Path, force_latest: bool = True) -> MCPLaunchSpec | None:
    """Spec que baja/resuelve el MCP via npx. Requiere token Azure Artifacts."""
    for p, src in _candidate_mcp_jsons(base_cwd):
        cfg = _read_mcp_config(p)
        if not cfg:
            continue
        servers = cfg.get("mcpServers", {})
        if "fabrics" not in servers:
            continue
        fabric = servers["fabrics"]
        command = str(fabric["command"])
        args = [str(a) for a in fabric.get("args", [])]
        if force_latest:
            args = _force_latest_args(args, command)
        env = os.environ.copy()
        resolved_env = _resolve_fabrics_env(fabric.get("env", {}))
        # Sin token usable npx no puede bajar el package (E401): mejor caer al cache.
        if not _is_usable_token(resolved_env.get("ARTIFACT_TOKEN", "")):
            continue
        env.update(resolved_env)
        return MCPLaunchSpec(command=[command, *args], env=env, source=src, version="latest")
    return None


def _cache_spec(base_cwd: Path) -> MCPLaunchSpec | None:
    """Spec que lanza el cache npx de mayor version con `node` directo."""
    entries = _find_cached_entries()
    if not entries:
        return None
    version, cached = entries[0]
    env = os.environ.copy()
    # Si hay .mcp.json con token, inyectar al env (el MCP lo necesita para
    # operaciones Azure Artifacts posteriores aunque el paquete ya este bajado)
    for p, _ in _candidate_mcp_jsons(base_cwd):
        cfg = _read_mcp_config(p)
        if cfg and "fabrics" in cfg.get("mcpServers", {}):
            fabric_env = _resolve_fabrics_env(cfg["mcpServers"]["fabrics"].get("env", {}))
            for k, v in fabric_env.items():
                env[k] = v
            break
    return MCPLaunchSpec(
        command=["node", str(cached)], env=env, source="cache", version=version
    )


def locate(
    cwd: Path | None = None,
    prefer_cache: bool = False,
    force_latest: bool = True,
) -> MCPLaunchSpec:
    """Find the MCP fabrics server and return how to launch it.

    Default (`prefer_cache=False`): usa `npx -y @pichincha/fabrics-project@latest`,
    que resuelve el tag contra el registry en cada corrida => siempre la ultima
    version publicada. Si no hay token usable, cae al cache npx de mayor version.

    `prefer_cache=True` invierte el orden (modo offline / sin .npmrc valido) y
    NO garantiza la ultima version.
    """
    base_cwd = cwd or Path.cwd()

    order = (
        (_cache_spec(base_cwd), _npx_spec(base_cwd, force_latest))
        if prefer_cache
        else (_npx_spec(base_cwd, force_latest), _cache_spec(base_cwd))
    )
    for spec in order:
        if spec is not None:
            return spec

    raise FileNotFoundError(
        "No se encontro el MCP Fabrics. Opciones:\n"
        "  1. Ejecuta 'capamedia fabrics setup' para registrar el MCP en .mcp.json\n"
        "  2. Ejecuta 'npx @pichincha/fabrics-project@latest' una vez para cachearlo\n"
        "     (requiere .npmrc con token Azure Artifacts valido)"
    )
