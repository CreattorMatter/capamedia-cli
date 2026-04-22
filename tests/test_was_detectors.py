"""Tests para los detectores WAS-specific: WSDL sin prefijo wsdl:,
UMPs en pom.xml y UMPs en Java imports.

Caso real: wstecnicos0008. WSDL en webapp/WEB-INF/wsdl/ con
`<operation name="X">` sin prefix `wsdl:`. UMP declarada como Maven
dependency + imports Java `com.pichincha.tecnicos.umptecnicos0023.pojo.*`.
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.legacy_analyzer import (
    analyze_legacy,
    analyze_wsdl,
    detect_ump_references_was,
    find_wsdl,
)


# ---------------------------------------------------------------------------
# WSDL sin prefijo wsdl:
# ---------------------------------------------------------------------------


_WSDL_WITHOUT_PREFIX = """<?xml version="1.0" encoding="UTF-8"?>
<definitions name="WSTecnicos0008Request"
    targetNamespace="http://bpichincha.com/servicios"
    xmlns="http://schemas.xmlsoap.org/wsdl/"
    xmlns:tns="http://bpichincha.com/servicios">
  <message name="ConsultarAtributosTransaccion01"/>
  <message name="ConsultarAtributosTransaccion01Response"/>
  <portType name="WSTecnicos0008">
    <operation name="ConsultarAtributosTransaccion01">
      <input message="tns:ConsultarAtributosTransaccion01"/>
      <output message="tns:ConsultarAtributosTransaccion01Response"/>
    </operation>
    <operation name="ConsultarAtributosTransaccion02">
      <input message="tns:ConsultarAtributosTransaccion02"/>
      <output message="tns:ConsultarAtributosTransaccion02Response"/>
    </operation>
  </portType>
</definitions>
"""

_WSDL_WITH_PREFIX = """<?xml version="1.0" encoding="UTF-8"?>
<wsdl:definitions name="WSClientes0007Request"
    xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">
  <wsdl:portType name="WSClientes0007">
    <wsdl:operation name="ConsultarContactoTransaccional01"/>
  </wsdl:portType>
</wsdl:definitions>
"""


def test_wsdl_without_wsdl_prefix_parsed(tmp_path: Path) -> None:
    """Caso wstecnicos0008: <operation> sin prefix wsdl: debe contarse."""
    wsdl = tmp_path / "svc.wsdl"
    wsdl.write_text(_WSDL_WITHOUT_PREFIX, encoding="utf-8")

    info = analyze_wsdl(wsdl)
    assert info.operation_count == 2
    assert "ConsultarAtributosTransaccion01" in info.operation_names
    assert "ConsultarAtributosTransaccion02" in info.operation_names


def test_wsdl_with_wsdl_prefix_still_parsed(tmp_path: Path) -> None:
    """Caso wsclientes0007: <wsdl:operation> sigue funcionando (regresion)."""
    wsdl = tmp_path / "svc.wsdl"
    wsdl.write_text(_WSDL_WITH_PREFIX, encoding="utf-8")

    info = analyze_wsdl(wsdl)
    assert info.operation_count == 1
    assert "ConsultarContactoTransaccional01" in info.operation_names


# ---------------------------------------------------------------------------
# WSDL en webapp/WEB-INF/wsdl/ (WAS path)
# ---------------------------------------------------------------------------


def test_find_wsdl_in_webapp_path(tmp_path: Path) -> None:
    """El WSDL de un WAS vive en `webapp/WEB-INF/wsdl/` — no en `src/main/resources`."""
    web_wsdl = tmp_path / "svc-infra" / "src" / "main" / "webapp" / "WEB-INF" / "wsdl"
    web_wsdl.mkdir(parents=True)
    (web_wsdl / "Svc.wsdl").write_text(_WSDL_WITHOUT_PREFIX, encoding="utf-8")

    found = find_wsdl(tmp_path)
    assert found is not None
    assert found.name == "Svc.wsdl"


# ---------------------------------------------------------------------------
# UMP en pom.xml (Maven dependency)
# ---------------------------------------------------------------------------


def test_ump_detected_in_pom_xml(tmp_path: Path) -> None:
    pom = tmp_path / "pom.xml"
    pom.write_text(
        """<?xml version="1.0"?>
<project>
  <dependencies>
    <dependency>
      <groupId>com.pichincha.tecnicos</groupId>
      <artifactId>umptecnicos0023-core-dominio</artifactId>
      <version>1.0.0-RC1</version>
    </dependency>
    <dependency>
      <groupId>com.pichincha.tecnicos</groupId>
      <artifactId>umptecnicos0023-dominio</artifactId>
      <version>1.0.0-RC1</version>
    </dependency>
  </dependencies>
</project>
""",
        encoding="utf-8",
    )
    umps = detect_ump_references_was(tmp_path)
    assert umps == ["umptecnicos0023"]  # dedup del suffix -core-dominio / -dominio


def test_ump_detected_in_java_imports(tmp_path: Path) -> None:
    java_dir = tmp_path / "src" / "main" / "java" / "com" / "pichincha" / "tecnicos"
    java_dir.mkdir(parents=True)
    (java_dir / "Svc.java").write_text(
        "package com.pichincha.tecnicos;\n\n"
        "import com.pichincha.tecnicos.umptecnicos0023.logica.AtributosTransaccionServicio;\n"
        "import com.pichincha.tecnicos.umptecnicos0023.pojo.EAtributosTransaccion;\n"
        "import com.pichincha.util.exception.ServicioExcepcion;\n\n"
        "public class Svc { }\n",
        encoding="utf-8",
    )
    umps = detect_ump_references_was(tmp_path)
    assert umps == ["umptecnicos0023"]


def test_ump_not_detected_in_esql(tmp_path: Path) -> None:
    """detect_ump_references_was no debe mirar ESQL (eso es IIB)."""
    (tmp_path / "module.esql").write_text(
        "CALL UMPClientes0002.doStuff();\n",
        encoding="utf-8",
    )
    umps = detect_ump_references_was(tmp_path)
    assert umps == []


def test_ump_detected_combining_pom_and_java(tmp_path: Path) -> None:
    """Si una UMP aparece en pom.xml y en imports Java, se cuenta una sola vez."""
    (tmp_path / "pom.xml").write_text(
        '<project><dependencies>'
        '<dependency><artifactId>umpclientes0010-dominio</artifactId></dependency>'
        '</dependencies></project>',
        encoding="utf-8",
    )
    java_dir = tmp_path / "src"
    java_dir.mkdir()
    (java_dir / "Svc.java").write_text(
        "import com.pichincha.clientes.umpclientes0010.pojo.Foo;\n",
        encoding="utf-8",
    )
    umps = detect_ump_references_was(tmp_path)
    assert umps == ["umpclientes0010"]


def test_ump_multiple_distinct(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text(
        '<project><dependencies>'
        '<dependency><artifactId>umpclientes0010-dominio</artifactId></dependency>'
        '<dependency><artifactId>umptecnicos0023-core-dominio</artifactId></dependency>'
        '<dependency><artifactId>umpseguridad0005</artifactId></dependency>'
        '</dependencies></project>',
        encoding="utf-8",
    )
    umps = detect_ump_references_was(tmp_path)
    assert umps == ["umpclientes0010", "umpseguridad0005", "umptecnicos0023"]


# ---------------------------------------------------------------------------
# analyze_legacy integracion: WAS con UMPs + WSDL en webapp
# ---------------------------------------------------------------------------


def test_analyze_legacy_was_finds_everything(tmp_path: Path) -> None:
    """Caso wstecnicos0008: WSDL en webapp/WEB-INF/wsdl/ + UMP en pom + Java.
    Debe detectar las 2 ops y la UMP."""
    # Estructura WAS real
    aplicacion = tmp_path / "svc-aplicacion"
    infra = tmp_path / "svc-infra"

    # aplicacion/ con Java que importa UMP
    java_dir = aplicacion / "src" / "main" / "java" / "com" / "pichincha" / "tecnicos"
    java_dir.mkdir(parents=True)
    (java_dir / "Bean.java").write_text(
        "package com.pichincha.tecnicos;\n"
        "import com.pichincha.tecnicos.umptecnicos0023.pojo.E;\n"
        "public class Bean {}\n",
        encoding="utf-8",
    )
    (aplicacion / "pom.xml").write_text(
        '<project><dependencies>'
        '<dependency><artifactId>umptecnicos0023-dominio</artifactId></dependency>'
        '</dependencies></project>',
        encoding="utf-8",
    )

    # infra/ con WSDL + web.xml
    web_inf = infra / "src" / "main" / "webapp" / "WEB-INF"
    web_inf.mkdir(parents=True)
    (web_inf / "web.xml").write_text(
        "<web-app><servlet/></web-app>", encoding="utf-8"
    )
    wsdl_dir = web_inf / "wsdl"
    wsdl_dir.mkdir()
    (wsdl_dir / "Svc.wsdl").write_text(_WSDL_WITHOUT_PREFIX, encoding="utf-8")

    analysis = analyze_legacy(tmp_path, service_name="wstecnicos0008")
    assert analysis.source_kind == "was"
    assert analysis.wsdl is not None
    assert analysis.wsdl.operation_count == 2
    assert len(analysis.umps) == 1
    assert analysis.umps[0].name == "umptecnicos0023"
