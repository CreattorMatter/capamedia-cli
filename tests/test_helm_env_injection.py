"""Inyeccion y correccion de env vars en los helm del banco.

Dos bugs reales de `fix_trace_logger_helm`:

1. **Rompia el chart.** Los helm del MCP tienen la lista de env vars en
   `variables.own.config`, o sea `variables:` es un MAPPING. El injector
   matcheaba `^variables:\\s*$` e insertaba `- name: ...` justo debajo,
   mezclando una secuencia dentro de un mapping: `ParserError` y Helm no
   renderiza el chart.
2. **No corregia valores.** Solo agregaba las env vars ausentes, asi que un
   `CCC_PAYLOAD_MODE=FULL` heredado del scaffold quedaba tal cual (Check 7.8
   lo marcaba HIGH pero nadie lo arreglaba). `FULL` significa payload con PII
   en los logs; el unico valor valido es `NONE` en los 3 ambientes.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from capamedia_cli.core.autofix import (
    Violation,
    _inject_helm_env_vars,
    _set_helm_env_value,
    fix_trace_logger_helm,
)

# Forma real del chart que emite el MCP Fabrics.
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

LEGACY_HELM = """environment:
  - name: "JAVA_OPTIONS"
    value: "-Xmx256m"
"""

TRACE_LOGGER_VARS = (
    "CCC_TRACE_LOGGER_ENABLED",
    "CCC_CUSTOM_LEVEL_ENABLED",
    "CCC_CUSTOM_LEVEL_INFO_ENABLED",
    "CCC_CUSTOM_LEVEL_WARN_ENABLED",
    "CCC_CUSTOM_LEVEL_ERROR_ENABLED",
)


def _violation() -> Violation:
    return Violation("7.8", "high", Path("helm"), 1, "", "")


def _config(text: str) -> list[dict]:
    return yaml.safe_load(text)["variables"]["own"]["config"]


def _value_of(text: str, var: str) -> str | None:
    return next((i["value"] for i in _config(text) if i["name"] == var), None)


def _mcp_helm_with(payload_mode: str, debug: str) -> str:
    extra = f'      - name: "CCC_PAYLOAD_MODE"\n        value: "{payload_mode}"\n'
    extra += f'      - name: "CCC_CUSTOM_LEVEL_DEBUG_ENABLED"\n        value: "{debug}"\n'
    for var in TRACE_LOGGER_VARS:
        extra += f'      - name: "{var}"\n        value: "true"\n'
    return MCP_HELM.replace("    secret: {}", extra + "    secret: {}")


def _write_env_helm(root: Path, body_by_env: dict[str, str]) -> None:
    (root / "helm").mkdir(parents=True, exist_ok=True)
    for env, body in body_by_env.items():
        (root / "helm" / f"{env}.yml").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Injector: no puede romper el chart
# ---------------------------------------------------------------------------


def test_inject_into_mcp_chart_keeps_yaml_valid_and_lands_in_the_env_list() -> None:
    result = _inject_helm_env_vars(MCP_HELM, {"CCC_PAYLOAD_MODE": "NONE"})

    data = yaml.safe_load(result)  # antes: ParserError
    names = [item["name"] for item in data["variables"]["own"]["config"]]
    assert "CCC_PAYLOAD_MODE" in names
    assert "JAVA_OPTIONS" in names  # no se pierde nada
    assert _value_of(result, "CCC_PAYLOAD_MODE") == "NONE"
    # `variables.own` sigue siendo un mapping con sus dos claves.
    assert set(data["variables"]["own"]) == {"config", "secret"}
    assert data["global"]["environment"] == "dev"


def test_inject_copies_the_indentation_of_an_existing_item() -> None:
    result = _inject_helm_env_vars(MCP_HELM, {"CCC_PAYLOAD_MODE": "NONE"})
    injected = next(line for line in result.splitlines() if "CCC_PAYLOAD_MODE" in line)
    sibling = next(line for line in MCP_HELM.splitlines() if "JAVA_OPTIONS" in line)

    assert len(injected) - len(injected.lstrip()) == len(sibling) - len(sibling.lstrip())


def test_inject_still_supports_the_legacy_environment_list() -> None:
    data = yaml.safe_load(_inject_helm_env_vars(LEGACY_HELM, {"CCC_PAYLOAD_MODE": "NONE"}))
    assert {i["name"] for i in data["environment"]} == {"JAVA_OPTIONS", "CCC_PAYLOAD_MODE"}


def test_inject_creates_a_block_when_the_chart_has_no_env_structure() -> None:
    data = yaml.safe_load(_inject_helm_env_vars("global:\n  environment: dev\n", {"CCC_X": "1"}))
    assert data["environment"] == [{"name": "CCC_X", "value": "1"}]


# ---------------------------------------------------------------------------
# Correccion de valores: CCC_PAYLOAD_MODE debe quedar en NONE
# ---------------------------------------------------------------------------


def test_set_helm_env_value_rewrites_in_place() -> None:
    text = _mcp_helm_with("FULL", "true")
    assert _value_of(text, "CCC_PAYLOAD_MODE") == "FULL"

    result = _set_helm_env_value(text, "CCC_PAYLOAD_MODE", "NONE")

    assert _value_of(result, "CCC_PAYLOAD_MODE") == "NONE"
    assert yaml.safe_load(result)["variables"]["own"]["secret"] == {}


def test_autofix_corrects_payload_mode_full_and_partial(tmp_path: Path) -> None:
    """dev/test en FULL y prod en PARTIAL deben quedar los tres en NONE."""
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
        assert _value_of(text, "CCC_PAYLOAD_MODE") == "NONE", env
        assert yaml.safe_load(text) is not None, env
    assert not fix_trace_logger_helm(tmp_path, _violation()).applied  # idempotente


def test_autofix_preserves_the_per_environment_debug_flag(tmp_path: Path) -> None:
    """DEBUG_ENABLED es true solo en dev: el fix no lo uniformiza."""
    _write_env_helm(
        tmp_path,
        {"dev": _mcp_helm_with("NONE", "false"), "prod": _mcp_helm_with("NONE", "true")},
    )

    fix_trace_logger_helm(tmp_path, _violation())

    def debug_of(env: str) -> str:
        text = (tmp_path / "helm" / f"{env}.yml").read_text(encoding="utf-8")
        return _value_of(text, "CCC_CUSTOM_LEVEL_DEBUG_ENABLED")

    assert debug_of("dev") == "true"
    assert debug_of("prod") == "false"


def test_autofix_adds_missing_vars_without_breaking_the_mcp_chart(tmp_path: Path) -> None:
    """El escenario que dejaba los 3 helm con ParserError."""
    _write_env_helm(tmp_path, {env: MCP_HELM for env in ("dev", "test", "prod")})

    assert fix_trace_logger_helm(tmp_path, _violation()).applied

    for env in ("dev", "test", "prod"):
        text = (tmp_path / "helm" / f"{env}.yml").read_text(encoding="utf-8")
        yaml.safe_load(text)  # no debe tirar ParserError
        assert _value_of(text, "CCC_PAYLOAD_MODE") == "NONE", env
        assert _value_of(text, "JAVA_OPTIONS").startswith("-XX:"), env
