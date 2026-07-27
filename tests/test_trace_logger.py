"""Tests para trace-logger + payload por defecto (Checks 7.7 / 7.8 + autofix).

Observabilidad por defecto en TODO servicio migrado (orquestador Y
microservicio). El log transaccional (lib-event-logs) sigue siendo ORQ-only y no
se valida aca. Referencia: orqproductos0044 feature/dev-BTHCCC-9015 (52ea1a8).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from capamedia_cli.core.autofix import (
    Violation,
    fix_trace_logger_application,
    fix_trace_logger_helm,
    run_autofix_loop,
)
from capamedia_cli.core.checklist_rules import (
    CheckContext,
    run_all_blocks,
    run_block_7,
)

_APP_YML_TRACE_OK = (
    "spring:\n"
    "  application:\n"
    "    name: foo\n"
    "trace-logger:\n"
    "  enabled: ${CCC_TRACE_LOGGER_ENABLED}\n"
    "  custom-level:\n"
    "    enabled: ${CCC_CUSTOM_LEVEL_ENABLED}\n"
    "    infoEnabled: ${CCC_CUSTOM_LEVEL_INFO_ENABLED}\n"
    "    debugEnabled: ${CCC_CUSTOM_LEVEL_DEBUG_ENABLED}\n"
    "    warnEnabled: ${CCC_CUSTOM_LEVEL_WARN_ENABLED}\n"
    "    errorEnabled: ${CCC_CUSTOM_LEVEL_ERROR_ENABLED}\n"
    "  payload:\n"
    "    mode: ${CCC_PAYLOAD_MODE}\n"
)

_HELM_HEAD = (
    "livenessProbe:\n  enabled: true\n"
    "readinessProbe:\n  enabled: true\n"
    "keda:\n  enabled: true\n  minReplicaCount: 1\n  maxReplicaCount: 1\n"
    "  triggers:\n    - type: prometheus\n"
    "servicemonitor:\n  enabled: true\n  path: '/actuator/prometheus'\n"
)


def _by_id(results, check_id: str):
    return next(r for r in results if r.id == check_id)


def _make_project(tmp_path: Path, *, app_yml: str = _APP_YML_TRACE_OK) -> Path:
    root = tmp_path / "migrated"
    res = root / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(app_yml, encoding="utf-8")
    return root


def _helm_env_block(env: str) -> str:
    debug = "true" if env == "dev" else "false"
    return (
        "environment:\n"
        '  - name: "CCC_TRACE_LOGGER_ENABLED"\n    value: "true"\n'
        '  - name: "CCC_CUSTOM_LEVEL_ENABLED"\n    value: "true"\n'
        '  - name: "CCC_CUSTOM_LEVEL_INFO_ENABLED"\n    value: "true"\n'
        f'  - name: "CCC_CUSTOM_LEVEL_DEBUG_ENABLED"\n    value: "{debug}"\n'
        '  - name: "CCC_CUSTOM_LEVEL_WARN_ENABLED"\n    value: "true"\n'
        '  - name: "CCC_CUSTOM_LEVEL_ERROR_ENABLED"\n    value: "true"\n'
        '  - name: "CCC_PAYLOAD_MODE"\n    value: "NONE"\n'
    )


def _write_helm(root: Path, *, with_trace: bool, bad_env: str | None = None) -> None:
    helm = root / "helm"
    helm.mkdir(exist_ok=True)
    for env in ("dev", "test", "prod"):
        text = _HELM_HEAD
        if with_trace:
            block = _helm_env_block(env)
            if bad_env == env:
                # Romper solo un flag: PAYLOAD_MODE -> PARTIAL (prohibido)
                block = block.replace('value: "NONE"', 'value: "PARTIAL"')
            text += block
        (helm / f"{env}.yml").write_text(text, encoding="utf-8")


# -- Check 7.7 (application.yml) -------------------------------------------


def test_77_fails_when_block_absent(tmp_path: Path) -> None:
    root = _make_project(tmp_path, app_yml="spring:\n  application:\n    name: foo\n")
    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.7")
    assert check.status == "fail"
    assert check.severity == "high"


def test_77_passes_with_full_block(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.7")
    assert check.status == "pass"


def test_77_fails_when_block_partial(tmp_path: Path) -> None:
    partial = _APP_YML_TRACE_OK.replace(
        "    debugEnabled: ${CCC_CUSTOM_LEVEL_DEBUG_ENABLED}\n", ""
    )
    root = _make_project(tmp_path, app_yml=partial)
    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.7")
    assert check.status == "fail"
    assert "CCC_CUSTOM_LEVEL_DEBUG_ENABLED" in check.detail


def test_77_fails_when_inline_default_instead_of_env(tmp_path: Path) -> None:
    # Regla 7: sin ${VAR:default}. Si usa literal en vez de ${CCC_*}, no matchea.
    literal = _APP_YML_TRACE_OK.replace(
        "  enabled: ${CCC_TRACE_LOGGER_ENABLED}\n", "  enabled: true\n"
    )
    root = _make_project(tmp_path, app_yml=literal)
    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.7")
    assert check.status == "fail"


# -- Check 7.8 (helm env vars) ---------------------------------------------


def test_78_fails_when_env_vars_absent(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    _write_helm(root, with_trace=False)
    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.8")
    assert check.status == "fail"
    assert check.severity == "high"


def test_78_passes_with_correct_per_env_values(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    _write_helm(root, with_trace=True)
    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.8")
    assert check.status == "pass"


def test_78_fails_when_payload_mode_not_none_in_prod(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    _write_helm(root, with_trace=True, bad_env="prod")
    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.8")
    assert check.status == "fail"
    assert "PAYLOAD_MODE" in check.detail


def test_78_fails_when_debug_true_in_prod(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    _write_helm(root, with_trace=True)
    prod = root / "helm" / "prod.yml"
    prod.write_text(
        prod.read_text(encoding="utf-8").replace(
            '- name: "CCC_CUSTOM_LEVEL_DEBUG_ENABLED"\n    value: "false"',
            '- name: "CCC_CUSTOM_LEVEL_DEBUG_ENABLED"\n    value: "true"',
        ),
        encoding="utf-8",
    )
    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.8")
    assert check.status == "fail"
    assert "CCC_CUSTOM_LEVEL_DEBUG_ENABLED" in check.detail


# -- Autofix ----------------------------------------------------------------


def _violation() -> Violation:
    return Violation("7.7", "high", Path(""), 0, "", "")


def test_autofix_application_injects_block(tmp_path: Path) -> None:
    root = _make_project(tmp_path, app_yml="spring:\n  application:\n    name: foo\n")
    result = fix_trace_logger_application(root, _violation())
    assert result.applied
    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.7")
    assert check.status == "pass"
    # YAML sigue siendo valido
    text = (root / "src/main/resources/application.yml").read_text(encoding="utf-8")
    assert yaml.safe_load(text)["trace-logger"]["payload"]["mode"] == "${CCC_PAYLOAD_MODE}"


def test_autofix_application_is_idempotent(tmp_path: Path) -> None:
    root = _make_project(tmp_path, app_yml="spring:\n  application:\n    name: foo\n")
    fix_trace_logger_application(root, _violation())
    second = fix_trace_logger_application(root, _violation())
    assert not second.applied
    text = (root / "src/main/resources/application.yml").read_text(encoding="utf-8")
    assert text.count("trace-logger:") == 1


def test_autofix_application_also_fixes_test_profile(tmp_path: Path) -> None:
    root = _make_project(tmp_path, app_yml="spring:\n  application:\n    name: foo\n")
    test_res = root / "src" / "test" / "resources"
    test_res.mkdir(parents=True)
    (test_res / "application-test.yml").write_text("spring:\n  main:\n    banner-mode: off\n", encoding="utf-8")
    fix_trace_logger_application(root, _violation())
    data = yaml.safe_load((test_res / "application-test.yml").read_text(encoding="utf-8"))
    assert data["trace-logger"]["enabled"] is False
    assert data["trace-logger"]["payload"]["mode"] == "NONE"


def test_autofix_helm_injects_missing_vars_per_env(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    _write_helm(root, with_trace=False)
    result = fix_trace_logger_helm(root, _violation())
    assert result.applied
    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.8")
    assert check.status == "pass"
    # DEBUG_ENABLED debe ser true solo en dev
    dev = yaml.safe_load((root / "helm/dev.yml").read_text(encoding="utf-8"))
    prod = yaml.safe_load((root / "helm/prod.yml").read_text(encoding="utf-8"))

    def _val(doc: dict, var: str) -> str:
        return next(e["value"] for e in doc["environment"] if e["name"] == var)

    assert _val(dev, "CCC_CUSTOM_LEVEL_DEBUG_ENABLED") == "true"
    assert _val(prod, "CCC_CUSTOM_LEVEL_DEBUG_ENABLED") == "false"
    assert _val(prod, "CCC_PAYLOAD_MODE") == "NONE"


def test_autofix_helm_preserves_existing_env_vars(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    helm = root / "helm"
    helm.mkdir()
    for env in ("dev", "test", "prod"):
        (helm / f"{env}.yml").write_text(
            _HELM_HEAD + 'environment:\n  - name: "OTHER"\n    value: "keep"\n',
            encoding="utf-8",
        )
    fix_trace_logger_helm(root, _violation())
    dev = yaml.safe_load((helm / "dev.yml").read_text(encoding="utf-8"))
    names = {e["name"] for e in dev["environment"]}
    assert "OTHER" in names
    assert "CCC_TRACE_LOGGER_ENABLED" in names


def test_autofix_loop_converges_trace_logger(tmp_path: Path) -> None:
    root = _make_project(tmp_path, app_yml="spring:\n  application:\n    name: foo\n")
    _write_helm(root, with_trace=False)

    def rerun():
        return run_all_blocks(CheckContext(migrated_path=root, legacy_path=None))

    run_autofix_loop(root, rerun)
    results = run_block_7(CheckContext(migrated_path=root, legacy_path=None))
    assert _by_id(results, "7.7").status == "pass"
    assert _by_id(results, "7.8").status == "pass"
