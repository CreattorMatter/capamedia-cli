"""Tests para clone/auth unattended."""

from __future__ import annotations

import subprocess
from pathlib import Path

from capamedia_cli.commands.clone import _git_clone


def test_git_clone_uses_env_auth_when_pat_is_present(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "legacy" / "sqb-msa-wsclientes0007"
    captured: dict[str, object] = {}

    def fake_run(cmd, capture_output, text, check, timeout, env):  # noqa: ANN001
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
