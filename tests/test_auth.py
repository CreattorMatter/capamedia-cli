"""Tests para auth/bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from capamedia_cli.commands.auth import _merge_path_entries
from capamedia_cli.commands.auth import app as auth_app
from capamedia_cli.commands.auth import bootstrap
from capamedia_cli.cli import app as root_app
from capamedia_cli.core.auth import build_azure_git_env, resolve_azure_devops_pat


runner = CliRunner()


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
        lambda scope, token, force, refresh_npmrc: calls.append((f"fabrics:{scope}", token)),
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


def test_auth_configure_user_persists_tokens_path_and_fabrics(monkeypatch) -> None:
    persisted: dict[str, str] = {}
    path_calls: list[list[str]] = []
    fabric_calls: list[tuple[str, str | None, bool, bool]] = []

    monkeypatch.setattr(
        "capamedia_cli.commands.auth._persist_user_environment",
        lambda values: persisted.update(values),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.auth._append_user_path_entries",
        lambda paths: path_calls.append([str(p) for p in paths]),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.auth.fabrics.setup",
        lambda scope, token, force, refresh_npmrc: fabric_calls.append(
            (scope, token, force, refresh_npmrc)
        ),
    )

    result = runner.invoke(
        auth_app,
        [
            "configure-user",
            "--artifact-token",
            "artifact-123",
            "--azure-pat",
            "azdo-456",
            "--path",
            r"C:\Users\me\AppData\Roaming\Python\Python314\Scripts",
        ],
    )

    assert result.exit_code == 0
    assert persisted["CAPAMEDIA_ARTIFACT_TOKEN"] == "artifact-123"
    assert persisted["ARTIFACT_TOKEN"] == "artifact-123"
    assert persisted["CAPAMEDIA_AZDO_PAT"] == "azdo-456"
    assert persisted["AZURE_DEVOPS_EXT_PAT"] == "azdo-456"
    assert path_calls == [[r"C:\Users\me\AppData\Roaming\Python\Python314\Scripts"]]
    assert fabric_calls == [("global", "artifact-123", True, True)]
    assert "artifact-123" not in result.output
    assert "azdo-456" not in result.output


def test_auth_configure_user_can_only_update_path(monkeypatch) -> None:
    persisted: dict[str, str] = {}
    fabric_calls: list[tuple[str, str | None, bool, bool]] = []
    path_calls: list[list[str]] = []
    for env_var in (
        "CAPAMEDIA_ARTIFACT_TOKEN",
        "ARTIFACT_TOKEN",
        "CAPAMEDIA_AZDO_PAT",
        "AZURE_DEVOPS_EXT_PAT",
    ):
        monkeypatch.delenv(env_var, raising=False)

    monkeypatch.setattr(
        "capamedia_cli.commands.auth._persist_user_environment",
        lambda values: persisted.update(values),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.auth._append_user_path_entries",
        lambda paths: path_calls.append([str(p) for p in paths]),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.auth.fabrics.setup",
        lambda scope, token, force, refresh_npmrc: fabric_calls.append(
            (scope, token, force, refresh_npmrc)
        ),
    )

    result = runner.invoke(
        auth_app,
        [
            "configure-user",
            "--path",
            r"C:\tools\bin",
            "--no-configure-fabrics",
        ],
    )

    assert result.exit_code == 0
    assert persisted == {}
    assert path_calls == [[r"C:\tools\bin"]]
    assert fabric_calls == []


def test_merge_path_entries_does_not_duplicate_existing_entry() -> None:
    merged = _merge_path_entries(
        r"C:\tools\bin;C:\Windows",
        [Path(r"C:\tools\bin"), Path(r"C:\Users\me\bin")],
        sep=";",
    )

    assert merged == r"C:\tools\bin;C:\Windows;C:\Users\me\bin"


def test_root_pat_command_uses_same_token_for_artifacts_and_azdo(monkeypatch) -> None:
    received: dict[str, object] = {}
    validation_calls: list[str] = []

    def fake_configure_user(**kwargs) -> None:
        received.update(kwargs)

    def fake_validate_pat_access(token: str):
        validation_calls.append(token)
        return [
            ("Azure DevOps", "ok", "org BancoPichinchaEC accesible"),
            ("Azure Artifacts", "ok", "feed Framework accesible"),
        ]

    monkeypatch.setattr("capamedia_cli.commands.auth._validate_pat_access", fake_validate_pat_access)
    monkeypatch.setattr("capamedia_cli.commands.auth.configure_user", fake_configure_user)

    result = runner.invoke(
        root_app,
        [
            "pat",
            "same-token",
            "--path",
            r"C:\tools\bin",
            "--no-configure-fabrics",
        ],
    )

    assert result.exit_code == 0
    assert validation_calls == ["same-token"]
    assert received["artifact_token"] == "same-token"
    assert received["azure_pat"] == "same-token"
    assert received["path_entries"] == [Path(r"C:\tools\bin")]
    assert received["configure_fabrics"] is False
    assert "same-token" not in result.output
    assert "Prueba de PAT" in result.output
    assert "Azure DevOps" in result.output
    assert "Azure Artifacts" in result.output


def test_root_pat_command_stops_when_pat_validation_fails(monkeypatch) -> None:
    configured = False

    def fake_configure_user(**kwargs) -> None:
        nonlocal configured
        configured = True

    def fake_validate_pat_access(token: str):
        raise RuntimeError("Azure DevOps devolvio 401 Unauthorized")

    monkeypatch.setattr("capamedia_cli.commands.auth._validate_pat_access", fake_validate_pat_access)
    monkeypatch.setattr("capamedia_cli.commands.auth.configure_user", fake_configure_user)

    result = runner.invoke(root_app, ["pat", "bad-token"])

    assert result.exit_code == 1
    assert configured is False
    assert "Azure DevOps devolvio 401 Unauthorized" in result.output
    assert "bad-token" not in result.output
