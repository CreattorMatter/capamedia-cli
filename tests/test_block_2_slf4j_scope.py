"""Tests del nuevo guard del check 2.5 (org.slf4j) por source_type.

Antes (universal): cualquier `import org.slf4j.` -> HIGH.
Despues (Lote D Etapa C): severidad depende del patron empirico:
  - BUS + has_bancs=True  -> HIGH  (BANCS corporativo exige @BpLogger)
  - WAS                   -> MEDIUM (8/8 WAS reales usan @Slf4j)
  - ORQ                   -> MEDIUM (mezcla 10/12)
  - BUS sin has_bancs     -> MEDIUM (batch viejo `lote-20260421`)
  - source_type=unknown   -> HIGH conservador (fallback)
  - sin slf4j             -> PASS

Justificacion empirica: ver pattern-scope.md (auditoria 38 servicios reales).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capamedia_cli.core.checklist_rules import CheckContext, run_block_2


def _make_project_with_slf4j(tmp_path: Path) -> Path:
    """Proyecto minimo con un service que importa org.slf4j (caso violacion)."""
    root = tmp_path / "svc"
    src = root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "application" / "service"
    src.mkdir(parents=True)
    (src / "MyService.java").write_text(
        'package com.pichincha.sp.application.service;\n'
        '\n'
        'import org.slf4j.Logger;\n'
        'import org.slf4j.LoggerFactory;\n'
        '\n'
        'public class MyService {\n'
        '    private static final Logger log = LoggerFactory.getLogger(MyService.class);\n'
        '    public void m() { log.info("hi"); }\n'
        '}\n',
        encoding="utf-8",
    )
    return root


def _find_check_25(results):
    return next((r for r in results if r.id == "2.5"), None)


# ---------------------------------------------------------------------------
# Sin slf4j -> pass (sin cambios respecto al comportamiento previo)
# ---------------------------------------------------------------------------


def test_check_25_pass_when_no_slf4j(tmp_path: Path) -> None:
    root = tmp_path / "svc"
    src = root / "src" / "main" / "java"
    src.mkdir(parents=True)
    (src / "MyService.java").write_text(
        'public class MyService { public void m() { } }\n',
        encoding="utf-8",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was")
    r = _find_check_25(run_block_2(ctx))
    assert r is not None
    assert r.status == "pass"


# ---------------------------------------------------------------------------
# BUS + invocaBancs=true -> HIGH (estricto corporativo)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source_type", ["bus", "iib"])
def test_check_25_high_for_bus_with_bancs(tmp_path: Path, source_type: str) -> None:
    root = _make_project_with_slf4j(tmp_path)
    ctx = CheckContext(migrated_path=root, legacy_path=None,
                       source_type=source_type, has_bancs=True)
    r = _find_check_25(run_block_2(ctx))
    assert r.status == "fail"
    assert r.severity == "high"
    assert "BUS+BANCS" in r.suggested_fix or "BANCS" in r.suggested_fix


# ---------------------------------------------------------------------------
# WAS -> MEDIUM (8/8 WAS reales usan @Slf4j)
# ---------------------------------------------------------------------------


def test_check_25_medium_for_was(tmp_path: Path) -> None:
    root = _make_project_with_slf4j(tmp_path)
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was")
    r = _find_check_25(run_block_2(ctx))
    assert r.status == "fail"
    assert r.severity == "medium"
    assert "@Slf4j" in r.suggested_fix
    assert "pattern-scope.md" in r.suggested_fix


# ---------------------------------------------------------------------------
# ORQ -> MEDIUM (mezcla observada)
# ---------------------------------------------------------------------------


def test_check_25_medium_for_orq(tmp_path: Path) -> None:
    root = _make_project_with_slf4j(tmp_path)
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="orq")
    r = _find_check_25(run_block_2(ctx))
    assert r.status == "fail"
    assert r.severity == "medium"


# ---------------------------------------------------------------------------
# BUS sin BANCS -> MEDIUM (batch viejo)
# ---------------------------------------------------------------------------


def test_check_25_medium_for_bus_without_bancs(tmp_path: Path) -> None:
    root = _make_project_with_slf4j(tmp_path)
    ctx = CheckContext(migrated_path=root, legacy_path=None,
                       source_type="bus", has_bancs=False)
    r = _find_check_25(run_block_2(ctx))
    assert r.status == "fail"
    assert r.severity == "medium"


# ---------------------------------------------------------------------------
# source_type unknown -> HIGH (fallback conservador, comportamiento previo)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source_type", ["", "unknown"])
def test_check_25_high_for_unknown_source(tmp_path: Path, source_type: str) -> None:
    root = _make_project_with_slf4j(tmp_path)
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type=source_type)
    r = _find_check_25(run_block_2(ctx))
    assert r.status == "fail"
    assert r.severity == "high"  # conservador cuando no hay info de patron


# ---------------------------------------------------------------------------
# Smoke E2E: contra 0010 real (WAS) debe ser MEDIUM, no HIGH
# ---------------------------------------------------------------------------


def test_check_25_real_was_0010_documents_actual_behavior() -> None:
    """Smoke E2E sobre WSClientes0010 real (WAS) — documenta el GAP REAL.

    HALLAZGO de la sesion Lote D: el check 2.5 actual solo detecta
    'import org.slf4j.' (regex original). PERO los WAS reales usan @Slf4j
    de lombok (que importa 'lombok.extern.slf4j.Slf4j', NO 'org.slf4j.').
    Por eso 0010 pasa el check con status=pass, sin necesidad del guard.

    Esto significa que la prohibicion '@Slf4j prohibido' del canonical
    historico NUNCA se aplico de facto en WAS — el gap esta en la
    implementacion del check, no en el scope. El guard que agregamos en la
    Etapa C SIGUE VALIENDO para casos donde alguien usa `import org.slf4j`
    directo (sin lombok), pero la cobertura real de '@Slf4j lombok' es 0.

    Documentado en pattern-scope.md como 'gap conocido'. Si en el futuro se
    decide ampliar el check para detectar @Slf4j lombok, este test debe
    actualizarse a assert severity=='medium' (porque source_type='was').
    """
    real = Path("/Users/juliocesarsoriadiaz/Documentos/SmartSolutions/Banco Pichincha/Capa Media/lote-20260421/WSClientes0010/destino/tnd-msa-sp-wsclientes0010")
    if not real.is_dir():
        pytest.skip("0010 real no disponible (CI o no clonado)")
    ctx = CheckContext(migrated_path=real, legacy_path=None, source_type="was")
    r = _find_check_25(run_block_2(ctx))
    # GAP CONOCIDO: 0010 usa @Slf4j lombok (import lombok.extern.slf4j.Slf4j)
    # que NO matchea el regex actual del check (r"import org\.slf4j\."). El
    # check da PASS — no detecta nada que prohibir.
    assert r is not None
    assert r.status == "pass", (
        f"Si el check ahora detecta @Slf4j lombok, este test debe actualizarse "
        f"a esperar fail/medium. Detalle: {r.detail}"
    )
