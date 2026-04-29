"""Utilidades deterministas para analisis de servicios legacy.

Logica compartida entre `clone`, `check` y `fabric generate` para:
  - Contar operaciones de un WSDL (portType)
  - Detectar UMPs referenciados en ESQL
  - Extraer TX codes de un repo UMP
  - Detectar tipo de fuente (IIB vs WAS vs ORQ)
  - Detectar uso de BD en WAS

Todo es shell-compatible (no requiere AI), basado en grep + glob + regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# -- Regex patterns ---------------------------------------------------------

RE_WSDL_OPERATION = re.compile(r'<(?:wsdl:)?operation\s+name="([^"]+)"', re.IGNORECASE)
RE_WSDL_TARGETNS = re.compile(r'targetNamespace="([^"]+)"')
RE_UMP_REFERENCE = re.compile(r"\b(UMP[A-Z][a-zA-Z]+\d{4})\b")
RE_TX_CODE = re.compile(r"'(\d{6})'")
RE_SCHEMALOCATION = re.compile(r'schemaLocation="([^"]+)"')


# -- Dataclasses ------------------------------------------------------------


@dataclass
class WsdlInfo:
    """Informacion extraida de un WSDL."""

    path: Path
    operation_count: int
    operation_names: list[str] = field(default_factory=list)
    target_namespace: str = ""
    schema_locations: list[str] = field(default_factory=list)


@dataclass
class UmpInfo:
    """UMP detectado + sus TX codes si se pudo escanear."""

    name: str
    tx_codes: list[str] = field(default_factory=list)
    repo_path: Path | None = None


@dataclass
class PropertiesReference:
    """Archivo `.properties` referenciado por el legacy.

    Se diferencian 3 status:
    - "SHARED_CATALOG": esta en bank-shared-properties.md (embebido en CLI, no hay blocker)
    - "SAMPLE_IN_REPO": existe un `.properties` en el repo con valores reales
    - "PENDING_FROM_BANK": hay que pedirselo al owner del servicio antes de /migrate
    """

    file_name: str  # "umptecnicos0023.properties"
    status: str  # "SHARED_CATALOG" | "SAMPLE_IN_REPO" | "PENDING_FROM_BANK"
    source_hint: str = ""  # "ump:umptecnicos0023" | "service" | "unknown"
    referenced_from: list[str] = field(default_factory=list)  # paths relativos
    keys_used: list[str] = field(default_factory=list)
    sample_values: dict[str, str] = field(default_factory=dict)
    physical_path_hint: str = ""  # "/apps/proy/.../umptecnicos0023.properties"


@dataclass
class LegacyAnalysis:
    """Resultado completo del analisis de una carpeta legacy."""

    source_kind: str  # "iib" | "was" | "orq" | "unknown"
    wsdl: WsdlInfo | None
    umps: list[UmpInfo] = field(default_factory=list)
    has_database: bool = False
    db_evidence: list[str] = field(default_factory=list)
    framework_recommendation: str = ""  # "rest" | "soap"
    complexity: str = ""  # "low" | "medium" | "high"
    warnings: list[str] = field(default_factory=list)
    has_bancs: bool = False
    bancs_evidence: list[str] = field(default_factory=list)
    properties_refs: list[PropertiesReference] = field(default_factory=list)


# -- WSDL parsing (portType-only, skip binding) -----------------------------


def _extract_portType_block(text: str) -> str:  # noqa: N802
    """Extract the text between <wsdl:portType> and </wsdl:portType>.

    Necesario porque `<wsdl:binding>` tambien tiene `<wsdl:operation>` y no
    queremos contarlo dos veces.
    """
    start = text.lower().find("<wsdl:porttype")
    if start < 0:
        # Some WSDLs don't use the wsdl: namespace prefix
        start = text.lower().find("<porttype")
        if start < 0:
            return ""
    end = text.lower().find("</wsdl:porttype>", start)
    if end < 0:
        end = text.lower().find("</porttype>", start)
        if end < 0:
            return text[start:]
    return text[start:end]


def analyze_wsdl(path: Path) -> WsdlInfo:
    """Extract operation count, names, namespace and schema imports from a WSDL."""
    content = path.read_text(encoding="utf-8", errors="replace")

    porttype_block = _extract_portType_block(content)
    op_names = RE_WSDL_OPERATION.findall(porttype_block)

    ns_match = RE_WSDL_TARGETNS.search(content)
    target_ns = ns_match.group(1) if ns_match else ""

    schema_locs = RE_SCHEMALOCATION.findall(content)

    return WsdlInfo(
        path=path,
        operation_count=len(op_names),
        operation_names=op_names,
        target_namespace=target_ns,
        schema_locations=schema_locs,
    )


def find_wsdl(root: Path) -> Path | None:
    """Find the first *.wsdl under root, preferring src/main/resources."""
    preferred = list(root.rglob("src/main/resources/**/*.wsdl"))
    if preferred:
        return preferred[0]
    all_wsdl = [
        p
        for p in root.rglob("*.wsdl")
        if "node_modules" not in p.parts and "build" not in p.parts and ".git" not in p.parts
    ]
    return all_wsdl[0] if all_wsdl else None


# -- UMP detection ----------------------------------------------------------


def detect_ump_references(legacy_root: Path) -> list[str]:
    """Scan *.esql and *.msgflow under legacy_root for UMP references.

    Returns deduplicated UMP names sorted.
    """
    refs: set[str] = set()
    for pattern in ("**/*.esql", "**/*.msgflow", "**/*.subflow"):
        for f in legacy_root.rglob(pattern):
            if ".git" in f.parts or "build" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            refs.update(RE_UMP_REFERENCE.findall(text))
    return sorted(refs)


# WAS declara UMPs como Maven dependencies (artifactId = umpXxx0000-*) y las
# usa via imports Java. El regex captura ambos casos.
RE_UMP_WAS_MAVEN = re.compile(
    r"<artifactId>\s*(ump[a-z]+\d{4})[-a-z]*\s*</artifactId>",
    re.IGNORECASE,
)
RE_UMP_WAS_JAVA_IMPORT = re.compile(
    r"import\s+com\.pichincha\.[a-z]+\.(ump[a-z]+\d{4})\.",
    re.IGNORECASE,
)


def detect_ump_references_was(legacy_root: Path) -> list[str]:
    """Scan pom.xml + Java sources for UMP references in WAS projects.

    WAS no usa ESQL — las UMPs se referencian como:
      1. Maven dependencies en pom.xml (<artifactId>umpXxx0000-dominio</artifactId>)
      2. Imports Java (`import com.pichincha.<dominio>.umpXxx0000.pojo.*`)

    Returns deduplicated UMP names (lowercase), sorted. Ej: ["umptecnicos0023"].
    """
    refs: set[str] = set()

    # 1. pom.xml Maven dependencies
    for pom in legacy_root.rglob("pom.xml"):
        if ".git" in pom.parts or "target" in pom.parts:
            continue
        try:
            text = pom.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in RE_UMP_WAS_MAVEN.findall(text):
            refs.add(match.lower())

    # 2. Java imports
    for java in legacy_root.rglob("*.java"):
        if ".git" in java.parts or "target" in java.parts or "build" in java.parts:
            continue
        try:
            text = java.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in RE_UMP_WAS_JAVA_IMPORT.findall(text):
            refs.add(match.lower())

    return sorted(refs)


# -- TX extraction ----------------------------------------------------------


def extract_tx_codes(ump_repo_root: Path) -> list[str]:
    """Scan ESQL of an UMP repo and return 6-digit TX codes found."""
    codes: set[str] = set()
    for f in ump_repo_root.rglob("*.esql"):
        if ".git" in f.parts:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        codes.update(RE_TX_CODE.findall(text))
    # Filter obvious non-TX matches (e.g., dates like '202601')
    return sorted(c for c in codes if c[0] != "2" or not (c[1:4].isdigit() and 1 <= int(c[1:4]) <= 123))


# -- Source kind detection --------------------------------------------------


def detect_source_kind(legacy_root: Path, service_name: str) -> str:
    """Detect IIB / WAS / ORQ based on file patterns."""
    has_esql = any(legacy_root.rglob("*.esql"))
    has_java_src = any(legacy_root.rglob("src/**/*.java"))
    has_web_xml = any(legacy_root.rglob("web.xml"))

    # ORQ: name starts with orq OR msgflow contains IniciarOrquestacionSOAP
    if service_name.lower().startswith("orq"):
        return "orq"
    for msgflow in legacy_root.rglob("*.msgflow"):
        try:
            text = msgflow.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "IniciarOrquestacionSOAP" in text:
            return "orq"

    if has_esql:
        return "iib"
    if has_java_src and has_web_xml:
        return "was"
    if has_esql and has_java_src:
        return "iib"  # prefer IIB if ambiguous
    return "unknown"


# -- Database detection (WAS only) ------------------------------------------


DB_EVIDENCE_PATTERNS = [
    ("persistence.xml", "presence"),
    ("ibm-web-bnd.xml", "presence"),
    (r"@Entity\b", "grep-java"),
    (r"@Repository\b", "grep-java"),
    (r"@PersistenceContext\b", "grep-java"),
    (r"EntityManager\b", "grep-java"),
    (r"JdbcTemplate\b", "grep-java"),
    (r"\bDataSource\b", "grep-java"),
    (r"<resource-ref>", "grep-xml"),
]


def detect_database_usage(legacy_root: Path) -> tuple[bool, list[str]]:
    """Return (has_db, evidence_list) for a WAS service."""
    evidence: list[str] = []
    for pattern, kind in DB_EVIDENCE_PATTERNS:
        if kind == "presence":
            matches = list(legacy_root.rglob(pattern))
            if matches:
                evidence.append(f"{pattern} ({len(matches)} file(s))")
        elif kind == "grep-java":
            count = 0
            for f in legacy_root.rglob("*.java"):
                if ".git" in f.parts or "build" in f.parts:
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if re.search(pattern, text):
                    count += 1
                    if count >= 3:
                        break
            if count > 0:
                evidence.append(f"{pattern} in {count}+ .java files")
        elif kind == "grep-xml":
            for f in legacy_root.rglob("*.xml"):
                if ".git" in f.parts:
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if re.search(pattern, text):
                    evidence.append(f"{pattern} in {f.name}")
                    break
    return (len(evidence) > 0, evidence)


# -- Complexity scoring -----------------------------------------------------


def score_complexity(op_count: int, ump_count: int, has_db: bool) -> str:
    """Rough LOW/MEDIUM/HIGH score based on complexity drivers."""
    score = 0
    score += op_count * 2
    score += ump_count * 1
    if has_db:
        score += 3
    if score <= 3:
        return "low"
    if score <= 8:
        return "medium"
    return "high"


# -- BANCS connection detection ---------------------------------------------


def detect_bancs_connection(legacy_root: Path) -> tuple[bool, list[str]]:
    """True si el servicio conecta a BANCS por cualquier via.

    4 senales:
      1. UMPs referenciadas (patron indirecto)
      2. TX BANCS literal (0NNNNN) en ESQL sin prefijo UMP adyacente
      3. HTTPRequest node apuntando a BANCS en msgflows
      4. BancsClient / @BancsService en Java
    """
    evidence: list[str] = []
    # 1. UMPs
    if detect_ump_references(legacy_root):
        evidence.append("UMP references")
    # 2. TX literal 0NNNNN en ESQL
    tx_pattern = re.compile(r"['\"]0\d{5}['\"]")
    for esql in legacy_root.rglob("*.esql"):
        try:
            text = esql.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if tx_pattern.search(text):
            evidence.append(f"TX literal en {esql.name}")
            break
    # 3. HTTPRequest con BANCS en msgflow
    for msgflow in legacy_root.rglob("*.msgflow"):
        try:
            text = msgflow.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"HTTPRequest", text) and re.search(r"bancs", text, re.IGNORECASE):
            evidence.append(f"HTTPRequest BANCS en {msgflow.name}")
            break
    # 4. BancsClient / @BancsService en Java
    for java in legacy_root.rglob("*.java"):
        if ".git" in java.parts or "build" in java.parts:
            continue
        try:
            text = java.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "BancsClient" in text or "@BancsService" in text:
            evidence.append(f"BancsClient en {java.name}")
            break
    return (len(evidence) > 0, evidence)


# -- WAS endpoint count via Java fallback -----------------------------------


def count_was_endpoints(legacy_root: Path) -> tuple[int, str]:
    """Cuenta endpoints de un WAS cuando no hay WSDL suelto.

    Cascada:
      1. WSDL embebido en .ear/.war (extrae y parsea)
      2. Metodos @WebMethod del servlet-class del web.xml
      3. Metodos publicos no-getter/setter del servlet-class
    Retorna (count, source). count=0 si no se pudo determinar.
    """
    import zipfile
    # 1. WSDL en .ear/.war
    for archive in list(legacy_root.rglob("*.ear")) + list(legacy_root.rglob("*.war")):
        try:
            with zipfile.ZipFile(archive) as z:
                wsdl_names = [n for n in z.namelist() if n.lower().endswith(".wsdl")]
                for wsdl_name in wsdl_names:
                    try:
                        content = z.read(wsdl_name).decode("utf-8", errors="ignore")
                        # Dedup operations by name attribute
                        ops = set(re.findall(r"<(?:\w+:)?operation\s+name=\"([^\"]+)\"", content))
                        if ops:
                            return (len(ops), f"WSDL embebido en {archive.name}")
                    except (KeyError, zipfile.BadZipFile, UnicodeDecodeError):
                        continue
        except (zipfile.BadZipFile, OSError):
            continue
    # 2/3. web.xml -> servlet-class -> metodos
    for webxml in legacy_root.rglob("web.xml"):
        if "target" in webxml.parts:
            continue
        try:
            text = webxml.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = re.search(r"<servlet-class>([^<]+)</servlet-class>", text)
        if not m:
            continue
        servlet_class = m.group(1).strip()
        class_simple = servlet_class.split(".")[-1]
        for java in legacy_root.rglob(f"{class_simple}.java"):
            if "target" in java.parts or "build" in java.parts:
                continue
            try:
                jtext = java.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            # 2. @WebMethod
            webmethods = re.findall(r"@WebMethod\b", jtext)
            if webmethods:
                return (len(webmethods), f"@WebMethod en {class_simple}.java")
            # 3. Publics no getter/setter/main
            publics = re.findall(
                r"public\s+(?!class\b)(?!static\s+void\s+main\b)"
                r"[\w<>\[\],\s?]+?\s+(?!get)(?!set)(?!is)(\w+)\s*\(",
                jtext,
            )
            uniq = set(publics)
            if uniq:
                return (len(uniq), f"metodos publicos en {class_simple}.java")
    return (0, "no se pudo determinar")


# -- Properties references detection (WAS/UMP especifico) ------------------

# Patterns para WAS legacy usando la clase Propiedad del banco.
# Propiedad.get("KEY")              -> busca en el .properties ESPECIFICO del servicio/UMP
# Propiedad.getGenerico("KEY")      -> generalservices.properties (catalogo compartido)
# Propiedad.getCatalogo("KEY")      -> catalogoaplicaciones.properties (catalogo compartido)
RE_PROPIEDAD_GET = re.compile(
    r"Propiedad\s*\.\s*get\s*\(\s*\"([^\"]+)\"\s*\)"
)
RE_PROPIEDAD_GET_GENERICO = re.compile(
    r"Propiedad\s*\.\s*getGenerico\s*\(\s*\"([^\"]+)\"\s*\)"
)
RE_PROPIEDAD_GET_CATALOGO = re.compile(
    r"Propiedad\s*\.\s*getCatalogo\s*\(\s*\"([^\"]+)\"\s*\)"
)
# Literal paths a archivos .properties en /apps/proy/.../conf/NOMBRE.properties
RE_PROPERTIES_PATH_LITERAL = re.compile(
    r'"(/apps/proy/[^"]+?/([A-Za-z_][A-Za-z0-9_]*)\.properties)"'
)
# ResourceBundle.getBundle("nombre") - raro en WAS banco pero completa el catalogo
RE_RESOURCE_BUNDLE = re.compile(
    r'ResourceBundle\s*\.\s*getBundle\s*\(\s*"([A-Za-z_][A-Za-z0-9_]*)"'
)

# En Propiedad.java el banco define la constante RUTA_ESPECIFICA apuntando al
# archivo .properties especifico del componente (UMP o servicio). Ej:
#   private static final String RUTA_ESPECIFICA =
#       "/apps/proy/OMNICANALIDAD_SERVICIOS/conf/wsclientes0076.properties";
RE_RUTA_ESPECIFICA = re.compile(
    r"RUTA_ESPECIFICA\s*=\s*"
    r'"/apps/proy/[^"]+?/([A-Za-z_][A-Za-z0-9_]*)\.properties"',
    re.IGNORECASE,
)

# Heuristicas para inferir el nombre del archivo .properties desde el nombre
# del root de clone (cuando Propiedad.java no esta disponible). Ejemplos:
#   ump-umptecnicos0023-was  -> umptecnicos0023.properties
#   ws-wsclientes0076-was    -> wsclientes0076.properties
#   ms-wsclientes0076-was    -> wsclientes0076.properties
#   sqb-msa-wsclientes0006   -> wsclientes0006.properties
_ROOT_PATTERNS = [
    re.compile(r"^ump-([a-z]+\d{4})-was$", re.IGNORECASE),
    re.compile(r"^ws-([a-z]+\d{4})-was$", re.IGNORECASE),
    re.compile(r"^ms-([a-z]+\d{4})-was$", re.IGNORECASE),
    re.compile(r"^sqb-msa-([a-z]+\d{4})$", re.IGNORECASE),
]

# Patrones para buscar repos UMP ya clonados en disco. Ordenados segun el
# source_kind del servicio consumidor:
#   - WAS:     UMPs suelen estar en ump-<ump>-was (fallback ms-/sqb-msa-)
#   - IIB/ORQ: UMPs suelen estar en sqb-msa-<ump> (fallback ump-/ms-)
_UMP_REPO_PATTERNS_WAS = [
    "ump-{ump}-was",
    "ms-{ump}-was",
    "sqb-msa-{ump}",
]
_UMP_REPO_PATTERNS_NON_WAS = [
    "sqb-msa-{ump}",
    "ump-{ump}-was",
    "ms-{ump}-was",
]


def _ump_name_variants(ump_name: str) -> list[str]:
    raw = ump_name.strip()
    lower = raw.lower()
    variants: list[str] = []

    def add(value: str) -> None:
        if value and value not in variants:
            variants.append(value)

    add(raw)
    if raw[:3].lower() == "ump" and len(raw) > 3:
        add("ump" + raw[3:])
    add(lower)
    return variants


def _existing_child_case_insensitive(parent: Path, name: str) -> Path | None:
    candidate = parent / name
    if candidate.exists():
        return candidate
    if not parent.exists():
        return None
    try:
        for child in parent.iterdir():
            if child.name.lower() == name.lower():
                return child
    except OSError:
        return None
    return None


def _find_ump_repo(umps_root: Path, ump_name: str, source_kind: str) -> Path | None:
    """Busca el repo de un UMP ya clonado en disco probando los 3 patterns
    conocidos. Respeta el `source_kind` para priorizar el patron mas probable.

    Returns el Path si existe, None si no.
    """
    patterns = (
        _UMP_REPO_PATTERNS_WAS
        if source_kind == "was"
        else _UMP_REPO_PATTERNS_NON_WAS
    )
    for tmpl in patterns:
        for ump in _ump_name_variants(ump_name):
            candidate = _existing_child_case_insensitive(umps_root, tmpl.format(ump=ump))
            if candidate is None:
                continue
            return candidate
    return None


def _detect_specific_file_from_propiedad_java(root: Path) -> str | None:
    """Busca `Propiedad.java` (clase util del banco) en el root y extrae el
    nombre del .properties especifico desde la constante RUTA_ESPECIFICA.

    Retorna el nombre del archivo (ej "wsclientes0076.properties") o None si
    no se encuentra.
    """
    for f in root.rglob("Propiedad.java"):
        if ".git" in f.parts or "build" in f.parts or "target" in f.parts:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = RE_RUTA_ESPECIFICA.search(text)
        if m:
            return f"{m.group(1)}.properties"
    return None


def _infer_specific_file_from_root_name(root: Path) -> str | None:
    """Heuristica de fallback: infiere el nombre del .properties por el nombre
    de la carpeta del root clonado. Funciona para los 4 patterns Azure.
    """
    name = root.name.lower()
    for pat in _ROOT_PATTERNS:
        m = pat.match(name)
        if m:
            return f"{m.group(1)}.properties"
    return None


def _resolve_specific_properties_file(root: Path) -> tuple[str | None, str]:
    """Resuelve el nombre del archivo .properties especifico para un root.

    Estrategia (en orden):
      1. Leer Propiedad.java y extraer RUTA_ESPECIFICA (lo correcto).
      2. Fallback: inferir del nombre del root (ws-<x>-was, ump-<x>-was, etc).

    Retorna (file_name, source_hint):
      file_name: "wsclientes0076.properties" o None si no se pudo resolver.
      source_hint: "service" | "ump:<ump_name>" | "unknown".
    """
    # 1. Propiedad.java (lo correcto)
    from_java = _detect_specific_file_from_propiedad_java(root)
    if from_java:
        file_stem = from_java.rsplit(".", 1)[0]
        if file_stem.startswith("ump"):
            return from_java, f"ump:{file_stem}"
        return from_java, "service"

    # 2. Heuristica de fallback por nombre de root
    from_root = _infer_specific_file_from_root_name(root)
    if from_root:
        file_stem = from_root.rsplit(".", 1)[0]
        if file_stem.startswith("ump"):
            return from_root, f"ump:{file_stem}"
        return from_root, "service"

    return None, "unknown"

# Archivos que son catalogo compartido (embebidos en v0.18.0).
# Comparacion case-insensitive porque los nombres varian
# (generalServices vs generalservices, CatalogoAplicaciones vs catalogoaplicaciones).
_SHARED_CATALOG_FILES = {
    "generalservices.properties",
    "catalogoaplicaciones.properties",
}


def _is_shared_catalog(file_name: str) -> bool:
    return file_name.lower() in _SHARED_CATALOG_FILES


def _read_sample_properties(path: Path) -> dict[str, str]:
    """Parsea un archivo .properties y devuelve el dict de claves->valores."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
        elif ":" in line:
            key, _, value = line.partition(":")
        else:
            continue
        values[key.strip()] = value.strip()
    return values


def detect_properties_references(
    roots: list[Path],
) -> list[PropertiesReference]:
    """Escanea roots (legacy + umps) en busca de archivos .properties referenciados.

    Devuelve una lista unificada donde cada `PropertiesReference` dice:
      - que archivo `.properties` se usa
      - desde que paths del codigo se referencia
      - que claves se usan (desde Propiedad.get/getGenerico/getCatalogo)
      - si hay sample en el repo (extrae valores) o si hay que pedirlo al banco

    Excluye explicitamente los `.properties` del catalogo compartido
    (generalservices + catalogoaplicaciones) ya embebidos en v0.18.0.
    """
    # Mapa: file_name_lower -> PropertiesReference acumulando referencias
    refs: dict[str, PropertiesReference] = {}

    # Paso 1: scan codigo para patterns Propiedad.* y literal paths
    # Por cada root (legacy + cada ump), escanear .java, .xml, .properties
    for root in roots:
        if not root.exists():
            continue

        # v0.20.2: resolver robusto del .properties especifico del root.
        # Antes: solo inferiamos por root_name si matcheaba "ump[a-z]+\d{4}",
        # entonces el WAS principal (ws-<svc>-was) se descartaba silenciosamente.
        # Ahora: leemos Propiedad.java (fuente de verdad) y si no, inferimos por
        # nombre de carpeta para los 4 patrones Azure (ws-, ms-, ump-, sqb-msa-).
        specific_file_name, source_hint = _resolve_specific_properties_file(root)

        for pattern in ("**/*.java", "**/*.xml"):
            for f in root.rglob(pattern):
                if ".git" in f.parts or "build" in f.parts or "target" in f.parts:
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                # Path literal define el nombre del archivo
                for m in RE_PROPERTIES_PATH_LITERAL.finditer(text):
                    physical = m.group(1)
                    name = f"{m.group(2)}.properties"
                    name_key = name.lower()
                    if _is_shared_catalog(name):
                        if name_key not in refs:
                            refs[name_key] = PropertiesReference(
                                file_name=name,
                                status="SHARED_CATALOG",
                                source_hint=source_hint,
                                physical_path_hint=physical,
                            )
                        continue
                    entry = refs.get(name_key) or PropertiesReference(
                        file_name=name,
                        status="PENDING_FROM_BANK",
                        source_hint=source_hint,
                        physical_path_hint=physical,
                    )
                    entry.physical_path_hint = entry.physical_path_hint or physical
                    try:
                        entry.referenced_from.append(
                            str(f.relative_to(root.parent))
                        )
                    except ValueError:
                        entry.referenced_from.append(str(f))
                    refs[name_key] = entry

        # Propiedad.get("KEY") -> keys al archivo especifico ya resuelto arriba
        # (via Propiedad.java o nombre de root).
        for f in root.rglob("*.java"):
            if ".git" in f.parts or "build" in f.parts or "target" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # KEYS del archivo especifico
            get_keys = RE_PROPIEDAD_GET.findall(text)
            if get_keys and specific_file_name:
                name_key = specific_file_name.lower()
                entry = refs.get(name_key) or PropertiesReference(
                    file_name=specific_file_name,
                    status="PENDING_FROM_BANK",
                    source_hint=source_hint,
                )
                for k in get_keys:
                    if k not in entry.keys_used:
                        entry.keys_used.append(k)
                try:
                    rel = str(f.relative_to(root.parent))
                except ValueError:
                    rel = str(f)
                if rel not in entry.referenced_from:
                    entry.referenced_from.append(rel)
                refs[name_key] = entry

            # getGenerico -> catalogo compartido (generalservices)
            gen_keys = RE_PROPIEDAD_GET_GENERICO.findall(text)
            if gen_keys:
                name_key = "generalservices.properties"
                entry = refs.get(name_key) or PropertiesReference(
                    file_name="generalServices.properties",
                    status="SHARED_CATALOG",
                    source_hint="bank-shared-catalog",
                )
                for k in gen_keys:
                    if k not in entry.keys_used:
                        entry.keys_used.append(k)
                refs[name_key] = entry

            # getCatalogo -> catalogo compartido (catalogoaplicaciones)
            cat_keys = RE_PROPIEDAD_GET_CATALOGO.findall(text)
            if cat_keys:
                name_key = "catalogoaplicaciones.properties"
                entry = refs.get(name_key) or PropertiesReference(
                    file_name="CatalogoAplicaciones.properties",
                    status="SHARED_CATALOG",
                    source_hint="bank-shared-catalog",
                )
                for k in cat_keys:
                    if k not in entry.keys_used:
                        entry.keys_used.append(k)
                refs[name_key] = entry

            # ResourceBundle.getBundle("nombre") - menos comun pero posible
            for rb_name in RE_RESOURCE_BUNDLE.findall(text):
                name = f"{rb_name}.properties"
                name_key = name.lower()
                if _is_shared_catalog(name):
                    continue
                entry = refs.get(name_key) or PropertiesReference(
                    file_name=name,
                    status="PENDING_FROM_BANK",
                    source_hint=source_hint,
                )
                try:
                    rel = str(f.relative_to(root.parent))
                except ValueError:
                    rel = str(f)
                if rel not in entry.referenced_from:
                    entry.referenced_from.append(rel)
                refs[name_key] = entry

    # Paso 2: si hay un .properties en el repo con el mismo nombre, marcar
    # SAMPLE_IN_REPO y extraer valores reales.
    for root in roots:
        if not root.exists():
            continue
        for f in root.rglob("*.properties"):
            if (".git" in f.parts or "build" in f.parts or "target" in f.parts
                    or "node_modules" in f.parts):
                continue
            name_key = f.name.lower()
            if name_key not in refs:
                continue  # no lo referencia el codigo, skip
            entry = refs[name_key]
            if entry.status == "SHARED_CATALOG":
                continue
            values = _read_sample_properties(f)
            if values:
                entry.status = "SAMPLE_IN_REPO"
                entry.sample_values = values
                # keys_used ya viene del scan, pero completamos si estaba vacio
                for k in values:
                    if k not in entry.keys_used:
                        entry.keys_used.append(k)

    # Orden estable: SHARED primero, luego SAMPLE, luego PENDING; alfa dentro
    status_order = {
        "SHARED_CATALOG": 0,
        "SAMPLE_IN_REPO": 1,
        "PENDING_FROM_BANK": 2,
    }
    return sorted(
        refs.values(),
        key=lambda r: (status_order.get(r.status, 9), r.file_name.lower()),
    )


# -- Full analysis orchestration --------------------------------------------


def analyze_legacy(legacy_root: Path, service_name: str, umps_root: Path | None = None) -> LegacyAnalysis:
    """Full analysis of a cloned legacy folder. Deterministic, no AI required."""
    warnings: list[str] = []

    source_kind = detect_source_kind(legacy_root, service_name)

    wsdl_path = find_wsdl(legacy_root)
    wsdl_info = analyze_wsdl(wsdl_path) if wsdl_path else None
    if wsdl_info is None:
        warnings.append("No se encontro ningun *.wsdl en el legacy")

    # Detector UMP depende del tipo de legacy:
    # - IIB/ORQ: buscar en ESQL + msgflow (referencias tipo "UMPClientes0002")
    # - WAS: buscar en pom.xml deps (Maven) + imports Java (ej umptecnicos0023)
    if source_kind == "was":
        ump_names = detect_ump_references_was(legacy_root)
    else:
        ump_names = detect_ump_references(legacy_root)
    umps: list[UmpInfo] = []
    if umps_root and umps_root.exists():
        for ump in ump_names:
            # v0.20.3: buscar UMP en los 3 patterns conocidos segun source_kind.
            # Antes solo probaba sqb-msa-<ump> (IIB), entonces para WAS el
            # ump.repo_path quedaba None y detect_properties_references no
            # podia escanear el UMP (bug de wsclientes0076 + umpclientes0025).
            repo = _find_ump_repo(umps_root, ump, source_kind)
            if repo is not None:
                txs = extract_tx_codes(repo)
                umps.append(UmpInfo(name=ump, tx_codes=txs, repo_path=repo))
            else:
                umps.append(UmpInfo(name=ump))
                warnings.append(f"UMP {ump} referenciado pero no clonado en {umps_root}")
    else:
        for ump in ump_names:
            umps.append(UmpInfo(name=ump))

    has_db = False
    db_evidence: list[str] = []
    if source_kind == "was":
        has_db, db_evidence = detect_database_usage(legacy_root)

    # Detectar BANCS por cualquier via (no solo UMPs)
    has_bancs, bancs_evidence = detect_bancs_connection(legacy_root)

    # Para WAS sin WSDL suelto, contar endpoints por codigo Java
    if source_kind == "was" and wsdl_info is None:
        endpoint_count, endpoint_source = count_was_endpoints(legacy_root)
        if endpoint_count > 0:
            warnings.append(
                f"WAS sin WSDL suelto. Endpoints inferidos: {endpoint_count} "
                f"(fuente: {endpoint_source})"
            )
            # Sintetizar un WsdlInfo minimo con el count
            wsdl_info = WsdlInfo(
                path=Path("<inferred-from-java>"),
                operation_count=endpoint_count,
                operation_names=[],
                target_namespace="",
            )

    # Framework recommendation segun matriz actualizada:
    # ORQ siempre REST. IIB con BANCS siempre REST (override).
    # Resto decide por op_count del WSDL.
    framework = ""
    if source_kind == "orq" or (source_kind == "iib" and has_bancs):
        framework = "rest"
    elif wsdl_info:
        framework = "rest" if wsdl_info.operation_count == 1 else "soap"

    op_count = wsdl_info.operation_count if wsdl_info else 0
    complexity = score_complexity(op_count, len(umps), has_db)

    # Properties references: scan legacy + cada UMP repo clonado.
    # Solo aplica a WAS (y potencialmente IIB con UMPs Java), no a ORQ.
    properties_refs: list[PropertiesReference] = []
    if source_kind in ("was", "iib"):
        roots_to_scan: list[Path] = [legacy_root]
        for ump in umps:
            if ump.repo_path and ump.repo_path.exists():
                roots_to_scan.append(ump.repo_path)
        properties_refs = detect_properties_references(roots_to_scan)

    return LegacyAnalysis(
        source_kind=source_kind,
        wsdl=wsdl_info,
        umps=umps,
        has_database=has_db,
        db_evidence=db_evidence,
        framework_recommendation=framework,
        complexity=complexity,
        warnings=warnings,
        has_bancs=has_bancs,
        bancs_evidence=bancs_evidence,
        properties_refs=properties_refs,
    )
