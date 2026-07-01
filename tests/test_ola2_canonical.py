"""Tests del Punto B: el prompt canonico analisis-orq.md consume el bloque Ola2
como fuente primaria, CON guardrails que impiden re-acoplar el veredicto al catalogo."""

from __future__ import annotations

from pathlib import Path

import capamedia_cli

_ROOT = Path(capamedia_cli.__file__).parent


def _analisis_orq() -> str:
    return (_ROOT / "data" / "canonical" / "prompts" / "analisis-orq.md").read_text(
        encoding="utf-8"
    )


def test_analisis_orq_uses_ola2_as_primary_source() -> None:
    t = _analisis_orq()
    assert "PRIMARY SOURCE" in t
    assert "Downstreams del catalogo Ola2" in t
    assert "MISSING_IN_ARTIFACTS" in t
    assert "EXTRA_NOT_IN_CATALOG" in t


def test_analisis_orq_guardrails_catalog_is_context_not_arbiter() -> None:
    t = _analisis_orq()
    assert "CONTEXT, not arbiter" in t
    assert "RETURN FALSE" in t
    assert "Ola2 catalog boundary" in t


def test_analisis_orq_delegation_map_forbids_catalog_mandatory_column() -> None:
    t = _analisis_orq()
    assert "Do NOT add a mandatory/best-effort column" in t


def test_check_5_13_not_coupled_to_ola2_catalog() -> None:
    """El Check 5.13 (run_block_5) NO importa ola2_catalog: el ESQL legacy sigue
    siendo el arbitro unico del RETURN FALSE (guardrail anti-reacople, leccion v0.28.10)."""
    src = (_ROOT / "core" / "checklist_rules.py").read_text(encoding="utf-8")
    assert "ola2_catalog" not in src
