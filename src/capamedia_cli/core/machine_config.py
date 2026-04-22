"""Config machine-local para la fabrica CapaMedia."""

from __future__ import annotations

import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

import tomli_w

MACHINE_CONFIG_ENV = "CAPAMEDIA_MACHINE_CONFIG"
DEFAULT_MACHINE_VERSION = 1


def default_machine_home() -> Path:
    return (Path.home() / ".capamedia").resolve()


def default_machine_config_path(path: Path | None = None) -> Path:
    if path is not None:
        return path.expanduser().resolve()

    env_path = os.environ.get(MACHINE_CONFIG_ENV, "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()

    return (default_machine_home() / "machine.toml").resolve()


def default_auth_env_path() -> Path:
    return (default_machine_home() / "auth.env").resolve()


def default_queue_dir() -> Path:
    return (default_machine_home() / "queue").resolve()


def machine_config_defaults() -> dict[str, Any]:
    return {
        "version": DEFAULT_MACHINE_VERSION,
        "provider": "codex",
        "auth_mode": "session",
        "scope": "global",
        "workspace_root": "",
        "queue_dir": str(default_queue_dir()),
        "env_file": str(default_auth_env_path()),
        "defaults": {
            "workers": 2,
            "namespace": "tnd",
            "group_id": "com.pichincha.sp",
            "timeout_minutes": 90,
            "retries": 1,
            "follow_interval_seconds": 300,
            "batch_mode": "pipeline",
            "refresh_npmrc": True,
            "skip_optional_install": False,
            "run_check": True,
        },
        "providers": {
            "codex": {
                "bin": "codex",
                "auth_mode": "session",
                "model": "gpt-5.4",
                "reasoning_effort": "high",
            },
            "claude": {
                "bin": "claude",
                "auth_mode": "session",
                "model": "opus",
                "effort": "high",
                "permission_mode": "bypassPermissions",
            },
        },
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_machine_config(data: dict[str, Any] | None) -> dict[str, Any]:
    raw = data if isinstance(data, dict) else {}
    normalized = _deep_merge(machine_config_defaults(), raw)
    normalized["version"] = int(normalized.get("version", DEFAULT_MACHINE_VERSION) or DEFAULT_MACHINE_VERSION)
    return normalized


def load_machine_config(path: Path | None = None) -> dict[str, Any]:
    config_path = default_machine_config_path(path)
    if not config_path.exists():
        return normalize_machine_config({})

    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return normalize_machine_config({})

    if not isinstance(payload, dict):
        return normalize_machine_config({})
    return normalize_machine_config(payload)


def write_machine_config(data: dict[str, Any], path: Path | None = None) -> Path:
    config_path = default_machine_config_path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_machine_config(data)
    with config_path.open("wb") as handle:
        tomli_w.dump(normalized, handle)
    return config_path


def provider_config(config: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    normalized = normalize_machine_config(config)
    provider_name = (provider or normalized.get("provider") or "codex").strip().lower()
    providers = normalized.get("providers", {})
    if not isinstance(providers, dict):
        return {}
    provider_data = providers.get(provider_name, {})
    return provider_data if isinstance(provider_data, dict) else {}


def machine_paths(config: dict[str, Any]) -> dict[str, Path]:
    normalized = normalize_machine_config(config)
    workspace_root = Path(str(normalized.get("workspace_root", "") or Path.cwd())).expanduser().resolve()
    queue_dir = Path(str(normalized.get("queue_dir", default_queue_dir()))).expanduser().resolve()
    env_file = Path(str(normalized.get("env_file", default_auth_env_path()))).expanduser().resolve()
    return {
        "workspace_root": workspace_root,
        "queue_dir": queue_dir,
        "env_file": env_file,
    }
