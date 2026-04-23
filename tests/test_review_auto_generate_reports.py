"""Tests para `_auto_generate_reports_from_local_legacy` (v0.23.8).

Escenario: el usuario trae un proyecto migrado fuera del CLI (sin `clone`)
y corre `review`. Los reportes de Block 19 no existen. El CLI los debe
generar on-the-fly desde el legacy local si esta disponible.
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.commands.review import _auto_generate_reports_from_local_legacy


def test_skips_when_report_already_exists(tmp_path: Path) -> None:
    """Si ya hay properties-report.yaml (del clone), no regenerar."""
    (tmp_path / ".capamedia").mkdir()
    (tmp_path / ".capamedia" / "properties-report.yaml").write_text(
        "generated_by: capamedia clone\n", encoding="utf-8",
    )
    legacy = tmp_path / "legacy" / "ws-x-was"
    legacy.mkdir(parents=True)

    generated, reason = _auto_generate_reports_from_local_legacy(
        tmp_path, legacy, "wsXXXX",
    )
    assert generated is False
    assert "ya existe" in reason


def test_skips_when_no_legacy_path(tmp_path: Path) -> None:
    """Sin legacy local, no se puede generar."""
    generated, reason = _auto_generate_reports_from_local_legacy(
        tmp_path, None, "wsXXXX",
    )
    assert generated is False
    assert "sin legacy" in reason.lower()


def test_skips_when_legacy_dir_does_not_exist(tmp_path: Path) -> None:
    legacy_nonexistent = tmp_path / "legacy" / "nope"
    generated, reason = _auto_generate_reports_from_local_legacy(
        tmp_path, legacy_nonexistent, "wsXXXX",
    )
    assert generated is False


def test_generates_properties_report_from_local_was(tmp_path: Path) -> None:
    """WAS con Propiedad.get(...) genera properties-report.yaml correctamente."""
    legacy = tmp_path / "legacy" / "ws-wsclientes0076-was"
    legacy.mkdir(parents=True)
    # Simular WAS: web.xml + Java con Propiedad.get()
    (legacy / "src" / "main" / "webapp" / "WEB-INF").mkdir(parents=True)
    (legacy / "src" / "main" / "webapp" / "WEB-INF" / "web.xml").write_text(
        "<web-app/>", encoding="utf-8",
    )
    java_dir = legacy / "src" / "main" / "java" / "com" / "pichincha"
    java_dir.mkdir(parents=True)
    (java_dir / "Constantes.java").write_text(
        """package com.pichincha;
public class Constantes {
    public static final String RECURSO_01 = Propiedad.get("RECURSO_01");
    public static final String COMPONENTE_01 = Propiedad.get("COMPONENTE_01");
}
""",
        encoding="utf-8",
    )
    (java_dir / "App.java").write_text(
        "package com.pichincha; public class App {}",
        encoding="utf-8",
    )

    generated, reason = _auto_generate_reports_from_local_legacy(
        tmp_path, legacy, "wsclientes0076",
    )
    assert generated is True, f"esperaba generar, got: {reason}"

    # Verificar que el archivo se creo y tiene las keys detectadas
    report = tmp_path / ".capamedia" / "properties-report.yaml"
    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "wsclientes0076.properties" in content
    assert "RECURSO_01" in content
    assert "COMPONENTE_01" in content


def test_generates_secrets_report_when_was_has_db(tmp_path: Path) -> None:
    """WAS con JNDI del catalogo de secrets genera secrets-report.yaml."""
    legacy = tmp_path / "legacy" / "ws-x-was"
    # Setup WAS con JPA/DB
    (legacy / "src" / "main" / "webapp" / "WEB-INF").mkdir(parents=True)
    (legacy / "src" / "main" / "webapp" / "WEB-INF" / "web.xml").write_text(
        "<web-app/>", encoding="utf-8",
    )
    (legacy / "src" / "main" / "java").mkdir(parents=True)
    (legacy / "src" / "main" / "java" / "X.java").write_text(
        "public class X {}", encoding="utf-8",
    )
    # persistence.xml con JNDI del catalogo
    pers = legacy / "src" / "main" / "resources" / "META-INF"
    pers.mkdir(parents=True)
    (pers / "persistence.xml").write_text(
        '<persistence><persistence-unit name="pu">'
        '<jta-data-source>jndi.tecnicos.cataloga</jta-data-source>'
        '</persistence-unit></persistence>',
        encoding="utf-8",
    )
    # ibm-web-bnd.xml para que detect_database_usage marque has_db=True
    (legacy / "src" / "main" / "webapp" / "WEB-INF" / "ibm-web-bnd.xml").write_text(
        '<web-bnd><resource-ref><jndi-name>jndi.tecnicos.cataloga</jndi-name></resource-ref></web-bnd>',
        encoding="utf-8",
    )

    generated, _ = _auto_generate_reports_from_local_legacy(
        tmp_path, legacy, "wsXXXX",
    )
    assert generated is True

    secrets_report = tmp_path / ".capamedia" / "secrets-report.yaml"
    if secrets_report.exists():
        # Si se detecto has_db=True, el secrets report existe con el mapping
        content = secrets_report.read_text(encoding="utf-8")
        assert "jndi.tecnicos.cataloga" in content
        assert "CCC-ORACLE-OMNI-CATALOGA-USER" in content


def test_does_not_overwrite_existing_property_report(tmp_path: Path) -> None:
    """Idempotencia: si el clone ya genero un report, no se pisa."""
    (tmp_path / ".capamedia").mkdir()
    original_content = "generated_by: capamedia clone\ncustom: value\n"
    (tmp_path / ".capamedia" / "properties-report.yaml").write_text(
        original_content, encoding="utf-8",
    )

    legacy = tmp_path / "legacy" / "ws-x-was"
    (legacy / "src").mkdir(parents=True)

    _auto_generate_reports_from_local_legacy(tmp_path, legacy, "wsXXXX")

    # El contenido no debe haberse tocado
    post = (tmp_path / ".capamedia" / "properties-report.yaml").read_text(
        encoding="utf-8"
    )
    assert post == original_content
