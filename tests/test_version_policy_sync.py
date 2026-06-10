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

from pathlib import Path

from capamedia_cli.core.version_policy import (
    NETTY_WEBFLUX_ALLOWED_VERSION,
    SPRING_BOOT_BASELINE_VERSION,
)

CANON = Path(__file__).resolve().parent.parent / "src" / "capamedia_cli" / "data" / "canonical"


def _read(rel: str) -> str:
    return (CANON / rel).read_text(encoding="utf-8")


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


def test_old_netty_version_not_allowed_anywhere() -> None:
    """La version permitida vigente debe figurar en el canonical; las viejas
    (4.1.132/4.1.133) solo pueden aparecer como ejemplo de lo prohibido."""
    rules = _read("context/bank-official-rules.md")
    # La version permitida (constante) si debe estar citada literal.
    assert NETTY_WEBFLUX_ALLOWED_VERSION in rules
    # La version vieja no debe figurar como la permitida (drift de v0.27.2).
    assert "4.1.133.Final" not in rules
