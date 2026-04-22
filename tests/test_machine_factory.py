"""Tests para setup/doctor/worker y config machine-local."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from capamedia_cli.commands.batch import _ensure_migrate_schema, _process_migrate_service
from capamedia_cli.commands.check_install import CheckResult
from capamedia_cli.commands.doctor import DoctorReport, run_doctor
from capamedia_cli.commands.setup import setup_machine
from capamedia_cli.commands.worker import run_worker
from capamedia_cli.core.machine_config import (
    load_machine_config,
    machine_paths,
    write_machine_config,
)


def _write_fabrics_metadata(workspace: Path, service: str) -> None:
    meta = workspace / ".capamedia" / "fabrics.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(
        json.dumps(
            {
                "service": service,
                "status": "ok",
                "detail": "fabrics ready",
                "project_name": f"tnd-msa-sp-{service}",
                "project_path": str(workspace / "destino" / f"tnd-msa-sp-{service}"),
            }
        ),
        encoding="utf-8",
    )


def test_machine_config_roundtrip(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "machine.toml"
    monkeypatch.setenv("CAPAMEDIA_MACHINE_CONFIG", str(config_path))

    written = write_machine_config(
        {
            "provider": "claude",
            "auth_mode": "session",
            "workspace_root": str(tmp_path / "lote"),
            "queue_dir": str(tmp_path / "queue"),
        }
    )

    assert written == config_path
    loaded = load_machine_config()
    assert loaded["provider"] == "claude"
    assert loaded["auth_mode"] == "session"
    assert machine_paths(loaded)["queue_dir"] == (tmp_path / "queue").resolve()


def test_setup_machine_writes_machine_config(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "machine.toml"
    env_file = tmp_path / "auth.env"
    queue_dir = tmp_path / "queue"
    workspace_root = tmp_path / "lote"
    monkeypatch.setenv("CAPAMEDIA_MACHINE_CONFIG", str(config_path))

    calls: list[str] = []
    monkeypatch.setattr(
        "capamedia_cli.commands.setup.install.install_toolchain",
        lambda skip_optional, yes: calls.append(f"install:{skip_optional}:{yes}"),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.setup.auth.bootstrap",
        lambda **kwargs: calls.append(f"bootstrap:{kwargs['scope']}"),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.setup.doctor.run_doctor",
        lambda: DoctorReport(
            classification="READY",
            reason="ok",
            config_path=config_path,
            machine_config={"provider": "claude", "auth_mode": "session"},
            categories={},
            extras=[],
            total_ok=1,
            total_warn=0,
            total_fail=0,
        ),
    )

    setup_machine(
        provider="claude",
        auth_mode="session",
        scope="global",
        workspace_root=workspace_root,
        queue_dir=queue_dir,
        env_file=env_file,
        artifact_token=None,
        azure_pat=None,
        codex_api_key=None,
        codex_bin="codex",
        claude_bin="claude",
        codex_model="gpt-5.4",
        claude_model="opus",
        workers=3,
        namespace="tnd",
        group_id="com.pichincha.sp",
        timeout_minutes=45,
        retries=2,
        follow_interval_seconds=120,
        refresh_npmrc=True,
        skip_install=True,
        skip_optional_install=True,
        skip_doctor=False,
        force=True,
        yes=True,
    )

    config = load_machine_config(config_path)
    assert "bootstrap:global" in calls
    assert config["provider"] == "claude"
    assert config["defaults"]["workers"] == 3
    assert config["queue_dir"] == str(queue_dir.resolve())


def test_run_doctor_classifies_provider_auth_blocker(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "machine.toml"
    monkeypatch.setenv("CAPAMEDIA_MACHINE_CONFIG", str(config_path))
    write_machine_config({"provider": "claude", "auth_mode": "session"}, config_path)

    monkeypatch.setattr(
        "capamedia_cli.commands.doctor.collect_check_results",
        lambda: {"Toolchain": [CheckResult("Git", "ok", "ok")]},
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.doctor._check_selected_provider_binary",
        lambda machine_config: CheckResult("Selected provider binary", "ok", "ok"),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.doctor._check_selected_provider_auth",
        lambda machine_config: CheckResult("Selected provider auth", "fail", "sin session"),
    )

    report = run_doctor()

    assert report.classification == "BLOCKED_PROVIDER_AUTH"


def test_worker_run_uses_machine_defaults(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "machine.toml"
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    queue_file = queue_dir / "services.txt"
    queue_file.write_text("ORQClientes0002\n", encoding="utf-8")
    workspace_root = tmp_path / "lote"
    workspace_root.mkdir()
    monkeypatch.setenv("CAPAMEDIA_MACHINE_CONFIG", str(config_path))
    write_machine_config(
        {
            "provider": "claude",
            "auth_mode": "session",
            "workspace_root": str(workspace_root),
            "queue_dir": str(queue_dir),
            "defaults": {
                "workers": 4,
                "namespace": "tnd",
                "group_id": "com.pichincha.sp",
                "timeout_minutes": 30,
                "retries": 2,
                "follow_interval_seconds": 10,
            },
            "providers": {
                "claude": {
                    "bin": "claude",
                    "model": "opus",
                    "auth_mode": "session",
                }
            },
        },
        config_path,
    )

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "capamedia_cli.commands.worker.doctor.run_doctor",
        lambda: DoctorReport(
            classification="READY",
            reason="ok",
            config_path=config_path,
            machine_config={},
            categories={},
            extras=[],
            total_ok=1,
            total_warn=0,
            total_fail=0,
        ),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.worker.batch.batch_pipeline",
        lambda **kwargs: calls.append(kwargs),
    )

    run_worker(mode="pipeline", once=True)

    assert calls
    assert calls[0]["provider"] == "claude"
    assert calls[0]["runner_bin"] == "claude"
    assert calls[0]["workers"] == 4


def test_process_migrate_service_supports_claude_runner(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    service = "orqclientes0022"
    workspace = root / service
    project = workspace / "destino" / "tnd-msa-sp-orqclientes0022"
    prompt_file = workspace / ".codex" / "prompts" / "migrate.md"
    project.mkdir(parents=True)
    prompt_file.parent.mkdir(parents=True)
    (project / "build.gradle").write_text("plugins {}", encoding="utf-8")
    prompt_file.write_text("prompt real", encoding="utf-8")
    (workspace / "legacy").mkdir(parents=True)
    _write_fabrics_metadata(workspace, service)
    schema_path = _ensure_migrate_schema(root)

    def fake_run(cmd, *, input=None, text=None, capture_output=None, check=None, timeout=None, env=None, cwd=None):
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        if cmd[:2] == ["git", "init"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        assert Path(cmd[0]).name == "claude"
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert cmd[cmd.index("--output-format") + 1] == "json"
        assert "--json-schema" in cmd
        assert "--cwd" in cmd
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "session_id": "claude-session-1",
                    "structured_output": {
                        "status": "ok",
                        "summary": "Migracion Claude completa",
                        "framework": "REST",
                        "build_status": "green",
                        "migrated_project": str(project),
                        "artifacts": [],
                        "notes": [],
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("capamedia_cli.commands.batch.subprocess.run", fake_run)
    monkeypatch.setattr(
        "capamedia_cli.commands.batch._run_batch_check",
        lambda service_name, migrated_project, legacy_root: {
            "verdict": "READY_TO_MERGE",
            "HIGH": "0",
            "MEDIUM": "0",
            "LOW": "0",
            "report": str(migrated_project / f"CHECKLIST_{service_name}.md"),
        },
    )

    row = _process_migrate_service(
        service,
        root,
        schema_path,
        provider="claude",
        runner_bin="claude",
        model="opus",
        prompt_file=None,
        timeout_minutes=5,
        run_check=True,
        unsafe=False,
    )

    assert row.status == "ok"
    assert row.fields["codex"] == "claude:ok"
    assert row.detail == "Migracion Claude completa"
