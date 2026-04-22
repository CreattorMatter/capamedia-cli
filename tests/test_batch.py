"""Tests para el modulo batch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from capamedia_cli.commands.batch import (
    BatchRow,
    _build_batch_migrate_prompt,
    _collect_watch_rows,
    _ensure_migrate_schema,
    _find_legacy_root,
    _find_migrated_project,
    _process_migrate_service,
    _process_pipeline_service,
    _read_services_file,
    _read_structured_message,
    _write_csv_report,
    _write_markdown_report,
)


def _write_fabrics_metadata(workspace: Path, service: str, *, status: str = "ok") -> None:
    meta = workspace / ".capamedia" / "fabrics.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(
        json.dumps(
            {
                "service": service,
                "status": status,
                "detail": "fabrics ready",
                "project_name": f"tnd-msa-sp-{service}",
                "project_path": str(workspace / "destino" / f"tnd-msa-sp-{service}"),
            }
        ),
        encoding="utf-8",
    )


def test_read_services_file_ignores_comments(tmp_path: Path) -> None:
    f = tmp_path / "services.txt"
    f.write_text(
        "# Comentario inicial\n"
        "wsclientes0007\n"
        "\n"
        "# otro\n"
        "wsclientes0030 # inline\n"
        "   wsclientes0013   \n",
        encoding="utf-8",
    )
    result = _read_services_file(f)
    assert result == ["wsclientes0007", "wsclientes0030", "wsclientes0013"]


def test_read_services_file_missing_raises(tmp_path: Path) -> None:
    import typer
    try:
        _read_services_file(tmp_path / "notfound.txt")
        raise AssertionError("expected typer.BadParameter")
    except typer.BadParameter:
        pass


def test_write_markdown_report_has_summary(tmp_path: Path) -> None:
    rows = [
        BatchRow("svc1", "ok", "", {"ops": "1", "framework": "REST"}),
        BatchRow("svc2", "fail", "clone error", {}),
        BatchRow("svc3", "ok", "", {"ops": "2", "framework": "SOAP"}),
    ]
    dest = _write_markdown_report("complexity", rows, tmp_path, ["ops", "framework"])
    content = dest.read_text(encoding="utf-8")
    assert "Batch `complexity`" in content
    assert "**OK:** 2" in content
    assert "**FAIL:** 1" in content
    assert "svc1" in content and "svc2" in content


def test_write_csv_report_has_header_and_rows(tmp_path: Path) -> None:
    rows = [
        BatchRow("svc1", "ok", "", {"ops": "1"}),
        BatchRow("svc2", "ok", "", {"ops": "2"}),
    ]
    dest = _write_csv_report("complexity", rows, tmp_path, ["ops"])
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "service,status,detail,ops"
    assert len(lines) == 3


def test_batch_row_default_fields() -> None:
    r = BatchRow("svc", "ok", "", {})
    assert r.service == "svc"
    assert r.status == "ok"
    assert r.fields == {}


def test_find_migrated_project_prefers_expected_service_folder(tmp_path: Path) -> None:
    workspace = tmp_path / "wsclientes0007"
    project = workspace / "destino" / "tnd-msa-sp-wsclientes0007"
    project.mkdir(parents=True)
    (project / "build.gradle").write_text("plugins {}", encoding="utf-8")

    assert _find_migrated_project(workspace, "wsclientes0007") == project


def test_read_structured_message_accepts_fenced_json(tmp_path: Path) -> None:
    output = tmp_path / "last-message.json"
    output.write_text(
        "```json\n"
        '{"status":"ok","summary":"build green","framework":"REST"}\n'
        "```\n",
        encoding="utf-8",
    )

    payload = _read_structured_message(output)
    assert payload["status"] == "ok"
    assert payload["framework"] == "REST"


def test_build_batch_migrate_prompt_contains_workspace_context(tmp_path: Path) -> None:
    workspace = tmp_path / "svc"
    project = workspace / "destino" / "tnd-msa-sp-svc"
    project.mkdir(parents=True)

    prompt = _build_batch_migrate_prompt("svc", workspace, project, "PROMPT BASE")
    assert "Servicio objetivo: svc" in prompt
    assert str(project) in prompt
    assert "PROMPT BASE" in prompt
    assert "NO es un" in prompt
    assert "status=blocked" in prompt
    assert "No uses sub-agentes" in prompt


def test_process_migrate_service_success(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    service = "wsclientes0007"
    workspace = root / service
    project = workspace / "destino" / "tnd-msa-sp-wsclientes0007"
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
        assert Path(cmd[0]).name == "codex"
        assert cmd[1] == "exec"
        assert "--ignore-user-config" in cmd
        assert "--ephemeral" in cmd
        assert "--full-auto" in cmd
        assert "--json" in cmd
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "gpt-5.4"
        output_idx = cmd.index("--output-last-message") + 1
        output_path = Path(cmd[output_idx])
        output_path.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "summary": "Migracion completa",
                    "framework": "REST",
                    "build_status": "green",
                    "migrated_project": str(project),
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"type":"thread.started","thread_id":"session-123"}\n',
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
        codex_bin="codex",
        model=None,
        prompt_file=None,
        timeout_minutes=5,
        run_check=True,
        unsafe=False,
    )

    assert row.status == "ok"
    assert row.fields["codex"] == "ok"
    assert row.fields["framework"] == "REST"
    assert row.fields["build"] == "green"
    assert row.fields["check"] == "READY_TO_MERGE"
    assert row.detail == "Migracion completa"


def test_process_migrate_service_host_build_fallback_promotes_result(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    service = "orqclientes0002"
    workspace = root / service
    project = workspace / "destino" / "tnd-msa-sp-orqclientes0002"
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
        output_idx = cmd.index("--output-last-message") + 1
        output_path = Path(cmd[output_idx])
        output_path.write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "summary": "Migracion completa, pero el sandbox no pudo correr Gradle por falta de Java Runtime.",
                    "framework": "REST + Spring WebFlux",
                    "build_status": "blocked: `./gradlew generateFromWsdl` fallo con `Unable to locate a Java Runtime`",
                    "migrated_project": str(project),
                    "artifacts": [],
                    "notes": ["Se aplicaron los cambios del servicio en `destino/`."],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"type":"thread.started","thread_id":"session-456"}\n',
            stderr="",
        )

    monkeypatch.setattr("capamedia_cli.commands.batch.subprocess.run", fake_run)
    monkeypatch.setattr(
        "capamedia_cli.commands.batch._run_host_build_fallback",
        lambda migrated_project, ts: ("green", "green: build host-side ejecutado con exito"),
    )
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
        codex_bin="codex",
        model=None,
        prompt_file=None,
        timeout_minutes=5,
        run_check=True,
        unsafe=False,
    )

    assert row.status == "ok"
    assert row.fields["result"] == "ok"
    assert row.fields["build"] == "green: build host-side ejecutado con exito"
    assert row.fields["check"] == "READY_TO_MERGE"
    assert "Validacion host-side" in row.detail


def test_process_migrate_service_host_build_fallback_keeps_blocked_when_codex_reported_no_edits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path
    service = "orqclientes0005"
    workspace = root / service
    project = workspace / "destino" / "tnd-msa-sp-orqclientes0005"
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
        output_idx = cmd.index("--output-last-message") + 1
        output_path = Path(cmd[output_idx])
        output_path.write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "summary": "Migracion no iniciada. Falta Java Runtime en el sandbox.",
                    "framework": "REST + Spring WebFlux",
                    "build_status": "blocked: `./gradlew generateFromWsdl` fallo con `Unable to locate a Java Runtime`",
                    "migrated_project": str(project),
                    "artifacts": [],
                    "notes": ["No hice ediciones en el workspace por este bloqueo previo."],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"type":"thread.started","thread_id":"session-789"}\n',
            stderr="",
        )

    monkeypatch.setattr("capamedia_cli.commands.batch.subprocess.run", fake_run)
    monkeypatch.setattr(
        "capamedia_cli.commands.batch._run_host_build_fallback",
        lambda migrated_project, ts: ("green", "green: build host-side ejecutado con exito"),
    )

    row = _process_migrate_service(
        service,
        root,
        schema_path,
        codex_bin="codex",
        model=None,
        prompt_file=None,
        timeout_minutes=5,
        run_check=False,
        unsafe=False,
    )

    assert row.status == "fail"
    assert row.fields["result"] == "blocked"
    assert row.fields["build"] == "green: build host-side ejecutado con exito"
    assert "no hizo ediciones" in row.detail


def test_process_migrate_service_fails_without_destino(tmp_path: Path) -> None:
    root = tmp_path
    service = "wsclientes0008"
    workspace = root / service
    workspace.mkdir()
    _write_fabrics_metadata(workspace, service)
    schema_path = _ensure_migrate_schema(root)

    row = _process_migrate_service(
        service,
        root,
        schema_path,
        codex_bin="codex",
        model=None,
        prompt_file=None,
        timeout_minutes=5,
        run_check=False,
        unsafe=False,
    )

    assert row.status == "fail"
    assert "destino" in row.detail


def test_process_migrate_service_requires_fabrics_metadata(tmp_path: Path) -> None:
    root = tmp_path
    service = "wsclientes0009"
    workspace = root / service
    project = workspace / "destino" / "tnd-msa-sp-wsclientes0009"
    project.mkdir(parents=True)
    (project / "build.gradle").write_text("plugins {}", encoding="utf-8")
    schema_path = _ensure_migrate_schema(root)

    row = _process_migrate_service(
        service,
        root,
        schema_path,
        codex_bin="codex",
        model=None,
        prompt_file=None,
        timeout_minutes=5,
        run_check=False,
        unsafe=False,
    )

    assert row.status == "fail"
    assert "evidencia de Fabrics" in row.detail


def test_process_migrate_service_resume_skips_successful_run(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    service = "wsclientes0007"
    workspace = root / service
    project = workspace / "destino" / "tnd-msa-sp-wsclientes0007"
    project.mkdir(parents=True)
    (project / "build.gradle").write_text("plugins {}", encoding="utf-8")
    _write_fabrics_metadata(workspace, service)
    state_dir = workspace / ".capamedia" / "batch-state"
    state_dir.mkdir(parents=True)
    (state_dir / "migrate.json").write_text(
        json.dumps(
            {
                "service": service,
                "run_kind": "migrate",
                "stages": {
                    "migrate": {"status": "ok", "detail": "done", "fields": {"codex": "ok", "result": "ok", "framework": "REST", "build": "green", "project": project.name}},
                    "check": {"status": "ok", "detail": "READY_TO_MERGE", "fields": {"check": "READY_TO_MERGE"}},
                },
                "result": {"status": "ok", "detail": "done", "fields": {"codex": "ok", "result": "ok", "framework": "REST", "build": "green", "check": "READY_TO_MERGE", "project": project.name}},
            }
        ),
        encoding="utf-8",
    )
    schema_path = _ensure_migrate_schema(root)

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called on resume")

    monkeypatch.setattr("capamedia_cli.commands.batch.subprocess.run", fail_run)

    row = _process_migrate_service(
        service,
        root,
        schema_path,
        codex_bin="codex",
        model=None,
        prompt_file=None,
        timeout_minutes=5,
        run_check=True,
        unsafe=False,
        resume=True,
    )

    assert row.status == "ok"
    assert row.fields["codex"] == "ok"
    assert row.fields["check"] == "READY_TO_MERGE"


def test_find_legacy_root_falls_back_to_local_resolver(tmp_path: Path) -> None:
    capa_media = tmp_path / "CapaMedia"
    workspace = capa_media / "orqclientes0023"
    workspace.mkdir(parents=True)
    variant = capa_media / "0023-ORQ" / "legacy" / "_variants" / "tpr-msa-sp-orqclientes0023"
    variant.mkdir(parents=True)

    assert _find_legacy_root(workspace, "ORQClientes0023") == variant


def test_process_pipeline_service_success(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    service = "wsclientes0007"
    schema_path = _ensure_migrate_schema(root)

    monkeypatch.setattr(
        "capamedia_cli.commands.clone.clone_service",
        lambda service_name, workspace, shallow, skip_tx: None,
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.init.scaffold_project",
        lambda target_dir, service_name, harnesses, artifact_token: (7, []),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.fabrics.inspect_fabrics_workspace",
        lambda workspace: {"status": "ok", "detail": f"config={workspace}"},
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.fabrics.generate",
        lambda service_name, workspace, namespace, group_id, dry_run: _write_fabrics_metadata(workspace, service_name),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.batch._process_migrate_service",
        lambda *args, **kwargs: BatchRow(
            service,
            "ok",
            "pipeline ok",
            {
                "codex": "ok",
                "result": "ok",
                "framework": "REST",
                "build": "green",
                "check": "READY_TO_MERGE",
                "seconds": "10.0",
                "project": "tnd-msa-sp-wsclientes0007",
            },
        ),
    )

    row = _process_pipeline_service(
        service,
        root,
        schema_path,
        harnesses=["codex"],
        artifact_token=None,
        namespace="tnd",
        group_id="com.pichincha.sp",
        codex_bin="codex",
        model=None,
        prompt_file=None,
        timeout_minutes=5,
        skip_tx=False,
        shallow=False,
        skip_check=False,
        unsafe=False,
    )

    assert row.status == "ok"
    assert row.fields["clone"] == "ok"
    assert row.fields["init"] == "ok"
    assert row.fields["fabric"] == "ok"
    assert row.fields["codex"] == "ok"
    assert row.fields["check"] == "READY_TO_MERGE"
    assert row.detail == "pipeline ok"


def test_process_pipeline_service_resume_skips_completed_stages(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    service = "wsclientes0007"
    workspace = root / service
    workspace.mkdir(parents=True)
    (workspace / "legacy" / f"sqb-msa-{service}").mkdir(parents=True)
    (workspace / f"COMPLEXITY_{service}.md").write_text("ok", encoding="utf-8")
    (workspace / ".capamedia" / "config.yaml").parent.mkdir(parents=True)
    (workspace / ".capamedia" / "config.yaml").write_text("service_name: wsclientes0007\n", encoding="utf-8")
    project = workspace / "destino" / "tnd-msa-sp-wsclientes0007"
    project.mkdir(parents=True)
    (project / "build.gradle").write_text("plugins {}", encoding="utf-8")
    _write_fabrics_metadata(workspace, service)
    state_dir = workspace / ".capamedia" / "batch-state"
    state_dir.mkdir(parents=True)
    (state_dir / "pipeline.json").write_text(
        json.dumps(
            {
                "service": service,
                "run_kind": "pipeline",
                "stages": {
                    "clone": {"status": "ok"},
                    "init": {"status": "ok"},
                    "fabric": {"status": "ok"},
                },
                "result": {},
            }
        ),
        encoding="utf-8",
    )
    schema_path = _ensure_migrate_schema(root)

    monkeypatch.setattr(
        "capamedia_cli.commands.batch._process_migrate_service",
        lambda *args, **kwargs: BatchRow(
            service,
            "ok",
            "resume migrate",
            {
                "codex": "ok",
                "result": "ok",
                "framework": "REST",
                "build": "green",
                "check": "READY_TO_MERGE",
                "seconds": "1.0",
                "project": project.name,
            },
        ),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.clone.clone_service",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("clone should be skipped")),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.init.scaffold_project",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("init should be skipped")),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.fabrics.generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fabric should be skipped")),
    )

    row = _process_pipeline_service(
        service,
        root,
        schema_path,
        harnesses=["codex"],
        artifact_token=None,
        namespace="tnd",
        group_id="com.pichincha.sp",
        codex_bin="codex",
        model=None,
        prompt_file=None,
        timeout_minutes=5,
        skip_tx=False,
        shallow=False,
        skip_check=False,
        unsafe=False,
        resume=True,
    )

    assert row.status == "ok"
    assert row.fields["clone"] == "ok"
    assert row.fields["init"] == "ok"
    assert row.fields["fabric"] == "ok"


def test_process_pipeline_service_fails_on_fabrics_preflight(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    service = "wsclientes0010"
    schema_path = _ensure_migrate_schema(root)

    monkeypatch.setattr(
        "capamedia_cli.commands.clone.clone_service",
        lambda service_name, workspace, shallow, skip_tx: None,
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.init.scaffold_project",
        lambda target_dir, service_name, harnesses, artifact_token: (7, []),
    )
    monkeypatch.setattr(
        "capamedia_cli.commands.fabrics.inspect_fabrics_workspace",
        lambda workspace: {"status": "fail", "detail": "token faltante"},
    )

    row = _process_pipeline_service(
        service,
        root,
        schema_path,
        harnesses=["codex"],
        artifact_token=None,
        namespace="tnd",
        group_id="com.pichincha.sp",
        codex_bin="codex",
        model=None,
        prompt_file=None,
        timeout_minutes=5,
        skip_tx=False,
        shallow=False,
        skip_check=False,
        unsafe=False,
    )

    assert row.status == "fail"
    assert row.fields["fabric"] == "fail"
    assert "fabrics preflight failed" in row.detail


def test_collect_watch_rows_uses_pipeline_state_and_fabrics_metadata(tmp_path: Path) -> None:
    root = tmp_path
    service = "wsclientes0011"
    workspace = root / service
    workspace.mkdir(parents=True)
    _write_fabrics_metadata(workspace, service, status="partial")
    state_dir = workspace / ".capamedia" / "batch-state"
    state_dir.mkdir(parents=True)
    (state_dir / "pipeline.json").write_text(
        json.dumps(
            {
                "service": service,
                "run_kind": "pipeline",
                "updated_at": "2026-04-21T15:30:45+00:00",
                "stages": {
                    "clone": {"status": "ok", "attempts": 1, "fields": {"clone": "ok"}},
                    "init": {"status": "ok", "attempts": 1, "fields": {"init": "ok"}},
                    "fabric": {"status": "ok", "attempts": 2, "fields": {"fabric": "partial"}},
                },
                "result": {"status": "partial", "detail": "esperando migrate", "fields": {"project": f"tnd-msa-sp-{service}"}},
            }
        ),
        encoding="utf-8",
    )

    rows = _collect_watch_rows(root, [service], "auto")

    assert len(rows) == 1
    row = rows[0]
    assert row.status == "wait"
    assert row.fields["kind"] == "pipeline"
    assert row.fields["fabric"] == "partial"
    assert row.fields["phase"] == "migrate"
    assert row.fields["attempts"] == "4"
