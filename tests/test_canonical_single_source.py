"""Phase 4 anti-duplication guards — enforce single-source-of-truth canonicals.

Background: v0.23.14 a v0.23.15 unificó la matriz MCP y el umbral de coverage
en canonicals únicos (`bank-mcp-matrix.md`, `bank-checklist-desarrollo.md`).
Antes vivían duplicados en 5-7 archivos distintos, lo que causó el bug de
`wstecnicos0006` (migrado como REST+WebFlux en vez de SOAP+MVC porque un
changelog histórico de `checklist-rules.md` contenía la frase ambigua
"1 op → REST + WebFlux").

These tests prevent regressions by scanning canonicals for content that
should ONLY live in one source file.

Run with: pytest tests/test_canonical_single_source.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

CANONICAL_ROOT = Path(__file__).resolve().parent.parent / "src" / "capamedia_cli" / "data" / "canonical"


def _iter_md_files() -> list[Path]:
    return sorted(p for p in CANONICAL_ROOT.rglob("*.md") if p.is_file())


# ---------------------------------------------------------------------------
# Guard 1: la matriz MCP vive SOLO en bank-mcp-matrix.md
# ---------------------------------------------------------------------------

# Sentinela = las 2 reglas clave de la matriz aparecen juntas en un archivo
# distinto a bank-mcp-matrix.md. Esto indica que el archivo está REPLICANDO
# la matriz en vez de REFERENCIARLA.
MATRIX_SENTINELS = ("invocaBancs: true", "deploymentType: orquestador")
MATRIX_SOURCE = CANONICAL_ROOT / "context" / "bank-mcp-matrix.md"

# Archivos permitidos a mencionar ambos sentinels porque los REFERENCIAN,
# no los duplican. Se verifica manualmente que solo aparezcan en tablas
# pequeñas de resumen (≤ 6 líneas). La fuente única es bank-mcp-matrix.md.
MATRIX_REFERENCES_ALLOWED = {
    "bank-mcp-matrix.md",  # la fuente única
    "bank-official-rules.md",  # Regla 2 - referencia compacta (≤ 10 líneas)
    "checklist-rules.md",  # Check 0.2 - tabla resumida + lista de reglas
    "migrate-rest-full.md",  # header - referencia al canonical
    "migrate-soap-full.md",  # header - referencia al canonical
    "analisis-servicio.md",  # Step H + triage - referencia al canonical
}


def _references_matrix_canonical(content: str) -> bool:
    """Archivo legítimamente referencia bank-mcp-matrix.md."""
    return "bank-mcp-matrix.md" in content


def test_matrix_mcp_lives_only_in_canonical() -> None:
    """La matriz MCP no debe estar duplicada fuera de `bank-mcp-matrix.md`.

    Criterio: si un archivo menciona AMBOS sentinels (`invocaBancs: true` y
    `deploymentType: orquestador`), DEBE estar en la allow-list (y en ese
    caso se exige que también referencie a `bank-mcp-matrix.md`).
    """
    violators: list[str] = []

    for md in _iter_md_files():
        if md == MATRIX_SOURCE:
            continue

        content = md.read_text(encoding="utf-8")
        has_both_sentinels = all(s in content for s in MATRIX_SENTINELS)
        if not has_both_sentinels:
            continue

        # Contiene ambas reglas juntas → debe estar en allow-list
        if md.name not in MATRIX_REFERENCES_ALLOWED:
            violators.append(
                f"{md.relative_to(CANONICAL_ROOT)} duplica la matriz MCP — "
                f"reemplazar por referencia a bank-mcp-matrix.md"
            )
            continue

        # Está en allow-list → verificar que al menos referencie el canonical
        if not _references_matrix_canonical(content):
            violators.append(
                f"{md.relative_to(CANONICAL_ROOT)} menciona la matriz pero NO "
                f"referencia bank-mcp-matrix.md — agregar link explícito"
            )

    assert not violators, (
        "Matriz MCP duplicada en canonicals (deben referenciar, no copiar):\n  "
        + "\n  ".join(violators)
    )


def test_matrix_source_exists() -> None:
    """La fuente única de la matriz MCP debe existir."""
    assert MATRIX_SOURCE.exists(), f"Falta el canonical fuente: {MATRIX_SOURCE}"


# ---------------------------------------------------------------------------
# Guard 2: umbral de coverage = 75% en todos los canonicals
# ---------------------------------------------------------------------------

COVERAGE_FORBIDDEN_VALUE = "85%"
COVERAGE_SOURCE = CANONICAL_ROOT / "context" / "bank-checklist-desarrollo.md"

# Archivos donde 85% puede aparecer sólo en contextos no-coverage (ej. un
# número en un ejemplo que coincide). Si en el futuro se agrega un uso
# legítimo de "85%" fuera de coverage, agregarlo acá con justificación.
COVERAGE_85_ALLOWED_CONTEXTS: set[str] = set()


def _line_mentions_coverage(line: str) -> bool:
    """True si la línea habla de coverage/JaCoCo/test coverage."""
    lower = line.lower()
    return any(
        kw in lower
        for kw in ("coverage", "jacoco", "line coverage", "branch coverage", "method coverage")
    )


def test_coverage_threshold_is_75_percent() -> None:
    """Todos los canonicals usan 75% como umbral de coverage (alineado con PDF).

    Fuente oficial: `BPTPSRE-CheckList Desarrollo` dice **75%**.
    Canonical único: `bank-checklist-desarrollo.md`.
    """
    violators: list[str] = []

    for md in _iter_md_files():
        content = md.read_text(encoding="utf-8")
        if COVERAGE_FORBIDDEN_VALUE not in content:
            continue

        for lineno, line in enumerate(content.splitlines(), start=1):
            if COVERAGE_FORBIDDEN_VALUE not in line:
                continue
            if not _line_mentions_coverage(line):
                continue
            if md.name in COVERAGE_85_ALLOWED_CONTEXTS:
                continue
            violators.append(
                f"{md.relative_to(CANONICAL_ROOT)}:{lineno} usa 85% de coverage "
                f"(debe ser 75% — ver bank-checklist-desarrollo.md)"
            )

    assert not violators, (
        "Conflicto de threshold de coverage (PDF oficial = 75%):\n  "
        + "\n  ".join(violators)
    )


def test_checklist_desarrollo_source_exists() -> None:
    """La fuente única del checklist oficial debe existir."""
    assert COVERAGE_SOURCE.exists(), f"Falta el canonical fuente: {COVERAGE_SOURCE}"


# ---------------------------------------------------------------------------
# Guard 3: la frase ambigua "1 op → REST + WebFlux" NUNCA debe reaparecer
# ---------------------------------------------------------------------------

# Esta frase causó el bug de wstecnicos0006 (2026-04-18 → 2026-04-23). La
# ambigüedad estaba en no calificar "1 op" con la tecnología — WAS 1 op va
# MVC, no WebFlux. Se prohíbe explícitamente porque nunca es correcta
# standalone: la decisión depende de 5 parámetros, no sólo de op count.
AMBIGUOUS_PHRASES = [
    # Literal que estaba en la línea 1734 del changelog
    "1 op → REST + WebFlux",
    "1 op -> REST + WebFlux",
    "1 op → REST+WebFlux",
    "1 op -> REST+WebFlux",
]


def test_ambiguous_matrix_phrase_removed() -> None:
    """La frase ambigua que causó el bug wstecnicos0006 no debe reaparecer.

    Contexto: la frase "1 op → REST + WebFlux" sin calificar tecnología es
    incorrecta para WAS (WAS 1 op va REST+MVC, no WebFlux). Fue la root cause
    del bug wstecnicos0006 (2026-04-23). La matriz correcta está en
    `bank-mcp-matrix.md` — usar esa referencia siempre.
    """
    offenders: list[str] = []

    for md in _iter_md_files():
        content = md.read_text(encoding="utf-8")
        for phrase in AMBIGUOUS_PHRASES:
            if phrase not in content:
                continue
            for lineno, line in enumerate(content.splitlines(), start=1):
                if phrase in line:
                    offenders.append(
                        f"{md.relative_to(CANONICAL_ROOT)}:{lineno} contiene "
                        f"frase prohibida {phrase!r} — root cause del bug "
                        f"wstecnicos0006. Reemplazar por referencia a "
                        f"bank-mcp-matrix.md."
                    )

    assert not offenders, (
        "Frase ambigua detectada (causó bug wstecnicos0006):\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Guard 4: los 3 canonicals nuevos de v0.23.15 existen
# ---------------------------------------------------------------------------

NEW_CANONICALS_V0_23_15 = [
    "context/bank-error-structure.md",
    "context/bank-configurables.md",
    "context/bank-checklist-desarrollo.md",
]


@pytest.mark.parametrize("rel_path", NEW_CANONICALS_V0_23_15)
def test_new_canonicals_v0_23_15_exist(rel_path: str) -> None:
    """Los 3 canonicals agregados en v0.23.15 deben existir y no estar vacíos."""
    path = CANONICAL_ROOT / rel_path
    assert path.exists(), f"Canonical faltante: {rel_path}"
    content = path.read_text(encoding="utf-8")
    assert len(content) > 500, f"Canonical demasiado corto (<500 chars): {rel_path}"
    assert content.startswith("---\n"), (
        f"Canonical sin frontmatter YAML: {rel_path}"
    )
