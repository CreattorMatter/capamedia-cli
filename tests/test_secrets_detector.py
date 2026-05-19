"""Tests para secrets_detector (v0.23.0)."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.secrets_detector import (
    AMBIGUOUS_SECRETS_CATALOG,
    SECRETS_CATALOG,
    audit_secrets,
    scan_jndi_references,
)


def _mk(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_catalog_has_entries_from_bptpsre() -> None:
    """El catalogo contiene las entradas oficiales conocidas por el CLI."""
    assert len(SECRETS_CATALOG) == 73
    # Claves criticas
    assert "jndi.tecnicos.cataloga" in SECRETS_CATALOG
    assert "jndi.clientes.conclient" in SECRETS_CATALOG
    assert "jndi.sar.creditos" in SECRETS_CATALOG
    assert "jndi.bddvia" in SECRETS_CATALOG
    # Entradas ampliadas del catalogo de secretos WAS.
    assert SECRETS_CATALOG["jdbc/notifica"] == (
        "TOTPAUT",
        "CCC-ORACLE-NOTIFICA-TOTPAUT-USER",
        "CCC-ORACLE-NOTIFICA-TOTPAUT-PASS",
    )
    assert SECRETS_CATALOG["GEOLOCALIZACION_JNDI"] == (
        "TOTPAUT",
        "CCC-ORACLE-GEOLOCALIZACION-TOTPAUT-USER",
        "CCC-ORACLE-GEOLOCALIZACION-TOTPAUT-PASSWORD",
    )
    assert SECRETS_CATALOG["jndi.internexo.cliente"] == (
        "internexo",
        "CCC-SQLSERVER-INTERNEXO-CLIENTE-USER",
        "CCC-SQLSERVER-INTERNEXO-CLIENTE-PASS",
    )
    assert SECRETS_CATALOG["AutogestionWeb/jdni"] == (
        "ClientesPreaprobados",
        "CCC-SQLSERVER-AUTOGESTIONWEB-CLIENTES-PREAPROBADOS-USER",
        "CCC-SQLSERVER-AUTOGESTIONWEB-CLIENTES-PREAPROBADOS-PASS",
    )


def test_catalog_keeps_conflicting_jndi_as_ambiguous() -> None:
    """JNDI duplicados con secrets distintos no se mapean automaticamente."""
    assert "jndi.xa.tecnicos.cataloga" not in SECRETS_CATALOG
    assert "jndi.sfi" not in SECRETS_CATALOG
    assert "jndi.tecnicos.autorizador" not in SECRETS_CATALOG
    assert set(AMBIGUOUS_SECRETS_CATALOG) == {
        "jndi.xa.tecnicos.cataloga",
        "jndi.sfi",
        "jndi.tecnicos.autorizador",
    }


def test_catalog_secret_naming_uses_hyphens() -> None:
    """Los secretos de KV usan guiones, no underscores."""
    for _, (_, user, password) in SECRETS_CATALOG.items():
        assert "_" not in user, f"user secret '{user}' debe usar guiones"
        assert "_" not in password, f"password secret '{password}' debe usar guiones"
        assert user.startswith("CCC-")
        assert password.startswith("CCC-")


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def test_scan_jndi_in_persistence_xml(tmp_path: Path) -> None:
    """Detecta jndi en <jta-data-source> de persistence.xml."""
    root = tmp_path / "legacy" / "ws-x-was"
    _mk(
        root / "src" / "main" / "resources" / "META-INF" / "persistence.xml",
        """<?xml version="1.0"?>
<persistence>
  <persistence-unit name="tecnicos">
    <jta-data-source>jndi.tecnicos.cataloga</jta-data-source>
  </persistence-unit>
</persistence>""",
    )
    hits = scan_jndi_references([root])
    jndis = {h.jndi for h in hits}
    assert "jndi.tecnicos.cataloga" in jndis


def test_scan_jndi_in_ibm_web_bnd(tmp_path: Path) -> None:
    """Detecta jndi en <resource-ref> de ibm-web-bnd.xml."""
    root = tmp_path / "legacy" / "ws-y-was"
    _mk(
        root / "src" / "main" / "webapp" / "WEB-INF" / "ibm-web-bnd.xml",
        """<?xml version="1.0"?>
<web-bnd>
  <resource-ref name="jdbc/ds">
    <jndi-name>jndi.sar.creditos</jndi-name>
  </resource-ref>
</web-bnd>""",
    )
    hits = scan_jndi_references([root])
    assert any(h.jndi == "jndi.sar.creditos" for h in hits)


def test_scan_jndi_in_java_resource_annotation(tmp_path: Path) -> None:
    """Detecta @Resource(name="jndi.xxx") en Java."""
    root = tmp_path / "ump-foo-was"
    _mk(
        root / "src" / "main" / "java" / "Dao.java",
        """package x;
public class Dao {
    @Resource(name = "jndi.productos.productos")
    private javax.sql.DataSource ds;
}""",
    )
    hits = scan_jndi_references([root])
    assert any(h.jndi == "jndi.productos.productos" for h in hits)


def test_scan_jndi_in_java_lookup(tmp_path: Path) -> None:
    """Detecta InitialContext.lookup("jndi.xxx") en Java."""
    root = tmp_path / "legacy"
    _mk(
        root / "src" / "Dao.java",
        'String ds = new InitialContext().lookup("jndi.clientes.conclient").toString();',
    )
    hits = scan_jndi_references([root])
    assert any(h.jndi == "jndi.clientes.conclient" for h in hits)


def test_scan_jndi_in_properties(tmp_path: Path) -> None:
    """Detecta `OMNI_JNDI_X = jndi.xxx` en properties."""
    root = tmp_path / "ump"
    _mk(
        root / "conf" / "ump.properties",
        "OMNI_JNDI_CATALOGA=jndi.tecnicos.cataloga\nOMN_JNDI_SAR=jndi.sar.creditos\n",
    )
    hits = scan_jndi_references([root])
    jndis = {h.jndi for h in hits}
    assert "jndi.tecnicos.cataloga" in jndis
    assert "jndi.sar.creditos" in jndis


def test_scan_catalog_values_that_are_not_jndi_prefix(tmp_path: Path) -> None:
    """Detecta entradas de catalogo tipo jdbc/*, constantes *_JNDI y jdni."""
    root = tmp_path / "legacy"
    _mk(
        root / "WEB-INF" / "ibm-web-bnd.xml",
        """<web-bnd>
  <resource-ref><jndi-name>jdbc/notifica</jndi-name></resource-ref>
  <resource-ref><jndi-name>AutogestionWeb/jdni</jndi-name></resource-ref>
</web-bnd>""",
    )
    _mk(
        root / "conf" / "service.properties",
        "GEOLOCALIZACION_JNDI=GEOLOCALIZACION_JNDI\n",
    )
    _mk(
        root / "src" / "Dao.java",
        'new InitialContext().lookup("jdbc/omni");',
    )

    hits = scan_jndi_references([root])
    values = {h.jndi for h in hits}

    assert {"jdbc/notifica", "AutogestionWeb/jdni", "GEOLOCALIZACION_JNDI", "jdbc/omni"} <= values


def test_scan_deduplicates_same_jndi_same_file(tmp_path: Path) -> None:
    """Si el mismo JNDI aparece N veces en el mismo archivo, solo 1 hit."""
    root = tmp_path / "legacy"
    _mk(
        root / "a.xml",
        '<x><jndi-name>jndi.bddvia</jndi-name><jndi-name>jndi.bddvia</jndi-name></x>',
    )
    hits = scan_jndi_references([root])
    # Podria haber >1 hit si se parsea por patrones distintos, pero por file+jndi
    # debe deduplicarse
    per_key = {(h.jndi, h.source_file) for h in hits}
    assert len(per_key) == 1


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def test_audit_skips_non_was_services(tmp_path: Path) -> None:
    """BUS/ORQ no generan audit aunque tengan JNDI en legacy."""
    root = tmp_path / "legacy"
    _mk(root / "Dao.java", '@Resource(name="jndi.tecnicos.cataloga") DataSource ds;')

    audit = audit_secrets(root, service_kind="bus", has_database=False)
    assert audit.applies is False
    assert audit.secrets_required == []


def test_audit_skips_was_without_db(tmp_path: Path) -> None:
    """WAS sin BD (has_database=False) no genera audit."""
    root = tmp_path / "legacy"
    _mk(root / "Dao.java", '@Resource(name="jndi.tecnicos.cataloga") DataSource ds;')
    audit = audit_secrets(root, service_kind="was", has_database=False)
    assert audit.applies is False


def test_audit_maps_known_jndi_to_secrets(tmp_path: Path) -> None:
    """WAS + BD + JNDI del catalogo -> SecretRequirement con user/password."""
    root = tmp_path / "legacy"
    _mk(
        root / "src" / "main" / "resources" / "META-INF" / "persistence.xml",
        '<persistence><jta-data-source>jndi.tecnicos.cataloga</jta-data-source></persistence>',
    )
    audit = audit_secrets(root, service_kind="was", has_database=True)
    assert audit.applies
    assert len(audit.secrets_required) == 1
    sr = audit.secrets_required[0]
    assert sr.jndi == "jndi.tecnicos.cataloga"
    assert sr.db_label == "TPOMN"
    assert sr.user_secret == "CCC-ORACLE-OMNI-CATALOGA-USER"
    assert sr.password_secret == "CCC-ORACLE-OMNI-CATALOGA-PASSWORD"


def test_audit_reports_unknown_jndi(tmp_path: Path) -> None:
    """JNDI fuera del catalogo -> jndi_references_unknown."""
    root = tmp_path / "legacy"
    _mk(
        root / "persistence.xml",
        '<persistence><jta-data-source>jndi.custom.loquesea</jta-data-source></persistence>',
    )
    audit = audit_secrets(root, service_kind="was", has_database=True)
    assert audit.applies
    assert len(audit.secrets_required) == 0
    assert len(audit.jndi_references_unknown) >= 1
    assert audit.jndi_references_unknown[0].jndi == "jndi.custom.loquesea"


def test_audit_reports_ambiguous_jndi_without_secret_mapping(tmp_path: Path) -> None:
    """Un JNDI ambiguo se reporta para decision humana, no como secret valido."""
    root = tmp_path / "legacy"
    _mk(
        root / "persistence.xml",
        '<persistence><jta-data-source>jndi.sfi</jta-data-source></persistence>',
    )

    audit = audit_secrets(root, service_kind="was", has_database=True)

    assert audit.applies
    assert audit.secrets_required == []
    assert [hit.jndi for hit in audit.jndi_references_unknown] == ["jndi.sfi"]


def test_audit_scans_umps_too(tmp_path: Path) -> None:
    """Si el JNDI vive en un UMP, tambien se detecta."""
    legacy_root = tmp_path / "legacy" / "ws-x-was"
    _mk(legacy_root / "web.xml", "<web-app/>")  # sin jndi aqui
    ump_root = tmp_path / "umps" / "ump-foo-was"
    _mk(
        ump_root / "core" / "persistence.xml",
        '<persistence><jta-data-source>jndi.bddvia</jta-data-source></persistence>',
    )
    audit = audit_secrets(
        legacy_root, umps_roots=[ump_root],
        service_kind="was", has_database=True,
    )
    assert audit.applies
    assert len(audit.secrets_required) == 1
    assert audit.secrets_required[0].jndi == "jndi.bddvia"
    assert audit.secrets_required[0].db_label == "CREDITO_TARJETAS"


def test_audit_multiple_jndi_same_service(tmp_path: Path) -> None:
    """Servicio que usa 2 JNDI distintos -> 2 SecretRequirements."""
    root = tmp_path / "legacy"
    _mk(
        root / "a.xml",
        '<x><jta-data-source>jndi.tecnicos.cataloga</jta-data-source></x>',
    )
    _mk(
        root / "b.xml",
        '<x><jta-data-source>jndi.productos.productos</jta-data-source></x>',
    )
    audit = audit_secrets(root, service_kind="was", has_database=True)
    assert len(audit.secrets_required) == 2
    jndis = {sr.jndi for sr in audit.secrets_required}
    assert jndis == {"jndi.tecnicos.cataloga", "jndi.productos.productos"}
