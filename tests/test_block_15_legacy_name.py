"""Tests for Block 15 — legacy service name leak in error.recurso / error.componente.

Background: QA del banco reporto (mayo 2026, ticket BTHCCC-6826) que el response
del servicio migrado WSClientes0011 traia el nombre LEGACY ("WSClientes0011")
en error.recurso y error.componente, cuando el estandar BPTPSRE exige el nombre
del COMPONENTE MIGRADO (spring.application.name = <namespace>-msa-sp-<svc>).

Estos tests blindan que run_block_15 detecta el patron como HIGH y propone
el fix correcto. Aplica a BUS/IIB (WSClientesNNNN), WAS (WSAlgoNNNN) y
ORQ (ORQAlgoNNNN, ORQNNNN, UMPAlgoNNNN).
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.bank_autofix import fix_legacy_name_in_error_payload
from capamedia_cli.core.checklist_rules import CheckContext, run_block_15


def _make_migrated_with_catalog(tmp_path: Path, catalog_name: str = "tnd-msa-sp-wsclientes0011") -> Path:
    """Create a minimal migrated project with catalog-info.yaml metadata.name set."""
    root = tmp_path / "migrated"
    src_java = root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "infrastructure"
    src_java.mkdir(parents=True)

    (root / "catalog-info.yaml").write_text(
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Component\n"
        "metadata:\n"
        f"  name: {catalog_name}\n"
        "  namespace: tnd-middleware\n"
        "spec:\n"
        "  type: service\n",
        encoding="utf-8",
    )
    return root


def _write_java(root: Path, name: str, body: str) -> Path:
    """Drop a java file under infrastructure/."""
    src_java = root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "infrastructure"
    f = src_java / name
    f.write_text(body, encoding="utf-8")
    return f


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


# ---------------------------------------------------------------------------
# 15.2 - recurso
# ---------------------------------------------------------------------------


def test_15_2_recurso_with_legacy_name_is_high(tmp_path: Path) -> None:
    """setRecurso("WSClientes0011/Op") debe ser HIGH (bug exacto de QA)."""
    root = _make_migrated_with_catalog(tmp_path)
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setRecurso("WSClientes0011/ConsultarDatosIdentificacion"); error.setComponente("tnd-msa-sp-wsclientes0011"); } }',
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)

    check = _find(results, "15.2")
    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"
    assert "legacy" in check.detail.lower()
    assert "tnd-msa-sp-wsclientes0011" in check.suggested_fix


def test_15_2_recurso_with_migrated_name_passes(tmp_path: Path) -> None:
    """setRecurso("tnd-msa-sp-wsclientes0011/Op") debe pasar."""
    root = _make_migrated_with_catalog(tmp_path)
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setRecurso("tnd-msa-sp-wsclientes0011/ConsultarDatosIdentificacion"); error.setComponente("tnd-msa-sp-wsclientes0011"); } }',
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)

    check = _find(results, "15.2")
    assert check is not None
    assert check.status == "pass"


def test_15_2_recurso_with_csg_namespace_passes(tmp_path: Path) -> None:
    """Sin hardcodear 'tnd-': el prefijo csg- debe pasar igual."""
    root = _make_migrated_with_catalog(tmp_path, catalog_name="csg-msa-sp-wsclientes0011")
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setRecurso("csg-msa-sp-wsclientes0011/Op"); error.setComponente("csg-msa-sp-wsclientes0011"); } }',
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)

    check = _find(results, "15.2")
    assert check is not None
    assert check.status == "pass"


def test_15_2_recurso_without_slash_is_medium(tmp_path: Path) -> None:
    """setRecurso sin '/' (mal formato pero sin nombre legacy) sigue siendo MEDIUM."""
    root = _make_migrated_with_catalog(tmp_path)
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setRecurso("just-a-name"); error.setComponente("tnd-msa-sp-wsclientes0011"); } }',
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)

    check = _find(results, "15.2")
    assert check is not None
    assert check.status == "fail"
    assert check.severity == "medium"
    assert "/" in check.suggested_fix


# ---------------------------------------------------------------------------
# 15.3 - componente
# ---------------------------------------------------------------------------


def test_15_3_componente_with_legacy_iib_name_is_high(tmp_path: Path) -> None:
    """setComponente("WSClientes0011") debe ser HIGH (bug exacto de QA)."""
    root = _make_migrated_with_catalog(tmp_path)
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setRecurso("tnd-msa-sp-wsclientes0011/Op"); error.setComponente("WSClientes0011"); } }',
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)

    check = _find(results, "15.3")
    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"
    assert "legacy" in check.detail.lower()
    # El fix debe mencionar los 3 valores validos
    assert "ApiClient" in check.suggested_fix
    assert "TX" in check.suggested_fix


def test_15_3_componente_with_legacy_orq_name_is_high(tmp_path: Path) -> None:
    """ORQ legacy tambien es HIGH (no solo WS*)."""
    root = _make_migrated_with_catalog(tmp_path, catalog_name="tnd-msa-sp-orqtransferencias0003")
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setRecurso("tnd-msa-sp-orqtransferencias0003/Op"); error.setComponente("ORQTransferencias0003"); } }',
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)

    check = _find(results, "15.3")
    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"


def test_15_3_componente_with_legacy_ump_name_is_high(tmp_path: Path) -> None:
    """UMP* legacy en componente tambien es HIGH."""
    root = _make_migrated_with_catalog(tmp_path)
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setRecurso("tnd-msa-sp-wsclientes0011/Op"); error.setComponente("UMPClientes0002"); } }',
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)

    check = _find(results, "15.3")
    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"


def test_15_3_componente_apiclient_passes(tmp_path: Path) -> None:
    """'ApiClient' es valor canonico aceptado (error propagado desde libreria)."""
    root = _make_migrated_with_catalog(tmp_path)
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setRecurso("tnd-msa-sp-wsclientes0011/Op"); error.setComponente("ApiClient"); } }',
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)

    check = _find(results, "15.3")
    assert check is not None
    assert check.status == "pass"


def test_15_3_componente_tx_code_passes(tmp_path: Path) -> None:
    """'TX060480' (6 digitos) es valor canonico aceptado (error de negocio BANCS)."""
    root = _make_migrated_with_catalog(tmp_path)
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setRecurso("tnd-msa-sp-wsclientes0011/Op"); error.setComponente("TX060480"); } }',
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)

    check = _find(results, "15.3")
    assert check is not None
    assert check.status == "pass"


def test_15_3_componente_migrated_artifactid_passes(tmp_path: Path) -> None:
    """spring.application.name del componente migrado es valor canonico aceptado."""
    root = _make_migrated_with_catalog(tmp_path)
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setRecurso("tnd-msa-sp-wsclientes0011/Op"); error.setComponente("tnd-msa-sp-wsclientes0011"); } }',
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)

    check = _find(results, "15.3")
    assert check is not None
    assert check.status == "pass"


def test_15_3_componente_no_hardcoded_tnd_prefix(tmp_path: Path) -> None:
    """Cualquier namespace de 3 letras matchea; no hardcodear 'tnd-'."""
    for ns in ["tnd", "csg", "tia", "bpe"]:
        root_dir = tmp_path / ns
        root_dir.mkdir()
        root = _make_migrated_with_catalog(root_dir, catalog_name=f"{ns}-msa-sp-wsclientes0011")
        _write_java(
            root,
            "ErrorMapper.java",
            f'public class ErrorMapper {{ void map() {{ error.setRecurso("{ns}-msa-sp-wsclientes0011/Op"); error.setComponente("{ns}-msa-sp-wsclientes0011"); }} }}',
        )

        ctx = CheckContext(migrated_path=root, legacy_path=None)
        results = run_block_15(ctx)
        check = _find(results, "15.3")
        assert check is not None, f"namespace={ns}"
        assert check.status == "pass", f"namespace={ns} should pass but got {check.status}: {check.detail}"


# ---------------------------------------------------------------------------
# Cross-check: el WS_RECURSO con prefijo migrado pero el setComponente con
# legacy debe seguir fallando solo el 15.3, no el 15.2.
# ---------------------------------------------------------------------------


def test_15_2_passes_and_15_3_fails_independently(tmp_path: Path) -> None:
    """Recurso bien, componente mal: 15.2 pass, 15.3 high."""
    root = _make_migrated_with_catalog(tmp_path)
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setRecurso("tnd-msa-sp-wsclientes0011/Op"); error.setComponente("WSClientes0011"); } }',
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)

    assert _find(results, "15.2").status == "pass"
    check_15_3 = _find(results, "15.3")
    assert check_15_3.status == "fail"
    assert check_15_3.severity == "high"


# ---------------------------------------------------------------------------
# Autofix fix_legacy_name_in_error_payload
# ---------------------------------------------------------------------------


def test_autofix_replaces_legacy_name_in_setters(tmp_path: Path) -> None:
    """Si catalog-info.yaml tiene metadata.name y el legacy hallado coincide
    con el sufijo del migrado, el autofix reemplaza el literal."""
    root = _make_migrated_with_catalog(tmp_path, catalog_name="tnd-msa-sp-wsclientes0011")
    f = _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() {\n'
        '    error.setRecurso("WSClientes0011/ConsultarDatosIdentificacion");\n'
        '    error.setComponente("WSClientes0011");\n'
        '} }',
    )

    result = fix_legacy_name_in_error_payload(root)

    assert result.applied is True
    assert len(result.files_modified) == 1
    text = f.read_text(encoding="utf-8")
    assert 'setRecurso("tnd-msa-sp-wsclientes0011/ConsultarDatosIdentificacion")' in text
    assert 'setComponente("tnd-msa-sp-wsclientes0011")' in text
    assert "WSClientes0011" not in text


def test_autofix_skips_when_legacy_unrelated_to_migrated(tmp_path: Path) -> None:
    """Si el legacy hallado no es el del componente migrado, NO tocar.
    Puede ser una referencia legitima a otro servicio (ej. en logs).
    """
    root = _make_migrated_with_catalog(tmp_path, catalog_name="tnd-msa-sp-wsclientes0011")
    f = _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setComponente("WSCuentas0007"); } }',
    )
    original = f.read_text(encoding="utf-8")

    result = fix_legacy_name_in_error_payload(root)

    assert result.applied is False
    assert f.read_text(encoding="utf-8") == original


def test_autofix_skips_when_catalog_missing(tmp_path: Path) -> None:
    """Sin catalog-info.yaml no hay forma de saber el nombre canonico. Skip."""
    root = tmp_path / "no-catalog"
    src_java = root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "infrastructure"
    src_java.mkdir(parents=True)
    f = src_java / "ErrorMapper.java"
    f.write_text(
        'public class ErrorMapper { void map() { error.setComponente("WSClientes0011"); } }',
        encoding="utf-8",
    )

    result = fix_legacy_name_in_error_payload(root)

    assert result.applied is False
    assert "catalog" in result.notes.lower()


def test_autofix_idempotent(tmp_path: Path) -> None:
    """Correr el autofix dos veces no rompe el resultado."""
    root = _make_migrated_with_catalog(tmp_path, catalog_name="csg-msa-sp-wsclientes0011")
    _write_java(
        root,
        "ErrorMapper.java",
        'public class ErrorMapper { void map() { error.setComponente("WSClientes0011"); } }',
    )

    first = fix_legacy_name_in_error_payload(root)
    second = fix_legacy_name_in_error_payload(root)

    assert first.applied is True
    assert second.applied is False
    # File sigue correcto
    text = (root / "src/main/java/com/pichincha/sp/infrastructure/ErrorMapper.java").read_text(encoding="utf-8")
    assert 'setComponente("csg-msa-sp-wsclientes0011")' in text
