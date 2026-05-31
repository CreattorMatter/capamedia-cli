"""Tests del nuevo run_block_4 — politica headerIn 2026-05-26.

Mirror de BLOQUE 4 en `checklist-rules.md`:
  4.1 - NO existe HeaderRequestValidator.java
  4.2 - NO regex/maxLength sobre campos del header en controllers
  4.3 - Null-check de <bancs> SOLO si invocaBancs=true
  4.4 - NO HeaderValidationProperties / @ConfigurationProperties con patterns
  4.5 - Codigos 9927/9996 solo en contexto bancs/header
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capamedia_cli.core.checklist_rules import CheckContext, run_block_4


def _mig_root(tmp_path: Path) -> Path:
    """Crea estructura minima: src/main/java/com/pichincha/sp/infrastructure/."""
    root = tmp_path / "migrated"
    (root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "infrastructure").mkdir(parents=True)
    return root


def _write(root: Path, rel: str, body: str) -> Path:
    src_java = root / "src" / "main" / "java"
    p = src_java / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


# ---------------------------------------------------------------------------
# 4.1 — HeaderRequestValidator NO debe existir
# ---------------------------------------------------------------------------


def test_check_41_pass_when_no_validator(tmp_path: Path) -> None:
    root = _mig_root(tmp_path)
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was")
    assert _find(run_block_4(ctx), "4.1").status == "pass"


def test_check_41_high_when_validator_exists(tmp_path: Path) -> None:
    root = _mig_root(tmp_path)
    _write(root, "com/pichincha/sp/infrastructure/input/adapter/rest/util/HeaderRequestValidator.java",
           "public class HeaderRequestValidator { }\n")
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="bus", has_bancs=True)
    r = _find(run_block_4(ctx), "4.1")
    assert r.status == "fail"
    assert r.severity == "high"
    assert "HeaderRequestValidator" in r.detail


# ---------------------------------------------------------------------------
# 4.2 — NO regex/maxLength sobre campos del header en controller
# ---------------------------------------------------------------------------


def test_check_42_high_when_pattern_compile_on_header_field(tmp_path: Path) -> None:
    root = _mig_root(tmp_path)
    _write(root, "com/pichincha/sp/infrastructure/input/MyController.java",
        'public class MyController {\n'
        '    private static final Pattern DEVICE = Pattern.compile("^[A-Za-z]*$");\n'
        '    public void m() { if (!DEVICE.matcher(header.getDispositivo()).matches()) throw new RE(); }\n'
        '}\n')
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="bus", has_bancs=True)
    r = _find(run_block_4(ctx), "4.2")
    assert r.status == "fail" and r.severity == "high"


def test_check_42_high_when_length_check_on_header_field(tmp_path: Path) -> None:
    root = _mig_root(tmp_path)
    _write(root, "com/pichincha/sp/infrastructure/MyController.java",
        'public class MyController {\n'
        '    public void m() { if (header.getCanal().length() > 5) throw new RE(); }\n'
        '}\n')
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="bus", has_bancs=False)
    assert _find(run_block_4(ctx), "4.2").status == "fail"


def test_check_42_pass_when_no_header_validation(tmp_path: Path) -> None:
    root = _mig_root(tmp_path)
    _write(root, "MyController.java", 'public class MyController { public void m() { } }\n')
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was")
    assert _find(run_block_4(ctx), "4.2").status == "pass"


# ---------------------------------------------------------------------------
# 4.3 — Null-check de <bancs> condicional segun invocaBancs
# ---------------------------------------------------------------------------


def test_check_43_high_when_bus_with_bancs_lacks_nullcheck(tmp_path: Path) -> None:
    """invocaBancs=true pero NO hay null-check de <bancs> -> HIGH (falta)."""
    root = _mig_root(tmp_path)
    _write(root, "MyController.java", 'public class MyController { public void m() { businessLogic(); } }\n')
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="bus", has_bancs=True)
    r = _find(run_block_4(ctx), "4.3")
    assert r.status == "fail" and r.severity == "high"
    assert "no se encontro" in r.detail.lower()


def test_check_43_pass_when_bus_with_bancs_has_nullcheck(tmp_path: Path) -> None:
    root = _mig_root(tmp_path)
    _write(root, "MyController.java",
        'public class MyController {\n'
        '    public Mono<X> m(SoapEnvelopeRequestDto req) {\n'
        '        GenericHeaderIn headerIn = req.getBody().getOp().getHeaderIn();\n'
        '        if (headerIn == null || headerIn.getBancs() == null) return error();\n'
        '        return businessLogic();\n'
        '    }\n'
        '}\n')
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="bus", has_bancs=True)
    assert _find(run_block_4(ctx), "4.3").status == "pass"


def test_check_43_medium_when_was_has_nullcheck_residual(tmp_path: Path) -> None:
    """WAS NO debe tener null-check (residuo del template viejo) -> MEDIUM."""
    root = _mig_root(tmp_path)
    _write(root, "MyController.java",
        'public class MyController {\n'
        '    public X m() {\n'
        '        if (headerIn == null || headerIn.getBancs() == null) return error();\n'
        '        return ok();\n'
        '    }\n'
        '}\n')
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was", has_bancs=False)
    r = _find(run_block_4(ctx), "4.3")
    assert r.status == "fail" and r.severity == "medium"
    assert "residuo" in r.detail.lower() or "no debe" in r.title.lower()


def test_check_43_pass_when_was_without_nullcheck(tmp_path: Path) -> None:
    root = _mig_root(tmp_path)
    _write(root, "MyController.java", 'public class MyController { public X m() { return businessLogic(); } }\n')
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was", has_bancs=False)
    assert _find(run_block_4(ctx), "4.3").status == "pass"


# ---------------------------------------------------------------------------
# 4.4 — HeaderValidationProperties NO debe existir
# ---------------------------------------------------------------------------


def test_check_44_high_when_validation_props_exists(tmp_path: Path) -> None:
    root = _mig_root(tmp_path)
    _write(root, "com/pichincha/sp/infrastructure/config/HeaderValidationProperties.java",
           "public record HeaderValidationProperties(...) {}\n")
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="bus", has_bancs=True)
    assert _find(run_block_4(ctx), "4.4").severity == "high"


def test_check_44_pass_when_no_props(tmp_path: Path) -> None:
    root = _mig_root(tmp_path)
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was")
    assert _find(run_block_4(ctx), "4.4").status == "pass"


# ---------------------------------------------------------------------------
# 4.5 — Codigos 9927/9996 solo en contexto bancs/header
# ---------------------------------------------------------------------------


def test_check_45_pass_when_9927_in_bancs_context(tmp_path: Path) -> None:
    root = _mig_root(tmp_path)
    _write(root, "ErrorResolver.java",
        'public class ErrorResolver {\n'
        '    private static final String HEADER_MISSING_BANCS = "9927";\n'
        '    public String headerMissing() { return HEADER_MISSING_BANCS; }\n'
        '}\n')
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="bus", has_bancs=True)
    assert _find(run_block_4(ctx), "4.5").status == "pass"


def test_check_45_medium_when_9927_orphan(tmp_path: Path) -> None:
    """9927 sin contexto bancs/header en la cercania -> residuo validator viejo."""
    root = _mig_root(tmp_path)
    _write(root, "RandomThing.java",
        'public class RandomThing {\n'
        '    public String getCode(int x) {\n'
        '        if (x > 100) return "9927";\n'
        '        return "0";\n'
        '    }\n'
        '}\n')
    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was")
    r = _find(run_block_4(ctx), "4.5")
    assert r.status == "fail" and r.severity == "medium"
