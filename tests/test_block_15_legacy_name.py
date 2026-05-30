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
    """Create a minimal migrated project with component name available."""
    root = tmp_path / "migrated"
    src_java = root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "infrastructure"
    src_java.mkdir(parents=True)
    resources = root / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "application.yml").write_text(
        "spring:\n"
        "  application:\n"
        f"    name: {catalog_name}\n",
        encoding="utf-8",
    )

    (root / "catalog-info.yaml").write_text(
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Component\n"
        "metadata:\n"
        "  name: tpl-middleware\n"
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
    """Si spring.application.name existe y el legacy hallado coincide
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


def test_autofix_skips_when_component_name_missing(tmp_path: Path) -> None:
    """Sin spring.application.name/carpeta canonica no hay nombre canonico. Skip."""
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
    assert "spring.application.name" in result.notes


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


# ---------------------------------------------------------------------------
# Etapa 5 — Pass 2 del autofix: cubre patrones que la Pass 1 (regex setter
# + literal directo) no veia. Verificado empiricamente en 0010 y 0022.
# ---------------------------------------------------------------------------


def _write_java_subdir(root: Path, rel_path: str, body: str) -> Path:
    """Escribe un .java bajo infrastructure/, creando subdirs si hacen falta.

    A diferencia de _write_java (que solo escribe en infrastructure/ raiz),
    este helper acepta rel_path con '/' para tests que necesitan multiples
    archivos en distintos paquetes (caso CONST_CLASS donde la constante vive
    en infrastructure/exception/ y el setter en infrastructure/soap/).
    """
    src_java = root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "infrastructure"
    f = src_java / rel_path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    return f


def test_autofix_pass2_replaces_legacy_in_const_local_same_file(tmp_path: Path) -> None:
    """Patron 0010: constante LOCAL en el mismo archivo donde se usa
    en builder ingles .resource(RESOURCE). Pass 1 no lo veia."""
    root = _make_migrated_with_catalog(tmp_path, "tnd-msa-sp-wsclientes0010")
    _write_java(root, "QueryService.java",
        'public class QueryService {\n'
        '    private static final String RESOURCE = "WSClientes0010/consultarGrupoClaveDigital01";\n'
        '    public ServiceError build() {\n'
        '        return ServiceError.builder().resource(RESOURCE).build();\n'
        '    }\n'
        '}\n')
    result = fix_legacy_name_in_error_payload(root)
    assert result.applied is True
    text = (root / "src/main/java/com/pichincha/sp/infrastructure/QueryService.java").read_text(encoding="utf-8")
    # El literal en la def de la constante quedo reescrito
    assert 'private static final String RESOURCE = "tnd-msa-sp-wsclientes0010/consultarGrupoClaveDigital01";' in text
    # El .resource(RESOURCE) sigue igual (es una referencia, no el literal)
    assert '.resource(RESOURCE)' in text


def test_autofix_pass2_replaces_legacy_in_const_class_other_file(tmp_path: Path) -> None:
    """Patron 0013/0022: CONST_CLASS — la constante vive en otra clase utility.
    El autofix encuentra el archivo y edita el literal alli."""
    root = _make_migrated_with_catalog(tmp_path, "tnd-msa-sp-wsclientes0011")
    # Catalogo de constantes (otro archivo)
    _write_java_subdir(root, "exception/CatalogExceptionConstants.java",
        'public class CatalogExceptionConstants {\n'
        '    public static final String WS_RECURSO = "WSClientes0011/ConsultarDatosIdentificacion";\n'
        '    public static final String WS_COMPONENTE = "WSClientes0011";\n'
        '}\n')
    # Setter que lo usa
    _write_java_subdir(root, "soap/Mapper.java",
        'public class Mapper {\n'
        '    public GenericError map() {\n'
        '        GenericError error = new GenericError();\n'
        '        error.setRecurso(CatalogExceptionConstants.WS_RECURSO);\n'
        '        error.setComponente(CatalogExceptionConstants.WS_COMPONENTE);\n'
        '        return error;\n'
        '    }\n'
        '}\n')
    result = fix_legacy_name_in_error_payload(root)
    assert result.applied is True
    cat = (root / "src/main/java/com/pichincha/sp/infrastructure/exception/CatalogExceptionConstants.java").read_text(encoding="utf-8")
    assert 'WS_RECURSO = "tnd-msa-sp-wsclientes0011/ConsultarDatosIdentificacion"' in cat
    assert 'WS_COMPONENTE = "tnd-msa-sp-wsclientes0011"' in cat
    # El Mapper sigue igual (referencia a la constante, no toca)
    mapper = (root / "src/main/java/com/pichincha/sp/infrastructure/soap/Mapper.java").read_text(encoding="utf-8")
    assert 'error.setRecurso(CatalogExceptionConstants.WS_RECURSO);' in mapper


def test_autofix_pass2_replaces_legacy_in_builder_with_literal(tmp_path: Path) -> None:
    """Builder fluent espanol .recurso("literal") — Pass 1 solo cubre setRecurso/setComponente."""
    root = _make_migrated_with_catalog(tmp_path, "tnd-msa-sp-orqclientes0022")
    _write_java(root, "Impl.java",
        'public class Impl {\n'
        '    public ServiceError build() {\n'
        '        return ServiceError.builder()\n'
        '                .recurso("ORQClientes0022/ConsultarInformacionClienteVirtual01")\n'
        '                .build();\n'
        '    }\n'
        '}\n')
    result = fix_legacy_name_in_error_payload(root)
    assert result.applied is True
    text = (root / "src/main/java/com/pichincha/sp/infrastructure/Impl.java").read_text(encoding="utf-8")
    assert '.recurso("tnd-msa-sp-orqclientes0022/ConsultarInformacionClienteVirtual01")' in text


def test_autofix_pass2_idempotent_no_changes_on_second_run(tmp_path: Path) -> None:
    """Idempotencia Pass 2: tras correr 1 vez, la 2a no encuentra mas hits legacy."""
    root = _make_migrated_with_catalog(tmp_path, "tnd-msa-sp-wsclientes0010")
    _write_java(root, "QueryService.java",
        'public class QueryService {\n'
        '    private static final String RESOURCE = "WSClientes0010/Op";\n'
        '    public void m() { ServiceError.builder().resource(RESOURCE).build(); }\n'
        '}\n')
    first = fix_legacy_name_in_error_payload(root)
    second = fix_legacy_name_in_error_payload(root)
    assert first.applied is True
    assert second.applied is False
    # File quedo en el estado migrado correcto
    text = (root / "src/main/java/com/pichincha/sp/infrastructure/QueryService.java").read_text(encoding="utf-8")
    assert 'private static final String RESOURCE = "tnd-msa-sp-wsclientes0010/Op";' in text


def test_autofix_pass2_skips_legacy_of_other_service(tmp_path: Path) -> None:
    """Si la constante referencia OTRO servicio legitimo (downstream/log), no tocar.

    Caso real: 0022 puede tener DOWNSTREAM_COMPONENT = "WSClientes0046/Op" como
    componente legitimo en error propagado del downstream. NO debe reescribirse
    como si fuera del propio 0022."""
    root = _make_migrated_with_catalog(tmp_path, "tnd-msa-sp-orqclientes0022")
    _write_java_subdir(root, "exception/ErrorCatalogConstants.java",
        'public class ErrorCatalogConstants {\n'
        '    public static final String RESOURCE_NAME = "ORQClientes0022/Op";\n'
        '    public static final String DOWNSTREAM = "WSClientes0046/DownstreamOp";\n'
        '}\n')
    _write_java(root, "Impl.java",
        'public class Impl {\n'
        '    public void m() {\n'
        '        ServiceError.builder()\n'
        '            .recurso(ErrorCatalogConstants.RESOURCE_NAME)\n'
        '            .componente(ErrorCatalogConstants.DOWNSTREAM)\n'
        '            .build();\n'
        '    }\n'
        '}\n')
    result = fix_legacy_name_in_error_payload(root)
    assert result.applied is True
    cat = (root / "src/main/java/com/pichincha/sp/infrastructure/exception/ErrorCatalogConstants.java").read_text(encoding="utf-8")
    # El RESOURCE_NAME (del propio 0022) SI se reescribio
    assert 'RESOURCE_NAME = "tnd-msa-sp-orqclientes0022/Op"' in cat
    # El DOWNSTREAM (otro servicio) NO se tocó
    assert 'DOWNSTREAM = "WSClientes0046/DownstreamOp"' in cat
