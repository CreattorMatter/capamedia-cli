"""Consistencia entre los Checks ejecutables (codigo) y el canonical (texto).

Contexto de orquestador: el canonical (`prompts/checklist-rules.md`) es el
CONTRATO que el orquestador pasa a sus workers AI; los Checks de
`core/checklist_rules.py` son los GATES que aplica al recibir. Si divergen, el
orquestador pide algo distinto de lo que exige (fue el origen de v0.27.2).

Este test NO pretende paridad perfecta hoy (existe drift heredado real: 16
checks sin doc, 27 reglas sin check). Lo que hace es CONGELAR ese estado en un
baseline documentado y fallar ante una discrepancia NUEVA — convirtiendo el
drift en deuda explicita y obligando a decidir conscientemente cada cambio.

Normaliza sub-checks al ID raiz: `0.2a`/`0.2b` -> `0.2`, `5.7b` -> `5.7`. Un
sub-check no necesita doc propia si su familia esta documentada.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src" / "capamedia_cli"
CODE = ROOT / "core" / "checklist_rules.py"
CANON = ROOT / "data" / "canonical" / "prompts" / "checklist-rules.md"

# Primer string tras CheckResult( (cruza lineas con DOTALL via \s).
_CODE_ID_RE = re.compile(r'CheckResult\(\s*"([0-9]+[a-z]?\.[0-9]+[a-z]?)"')
# "Check X.Y:" / "Check X.Yz." en el canonical.
_CANON_ID_RE = re.compile(r"Check\s+([0-9]+[a-z]?\.[0-9]+[a-z]?)\s*[:.]")


def _root(check_id: str) -> str:
    """ID raiz: quita sufijo alfabetico del ultimo segmento (0.2a -> 0.2)."""
    major, _, minor = check_id.partition(".")
    minor_num = re.match(r"\d+", minor)
    return f"{major}.{minor_num.group()}" if minor_num else check_id


def _code_roots() -> set[str]:
    return {_root(i) for i in _CODE_ID_RE.findall(CODE.read_text(encoding="utf-8"))}


def _canon_roots() -> set[str]:
    return {_root(i) for i in _CANON_ID_RE.findall(CANON.read_text(encoding="utf-8"))}


# ── BASELINE 1: checks ejecutables cuya familia NO esta documentada ──────────
# Deuda: documentar estos bloques en checklist-rules.md. Si agregas un check
# nuevo en codigo, documentalo (o sumalo aca con justificacion).
CODE_WITHOUT_DOC_BASELINE = {
    "7.6",    # check ejecutable sin entrada textual en el canonical
    "13.4",   # Block 13 (persistence) sub-checks no documentados individualmente
    "13.5",
    "13.11",
    "19.0",   # numeracion: codigo usa 19.0, canonical documenta 19.1 (unificar)
    "22.0",   # Block 22 (discovery) sub-checks
    "22.2",
}

# ── BASELINE 2: reglas documentadas SIN check ejecutable ─────────────────────
# Dos naturalezas mezcladas:
#  (a) SOLO-DOC legitimo: guias semanticas para el agente AI que no se pueden
#      verificar deterministamente (naming, business logic). Permanentes.
#  (b) GAP DE ENFORCEMENT: reglas "FAIL HIGH" que merecerian check. Candidatas
#      a implementar (ver hallazgos del review: Block 4, codigos fuera catalogo).
DOC_WITHOUT_CHECK_BASELINE = {
    # (a) solo-doc semantico
    # 2.6 salio del baseline en v0.40.0: ahora tiene check (logs INFO diagnosticos)
    "1.6", "2.2", "2.7", "3.1", "3.2", "3.3", "3.4",
    "5.2", "5.3", "5.4", "5.6", "6.1", "6.2", "6.3", "6.4",
    "8.3", "8.4", "8.5", "8.6",
    # nota: 0.2 y 7.5 NO van aca — tienen check via sub-checks (0.2a-g, 7.5c-f)
    # (b) gap de enforcement conocido — candidatos a check futuro
    "4.1", "4.2", "4.3", "4.4", "4.5",  # Block 4 headerIn (reescrito v0.27.0)
    "14.1",  # Spring Boot Validation starter (drift detectado, sin check)
    "19.1",  # ver 19.0 arriba
}


def test_no_new_undocumented_checks() -> None:
    """Todo check ejecutable nuevo debe documentarse en el canonical."""
    undocumented = _code_roots() - _canon_roots() - CODE_WITHOUT_DOC_BASELINE
    assert not undocumented, (
        "Checks ejecutables NUEVOS sin documentar en checklist-rules.md: "
        f"{sorted(undocumented)}. Documentalos en el canonical o agregalos al "
        "baseline CODE_WITHOUT_DOC_BASELINE con justificacion."
    )


def test_no_new_unenforced_rules() -> None:
    """Toda regla documentada nueva debe tener check o declararse solo-doc."""
    unenforced = _canon_roots() - _code_roots() - DOC_WITHOUT_CHECK_BASELINE
    assert not unenforced, (
        "Reglas documentadas NUEVAS sin check ejecutable: "
        f"{sorted(unenforced)}. Implementa el check en checklist_rules.py o "
        "agregalas a DOC_WITHOUT_CHECK_BASELINE (categoria solo-doc o gap conocido)."
    )


def test_baselines_do_not_rot() -> None:
    """Si un baseline-item ya se resolvio (aparece en ambos lados), sacarlo del
    allowlist para que el guard siga siendo estricto."""
    code, canon = _code_roots(), _canon_roots()
    stale_a = {i for i in CODE_WITHOUT_DOC_BASELINE if i in canon}
    stale_b = {i for i in DOC_WITHOUT_CHECK_BASELINE if i in code}
    assert not stale_a, f"CODE_WITHOUT_DOC_BASELINE tiene items ya documentados: {sorted(stale_a)}"
    assert not stale_b, f"DOC_WITHOUT_CHECK_BASELINE tiene items ya con check: {sorted(stale_b)}"
