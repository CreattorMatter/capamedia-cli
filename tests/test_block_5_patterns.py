"""Tests for Block 5 patterns detected in QA report WSClientes0011 (2026-05).

Cubre los 4 checks nuevos/ampliados en run_block_5:
- 5.5b: mensajes de error normalizados (Normalizer.normalize / stripAccents /
        replaceAll("\\s+", " ")) -> MEDIUM
- 5.6.1: constante ERROR_TYPE_FATAL existe en CatalogExceptionConstants -> MEDIUM
- 5.6.5: BusinessValidationException nunca se mapea a FATAL -> HIGH
- 5.8: fechas no informadas en adapter/bancs/ = alto valor 31129999, no
       bajo valor 01011901 -> MEDIUM

Tambien cubre el autofix `fix_bve_not_fatal` para el caso 5.6.5.
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.bank_autofix import fix_bve_not_fatal
from capamedia_cli.core.checklist_rules import CheckContext, run_block_5


def _make_migrated(tmp_path: Path) -> Path:
    """Layout minimo: src/main/java/com/pichincha/sp/{infrastructure,...}."""
    root = tmp_path / "migrated"
    base = root / "src" / "main" / "java" / "com" / "pichincha" / "sp"
    (base / "infrastructure" / "exception").mkdir(parents=True)
    (base / "infrastructure" / "input" / "adapter" / "soap" / "impl").mkdir(parents=True)
    (base / "infrastructure" / "output" / "adapter" / "bancs").mkdir(parents=True)
    return root


def _write_java(root: Path, relative: str, body: str) -> Path:
    f = root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / relative
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    return f


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


# ---------------------------------------------------------------------------
# Check 5.5b — Mensajes de error sin normalizar
# ---------------------------------------------------------------------------


def test_5_5b_normalizer_in_setMensaje_is_medium(tmp_path: Path) -> None:
    """Aplicar Normalizer.normalize al mensaje antes de setMensaje -> MEDIUM."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/Mapper.java",
        """
        import java.text.Normalizer;
        public class Mapper {
            void map(GenericError error, String mensaje) {
                String clean = Normalizer.normalize(mensaje, Normalizer.Form.NFD);
                error.setMensaje(clean);
            }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.5b")

    assert check is not None
    assert check.status == "fail"
    assert check.severity == "medium"


def test_5_5b_stripAccents_is_medium(tmp_path: Path) -> None:
    """StringUtils.stripAccents en setMensajeCliente -> MEDIUM."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/Mapper.java",
        """
        public class Mapper {
            void map(GenericError error, String msg) {
                error.setMensajeCliente(stripAccents(msg));
            }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.5b")
    assert check.status == "fail"


def test_5_5b_replaceAll_whitespace_collapse_is_medium(tmp_path: Path) -> None:
    """replaceAll("\\\\s+", " ") en mensaje colapsa dobles espacios -> MEDIUM."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/Mapper.java",
        r"""
        public class Mapper {
            void map(GenericError error, String msg) {
                String collapsed = msg.replaceAll("\\s+", " ");
                error.setMensaje(collapsed);
            }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.5b")
    assert check.status == "fail"


def test_5_5b_no_normalization_passes(tmp_path: Path) -> None:
    """Sin normalizacion en codigo cerca de setMensaje -> PASS."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/Mapper.java",
        """
        public class Mapper {
            void map(GenericError error, String msg) {
                error.setMensaje(msg);  // tal cual del catalogo
            }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.5b")
    assert check.status == "pass"


def test_5_5b_normalizer_in_unrelated_util_is_pass(tmp_path: Path) -> None:
    """Normalizer en un util no relacionado a errores -> PASS (no falso positivo)."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/util/SearchHelper.java",
        """
        import java.text.Normalizer;
        public class SearchHelper {
            String normalize(String s) { return Normalizer.normalize(s, Normalizer.Form.NFD); }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.5b")
    assert check.status == "pass"


# ---------------------------------------------------------------------------
# Check 5.6.1 — Constante ERROR_TYPE_FATAL
# ---------------------------------------------------------------------------


def test_5_6_1_error_type_fatal_present_passes(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/exception/CatalogExceptionConstants.java",
        """
        public class CatalogExceptionConstants {
            public static final String ERROR_TYPE_INFO = "INFO";
            public static final String ERROR_TYPE_ERROR = "ERROR";
            public static final String ERROR_TYPE_FATAL = "FATAL";
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.6.1")
    assert check is not None
    assert check.status == "pass"


def test_5_6_1_error_type_fatal_missing_is_medium(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/exception/CatalogExceptionConstants.java",
        """
        public class CatalogExceptionConstants {
            public static final String ERROR_TYPE_INFO = "INFO";
            public static final String ERROR_TYPE_ERROR = "ERROR";
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.6.1")
    assert check.status == "fail"
    assert check.severity == "medium"


def test_5_6_1_no_catalog_skips_check(tmp_path: Path) -> None:
    """Sin CatalogExceptionConstants no se emite 5.6.1 (esta cubierto por otros checks)."""
    root = _make_migrated(tmp_path)
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    assert _find(results, "5.6.1") is None


# ---------------------------------------------------------------------------
# Check 5.6.5 — BusinessValidationException nunca a FATAL
# ---------------------------------------------------------------------------


def test_5_6_5_bve_routed_to_buildFatalResponse_is_high(tmp_path: Path) -> None:
    """Catch BVE seguido de buildFatalResponse en la ventana -> HIGH (bug del informe)."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/CustomerController.java",
        """
        public class CustomerController {
            void handle() {
                try {
                    service.execute();
                } catch (BusinessValidationException bve) {
                    return helper.buildFatalResponse(bve, headerOut);
                }
            }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.6.5")
    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"


def test_5_6_5_bve_routed_to_buildBancsErrorResponse_is_high(tmp_path: Path) -> None:
    """Catch BVE + buildBancsErrorResponse tambien es bug (BANCS != validacion)."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/CustomerController.java",
        """
        public class CustomerController {
            void handle() {
                try { service.execute(); }
                catch (BusinessValidationException bve) {
                    return helper.buildBancsErrorResponse(bve, headerOut);
                }
            }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.6.5")
    assert check.status == "fail"
    assert check.severity == "high"


def test_5_6_5_bve_with_setTipo_FATAL_is_high(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/CustomerController.java",
        """
        public class CustomerController {
            void handle() {
                try { service.execute(); }
                catch (BusinessValidationException bve) {
                    error.setTipo("FATAL");
                    error.setCodigo(bve.getErrorCode());
                }
            }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.6.5")
    assert check.status == "fail"


def test_5_6_5_bve_routed_to_buildErrorResponse_passes(tmp_path: Path) -> None:
    """Catch BVE + buildErrorResponse -> PASS (es lo correcto)."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/CustomerController.java",
        """
        public class CustomerController {
            void handle() {
                try { service.execute(); }
                catch (BusinessValidationException bve) {
                    return helper.buildErrorResponse(bve, headerOut);
                }
            }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.6.5")
    assert check.status == "pass"


def test_5_6_5_no_bve_in_project_passes(tmp_path: Path) -> None:
    """Sin BusinessValidationException en el proyecto -> PASS."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/Controller.java",
        "public class Controller { void noop() {} }",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.6.5")
    assert check.status == "pass"


# ---------------------------------------------------------------------------
# Check 5.8 — Fechas alto valor BANCS
# ---------------------------------------------------------------------------


def test_5_8_low_value_literal_in_bancs_adapter_is_medium(tmp_path: Path) -> None:
    """Literal "01011901" en adapter/bancs/ -> MEDIUM."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/output/adapter/bancs/CustomerAdapterBancs.java",
        """
        public class CustomerAdapterBancs {
            String defaultDate() { return "01011901"; }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.8")
    assert check is not None
    assert check.status == "fail"
    assert check.severity == "medium"


def test_5_8_LocalDate_MIN_is_medium(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/output/adapter/bancs/CustomerAdapterBancs.java",
        """
        import java.time.LocalDate;
        public class CustomerAdapterBancs {
            LocalDate fallback() { return LocalDate.MIN; }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.8")
    assert check.status == "fail"


def test_5_8_LocalDate_of_1901_1_1_is_medium(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/output/adapter/bancs/CustomerAdapterBancs.java",
        """
        import java.time.LocalDate;
        public class CustomerAdapterBancs {
            LocalDate fallback() { return LocalDate.of(1901, 1, 1); }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.8")
    assert check.status == "fail"


def test_5_8_high_value_31129999_passes(tmp_path: Path) -> None:
    """Literal "31129999" o LocalDate.of(9999,12,31) -> PASS."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/output/adapter/bancs/CustomerAdapterBancs.java",
        """
        import java.time.LocalDate;
        public class CustomerAdapterBancs {
            String defaultDate() { return "31129999"; }
            LocalDate fallback() { return LocalDate.of(9999, 12, 31); }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.8")
    assert check.status == "pass"


def test_5_8_no_bancs_adapter_skips_check(tmp_path: Path) -> None:
    """Sin adapter/bancs/, el check 5.8 no se emite."""
    root = _make_migrated(tmp_path)
    # eliminar el dir vacio para que rglob no lo encuentre
    bancs_dir = root / "src/main/java/com/pichincha/sp/infrastructure/output/adapter/bancs"
    bancs_dir.rmdir()
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    assert _find(results, "5.8") is None


def test_5_8_low_value_outside_bancs_adapter_passes(tmp_path: Path) -> None:
    """Literal 01011901 en otro adapter (no bancs) no es bug -> 5.8 PASS (no aplica)."""
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/output/adapter/other/SomeAdapter.java",
        """
        public class SomeAdapter {
            String def() { return "01011901"; }
        }
        """,
    )
    # Mantener el dir bancs vacio para que el check se emita y sea PASS
    _write_java(
        root,
        "infrastructure/output/adapter/bancs/BancsAdapter.java",
        "public class BancsAdapter { void noop() {} }",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_5(ctx)
    check = _find(results, "5.8")
    assert check is not None
    assert check.status == "pass"


# ---------------------------------------------------------------------------
# Autofix fix_bve_not_fatal
# ---------------------------------------------------------------------------


def test_autofix_replaces_buildFatalResponse_in_bve_catch(tmp_path: Path) -> None:
    """Autofix reemplaza buildFatalResponse por buildErrorResponse dentro del catch BVE."""
    root = _make_migrated(tmp_path)
    f = _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/Controller.java",
        """public class Controller {
    void h() {
        try { svc.run(); }
        catch (BusinessValidationException bve) {
            return helper.buildFatalResponse(bve, headerOut);
        }
    }
}
""",
    )

    result = fix_bve_not_fatal(root)

    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    assert "buildErrorResponse" in text
    assert "buildFatalResponse" not in text


def test_autofix_replaces_setTipo_FATAL_in_bve_catch(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    f = _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/Controller.java",
        """public class Controller {
    void h() {
        try { svc.run(); }
        catch (BusinessValidationException bve) {
            error.setTipo("FATAL");
            error.setCodigo(bve.getErrorCode());
        }
    }
}
""",
    )

    result = fix_bve_not_fatal(root)

    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    assert 'setTipo("ERROR")' in text
    assert 'setTipo("FATAL")' not in text


def test_autofix_does_not_touch_FATAL_outside_bve_catch(tmp_path: Path) -> None:
    """FATAL en un catch de BancsOperationException (que SI debe ser FATAL) no se toca."""
    root = _make_migrated(tmp_path)
    f = _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/Controller.java",
        """public class Controller {
    void h() {
        try { svc.run(); }
        catch (BancsOperationException be) {
            return helper.buildFatalResponse(be, headerOut);
        }
    }
}
""",
    )
    original = f.read_text(encoding="utf-8")

    result = fix_bve_not_fatal(root)

    assert result.applied is False
    assert f.read_text(encoding="utf-8") == original


def test_autofix_idempotent(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/Controller.java",
        """public class Controller {
    void h() {
        try { svc.run(); }
        catch (BusinessValidationException bve) {
            return helper.buildFatalResponse(bve, headerOut);
        }
    }
}
""",
    )

    first = fix_bve_not_fatal(root)
    second = fix_bve_not_fatal(root)

    assert first.applied is True
    assert second.applied is False
