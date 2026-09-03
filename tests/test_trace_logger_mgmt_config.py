"""Check 2.10 y su autofix: `TraceLoggerManagementPathConfig`.

Los extractores del `lib-trace-logger` vuelcan cada request en un
`RequestInformationContextHolder` singleton, asi que las sondas de
liveness/readiness/prometheus pisan el contexto del request de negocio. La clase
lo evita envolviendo el bean con un `BeanPostProcessor`.

El bug que motiva el guard de variante: el prompt listaba la variante reactiva
para "ORQ / BUS + invocaBancs", asi que un BUS WebFlux **sin** BANCS no encajaba
en ninguna fila y el agente omitio la clase (WSSeguridad0069, 2026-09-03). La
variante se decide por el starter de `build.gradle`, nunca por BANCS.
"""

from __future__ import annotations

import re
from pathlib import Path

from capamedia_cli.core.autofix import (
    AUTOFIX_REGISTRY,
    Violation,
    fix_add_trace_logger_management_config,
)
from capamedia_cli.core.canonical import CANONICAL_ROOT
from capamedia_cli.core.checklist_rules import CheckContext, run_block_2
from capamedia_cli.core.java_templates import (
    TRACE_LOGGER_MGMT_CONFIG_CLASS,
    TRACE_LOGGER_MGMT_SERVLET,
    TRACE_LOGGER_MGMT_WEBFLUX,
    trace_logger_mgmt_template,
)

WEBFLUX_GRADLE = "dependencies { implementation 'org.springframework.boot:spring-boot-starter-webflux' }\n"
MVC_GRADLE = "dependencies { implementation 'org.springframework.boot:spring-boot-starter-web' }\n"


def _project(tmp_path: Path, gradle: str) -> Path:
    root = tmp_path / "csg-msa-sp-svc"
    pkg = root / "src" / "main" / "java" / "com" / "pichincha" / "sp"
    pkg.mkdir(parents=True)
    (pkg / "Application.java").write_text(
        "package com.pichincha.sp;\n@SpringBootApplication\npublic class Application {}\n",
        encoding="utf-8",
    )
    (root / "build.gradle").write_text(gradle, encoding="utf-8")
    return root


def _check(root: Path):
    return next(r for r in run_block_2(CheckContext(migrated_path=root, legacy_path=None)) if r.id == "2.10")


def _violation() -> Violation:
    return Violation("2.10", "high", Path("build.gradle"), 1, "", "")


def _config_file(root: Path) -> Path:
    return next(root.rglob(f"{TRACE_LOGGER_MGMT_CONFIG_CLASS}.java"))


# ---------------------------------------------------------------------------
# Check 2.10
# ---------------------------------------------------------------------------


def test_missing_class_is_high_on_webflux_without_bancs(tmp_path: Path) -> None:
    """El caso que se omitia: WebFlux sin BANCS tambien la necesita."""
    root = _project(tmp_path, WEBFLUX_GRADLE)  # sin lib-bnc-api-client

    check = _check(root)

    assert check.status == "fail"
    assert check.severity == "high"
    assert "ReactiveRequestInformationExtractor" in check.detail


def test_missing_class_is_high_on_mvc(tmp_path: Path) -> None:
    check = _check(_project(tmp_path, MVC_GRADLE))
    assert check.status == "fail"
    assert "ServletRequestInformationExtractor" in check.detail


def test_wrong_variant_for_the_stack_fails(tmp_path: Path) -> None:
    root = _project(tmp_path, MVC_GRADLE)
    dest = root / "src/main/java/com/pichincha/sp/infrastructure/config"
    dest.mkdir(parents=True)
    # variante reactiva en un proyecto servlet
    (dest / f"{TRACE_LOGGER_MGMT_CONFIG_CLASS}.java").write_text(
        trace_logger_mgmt_template(True, "com.pichincha.sp"), encoding="utf-8"
    )

    check = _check(root)

    assert check.status == "fail"
    assert "variante equivocada" in check.detail


def test_class_without_bean_post_processor_fails(tmp_path: Path) -> None:
    root = _project(tmp_path, WEBFLUX_GRADLE)
    dest = root / "src/main/java/com/pichincha/sp/infrastructure/config"
    dest.mkdir(parents=True)
    (dest / f"{TRACE_LOGGER_MGMT_CONFIG_CLASS}.java").write_text(
        "package com.pichincha.sp.infrastructure.config;\n"
        "class TraceLoggerManagementPathConfig implements WebFilter {\n"
        "  // instanceof ReactiveRequestInformationExtractor\n}\n",
        encoding="utf-8",
    )

    check = _check(root)

    assert check.status == "fail"
    assert "BeanPostProcessor" in check.detail


def test_class_outside_infrastructure_config_fails(tmp_path: Path) -> None:
    root = _project(tmp_path, WEBFLUX_GRADLE)
    dest = root / "src/main/java/com/pichincha/sp/util"
    dest.mkdir(parents=True)
    (dest / f"{TRACE_LOGGER_MGMT_CONFIG_CLASS}.java").write_text(
        trace_logger_mgmt_template(True, "com.pichincha.sp"), encoding="utf-8"
    )

    assert "infrastructure/config" in _check(root).suggested_fix or "ubicacion" in _check(root).detail


# ---------------------------------------------------------------------------
# Autofix
# ---------------------------------------------------------------------------


def test_autofix_creates_the_reactive_variant_on_webflux(tmp_path: Path) -> None:
    root = _project(tmp_path, WEBFLUX_GRADLE)

    result = fix_add_trace_logger_management_config(root, _violation())

    assert result.applied
    text = _config_file(root).read_text(encoding="utf-8")
    assert text.startswith("package com.pichincha.sp.infrastructure.config;")
    assert "instanceof ReactiveRequestInformationExtractor" in text
    assert "implements BeanPostProcessor, EnvironmentAware" in text
    assert _check(root).status == "pass"


def test_autofix_creates_the_servlet_variant_on_mvc(tmp_path: Path) -> None:
    root = _project(tmp_path, MVC_GRADLE)

    fix_add_trace_logger_management_config(root, _violation())

    text = _config_file(root).read_text(encoding="utf-8")
    assert "instanceof ServletRequestInformationExtractor" in text
    assert "jakarta.servlet.Filter" in text
    assert _check(root).status == "pass"


def test_autofix_is_idempotent_and_never_overwrites(tmp_path: Path) -> None:
    root = _project(tmp_path, WEBFLUX_GRADLE)
    assert fix_add_trace_logger_management_config(root, _violation()).applied

    marker = "// editado a mano\n"
    path = _config_file(root)
    path.write_text(marker + path.read_text(encoding="utf-8"), encoding="utf-8")

    second = fix_add_trace_logger_management_config(root, _violation())

    assert not second.applied
    assert path.read_text(encoding="utf-8").startswith(marker)


def test_autofix_uses_the_project_base_package(tmp_path: Path) -> None:
    root = tmp_path / "svc"
    pkg = root / "src" / "main" / "java" / "ec" / "banco" / "svc"
    pkg.mkdir(parents=True)
    (pkg / "Application.java").write_text(
        "package ec.banco.svc;\n@SpringBootApplication\npublic class Application {}\n", encoding="utf-8"
    )
    (root / "build.gradle").write_text(WEBFLUX_GRADLE, encoding="utf-8")

    fix_add_trace_logger_management_config(root, _violation())

    path = _config_file(root)
    assert path.parts[-4:] == ("svc", "infrastructure", "config", f"{TRACE_LOGGER_MGMT_CONFIG_CLASS}.java")
    assert path.read_text(encoding="utf-8").startswith("package ec.banco.svc.infrastructure.config;")


def test_autofix_registered_for_check_2_10() -> None:
    assert fix_add_trace_logger_management_config in AUTOFIX_REGISTRY["2.10"]


# ---------------------------------------------------------------------------
# Las plantillas no pueden divergir del prompt que lee el agente
# ---------------------------------------------------------------------------


def test_java_templates_match_doublecheck_prompt() -> None:
    """El codigo que genera el autofix y el que lee el agente son el mismo."""
    prompt = (CANONICAL_ROOT / "prompts" / "doublecheck.md").read_text(encoding="utf-8")
    blocks = [b for b in re.findall(r"```java\n(.*?)```", prompt, re.DOTALL) if TRACE_LOGGER_MGMT_CONFIG_CLASS in b]
    assert len(blocks) == 2, "doublecheck.md debe traer las dos variantes"

    rendered = {
        TRACE_LOGGER_MGMT_WEBFLUX.replace("__PKG__", "com.pichincha.sp").strip(),
        TRACE_LOGGER_MGMT_SERVLET.replace("__PKG__", "com.pichincha.sp").strip(),
    }
    assert {b.strip() for b in blocks} == rendered


def test_checklist_canonical_documents_that_bancs_is_irrelevant() -> None:
    rules = (CANONICAL_ROOT / "prompts" / "checklist-rules.md").read_text(encoding="utf-8")
    assert "Check 2.10" in rules
    assert "no depende de si invoca BANCS" in rules

    prompt = (CANONICAL_ROOT / "prompts" / "doublecheck.md").read_text(encoding="utf-8")
    # El titulo que causo la omision no debe volver.
    assert "### Variante WebFlux (ORQ, BUS + invocaBancs)" not in prompt
    assert "spring-boot-starter-webflux" in prompt
