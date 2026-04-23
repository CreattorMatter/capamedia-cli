"""Tests para Block 3 (v0.22.0): Naming profesional - sin nombres genericos."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import CheckContext, run_block_3


def _mk_java(path: Path, class_decl: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "package com.pichincha;\n\n" + class_decl + "\n",
        encoding="utf-8",
    )


def test_flags_generic_service_class(tmp_path: Path) -> None:
    """`public class Service` sin prefijo de dominio -> FAIL HIGH."""
    project = tmp_path / "proj"
    _mk_java(
        project / "src" / "main" / "java" / "com" / "pichincha" / "Service.java",
        "public class Service {}",
    )
    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_3(ctx)
    fails = [r for r in results if r.status == "fail"]
    assert len(fails) == 1
    assert fails[0].severity == "high"
    assert "Service" in fails[0].title


def test_flags_multiple_generic_classes(tmp_path: Path) -> None:
    """Varias clases genericas → un FAIL por cada una."""
    project = tmp_path / "proj"
    jdir = project / "src" / "main" / "java" / "com" / "pichincha"
    _mk_java(jdir / "Service.java", "public class Service {}")
    _mk_java(jdir / "Adapter.java", "public class Adapter {}")
    _mk_java(jdir / "Request.java", "public record Request(String x) {}")
    _mk_java(jdir / "Mapper.java", "public interface Mapper {}")

    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_3(ctx)
    fail_ids = {r.id for r in results if r.status == "fail"}
    assert "3.5.Service" in fail_ids
    assert "3.5.Adapter" in fail_ids
    assert "3.5.Request" in fail_ids
    assert "3.5.Mapper" in fail_ids


def test_passes_when_classes_have_domain_prefix(tmp_path: Path) -> None:
    """Clases con dominio como prefijo (`CustomerService`, `BancsAdapter`) → PASS."""
    project = tmp_path / "proj"
    jdir = project / "src" / "main" / "java" / "com" / "pichincha"
    _mk_java(jdir / "CustomerService.java", "public class CustomerService {}")
    _mk_java(jdir / "BancsAdapter.java", "public class BancsAdapter {}")
    _mk_java(jdir / "GetContactRequest.java", "public record GetContactRequest(String x) {}")
    _mk_java(jdir / "HeaderValidator.java", "public class HeaderValidator {}")

    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_3(ctx)
    assert all(r.status == "pass" for r in results), (
        f"Todas las clases con prefijo deberian PASS. Got: {results}"
    )


def test_mixed_generic_and_domain_classes(tmp_path: Path) -> None:
    """Si hay 1 generica y 3 con dominio, solo 1 FAIL."""
    project = tmp_path / "proj"
    jdir = project / "src" / "main" / "java" / "com" / "pichincha"
    _mk_java(jdir / "CustomerService.java", "public class CustomerService {}")
    _mk_java(jdir / "BancsAdapter.java", "public class BancsAdapter {}")
    _mk_java(jdir / "Controller.java", "public class Controller {}")  # ← generica
    _mk_java(jdir / "HeaderValidator.java", "public class HeaderValidator {}")

    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_3(ctx)
    fails = [r for r in results if r.status == "fail"]
    assert len(fails) == 1
    assert "Controller" in fails[0].title


def test_detects_interfaces_and_records(tmp_path: Path) -> None:
    """El check aplica a class, interface, record y enum."""
    project = tmp_path / "proj"
    jdir = project / "src" / "main" / "java" / "com" / "pichincha"
    _mk_java(jdir / "Port.java", "public interface Port {}")
    _mk_java(jdir / "Dto.java", "public record Dto(String x) {}")

    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_3(ctx)
    fail_ids = {r.id for r in results if r.status == "fail"}
    assert "3.5.Port" in fail_ids
    assert "3.5.Dto" in fail_ids


def test_no_source_java_dir_returns_empty(tmp_path: Path) -> None:
    """Si no existe src/main/java, no emite results."""
    project = tmp_path / "proj"
    project.mkdir()
    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_3(ctx)
    assert results == []


def test_empty_java_dir_passes(tmp_path: Path) -> None:
    """src/main/java vacio → 1 result PASS."""
    project = tmp_path / "proj"
    (project / "src" / "main" / "java").mkdir(parents=True)
    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_3(ctx)
    assert len(results) == 1
    assert results[0].status == "pass"


def test_ignores_build_dir(tmp_path: Path) -> None:
    """Archivos en build/ no se revisan (son autogenerados)."""
    project = tmp_path / "proj"
    build_java = project / "src" / "main" / "java" / "build" / "Service.java"
    _mk_java(build_java, "public class Service {}")
    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_3(ctx)
    # Sin clases validas, pasa (nada genericio detectable fuera de build/)
    fails = [r for r in results if r.status == "fail"]
    assert fails == []


def test_suggested_fix_includes_domain_examples(tmp_path: Path) -> None:
    """El suggested_fix debe dar ejemplos utiles (Customer, Bancs, <Operation>)."""
    project = tmp_path / "proj"
    _mk_java(
        project / "src" / "main" / "java" / "com" / "pichincha" / "Adapter.java",
        "public class Adapter {}",
    )
    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_3(ctx)
    r = next(r for r in results if r.status == "fail")
    assert "Customer" in r.suggested_fix
    assert "Bancs" in r.suggested_fix
