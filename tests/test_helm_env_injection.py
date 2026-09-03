"""Inyeccion de env vars en los helm del banco (v0.43.0).

Dos bugs reales encontrados el 2026-09-03 sobre WSSeguridad0069:

1. **El injector rompia el chart.** Los helm del MCP tienen la lista de env vars
   en `variables.own.config`, o sea `variables:` es un MAPPING. El injector
   viejo matcheaba `^variables:\\s*$` e insertaba `- name: ...` justo debajo,
   mezclando una secuencia dentro de un mapping: los 3 helm quedaban con
   `ParserError` y Helm no los renderiza.
2. **El Check 7.8 daba PASS igual**, porque lee los valores con regex y no con
   el parser YAML. La herramienta rompia el chart y despues lo declaraba sano.

Ademas `CCC_PAYLOAD_MODE` llegaba en `FULL`/`PARTIAL` desde el scaffold y el
autofix solo agregaba variables faltantes, nunca corregia un valor existente:
la desviacion quedaba como FAIL HIGH sin arreglo automatico, y `FULL` significa
payload con PII en los logs.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from capamedia_cli.core.autofix import (
    Violation,
    _inject_helm_env_vars,
    _set_helm_env_value,
    fix_helm_probes_enabled_env,
    fix_trace_logger_helm,
    repair_helm_env_structure,
)
from capamedia_cli.core.checklist_rules import CheckContext, run_block_7

# Forma real del chart que emite el MCP Fabrics: `variables.own.config` es la
# lista, `variables` es un mapping y `secret` es un hermano.
MCP_HELM = """# templates Helm diferentes para aks y ocp4

variables:
  own:
    config:
      - name: "JAVA_OPTIONS"
        value: "-XX:MaxRAMPercentage=60.0 -XX:+UseStringDeduplication -XX:+UseG1GC"
      # ACTUATOR
      - name: "CCC_ACTUATOR_BASE_PATH"
        value: "/actuator"
    secret: {}

global:
  environment: "dev"
"""

# Forma legacy con lista directa bajo `environment:` (charts viejos).
LEGACY_HELM = """environment:
  - name: "JAVA_OPTIONS"
    value: "-Xmx256m"
"""


def _payload_mode(text: str) -> str | None:
    data = yaml.safe_load(text)
    config = data["variables"]["own"]["config"]
    return next((i["value"] for i in config if i["name"] == "CCC_PAYLOAD_MODE"), None)


def _violation() -> Violation:
    return Violation("7.8", "high", Path("helm"), 1, "", "")


# ---------------------------------------------------------------------------
# Injector
# ---------------------------------------------------------------------------


def test_inject_into_mcp_chart_keeps_yaml_valid_and_lands_in_the_env_list() -> None:
    result = _inject_helm_env_vars(MCP_HELM, {"CCC_PAYLOAD_MODE": "NONE"})

    data = yaml.safe_load(result)  # antes: ParserError
    config = data["variables"]["own"]["config"]
    names = [item["name"] for item in config]
    assert "CCC_PAYLOAD_MODE" in names
    assert "JAVA_OPTIONS" in names  # no se pierde nada
    assert _payload_mode(result) == "NONE"
    # `variables` sigue siendo mapping con sus dos claves.
    assert set(data["variables"]["own"]) == {"config", "secret"}
    assert data["global"]["environment"] == "dev"


def test_inject_copies_sibling_indentation() -> None:
    result = _inject_helm_env_vars(MCP_HELM, {"CCC_PAYLOAD_MODE": "NONE"})
    injected = next(
        line for line in result.splitlines() if "CCC_PAYLOAD_MODE" in line
    )
    java_options = next(
        line for line in MCP_HELM.splitlines() if "JAVA_OPTIONS" in line
    )
    assert len(injected) - len(injected.lstrip()) == len(java_options) - len(
        java_options.lstrip()
    )


def test_inject_still_supports_legacy_environment_list() -> None:
    result = _inject_helm_env_vars(LEGACY_HELM, {"CCC_PAYLOAD_MODE": "NONE"})
    data = yaml.safe_load(result)
    assert {i["name"] for i in data["environment"]} == {"JAVA_OPTIONS", "CCC_PAYLOAD_MODE"}


def test_inject_creates_block_when_chart_has_no_env_structure() -> None:
    result = _inject_helm_env_vars("global:\n  environment: dev\n", {"CCC_X": "1"})
    data = yaml.safe_load(result)
    assert data["environment"] == [{"name": "CCC_X", "value": "1"}]


# ---------------------------------------------------------------------------
# Correccion de valores (el reporte del usuario)
# ---------------------------------------------------------------------------


def test_set_helm_env_value_rewrites_in_place() -> None:
    text = MCP_HELM.replace(
        '        value: "/actuator"', '        value: "/actuator"\n      - name: "CCC_PAYLOAD_MODE"\n        value: "FULL"'
    )
    assert _payload_mode(text) == "FULL"

    result = _set_helm_env_value(text, "CCC_PAYLOAD_MODE", "NONE")

    assert _payload_mode(result) == "NONE"
    assert yaml.safe_load(result)["variables"]["own"]["secret"] == {}


def _write_env_helm(root: Path, body_by_env: dict[str, str]) -> None:
    (root / "helm").mkdir(parents=True, exist_ok=True)
    for env, body in body_by_env.items():
        (root / "helm" / f"{env}.yml").write_text(body, encoding="utf-8")


def _mcp_helm_with(payload_mode: str, debug: str) -> str:
    extra = (
        f'      - name: "CCC_PAYLOAD_MODE"\n        value: "{payload_mode}"\n'
        f'      - name: "CCC_TRACE_LOGGER_ENABLED"\n        value: "true"\n'
        f'      - name: "CCC_CUSTOM_LEVEL_ENABLED"\n        value: "true"\n'
        f'      - name: "CCC_CUSTOM_LEVEL_INFO_ENABLED"\n        value: "true"\n'
        f'      - name: "CCC_CUSTOM_LEVEL_DEBUG_ENABLED"\n        value: "{debug}"\n'
        f'      - name: "CCC_CUSTOM_LEVEL_WARN_ENABLED"\n        value: "true"\n'
        f'      - name: "CCC_CUSTOM_LEVEL_ERROR_ENABLED"\n        value: "true"\n'
    )
    return MCP_HELM.replace("    secret: {}", extra + "    secret: {}")


def test_autofix_corrects_payload_mode_full_and_partial(tmp_path: Path) -> None:
    """El caso reportado: dev/test en FULL y prod en PARTIAL deben quedar NONE."""
    _write_env_helm(
        tmp_path,
        {
            "dev": _mcp_helm_with("FULL", "true"),
            "test": _mcp_helm_with("FULL", "false"),
            "prod": _mcp_helm_with("PARTIAL", "false"),
        },
    )

    result = fix_trace_logger_helm(tmp_path, _violation())

    assert result.applied
    assert "CCC_PAYLOAD_MODE=NONE" in result.after
    for env in ("dev", "test", "prod"):
        text = (tmp_path / "helm" / f"{env}.yml").read_text(encoding="utf-8")
        assert _payload_mode(text) == "NONE", env
    # Idempotente: nada mas que corregir.
    assert not fix_trace_logger_helm(tmp_path, _violation()).applied


def test_autofix_preserves_per_environment_debug_flag(tmp_path: Path) -> None:
    """DEBUG_ENABLED es true solo en dev: el fix no lo uniformiza."""
    _write_env_helm(
        tmp_path,
        {
            "dev": _mcp_helm_with("NONE", "false"),
            "prod": _mcp_helm_with("NONE", "true"),
        },
    )

    fix_trace_logger_helm(tmp_path, _violation())

    def debug_of(env: str) -> str:
        data = yaml.safe_load((tmp_path / "helm" / f"{env}.yml").read_text(encoding="utf-8"))
        config = data["variables"]["own"]["config"]
        return next(i["value"] for i in config if i["name"] == "CCC_CUSTOM_LEVEL_DEBUG_ENABLED")

    assert debug_of("dev") == "true"
    assert debug_of("prod") == "false"


# ---------------------------------------------------------------------------
# Auto-sanacion de charts ya corrompidos por el injector viejo
# ---------------------------------------------------------------------------

CORRUPTED = MCP_HELM.replace(
    "variables:\n",
    'variables:\n  - name: "CCC_PAYLOAD_MODE"\n    value: "NONE"\n',
)


def test_corrupted_chart_is_invalid_yaml_to_begin_with() -> None:
    try:
        yaml.safe_load(CORRUPTED)
    except yaml.YAMLError:
        return
    raise AssertionError("el fixture deberia ser YAML invalido")


def test_repair_relocates_misplaced_vars_and_leaves_valid_yaml() -> None:
    cleaned, relocated = repair_helm_env_structure(CORRUPTED)

    assert relocated == {"CCC_PAYLOAD_MODE": "NONE"}
    assert yaml.safe_load(cleaned)["variables"]["own"]["secret"] == {}
    # Re-insertar lo relocalizado deja el chart sano y completo.
    final = _inject_helm_env_vars(cleaned, relocated)
    assert _payload_mode(final) == "NONE"


def test_repair_never_touches_a_healthy_chart() -> None:
    cleaned, relocated = repair_helm_env_structure(MCP_HELM)
    assert cleaned == MCP_HELM
    assert relocated == {}


def test_autofix_self_heals_a_corrupted_chart(tmp_path: Path) -> None:
    _write_env_helm(tmp_path, {"dev": CORRUPTED})

    result = fix_trace_logger_helm(tmp_path, _violation())

    assert result.applied
    assert "reubicadas" in result.after
    text = (tmp_path / "helm" / "dev.yml").read_text(encoding="utf-8")
    assert _payload_mode(text) == "NONE"
    assert yaml.safe_load(text)["global"]["environment"] == "dev"


def test_probes_fix_also_lands_inside_the_env_list(tmp_path: Path) -> None:
    _write_env_helm(tmp_path, {"dev": MCP_HELM})

    assert fix_helm_probes_enabled_env(tmp_path, Violation("7.11", "medium", Path("helm"), 1, "", "")).applied

    data = yaml.safe_load((tmp_path / "helm" / "dev.yml").read_text(encoding="utf-8"))
    config = data["variables"]["own"]["config"]
    probes = next(i for i in config if i["name"] == "CCC_ACTUATOR_HEALTH_PROBES_ENABLED")
    assert probes["value"] == "true"


# ---------------------------------------------------------------------------
# Check 7.12: un chart roto no puede pasar en silencio
# ---------------------------------------------------------------------------


def _block7(root: Path) -> dict[str, object]:
    return {r.id: r for r in run_block_7(CheckContext(migrated_path=root, legacy_path=None))}


def _minimal_project(tmp_path: Path, helm_body: str) -> Path:
    root = tmp_path / "csg-msa-sp-svc"
    (root / "src" / "main" / "resources").mkdir(parents=True)
    (root / "src" / "main" / "resources" / "application.yml").write_text(
        "trace-logger:\n  enabled: ${CCC_TRACE_LOGGER_ENABLED}\n", encoding="utf-8"
    )
    _write_env_helm(root, {env: helm_body for env in ("dev", "test", "prod")})
    return root


def test_check_712_fails_on_broken_chart(tmp_path: Path) -> None:
    results = _block7(_minimal_project(tmp_path, CORRUPTED))

    check = results["7.12"]
    assert check.status == "fail"
    assert check.severity == "high"
    assert "dev.yml" in check.detail


def test_check_78_no_longer_passes_on_broken_chart(tmp_path: Path) -> None:
    """El agujero original: el chart roto pasaba porque 7.8 lee con regex."""
    results = _block7(_minimal_project(tmp_path, CORRUPTED))

    assert results["7.8"].status == "fail"
    assert "YAML invalido" in results["7.8"].detail


def test_check_712_passes_on_valid_chart(tmp_path: Path) -> None:
    results = _block7(_minimal_project(tmp_path, _mcp_helm_with("NONE", "true")))
    assert results["7.12"].status == "pass"
