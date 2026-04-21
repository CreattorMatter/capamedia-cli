"""Tests para auth/bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.commands.auth import bootstrap
from capamedia_cli.core.auth import build_azure_git_env, resolve_azure_devops_pat


def test_build_azure_git_env_uses_capamedia_pat(monkeypatch) -> None:
    monkeypatch.setenv("CAPAMEDIA_AZDO_PAT", "secret-pat")

    env = build_azure_git_env()

    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GCM_INTERACTIVE"] == "Never"


def test_resolve_azure_devops_pat_prefers_explicit_value(monkeypatch) -> None:
    monkeypatch.setenv("CAPAMEDIA_AZDO_PAT", "env-pat")

    assert resolve_azure_devops_pat("explicit-pat") == "explicit-pat"


def test_auth_bootstrap_writes_env_file_and_runs_integrations(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    env_file = tmp_path / "auth.env"

    monkeypatch.setattr(
        "capamedia_cli.commands.auth.fabrics.setup",
        lambda scope, token, force, refresh_npmrc: calls.append((f"fabrics:{scope}", token)),  # noqa: ARG005
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.auth._codex_login_with_api_key",
        lambda api_key: calls.append(("codex", api_key)) or "Logged in using API key",
    )

    bootstrap(
        scope="global",
        artifact_token="artifact-123",
        azure_pat="azdo-456",
        openai_api_key="openai-789",
        env_file=env_file,
        force=True,
        refresh_npmrc=True,
    )

    content = env_file.read_text(encoding="utf-8")
    assert "CAPAMEDIA_ARTIFACT_TOKEN=artifact-123" in content
    assert "CAPAMEDIA_AZDO_PAT=azdo-456" in content
    assert "OPENAI_API_KEY=openai-789" in content
    assert ("fabrics:global", "artifact-123") in calls
    assert ("codex", "openai-789") in calls
