"""Helpers de autenticacion compartidos por clone/install/check/install."""

from __future__ import annotations

import base64
import os

AZURE_PAT_ENV_VARS = ("CAPAMEDIA_AZDO_PAT", "AZURE_DEVOPS_EXT_PAT")
ARTIFACT_TOKEN_ENV_VARS = ("CAPAMEDIA_ARTIFACT_TOKEN", "ARTIFACT_TOKEN")
OPENAI_API_KEY_ENV_VARS = ("OPENAI_API_KEY",)


def _first_non_empty(value: str | None, env_vars: tuple[str, ...]) -> str | None:
    raw = (value or "").strip()
    if raw:
        return raw
    for env_var in env_vars:
        candidate = os.environ.get(env_var, "").strip()
        if candidate:
            return candidate
    return None


def resolve_azure_devops_pat(value: str | None = None) -> str | None:
    """Return the Azure DevOps PAT from an explicit value or known env vars."""
    return _first_non_empty(value, AZURE_PAT_ENV_VARS)


def resolve_artifact_token(value: str | None = None) -> str | None:
    """Return the Azure Artifacts token from an explicit value or known env vars."""
    return _first_non_empty(value, ARTIFACT_TOKEN_ENV_VARS)


def resolve_openai_api_key(value: str | None = None) -> str | None:
    """Return the OpenAI API key from an explicit value or known env vars."""
    return _first_non_empty(value, OPENAI_API_KEY_ENV_VARS)


def build_azure_git_env(value: str | None = None) -> dict[str, str]:
    """Build env overrides so `git clone` can auth to Azure DevOps unattended."""
    pat = resolve_azure_devops_pat(value)
    if not pat:
        return {}

    basic = base64.b64encode(f"capamedia:{pat}".encode()).decode("ascii")
    return {
        "GCM_INTERACTIVE": "Never",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
    }
