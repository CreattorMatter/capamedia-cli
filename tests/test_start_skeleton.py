"""Tests del esqueleto de `capamedia start` (Fase 1 del wizard).

Verifica que la fachada NO-interactiva orqueste el pipeline existente con los
kwargs correctos (Opus forzado), persista las decisiones en wizard.json y
propague --resume. Mockea _process_pipeline_service: la Fase 1 es cableado, no
logica nueva.
"""

from __future__ import annotations

import pytest

import capamedia_cli.commands.batch as batch_mod
import capamedia_cli.commands.clone as clone_mod
import capamedia_cli.commands.start as start_mod
from capamedia_cli.commands.batch import BatchRow
from capamedia_cli.commands.start import (
    _resolve_branch_interactive,
    load_wizard_decisions,
    start_command,
)


class _FakeEngine:
    name = "claude"
    subscription_type = "max"


@pytest.fixture
def captured(monkeypatch, tmp_path):
    """Mockea el backbone y captura los kwargs con que se invoca el pipeline."""
    grabbed: dict = {}

    def fake_pipeline(service, root, schema_path, **kwargs):
        grabbed["service"] = service
        grabbed["root"] = root
        grabbed["schema_path"] = schema_path
        grabbed.update(kwargs)
        return BatchRow(service, "ok", "pipeline ok (mock)", {"project": "tnd-msa-sp-x"})

    monkeypatch.setattr(batch_mod, "_process_pipeline_service", fake_pipeline)
    monkeypatch.setattr(batch_mod, "_ensure_migrate_schema", lambda ws: ws / "schema.json")
    monkeypatch.setattr(start_mod, "select_engine", lambda *a, **k: _FakeEngine())
    monkeypatch.setattr(start_mod, "engine_from_env", lambda: None)
    # Default: modo "nuevo" (sin destino migrado previo). No toca red.
    monkeypatch.setattr(clone_mod, "_clone_migrated_repos", lambda *a, **k: [])
    return grabbed


def test_start_forces_opus_and_orchestrates_pipeline(captured, tmp_path):
    start_command(service="wsclientes0076", namespace="tnd", root=tmp_path)

    assert captured["service"] == "wsclientes0076"
    assert captured["namespace"] == "tnd"
    # Decision owner: SIEMPRE Opus 4.8, el wizard no pregunta modelo.
    assert captured["model"] == "claude-opus-4-8"
    assert captured["resume"] is False
    assert "claude" in captured["harnesses"]
    assert captured["group_id"] == "com.pichincha.sp"
    # reasoning lo ignora claude/opus en Fase 1.
    assert captured["reasoning_effort"] is None


def test_start_persists_wizard_decisions(captured, tmp_path):
    start_command(service="wsclientes0099", namespace="csg", branch="feature/dev-X", root=tmp_path)

    decisions = load_wizard_decisions(tmp_path / "wsclientes0099")
    assert decisions["service"] == "wsclientes0099"
    assert decisions["namespace"] == "csg"
    assert decisions["branch"] == "feature/dev-X"
    assert decisions["model"] == "claude-opus-4-8"
    assert decisions["engine"] == "claude"
    assert decisions["phase"] == "1-skeleton"


def test_start_branch_persisted_but_not_passed_to_pipeline(captured, tmp_path):
    """Fase 1: el branch se registra pero su integracion real es una fase posterior."""
    start_command(service="wstecnicos0006", namespace="tct", branch="feature/x", root=tmp_path)

    # El pipeline NO recibe branch (clone_service no lo soporta aun).
    assert "branch" not in captured
    # Pero queda persistido para la fase que lo use.
    assert load_wizard_decisions(tmp_path / "wstecnicos0006")["branch"] == "feature/x"


def test_start_resume_propagates(captured, tmp_path):
    start_command(service="wsclientes0076", namespace="tnd", root=tmp_path, resume=True)
    assert captured["resume"] is True


def test_start_model_matches_engine_not_hardcoded_claude(monkeypatch, tmp_path):
    """Regresion: el modelo se deriva del engine activo, NO se hardcodea claude.
    Con --engine codex, el modelo debe ser el tope de codex (gpt-5.5), no
    claude-opus-4-8 (que romperia Codex)."""
    grabbed: dict = {}

    def fake_pipeline(service, root, schema_path, **kwargs):
        grabbed.update(kwargs)
        return BatchRow(service, "ok", "ok", {})

    class _CodexEngine:
        name = "codex"
        subscription_type = "api"

    monkeypatch.setattr(batch_mod, "_process_pipeline_service", fake_pipeline)
    monkeypatch.setattr(batch_mod, "_ensure_migrate_schema", lambda ws: ws / "schema.json")
    monkeypatch.setattr(start_mod, "select_engine", lambda *a, **k: _CodexEngine())
    monkeypatch.setattr(start_mod, "engine_from_env", lambda: None)
    monkeypatch.setattr(clone_mod, "_clone_migrated_repos", lambda *a, **k: [])

    start_command(service="wsclientes0076", namespace="tnd", engine_name="codex", root=tmp_path)
    assert grabbed["model"] == "gpt-5.5"  # tier opus traducido a codex, no claude
    assert load_wizard_decisions(tmp_path / "wsclientes0076")["model"] == "gpt-5.5"


def test_start_exits_nonzero_on_pipeline_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(
        batch_mod,
        "_process_pipeline_service",
        lambda service, root, schema_path, **kw: BatchRow(service, "fail", "clone failed", {}),
    )
    monkeypatch.setattr(batch_mod, "_ensure_migrate_schema", lambda ws: ws / "schema.json")
    monkeypatch.setattr(start_mod, "select_engine", lambda *a, **k: _FakeEngine())
    monkeypatch.setattr(start_mod, "engine_from_env", lambda: None)
    monkeypatch.setattr(clone_mod, "_clone_migrated_repos", lambda *a, **k: [])

    import typer

    with pytest.raises(typer.Exit):
        start_command(service="wsx0001", namespace="tnd", root=tmp_path)


# ── Fase 2: modo interactivo (bienvenida + preflight + menu) ─────────────────


@pytest.fixture
def fake_preflight(monkeypatch):
    """PAT ok + claude disponible, sin tocar red."""
    monkeypatch.setattr(start_mod, "probe_azure_devops_pat", lambda *a, **k: ("ok", "PAT valido"))
    monkeypatch.setattr(
        start_mod,
        "available_engines",
        lambda **k: {"claude": (True, "claude 1.0"), "codex": (False, "no instalado")},
    )


def _force_tty(monkeypatch, is_tty: bool):
    monkeypatch.setattr(start_mod.sys.stdin, "isatty", lambda: is_tty)


def test_non_interactive_without_flags_raises_when_no_tty(monkeypatch, tmp_path):
    """Sin TTY y sin --service/--namespace: error claro, NO se cuelga."""
    _force_tty(monkeypatch, False)
    import typer

    with pytest.raises(typer.BadParameter):
        start_command(root=tmp_path)


def test_interactive_menu_exit(monkeypatch, tmp_path, fake_preflight):
    """TTY, sin flags: muestra menu; elegir '0' sale sin tocar el pipeline."""
    _force_tty(monkeypatch, True)
    called = {"pipeline": False}
    monkeypatch.setattr(
        batch_mod, "_process_pipeline_service",
        lambda *a, **k: called.__setitem__("pipeline", True) or BatchRow("x", "ok", "", {}),
    )
    monkeypatch.setattr(start_mod.Prompt, "ask", lambda *a, **k: "0")

    start_command(root=tmp_path)  # no raise, no pipeline
    assert called["pipeline"] is False


def test_interactive_subwizard_collects_and_runs(monkeypatch, tmp_path, captured, fake_preflight):
    """Fase 3: 'Iniciar' (1) sin flags abre el sub-wizard, recolecta inputs y corre.

    Prompt.ask: '1' (menu) -> 'wsclientes50' (servicio, se normaliza) -> 'tnd' (ns).
    Confirm.ask: True (destino) -> False (harnesses extra) -> True (ejecutar plan).
    """
    _force_tty(monkeypatch, True)
    prompts = iter(["1", "wsclientes50", "tnd"])
    # destino=True, harness_extra=False, especificar_rama=False, ejecutar=True
    confirms = iter([True, False, False, True])
    monkeypatch.setattr(start_mod.Prompt, "ask", lambda *a, **k: next(prompts))
    monkeypatch.setattr(start_mod.Confirm, "ask", lambda *a, **k: next(confirms))

    start_command(root=tmp_path)

    assert captured["service"] == "wsclientes0050"  # auto-padding aplicado
    assert captured["namespace"] == "tnd"
    assert captured["model"] == "claude-opus-4-8"


def test_interactive_subwizard_reprompts_on_empty_service(monkeypatch, tmp_path, captured, fake_preflight):
    """Regresion: servicio vacio re-pregunta (no continua con '' y rompe luego)."""
    _force_tty(monkeypatch, True)
    # '1' menu -> '' (vacio, re-pregunta) -> 'wsclientes0050' -> 'tnd'
    prompts = iter(["1", "", "wsclientes0050", "tnd"])
    confirms = iter([True, False, False, True])
    monkeypatch.setattr(start_mod.Prompt, "ask", lambda *a, **k: next(prompts))
    monkeypatch.setattr(start_mod.Confirm, "ask", lambda *a, **k: next(confirms))

    start_command(root=tmp_path)
    assert captured["service"] == "wsclientes0050"


def test_interactive_subwizard_cancel_at_plan_does_not_run(monkeypatch, tmp_path, fake_preflight):
    """Si el usuario rechaza el gate final 'Ejecutar?', NO corre el pipeline."""
    _force_tty(monkeypatch, True)
    called = {"pipeline": False}
    monkeypatch.setattr(
        batch_mod, "_process_pipeline_service",
        lambda *a, **k: called.__setitem__("pipeline", True) or BatchRow("x", "ok", "", {}),
    )
    prompts = iter(["1", "wsclientes0050", "tnd"])
    # destino=True, harness_extra=False, especificar_rama=False, ejecutar=False
    confirms = iter([True, False, False, False])
    monkeypatch.setattr(start_mod.Prompt, "ask", lambda *a, **k: next(prompts))
    monkeypatch.setattr(start_mod.Confirm, "ask", lambda *a, **k: next(confirms))

    start_command(root=tmp_path)
    assert called["pipeline"] is False


def test_interactive_iniciar_with_flags_runs(monkeypatch, tmp_path, captured, fake_preflight):
    """TTY pero con --service/--namespace: corre directo (no entra al menu)."""
    _force_tty(monkeypatch, True)
    start_command(service="wsclientes0076", namespace="tnd", root=tmp_path)
    assert captured["service"] == "wsclientes0076"
    assert captured["model"] == "claude-opus-4-8"


def test_interactive_resume_from_wizard_json(monkeypatch, tmp_path, captured, fake_preflight):
    """Hay wizard.json previo: 'Iniciar' reanuda ese servicio."""
    _force_tty(monkeypatch, True)
    # Sembramos una sesion previa
    svc_ws = tmp_path / "wsclientes0099"
    (svc_ws / ".capamedia").mkdir(parents=True)
    (svc_ws / ".capamedia" / "wizard.json").write_text(
        '{"service": "wsclientes0099", "namespace": "csg"}', encoding="utf-8"
    )
    monkeypatch.setattr(start_mod.Prompt, "ask", lambda *a, **k: "1")
    # Ahora se pide confirmacion explicita para reanudar (default True).
    monkeypatch.setattr(start_mod.Confirm, "ask", lambda *a, **k: True)

    start_command(root=tmp_path)
    assert captured["service"] == "wsclientes0099"
    assert captured["namespace"] == "csg"
    assert captured["resume"] is True


# ── Fase 4: _resolve_branch_interactive (picker de rama) ─────────────────────


def test_flow_retomar_detected_runs_branch_picker(monkeypatch, tmp_path, captured):
    """Flujo 'ambos': si el destino migrado existe, modo retomar -> se posiciona
    la rama (picker) y se registra flow_mode='retomar'."""

    class _Result:
        path = tmp_path / "wsclientes0076" / "destino" / "tnd-msa-sp-wsclientes0076"

    # Override del default 'nuevo' del fixture: ahora SI hay destino.
    monkeypatch.setattr(clone_mod, "_clone_migrated_repos", lambda *a, **k: [_Result()])
    branch_called = {}
    monkeypatch.setattr(
        start_mod, "_resolve_branch_interactive",
        lambda repo, req, svc: branch_called.update({"repo": repo, "svc": svc}) or ("feature/x", "picker"),
    )

    start_command(service="wsclientes0076", namespace="tnd", root=tmp_path)

    assert branch_called["svc"] == "wsclientes0076"
    assert load_wizard_decisions(tmp_path / "wsclientes0076")["flow_mode"] == "retomar"


def test_flow_nuevo_when_no_migrated(captured, tmp_path):
    """Sin destino migrado (fixture default []): modo nuevo, sin picker."""
    start_command(service="wsclientes0076", namespace="tnd", root=tmp_path)
    assert load_wizard_decisions(tmp_path / "wsclientes0076")["flow_mode"] == "nuevo"


def test_resolve_branch_non_ambiguous_delegates(monkeypatch, tmp_path):
    """explicit/auto/default: delega a _auto_checkout y devuelve tal cual (sin picker)."""
    monkeypatch.setattr(
        clone_mod, "_auto_checkout_migrated_branch",
        lambda repo, req: ("feature/dev-X", "auto", ""),
    )
    branch, mode = _resolve_branch_interactive(tmp_path, None, "wsclientes0076")
    assert (branch, mode) == ("feature/dev-X", "auto")


def test_resolve_branch_ambiguous_picker_selects(monkeypatch, tmp_path):
    """ambiguous -> picker; el usuario elige una rama existente -> checkout."""
    monkeypatch.setattr(
        clone_mod, "_auto_checkout_migrated_branch",
        lambda repo, req: ("", "ambiguous", "varias"),
    )
    monkeypatch.setattr(
        clone_mod, "_list_remote_branches",
        lambda repo: ["feature/a", "feature/b"],
    )
    checked = {}
    monkeypatch.setattr(
        clone_mod, "_checkout_branch",
        lambda repo, b: (checked.__setitem__("branch", b) or (True, "")),
    )
    monkeypatch.setattr(start_mod.Prompt, "ask", lambda *a, **k: "2")  # elige feature/b

    branch, mode = _resolve_branch_interactive(tmp_path, None, "wsclientes0076")
    assert branch == "feature/b"
    assert mode == "picker"
    assert checked["branch"] == "feature/b"


def test_resolve_branch_ambiguous_create_new(monkeypatch, tmp_path):
    """ambiguous -> picker; el usuario elige '0' -> crea feature/migracion-<svc>."""
    monkeypatch.setattr(
        clone_mod, "_auto_checkout_migrated_branch",
        lambda repo, req: ("", "ambiguous", "varias"),
    )
    monkeypatch.setattr(clone_mod, "_list_remote_branches", lambda repo: ["feature/a", "feature/b"])
    ran = {}
    monkeypatch.setattr(
        start_mod.subprocess, "run",
        lambda *a, **k: ran.__setitem__("cmd", a[0]) or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    monkeypatch.setattr(start_mod.Prompt, "ask", lambda *a, **k: "0")

    branch, mode = _resolve_branch_interactive(tmp_path, None, "wsclientes0076")
    assert branch == "feature/migracion-wsclientes0076"
    assert mode == "created"
    assert "checkout" in ran["cmd"] and "-B" in ran["cmd"]
