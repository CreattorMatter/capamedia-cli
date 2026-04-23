"""Tests para detect_properties_references (v0.19.0)."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.legacy_analyzer import (
    PropertiesReference,
    _detect_specific_file_from_propiedad_java,
    _infer_specific_file_from_root_name,
    _resolve_specific_properties_file,
    detect_properties_references,
)


def _mk_java(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_detects_propiedad_get_as_pending(tmp_path: Path) -> None:
    """Propiedad.get("KEY") -> .properties especifico del UMP pendiente."""
    ump_root = tmp_path / "ump-umptecnicos0023-was"
    _mk_java(
        ump_root / "src" / "main" / "java" / "Constantes.java",
        """
        public class Constantes {
            public static final String URL_XML = Propiedad.get("URL_XML");
            public static final String RECURSO = Propiedad.get("RECURSO");
            public static final String COMPONENTE = Propiedad.get("COMPONENTE");
        }
        """,
    )
    refs = detect_properties_references([ump_root])
    # Debe haber 1 archivo detectado: umptecnicos0023.properties
    specific = [r for r in refs if r.file_name == "umptecnicos0023.properties"]
    assert len(specific) == 1
    entry = specific[0]
    assert entry.status == "PENDING_FROM_BANK"
    assert entry.source_hint == "ump:umptecnicos0023"
    assert set(entry.keys_used) == {"URL_XML", "RECURSO", "COMPONENTE"}


def test_propiedad_getGenerico_goes_to_shared_catalog(tmp_path: Path) -> None:
    """getGenerico("KEY") -> generalservices.properties (SHARED_CATALOG)."""
    ump_root = tmp_path / "ump-umpclientes0023-was"
    _mk_java(
        ump_root / "Constantes.java",
        """
        public static final String COD_OK = Propiedad.getGenerico("OMNI_COD_SERVICIO_OK");
        public static final String COD_FATAL = Propiedad.getGenerico("OMNI_COD_FATAL");
        """,
    )
    refs = detect_properties_references([ump_root])
    shared = [r for r in refs if r.file_name.lower() == "generalservices.properties"]
    assert len(shared) == 1
    assert shared[0].status == "SHARED_CATALOG"
    assert "OMNI_COD_SERVICIO_OK" in shared[0].keys_used
    assert "OMNI_COD_FATAL" in shared[0].keys_used


def test_propiedad_getCatalogo_goes_to_shared_catalog(tmp_path: Path) -> None:
    """getCatalogo("KEY") -> catalogoaplicaciones.properties (SHARED_CATALOG)."""
    ump_root = tmp_path / "ump-ump0001-was"
    _mk_java(
        ump_root / "Constantes.java",
        """
        public static final String BACKEND = Propiedad.getCatalogo("MIDDLEWARE_INTEGRACION_TECNICO_WAS");
        """,
    )
    refs = detect_properties_references([ump_root])
    shared = [r for r in refs if r.file_name.lower() == "catalogoaplicaciones.properties"]
    assert len(shared) == 1
    assert shared[0].status == "SHARED_CATALOG"
    assert "MIDDLEWARE_INTEGRACION_TECNICO_WAS" in shared[0].keys_used


def test_literal_path_identifies_file_name(tmp_path: Path) -> None:
    """RUTA_X = "/apps/proy/.../foo.properties" -> detecta foo.properties."""
    ump_root = tmp_path / "ump-umpfoo0001-was"
    _mk_java(
        ump_root / "Propiedad.java",
        '''
        private static final String RUTA_ESPECIFICA =
            "/apps/proy/OMNICANALIDAD_SERVICIOS/conf/umpfoo0001.properties";
        ''',
    )
    refs = detect_properties_references([ump_root])
    names = {r.file_name for r in refs}
    assert "umpfoo0001.properties" in names


def test_sample_in_repo_extracts_values(tmp_path: Path) -> None:
    """Si existe el .properties en el repo, extraer valores y marcar SAMPLE_IN_REPO."""
    ump_root = tmp_path / "ump-umpbar0002-was"
    # Referencia en codigo
    _mk_java(
        ump_root / "Constantes.java",
        'String x = Propiedad.get("URL_XML");',
    )
    # Sample del properties
    props_path = ump_root / "src" / "main" / "resources" / "umpbar0002.properties"
    props_path.parent.mkdir(parents=True, exist_ok=True)
    props_path.write_text(
        "URL_XML=/apps/proy/config/bar.xml\nRECURSO=RECURSO_X\n",
        encoding="utf-8",
    )

    refs = detect_properties_references([ump_root])
    specific = [r for r in refs if r.file_name == "umpbar0002.properties"]
    assert len(specific) == 1
    entry = specific[0]
    assert entry.status == "SAMPLE_IN_REPO"
    assert entry.sample_values.get("URL_XML") == "/apps/proy/config/bar.xml"
    assert entry.sample_values.get("RECURSO") == "RECURSO_X"


def test_shared_catalog_literal_path_is_excluded_from_pending(tmp_path: Path) -> None:
    """Path literal a generalservices.properties -> SHARED_CATALOG, no PENDING."""
    root = tmp_path / "legacy"
    _mk_java(
        root / "Propiedad.java",
        '''
        private static final String RUTA_GENERICA =
            "/apps/proy/OMNICANALIDAD_SERVICIOS/conf/generalServices.properties";
        private static final String RUTA_CATALOGOS =
            "/apps/proy/OMNICANALIDAD_SERVICIOS/conf/CatalogoAplicaciones.properties";
        ''',
    )
    refs = detect_properties_references([root])
    shared = [r for r in refs if r.status == "SHARED_CATALOG"]
    pending = [r for r in refs if r.status == "PENDING_FROM_BANK"]
    names_shared = {r.file_name.lower() for r in shared}
    assert "generalservices.properties" in names_shared
    assert "catalogoaplicaciones.properties" in names_shared
    assert not pending


def test_no_references_returns_empty(tmp_path: Path) -> None:
    """Sin patterns Propiedad.* en el codigo, devuelve lista vacia."""
    root = tmp_path / "legacy"
    _mk_java(root / "Foo.java", "public class Foo {}")
    refs = detect_properties_references([root])
    assert refs == []


def test_multiple_ump_roots_merge_correctly(tmp_path: Path) -> None:
    """Con 2 UMPs referenciando cada uno su properties, se detectan ambos."""
    ump1 = tmp_path / "ump-umptecnicos0023-was"
    ump2 = tmp_path / "ump-umpclientes0045-was"
    _mk_java(ump1 / "A.java", 'String x = Propiedad.get("K1");')
    _mk_java(ump2 / "B.java", 'String y = Propiedad.get("K2");')

    refs = detect_properties_references([ump1, ump2])
    names = {r.file_name for r in refs if r.status == "PENDING_FROM_BANK"}
    assert "umptecnicos0023.properties" in names
    assert "umpclientes0045.properties" in names


def test_output_is_sorted_shared_then_pending(tmp_path: Path) -> None:
    """Resultado ordenado: SHARED_CATALOG primero, luego SAMPLE, luego PENDING."""
    root = tmp_path / "ump-umptecnicos0023-was"
    _mk_java(
        root / "A.java",
        '''
        String a = Propiedad.get("K1");
        String b = Propiedad.getGenerico("OMNI_COD_FATAL");
        ''',
    )
    refs = detect_properties_references([root])
    statuses = [r.status for r in refs]
    # generalservices antes que umptecnicos0023
    assert statuses.index("SHARED_CATALOG") < statuses.index("PENDING_FROM_BANK")


def test_resource_bundle_pattern_also_detected(tmp_path: Path) -> None:
    """ResourceBundle.getBundle("nombre") tambien se detecta."""
    root = tmp_path / "legacy"
    _mk_java(
        root / "A.java",
        'ResourceBundle bundle = ResourceBundle.getBundle("customConfig");',
    )
    refs = detect_properties_references([root])
    names = {r.file_name for r in refs}
    assert "customConfig.properties" in names


def test_dataclass_defaults() -> None:
    p = PropertiesReference(file_name="foo.properties", status="PENDING_FROM_BANK")
    assert p.file_name == "foo.properties"
    assert p.keys_used == []
    assert p.sample_values == {}
    assert p.referenced_from == []


# ---------------------------------------------------------------------------
# v0.20.2 - WAS principal tambien se detecta (no solo UMPs)
# ---------------------------------------------------------------------------


def test_was_principal_detects_its_own_properties(tmp_path: Path) -> None:
    """Bug v0.19.0: WAS principal (ws-<svc>-was) no tenia 'ump' en el nombre
    y las Propiedad.get("K") del codigo del servicio se descartaban.

    Ahora debe detectar wsclientes0076.properties via heuristica de root.
    """
    was_root = tmp_path / "ws-wsclientes0076-was"
    _mk_java(
        was_root / "wsclientes0076-aplicacion" / "Constantes.java",
        """
        public static final String URL_SERVICIO = Propiedad.get("URL_SERVICIO");
        public static final String TIMEOUT = Propiedad.get("TIMEOUT");
        """,
    )
    refs = detect_properties_references([was_root])
    specific = [r for r in refs if r.file_name == "wsclientes0076.properties"]
    assert len(specific) == 1, (
        "El WAS principal tambien debe detectar sus propias Propiedad.get() - "
        f"refs encontradas: {[r.file_name for r in refs]}"
    )
    entry = specific[0]
    assert entry.status == "PENDING_FROM_BANK"
    assert entry.source_hint == "service"
    assert set(entry.keys_used) == {"URL_SERVICIO", "TIMEOUT"}


def test_was_principal_plus_ump_detects_both(tmp_path: Path) -> None:
    """Flow real: WAS principal + UMP, cada uno con su propio .properties."""
    was_root = tmp_path / "ws-wsclientes0076-was"
    ump_root = tmp_path / "ump-umptecnicos0023-was"

    _mk_java(
        was_root / "wsclientes0076-aplicacion" / "Servicio.java",
        'String x = Propiedad.get("TIMEOUT");',
    )
    _mk_java(
        ump_root / "umptecnicos0023-core" / "Constantes.java",
        'String y = Propiedad.get("URL_XML");',
    )

    refs = detect_properties_references([was_root, ump_root])
    pending = [r for r in refs if r.status == "PENDING_FROM_BANK"]
    names = {r.file_name for r in pending}
    # Ambos archivos se detectan por separado
    assert "wsclientes0076.properties" in names
    assert "umptecnicos0023.properties" in names


def test_propiedad_java_takes_priority_over_root_name(tmp_path: Path) -> None:
    """Si Propiedad.java dice RUTA_ESPECIFICA = "/apps/.../foobar.properties",
    el detector debe usar ese nombre (fuente de verdad), no el del root."""
    root = tmp_path / "ws-wsclientes0076-was"
    # Propiedad.java dice otra cosa
    _mk_java(
        root / "src" / "Propiedad.java",
        '''
        private static final String RUTA_ESPECIFICA =
            "/apps/proy/OMNICANALIDAD_SERVICIOS/conf/servicioCustom.properties";
        ''',
    )
    _mk_java(
        root / "src" / "Uses.java",
        'String a = Propiedad.get("SOME_KEY");',
    )

    refs = detect_properties_references([root])
    names = {r.file_name for r in refs if r.status == "PENDING_FROM_BANK"}
    # Debe usar servicioCustom.properties, NO wsclientes0076.properties
    assert "servicioCustom.properties" in names
    # Las keys estan asociadas al archivo correcto
    custom = next(r for r in refs if r.file_name == "servicioCustom.properties")
    assert "SOME_KEY" in custom.keys_used


def test_ms_prefix_root_resolves() -> None:
    """ms-<svc>-was (variante WAS) tambien resuelve heuristicamente."""
    name = _infer_specific_file_from_root_name(Path("ms-wsclientes0076-was"))
    assert name == "wsclientes0076.properties"


def test_sqb_msa_prefix_root_resolves() -> None:
    """sqb-msa-<svc> (IIB) tambien resuelve heuristicamente."""
    name = _infer_specific_file_from_root_name(Path("sqb-msa-wsclientes0006"))
    assert name == "wsclientes0006.properties"


def test_unknown_root_name_returns_none() -> None:
    """Root que no matchea ningun pattern conocido devuelve None."""
    name = _infer_specific_file_from_root_name(Path("random-folder-name"))
    assert name is None


def test_resolve_falls_back_to_root_when_no_propiedad_java(tmp_path: Path) -> None:
    """Sin Propiedad.java, cae al resolver por nombre de root."""
    root = tmp_path / "ws-wsclientes0076-was"
    root.mkdir()
    file_name, hint = _resolve_specific_properties_file(root)
    assert file_name == "wsclientes0076.properties"
    assert hint == "service"


def test_resolve_reads_propiedad_java_when_present(tmp_path: Path) -> None:
    """Con Propiedad.java, lo usa como fuente de verdad."""
    root = tmp_path / "ws-wsclientes0076-was"
    _mk_java(
        root / "Propiedad.java",
        '''
        private static final String RUTA_ESPECIFICA =
            "/apps/proy/OMNICANALIDAD_SERVICIOS/conf/override.properties";
        ''',
    )
    file_name, hint = _resolve_specific_properties_file(root)
    assert file_name == "override.properties"
    # No empieza con "ump", asi que source es "service"
    assert hint == "service"


def test_resolve_ump_via_propiedad_java(tmp_path: Path) -> None:
    """Si RUTA_ESPECIFICA apunta a ump*.properties, hint es ump:<name>."""
    root = tmp_path / "ump-umptecnicos0023-was"
    _mk_java(
        root / "Propiedad.java",
        '''
        private static final String RUTA_ESPECIFICA =
            "/apps/proy/OMNICANALIDAD_SERVICIOS/conf/umptecnicos0023.properties";
        ''',
    )
    file_name, hint = _resolve_specific_properties_file(root)
    assert file_name == "umptecnicos0023.properties"
    assert hint == "ump:umptecnicos0023"


def test_propiedad_java_detector_returns_none_when_not_found(tmp_path: Path) -> None:
    """Si no hay Propiedad.java en el root, devuelve None (no crashea)."""
    root = tmp_path / "empty-root"
    root.mkdir()
    assert _detect_specific_file_from_propiedad_java(root) is None


def test_propiedad_java_without_ruta_especifica(tmp_path: Path) -> None:
    """Propiedad.java existe pero sin RUTA_ESPECIFICA -> None."""
    root = tmp_path / "ws-wsclientes0076-was"
    _mk_java(
        root / "Propiedad.java",
        'public class Propiedad { /* no RUTA_ESPECIFICA here */ }',
    )
    assert _detect_specific_file_from_propiedad_java(root) is None
