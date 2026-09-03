"""Guard anti-drift entre constantes de version (codigo) y el canonical (texto).

Motivacion: v0.27.2 existio porque la excepcion Netty WebFlux se agrego al
codigo Python (Check 8.7) pero los canonicales seguian diciendo "NUNCA pinear".
El codigo y el canonical son dos fuentes que el agente AI lee como contrato; si
divergen, el orquestador le pide a sus workers algo distinto de lo que exige.

Este test no compara semantica (eso no se puede con strings), pero si verifica
que los VALORES concretos (versiones) que el codigo enforcea aparezcan citados
en los canonicales que los documentan. Atrapa el caso "cambie la version en
version_policy.py pero olvide actualizar el canonical".
"""

from __future__ import annotations

import re
from pathlib import Path

from capamedia_cli.core.version_policy import (
    LIB_TRACE_LOGGER_COORD,
    LIB_TRACE_LOGGER_VERSION,
    NETTY_WEBFLUX_ALLOWED_VERSION,
    PEER_REVIEW_PLUGIN_ID,
    PEER_REVIEW_PLUGIN_VERSION,
    SPRING_BOOT_BASELINE_VERSION,
)

CANON = Path(__file__).resolve().parent.parent / "src" / "capamedia_cli" / "data" / "canonical"


def _read(rel: str) -> str:
    return (CANON / rel).read_text(encoding="utf-8")


def _canonical_files() -> list[str]:
    """Todos los .md del canonical, relativos a CANON."""
    return [str(p.relative_to(CANON)) for p in CANON.rglob("*.md")]


def test_netty_webflux_version_cited_in_canonicals() -> None:
    """El valor permitido en WebFlux debe aparecer literal en los canonicales
    que documentan la excepcion (Regla 8.5, Check 8.7, prompt REST)."""
    targets = [
        "context/bank-official-rules.md",
        "prompts/checklist-rules.md",
        "prompts/migrate-rest-full.md",
    ]
    missing = [t for t in targets if NETTY_WEBFLUX_ALLOWED_VERSION not in _read(t)]
    assert not missing, (
        f"NETTY_WEBFLUX_ALLOWED_VERSION ({NETTY_WEBFLUX_ALLOWED_VERSION}) "
        f"no aparece en: {missing}. Actualizar el canonical al cambiar la constante "
        f"(evita el drift que causo v0.27.2)."
    )


def test_spring_boot_baseline_cited_in_canonicals() -> None:
    """El baseline de Spring Boot debe aparecer en bank-official-rules.md."""
    text = _read("context/bank-official-rules.md")
    assert SPRING_BOOT_BASELINE_VERSION in text, (
        f"SPRING_BOOT_BASELINE_VERSION ({SPRING_BOOT_BASELINE_VERSION}) no aparece "
        "en bank-official-rules.md. Mantener canonical y version_policy en sync."
    )


def test_peer_review_plugin_version_cited_in_canonicals() -> None:
    """La version vigente del plugin de peer review debe aparecer literal en el
    canonical de la regla (9h.4), en el Check 8.12 y en los prompts que el
    agente lee (doublecheck + migracion REST)."""
    targets = [
        "context/bank-official-rules.md",
        "prompts/checklist-rules.md",
        "prompts/doublecheck.md",
        "prompts/migrate-rest-full.md",
    ]
    declaration = f"id '{PEER_REVIEW_PLUGIN_ID}' version '{PEER_REVIEW_PLUGIN_VERSION}'"
    missing = [t for t in targets if declaration not in _read(t)]
    assert not missing, (
        f"La declaracion `{declaration}` no aparece en: {missing}. Actualizar el "
        "canonical al cambiar PEER_REVIEW_PLUGIN_VERSION (mismo drift que v0.27.2)."
    )


def test_old_peer_review_plugin_version_not_declared_as_current() -> None:
    """`1.1.0` (scaffold viejo) solo puede figurar como version a actualizar,
    nunca como la declaracion vigente."""
    stale = f"id '{PEER_REVIEW_PLUGIN_ID}' version '1.1.0'"
    for target in ("prompts/migrate-rest-full.md", "prompts/doublecheck.md"):
        assert stale not in _read(target), (
            f"{target} todavia declara el plugin de peer review en 1.1.0"
        )


def test_no_canonical_promotes_a_different_spring_boot_version() -> None:
    """Ningun canonical puede proponer un `org.springframework.boot version 'X'`
    distinto del baseline.

    Drift real detectado en v0.35.0: `doublecheck.md` pedia `3.5.15` mientras el
    codigo y los prompts de migracion decian `3.5.14`. El agente subia la version
    en el doublecheck contradiciendo lo que acababa de generar la migracion, y
    ningun check lo exigia. El guard de "aparece citado" no lo atrapaba porque
    solo verifica presencia, no exclusividad.
    """
    pattern = re.compile(
        r"org\.springframework\.boot['\"]?\s+version\s+['\"]([0-9][^'\"]*)['\"]"
    )
    offenders: list[str] = []
    for rel in sorted(_canonical_files()):
        for version in set(pattern.findall(_read(rel))):
            if version != SPRING_BOOT_BASELINE_VERSION:
                offenders.append(f"{rel}: {version}")
    assert not offenders, (
        f"Canonicales que proponen una version de Spring Boot distinta del "
        f"baseline ({SPRING_BOOT_BASELINE_VERSION}): {offenders}. Mantener una "
        "sola version en todo el canonical o el agente recibe ordenes en conflicto."
    )


def test_lib_trace_logger_version_cited_in_canonicals() -> None:
    """La coordenada versionada de lib-trace-logger debe aparecer literal en los
    prompts REST y SOAP: el trace-logger es observabilidad por defecto en TODO
    servicio, y ambos prompts declaran la dependencia."""
    coord = f"{LIB_TRACE_LOGGER_COORD}:{LIB_TRACE_LOGGER_VERSION}"
    targets = ["prompts/migrate-rest-full.md", "prompts/migrate-soap-full.md"]
    missing = [t for t in targets if coord not in _read(t)]
    assert not missing, (
        f"La coordenada `{coord}` no aparece en: {missing}. Actualizar el canonical "
        "al cambiar LIB_TRACE_LOGGER_VERSION (mismo drift que causo v0.27.2)."
    )


def test_trace_logger_env_vars_cited_in_checklist_canonical() -> None:
    """Las 7 env vars que enforcean los Checks 7.7/7.8 deben estar documentadas
    en el canonical del checklist. Evita que el codigo exija una env var que el
    agente nunca leyo en el prompt."""
    from capamedia_cli.core.checklist_rules import TRACE_LOGGER_ENV_VARS

    rules = _read("prompts/checklist-rules.md")
    # El canonical abrevia la familia custom-level con barras
    # (`CCC_CUSTOM_LEVEL_ENABLED/INFO/DEBUG/WARN/ERROR_ENABLED`) en vez de
    # listar los 5 nombres completos. Una env var cuenta como documentada si
    # aparece completa o cubierta por esa forma agrupada.
    grouped = "CCC_CUSTOM_LEVEL_ENABLED/INFO/DEBUG/WARN/ERROR_ENABLED"
    missing = [
        var
        for var in TRACE_LOGGER_ENV_VARS
        if var not in rules
        and not (var.startswith("CCC_CUSTOM_LEVEL_") and grouped in rules)
    ]
    assert not missing, (
        f"Env vars del trace-logger sin documentar en checklist-rules.md: "
        f"{missing}. Los Checks 7.7/7.8 las exigen; el prompt debe nombrarlas."
    )


def test_old_netty_version_not_allowed_anywhere() -> None:
    """La version permitida vigente debe figurar en el canonical; las viejas
    (4.1.132/4.1.133) solo pueden aparecer como ejemplo de lo prohibido."""
    rules = _read("context/bank-official-rules.md")
    # La version permitida (constante) si debe estar citada literal.
    assert NETTY_WEBFLUX_ALLOWED_VERSION in rules
    # La version vieja no debe figurar como la permitida (drift de v0.27.2).
    assert "4.1.133.Final" not in rules
