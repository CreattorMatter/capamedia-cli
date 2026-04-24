"""Tests para `capamedia ai` (migrate/doublecheck)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from capamedia_cli.cli import app as root_app
from capamedia_cli.commands.ai import (
    _ensure_doublecheck_schema,
    _process_doublecheck_workspace,
)
from capamedia_cli.commands.ai import (
    app as ai_app,
)
from capamedia_cli.commands.batch import BatchRow
from capamedia_cli.core.engine import EngineResult

runner = CliRunner()


class _FakeEngine:
    name = "codex"
    subscription_type = "test"

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {"status": "ok", "summary": "done"}
        self.inputs = []

    def is_available(self) -> tuple[bool, str]:
        return (True, "ok")

    def run_headless(self, einput) -> EngineResult:
        self.inputs.append(einput)
        einput.output_path.parent.mkdir(parents=True, exist_ok=True)
        einput.output_path.write_text(json.dumps(self.payload), encoding="utf-8")
        return EngineResult(exit_code=0, stdout="ok", stderr="", duration_seconds=1.2)


def _write_workspace(workspace: Path, service: str = "wstecnicos0006") -> Path:
    (workspace / ".capamedia").mkdir(parents=True)
    (workspace / ".capamedia" / "config.yaml").write_text(
        f"service_name: {service}\n",
        encoding="utf-8",
    )
    project = workspace / "destino" / f"tnd-msa-sp-{service}"
    project.mkdir(parents=True)
    (project / "build.gradle").write_text("plugins {}", encoding="utf-8")
    (workspace / ".capamedia" / "fabrics.json").write_text(
        json.dumps(
            {
                "service": service,
                "status": "ok",
                "project_name": project.name,
                "project_path": str(project),
            }
        ),
        encoding="utf-8",
    )
    return project


def test_root_registers_ai_namespace() -> None:
    result = runner.invoke(root_app, ["ai", "--help"])

    assert result.exit_code == 0
    assert "migrate" in result.output
    assert "doublecheck" in result.output


def test_ai_migrate_help_shows_engine_controls() -> None:
    result = runner.invoke(ai_app, ["migrate", "--help"])

    assert result.exit_code == 0
    assert "--engine" in result.output
    assert "--reasoning-effort" in result.output
    assert "--check" in result.output


def test_ai_doublecheck_help_shows_engine_controls() -> None:
    result = runner.invoke(ai_app, ["doublecheck", "--help"])

    assert result.exit_code == 0
    assert "--engine" in result.output
    assert "--reasoning-effort" in result.output
    assert "review" in result.output.lower()


def test_ai_migrate_autodetects_service_and_skips_check_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "wstecnicos0006"
    _write_workspace(workspace)
    fake = _FakeEngine()
    captured = {}

    monkeypatch.setattr("capamedia_cli.commands.ai.select_engine", lambda *args, **kwargs: fake)

    def fake_process(service: str, workspace_arg: Path, schema_path: Path, **kwargs) -> BatchRow:
        captured.update(
            {
                "service": service,
                "workspace": workspace_arg,
                "schema_path": schema_path,
                **kwargs,
            }
        )
        return BatchRow(
            service,
            "ok",
            "migrated",
            {
                "engine": "codex",
                "codex": "ok",
                "result": "ok",
                "framework": "REST",
                "build": "green",
                "check": "skip",
                "seconds": "1.0",
                "project": "tnd-msa-sp-wstecnicos0006",
            },
        )

    monkeypatch.setattr("capamedia_cli.commands.ai._process_migrate_workspace", fake_process)

    result = runner.invoke(ai_app, ["migrate", "--workspace", str(workspace)])

    assert result.exit_code == 0
    assert captured["service"] == "wstecnicos0006"
    assert captured["workspace"] == workspace.resolve()
    assert captured["run_check"] is False
    assert captured["reasoning_effort"] == "xhigh"
    assert captured["engine"] is fake
    assert captured["schema_path"].name == "codex-batch-migrate.schema.json"


def test_process_doublecheck_workspace_writes_structured_state(tmp_path: Path) -> None:
    workspace = tmp_path / "wstecnicos0006"
    project = _write_workspace(workspace)
    fake = _FakeEngine(
        {
            "status": "ok",
            "summary": "doublecheck completo",
            "checklist_verdict": "READY_TO_MERGE",
            "autofixes_applied": 2,
            "high": 0,
            "medium": 0,
            "low": 1,
            "report": str(project / "CHECKLIST_wstecnicos0006.md"),
            "next_step": "capamedia review",
        }
    )
    schema_path = _ensure_doublecheck_schema(workspace)

    row = _process_doublecheck_workspace(
        "wstecnicos0006",
        workspace,
        schema_path,
        engine=fake,
        model="gpt-5.5",
        prompt_file=None,
        timeout_minutes=5,
        unsafe=False,
        reasoning_effort="xhigh",
    )

    assert row.status == "ok"
    assert row.fields["verdict"] == "READY_TO_MERGE"
    assert row.fields["fixes"] == "2"
    assert fake.inputs[0].workspace == workspace
    assert fake.inputs[0].model == "gpt-5.5"
    assert fake.inputs[0].reasoning_effort == "xhigh"
    assert "No ejecutes `capamedia ai migrate`" in fake.inputs[0].prompt
    assert "ni `capamedia review`" in fake.inputs[0].prompt
    assert (workspace / ".capamedia" / "batch-state" / "doublecheck.json").exists()
