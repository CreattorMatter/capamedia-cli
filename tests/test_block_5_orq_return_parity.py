"""Check 5.13 — Paridad de short-circuit en ORQ (ORQ-RETURN-PARITY).

Caso real ORQClientes0022 (PROCEDURE OP21): un downstream cuyo PROCEDURE legacy
solo retorna TRUE es best-effort; migrarlo como rama mandatoria del Mono.zip
rompe productivo (cliente sin asesor -> 500 en vez de 200 con campos vacios).
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import CheckContext, run_block_5


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


def test_5_13_onerror_in_util_helper_not_flagged(tmp_path: Path) -> None:
    """El .onErrorResume best-effort vive en application/util/*Helper.java
    (Service Purity): NO debe dar FAIL HIGH 'estricto' (regresion que H6 detecto)."""
    root = _make_orq(tmp_path, _SVC_MANDATORY)  # ServiceImpl con Mono.zip, sin onErrorResume
    helper = (
        root
        / "src/main/java/com/pichincha/sp/application/util/FooDownstreamHelper.java"
    )
    helper.parent.mkdir(parents=True)
    helper.write_text(_HELPER_WITH_ONERROR, encoding="utf-8")
    legacy = _legacy(tmp_path, _ESQL_ONLY_TRUE)  # best-effort
    check = _find(run_block_5(CheckContext(migrated_path=root, legacy_path=legacy)), "5.13")
    assert check.status == "pass"
