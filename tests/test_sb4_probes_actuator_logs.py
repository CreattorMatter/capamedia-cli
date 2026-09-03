"""Spring Boot 4, probes Kubernetes y ruido de Actuator en logs (v0.40.0).

Fuente: doc BPTPSRE-SpringBoot4-probes-actuator-logs (2026-09-02), correos
BPTPSRE (Alexis Padilla / Juan Guillermo Callapina) y hallazgos del TO del
2026-08-25 (8/8 tarjetas rechazadas).

Cubre:
- Politica de versiones: baseline 4.1.1, linea SB3 3.5.15 aceptada para
  existentes, NUNCA bajar (spring_boot_target_version + Check 8.1 + autofix).
- Netty/pins CVE de SB3 no aplican en SB4 (8.7/8.8/8.10 + autofixes).
- lib-bnc-api-client 3.0.0 final en SB4 (8.9 + ola_policy).
- lib-trace-logger-sb4:1.2.0 (8.13 + autofix), lib-event-logs 2.0.0 (8.14 + autofix).
- Probes liveness/readiness (7.10 + autofix), CCC_ACTUATOR_HEALTH_PROBES_ENABLED (7.11).
- TraceLoggerManagementPathConfig (2.10/2.11 + autofix), logs INFO diagnosticos (2.6).
- logging.event.excluded-paths (17.8 + autofix).
- cURL por operacion WSDL en README (0.6).
- MCP minimo v20260827161016, namespace `tem`.
"""

from __future__ import annotations

import json
from pathlib import Path

from capamedia_cli.core.autofix import (
    AUTOFIX_REGISTRY,
    Violation,
    fix_add_trace_logger_management_config,
    fix_event_logs_excluded_paths,
    fix_event_logs_sb4_version,
    fix_helm_probe_paths,
    fix_helm_probes_enabled_env,
    fix_spring_boot_plugin_version,
    fix_trace_logger_sb4_artifact,
    run_autofix_loop,
)
from capamedia_cli.core.bank_autofix import (
    fix_add_libbnc_dependency,
    fix_netty_full_tree_pin,
    fix_remove_netty_pin,
    fix_webflux_security_pins,
)
from capamedia_cli.core.checklist_rules import (
    ORQ_EVENT_LOGS_EXCLUDED_PATHS,
    CheckContext,
    run_block_0,
    run_block_2,
    run_block_7,
    run_block_8,
    run_block_17,
)
from capamedia_cli.core.ola_policy import (
    BANK_NAMESPACES,
    LIB_BNC_API_CLIENT_SB4,
    lib_bnc_api_client_version,
)
from capamedia_cli.core.version_policy import (
    ACTUATOR_LIVENESS_PATH,
    ACTUATOR_PROBES_ENV_VAR,
    ACTUATOR_READINESS_PATH,
    LIB_EVENT_LOGS_VERSION,
    LIB_TRACE_LOGGER_COORD,
    LIB_TRACE_LOGGER_SB3_COORD,
    LIB_TRACE_LOGGER_SB3_VERSION,
    LIB_TRACE_LOGGER_VERSION,
    MCP_MIN_VERSION,
    NETTY_WEBFLUX_ALLOWED_VERSION,
    SPRING_BOOT_BASELINE_VERSION,
    SPRING_BOOT_LEGACY_BASELINE_VERSION,
    is_spring_boot_4,
    lib_event_logs_version,
    lib_trace_logger_coord,
    mcp_build_is_current,
    spring_boot_target_version,
)

SB4 = "plugins { id 'org.springframework.boot' version '4.1.1' }\n"
SB3 = "plugins { id 'org.springframework.boot' version '3.5.16' }\n"
WEBFLUX = "dependencies { implementation 'org.springframework.boot:spring-boot-starter-webflux' }\n"
MVC = "dependencies { implementation 'org.springframework.boot:spring-boot-starter-web' }\n"


def _violation(check_id: str) -> Violation:
    return Violation(check_id, "high", Path("build.gradle"), 1, "", "")


def _project(tmp_path: Path, name: str = "tnd-msa-sp-wsclientes0011") -> Path:
    root = tmp_path / name
    (root / "src" / "main" / "java").mkdir(parents=True)
    (root / "src" / "main" / "resources").mkdir(parents=True)
    return root


def _gradle(root: Path, *parts: str) -> Path:
    f = root / "build.gradle"
    f.write_text("".join(parts), encoding="utf-8")
    return f


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


def _helm(root: Path, name: str, body: str) -> Path:
    (root / "helm").mkdir(exist_ok=True)
    f = root / "helm" / name
    f.write_text(body, encoding="utf-8")
    return f


PROBES_AGGREGATE = """livenessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - |
        if [ "$(curl -s http://localhost:8080/actuator/health | cut -d "{" -f 2 | cut -d "}" -f 1 | cut -d "," -f 1 )" != '"status":"UP"' ];then exit 1; fi
  initialDelaySeconds: 300
  periodSeconds: 30
readinessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - |
        if [ "$(curl -s http://localhost:8080/actuator/health | cut -d "{" -f 2 | cut -d "}" -f 1 | cut -d "," -f 1 )" != '"status":"UP"' ];then exit 1; fi
  timeoutSeconds: 10
"""

PROBES_GREP_OK = """livenessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - |
        if ! curl -s http://localhost:8080/actuator/health/liveness | grep -q '"status":"UP"'; then exit 1; fi
readinessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - |
        if ! curl -s http://localhost:8080/actuator/health/readiness | grep -q '"status":"UP"'; then exit 1; fi
"""

PROBES_CUT_OK = """livenessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - |
        if [ "$(curl -s http://localhost:8080/actuator/health/liveness  | cut -d "{" -f 2 | cut -d "}" -f 1 | cut -d "," -f 1 )" != '"status":"UP"' ];then exit 1; fi
readinessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - |
        if [ "$(curl -s http://localhost:8080/actuator/health/readiness | cut -d "{" -f 2 | cut -d "}" -f 1 | cut -d "," -f 1 )" != '"status":"UP"' ];then exit 1; fi
"""

PROBES_ENV_OK = (
    'environment:\n  - name: "CCC_ACTUATOR_HEALTH_PROBES_ENABLED"\n    value: "true"\n'
)


# ---------------------------------------------------------------------------
# version_policy: nunca bajar, subir dentro de la linea
# ---------------------------------------------------------------------------


def test_spring_boot_target_version_never_downgrades() -> None:
    assert SPRING_BOOT_BASELINE_VERSION == "4.1.1"
    assert SPRING_BOOT_LEGACY_BASELINE_VERSION == "3.5.15"
    assert spring_boot_target_version("3.5.14") == "3.5.15"
    assert spring_boot_target_version("3.5.15") is None
    assert spring_boot_target_version("3.5.16") is None  # linea SB3 se conserva
    assert spring_boot_target_version("4.0.0") == "4.1.1"
    assert spring_boot_target_version("4.1.1") is None
    assert spring_boot_target_version("4.2.0") is None  # mas alto que el MCP: se conserva
    assert spring_boot_target_version("") is None


def test_is_spring_boot_4_and_lib_coords() -> None:
    assert is_spring_boot_4("4.1.1") and not is_spring_boot_4("3.5.16")
    assert lib_trace_logger_coord("4.1.1") == (LIB_TRACE_LOGGER_COORD, LIB_TRACE_LOGGER_VERSION)
    assert lib_trace_logger_coord("3.5.16") == (LIB_TRACE_LOGGER_SB3_COORD, LIB_TRACE_LOGGER_SB3_VERSION)
    assert LIB_TRACE_LOGGER_COORD.endswith("lib-trace-logger-sb4") and LIB_TRACE_LOGGER_VERSION == "1.2.0"
    assert lib_event_logs_version("4.1.1") == LIB_EVENT_LOGS_VERSION == "2.0.0"
    assert lib_event_logs_version("3.5.16") == "1.0.0"


def test_mcp_min_build_is_20260827161016() -> None:
    assert MCP_MIN_VERSION == "v20260827161016"
    assert mcp_build_is_current("1.0.0-alpha.20260827161016") is True
    assert mcp_build_is_current("1.0.0-alpha.20260901000000") is True
    assert mcp_build_is_current("1.0.0-alpha.20260804132641") is False
    assert mcp_build_is_current("1.0.0") is None


def test_lib_bnc_api_client_3_0_0_in_sb4_any_ola() -> None:
    assert LIB_BNC_API_CLIENT_SB4 == "3.0.0"
    assert lib_bnc_api_client_version("wsclientes0011", "4.1.1") == "3.0.0"  # OLA 1
    assert lib_bnc_api_client_version("wsclientes0042", "4.1.1") == "3.0.0"  # OLA 2
    assert lib_bnc_api_client_version("wsclientes0042", "3.5.16") == "2.0.0"
    assert lib_bnc_api_client_version("wsclientes0011") == "1.1.0"


def test_tem_namespace_available() -> None:
    from capamedia_cli.commands.fabrics import NAMESPACE_OPTIONS

    assert "tem" in BANK_NAMESPACES
    assert "tca" in BANK_NAMESPACES
    assert "tem" in NAMESPACE_OPTIONS


# ---------------------------------------------------------------------------
# Check 8.1 + autofix
# ---------------------------------------------------------------------------


def test_8_1_states(tmp_path: Path) -> None:
    root = _project(tmp_path)
    cases = {
        "3.5.14": ("fail", "high"),
        "3.5.16": ("fail", "medium"),
        "4.0.0": ("fail", "high"),
        "4.1.1": ("pass", ""),
        "4.3.0": ("pass", ""),
    }
    for version, (status, severity) in cases.items():
        _gradle(root, f"plugins {{ id 'org.springframework.boot' version '{version}' }}\n")
        check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.1")
        assert (check.status, check.severity) == (status, severity), version


def test_autofix_8_1_bumps_within_line_only(tmp_path: Path) -> None:
    root = _project(tmp_path)
    gradle = _gradle(root, "plugins { id 'org.springframework.boot' version '3.5.13' }\n")
    (root / "migration-context.json").write_text(
        json.dumps({"spring_boot_version": "3.5.13"}), encoding="utf-8"
    )

    result = fix_spring_boot_plugin_version(root, _violation("8.1"))

    assert result.applied
    assert "version '3.5.15'" in gradle.read_text(encoding="utf-8")
    assert '"3.5.15"' in (root / "migration-context.json").read_text(encoding="utf-8")


def test_autofix_8_1_sb4_line_and_never_downgrade(tmp_path: Path) -> None:
    root = _project(tmp_path)
    gradle = _gradle(root, "plugins { id 'org.springframework.boot' version '4.0.2' }\n")
    assert fix_spring_boot_plugin_version(root, _violation("8.1")).applied
    assert "version '4.1.1'" in gradle.read_text(encoding="utf-8")

    gradle.write_text("plugins { id 'org.springframework.boot' version '4.2.0' }\n", encoding="utf-8")
    result = fix_spring_boot_plugin_version(root, _violation("8.1"))
    assert not result.applied
    assert "version '4.2.0'" in gradle.read_text(encoding="utf-8")
    assert "nunca se baja" in result.notes


def test_autofix_8_1_does_not_jump_sb3_to_sb4(tmp_path: Path) -> None:
    """3.5.16 es MEDIUM pero el autofix NO lo salta a 4.x (cambia artifactIds)."""
    root = _project(tmp_path)
    gradle = _gradle(root, SB3)

    report = run_autofix_loop(
        root, lambda: run_block_8(CheckContext(migrated_path=root, legacy_path=None))
    )

    assert report.total_applied == 0
    assert "version '3.5.16'" in gradle.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Netty / pins SB3 no aplican en SB4
# ---------------------------------------------------------------------------


def test_8_7_sb4_flags_4_1_pin_as_downgrade(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _gradle(
        root,
        SB4,
        WEBFLUX,
        "dependencyManagement { dependencies {\n"
        f"  dependency 'io.netty:netty-codec-http:{NETTY_WEBFLUX_ALLOWED_VERSION}'\n"
        "} }\n",
    )
    results = run_block_8(CheckContext(migrated_path=root, legacy_path=None))
    c87 = _find(results, "8.7")
    assert c87.status == "fail" and c87.severity == "medium"
    assert "downgrade" in c87.detail
    assert _find(results, "8.8").status == "pass"
    assert _find(results, "8.10").status == "pass"


def test_8_7_sb4_passes_with_4_2_pin_or_none(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _gradle(
        root, SB4, WEBFLUX,
        "dependencyManagement { dependencies {\n  dependency 'io.netty:netty-codec-http:4.2.17.Final'\n} }\n",
    )
    results = run_block_8(CheckContext(migrated_path=root, legacy_path=None))
    assert _find(results, "8.7").status == "pass"
    assert "no aplican en SB4" in _find(results, "8.7").detail


def test_sb3_netty_rules_unchanged(tmp_path: Path) -> None:
    """La linea SB3 conserva la excepcion 4.1.136 y el gate 8.8."""
    root = _project(tmp_path)
    _gradle(
        root, SB3, WEBFLUX,
        "dependencyManagement { dependencies {\n"
        f"  dependency 'io.netty:netty-codec-http:{NETTY_WEBFLUX_ALLOWED_VERSION}'\n"
        "} }\n",
    )
    results = run_block_8(CheckContext(migrated_path=root, legacy_path=None))
    assert _find(results, "8.7").status == "pass"
    assert _find(results, "8.8").status == "fail"


def test_autofixes_netty_skip_in_sb4(tmp_path: Path) -> None:
    root = _project(tmp_path)
    gradle = _gradle(
        root, SB4, WEBFLUX,
        "dependencyManagement { dependencies {\n"
        f"  dependency 'io.netty:netty-codec-http:{NETTY_WEBFLUX_ALLOWED_VERSION}'\n"
        "  dependency 'io.netty:netty-handler:4.2.17.Final'\n"
        "} }\n",
    )
    assert not fix_netty_full_tree_pin(root).applied
    assert not fix_webflux_security_pins(root).applied

    removed = fix_remove_netty_pin(root)
    text = gradle.read_text(encoding="utf-8")
    assert removed.applied
    assert NETTY_WEBFLUX_ALLOWED_VERSION not in text  # downgrade removido
    assert "4.2.17.Final" in text  # el pin SB4 se conserva
    assert "spring-framework-bom" not in text


# ---------------------------------------------------------------------------
# 8.9 lib-bnc-api-client en SB4
# ---------------------------------------------------------------------------


def _bancs_fabrics(root: Path) -> None:
    (root / ".capamedia").mkdir(exist_ok=True)
    (root / ".capamedia" / "fabrics.json").write_text(
        json.dumps({"source_kind": "iib", "tecnologia": "bus", "invoca_bancs": "true"}),
        encoding="utf-8",
    )


def test_8_9_sb4_rejects_alpha_and_lower(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _bancs_fabrics(root)
    for bad in ("3.0.0-alpha.20260825120715", "2.0.0"):
        _gradle(root, SB4, f"dependencies {{ implementation 'com.pichincha.bnc:lib-bnc-api-client:{bad}' }}\n")
        c89 = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.9")
        assert c89.status == "fail" and c89.severity == "high", bad
    _gradle(root, SB4, "dependencies { implementation 'com.pichincha.bnc:lib-bnc-api-client:3.0.0' }\n")
    assert _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.9").status == "pass"


def test_autofix_libbnc_sb4_sets_3_0_0_and_never_downgrades(tmp_path: Path) -> None:
    root = _project(tmp_path)
    gradle = _gradle(root, SB4, "dependencies {\n    implementation 'com.pichincha.bnc:lib-bnc-api-client:3.0.0-alpha.20260825120715'\n}\n")
    result = fix_add_libbnc_dependency(root, requires_bancs=True, service="wsclientes0011")
    assert result.applied
    assert "lib-bnc-api-client:3.0.0'" in gradle.read_text(encoding="utf-8")

    # SB3 con 3.0.0 declarada: no se baja a 1.1.0
    gradle.write_text(SB3 + "dependencies {\n    implementation 'com.pichincha.bnc:lib-bnc-api-client:3.0.0'\n}\n", encoding="utf-8")
    result = fix_add_libbnc_dependency(root, requires_bancs=True, service="wsclientes0011")
    assert not result.applied
    assert "lib-bnc-api-client:3.0.0'" in gradle.read_text(encoding="utf-8")
    assert "nunca se baja" in result.notes


# ---------------------------------------------------------------------------
# 8.13 / 8.14 + autofixes
# ---------------------------------------------------------------------------


def test_8_13_trace_logger_artifact_per_major(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _gradle(root, SB4, "dependencies { implementation 'com.pichincha.common:lib-trace-logger:1.4.0' }\n")
    c = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.13")
    assert c.status == "fail" and c.severity == "high" and "-sb4" in c.detail

    _gradle(root, SB3, "dependencies { implementation 'com.pichincha.common:lib-trace-logger-sb4:1.2.0' }\n")
    assert _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.13").status == "fail"

    _gradle(root, SB4, "dependencies { implementation 'com.pichincha.common:lib-trace-logger-sb4:1.2.0' }\n")
    assert _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.13").status == "pass"

    _gradle(root, SB3, "dependencies { implementation 'com.pichincha.common:lib-trace-logger:1.4.0' }\n")
    assert _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.13").status == "pass"

    _gradle(root, SB4)
    assert _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.13").status == "fail"


def test_autofix_8_13_rewrites_artifact_in_sb4_only(tmp_path: Path) -> None:
    root = _project(tmp_path)
    gradle = _gradle(root, SB4, "dependencies {\n    implementation 'com.pichincha.common:lib-trace-logger:1.4.0'\n}\n")
    assert fix_trace_logger_sb4_artifact(root, _violation("8.13")).applied
    assert "lib-trace-logger-sb4:1.2.0" in gradle.read_text(encoding="utf-8")
    assert "lib-trace-logger:1.4.0" not in gradle.read_text(encoding="utf-8")

    # SB3 con -sb4: no revertir (revision manual)
    gradle.write_text(SB3 + "dependencies {\n    implementation 'com.pichincha.common:lib-trace-logger-sb4:1.2.0'\n}\n", encoding="utf-8")
    assert not fix_trace_logger_sb4_artifact(root, _violation("8.13")).applied

    # SB3 con version vieja: sube a 1.4.0
    gradle.write_text(SB3 + "dependencies {\n    implementation 'com.pichincha.common:lib-trace-logger:1.3.0'\n}\n", encoding="utf-8")
    assert fix_trace_logger_sb4_artifact(root, _violation("8.13")).applied
    assert "lib-trace-logger:1.4.0" in gradle.read_text(encoding="utf-8")


def test_8_14_event_logs_2_0_0_in_sb4(tmp_path: Path) -> None:
    root = _project(tmp_path, "tnd-msa-sp-orqpagos0011")
    gradle = _gradle(root, SB4, "dependencies {\n    implementation 'com.pichincha.common:lib-event-logs-webflux:1.0.1'\n}\n")
    c = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.14")
    assert c.status == "fail" and c.severity == "high"

    assert fix_event_logs_sb4_version(root, _violation("8.14")).applied
    assert "lib-event-logs-webflux:2.0.0" in gradle.read_text(encoding="utf-8")
    assert _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.14").status == "pass"

    # SB3 con 1.0.1: pasa y no se toca; sin lib: 8.14 no se emite
    gradle.write_text(SB3 + "dependencies { implementation 'com.pichincha.common:lib-event-logs-webflux:1.0.1' }\n", encoding="utf-8")
    assert _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.14").status == "pass"
    _gradle(root, SB4)
    assert _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.14") is None


# ---------------------------------------------------------------------------
# 7.10 / 7.11 probes + autofixes
# ---------------------------------------------------------------------------


def _probe_project(tmp_path: Path, plugin: str, probes: str, env: str = PROBES_ENV_OK) -> Path:
    root = _project(tmp_path)
    _gradle(root, plugin, MVC)
    (root / "src" / "main" / "resources" / "application.yml").write_text(
        "trace-logger:\n  enabled: ${CCC_TRACE_LOGGER_ENABLED}\n", encoding="utf-8"
    )
    for env_name in ("dev.yml", "test.yml", "prod.yml"):
        _helm(root, env_name, env + probes)
    return root


def test_7_10_aggregate_health_is_high_in_sb4_medium_in_sb3(tmp_path: Path) -> None:
    root = _probe_project(tmp_path, SB4, PROBES_AGGREGATE)
    c = _find(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.10")
    assert c.status == "fail" and c.severity == "high"
    assert "dev.yml" in c.detail and "liveness" in c.detail

    root3 = _probe_project(tmp_path / "sb3", SB3, PROBES_AGGREGATE)
    c3 = _find(run_block_7(CheckContext(migrated_path=root3, legacy_path=None)), "7.10")
    assert c3.status == "fail" and c3.severity == "medium"


def test_7_10_accepts_grep_and_cut_forms(tmp_path: Path) -> None:
    for i, probes in enumerate((PROBES_GREP_OK, PROBES_CUT_OK)):
        root = _probe_project(tmp_path / str(i), SB4, probes)
        results = run_block_7(CheckContext(migrated_path=root, legacy_path=None))
        assert _find(results, "7.10").status == "pass"
        assert _find(results, "7.11").status == "pass"


def test_7_10_swapped_paths_fail(tmp_path: Path) -> None:
    swapped = PROBES_GREP_OK.replace("health/liveness", "TMP").replace("health/readiness", "health/liveness").replace("TMP", "health/readiness")
    root = _probe_project(tmp_path, SB4, swapped)
    c = _find(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.10")
    assert c.status == "fail"


def test_autofix_7_10_rewrites_only_probe_paths(tmp_path: Path) -> None:
    root = _probe_project(tmp_path, SB4, PROBES_AGGREGATE)
    result = fix_helm_probe_paths(root, _violation("7.10"))
    assert result.applied and len(result.files_modified) == 3
    text = (root / "helm" / "dev.yml").read_text(encoding="utf-8")
    live, ready = text.split("readinessProbe:")
    assert ACTUATOR_LIVENESS_PATH in live and ACTUATOR_READINESS_PATH not in live
    assert ACTUATOR_READINESS_PATH in ready and ACTUATOR_LIVENESS_PATH not in ready
    assert "initialDelaySeconds: 300" in text and "timeoutSeconds: 10" in text
    assert 'cut -d "{"' in text  # forma cut conservada
    assert _find(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.10").status == "pass"
    # idempotente
    assert not fix_helm_probe_paths(root, _violation("7.10")).applied


def test_7_11_probes_env_var_and_autofix(tmp_path: Path) -> None:
    root = _probe_project(tmp_path, SB4, PROBES_GREP_OK, env="environment:\n")
    c = _find(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.11")
    assert c.status == "fail" and c.severity == "medium"

    assert fix_helm_probes_enabled_env(root, _violation("7.11")).applied
    assert f'name: "{ACTUATOR_PROBES_ENV_VAR}"' in (root / "helm" / "prod.yml").read_text(encoding="utf-8")
    assert _find(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.11").status == "pass"

    # forma mapping con valor distinto de true -> fail, y el autofix no lo pisa
    _helm(root, "dev.yml", f'{ACTUATOR_PROBES_ENV_VAR}: "false"\n' + PROBES_GREP_OK)
    c = _find(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.11")
    assert c.status == "fail" and "dev.yml" in c.detail
    assert not fix_helm_probes_enabled_env(root, _violation("7.11")).applied


# ---------------------------------------------------------------------------
# Block 2: 2.6, 2.10, 2.11 + autofix
# ---------------------------------------------------------------------------


def _java(root: Path, rel: str, body: str) -> Path:
    f = root / "src" / "main" / "java" / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    return f


def test_2_6_flags_diagnostic_info_logs(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _java(
        root,
        "com/pichincha/sp/infrastructure/input/adapter/rest/WsController.java",
        "package com.pichincha.sp.infrastructure.input.adapter.rest;\n"
        "class WsController {\n"
        "  void process() {\n"
        '    log.info("Request received for operation: {}", op);\n'
        '    log.info("Transaccion {} finalizada guid={}", op, guid);\n'
        "  }\n}\n",
    )
    _java(
        root,
        "com/pichincha/sp/application/util/DetectIdValidationHelper.java",
        "class DetectIdValidationHelper {\n  void validate() {\n"
        '    log.log(CustomLogLevel.INFO,\n        "Input validation passed for: {}", req);\n  }\n}\n',
    )
    c = _find(run_block_2(CheckContext(migrated_path=root, legacy_path=None)), "2.6")
    assert c.status == "fail" and c.severity == "medium"
    assert "Request received" in c.detail and "Input validation passed" in c.detail
    assert "WsController.java" in c.detail and "DetectIdValidationHelper.java" in c.detail


def test_2_6_debug_level_is_fine(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _java(root, "com/pichincha/sp/X.java", 'class X { void a() { log.debug("Request received for operation: {}", op); } }\n')
    assert _find(run_block_2(CheckContext(migrated_path=root, legacy_path=None)), "2.6").status == "pass"


def test_2_10_missing_config_is_high_and_autofix_creates_variant(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _gradle(root, SB4, WEBFLUX)
    _java(root, "com/pichincha/sp/Application.java", "package com.pichincha.sp;\n@SpringBootApplication\nclass Application {}\n")
    results = run_block_2(CheckContext(migrated_path=root, legacy_path=None))
    c = _find(results, "2.10")
    assert c.status == "fail" and c.severity == "high" and "Reactive" in c.detail
    assert _find(results, "2.11").status == "fail"

    result = fix_add_trace_logger_management_config(root, _violation("2.10"))
    assert result.applied and len(result.files_modified) == 2
    cfg = root / "src/main/java/com/pichincha/sp/infrastructure/config/TraceLoggerManagementPathConfig.java"
    test = root / "src/test/java/com/pichincha/sp/infrastructure/config/TraceLoggerManagementPathConfigTest.java"
    assert cfg.exists() and test.exists()
    cfg_text = cfg.read_text(encoding="utf-8")
    assert cfg_text.startswith("package com.pichincha.sp.infrastructure.config;")
    assert "instanceof ReactiveRequestInformationExtractor" in cfg_text
    assert "implements BeanPostProcessor, EnvironmentAware" in cfg_text

    results = run_block_2(CheckContext(migrated_path=root, legacy_path=None))
    assert _find(results, "2.10").status == "pass"
    assert _find(results, "2.11").status == "pass"
    assert not fix_add_trace_logger_management_config(root, _violation("2.10")).applied


def test_2_10_wrong_variant_for_stack_fails(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _gradle(root, SB4, MVC)
    _java(
        root,
        "com/pichincha/sp/infrastructure/config/TraceLoggerManagementPathConfig.java",
        "package com.pichincha.sp.infrastructure.config;\n"
        "public class TraceLoggerManagementPathConfig implements BeanPostProcessor {\n"
        "  public Object postProcessAfterInitialization(Object bean, String n) {\n"
        "    if (bean instanceof ReactiveRequestInformationExtractor d) { return d; }\n    return bean;\n  }\n}\n",
    )
    c = _find(run_block_2(CheckContext(migrated_path=root, legacy_path=None)), "2.10")
    assert c.status == "fail" and "variante equivocada" in c.detail


def test_2_11_counts_given_when_then(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _gradle(root, SB4, MVC)
    _java(
        root,
        "com/pichincha/sp/infrastructure/config/TraceLoggerManagementPathConfig.java",
        "package com.pichincha.sp.infrastructure.config;\nclass TraceLoggerManagementPathConfig implements BeanPostProcessor {"
        " Object p(Object bean){ if (bean instanceof ServletRequestInformationExtractor d) return d; return bean; } }\n",
    )
    t = root / "src/test/java/com/pichincha/sp/infrastructure/config/TraceLoggerManagementPathConfigTest.java"
    t.parent.mkdir(parents=True)
    t.write_text("class T {\n" + "".join(f"  @Test void givenX{i}_whenY_thenZ() {{}}\n" for i in range(3)) + "}\n", encoding="utf-8")
    c = _find(run_block_2(CheckContext(migrated_path=root, legacy_path=None)), "2.11")
    assert c.status == "fail" and c.severity == "medium" and "3 metodo" in c.detail


# ---------------------------------------------------------------------------
# 17.8 excluded-paths + autofix
# ---------------------------------------------------------------------------

ORQ_YML_BASE = """spring:
  kafka:
    bootstrap-servers: ${KAFKA_SERVER}
logging:
  level:
    org:
      apache:
        kafka: ${CCC_LOG_LEVEL_KAFKA}
  event:
    mode: 'EXTERNAL'
    kafka:
      topic:
        name: ${KAFKA_TOPIC_AUDITOR}
"""


def test_17_8_excluded_paths_and_autofix(tmp_path: Path) -> None:
    root = _project(tmp_path, "tnd-msa-sp-orqpagos0011")
    _gradle(root, SB4, "dependencies { implementation 'com.pichincha.common:lib-event-logs-webflux:2.0.0' }\n")
    yml = root / "src" / "main" / "resources" / "application.yml"
    yml.write_text(ORQ_YML_BASE, encoding="utf-8")

    c = _find(run_block_17(CheckContext(migrated_path=root, legacy_path=None)), "17.8")
    assert c.status == "fail" and c.severity == "high"

    assert fix_event_logs_excluded_paths(root, _violation("17.8")).applied
    text = yml.read_text(encoding="utf-8")
    assert f"    excluded-paths: {ORQ_EVENT_LOGS_EXCLUDED_PATHS}\n" in text
    assert text.index("excluded-paths") > text.index("  event:")
    assert _find(run_block_17(CheckContext(migrated_path=root, legacy_path=None)), "17.8").status == "pass"
    assert not fix_event_logs_excluded_paths(root, _violation("17.8")).applied


def test_17_8_without_actuator_fails_and_list_form_passes(tmp_path: Path) -> None:
    root = _project(tmp_path, "tnd-msa-sp-orqpagos0011")
    yml = root / "src" / "main" / "resources" / "application.yml"
    yml.write_text(ORQ_YML_BASE + "    excluded-paths: /health,/metrics\n", encoding="utf-8")
    c = _find(run_block_17(CheckContext(migrated_path=root, legacy_path=None)), "17.8")
    assert c.status == "fail" and "/actuator/**" in c.detail
    assert not fix_event_logs_excluded_paths(root, _violation("17.8")).applied  # no pisa

    yml.write_text(ORQ_YML_BASE + "    excluded-paths:\n      - /actuator/**\n      - /health\n", encoding="utf-8")
    assert _find(run_block_17(CheckContext(migrated_path=root, legacy_path=None)), "17.8").status == "pass"


# ---------------------------------------------------------------------------
# 0.6 cURL por operacion
# ---------------------------------------------------------------------------

WSDL = """<definitions xmlns="http://schemas.xmlsoap.org/wsdl/" xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" targetNamespace="http://x">
  <wsdl:portType name="WSPagos0017PortType">
    <wsdl:operation name="consultarPago"/>
    <wsdl:operation name="registrarPago"/>
  </wsdl:portType>
</definitions>
"""


def _wsdl_project(tmp_path: Path) -> Path:
    root = _project(tmp_path)
    _java(root, "com/pichincha/sp/infrastructure/input/adapter/rest/C.java", "@RestController class C {}\n")
    (root / "src" / "main" / "resources" / "legacy").mkdir()
    (root / "src" / "main" / "resources" / "legacy" / "WSPagos0017.wsdl").write_text(WSDL, encoding="utf-8")
    return root


def test_0_6_curl_per_operation(tmp_path: Path) -> None:
    root = _wsdl_project(tmp_path)
    c = _find(run_block_0(CheckContext(migrated_path=root, legacy_path=None)), "0.6")
    assert c.status == "fail" and c.severity == "medium"
    assert "consultarPago" in c.detail and "registrarPago" in c.detail

    (root / "README.md").write_text(
        "# Servicio\n\n## consultarPago\n\n```bash\ncurl -X POST http://localhost:8080/IntegrationBus/soap/WSPagos0017 "
        "-H 'Content-Type: text/xml;charset=utf-8' -d '<consultarPago/>'\n```\n",
        encoding="utf-8",
    )
    c = _find(run_block_0(CheckContext(migrated_path=root, legacy_path=None)), "0.6")
    assert c.status == "fail" and "registrarPago" in c.detail and "consultarPago" not in c.detail

    (root / "docs").mkdir()
    (root / "docs" / "curl.md").write_text("```sh\ncurl ... -d '<registrarPago/>'\n```\n", encoding="utf-8")
    assert _find(run_block_0(CheckContext(migrated_path=root, legacy_path=None)), "0.6").status == "pass"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_new_autofixes_registered() -> None:
    for check_id in ("2.10", "2.11", "7.10", "7.11", "8.13", "8.14", "17.8"):
        assert check_id in AUTOFIX_REGISTRY, check_id
