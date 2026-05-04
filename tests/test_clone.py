"""Tests para clone/auth unattended."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from capamedia_cli.commands.clone import (
    MIGRATED_NAMESPACES,
    _clone_migrated_repos,
    _git_clone,
    _resolve_azure_repo,
    _write_properties_report,
)
from capamedia_cli.core.legacy_analyzer import LegacyAnalysis, PropertiesReference


def test_git_clone_uses_env_auth_when_pat_is_present(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "legacy" / "sqb-msa-wsclientes0007"
    captured: dict[str, object] = {}

    def fake_run(cmd, capture_output, text, check, timeout, env):
        captured["cmd"] = cmd
        captured["env"] = env
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setenv("CAPAMEDIA_AZDO_PAT", "secret-pat")
    monkeypatch.setattr("capamedia_cli.commands.clone.subprocess.run", fake_run)

    ok, err = _git_clone("sqb-msa-wsclientes0007", dest, shallow=True)

    assert ok is True
    assert err == ""
    assert captured["cmd"][:3] == ["git", "clone", "--depth"]
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GCM_INTERACTIVE"] == "Never"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")


def test_git_clone_retries_with_gcm_when_env_pat_is_stale(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "legacy" / "sqb-msa-wsclientes0077"
    calls: list[dict[str, str] | None] = []

    def fake_run(cmd, capture_output, text, check, timeout, env):
        calls.append(env)
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr="remote: TF401019: repository not found or no permissions\n",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setenv("CAPAMEDIA_AZDO_PAT", "stale-pat")
    monkeypatch.setattr("capamedia_cli.commands.clone.subprocess.run", fake_run)

    ok, err = _git_clone("sqb-msa-wsclientes0077", dest, shallow=True)

    assert ok is True
    assert err == ""
    assert len(calls) == 2
    first_env = calls[0]
    retry_env = calls[1]
    assert isinstance(first_env, dict)
    assert isinstance(retry_env, dict)
    assert "GIT_CONFIG_VALUE_0" in first_env
    assert "GIT_CONFIG_VALUE_0" not in retry_env
    assert retry_env["GCM_INTERACTIVE"] == "Never"
    assert retry_env["GIT_TERMINAL_PROMPT"] == "0"


def test_clone_migrated_repos_tries_known_namespaces(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, Path, str, bool, bool]] = []

    def fake_git_clone(
        repo_name: str,
        dest: Path,
        project_key: str = "bus",
        shallow: bool = False,
        no_single_branch: bool = False,
    ) -> tuple[bool, str]:
        calls.append((repo_name, dest, project_key, shallow, no_single_branch))
        if repo_name == "csg-msa-sp-wsclientes0076":
            dest.mkdir(parents=True)
            (dest / "build.gradle").write_text("plugins {}", encoding="utf-8")
            return (True, "")
        return (False, "repository not found")

    monkeypatch.setattr("capamedia_cli.commands.clone._git_clone", fake_git_clone)
    monkeypatch.setattr(
        "capamedia_cli.commands.clone._auto_checkout_migrated_branch",
        lambda repo_path, requested_branch: ("feature/dev-BTHCCC-5961", "auto", ""),
    )

    results = _clone_migrated_repos("wsclientes0076", tmp_path, shallow=True)

    assert [call[0] for call in calls] == [
        f"{ns}-msa-sp-wsclientes0076" for ns in MIGRATED_NAMESPACES
    ]
    assert all(call[2] == "middleware" for call in calls)
    assert all(call[3] is True for call in calls)
    assert all(call[4] is True for call in calls)

    cloned = [r for r in results if r.status == "cloned"]
    assert len(cloned) == 1
    assert cloned[0].repo_name == "csg-msa-sp-wsclientes0076"
    assert cloned[0].path == tmp_path / "destino" / "csg-msa-sp-wsclientes0076"
    assert cloned[0].branch == "feature/dev-BTHCCC-5961"


def test_clone_migrated_repos_respects_namespace_and_branch(tmp_path: Path, monkeypatch) -> None:
    branches: list[str | None] = []

    def fake_git_clone(
        repo_name: str,
        dest: Path,
        project_key: str = "bus",
        shallow: bool = False,
        no_single_branch: bool = False,
    ) -> tuple[bool, str]:
        dest.mkdir(parents=True)
        (dest / "build.gradle").write_text("plugins {}", encoding="utf-8")
        return (True, "")

    def fake_checkout(repo_path: Path, requested_branch: str | None) -> tuple[str, str, str]:
        branches.append(requested_branch)
        return (requested_branch or "", "explicit", "")

    monkeypatch.setattr("capamedia_cli.commands.clone._git_clone", fake_git_clone)
    monkeypatch.setattr("capamedia_cli.commands.clone._auto_checkout_migrated_branch", fake_checkout)

    results = _clone_migrated_repos(
        "wstecnicos0006",
        tmp_path,
        namespace="tnd",
        branch="feature/dev-BTHCCC-5953",
    )

    assert len(results) == 1
    assert results[0].repo_name == "tnd-msa-sp-wstecnicos0006"
    assert results[0].status == "cloned"
    assert results[0].branch == "feature/dev-BTHCCC-5953"
    assert branches == ["feature/dev-BTHCCC-5953"]


def test_resolve_azure_repo_supports_was_split_repos(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, Path, str]] = []

    def fake_git_clone(
        repo_name: str,
        dest: Path,
        project_key: str = "bus",
        shallow: bool = False,
        no_single_branch: bool = False,
    ) -> tuple[bool, str]:
        calls.append((repo_name, dest, project_key))
        if repo_name in {
            "wsclientes0154-aplicacion",
            "wsclientes0154-infraestructura",
        }:
            dest.mkdir(parents=True)
            return (True, "")
        return (False, "repository not found")

    monkeypatch.setattr("capamedia_cli.commands.clone._git_clone", fake_git_clone)

    path, project_key, repo_name = _resolve_azure_repo(
        "wsclientes0154", tmp_path, shallow=True
    )

    assert path == tmp_path / "legacy" / "_repo"
    assert project_key == "was"
    assert repo_name == "wsclientes0154-aplicacion + wsclientes0154-infraestructura"
    assert [call[0] for call in calls] == [
        "sqb-msa-wsclientes0154",
        "ws-wsclientes0154-was",
        "ms-wsclientes0154-was",
        "wsclientes0154-aplicacion",
        "wsclientes0154-infraestructura",
    ]
    assert all(call[2] == "was" for call in calls[-2:])


# ---------------------------------------------------------------------------
# v0.19.0: properties-report.yaml persistence
# ---------------------------------------------------------------------------


def test_write_properties_report_persists_pending_and_shared(tmp_path: Path) -> None:
    """_write_properties_report genera .capamedia/properties-report.yaml con
    la separacion correcta entre shared catalog y pendientes del banco."""
    analysis = LegacyAnalysis(
        source_kind="was",
        wsdl=None,
        properties_refs=[
            PropertiesReference(
                file_name="generalServices.properties",
                status="SHARED_CATALOG",
                source_hint="bank-shared-catalog",
                keys_used=["OMNI_COD_SERVICIO_OK", "OMNI_COD_FATAL"],
            ),
            PropertiesReference(
                file_name="umptecnicos0023.properties",
                status="PENDING_FROM_BANK",
                source_hint="ump:umptecnicos0023",
                keys_used=["URL_XML", "RECURSO", "COMPONENTE"],
                referenced_from=["ump-umptecnicos0023-was/src/.../Constantes.java"],
                physical_path_hint="/apps/proy/OMNICANALIDAD_SERVICIOS/conf/umptecnicos0023.properties",
            ),
        ],
    )

    out = _write_properties_report(analysis, tmp_path)
    assert out is not None
    assert out.exists()
    data = yaml.safe_load(out.read_text(encoding="utf-8"))

    # Shared catalog debe estar en seccion separada
    assert "generalServices.properties" in data["shared_catalog_keys_used"]
    assert "OMNI_COD_SERVICIO_OK" in data["shared_catalog_keys_used"]["generalServices.properties"]

    # Pendientes en service_specific_properties
    pending = data["service_specific_properties"]
    assert len(pending) == 1
    assert pending[0]["file"] == "umptecnicos0023.properties"
    assert pending[0]["status"] == "PENDING_FROM_BANK"
    assert "URL_XML" in pending[0]["keys_used"]
    assert "Pedir al owner" in pending[0]["action"]


def test_write_properties_report_returns_none_when_no_refs(tmp_path: Path) -> None:
    """Si no hay properties_refs, no genera archivo."""
    analysis = LegacyAnalysis(
        source_kind="was",
        wsdl=None,
        properties_refs=[],
    )
    out = _write_properties_report(analysis, tmp_path)
    assert out is None
    assert not (tmp_path / ".capamedia" / "properties-report.yaml").exists()
