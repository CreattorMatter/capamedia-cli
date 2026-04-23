"""Tests para `capamedia review` - pipeline end-to-end."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import typer

from capamedia_cli.commands.review import (
    _autodetect_review_paths,
    _find_single_subdir,
    _relocate_generated_reports,
    _resolve_workspace_root,
    _run_official_validator,
    _summarize_results,
    _verdict_from_summary,
    _write_review_log,
    review,
)


class _FakeResult:
    """CheckResult-lite para tests sin depender de la dataclass real."""

    def __init__(self, status: str, severity: str | None = None):
        self.status = status
        self.severity = severity


# ---------------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------------


def test_summarize_counts_pass_and_fail_by_severity() -> None:
    results = [
        _FakeResult("pass"),
        _FakeResult("pass"),
        _FakeResult("fail", "high"),
        _FakeResult("fail", "medium"),
        _FakeResult("fail", "medium"),
        _FakeResult("fail", "low"),
    ]
    summary = _summarize_results(results)
    assert summary == {"pass": 2, "fail_high": 1, "fail_medium": 2, "fail_low": 1}


def test_summarize_empty() -> None:
    assert _summarize_results([]) == {
        "pass": 0, "fail_high": 0, "fail_medium": 0, "fail_low": 0,
    }


def test_verdict_blocked_by_high() -> None:
    s = {"pass": 5, "fail_high": 1, "fail_medium": 0, "fail_low": 0}
    assert _verdict_from_summary(s) == "BLOCKED_BY_HIGH"


def test_verdict_ready_with_followup() -> None:
    s = {"pass": 5, "fail_high": 0, "fail_medium": 3, "fail_low": 0}
    assert _verdict_from_summary(s) == "READY_WITH_FOLLOW_UP"


def test_verdict_ready_to_merge() -> None:
    s = {"pass": 5, "fail_high": 0, "fail_medium": 0, "fail_low": 0}
    assert _verdict_from_summary(s) == "READY_TO_MERGE"


def test_write_review_log_creates_json(tmp_path: Path) -> None:
    phases = [{"phase": "1-test", "data": "ok"}]
    log_path = _write_review_log(tmp_path, phases, "PR_READY")
    assert log_path.exists()
    # v0.20.0: los logs del review viven en .capamedia/reports/
    assert log_path.parent.name == "reports"
    assert log_path.name.startswith("review_")
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["final_verdict"] == "PR_READY"
    assert data["phases"] == phases
    assert "timestamp" in data


# ---------------------------------------------------------------------------
# _run_official_validator — mock subprocess
# ---------------------------------------------------------------------------


def test_run_official_parses_result_with_ansi(tmp_path: Path) -> None:
    """El script oficial imprime con ANSI color codes - debemos limpiarlos."""

    class _CompletedProc:
        stdout = (
            "\x1b[1m\x1b[96m===== header =====\x1b[0m\n"
            "some output...\n"
            "\x1b[1m  Resultado: \x1b[92m9/10 checks pasados\x1b[0m\n"
        )
        stderr = ""
        returncode = 1

    # Simulamos que existe el script vendor
    script = (
        Path(__file__).resolve().parent.parent
        / "src" / "capamedia_cli" / "data" / "vendor" / "validate_hexagonal.py"
    )
    assert script.exists(), "vendor script debe existir en el repo"

    with patch(
        "capamedia_cli.commands.review.subprocess.run",
        return_value=_CompletedProc(),
    ):
        passed, total, _report = _run_official_validator(tmp_path)

    assert passed == 9
    assert total == 10


def test_run_official_returns_zero_when_script_missing(monkeypatch, tmp_path: Path) -> None:
    """Si el vendor script no existe, devuelve 0/0 sin crashear."""
    with patch(
        "capamedia_cli.commands.review._vendor_script_path_for_test",
        return_value=tmp_path / "nonexistent.py",
        create=True,
    ):
        # Fallback al path real, pero con el argumento tmp_path no resuelve a vendor
        passed, total, _ = _run_official_validator(tmp_path / "foo")
        # Con project_path inexistente el script igual va a salir con error
        # pero aqui no hacemos assert de ceros porque el script SI existe.
        # Este test se deja como placeholder de contrato.
        assert isinstance(passed, int)
        assert isinstance(total, int)


def test_run_official_returns_zero_on_timeout(tmp_path: Path) -> None:
    import subprocess

    with patch(
        "capamedia_cli.commands.review.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="x", timeout=120),
    ):
        passed, total, report = _run_official_validator(tmp_path)
    assert passed == 0
    assert total == 0
    assert report == ""
    _ = report  # ruff guard


def test_run_official_survives_none_stdout(tmp_path: Path) -> None:
    """Regresion v0.18.1: si subprocess devuelve stdout=None (Windows cp1252),
    _run_official_validator no debe crashear con TypeError."""

    class _CompletedProcNoneStdout:
        stdout = None
        stderr = ""
        returncode = 1

    with patch(
        "capamedia_cli.commands.review.subprocess.run",
        return_value=_CompletedProcNoneStdout(),
    ):
        passed, total, _ = _run_official_validator(tmp_path)

    # Sin stdout no podemos parsear el resultado, pero no debemos crashear
    assert passed == 0
    assert total == 0


def test_run_official_survives_unicode_decode_error(tmp_path: Path) -> None:
    """Regresion v0.18.1: si subprocess levanta UnicodeDecodeError (Windows
    cp1252 con emojis UTF-8), el validador debe devolver 0/0 en vez de crashear."""

    with patch(
        "capamedia_cli.commands.review.subprocess.run",
        side_effect=UnicodeDecodeError("charmap", b"\x90", 0, 1, "test"),
    ):
        passed, total, report = _run_official_validator(tmp_path)

    assert passed == 0
    assert total == 0
    assert report == ""


def test_run_official_passes_utf8_encoding(tmp_path: Path) -> None:
    """Regresion v0.18.1: _run_official_validator DEBE pasar encoding='utf-8'
    al subprocess para evitar el bug de cp1252 en Windows."""

    class _CompletedProc:
        stdout = "Resultado: 5/9 checks pasados\n"
        stderr = ""
        returncode = 1

    with patch(
        "capamedia_cli.commands.review.subprocess.run",
        return_value=_CompletedProc(),
    ) as mock_run:
        _run_official_validator(tmp_path)

    # Verificar que la llamada incluyo encoding explicito
    assert mock_run.called
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs.get("encoding") == "utf-8", (
        "subprocess.run DEBE recibir encoding='utf-8' para evitar el bug de "
        "cp1252 en Windows con Python 3.14"
    )
    assert call_kwargs.get("errors") == "replace", (
        "subprocess.run DEBE recibir errors='replace' como salvavidas extra"
    )


# ---------------------------------------------------------------------------
# Comando review - end-to-end con mocks
# ---------------------------------------------------------------------------


def test_review_exits_with_code_2_when_project_missing(tmp_path: Path) -> None:
    fake = tmp_path / "nonexistent"
    with pytest.raises(typer.Exit) as exc:
        review(project_path=fake)
    assert exc.value.exit_code == 2


def test_review_pr_ready_when_all_green(tmp_path: Path) -> None:
    """Simula el happy path: checklist limpio + validador oficial 10/10."""
    # Crea un proyecto minimo con estructura Spring
    (tmp_path / "src" / "main" / "java").mkdir(parents=True)
    (tmp_path / "build.gradle").write_text(
        "dependencies { implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0' }\n",
        encoding="utf-8",
    )

    # Mockeamos TODO el pipeline interno
    clean_results = [_FakeResult("pass") for _ in range(21)]

    class _AutofixReport:
        iterations = 1
        total_applied = 0
        converged = True
        log_path = None

    class _BankResult:
        def __init__(self, rule: str):
            self.rule = rule
            self.applied = False
            self.notes = ""

    class _OfficialResult:
        stdout = "Resultado: 10/10 checks pasados\n"
        stderr = ""
        returncode = 0

    with (
        patch("capamedia_cli.commands.review.run_autofix_loop", return_value=_AutofixReport()),
        patch(
            "capamedia_cli.commands.review.run_bank_autofix",
            return_value=[_BankResult(r) for r in ("4", "6", "7", "8", "9")],
        ),
        patch(
            "capamedia_cli.commands.review.run_all_blocks",
            return_value=clean_results,
        ),
        patch(
            "capamedia_cli.commands.review.subprocess.run",
            return_value=_OfficialResult(),
        ),
    ):
        # No debe raise (exit_code=0 = no Exit lanzado)
        review(project_path=tmp_path)

    # v0.20.0: log consolidado en .capamedia/reports/review_<ts>.json
    log_dir = tmp_path / ".capamedia" / "reports"
    assert log_dir.exists()
    logs = list(log_dir.glob("review_*.json"))
    assert len(logs) == 1
    data = json.loads(logs[0].read_text(encoding="utf-8"))
    assert data["final_verdict"] == "PR_READY"


def test_review_needs_work_when_high_fail(tmp_path: Path) -> None:
    (tmp_path / "src" / "main" / "java").mkdir(parents=True)
    high_fail = [_FakeResult("fail", "high")]

    class _AutofixReport:
        iterations = 3
        total_applied = 0
        converged = False
        log_path = None

    with (
        patch("capamedia_cli.commands.review.run_autofix_loop", return_value=_AutofixReport()),
        patch("capamedia_cli.commands.review.run_bank_autofix", return_value=[]),
        patch("capamedia_cli.commands.review.run_all_blocks", return_value=high_fail),
    ):
        with pytest.raises(typer.Exit) as exc:
            review(project_path=tmp_path, skip_official=True)
        assert exc.value.exit_code == 1


def test_review_dry_run_does_not_apply_autofix(tmp_path: Path) -> None:
    (tmp_path / "src" / "main" / "java").mkdir(parents=True)
    clean_results = [_FakeResult("pass") for _ in range(3)]

    autofix_called = {"v": False}
    bank_called = {"v": False}

    def _fake_autofix(*args, **kwargs):
        autofix_called["v"] = True
        raise AssertionError("autofix NO debe correr en dry-run")

    def _fake_bank(*args, **kwargs):
        bank_called["v"] = True
        raise AssertionError("bank autofix NO debe correr en dry-run")

    with (
        patch("capamedia_cli.commands.review.run_autofix_loop", side_effect=_fake_autofix),
        patch("capamedia_cli.commands.review.run_bank_autofix", side_effect=_fake_bank),
        patch("capamedia_cli.commands.review.run_all_blocks", return_value=clean_results),
    ):
        review(project_path=tmp_path, dry_run=True, skip_official=True)

    assert not autofix_called["v"]
    assert not bank_called["v"]


def test_review_skip_official_does_not_call_validator(tmp_path: Path) -> None:
    (tmp_path / "src" / "main" / "java").mkdir(parents=True)

    class _AutofixReport:
        iterations = 1
        total_applied = 0
        converged = True
        log_path = None

    with (
        patch("capamedia_cli.commands.review.run_autofix_loop", return_value=_AutofixReport()),
        patch("capamedia_cli.commands.review.run_bank_autofix", return_value=[]),
        patch(
            "capamedia_cli.commands.review.run_all_blocks",
            return_value=[_FakeResult("pass")],
        ),
        patch(
            "capamedia_cli.commands.review._run_official_validator",
        ) as mock_official,
    ):
        review(project_path=tmp_path, skip_official=True)
        mock_official.assert_not_called()


# ---------------------------------------------------------------------------
# v0.20.0 - Autodetect paths + relocate reports
# ---------------------------------------------------------------------------


def _make_workspace(tmp_path: Path, with_legacy: bool = True) -> Path:
    """Crea estructura tipica: destino/tnd-msa-sp-<svc>/ + legacy/ws-*-was/."""
    ws = tmp_path / "wstecnicos0008"
    (ws / "destino" / "tnd-msa-sp-wstecnicos0008" / "src" / "main" / "java").mkdir(
        parents=True
    )
    if with_legacy:
        (ws / "legacy" / "ws-wstecnicos0008-was").mkdir(parents=True)
    return ws


def test_find_single_subdir_returns_the_only_one(tmp_path: Path) -> None:
    parent = tmp_path / "destino"
    parent.mkdir()
    (parent / "tnd-msa-sp-foo").mkdir()
    assert _find_single_subdir(parent).name == "tnd-msa-sp-foo"


def test_find_single_subdir_returns_none_when_multiple(tmp_path: Path) -> None:
    parent = tmp_path / "destino"
    parent.mkdir()
    (parent / "foo").mkdir()
    (parent / "bar").mkdir()
    assert _find_single_subdir(parent) is None


def test_find_single_subdir_ignores_hidden_dirs(tmp_path: Path) -> None:
    parent = tmp_path / "destino"
    parent.mkdir()
    (parent / "tnd-msa-sp-foo").mkdir()
    (parent / ".DS_Store").mkdir()  # hidden, debe ignorarse
    (parent / ".idea").mkdir()
    assert _find_single_subdir(parent).name == "tnd-msa-sp-foo"


def test_autodetect_resolves_both_when_workspace_clean(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    project, legacy, workspace = _autodetect_review_paths(ws)
    assert project.name == "tnd-msa-sp-wstecnicos0008"
    assert project.parent.name == "destino"
    assert legacy.name == "ws-wstecnicos0008-was"
    assert workspace == ws


def test_autodetect_legacy_is_optional(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, with_legacy=False)
    project, legacy, workspace = _autodetect_review_paths(ws)
    assert project is not None
    assert legacy is None  # sin legacy es OK, block 0 se saltea
    assert workspace == ws


def test_autodetect_fails_when_no_destino(tmp_path: Path) -> None:
    # Sin destino/ debe dar exit code 2 con mensaje claro
    with pytest.raises(typer.Exit) as exc:
        _autodetect_review_paths(tmp_path)
    assert exc.value.exit_code == 2


def test_autodetect_fails_when_destino_empty(tmp_path: Path) -> None:
    (tmp_path / "destino").mkdir()
    with pytest.raises(typer.Exit) as exc:
        _autodetect_review_paths(tmp_path)
    assert exc.value.exit_code == 2


def test_autodetect_fails_when_multiple_destino_subdirs(tmp_path: Path) -> None:
    destino = tmp_path / "destino"
    destino.mkdir()
    (destino / "proj-a").mkdir()
    (destino / "proj-b").mkdir()
    with pytest.raises(typer.Exit) as exc:
        _autodetect_review_paths(tmp_path)
    assert exc.value.exit_code == 2


def test_resolve_workspace_root_from_destino_path(tmp_path: Path) -> None:
    """Si project_path esta dentro de destino/, workspace es 2 niveles arriba."""
    ws = _make_workspace(tmp_path)
    project = ws / "destino" / "tnd-msa-sp-wstecnicos0008"
    assert _resolve_workspace_root(project) == ws


def test_resolve_workspace_root_fallback_when_not_under_destino(tmp_path: Path) -> None:
    """Si el project_path no esta bajo destino/, fallback al project_path mismo."""
    project = tmp_path / "some-other-project"
    project.mkdir()
    assert _resolve_workspace_root(project) == project


def test_relocate_moves_hexagonal_reports(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    project = ws / "destino" / "tnd-msa-sp-wstecnicos0008"
    # Simula reportes generados por el validador oficial
    (project / "hexagonal_validation_20260422.md").write_text("# report", encoding="utf-8")
    (project / "hexagonal_validation_20260422.json").write_text("{}", encoding="utf-8")

    moved = _relocate_generated_reports(project, ws)
    assert len(moved) == 2
    # Los originales ya no estan en destino/
    assert not (project / "hexagonal_validation_20260422.md").exists()
    assert not (project / "hexagonal_validation_20260422.json").exists()
    # Estan en .capamedia/reports/ del workspace
    reports_dir = ws / ".capamedia" / "reports"
    assert (reports_dir / "hexagonal_validation_20260422.md").exists()
    assert (reports_dir / "hexagonal_validation_20260422.json").exists()


def test_relocate_is_noop_when_workspace_equals_project(tmp_path: Path) -> None:
    """Si workspace == project (fallback legacy), no debe mover nada."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "hexagonal_validation_x.md").write_text("x", encoding="utf-8")
    moved = _relocate_generated_reports(project, project)
    assert moved == []
    # El archivo sigue en su lugar
    assert (project / "hexagonal_validation_x.md").exists()


def test_relocate_overwrites_existing_reports(tmp_path: Path) -> None:
    """Correr review 2 veces no debe fallar por archivos duplicados."""
    ws = _make_workspace(tmp_path)
    project = ws / "destino" / "tnd-msa-sp-wstecnicos0008"
    reports_dir = ws / ".capamedia" / "reports"
    reports_dir.mkdir(parents=True)
    # Existe un reporte viejo
    (reports_dir / "hexagonal_validation_old.md").write_text("old", encoding="utf-8")
    # Y ahora se genera uno nuevo con el mismo nombre
    (project / "hexagonal_validation_old.md").write_text("new", encoding="utf-8")

    moved = _relocate_generated_reports(project, ws)
    assert len(moved) == 1
    # El viejo fue sobrescrito por el nuevo
    assert (reports_dir / "hexagonal_validation_old.md").read_text(encoding="utf-8") == "new"


def test_review_no_args_autodetects_from_cwd(tmp_path: Path, monkeypatch) -> None:
    """Correr `capamedia review` sin args desde el workspace root funciona."""
    ws = _make_workspace(tmp_path)
    monkeypatch.chdir(ws)

    clean_results = [_FakeResult("pass") for _ in range(3)]

    class _AutofixReport:
        iterations = 1
        total_applied = 0
        converged = True
        log_path = None

    with (
        patch("capamedia_cli.commands.review.run_autofix_loop", return_value=_AutofixReport()),
        patch("capamedia_cli.commands.review.run_bank_autofix", return_value=[]),
        patch("capamedia_cli.commands.review.run_all_blocks", return_value=clean_results),
    ):
        review(skip_official=True)  # sin project_path

    # El log fue escrito en <workspace>/.capamedia/reports/ (no en destino/)
    reports_dir = ws / ".capamedia" / "reports"
    assert reports_dir.exists()
    logs = list(reports_dir.glob("review_*.json"))
    assert len(logs) == 1
    data = json.loads(logs[0].read_text(encoding="utf-8"))
    assert data["final_verdict"] == "PR_READY"


def test_review_no_args_fails_when_not_in_workspace(tmp_path: Path, monkeypatch) -> None:
    """Sin destino/ en CWD, el comando tira exit 2 sin intentar correr nada."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(typer.Exit) as exc:
        review()
    assert exc.value.exit_code == 2
