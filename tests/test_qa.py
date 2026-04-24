from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from capamedia_cli.cli import app

runner = CliRunner()


def test_qa_command_is_registered() -> None:
    result = runner.invoke(app, ["qa", "--help"])

    assert result.exit_code == 0
    assert "equivalencia" in result.output.lower()
    assert "pack" in result.output


def test_qa_pack_generates_copilot_prompt_and_cmd_contract(tmp_path: Path) -> None:
    service = "wstecnicos0098"
    (tmp_path / "legacy" / f"sqb-msa-{service}").mkdir(parents=True)
    destino = tmp_path / "destino" / f"tnd-msa-sp-{service}"
    destino.mkdir(parents=True)
    (destino / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["qa", "pack", service, "--workspace", str(tmp_path), "--no-clone"],
    )

    assert result.exit_code == 0
    prompt = tmp_path / ".github" / "prompts" / "qa.prompt.md"
    assert prompt.exists()
    content = prompt.read_text(encoding="utf-8")
    assert "name: qa" in content
    assert "TRAMAS.txt" in content
    assert "Command Prompt" in content
    assert "cmd.exe" in content
    assert "No uses PowerShell" in content
    assert "curl.exe" in content
    assert "Get-Content" in content
    assert "execute/runInTerminal" in content
    assert not list(tmp_path.rglob("*.ps1"))
    assert (tmp_path / "TRAMAS.txt").exists()
    assert (tmp_path / ".capamedia" / "qa" / "pack.json").exists()
    settings = tmp_path / ".vscode" / "settings.json"
    assert settings.exists()
    settings_content = settings.read_text(encoding="utf-8")
    assert "terminal.integrated.defaultProfile.windows" in settings_content
    assert "Command Prompt" in settings_content
    assert "cmd.exe" in settings_content


def test_qa_prepare_fails_when_repos_are_missing_but_writes_prompt(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["qa", "prepare", "wsclientes0076", "--workspace", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert (tmp_path / ".github" / "prompts" / "qa.prompt.md").exists()
    assert (tmp_path / "TRAMAS.txt").exists()


def test_qa_pack_clones_legacy_and_destino_with_namespace(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, Path, str, bool]] = []

    def fake_git_clone(repo_name: str, dest: Path, project_key: str = "bus", shallow: bool = False):
        calls.append((repo_name, dest, project_key, shallow))
        dest.mkdir(parents=True, exist_ok=True)
        if project_key == "middleware":
            (dest / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
        return True, ""

    monkeypatch.setattr("capamedia_cli.commands.qa._git_clone", fake_git_clone)

    result = runner.invoke(
        app,
        [
            "qa",
            "pack",
            "wsclientes0076",
            "--workspace",
            str(tmp_path),
            "--namespace",
            "csg",
        ],
    )

    assert result.exit_code == 0
    assert calls[0][0] == "sqb-msa-wsclientes0076"
    assert calls[0][2] == "bus"
    assert calls[0][3] is True
    assert ("csg-msa-sp-wsclientes0076", tmp_path / "destino" / "csg-msa-sp-wsclientes0076", "middleware", True) in calls


def test_qa_pack_rejects_invalid_namespace(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["qa", "pack", "wsclientes0076", "--workspace", str(tmp_path), "--namespace", "bad"],
    )

    assert result.exit_code != 0
    assert "namespace invalido" in result.output.lower()
