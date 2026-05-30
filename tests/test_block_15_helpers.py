"""Tests para los helpers nuevos del check 15.2/15.3 (Etapa 1).

Funciones puras (sin I/O) que detectan y clasifican el argumento de
setter/builder de error.recurso / error.componente. Base de las Etapas 2-4
que resuelven constantes e integran al run_block_15.

Casos derivados de la auditoria empirica sobre 4 servicios reales del banco:
  0077 (LITERAL), 0013 (CONST_CLASS en setter), 0010 (CONST_LOCAL en builder
  ingles), 0022 (CONST_CLASS en builder espanol).
"""

from __future__ import annotations

import pytest

from capamedia_cli.core.checklist_rules import _classify_arg, _extract_call_arg


# ---------------------------------------------------------------------------
# _extract_call_arg
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,expected",
    [
        # Patron 0077 — setter clasico, LITERAL
        ('error.setRecurso("tnd-msa-sp-wsclientes0077/Op");', '"tnd-msa-sp-wsclientes0077/Op"'),
        ('error.setComponente("tnd-msa-sp-wsclientes0077");', '"tnd-msa-sp-wsclientes0077"'),
        # Patron 0013 — setter clasico, CONST_CLASS
        ('error.setRecurso(CatalogExceptionConstants.WS_RECURSO);', 'CatalogExceptionConstants.WS_RECURSO'),
        ('error.setComponente(CatalogExceptionConstants.WS_COMPONENTE);', 'CatalogExceptionConstants.WS_COMPONENTE'),
        # Patron 0010 — builder ingles, CONST_LOCAL
        ('.resource(RESOURCE)', 'RESOURCE'),
        ('.component(COMPONENT)', 'COMPONENT'),
        # Patron 0010 — builder ingles encadenado en una linea
        ('ServiceError.builder().resource(RESOURCE).component(COMPONENT).build()', 'RESOURCE'),
        # Patron 0022 — builder espanol, CONST_CLASS
        ('.recurso(ErrorCatalogConstants.RESOURCE_NAME)', 'ErrorCatalogConstants.RESOURCE_NAME'),
        ('.componente(ErrorCatalogConstants.COMPONENT_NAME)', 'ErrorCatalogConstants.COMPONENT_NAME'),
        # Expresion como argumento — captura crudo, despues clasifica como EXPRESSION
        ('soapError.setRecurso(error.resource());', 'error.resource()'),
        ('errorDto.componente(globalError.getComponent())', 'globalError.getComponent()'),
        # Lineas que NO deben matchear
        ('// no es un setter, solo comentario', None),
        ('private static final String RESOURCE = "WSClientes0010/op";', None),
        ('private GenericError build(String codigo, String mensaje) {', None),
        # .resource( en un contexto distinto (RestTemplate u otro) — matchea por nombre,
        # la heuristica de pre-scan (Etapa 4) descarta archivos sin ServiceError/GenericError.
        ('webClient.get().uri("/api/x").resource(template);', 'template'),
    ],
)
def test_extract_call_arg(line: str, expected: str | None) -> None:
    assert _extract_call_arg(line) == expected


# ---------------------------------------------------------------------------
# _classify_arg
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arg,expected",
    [
        # LITERAL — comillas dobles
        ('"tnd-msa-sp-wsclientes0077/Op"', ("LITERAL", "tnd-msa-sp-wsclientes0077/Op")),
        ('"WSClientes0011"', ("LITERAL", "WSClientes0011")),
        ('""', ("LITERAL", "")),
        # LITERAL — comillas simples (raro en Java pero valido por regex)
        ("'literal'", ("LITERAL", "literal")),
        # CONST_CLASS — Class.CONST con underscores
        ("CatalogExceptionConstants.WS_RECURSO", ("CONST_CLASS", "CatalogExceptionConstants.WS_RECURSO")),
        ("ErrorCatalogConstants.RESOURCE_NAME", ("CONST_CLASS", "ErrorCatalogConstants.RESOURCE_NAME")),
        ("Catalog.X_Y", ("CONST_CLASS", "Catalog.X_Y")),
        # CONST_LOCAL — TODO_MAYUSCULAS con underscore opcional, min 2 chars
        ("RESOURCE", ("CONST_LOCAL", "RESOURCE")),
        ("COMPONENT", ("CONST_LOCAL", "COMPONENT")),
        ("WS_COMPONENTE", ("CONST_LOCAL", "WS_COMPONENTE")),
        # EXPRESSION — variable minuscula, llamada a metodo, concatenacion
        ("recursoVar", ("EXPRESSION", None)),
        ("error.resource()", ("EXPRESSION", None)),
        ('"prefijo/" + operacion', ("EXPRESSION", None)),
        ("globalError.getComponent()", ("EXPRESSION", None)),
        # Edge cases — el clasificador es estricto
        ("camelCase", ("EXPRESSION", None)),                # mixta -> no constante
        ("a", ("EXPRESSION", None)),                          # 1 char -> no entra al regex CONST_LOCAL
    ],
)
def test_classify_arg(arg: str, expected: tuple[str, str | None]) -> None:
    assert _classify_arg(arg) == expected


# ---------------------------------------------------------------------------
# Composicion: extract + classify (smoke test integrado)
# ---------------------------------------------------------------------------


def test_extract_then_classify_for_each_real_pattern() -> None:
    """Verifica los 4 patrones reales end-to-end (sin resolver constantes aun)."""
    samples = [
        # (line, expected_kind, expected_resolved_value_for_literal_only)
        ('error.setRecurso("tnd-msa-sp-wsclientes0077/Op");', "LITERAL", "tnd-msa-sp-wsclientes0077/Op"),
        ('error.setRecurso(CatalogExceptionConstants.WS_RECURSO);', "CONST_CLASS", None),
        ('.resource(RESOURCE)', "CONST_LOCAL", None),
        ('.recurso(ErrorCatalogConstants.RESOURCE_NAME)', "CONST_CLASS", None),
    ]
    for line, expected_kind, expected_value in samples:
        arg = _extract_call_arg(line)
        assert arg is not None, f"falla extract en: {line}"
        kind, value = _classify_arg(arg)
        assert kind == expected_kind, f"kind incorrecto para: {line}"
        if expected_kind == "LITERAL":
            assert value == expected_value
        else:
            assert value is not None  # las no-LITERAL devuelven el identificador crudo para resolver despues
