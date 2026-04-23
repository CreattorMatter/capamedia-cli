"""Tests para la matriz MCP-driven del Block 0 (v0.22.0)."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import (
    CheckContext,
    _expected_framework,
    run_block_0,
)


# ---------------------------------------------------------------------------
# Unit tests de _expected_framework (matriz pura)
# ---------------------------------------------------------------------------


def test_bus_with_invoca_bancs_always_rest() -> None:
    """BUS + invocaBancs=true siempre REST (override MCP, ignora ops)."""
    fw, reason = _expected_framework("bus", True, ops_count=1)
    assert fw == "rest"
    assert "invocaBancs" in reason

    fw, reason = _expected_framework("bus", True, ops_count=5)
    assert fw == "rest", "BUS+invocaBancs debe ser REST aun con 5 ops"


def test_bus_without_invoca_bancs_falls_to_ops_count() -> None:
    """BUS sin invocaBancs: comportamiento fallback por conteo."""
    fw, _ = _expected_framework("bus", False, ops_count=1)
    assert fw == "rest"
    fw, _ = _expected_framework("bus", False, ops_count=3)
    assert fw == "soap"


def test_orq_always_rest() -> None:
    """ORQ siempre REST+WebFlux (deploymentType=orquestador)."""
    for ops in (1, 2, 5, 10):
        fw, reason = _expected_framework("orq", has_bancs=False, ops_count=ops)
        assert fw == "rest", f"ORQ con {ops} ops debe ser REST"
        assert "WebFlux" in reason or "orquestador" in reason.lower()


def test_was_one_op_rest() -> None:
    fw, reason = _expected_framework("was", has_bancs=False, ops_count=1)
    assert fw == "rest"
    assert "MVC" in reason


def test_was_multi_op_soap() -> None:
    for ops in (2, 3, 7):
        fw, reason = _expected_framework("was", has_bancs=False, ops_count=ops)
        assert fw == "soap", f"WAS con {ops} ops debe ser SOAP"
        assert "MVC" in reason


def test_was_with_bancs_still_uses_ops_count() -> None:
    """WAS+invocaBancs no es un caso especial — sigue la regla por ops count."""
    fw, _ = _expected_framework("was", has_bancs=True, ops_count=1)
    assert fw == "rest"
    fw, _ = _expected_framework("was", has_bancs=True, ops_count=3)
    assert fw == "soap"


def test_unknown_source_fallback_to_ops_count() -> None:
    """Sin source_type (unknown), fallback a conteo de ops (compat legacy)."""
    fw, reason = _expected_framework("", False, ops_count=1)
    assert fw == "rest"
    assert "fallback" in reason.lower() or "conteo" in reason.lower()

    fw, _ = _expected_framework("unknown", False, ops_count=3)
    assert fw == "soap"


def test_case_insensitive_source_type() -> None:
    """BUS / bus / Bus deben comportarse igual."""
    for variant in ("BUS", "Bus", "bus"):
        fw, _ = _expected_framework(variant, True, ops_count=3)
        assert fw == "rest", f"source_type '{variant}' deberia ser case-insensitive"


# ---------------------------------------------------------------------------
# Integration tests de run_block_0 con context completo
# ---------------------------------------------------------------------------


def _mk_minimal_project(tmp_path: Path, *, has_endpoint: bool, has_controller: bool, ops: int) -> Path:
    """Crea proyecto minimo con WSDL de N ops + @Endpoint o @RestController."""
    project = tmp_path / "proj"
    src_java = project / "src" / "main" / "java" / "com" / "pichincha"
    src_java.mkdir(parents=True)

    if has_endpoint:
        (src_java / "TheEndpoint.java").write_text(
            "package com.pichincha;\n"
            "import org.springframework.ws.server.endpoint.annotation.Endpoint;\n"
            "@Endpoint\npublic class TheEndpoint {}\n",
            encoding="utf-8",
        )
    if has_controller:
        (src_java / "TheController.java").write_text(
            "package com.pichincha;\n"
            "import org.springframework.web.bind.annotation.RestController;\n"
            "@RestController\npublic class TheController {}\n",
            encoding="utf-8",
        )

    # WSDL minimal con N operations
    resources = project / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    ops_xml = "\n".join(
        f'<wsdl:operation name="op{i}"/>' for i in range(ops)
    )
    (resources / "svc.wsdl").write_text(
        f'<?xml version="1.0"?>\n'
        f'<definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" '
        f'targetNamespace="http://x.com">\n'
        f'<wsdl:portType name="X">\n{ops_xml}\n</wsdl:portType>\n'
        f'</definitions>\n',
        encoding="utf-8",
    )
    return project


def _find_0_2c(results) -> object:
    return next(r for r in results if r.id == "0.2c")


def test_run_block_0_bus_with_bancs_rest_ok(tmp_path: Path) -> None:
    """BUS + invocaBancs migrado como REST con N ops → PASS (matriz MCP)."""
    project = _mk_minimal_project(tmp_path, has_endpoint=False, has_controller=True, ops=3)
    ctx = CheckContext(
        migrated_path=project, legacy_path=None,
        source_type="bus", has_bancs=True,
    )
    results = run_block_0(ctx)
    r = _find_0_2c(results)
    assert r.status == "pass", (
        f"BUS+invocaBancs+REST con 3 ops deberia PASS (matriz MCP override). "
        f"Detail: {r.detail}"
    )
    assert "BUS" in r.detail
    assert "invocaBancs=SI" in r.detail


def test_run_block_0_bus_with_bancs_soap_fails(tmp_path: Path) -> None:
    """BUS + invocaBancs migrado como SOAP → HIGH mal-clasificado."""
    project = _mk_minimal_project(tmp_path, has_endpoint=True, has_controller=False, ops=3)
    ctx = CheckContext(
        migrated_path=project, legacy_path=None,
        source_type="bus", has_bancs=True,
    )
    results = run_block_0(ctx)
    r = _find_0_2c(results)
    assert r.status == "fail"
    assert r.severity == "high"
    assert "MAL-CLASIFICADO" in r.detail


def test_run_block_0_orq_rest_ok(tmp_path: Path) -> None:
    """ORQ migrado como REST con cualquier cant ops → PASS."""
    project = _mk_minimal_project(tmp_path, has_endpoint=False, has_controller=True, ops=2)
    ctx = CheckContext(
        migrated_path=project, legacy_path=None,
        source_type="orq", has_bancs=False,
    )
    results = run_block_0(ctx)
    r = _find_0_2c(results)
    assert r.status == "pass"
    assert "ORQ" in r.detail


def test_run_block_0_orq_soap_fails(tmp_path: Path) -> None:
    """ORQ migrado como SOAP → HIGH mal-clasificado."""
    project = _mk_minimal_project(tmp_path, has_endpoint=True, has_controller=False, ops=2)
    ctx = CheckContext(
        migrated_path=project, legacy_path=None,
        source_type="orq", has_bancs=False,
    )
    results = run_block_0(ctx)
    r = _find_0_2c(results)
    assert r.status == "fail"
    assert r.severity == "high"


def test_run_block_0_was_1op_rest_ok(tmp_path: Path) -> None:
    project = _mk_minimal_project(tmp_path, has_endpoint=False, has_controller=True, ops=1)
    ctx = CheckContext(
        migrated_path=project, legacy_path=None,
        source_type="was", has_bancs=False,
    )
    results = run_block_0(ctx)
    r = _find_0_2c(results)
    assert r.status == "pass"


def test_run_block_0_was_2op_soap_ok(tmp_path: Path) -> None:
    project = _mk_minimal_project(tmp_path, has_endpoint=True, has_controller=False, ops=2)
    ctx = CheckContext(
        migrated_path=project, legacy_path=None,
        source_type="was", has_bancs=False,
    )
    results = run_block_0(ctx)
    r = _find_0_2c(results)
    assert r.status == "pass"


def test_run_block_0_was_1op_soap_fails(tmp_path: Path) -> None:
    """WAS 1 op migrado como SOAP → HIGH (deberia REST+MVC)."""
    project = _mk_minimal_project(tmp_path, has_endpoint=True, has_controller=False, ops=1)
    ctx = CheckContext(
        migrated_path=project, legacy_path=None,
        source_type="was", has_bancs=False,
    )
    results = run_block_0(ctx)
    r = _find_0_2c(results)
    assert r.status == "fail"
    assert r.severity == "high"
