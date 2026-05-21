"""Helpers de autenticacion compartidos por clone/install/check/install."""

from __future__ import annotations

import base64
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

AZURE_PAT_ENV_VARS = ("CAPAMEDIA_AZDO_PAT", "AZURE_DEVOPS_EXT_PAT")
ARTIFACT_TOKEN_ENV_VARS = ("CAPAMEDIA_ARTIFACT_TOKEN", "ARTIFACT_TOKEN")
OPENAI_API_KEY_ENV_VARS = ("OPENAI_API_KEY",)

# Endpoint barato de Azure DevOps para verificar que un PAT tiene scope
# `Code (Read)` — el scope que `git clone` necesita. Listar proyectos requiere
# el mismo nivel de acceso de lectura que clonar un repo.
AZURE_DEVOPS_PAT_PROBE_URL = (
    "https://dev.azure.com/BancoPichinchaEC/_apis/projects?api-version=7.1"
)


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


def probe_azure_devops_pat(value: str | None = None) -> tuple[str, str]:
    """Verifica que el PAT de Azure DevOps sirva para clonar repos.

    Devuelve ``(status, detail)``:
      - ``("ok", ...)``       el PAT autentica y tiene acceso de lectura.
      - ``("no_pat", ...)``   no hay PAT configurado (env vars vacias).
      - ``("denied", ...)``   el PAT fue rechazado (401/403) — tipicamente
                              porque le falta el scope `Code (Read)`. Es el
                              caso clasico de copiar el token de Artifacts
                              (scope `Packaging`) al `CAPAMEDIA_AZDO_PAT`.
      - ``("unreachable", ...)`` no se pudo contactar Azure DevOps (red/proxy).

    NOTA: `commands/auth.py` tiene su propio `_probe_pat_endpoint` para el
    flujo de `capamedia pat` (valida 2 endpoints en el setup). Esta funcion es
    el helper liviano de 1 endpoint para `clone`/`check`. Si en el futuro se
    consolidan, esta es la version canonica (vive en el modulo compartido).
    """
    pat = resolve_azure_devops_pat(value)
    if not pat:
        return ("no_pat", "No hay PAT en CAPAMEDIA_AZDO_PAT ni AZURE_DEVOPS_EXT_PAT.")

    header = base64.b64encode(f":{pat}".encode()).decode("ascii")
    request = Request(
        AZURE_DEVOPS_PAT_PROBE_URL,
        headers={
            "Authorization": f"Basic {header}",
            "Accept": "application/json",
            "User-Agent": "capamedia-cli",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            status = int(response.status)
    except HTTPError as exc:
        if exc.code in (401, 403):
            return (
                "denied",
                f"Azure DevOps rechazo el PAT (HTTP {exc.code}). El PAT necesita "
                "scope `Code (Read)`. Revisa que no estes usando el token de "
                "Artifacts (scope `Packaging`) en CAPAMEDIA_AZDO_PAT.",
            )
        return ("denied", f"Azure DevOps devolvio HTTP {exc.code}.")
    except (URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return ("unreachable", f"Azure DevOps no respondio: {reason}.")

    if 200 <= status < 300:
        return ("ok", "PAT con acceso de lectura validado.")
    return ("denied", f"Azure DevOps devolvio HTTP {status}.")
