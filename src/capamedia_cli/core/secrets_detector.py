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
}


# Patrones de deteccion de JNDI en distintos formatos del legacy
_JNDI_PATTERN_GENERIC = re.compile(r"\bjndi\.[a-zA-Z][a-zA-Z0-9._]+\b")
_JNDI_IN_XML = re.compile(
    r"<(?:jta-data-source|data-source|resource-ref-name|res-ref-name|"
    r"resource-name|jndi-name|lookup-name)>\s*(jndi\.[^<\s]+)\s*</"
)
_JNDI_IN_JAVA_RESOURCE = re.compile(
    r'@(?:javax\.annotation\.Resource|Resource)\s*\(\s*'
    r'(?:name|lookup|mappedName)\s*=\s*"(jndi\.[^"]+)"'
)
_JNDI_IN_JAVA_LOOKUP = re.compile(
    r'\.lookup\s*\(\s*"(jndi\.[^"]+)"\s*\)'
)
_JNDI_IN_PROPERTIES = re.compile(
    r"^\s*(?:[A-Z_][A-Z0-9_]*_)?JNDI\w*\s*=\s*(jndi\.[^\s#;]+)",
    re.MULTILINE | re.IGNORECASE,
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
            found_in_tags.add(jndi)
            hits.append(JndiHit(jndi=jndi, source_file=rel, source_kind="xml"))

        # Match generico (captura `jndi.xxx` en cualquier parte del XML)
        # — solo si NO fue ya encontrado en tags (evita duplicar la misma ocurrencia)
        for m in _JNDI_PATTERN_GENERIC.finditer(text):
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
            hits.append(JndiHit(jndi=m.group(1), source_file=rel, source_kind="java"))
        for m in _JNDI_IN_JAVA_LOOKUP.finditer(text):
            hits.append(JndiHit(jndi=m.group(1), source_file=rel, source_kind="java"))
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
            hits.append(JndiHit(jndi=m.group(1).strip(), source_file=rel, source_kind="properties"))
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
