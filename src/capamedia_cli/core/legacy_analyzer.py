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

RE_WSDL_OPERATION = re.compile(r'<wsdl:operation\s+name="([^"]+)"', re.IGNORECASE)
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


# -- WSDL parsing (portType-only, skip binding) -----------------------------


def _extract_portType_block(text: str) -> str:
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


# -- Full analysis orchestration --------------------------------------------


def analyze_legacy(legacy_root: Path, service_name: str, umps_root: Path | None = None) -> LegacyAnalysis:
    """Full analysis of a cloned legacy folder. Deterministic, no AI required."""
    warnings: list[str] = []

    source_kind = detect_source_kind(legacy_root, service_name)

    wsdl_path = find_wsdl(legacy_root)
    wsdl_info = analyze_wsdl(wsdl_path) if wsdl_path else None
    if wsdl_info is None:
        warnings.append("No se encontro ningun *.wsdl en el legacy")

    ump_names = detect_ump_references(legacy_root) if source_kind != "was" else []
    umps: list[UmpInfo] = []
    if umps_root and umps_root.exists():
        for ump in ump_names:
            ump_lower = ump.lower()
            repo = umps_root / f"sqb-msa-{ump_lower}"
            if repo.exists():
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
    )
