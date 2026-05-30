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

from pathlib import Path

from capamedia_cli.core.checklist_rules import (
    FieldUsage,
    _classify_arg,
    _extract_call_arg,
    _file_has_error_context,
    _find_field_usages,
    _resolve_const,
)


# Helper para escribir un .java en tmp y devolver su Path
def _write_java(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


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


# ---------------------------------------------------------------------------
# _resolve_const (Etapa 2) — resuelve CONST_LOCAL y CONST_CLASS con I/O
# ---------------------------------------------------------------------------


def test_resolve_const_literal_returns_none(tmp_path: Path) -> None:
    """LITERAL ya viene resuelto desde _classify_arg; _resolve_const no aplica."""
    assert _resolve_const(tmp_path, "LITERAL", '"x"', "") is None


def test_resolve_const_expression_returns_none(tmp_path: Path) -> None:
    """EXPRESSION nunca se puede resolver por regex."""
    assert _resolve_const(tmp_path, "EXPRESSION", "", "") is None


def test_resolve_const_local_found_in_current_file(tmp_path: Path) -> None:
    """Patron 0010: RESOURCE definida en el mismo archivo del service."""
    content = (
        'package com.pichincha.sp.application.service;\n'
        '\n'
        'public class QueryGroupDigitalKeyServiceImpl {\n'
        '    private static final String RESOURCE = "tnd-msa-sp-wsclientes0010/consultarGrupoClaveDigital01";\n'
        '    // ... resto\n'
        '}\n'
    )
    assert _resolve_const(tmp_path, "CONST_LOCAL", "RESOURCE", content) == \
        "tnd-msa-sp-wsclientes0010/consultarGrupoClaveDigital01"


def test_resolve_const_local_not_found(tmp_path: Path) -> None:
    """CONST_LOCAL referenciada pero sin definicion -> None (MEDIUM despues)."""
    assert _resolve_const(tmp_path, "CONST_LOCAL", "MISSING", "// nothing here\n") is None


def test_resolve_const_class_found_in_utility(tmp_path: Path) -> None:
    """Patron 0013: setRecurso(Catalog.WS_RECURSO) — la clase Catalog vive en otro archivo."""
    catalog = tmp_path / "infrastructure" / "exception" / "CatalogExceptionConstants.java"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        'package com.pichincha.sp.infrastructure.exception;\n'
        '\n'
        'public class CatalogExceptionConstants {\n'
        '    public static final String WS_RECURSO =\n'
        '        "tnd-msa-sp-wsclientes0013/ConsultarDatosLocalizacionCliente01";\n'
        '    public static final String WS_COMPONENTE = "tnd-msa-sp-wsclientes0013";\n'
        '}\n',
        encoding="utf-8",
    )
    assert _resolve_const(tmp_path, "CONST_CLASS", "CatalogExceptionConstants.WS_RECURSO", "") == \
        "tnd-msa-sp-wsclientes0013/ConsultarDatosLocalizacionCliente01"
    assert _resolve_const(tmp_path, "CONST_CLASS", "CatalogExceptionConstants.WS_COMPONENTE", "") == \
        "tnd-msa-sp-wsclientes0013"


def test_resolve_const_class_missing_class(tmp_path: Path) -> None:
    """Constante referenciada sobre clase inexistente -> None."""
    assert _resolve_const(tmp_path, "CONST_CLASS", "GhostConstants.X", "") is None


def test_resolve_const_class_missing_constant(tmp_path: Path) -> None:
    """Clase existe pero la constante no -> None."""
    (tmp_path / "Cat.java").write_text(
        'public class Cat { public static final String OTHER = "x"; }\n',
        encoding="utf-8",
    )
    assert _resolve_const(tmp_path, "CONST_CLASS", "Cat.MISSING", "") is None


def test_resolve_const_uses_cache(tmp_path: Path) -> None:
    """El cache evita re-leer el mismo archivo."""
    f = tmp_path / "Cat.java"
    f.write_text('public static final String A = "valA";\n', encoding="utf-8")
    cache: dict[Path, str] = {}
    v1 = _resolve_const(tmp_path, "CONST_CLASS", "Cat.A", "", file_cache=cache)
    assert v1 == "valA"
    assert f in cache  # se cacheo en la 1a llamada
    # Mutar el cache para simular: si se vuelve a leer el archivo, fallaria.
    cache[f] = 'public static final String A = "valB";\n'
    v2 = _resolve_const(tmp_path, "CONST_CLASS", "Cat.A", "", file_cache=cache)
    assert v2 == "valB"  # uso el cache, no reabrio el archivo


# ---------------------------------------------------------------------------
# _find_field_usages (Etapa 3) — integra extract+classify+resolve sobre arbol
# ---------------------------------------------------------------------------


def test_find_field_usages_invalid_field_raises(tmp_path: Path) -> None:
    import pytest as _pytest  # local
    with _pytest.raises(ValueError):
        _find_field_usages(tmp_path, "otroCampo")


def test_find_field_usages_pre_scan_filters_unrelated_files(tmp_path: Path) -> None:
    """Archivo sin marcadores de bloque error (HttpService con .resource(template)) -> 0 hits."""
    _write_java(tmp_path, "HttpService.java",
        'public class HttpService {\n'
        '    public void call() { webClient.get().uri("/x").resource(template).send(); }\n'
        '}\n')
    assert _find_field_usages(tmp_path, "recurso") == []


def test_find_field_usages_0077_literal(tmp_path: Path) -> None:
    """Patron 0077: setter clasico con literal directo en SoapResponseHelper."""
    _write_java(tmp_path, "SoapResponseHelper.java",
        'public class SoapResponseHelper {\n'
        '    private GenericError build() {\n'
        '        GenericError error = new GenericError();\n'
        '        error.setRecurso("tnd-msa-sp-wsclientes0077/ConsultarDatoBasicoCliente01");\n'
        '        return error;\n'
        '    }\n'
        '}\n')
    hits = _find_field_usages(tmp_path, "recurso")
    assert len(hits) == 1
    assert hits[0].arg_kind == "LITERAL"
    assert hits[0].resolved_value == "tnd-msa-sp-wsclientes0077/ConsultarDatoBasicoCliente01"


def test_find_field_usages_0013_const_class(tmp_path: Path) -> None:
    """Patron 0013: setter clasico con CONST_CLASS + clase utility en otro archivo."""
    _write_java(tmp_path, "infrastructure/exception/CatalogExceptionConstants.java",
        'public class CatalogExceptionConstants {\n'
        '    public static final String WS_RECURSO =\n'
        '        "tnd-msa-sp-wsclientes0013/ConsultarDatosLocalizacionCliente01";\n'
        '}\n')
    _write_java(tmp_path, "infrastructure/soap/mapper/Mapper.java",
        'public class Mapper {\n'
        '    public GenericError map() {\n'
        '        GenericError error = new GenericError();\n'
        '        error.setRecurso(CatalogExceptionConstants.WS_RECURSO);\n'
        '        return error;\n'
        '    }\n'
        '}\n')
    hits = _find_field_usages(tmp_path, "recurso")
    assert len(hits) == 1
    assert hits[0].arg_kind == "CONST_CLASS"
    assert hits[0].resolved_value == "tnd-msa-sp-wsclientes0013/ConsultarDatosLocalizacionCliente01"


def test_find_field_usages_0010_const_local_in_builder(tmp_path: Path) -> None:
    """Patron 0010: builder ingles .resource(RESOURCE) con constante LOCAL en mismo archivo."""
    _write_java(tmp_path, "QueryService.java",
        'public class QueryService {\n'
        '    private static final String RESOURCE = "tnd-msa-sp-wsclientes0010/consultarGrupoClaveDigital01";\n'
        '    public ServiceError build() {\n'
        '        return ServiceError.builder().resource(RESOURCE).build();\n'
        '    }\n'
        '}\n')
    hits = _find_field_usages(tmp_path, "recurso")
    assert len(hits) == 1
    assert hits[0].arg_kind == "CONST_LOCAL"
    assert hits[0].resolved_value == "tnd-msa-sp-wsclientes0010/consultarGrupoClaveDigital01"


def test_find_field_usages_0022_const_class_in_spanish_builder(tmp_path: Path) -> None:
    """Patron 0022: builder espanol .recurso(Const.RESOURCE_NAME) con clase utility."""
    _write_java(tmp_path, "domain/constants/ErrorCatalogConstants.java",
        'public class ErrorCatalogConstants {\n'
        '    public static final String RESOURCE_NAME = "ORQClientes0022/ConsultarInformacionClienteVirtual01";\n'
        '}\n')
    _write_java(tmp_path, "service/Impl.java",
        'public class Impl {\n'
        '    public void m() {\n'
        '        ServiceError.builder().recurso(ErrorCatalogConstants.RESOURCE_NAME).build();\n'
        '    }\n'
        '}\n')
    hits = _find_field_usages(tmp_path, "recurso")
    assert len(hits) == 1
    assert hits[0].arg_kind == "CONST_CLASS"
    # Valor LEGACY a proposito: el subagente F confirmo que 0022 usa nombre legacy.
    assert hits[0].resolved_value == "ORQClientes0022/ConsultarInformacionClienteVirtual01"


def test_find_field_usages_expression_not_resolved(tmp_path: Path) -> None:
    """Argumento que es una llamada a metodo (error.resource()) -> EXPRESSION sin resolver."""
    _write_java(tmp_path, "PassThroughMapper.java",
        'public class PassThroughMapper {\n'
        '    public void map(ServiceError error) {\n'
        '        soapError.setRecurso(error.resource());\n'
        '    }\n'
        '}\n')
    hits = _find_field_usages(tmp_path, "recurso")
    assert len(hits) == 1
    assert hits[0].arg_kind == "EXPRESSION"
    assert hits[0].resolved_value is None


def test_find_field_usages_field_filter_separates_recurso_from_componente(tmp_path: Path) -> None:
    """field='recurso' NO incluye hits de .componente()/.component() y viceversa."""
    _write_java(tmp_path, "Both.java",
        'public class Both {\n'
        '    public void m() {\n'
        '        ServiceError.builder()\n'
        '            .recurso("R")\n'
        '            .componente("C")\n'
        '            .resource("R2")\n'
        '            .component("C2")\n'
        '            .build();\n'
        '    }\n'
        '}\n')
    recurso_hits = _find_field_usages(tmp_path, "recurso")
    comp_hits = _find_field_usages(tmp_path, "componente")
    # .recurso("R") + .resource("R2") = 2; .componente("C") + .component("C2") = 2
    assert {h.resolved_value for h in recurso_hits} == {"R", "R2"}
    assert {h.resolved_value for h in comp_hits} == {"C", "C2"}


def test_find_field_usages_skips_build_and_git(tmp_path: Path) -> None:
    """Archivos bajo build/ o .git/ se ignoran."""
    _write_java(tmp_path, "build/generated/Generated.java",
        'public class Generated { public void m() { error.setRecurso("X"); } }\n')
    _write_java(tmp_path, "Real.java",
        'public class Real { public void m() { error.setRecurso("Y"); } }\n')
    hits = _find_field_usages(tmp_path, "recurso")
    assert [h.resolved_value for h in hits] == ["Y"]


def test_find_field_usages_returns_FieldUsage_dataclass(tmp_path: Path) -> None:
    """Smoke test del tipo devuelto."""
    _write_java(tmp_path, "F.java",
        'public class F { public void m() { error.setRecurso("X"); } }\n')
    hits = _find_field_usages(tmp_path, "recurso")
    assert len(hits) == 1
    assert isinstance(hits[0], FieldUsage)
    assert hits[0].line_no == 1
    assert hits[0].file.name == "F.java"


# ---------------------------------------------------------------------------
# _file_has_error_context (helper del pre-scan)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content,expected",
    [
        ("class X { void m() { GenericError e; } }", True),  # marcador GenericError
        ("class X { ServiceError.builder().build(); }", True),  # marcador ServiceError
        ("class X { error.setRecurso(\"x\"); }", True),  # marcador setRecurso
        ("class HttpService { webClient.uri().resource(template); }", False),  # SIN marcador
        ("// comentario", False),
    ],
)
def test_file_has_error_context(content: str, expected: bool) -> None:
    assert _file_has_error_context(content) is expected


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
