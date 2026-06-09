"""Check 5.13 — Paridad de short-circuit en ORQ (ORQ-RETURN-PARITY).

Caso real ORQClientes0022 (PROCEDURE OP21): un downstream cuyo PROCEDURE legacy
solo retorna TRUE es best-effort; migrarlo como rama mandatoria del Mono.zip
rompe productivo (cliente sin asesor -> 500 en vez de 200 con campos vacios).
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import (
    CheckContext,
    _zip_legs_with_onerror,
    run_block_5,
)


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


# -- Service migrado (Mono.zip; con o sin onErrorResume por rama) ------------

_SVC_MANDATORY = (
    "package com.pichincha.sp.application.service;\n"
    "class FooServiceImpl {\n"
    "    Mono<Result> consultar() {\n"
    "        return Mono.zip(a.consultar(cif), b.consultar(cif)).map(this::build);\n"
    "    }\n"
    "}\n"
)
_SVC_BEST_EFFORT = (
    "package com.pichincha.sp.application.service;\n"
    "class FooServiceImpl {\n"
    "    Mono<Result> consultar() {\n"
    "        return Mono.zip(a.consultar(cif),\n"
    "                b.consultar(cif).onErrorResume(t -> Mono.just(EMPTY)))\n"
    "            .map(this::build);\n"
    "    }\n"
    "}\n"
)

# -- PROCEDURE legacy (con / sin RETURN FALSE) -------------------------------

_ESQL_RETURNS_FALSE = (
    "CREATE PROCEDURE InvocarConsultaA() RETURNS BOOLEAN\n"
    "BEGIN\n"
    "  IF error THEN\n"
    "    RETURN FALSE;\n"
    "  END IF;\n"
    "  RETURN TRUE;\n"
    "END;\n"
)
_ESQL_ONLY_TRUE = (
    "CREATE PROCEDURE InvocarConsultaB() RETURNS BOOLEAN\n"
    "BEGIN\n"
    "  SET salida.campo = valor;\n"
    "  RETURN TRUE;\n"
    "END;\n"
)


def _make_orq(tmp_path: Path, service_body: str, *, orq_name: bool = True) -> Path:
    root = tmp_path / ("orqfoo0001" if orq_name else "wasfoo0001")
    svc = (
        root
        / "src/main/java/com/pichincha/sp/application/service/FooServiceImpl.java"
    )
    svc.parent.mkdir(parents=True)
    svc.write_text(service_body, encoding="utf-8")
    return root


def _legacy(tmp_path: Path, esql_body: str) -> Path:
    legacy = tmp_path / "legacy"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "flow.esql").write_text(esql_body, encoding="utf-8")
    return legacy


def test_5_13_skipped_for_non_orq(tmp_path: Path) -> None:
    root = _make_orq(tmp_path, _SVC_MANDATORY, orq_name=False)
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was")
    assert _find(run_block_5(ctx), "5.13") is None


def test_5_13_pass_when_procedure_returns_false_and_branch_mandatory(tmp_path: Path) -> None:
    root = _make_orq(tmp_path, _SVC_MANDATORY)
    legacy = _legacy(tmp_path, _ESQL_RETURNS_FALSE)
    check = _find(run_block_5(CheckContext(migrated_path=root, legacy_path=legacy)), "5.13")
    assert check is not None
    assert check.status == "pass"


def test_5_13_high_when_procedure_returns_false_but_branch_has_onerror(tmp_path: Path) -> None:
    root = _make_orq(tmp_path, _SVC_BEST_EFFORT)
    legacy = _legacy(tmp_path, _ESQL_RETURNS_FALSE)
    check = _find(run_block_5(CheckContext(migrated_path=root, legacy_path=legacy)), "5.13")
    assert check.status == "fail"
    assert check.severity == "high"
    assert "PERMISIVO" in check.detail


def test_5_13_pass_when_procedure_only_true_and_branch_best_effort(tmp_path: Path) -> None:
    """Caso OP21 corregido: PROCEDURE solo TRUE + rama best-effort -> PASS."""
    root = _make_orq(tmp_path, _SVC_BEST_EFFORT)
    legacy = _legacy(tmp_path, _ESQL_ONLY_TRUE)
    check = _find(run_block_5(CheckContext(migrated_path=root, legacy_path=legacy)), "5.13")
    assert check.status == "pass"


def test_5_13_high_when_procedure_only_true_but_branch_mandatory(tmp_path: Path) -> None:
    """Regresion ORQClientes0022 pre-fix: best-effort migrado como mandatorio -> HIGH."""
    root = _make_orq(tmp_path, _SVC_MANDATORY)
    legacy = _legacy(tmp_path, _ESQL_ONLY_TRUE)
    check = _find(run_block_5(CheckContext(migrated_path=root, legacy_path=legacy)), "5.13")
    assert check.status == "fail"
    assert check.severity == "high"
    assert "ESTRICTO" in check.detail


def test_5_13_low_when_orq_but_no_legacy(tmp_path: Path) -> None:
    root = _make_orq(tmp_path, _SVC_MANDATORY)
    check = _find(run_block_5(CheckContext(migrated_path=root, legacy_path=None)), "5.13")
    assert check.status == "fail"
    assert check.severity == "low"


# -- H4/H6: caso mixto y onErrorResume en helper de util/ -------------------

_SVC_MANDATORY_WITH_ONERROR = (
    "package com.pichincha.sp.application.service;\n"
    "class FooServiceImpl {\n"
    "    Mono<Result> consultar() {\n"
    "        return Mono.zip(a.consultar(cif).onErrorResume(t -> Mono.just(EMPTY)),\n"
    "                b.consultar(cif)).map(this::build);\n"
    "    }\n"
    "}\n"
)
_HELPER_WITH_ONERROR = (
    "package com.pichincha.sp.application.util;\n"
    "class FooDownstreamHelper {\n"
    "    static Mono<X> advisorBestEffort() {\n"
    "        return port.consultar().onErrorResume(t -> Mono.just(EMPTY));\n"
    "    }\n"
    "}\n"
)


def test_5_13_mixed_downstreams_is_low_manual_review(tmp_path: Path) -> None:
    """Caso mixto (mandatory + best-effort): el check agregado no distingue rama
    -> LOW revision manual, NO PASS silencioso (regresion que H4 detecto)."""
    root = _make_orq(tmp_path, _SVC_MANDATORY_WITH_ONERROR)
    legacy = _legacy(tmp_path, _ESQL_RETURNS_FALSE + "\n" + _ESQL_ONLY_TRUE)
    check = _find(run_block_5(CheckContext(migrated_path=root, legacy_path=legacy)), "5.13")
    assert check.status == "fail"
    assert check.severity == "low"
    assert "mixtos" in check.detail


def test_5_13_onerror_in_util_helper_is_low_not_high(tmp_path: Path) -> None:
    """best-effort con .onError* SOLO en un helper (no inline en la rama del zip):
    NO debe dar FAIL HIGH (H6); sin resolucion leg->helper queda LOW (revision
    manual, M1: no enmascarar con un onError que podria ser de otra operacion)."""
    root = _make_orq(tmp_path, _SVC_MANDATORY)  # Mono.zip sin onError inline
    helper = (
        root
        / "src/main/java/com/pichincha/sp/application/util/FooDownstreamHelper.java"
    )
    helper.parent.mkdir(parents=True)
    helper.write_text(_HELPER_WITH_ONERROR, encoding="utf-8")
    legacy = _legacy(tmp_path, _ESQL_ONLY_TRUE)  # best-effort
    check = _find(run_block_5(CheckContext(migrated_path=root, legacy_path=legacy)), "5.13")
    assert check.status == "fail"
    assert check.severity == "low"  # no HIGH (H6), no PASS (M1)


# -- A1/A2: gate ORQ por token + override de source_type explicito -----------


def test_5_13_explicit_was_source_overrides_name(tmp_path: Path) -> None:
    """source_type='was' + nombre con substring 'mayorque' -> 5.13 NO se emite."""
    root = tmp_path / "consultamayorquedato0001"
    svc = root / "src/main/java/com/pichincha/sp/application/service/FooServiceImpl.java"
    svc.parent.mkdir(parents=True)
    svc.write_text(_SVC_MANDATORY, encoding="utf-8")
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was")
    assert _find(run_block_5(ctx), "5.13") is None


def test_5_13_embedded_orq_substring_not_orq(tmp_path: Path) -> None:
    """Sin source_type, un 'orq' EMBEBIDO ('mayorque') no activa 5.13 (token-boundary).
    Nota: 'orquideas'/'orquesta' SI matchean (empiezan con orq) — colision aceptada."""
    root = tmp_path / "consultamayorquedato0001"
    svc = root / "src/main/java/com/pichincha/sp/application/service/FooServiceImpl.java"
    svc.parent.mkdir(parents=True)
    svc.write_text(_SVC_MANDATORY, encoding="utf-8")
    assert _find(run_block_5(CheckContext(migrated_path=root, legacy_path=None)), "5.13") is None


# -- A3: Mono.zip en comentario no activa ------------------------------------


def test_5_13_mono_zip_in_comment_not_detected(tmp_path: Path) -> None:
    body = (
        "package com.pichincha.sp.application.service;\n"
        "class FooServiceImpl {\n"
        "    // pendiente: migrar a Mono.zip(...)\n"
        "    Mono<X> consultar() { return port.consultar(); }\n"
        "}\n"
    )
    root = _make_orq(tmp_path, body)
    legacy = _legacy(tmp_path, _ESQL_ONLY_TRUE)
    assert _find(run_block_5(CheckContext(migrated_path=root, legacy_path=legacy)), "5.13") is None


# -- A5: parser de ramas del Mono.zip ----------------------------------------


def test_zip_legs_with_onerror_per_leg() -> None:
    legs = _zip_legs_with_onerror("Mono.zip(a.x(), b.x().onErrorResume(t -> Mono.just(E)))")
    assert legs == [[False, True]]


def test_zip_legs_nested_and_map() -> None:
    assert _zip_legs_with_onerror("Mono.zip(a.x(), b.x()).map(this::build)") == [[False, False]]


def test_zip_legs_dirty_parse_degrades() -> None:
    assert _zip_legs_with_onerror("Mono.zip(a.x(), b.x(") is None  # desbalanceado -> None


def test_zip_legs_ignores_block_comment_and_string() -> None:
    """.onErrorResume / Mono.zip dentro de comentario de bloque o string NO cuenta (H1)."""
    assert _zip_legs_with_onerror(
        "/* old: Mono.zip(x.onErrorResume(e), y) */ Mono.zip(a(), b())"
    ) == [[False, False]]
    assert _zip_legs_with_onerror('Mono.zip(a().name("x.onErrorResume.y"), b())') == [[False, False]]


def test_zip_legs_ignores_zipdelayerror() -> None:
    """Mono.zipDelayError NO es Mono.zip (H1)."""
    assert _zip_legs_with_onerror("Mono.zipDelayError(a.onErrorResume(e), b)") == []


def test_zip_legs_generics_not_split() -> None:
    """Comas en generics `<A,B>` no parten legs (L1)."""
    assert _zip_legs_with_onerror("Mono.zip(this.<Tuple2<A,B>>call(), b())") == [[False, False]]


def test_zip_legs_onerror_family() -> None:
    """onErrorReturn / onErrorComplete cuentan como proteccion best-effort (M3)."""
    assert _zip_legs_with_onerror(
        "Mono.zip(a().onErrorReturn(E), b().onErrorComplete())"
    ) == [[True, True]]


def test_zip_legs_multiple_zips_grouped() -> None:
    """Cada Mono.zip es un grupo separado, no aplanado (M4)."""
    assert _zip_legs_with_onerror(
        "Mono.zip(a(), b().onErrorResume(e)); Mono.zip(c(), d())"
    ) == [[False, True], [False, False]]


# -- A6: conteo por-rama (cross-op intra-file, mixto MEDIUM) ------------------

_SVC_ZIP_PLUS_OTHER_OP_ONERROR = (
    "package com.pichincha.sp.application.service;\n"
    "class FooServiceImpl {\n"
    "    Mono<X> consultar() { return Mono.zip(a.x(), b.x()).map(this::build); }\n"
    "    Mono<Y> otra() { return c.x().onErrorResume(t -> Mono.just(E)); }\n"
    "}\n"
)


def test_5_13_onerror_outside_zip_same_file_not_miscounted(tmp_path: Path) -> None:
    """all-mandatory: el Mono.zip no tiene onError pero OTRA operacion del mismo
    archivo si -> el conteo por-rama no la cuenta -> PASS (antes daria HIGH falso)."""
    root = _make_orq(tmp_path, _SVC_ZIP_PLUS_OTHER_OP_ONERROR)
    legacy = _legacy(tmp_path, _ESQL_RETURNS_FALSE)  # todos mandatory
    check = _find(run_block_5(CheckContext(migrated_path=root, legacy_path=legacy)), "5.13")
    assert check.status == "pass"


def test_5_13_mixed_more_onerror_than_besteffort_is_medium(tmp_path: Path) -> None:
    svc = (
        "package com.pichincha.sp.application.service;\n"
        "class FooServiceImpl {\n"
        "    Mono<X> consultar() {\n"
        "        return Mono.zip(a.x().onErrorResume(t -> Mono.just(E)),\n"
        "                b.x().onErrorResume(t -> Mono.just(E))).map(this::build);\n"
        "    }\n}\n"
    )
    root = _make_orq(tmp_path, svc)
    legacy = _legacy(tmp_path, _ESQL_RETURNS_FALSE + "\n" + _ESQL_ONLY_TRUE)  # 1 mand + 1 best
    check = _find(run_block_5(CheckContext(migrated_path=root, legacy_path=legacy)), "5.13")
    assert check.status == "fail"
    assert check.severity == "medium"


def test_5_13_mixed_no_onerror_is_medium_strict(tmp_path: Path) -> None:
    root = _make_orq(tmp_path, _SVC_MANDATORY)  # Mono.zip sin onError
    legacy = _legacy(tmp_path, _ESQL_RETURNS_FALSE + "\n" + _ESQL_ONLY_TRUE)  # mixto
    check = _find(run_block_5(CheckContext(migrated_path=root, legacy_path=legacy)), "5.13")
    assert check.status == "fail"
    assert check.severity == "medium"
