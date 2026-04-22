"""Tests para core/self_correction.py y su integracion con batch migrate."""

from __future__ import annotations

import json
from pathlib import Path

from capamedia_cli.core.self_correction import (
    FailureContext,
    build_correction_appendix,
    extract_failure_context,
    load_failure_context,
    stash_failure_context,
)

# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------


def _make_workspace(tmp_path: Path, service: str) -> tuple[Path, Path]:
    workspace = tmp_path / service
    project = workspace / "destino" / f"tnd-msa-sp-{service}"
    project.mkdir(parents=True, exist_ok=True)
    return workspace, project


def _write_build_logs(
    workspace: Path,
    *,
    stdout: str,
    stderr: str,
    engine_name: str = "claude",
) -> None:
    run_dir = workspace / ".capamedia" / "batch-migrate"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{engine_name}-stdout-20260422-120000.log").write_text(
        stdout, encoding="utf-8"
    )
    (run_dir / f"{engine_name}-stderr-20260422-120000.log").write_text(
        stderr, encoding="utf-8"
    )


def _write_checklist_md(project: Path, service: str, body: str) -> None:
    md = project / f"CHECKLIST_{service}.md"
    md.write_text(body, encoding="utf-8")


def _fail_state(
    service: str,
    *,
    stage_detail: str = "build red",
    attempts: int = 1,
    fields: dict | None = None,
) -> dict:
    return {
        "service": service,
        "run_kind": "migrate",
        "stages": {
            "migrate": {
                "status": "fail",
                "detail": stage_detail,
                "attempts": attempts,
                "fields": fields
                or {
                    "codex": "ok",
                    "result": "failed",
                    "build": "red",
                    "check": "not_run",
                },
            }
        },
        "result": {"status": "fail", "detail": stage_detail, "fields": {}},
    }


# ---------------------------------------------------------------------------
# extract_failure_context
# ---------------------------------------------------------------------------


def test_extract_failure_context_returns_none_when_no_failure(tmp_path: Path) -> None:
    workspace, project = _make_workspace(tmp_path, "wsclientes0007")
    state = {
        "service": "wsclientes0007",
        "run_kind": "migrate",
        "stages": {"migrate": {"status": "ok", "attempts": 1}},
        "result": {"status": "ok"},
    }

    ctx = extract_failure_context(workspace, project, state)
    assert ctx is None


def test_extract_failure_context_parses_build_errors(tmp_path: Path) -> None:
    workspace, project = _make_workspace(tmp_path, "wsclientes0007")
    stderr = "\n".join(
        [
            "> Task :compileJava FAILED",
            "src/main/java/com/pichincha/sp/CustomerAdapter.java:47: error: cannot find symbol",
            "    CustomerPort port;",
            "                 ^",
            "  symbol:   class CustomerPort",
            "BUILD FAILED in 3s",
        ]
    )
    _write_build_logs(workspace, stdout="", stderr=stderr)
    state = _fail_state("wsclientes0007")

    ctx = extract_failure_context(workspace, project, state)
    assert ctx is not None
    assert ctx.failure_category == "build"
    # Tiene que incluir las dos lineas con markers (error: + FAILED + BUILD FAILED)
    joined = "\n".join(ctx.build_errors)
    assert "cannot find symbol" in joined
    assert "BUILD FAILED" in joined
    assert "FAILED" in joined


def test_extract_failure_context_parses_checklist_violations(tmp_path: Path) -> None:
    workspace, project = _make_workspace(tmp_path, "wsclientes0007")
    _write_build_logs(workspace, stdout="", stderr="")
    md = (
        "# Post-Migration Checklist Report: wsclientes0007\n\n"
        "**Verdict:** `BLOCKED_BY_HIGH`\n\n"
        "## Detalle\n\n"
        "### Block 1\n\n"
        "**1.3 Ports son interfaces** - `FAIL-HIGH`\n"
        "  - Detail: CustomerOutputPort.java es abstract class\n"
        "  - Fix: Convertir a interface\n\n"
        "**15.3 setComponente del catalogo** - `FAIL-MEDIUM`\n"
        "  - Detail: setComponente('custom-thing') no esta en el PDF\n\n"
        "**2.1 Constructor injection** - `PASS`\n"
        "  - Detail: OK\n\n"
    )
    _write_checklist_md(project, "wsclientes0007", md)
    state = _fail_state(
        "wsclientes0007",
        stage_detail="checklist BLOCKED_BY_HIGH",
        fields={"codex": "ok", "result": "ok", "build": "green", "check": "BLOCKED_BY_HIGH"},
    )

    ctx = extract_failure_context(workspace, project, state)
    assert ctx is not None
    assert ctx.failure_category == "checklist"
    ids = [v["check_id"] for v in ctx.checklist_violations]
    assert "1.3" in ids
    assert "15.3" in ids
    # El PASS NO debe aparecer
    assert all(v["check_id"] != "2.1" for v in ctx.checklist_violations)

    v13 = next(v for v in ctx.checklist_violations if v["check_id"] == "1.3")
    assert v13["severity"].upper() == "HIGH"
    assert "abstract class" in v13["evidence"]
    # El hint para 1.3 debe ser el del registry de self_correction
    assert "interface" in v13["hint"].lower()


def test_extract_failure_context_classifies_timeout(tmp_path: Path) -> None:
    workspace, project = _make_workspace(tmp_path, "wsclientes0007")
    _write_build_logs(workspace, stdout="", stderr="")
    state = _fail_state(
        "wsclientes0007",
        stage_detail="engine timeout after 90 minutes",
        fields={"codex": "timeout", "result": "failed"},
    )

    ctx = extract_failure_context(workspace, project, state)
    assert ctx is not None
    assert ctx.failure_category == "timeout"


def test_extract_failure_context_returns_none_when_unknown_and_empty(
    tmp_path: Path,
) -> None:
    workspace, project = _make_workspace(tmp_path, "wsclientes0007")
    # Logs vacios + state sin stage migrate pero con result ok -> None
    state = {
        "service": "wsclientes0007",
        "run_kind": "migrate",
        "stages": {},
        "result": {"status": "ok"},
    }
    ctx = extract_failure_context(workspace, project, state)
    assert ctx is None


# ---------------------------------------------------------------------------
# build_correction_appendix
# ---------------------------------------------------------------------------


def test_build_correction_appendix_includes_hints_and_header() -> None:
    ctx = FailureContext(
        attempt=0,
        failure_category="checklist",
        build_errors=[],
        checklist_violations=[
            {
                "check_id": "1.3",
                "severity": "high",
                "title": "Ports son interfaces",
                "evidence": "CustomerOutputPort es abstract class",
                "hint": "Convertir abstract class a interface.",
            },
            {
                "check_id": "15.3",
                "severity": "medium",
                "title": "setComponente del catalogo",
                "evidence": "valor 'custom-thing' invalido",
                "hint": "Usar <nombre-servicio> o ApiClient.",
            },
        ],
        stdout_tail="",
        stderr_tail="",
    )
    out = build_correction_appendix(ctx, "PROMPT BASE ORIGINAL")

    assert "PROMPT BASE ORIGINAL" in out
    assert "INTENTO 1 (correccion automatica)" in out
    assert "violaciones del checklist" in out
    assert "[HIGH] 1.3" in out
    assert "[MEDIUM] 15.3" in out
    assert "Convertir abstract class a interface." in out
    assert "Usar <nombre-servicio> o ApiClient." in out
    assert "NO intentes re-migrar desde cero" in out


def test_build_correction_appendix_includes_build_errors_block() -> None:
    ctx = FailureContext(
        attempt=1,
        failure_category="build",
        build_errors=[
            "> Task :compileJava FAILED",
            "error: cannot find symbol 'CustomerPort'",
        ],
        checklist_violations=[],
        stdout_tail="",
        stderr_tail="irrelevant",
    )
    out = build_correction_appendix(ctx, "BASE")
    assert "### Build errors (tail)" in out
    assert "cannot find symbol" in out
    # Como hay build errors, NO debe haber bloque "Stderr (tail)"
    assert "### Stderr (tail)" not in out


def test_build_correction_appendix_is_idempotent() -> None:
    ctx = FailureContext(
        attempt=0,
        failure_category="build",
        build_errors=["BUILD FAILED"],
        checklist_violations=[],
        stdout_tail="",
        stderr_tail="",
    )
    first = build_correction_appendix(ctx, "BASE PROMPT")
    second = build_correction_appendix(ctx, first)

    # No debe duplicar el marcador ni el header
    assert first.count("<!-- capamedia:self-correction -->") == 1
    assert second.count("<!-- capamedia:self-correction -->") == 1
    assert second.count("INTENTO 1 (correccion automatica)") == 1
    # Y el base original debe seguir presente
    assert "BASE PROMPT" in second


def test_build_correction_appendix_updates_on_second_attempt() -> None:
    ctx1 = FailureContext(
        attempt=0,
        failure_category="build",
        build_errors=["error: first failure"],
        checklist_violations=[],
        stdout_tail="",
        stderr_tail="",
    )
    ctx2 = FailureContext(
        attempt=1,
        failure_category="checklist",
        build_errors=[],
        checklist_violations=[
            {
                "check_id": "1.3",
                "severity": "high",
                "title": "Ports son interfaces",
                "evidence": "evidence2",
                "hint": "hint2",
            }
        ],
        stdout_tail="",
        stderr_tail="",
    )
    first = build_correction_appendix(ctx1, "BASE")
    second = build_correction_appendix(ctx2, first)

    # El appendix viejo fue reemplazado
    assert "first failure" not in second
    assert "hint2" in second
    assert "INTENTO 2 (correccion automatica)" in second


# ---------------------------------------------------------------------------
# stash_failure_context / load_failure_context
# ---------------------------------------------------------------------------


def test_stash_and_load_failure_context_roundtrip() -> None:
    ctx = FailureContext(
        attempt=2,
        failure_category="build",
        build_errors=["BUILD FAILED"],
        checklist_violations=[{"check_id": "1.3", "severity": "high", "title": "t", "evidence": "e", "hint": "h"}],
        stdout_tail="out",
        stderr_tail="err",
    )
    state: dict = {}
    stash_failure_context(state, ctx)
    loaded = load_failure_context(state)
    assert loaded is not None
    assert loaded.attempt == 2
    assert loaded.failure_category == "build"
    assert loaded.build_errors == ["BUILD FAILED"]
    assert loaded.checklist_violations[0]["check_id"] == "1.3"
    assert loaded.stdout_tail == "out"


def test_stash_none_clears_state() -> None:
    state = {"last_failure": {"attempt": 1}}
    stash_failure_context(state, None)
    assert "last_failure" not in state
    assert load_failure_context(state) is None


def test_load_failure_context_handles_missing_and_malformed() -> None:
    assert load_failure_context({}) is None
    assert load_failure_context({"last_failure": "not a dict"}) is None


# ---------------------------------------------------------------------------
# Integration: retry loop con engine fake
# ---------------------------------------------------------------------------


def test_retry_loop_feeds_failure_context_into_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    """Simular retry: iter1 falla con build red, iter2 debe recibir appendix."""
    from capamedia_cli.commands.batch import (
        BatchRow,
        _run_service_with_retries,
    )
    from capamedia_cli.core.batch_state import load_state, save_state

    service = "wsclientes0007"
    workspace, project = _make_workspace(tmp_path, service)
    # Logs de build fallido listos para el retry-1:
    stderr = (
        "> Task :compileJava FAILED\n"
        "error: cannot find symbol\n"
        "BUILD FAILED in 3s\n"
    )
    _write_build_logs(workspace, stdout="ok", stderr=stderr)

    captured_prompts: list[str] = []

    def fake_runner(svc: str, attempt: int) -> BatchRow:
        # Emular lo que hace _process_migrate_service: levantar state y
        # checar si hay last_failure cacheado.
        state = load_state(workspace, "migrate", svc, reset=False)
        from capamedia_cli.core.self_correction import (
            build_correction_appendix,
            load_failure_context,
        )

        base_prompt = "PROMPT BASE"
        ctx = load_failure_context(state)
        if ctx is not None:
            base_prompt = build_correction_appendix(ctx, base_prompt)
        captured_prompts.append(base_prompt)

        if attempt == 0:
            # Primer intento: marca fallo en state y devuelve fail
            state["stages"] = {
                "migrate": {
                    "status": "fail",
                    "detail": "build red",
                    "attempts": 1,
                    "fields": {
                        "codex": "ok",
                        "result": "failed",
                        "build": "red",
                        "check": "not_run",
                    },
                }
            }
            state["result"] = {"status": "fail", "detail": "build red"}
            save_state(workspace, "migrate", state)
            return BatchRow(svc, "fail", "build red", {"build": "red"})
        # Segundo intento: OK
        return BatchRow(svc, "ok", "green", {"build": "green"})

    row = _run_service_with_retries(
        service,
        fake_runner,
        retries=1,
        workspace_resolver=lambda svc: workspace,
        project_resolver=lambda svc, wsp: project,
        run_kind="migrate",
    )

    assert row.status == "ok"
    assert len(captured_prompts) == 2
    # El primer prompt NO tiene appendix
    assert "INTENTO" not in captured_prompts[0]
    assert captured_prompts[0] == "PROMPT BASE"
    # El segundo prompt SI tiene appendix con los build errors
    assert "INTENTO 2 (correccion automatica)" in captured_prompts[1]
    assert "Build errors (tail)" in captured_prompts[1]
    assert "cannot find symbol" in captured_prompts[1]
    # Y el state tiene persistido el last_failure
    persisted = json.loads(
        (workspace / ".capamedia" / "batch-state" / "migrate.json").read_text(
            encoding="utf-8"
        )
    )
    assert "last_failure" in persisted


def test_retry_loop_no_workspace_resolver_is_noop(tmp_path: Path) -> None:
    """Sin workspace_resolver, el loop debe comportarse exactamente como antes."""
    from capamedia_cli.commands.batch import BatchRow, _run_service_with_retries

    calls: list[int] = []

    def runner(svc: str, attempt: int) -> BatchRow:
        calls.append(attempt)
        if attempt == 0:
            return BatchRow(svc, "fail", "boom", {})
        return BatchRow(svc, "ok", "", {})

    row = _run_service_with_retries("svc", runner, retries=1)
    assert row.status == "ok"
    assert calls == [0, 1]


def test_retry_loop_swallows_resolver_errors(tmp_path: Path) -> None:
    """Si workspace_resolver revienta, el retry loop no debe romper."""
    from capamedia_cli.commands.batch import BatchRow, _run_service_with_retries

    calls: list[int] = []

    def runner(svc: str, attempt: int) -> BatchRow:
        calls.append(attempt)
        if attempt == 0:
            return BatchRow(svc, "fail", "boom", {})
        return BatchRow(svc, "ok", "", {})

    def bad_resolver(svc: str):
        raise RuntimeError("resolver broke")

    row = _run_service_with_retries(
        "svc",
        runner,
        retries=1,
        workspace_resolver=bad_resolver,
        run_kind="migrate",
    )
    assert row.status == "ok"
    assert calls == [0, 1]
