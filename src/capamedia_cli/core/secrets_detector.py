"""Secrets detector for WAS with BD (v0.23.0).

Escanea el legacy WAS + sus UMPs buscando referencias a JNDI conocidos, y los
mapea al catalogo oficial de secretos del banco (bank-secrets.md). Genera el
insumo para que `capamedia clone` escriba `.capamedia/secrets-report.yaml`.

Fuente canonica de mapping: BPTPSRE-Secretos (documentacion oficial Lift and Shift).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# Catalogo oficial del banco (BPTPSRE-Secretos).
# key = nombre exacto del JNDI (case-sensitive, como aparece en el legacy)
# value = (db_label, user_secret, password_secret)
SECRETS_CATALOG: dict[str, tuple[str, str, str]] = {
    "jndi.sar.creditos": (
        "DTST",
        "CCC-ORACLE-SAR-CREDITOS-USER",
        "CCC-ORACLE-SAR-CREDITOS-PASSWORD",
    ),
    "jndi.productos.productos": (
        "TPOMN",
        "CCC-ORACLE-OMNI-PRODUCTOS-USER",
        "CCC-ORACLE-OMNI-PRODUCTOS-PASSWORD",
    ),
    "jndi.tecnicos.cataloga": (
        "TPOMN",
        "CCC-ORACLE-OMNI-CATALOGA-USER",
        "CCC-ORACLE-OMNI-CATALOGA-PASSWORD",
    ),
    "jndi.clientes.conclient": (
        "TPOMN",
        "CCC-ORACLE-OMNI-CLIENTE-USER",
        "CCC-ORACLE-OMNI-CLIENTE-PASSWORD",
    ),
    "jndi.bddvia": (
        "CREDITO_TARJETAS",
        "CCC-SQLSERVER-CREDITO-TARJETAS-USER",
        "CCC-SQLSERVER-CREDITO-TARJETAS-PASSWORD",
    ),
    "jndi.clientes.homologacionCRM": (
        "MOTOR_HOMOLOGACION",
        "CCC-SQLSERVER-MOTOR-HOMOLOGACION-USER",
        "CCC-SQLSERVER-MOTOR-HOMOLOGACION-PASSWORD",
    ),
    "jndi.clientes.riesgo.01": (
        "DTST",
        "CCC-ORACLE-SIGLO-RIESGO-USER",
        "CCC-ORACLE-SIGLO-RIESGO-PASSWORD",
    ),
    "jndi.clientes.fnsonlf.01": (
        "M012BAND",
        "CCC-ORACLE-M012BAND-USER",
        "CCC-ORACLE-M012BAND-PASSWORD",
    ),
    "jndi.clientes.repositorio_sitar.01": (
        "REPOSITORIO_SITAR",
        "CCC-SQLSERVER-SITAR-USER",
        "CCC-SQLSERVER-SITAR-PASSWORD",
    ),
    "GEOLOCALIZACION_JNDI": (
        "TOTPAUT",
        "CCC-ORACLE-GEOLOCALIZACION-TOTPAUT-USER",
        "CCC-ORACLE-GEOLOCALIZACION-TOTPAUT-PASSWORD",
    ),
    "jndi.seguridad.autentica": (
        "TPOMN",
        "CCC-ORACLE-SEGURIDAD-AUTENTICA-TPOMN-USER",
        "CCC-ORACLE-SEGURIDAD-AUTENTICA-TPOMN-PASSWORD",
    ),
    "jdbc/notifica": (
        "TOTPAUT",
        "CCC-ORACLE-NOTIFICA-TOTPAUT-USER",
        "CCC-ORACLE-NOTIFICA-TOTPAUT-PASS",
    ),
    "jdbc/omni": (
        "TPOMN",
        "CCC-ORACLE-OMNI-TPOMN-USER",
        "CCC-ORACLE-OMNI-TPOMN-PASS",
    ),
    "jdbc/notificador2": (
        "TOTPNOT",
        "CCC-ORACLE-NOTIFICADOR2-TOTPNOT-USER",
        "CCC-ORACLE-NOTIFICADOR2-TOTPNOT-PASS",
    ),
    "jdbc/notificador": (
        "TOTPNOT",
        "CCC-ORACLE-NOTIFICADOR-TOTPNOT-USER",
        "CCC-ORACLE-NOTIFICADOR-TOTPNOT-PASS",
    ),
    "jndi.productos.cataloga": (
        "TPOMN",
        "CCC-ORACLE-PRODUCTOS-CATALOGA-TPOMN-USER",
        "CCC-ORACLE-PRODUCTOS-CATALOGA-TPOMN-PASS",
    ),
    "jndi.notifier.notificacion": (
        "TOTPAUT",
        "CCC-ORACLE-NOTIFIER-NOTIFICACION-TOTPAUT-USER",
        "CCC-ORACLE-NOTIFIER-NOTIFICACION-TOTPAUT-PASS",
    ),
    "jndi.tecnicos.transacc": (
        "TPOMNLOG",
        "CCC-ORACLE-TECNICOS-TRANSACC-TPOMNLOG-USER",
        "CCC-ORACLE-TECNICOS-TRANSACC-TPOMNLOG-PASS",
    ),
    "jndi.cardholder.tarjetaxperta": (
        "DTST",
        "CCC-ORACLE-CARDHOLDER-TARJETAXPERTA-DTST-USER",
        "CCC-ORACLE-CARDHOLDER-TARJETAXPERTA-DTST-PASS",
    ),
    "jndi.siglo.seguridad": (
        "DTST",
        "CCC-ORACLE-SIGLO-SEGURIDAD-DTST-USER",
        "CCC-ORACLE-SIGLO-SEGURIDAD-DTST-PASS",
    ),
    "jndi.tecnicos.logs002": (
        "TPOMNLOG",
        "CCC-ORACLE-TECNICOS-LOGS002-TPOMNLOG-USER",
        "CCC-ORACLE-TECNICOS-LOGS002-TPOMNLOG-PASS",
    ),
    "jndi.productos.cheqscanCamara": (
        "TPOMN",
        "CCC-ORACLE-PRODUCTOS-CHEQSCANCAMARA-TPOMN-USER",
        "CCC-ORACLE-PRODUCTOS-CHEQSCANCAMARA-TPOMN-PASS",
    ),
    "jndi.clientes.cobrossms": (
        "TOTPNOT",
        "CCC-ORACLE-CLIENTES-COBROSSMS-TOTPNOT-USER",
        "CCC-ORACLE-CLIENTES-COBROSSMS-TOTPNOT-PASS",
    ),
    "jndi.clientes.fnsonlf.01.bac": (
        "M012BAND",
        "CCC-ORACLE-CLIENTES-FNSONLF-01-BAC-M012BAND-USER",
        "CCC-ORACLE-CLIENTES-FNSONLF-01-BAC-M012BAND-PASS",
    ),
    "jndi.bancs.clientes.bac": (
        "M012BAND",
        "CCC-ORACLE-BANCS-CLIENTES-BAC-M012BAND-USER",
        "CCC-ORACLE-BANCS-CLIENTES-BAC-M012BAND-PASS",
    ),
    "jndi.clientes.bpschema.01": (
        "BPBPMD",
        "CCC-ORACLE-CLIENTES-BPSCHEMA-01-BPBPMD-USER",
        "CCC-ORACLE-CLIENTES-BPSCHEMA-01-BPBPMD-PASS",
    ),
    "jndi.productos.riesgo": (
        "DTST",
        "CCC-ORACLE-PRODUCTOS-RIESGO-DTST-USER",
        "CCC-ORACLE-PRODUCTOS-RIESGO-DTST-PASS",
    ),
    "OMNI_ORACLE_14_SIGLO_JNDI": (
        "DTST",
        "CCC-ORACLE-OMNI-14-SIGLO-DTST-USER",
        "CCC-ORACLE-OMNI-14-SIGLO-DTST-PASS",
    ),
    "jdbc/notifier": (
        "TOTPNOT",
        "CCC-ORACLE-NOTIFIER-TOTPNOT-USER",
        "CCC-ORACLE-NOTIFIER-TOTPNOT-PASS",
    ),
    "jdbc/cardHolder": (
        "DTST",
        "CCC-ORACLE-CARDHOLDER-DTST-USER",
        "CCC-ORACLE-CARDHOLDER-DTST-PASS",
    ),
    "jndi.tecnicos": (
        "TPOMN",
        "CCC-ORACLEXA-TECNICOS-TPOMN-USER",
        "CCC-ORACLEXA-TECNICOS-TPOMN-PASS",
    ),
    "jndi.xa.tecnicos.transespera": (
        "TPOMNLOG",
        "CCC-ORACLEXA-TECNICOS-TRANSESPERA-TPOMNLOG-USER",
        "CCC-ORACLEXA-TECNICOS-TRANSESPERA-TPOMNLOG-PASS",
    ),
    "jndi.administracion": (
        "TPOMN",
        "CCC-ORACLEXA-ADMINISTRACION-TPOMN-USER",
        "CCC-ORACLEXA-ADMINISTRACION-TPOMN-PASS",
    ),
    "jndi.catalogo.bancs.bac": (
        "M012BAND",
        "CCC-ORACLEXA-CATALOGO-BANCS-BAC-M012BAND-USER",
        "CCC-ORACLEXA-CATALOGO-BANCS-BAC-M012BAND-PASS",
    ),
    "jndi.catalogo.siglo": (
        "DTST",
        "CCC-ORACLEXA-CATALOGO-SIGLO-DTST-USER",
        "CCC-ORACLEXA-CATALOGO-SIGLO-DTST-PASS",
    ),
    "jndi.administracion.conadmin": (
        "TPOMN",
        "CCC-ORACLEXA-ADMINISTRACION-CONADMIN-TPOMN-USER",
        "CCC-ORACLEXA-ADMINISTRACION-CONADMIN-TPOMN-PASS",
    ),
    "jndi.xa.seguridad.autentica": (
        "TPOMN",
        "CCC-ORACLEXA-SEGURIDAD-AUTENTICA-TPOMN-USER",
        "CCC-ORACLEXA-SEGURIDAD-AUTENTICA-TPOMN-PASS",
    ),
    "jndi.interdin": (
        "TPOMN",
        "CCC-ORACLEXA-INTERDIN-TPOMN-USER",
        "CCC-ORACLEXA-INTERDIN-TPOMN-PASS",
    ),
    "jndi.bancs.clientes": (
        "M012BAND",
        "CCC-ORACLE-BANCS-CLIENTES-M012BAND-USER",
        "CCC-ORACLE-BANCS-CLIENTES-M012BAND-PASS",
    ),
    "jndi.bancs.clientes.reference": (
        "M014BANR_TAF",
        "CCC-ORACLE-BANCS-CLIENTES-REFERENCE-M014BANR-TAF-USER",
        "CCC-ORACLE-BANCS-CLIENTES-REFERENCE-M014BANR-TAF-PASS",
    ),
    "jndi.catalogo.bancs": (
        "M012BAND",
        "CCC-ORACLEXA-CATALOGO-BANCS-M012BAND-USER",
        "CCC-ORACLEXA-CATALOGO-BANCS-M012BAND-PASS",
    ),
    "jndi.homologacion.usuario": (
        "MOTOR_HOMOLOGACION",
        "CCC-SQLSERVER-HOMOLOGACION-USUARIO-MOTOR-HOMOLOGACION-USER",
        "CCC-SQLSERVER-HOMOLOGACION-USUARIO-MOTOR-HOMOLOGACION-PASS",
    ),
    "OMNI_SQLSERVER_INTERNEXO_JNDI": (
        "internexo",
        "CCC-SQLSERVER-OMNI-INTERNEXO-USER",
        "CCC-SQLSERVER-OMNI-INTERNEXO-PASS",
    ),
    "asesores": (
        "Asesores",
        "CCC-SQLSERVER-ASESORES-USER",
        "CCC-SQLSERVER-ASESORES-PASS",
    ),
    "jndi.productos.pdmp": (
        "BDD_PDMP",
        "CCC-SQLSERVER-PRODUCTOS-BDD-PDMP-USER",
        "CCC-SQLSERVER-PRODUCTOS-BDD-PDMP-PASS",
    ),
    "jndi.tecnicos.sentinel_replica.01": (
        "SENTINEL_REPLICA",
        "CCC-SQLSERVER-TECNICOS-SENTINEL-REPLICA-01-USER",
        "CCC-SQLSERVER-TECNICOS-SENTINEL-REPLICA-01-PASS",
    ),
    "jndi.productos.datint": (
        "BDD_INTERCAMBIO_DATA_BPM_BIZAGI",
        "CCC-SQLSERVER-PRODUCTOS-INTERCAMBIO-BPM-BIZAGI-USER",
        "CCC-SQLSERVER-PRODUCTOS-INTERCAMBIO-BPM-BIZAGI-PASS",
    ),
    "jndi.sitar.tarjetacredito": (
        "REPOSITORIO_SITAR",
        "CCC-SQLSERVER-SITAR-TARJETACREDITO-USER",
        "CCC-SQLSERVER-SITAR-TARJETACREDITO-PASS",
    ),
    "jndi.internexo.cliente": (
        "internexo",
        "CCC-SQLSERVER-INTERNEXO-CLIENTE-USER",
        "CCC-SQLSERVER-INTERNEXO-CLIENTE-PASS",
    ),
    "AutogestionWeb/jdni": (
        "ClientesPreaprobados",
        "CCC-SQLSERVER-AUTOGESTIONWEB-CLIENTES-PREAPROBADOS-USER",
        "CCC-SQLSERVER-AUTOGESTIONWEB-CLIENTES-PREAPROBADOS-PASS",
    ),
    "Autogestion/jdni": (
        "AutoGestion",
        "CCC-SQLSERVER-AUTOGESTION-USER",
        "CCC-SQLSERVER-AUTOGESTION-PASS",
    ),
    "jndi.microfinanzas": (
        "MOVILIDADMICRO",
        "CCC-SQLSERVER-MICROFINANZAS-MOVILIDADMICRO-USER",
        "CCC-SQLSERVER-MICROFINANZAS-MOVILIDADMICRO-PASS",
    ),
    "jndi.productos.mdo": (
        "MDO_OFERTAS",
        "CCC-SQLSERVER-PRODUCTOS-MDO-OFERTAS-USER",
        "CCC-SQLSERVER-PRODUCTOS-MDO-OFERTAS-PASS",
    ),
    "jndi.productos.mdoprocesos": (
        "MDO_PROCESOS",
        "CCC-SQLSERVER-PRODUCTOS-MDO-PROCESOS-USER",
        "CCC-SQLSERVER-PRODUCTOS-MDO-PROCESOS-PASS",
    ),
    "jndi.productos.autogestion": (
        "AutoGestion",
        "CCC-SQLSERVER-PRODUCTOS-AUTOGESTION-USER",
        "CCC-SQLSERVER-PRODUCTOS-AUTOGESTION-PASS",
    ),
    "jndi.tecnicos.portal.bac": (
        "M012BAND",
        "CCC-ORACLE-TECNICOS-PORTAL-BAC-M012BAND-USER",
        "CCC-ORACLE-TECNICOS-PORTAL-BAC-M012BAND-PASS",
    ),
    "jndi.clientes.cardholder": (
        "DTST",
        "CCC-ORACLE-CLIENTES-CARDHOLDER-DTST-USER",
        "CCC-ORACLE-CLIENTES-CARDHOLDER-DTST-PASS",
    ),
    "jndi.tecnicos.notificadormsg": (
        "TOTPNOT",
        "CCC-ORACLE-TECNICOS-NOTIFICADORMSG-TOTPNOT-USER",
        "CCC-ORACLE-TECNICOS-NOTIFICADORMSG-TOTPNOT-PASS",
    ),
    "jndi.bddvia.campanias": (
        "ASYNCRONO",
        "CCC-SQLSERVER--VIA-CAMPANIAS-ASYNCRONO-USER",
        "CCC-SQLSERVER--VIA-CAMPANIAS-ASYNCRONO-PASS",
    ),
    "jndi.cleansing.cliente": (
        "CLEANSING",
        "CCC-SQLSERVER-CLEANSING-CLIENTE-USER",
        "CCC-SQLSERVER-CLEANSING-CLIENTE-PASS",
    ),
    "jndi.transferencia.swmt950": (
        "SWMT950",
        "CCC-SQLSERVER-TRANSFERENCIA-SWMT950-USER",
        "CCC-SQLSERVER-TRANSFERENCIA-SWMT950-PASS",
    ),
    "jndi.transferencias.swift": (
        "SWIFT",
        "CCC-SQLSERVER-TRANSFERENCIAS-SWIFT-USER",
        "CCC-SQLSERVER-TRANSFERENCIAS-SWIFT-PASS",
    ),
    "jndi.transferencias.swinquiry": (
        "SWINQUIRY",
        "CCC-SQLSERVER-TRANSFERENCIAS-SWINQUIRY-USER",
        "CCC-SQLSERVER-TRANSFERENCIAS-SWINQUIRY-PASS",
    ),
    "jndi.productos.atm": (
        "ATM",
        "CCC-SQLSERVER-PRODUCTOS-ATM-USER",
        "CCC-SQLSERVER-PRODUCTOS-ATM-PASS",
    ),
    "jndi.clientes.preguntas": (
        "BDDPWA",
        "CCC-SQLSERVER-CLIENTES-PREGUNTAS-PWA-USER",
        "CCC-SQLSERVER-CLIENTES-PREGUNTAS-PWA-PASS",
    ),
    "jndi.tecnicos.workflow": (
        "WorkFlow",
        "CCC-SQLSERVER-TECNICOS-WORKFLOW-USER",
        "CCC-SQLSERVER-TECNICOS-WORKFLOW-PASS",
    ),
    "jndi.pagos": (
        "TPOMN",
        "CCC-ORACLEXA-PAGOS-TPOMN-USER",
        "CCC-ORACLEXA-PAGOS-TPOMN-PASS",
    ),
    "jndi.seguridad.autoriza": (
        "TPOMN",
        "CCC-ORACLEXA-SEGURIDAD-AUTORIZA-TPOMN-USER",
        "CCC-ORACLEXA-SEGURIDAD-AUTORIZA-TPOMN-PASS",
    ),
    "jdbc/botonCredito": (
        "BDD_BOTON_DE_CREDITO",
        "CCC-SQLSERVER-BOTONCREDITO-USER",
        "CCC-SQLSERVER-BOTONCREDITO-PASS",
    ),
    "jndi.clientes.firmas": (
        "Firmas",
        "CCC-SQLSERVER-CLIENTES-FIRMAS-USER",
        "CCC-SQLSERVER-CLIENTES-FIRMAS-PASS",
    ),
    "jndi.tecnicos.controltransaccion": (
        "mysqlUser",
        "CCC-USER-DEF-TECNICOS-CONTROLTRANSACCION-USER",
        "CCC-USER-DEF-TECNICOS-CONTROLTRANSACCION-PASS",
    ),
    "jndi.tecnicos.portal": (
        "M012BAND",
        "CCC-ORACLE-TECNICOS-PORTAL-M012BAND-USER",
        "CCC-ORACLE-TECNICOS-PORTAL-M012BAND-PASS",
    ),
    "jndi.clientes.firmas.pry": (
        "Firmas",
        "CCC-SQLSERVER-CLIENTES-FIRMAS-PRY-FIRMAS-USER",
        "CCC-SQLSERVER-CLIENTES-FIRMAS-PRY-FIRMAS-PASS",
    ),
}


# Duplicados recibidos con secrets distintos. Se detectan, pero NO se mapean a
# un SecretRequirement hasta que SRE/arquitectura confirme cual par usar.
AMBIGUOUS_SECRETS_CATALOG: dict[str, tuple[tuple[str, str, str], ...]] = {
    "jndi.xa.tecnicos.cataloga": (
        (
            "TPOMN",
            "CCC-ORACLE-OMNI-CATALOGA-USER",
            "CCC-ORACLE-OMNI-CATALOGA-PASSWORD",
        ),
        (
            "TPOMN",
            "CCC-ORACLEXA-TECNICOS-CATALOGA-TPOMN-USER",
            "CCC-ORACLEXA-TECNICOS-CATALOGA-TPOMN-PASS",
        ),
    ),
    "jndi.sfi": (
        (
            "CREDIFE",
            "CCC-SQLSERVER-SFI-CREDIFE-USER",
            "CCC-SQLSERVER-SFI-CREDIFE-PASS",
        ),
        (
            "CREDIFE",
            "CCC-SQLSERVER-SFI-USER",
            "CCC-SQLSERVER-SFI-PASS",
        ),
    ),
    "jndi.tecnicos.autorizador": (
        (
            "AUTORIZADOR_PICHINCHA",
            "CCC-SQLSERVER-TECNICOS-AUTORIZADOR-USER",
            "CCC-SQLSERVER-TECNICOS-AUTORIZADOR-PASS",
        ),
        (
            "AUTORIZADOR_PICHINCHA",
            "CCC-SQLSERVER-TECNICOS-AUTORIZADOR-PICHINCHA-USER",
            "CCC-SQLSERVER-TECNICOS-AUTORIZADOR-PICHINCHA-PASS",
        ),
    ),
}


# Patrones de deteccion de JNDI/datasource en distintos formatos del legacy.
_KNOWN_DATASOURCE_NAMES = frozenset(SECRETS_CATALOG) | frozenset(AMBIGUOUS_SECRETS_CATALOG)
_DATASOURCE_PATTERN_GENERIC = re.compile(
    r"\bjndi\.[a-zA-Z][a-zA-Z0-9._]+\b|\bjdbc/[a-zA-Z][a-zA-Z0-9._-]+\b"
)
_JNDI_IN_XML = re.compile(
    r"<(?:jta-data-source|data-source|resource-ref-name|res-ref-name|"
    r"resource-name|jndi-name|lookup-name)>\s*([^<\s]+)\s*</"
)
_JNDI_IN_JAVA_RESOURCE = re.compile(
    r'@(?:javax\.annotation\.Resource|Resource)\s*\(\s*'
    r'(?:name|lookup|mappedName)\s*=\s*"([^"]+)"'
)
_JNDI_IN_JAVA_LOOKUP = re.compile(
    r'\.lookup\s*\(\s*"([^"]+)"\s*\)'
)
_JNDI_IN_PROPERTIES = re.compile(
    r"^\s*(?:[A-Z_][A-Z0-9_]*_)?(?:JNDI\w*|[A-Z0-9_]*_JNDI)\s*=\s*([^\s#;]+)",
    re.MULTILINE | re.IGNORECASE,
)


def _is_datasource_reference(value: str) -> bool:
    clean = value.strip()
    return (
        clean in _KNOWN_DATASOURCE_NAMES
        or clean.startswith("jndi.")
        or clean.startswith("jdbc/")
    )


@dataclass
class JndiHit:
    """Una ocurrencia de JNDI encontrada en el legacy."""

    jndi: str
    source_file: str             # path relativo al root escaneado
    source_kind: str             # "xml" | "java" | "properties" | "generic"


@dataclass
class SecretRequirement:
    """Un secreto que el servicio migrado necesita configurar."""

    jndi: str
    db_label: str                # "DTST" | "TPOMN" | etc.
    user_secret: str             # nombre KV del secreto username
    password_secret: str         # nombre KV del secreto password
    detected_from: list[str] = field(default_factory=list)


@dataclass
class SecretsAudit:
    """Resultado del scan completo del workspace."""

    service_kind: str            # "was" | "bus" | "orq" | "unknown"
    has_database: bool
    secrets_required: list[SecretRequirement] = field(default_factory=list)
    jndi_references_unknown: list[JndiHit] = field(default_factory=list)

    @property
    def applies(self) -> bool:
        """True si este servicio DEBE configurar secretos de KV."""
        return self.service_kind == "was" and self.has_database


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def _scan_xml_files(root: Path) -> list[JndiHit]:
    """Escanea *.xml buscando JNDI en tags conocidos + patron generico."""
    hits: list[JndiHit] = []
    for xml in root.rglob("*.xml"):
        if ".git" in xml.parts or "build" in xml.parts or "target" in xml.parts:
            continue
        try:
            text = xml.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(xml.relative_to(root.parent))
        except ValueError:
            rel = str(xml)

        # Match en tags conocidos (preferido)
        found_in_tags: set[str] = set()
        for m in _JNDI_IN_XML.finditer(text):
            jndi = m.group(1).strip()
            if not _is_datasource_reference(jndi):
                continue
            found_in_tags.add(jndi)
            hits.append(JndiHit(jndi=jndi, source_file=rel, source_kind="xml"))

        # Match generico (captura `jndi.xxx` en cualquier parte del XML)
        # — solo si NO fue ya encontrado en tags (evita duplicar la misma ocurrencia)
        for m in _DATASOURCE_PATTERN_GENERIC.finditer(text):
            jndi = m.group(0).strip()
            if jndi in found_in_tags:
                continue
            if not any(h.jndi == jndi and h.source_file == rel for h in hits):
                hits.append(JndiHit(jndi=jndi, source_file=rel, source_kind="generic"))
    return hits


def _scan_java_files(root: Path) -> list[JndiHit]:
    """Escanea *.java buscando @Resource(name=...) y .lookup(...) con JNDI."""
    hits: list[JndiHit] = []
    for java in root.rglob("*.java"):
        if ".git" in java.parts or "build" in java.parts or "target" in java.parts:
            continue
        try:
            text = java.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(java.relative_to(root.parent))
        except ValueError:
            rel = str(java)

        for m in _JNDI_IN_JAVA_RESOURCE.finditer(text):
            jndi = m.group(1).strip()
            if _is_datasource_reference(jndi):
                hits.append(JndiHit(jndi=jndi, source_file=rel, source_kind="java"))
        for m in _JNDI_IN_JAVA_LOOKUP.finditer(text):
            jndi = m.group(1).strip()
            if _is_datasource_reference(jndi):
                hits.append(JndiHit(jndi=jndi, source_file=rel, source_kind="java"))
    return hits


def _scan_properties_files(root: Path) -> list[JndiHit]:
    """Escanea *.properties buscando `...JNDI... = jndi.xxx`."""
    hits: list[JndiHit] = []
    for props in root.rglob("*.properties"):
        if ".git" in props.parts or "build" in props.parts or "target" in props.parts:
            continue
        try:
            text = props.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(props.relative_to(root.parent))
        except ValueError:
            rel = str(props)
        for m in _JNDI_IN_PROPERTIES.finditer(text):
            jndi = m.group(1).strip()
            if _is_datasource_reference(jndi):
                hits.append(JndiHit(jndi=jndi, source_file=rel, source_kind="properties"))
    return hits


def scan_jndi_references(roots: list[Path]) -> list[JndiHit]:
    """Escanea varios roots (legacy + umps) y colecta JNDI hits deduplicados."""
    all_hits: list[JndiHit] = []
    seen: set[tuple[str, str]] = set()
    for root in roots:
        if not root.exists():
            continue
        collected = []
        collected.extend(_scan_xml_files(root))
        collected.extend(_scan_java_files(root))
        collected.extend(_scan_properties_files(root))
        for h in collected:
            key = (h.jndi, h.source_file)
            if key in seen:
                continue
            seen.add(key)
            all_hits.append(h)
    return all_hits


def audit_secrets(
    legacy_root: Path,
    umps_roots: list[Path] | None = None,
    *,
    service_kind: str = "",
    has_database: bool = False,
) -> SecretsAudit:
    """Escanea legacy + umps y mapea JNDI al catalogo de secretos.

    Solo genera entradas si service_kind=="was" y has_database=True; para
    BUS/ORQ/WAS-sin-BD el audit retorna vacio (no aplica).
    """
    audit = SecretsAudit(service_kind=service_kind, has_database=has_database)

    if not audit.applies:
        return audit

    roots = [legacy_root]
    if umps_roots:
        roots.extend(umps_roots)

    hits = scan_jndi_references(roots)

    # Agrupar hits por JNDI, conservar paths como detected_from
    by_jndi: dict[str, list[JndiHit]] = {}
    for h in hits:
        by_jndi.setdefault(h.jndi, []).append(h)

    for jndi, occurrences in sorted(by_jndi.items()):
        if jndi in SECRETS_CATALOG:
            db_label, user_secret, password_secret = SECRETS_CATALOG[jndi]
            audit.secrets_required.append(
                SecretRequirement(
                    jndi=jndi,
                    db_label=db_label,
                    user_secret=user_secret,
                    password_secret=password_secret,
                    detected_from=[o.source_file for o in occurrences[:5]],
                )
            )
        else:
            # JNDI desconocido — no mapea a catalogo, requiere verificar con SRE
            audit.jndi_references_unknown.extend(occurrences[:3])

    return audit
