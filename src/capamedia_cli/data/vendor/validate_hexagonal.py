#!/usr/bin/env python3
"""
================================================================================
  Hexagonal Architecture Validator — Java Projects
  Validador de arquitectura hexagonal para proyectos Java
================================================================================
  Validaciones:
    1. Capas permitidas: application, domain, infrastructure
    2. WSDL: 1 método → REST + WebFlux | >1 métodos → SOAP + MVC
    3. Controladores deben usar @BpTraceable (excluye controladores de test)
    4. Servicios deben usar @BpLogger
    5. No navegación cruzada entre capas
    6. Service Business Logic: servicios solo con lógica de negocio (sin métodos utilitarios)
    7. application.yml: variables sin valores por defecto (excluye rutas optimus.web.*)
    8. Gradle: librería obligatoria lib-bnc-api-client:1.1.0
    9. catalog-info.yaml: metadata, links, annotations y specs
   10. Genera reporte Markdown con checklist
================================================================================
"""

import os
import re
import sys
import json
import yaml
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)
    warning: bool = False          # True → PASS but with observations
    observations: list[str] = field(default_factory=list)

@dataclass
class ValidationReport:
    project_path: str
    timestamp: str
    layers_check: Optional[CheckResult] = None
    wsdl_checks: list[CheckResult] = field(default_factory=list)
    controller_annotation_check: Optional[CheckResult] = None
    service_annotation_check: Optional[CheckResult] = None
    layer_navigation_check: Optional[CheckResult] = None
    service_business_logic_check: Optional[CheckResult] = None
    application_yml_check: Optional[CheckResult] = None
    gradle_library_check: Optional[CheckResult] = None
    catalog_info_check: Optional[CheckResult] = None

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_LAYERS = {"application", "domain", "infrastructure"}

WSDL_NS = {
    "wsdl":  "http://schemas.xmlsoap.org/wsdl/",
    "wsdl2": "http://www.w3.org/ns/wsdl",
}

# Forbidden cross-layer imports (hexagonal rules)
# domain  → must NOT import application or infrastructure
# application → must NOT import infrastructure
LAYER_RULES: dict[str, set[str]] = {
    "domain":      {"application", "infrastructure"},
    "application": {"infrastructure"},
    "infrastructure": set(),          # infrastructure CAN import domain/application
}


def find_java_files(root: Path) -> list[Path]:
    return list(root.rglob("*.java"))


def find_wsdl_files(root: Path) -> list[Path]:
    return list(root.rglob("*.wsdl"))


def file_content(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def detect_layer_of_file(path: Path) -> Optional[str]:
    """Return the hexagonal layer this file belongs to, if any."""
    parts = [p.lower() for p in path.parts]
    for layer in ALLOWED_LAYERS:
        if layer in parts:
            return layer
    return None


def is_controller(path: Path, content: str) -> bool:
    return (
        "Controller" in path.name
        or "@RestController" in content
        or "@Controller" in content
    )


def is_test_controller(path: Path, content: str) -> bool:
    """
    Return True when a controller file is a test and must be excluded from
    @BpTraceable validation.  Criteria (any one is sufficient):
      - Filename ends with 'Test.java' or 'Tests.java'
      - File lives inside a 'test' directory segment in its path
      - Source contains typical Spring test annotations
    """
    name = path.name
    if name.endswith("Test.java") or name.endswith("Tests.java"):
        return True
    path_parts_lower = [p.lower() for p in path.parts]
    if "test" in path_parts_lower:
        return True
    test_annotations = (
        "@SpringBootTest",
        "@WebMvcTest",
        "@ExtendWith",
        "@RunWith",
        "@AutoConfigureMockMvc",
    )
    return any(ann in content for ann in test_annotations)


def is_service(path: Path, content: str) -> bool:
    return (
        "Service" in path.name or "ServiceImpl" in path.name
    ) and "@Service" in content


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION 1 — Layer structure
# ─────────────────────────────────────────────────────────────────────────────

def _find_artifact_roots(root: Path) -> list[Path]:
    """
    Locate the package root directory that sits directly above the hexagonal
    layer directories.  Strategy: find every directory named 'application',
    'domain', or 'infrastructure' and return their parent directories —
    those are the artifact roots where we should check for illegal siblings.
    """
    artifact_roots: set[Path] = set()
    for java_file in find_java_files(root):
        parts = list(java_file.parts)
        for layer in ALLOWED_LAYERS:
            if layer in parts:
                idx = parts.index(layer)
                artifact_roots.add(Path(*parts[:idx]))
    return list(artifact_roots)


def check_layers(root: Path) -> CheckResult:
    """
    Ensure that:
      1. All three canonical layers are present.
      2. No OTHER directories exist as siblings of the layer directories
         (i.e. no extra top-level packages alongside application/domain/infrastructure).
    """
    found_layers: set[str] = set()
    illegal_siblings: set[str] = set()
    details: list[str] = []

    # Collect found layers from Java file paths
    for java_file in find_java_files(root):
        parts_lower = [p.lower() for p in java_file.parts]
        for p in parts_lower:
            if p in ALLOWED_LAYERS:
                found_layers.add(p)

    # Find siblings of layer directories
    artifact_roots = _find_artifact_roots(root)
    for ar in artifact_roots:
        if not ar.is_dir():
            continue
        for child in ar.iterdir():
            if not child.is_dir():
                continue
            name = child.name.lower()
            if name not in ALLOWED_LAYERS:
                illegal_siblings.add(name)

    missing = ALLOWED_LAYERS - found_layers
    passed  = len(missing) == 0 and len(illegal_siblings) == 0

    if found_layers:
        details.append(f"✔ Capas encontradas: {', '.join(sorted(found_layers))}")
    if missing:
        details.append(f"✘ Capas faltantes: {', '.join(sorted(missing))}")
    if illegal_siblings:
        details.append(
            f"✘ Paquetes no permitidos junto a las capas: {', '.join(sorted(illegal_siblings))}"
        )
        details.append("  Solo se permiten: application, domain, infrastructure")

    msg = (
        "Estructura de capas válida (application / domain / infrastructure)."
        if passed
        else "Estructura de capas INVÁLIDA o incompleta."
    )
    return CheckResult(passed=passed, message=msg, details=details)


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION 2 — WSDL → REST/WebFlux vs SOAP/MVC
# ─────────────────────────────────────────────────────────────────────────────

def _count_wsdl_operations(wsdl_path: Path) -> tuple[int, list[str]]:
    """
    Return (unique_operation_count, sorted_unique_names).
    Deduplication is done by the 'name' attribute of <operation> elements.
    Operations without a name attribute fall back to their position index.
    Returns (-1, []) for malformed WSDL.
    """
    try:
        tree = ET.parse(wsdl_path)
        root = tree.getroot()

        # Try WSDL 1.1 namespace first, then 2.0, then namespace-less
        ops = root.findall(".//{http://schemas.xmlsoap.org/wsdl/}operation")
        if not ops:
            ops = root.findall(".//{http://www.w3.org/ns/wsdl}operation")
        if not ops:
            ops = root.findall(".//operation")

        # Deduplicate by name attribute
        seen: set[str] = set()
        unique_names: list[str] = []
        for idx, op in enumerate(ops):
            name = op.get("name") or f"__unnamed_{idx}__"
            if name not in seen:
                seen.add(name)
                unique_names.append(name)

        return len(unique_names), sorted(unique_names)
    except ET.ParseError:
        return -1, []


def _detect_framework(root: Path) -> dict[str, bool]:
    """Scan build files and Java sources to detect WebFlux / MVC / SOAP usage."""
    flags = {"webflux": False, "mvc": False, "soap": False}

    # ── Regex patterns ─────────────────────────────────────────────────────────
    # pom.xml — match the exact artifactId inside a <dependency> block
    _pom_mvc  = re.compile(r'<artifactId>\s*spring-boot-starter-web\s*</artifactId>')
    _pom_flux = re.compile(r'<artifactId>\s*spring-boot-starter-webflux\s*</artifactId>')
    _pom_soap = re.compile(r'<artifactId>\s*(?:spring-ws-core|cxf-spring-boot-starter|cxf-rt-frontend-jaxws)\s*</artifactId>')

    # build.gradle / build.gradle.kts — dependency string literals
    # Covers both:  'group:artifact:version'  and  group: "g", name: "a"
    _gradle_mvc  = re.compile(r'spring-boot-starter-web(?!flux)["\'\s]')
    _gradle_flux = re.compile(r'spring-boot-starter-webflux')
    _gradle_soap = re.compile(r'(?:spring-ws-core|cxf-spring-boot-starter|cxf-rt-frontend-jaxws)')

    # ── pom.xml ────────────────────────────────────────────────────────────────
    for build_file in root.glob("**/pom.xml"):
        content = file_content(build_file)
        if _pom_flux.search(content):
            flags["webflux"] = True
        if _pom_mvc.search(content):
            flags["mvc"] = True
        if _pom_soap.search(content):
            flags["soap"] = True

    # ── build.gradle / build.gradle.kts ───────────────────────────────────────
    for build_file in list(root.glob("**/build.gradle")) + list(root.glob("**/build.gradle.kts")):
        content = file_content(build_file)
        if _gradle_flux.search(content):
            flags["webflux"] = True
        if _gradle_mvc.search(content):
            flags["mvc"] = True
        if _gradle_soap.search(content):
            flags["soap"] = True

    # ── Java sources — reactive types and SOAP annotations ────────────────────
    for java_file in find_java_files(root):
        content = file_content(java_file)
        if "Mono<" in content or "Flux<" in content or "WebClient" in content:
            flags["webflux"] = True
        if "@Endpoint" in content or "WebServiceTemplate" in content:
            flags["soap"] = True

    return flags


def check_wsdl(root: Path) -> list[CheckResult]:
    wsdl_files = find_wsdl_files(root)
    if not wsdl_files:
        return [CheckResult(
            passed=True,
            message="No se encontraron archivos WSDL en el proyecto.",
            details=["ℹ Sin WSDL — sin restricciones de framework por este criterio."]
        )]

    framework = _detect_framework(root)
    results: list[CheckResult] = []

    for wsdl_path in wsdl_files:
        ops, op_names = _count_wsdl_operations(wsdl_path)
        rel = wsdl_path.relative_to(root)
        details: list[str] = [f"📄 Archivo: {rel}"]

        if ops == -1:
            results.append(CheckResult(
                passed=False,
                message=f"WSDL malformado: {rel}",
                details=details + ["✘ No se pudo parsear el archivo WSDL."]
            ))
            continue

        details.append(f"  Operaciones únicas detectadas: {ops}")
        if op_names:
            details.append(f"  Nombres: {', '.join(op_names)}")

        if ops == 1:
            # Expected: REST + WebFlux
            details.append("  Regla aplicable: 1 operación → REST + WebFlux")
            details.append(f"  WebFlux detectado: {'✔' if framework['webflux'] else '✘'}")
            details.append(f"  MVC NO presente:   {'✔' if not framework['mvc'] else '✘ MVC detectado (no debería estar)'}")

            if framework["mvc"]:
                # MVC confirmado — fallo claro
                results.append(CheckResult(
                    passed=False,
                    message=f"WSDL '{rel.name}': 1 operación — ✘ INCORRECTO (MVC detectado, se esperaba WebFlux)."
                    , details=details
                ))
            elif framework["webflux"]:
                # WebFlux confirmado — correcto
                results.append(CheckResult(
                    passed=True,
                    message=f"WSDL '{rel.name}': 1 operación — ✔ CORRECTO (REST + WebFlux confirmado).",
                    details=details
                ))
            else:
                # No se pudo confirmar ningún framework — pasa con observación
                results.append(CheckResult(
                    passed=True,
                    warning=True,
                    message=f"WSDL '{rel.name}': 1 operación — ⚠ PASA CON OBSERVACIÓN.",
                    details=details,
                    observations=[
                        "No se detectó spring-boot-starter-webflux en los archivos de build.",
                        "Verificar manualmente que el proyecto use REST + WebFlux.",
                    ]
                ))

        else:
            # Expected: SOAP + MVC
            details.append(f"  Regla aplicable: {ops} operaciones únicas → SOAP + MVC")
            details.append(f"  SOAP detectado: {'✔' if framework['soap'] else '✘'}")
            details.append(f"  MVC detectado:  {'✔' if framework['mvc'] else '✘'}")
            details.append(f"  WebFlux NO presente: {'✔' if not framework['webflux'] else '✘ WebFlux detectado (no debería estar)'}")

            if framework["webflux"]:
                # WebFlux confirmado — fallo claro
                results.append(CheckResult(
                    passed=False,
                    message=f"WSDL '{rel.name}': {ops} operaciones — ✘ INCORRECTO (WebFlux detectado, se esperaba SOAP + MVC).",
                    details=details
                ))
            elif framework["mvc"] or framework["soap"]:
                # MVC/SOAP confirmado — correcto
                results.append(CheckResult(
                    passed=True,
                    message=f"WSDL '{rel.name}': {ops} operaciones — ✔ CORRECTO (SOAP + MVC confirmado).",
                    details=details
                ))
            else:
                # No se pudo confirmar ningún framework — pasa con observación
                results.append(CheckResult(
                    passed=True,
                    warning=True,
                    message=f"WSDL '{rel.name}': {ops} operaciones — ⚠ PASA CON OBSERVACIÓN.",
                    details=details,
                    observations=[
                        "No se detectó spring-boot-starter-web ni dependencias SOAP en los archivos de build.",
                        "Verificar manualmente que el proyecto use SOAP + MVC.",
                    ]
                ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION 3 — @BpTraceable in controllers (excluding test controllers)
# ─────────────────────────────────────────────────────────────────────────────

def check_controller_annotation(root: Path) -> CheckResult:
    controllers_ok: list[str] = []
    controllers_missing: list[str] = []
    controllers_skipped: list[str] = []
    details: list[str] = []

    for java_file in find_java_files(root):
        content = file_content(java_file)
        if not is_controller(java_file, content):
            continue

        rel = java_file.relative_to(root)

        # Exclude test controllers — they don't need @BpTraceable
        if is_test_controller(java_file, content):
            controllers_skipped.append(str(rel))
            details.append(f"  ⏭ {rel}  (controlador de test — omitido)")
            continue

        has_annotation = "@BpTraceable" in content

        if has_annotation:
            controllers_ok.append(str(rel))
            details.append(f"  ✔ {rel}")
        else:
            controllers_missing.append(str(rel))
            details.append(f"  ✘ {rel}  ← falta @BpTraceable")

    total = len(controllers_ok) + len(controllers_missing)
    if total == 0 and not controllers_skipped:
        return CheckResult(
            passed=True,
            message="No se encontraron controladores en el proyecto.",
            details=["ℹ Sin controladores detectados."]
        )
    if total == 0 and controllers_skipped:
        return CheckResult(
            passed=True,
            message=f"Solo se encontraron controladores de test ({len(controllers_skipped)}). Ninguno requiere @BpTraceable.",
            details=details
        )

    skipped_note = f"  ({len(controllers_skipped)} controlador(es) de test omitidos)" if controllers_skipped else ""
    passed = len(controllers_missing) == 0
    header = f"Controladores: {len(controllers_ok)}/{total} tienen @BpTraceable.{skipped_note}"
    return CheckResult(passed=passed, message=header, details=details)


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION 4 — @BpLogger in services
# ─────────────────────────────────────────────────────────────────────────────

def check_service_annotation(root: Path) -> CheckResult:
    services_ok: list[str] = []
    services_missing: list[str] = []
    details: list[str] = []

    for java_file in find_java_files(root):
        content = file_content(java_file)
        if not is_service(java_file, content):
            continue

        rel = java_file.relative_to(root)
        has_annotation = "@BpLogger" in content

        if has_annotation:
            services_ok.append(str(rel))
            details.append(f"  ✔ {rel}")
        else:
            services_missing.append(str(rel))
            details.append(f"  ✘ {rel}  ← falta @BpLogger")

    total = len(services_ok) + len(services_missing)
    if total == 0:
        return CheckResult(
            passed=True,
            message="No se encontraron servicios (@Service) en el proyecto.",
            details=["ℹ Sin servicios detectados."]
        )

    passed = len(services_ok) >= 1
    header = f"Servicios: {len(services_ok)}/{total} tienen @BpLogger." + (
        " Al menos uno cumple ✔" if passed else " Ningún servicio tiene @BpLogger."
    )
    return CheckResult(passed=passed, message=header, details=details)


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION 5 — No cross-layer navigation
# ─────────────────────────────────────────────────────────────────────────────

def _is_test_file(path: Path) -> bool:
    """Return True if the file is a test — same criteria used for controllers."""
    name        = path.name
    parts_lower = [p.lower() for p in path.parts]
    return (
        name.endswith("Test.java")
        or name.endswith("Tests.java")
        or "test" in parts_lower
    )


def check_layer_navigation(root: Path) -> CheckResult:
    """
    Detect imports that violate hexagonal boundaries:
      - domain    → must NOT import application or infrastructure
      - application → must NOT import infrastructure
    Test files are excluded from this validation.
    """
    violations:    list[str] = []
    details:       list[str] = []
    files_checked  = 0
    files_skipped  = 0

    for java_file in find_java_files(root):
        layer = detect_layer_of_file(java_file)
        if layer is None or layer not in LAYER_RULES:
            continue

        forbidden = LAYER_RULES[layer]
        if not forbidden:
            continue  # infrastructure has no restrictions

        # Skip test files
        if _is_test_file(java_file):
            files_skipped += 1
            continue

        content = file_content(java_file)
        rel     = java_file.relative_to(root)
        files_checked += 1

        for line_num, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("import "):
                continue
            import_lower = stripped.lower()
            for forbidden_layer in forbidden:
                if f".{forbidden_layer}." in import_lower:
                    violation = (
                        f"  ✘ [{layer.upper()}] {rel}:{line_num}\n"
                        f"      → importa capa '{forbidden_layer}': {stripped}"
                    )
                    violations.append(violation)
                    details.append(violation)

    if files_checked == 0:
        return CheckResult(
            passed=True,
            message="No se encontraron archivos Java (no-test) en capas hexagonales.",
            details=["ℹ Sin archivos de capas detectados."]
        )

    passed = len(violations) == 0
    header = (
        "Sin violaciones de navegación entre capas."
        if passed
        else f"Se encontraron {len(violations)} violación(es) de navegación entre capas."
    )
    skipped_note = f"  Archivos de test omitidos: {files_skipped}" if files_skipped else ""
    summary = [f"  Archivos analizados en capas: {files_checked}"]
    if skipped_note:
        summary.append(skipped_note)
    return CheckResult(passed=passed, message=header, details=summary + details)



# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION 6 — Service Business Logic Purity
# ─────────────────────────────────────────────────────────────────────────────

# JDK / standard library types — a method whose signature ONLY uses these
# types has no contact with the project's own domain model.
_JDK_TYPES: frozenset[str] = frozenset({
    # primitives
    "void", "boolean", "byte", "char", "short", "int", "long", "float", "double",
    # wrappers & strings
    "String", "Integer", "Long", "Boolean", "Byte", "Short", "Float", "Double",
    "Character", "Number", "Object", "CharSequence", "StringBuilder", "StringBuffer",
    # collections
    "List", "Map", "Set", "Collection", "Iterable", "Iterator", "Queue", "Deque",
    "ArrayList", "HashMap", "HashSet", "LinkedList", "LinkedHashMap",
    "TreeMap", "TreeSet", "Optional",
    # time
    "LocalDate", "LocalDateTime", "ZonedDateTime", "OffsetDateTime",
    "Instant", "Date", "Calendar", "Duration", "Period", "Timestamp",
    # math & misc
    "BigDecimal", "BigInteger", "Math", "Random", "Objects",
    "Comparable", "Serializable", "Pattern", "Matcher",
    # common third-party types treated as "non-domain"
    "StringUtils", "ObjectUtils", "CollectionUtils",
})

# Method name prefixes that strongly suggest utility logic, not business logic
_UTILITY_PREFIXES: tuple[str, ...] = (
    "normalize", "pad", "strip", "format", "parse", "convert",
    "keep", "remove", "clean", "sanitize", "encode", "decode",
    "trim", "toJson", "fromJson", "toDto", "fromDto",
    "toModel", "fromModel",
)
# Borderline prefixes: suspicious only if combined with other signals
_BORDERLINE_PREFIXES: tuple[str, ...] = (
    "map", "build", "to", "from",
)

# Regex: direct use of StringUtils / Apache Commons in method body
_STRINGUTILS_RE   = re.compile(r'\bStringUtils\.')
_APACHE_COMMONS_RE = re.compile(
    r'import\s+(org\.apache\.commons|com\.google\.common|'
    r'org\.springframework\.util\.StringUtils)'
)

# Regex: raw string / number manipulation calls that belong in a util class
_STRING_MANIP_RE = re.compile(
    r'(?:'
    r'\.trim\(\)'
    r'|\.substring\s*\('
    r'|\.toLowerCase\s*\('
    r'|\.toUpperCase\s*\('
    r'|\.replace\s*\('
    r'|\.replaceAll\s*\('
    r'|\.split\s*\('
    r'|\.startsWith\s*\('
    r'|\.endsWith\s*\('
    r'|String\.format\s*\('
    r'|String\.valueOf\s*\('
    r'|Long\.parseLong\s*\('
    r'|Integer\.parseInt\s*\('
    r'|Double\.parseDouble\s*\('
    r'|Float\.parseFloat\s*\('
    r'|Pattern\.compile\s*\('
    r')'
)

# Regex: inner records/classes/enums defined inside the service class body
_INNER_TYPE_RE = re.compile(
    r'\b(?:private|protected|public|static)?\s*'
    r'(record|class|enum|interface)\s+(\w+)\s*[({]'
)

# Method declaration extractor (works on comment-stripped source)
_METHOD_DECL_RE = re.compile(
    r'(?m)'
    r'(?P<modifiers>(?:(?:public|protected|private|static|final|synchronized|abstract)\s+)*)'
    r'(?P<return_type>(?:@\w+\s+)?[\w<>\[\]?,\s]+?)\s+'
    r'(?P<name>[a-z_]\w*)\s*'
    r'\((?P<params>[^)]*)\)\s*'
    r'(?:throws\s+[\w,\s]+\s*)?'
    r'\{'
)

# Default suspicion threshold — configurable via --threshold CLI flag
DEFAULT_THRESHOLD = 3

# Score weights: (description, points)
_W = {
    "static":       ("método static en @Service",                3),
    "util_name":    ("nombre con prefijo utilitario",             2),
    "border_name":  ("nombre borderline utilitario",              1),
    "stringutils":  ("llama a StringUtils.* directamente",        2),
    "str_manip":    ("manipulación directa de String/número",     1),  # capped at 2
    "only_jdk":     ("firma sin tipos del dominio propio",        2),
}


def _strip_java_comments(src: str) -> str:
    """Remove // and /* */ comments without touching string literals."""
    src = re.sub(r'//[^\n]*', '', src)
    src = re.sub(r'/\*.*?\*/', ' ', src, flags=re.DOTALL)
    return src


def _extract_body(src: str, match: re.Match) -> str:
    """Return the method body (from '{' to matching '}') via brace counting."""
    pos   = match.end() - 1   # position of opening '{'
    depth = 0
    while pos < len(src):
        c = src[pos]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return src[match.end() - 1 : pos + 1]
        pos += 1
    return src[match.end() - 1:]


def _sig_types(return_type: str, params: str) -> set[str]:
    """Extract capitalised type names from return type + parameter list."""
    types: set[str] = set()

    def harvest(raw: str) -> None:
        raw = re.sub(r'<[^>]*>', '', raw)           # strip generics
        raw = re.sub(r'@\w+(?:\([^)]*\))?\s*', '', raw)  # strip annotations
        raw = raw.replace('[', ' ').replace(']', ' ').replace('?', ' ')
        for tok in raw.split():
            tok = tok.strip(',')
            if tok and tok[0].isupper():
                types.add(tok)

    harvest(return_type)
    for param in params.split(','):
        parts = param.strip().split()
        if parts:
            harvest(parts[0])
    return types


def _collect_project_types(root: Path) -> set[str]:
    """Return all Java class names (stems) in the project — used to detect domain types."""
    return {f.stem for f in find_java_files(root)}


def _score_method(
    name: str,
    modifiers: str,
    return_type: str,
    params: str,
    body: str,
    project_types: set[str],
) -> tuple[int, list[str]]:
    """
    Heuristic scoring for utility-method signals.
    Returns (total_score, list_of_human_readable_signals).
    """
    score   = 0
    signals: list[str] = []

    # ── 1. static method ──────────────────────────────────────────────────────
    if 'static' in modifiers:
        w = _W["static"]
        score += w[1]
        signals.append(f"+{w[1]} {w[0]}")

    # ── 2. utility / borderline name prefix ───────────────────────────────────
    nl = name.lower()
    hit = next((p for p in _UTILITY_PREFIXES  if nl.startswith(p) and len(nl) > len(p)), None)
    if hit:
        w = _W["util_name"]
        score += w[1]
        signals.append(f"+{w[1]} {w[0]}: '{name}' ('{hit}*')")
    else:
        hit = next((p for p in _BORDERLINE_PREFIXES if nl.startswith(p) and len(nl) > len(p)), None)
        if hit:
            w = _W["border_name"]
            score += w[1]
            signals.append(f"+{w[1]} {w[0]}: '{name}' ('{hit}*')")

    # ── 3. StringUtils.* calls ────────────────────────────────────────────────
    if _STRINGUTILS_RE.search(body):
        w = _W["stringutils"]
        score += w[1]
        signals.append(f"+{w[1]} {w[0]}")

    # ── 4. raw string/number manipulation (max +2) ────────────────────────────
    manip_hits = list(dict.fromkeys(_STRING_MANIP_RE.findall(body)))
    if manip_hits:
        pts = min(len(manip_hits), 2)
        score += pts
        preview = ', '.join(m.strip() for m in manip_hits[:3])
        signals.append(f"+{pts} {_W['str_manip'][0]}: {preview}")

    # ── 5. signature with only JDK types (no domain types at all) ────────────
    types = _sig_types(return_type, params)
    non_jdk = types - _JDK_TYPES
    domain_hits = non_jdk & project_types
    if types and not domain_hits:
        w = _W["only_jdk"]
        score += w[1]
        signals.append(f"+{w[1]} {w[0]}")

    return score, signals


def check_service_business_logic(root: Path, threshold: int = DEFAULT_THRESHOLD) -> CheckResult:
    """
    Validate that @Service classes contain only business logic.

    Per-method heuristic scoring:
      +3  método static en @Service
      +2  nombre con prefijo utilitario  (normalize*, pad*, strip*, format*, ...)
      +1  nombre borderline              (map*, build*, to*, from*)
      +2  llama a StringUtils.*
      +1  manipulación directa de String/número (capped +2)
      +2  firma sin tipos del dominio propio

    Un método se reporta como sospechoso si score ≥ threshold (default: {threshold}).
    """
    project_types = _collect_project_types(root)

    suspicious_files: list[str] = []
    clean_files:      list[str] = []
    details:          list[str] = []
    total_services = 0

    for java_file in find_java_files(root):
        content = file_content(java_file)
        if not is_service(java_file, content):
            continue

        total_services += 1
        rel    = java_file.relative_to(root)
        clean  = _strip_java_comments(content)

        file_issues: list[str] = []

        # ── File-level: utility library imports ───────────────────────────────
        for imp_match in _APACHE_COMMONS_RE.finditer(content):
            file_issues.append(
                f"  ⚠  Import de librería utilitaria detectado: "
                f"'{imp_match.group(1)}.*'  → considera moverlo a una clase Util"
            )

        # ── File-level: inner records / classes / enums ───────────────────────
        outer_name = java_file.stem
        for m in _INNER_TYPE_RE.finditer(clean):
            kw   = m.group(1)
            iname = m.group(2)
            if iname == outer_name:
                continue   # skip the outer class declaration itself
            file_issues.append(
                f"  ⚠  {kw} '{iname}' definido dentro del @Service "
                f"→ debería vivir en domain/model/ o en una clase util dedicada"
            )

        # ── Per-method scoring ────────────────────────────────────────────────
        method_issues: list[str] = []
        for m in _METHOD_DECL_RE.finditer(clean):
            mname     = m.group('name')
            modifiers = m.group('modifiers') or ''
            ret_type  = (m.group('return_type') or '').strip()
            params    = m.group('params') or ''
            body      = _extract_body(clean, m)
            line      = clean[:m.start()].count('\n') + 1

            score, signals = _score_method(
                mname, modifiers, ret_type, params, body, project_types
            )

            if score >= threshold:
                level = "✘" if score >= threshold + 2 else "⚠"
                method_issues.append(
                    f"  {level} ~línea {line}:  {ret_type} {mname}(...)  "
                    f"[score {score} / umbral {threshold}]"
                )
                for sig in signals:
                    method_issues.append(f"       {sig}")

        all_issues = file_issues + method_issues
        if all_issues:
            suspicious_files.append(str(rel))
            details.append(f"  ✘ {rel}")
            details.extend(all_issues)
            details.append("")
        else:
            clean_files.append(str(rel))
            details.append(f"  ✔ {rel}")

    if total_services == 0:
        return CheckResult(
            passed=True,
            message="No se encontraron servicios (@Service) en el proyecto.",
            details=["ℹ Sin servicios detectados."]
        )

    passed = len(suspicious_files) == 0
    header = (
        f"Servicios con lógica de negocio pura: "
        f"{len(clean_files)}/{total_services}. "
        + ("Todos limpios ✔" if passed
           else f"{len(suspicious_files)} servicio(s) con posibles métodos utilitarios.")
    )
    footer = [
        "",
        f"  ℹ Umbral de sospecha configurado: score ≥ {threshold}",
        "  ℹ Señales: static(+3) | nombre util(+2) | StringUtils(+2) | "
        "solo tipos JDK(+2) | manipulación string(+1~2) | nombre borderline(+1)",
        "  ℹ Revisar manualmente antes de refactorizar — pueden existir falsos positivos.",
    ]
    return CheckResult(passed=passed, message=header, details=details + footer)



# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION 7 — application.yml: variables sin valores por defecto
# ─────────────────────────────────────────────────────────────────────────────

# Spring variable expression with a non-empty default: ${VAR:default}
# Group 1 → variable name   |   Group 2 → default value
_YML_VAR_DEFAULT_RE = re.compile(r'\$\{([^}:]+):([^}]+)\}')

# YAML property path prefixes excluidos de la validación.
# Exact match y prefix match (path == excl  OR  path.startswith(excl + "."))
YML_EXCLUDED_PREFIXES: frozenset[str] = frozenset({
    "optimus.web",
})


def _find_yml_files(root: Path) -> list[Path]:
    """
    Return only application.yml files (exact name), excluding any path
    that contains a 'test' directory segment (src/test/..., testIntegration/...).
    application-profile.yml variants are intentionally excluded.
    """
    found: list[Path] = []
    seen:  set[Path]  = set()
    for candidate in root.rglob("application.yml"):
        # Exclude files living under any test directory segment
        parts_lower = [p.lower() for p in candidate.parts[:-1]]  # skip filename itself
        if any(p == "test" or p.startswith("test") for p in parts_lower):
            continue
        if candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    return found


def _is_excluded(path: str) -> bool:
    """Return True if the dotted YAML path should be skipped."""
    return any(
        path == excl or path.startswith(excl + ".")
        for excl in YML_EXCLUDED_PREFIXES
    )


def _walk_yaml_node(
    node: yaml.Node,
    path: str,
    violations: list[dict],
) -> None:
    """
    Recursively walk a PyYAML composed node tree.
    Collects violations where a scalar value contains ${VAR:non-empty-default}.
    """
    if isinstance(node, yaml.MappingNode):
        for key_node, val_node in node.value:
            key      = key_node.value
            new_path = f"{path}.{key}" if path else key
            _walk_yaml_node(val_node, new_path, violations)

    elif isinstance(node, yaml.SequenceNode):
        for idx, item in enumerate(node.value):
            _walk_yaml_node(item, f"{path}[{idx}]", violations)

    elif isinstance(node, yaml.ScalarNode):
        value    = node.value or ""
        line_num = node.start_mark.line + 1  # PyYAML uses 0-indexed lines

        if _is_excluded(path):
            return

        for m in _YML_VAR_DEFAULT_RE.finditer(value):
            var_name    = m.group(1).strip()
            default_val = m.group(2)
            violations.append({
                "path":        path,
                "var_name":    var_name,
                "default":     default_val,
                "full_value":  value,
                "line":        line_num,
            })


def _scan_yml_fallback(content: str, rel_path: Path) -> list[dict]:
    """
    Line-by-line fallback for malformed YAML.
    Scans for ${VAR:default} in any line, reports line number.
    No path tracking — uses raw line content instead.
    """
    violations = []
    for line_num, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        # Skip comment lines
        if stripped.startswith("#"):
            continue
        for m in _YML_VAR_DEFAULT_RE.finditer(stripped):
            var_name    = m.group(1).strip()
            default_val = m.group(2)
            violations.append({
                "path":        f"(línea {line_num} — YAML no parseable)",
                "var_name":    var_name,
                "default":     default_val,
                "full_value":  stripped,
                "line":        line_num,
            })
    return violations


def check_application_yml(root: Path) -> CheckResult:
    """
    Validates that application.yml files do NOT use Spring variables with
    hardcoded default values.

    CORRECT:   server.port: ${SERVER_PORT}
    INCORRECT: server.port: ${SERVER_PORT:8080}

    Excluded paths (optimus.web.*) are allowed to have hardcoded values.
    """
    yml_files = _find_yml_files(root)

    if not yml_files:
        return CheckResult(
            passed=True,
            message="No se encontraron archivos application.yml en el proyecto.",
            details=["ℹ Sin application.yml detectado — validación omitida."]
        )

    all_violations: list[dict] = []
    details: list[str] = []
    files_with_issues: list[str] = []
    files_clean: list[str] = []

    for yml_path in yml_files:
        content = file_content(yml_path)
        rel     = yml_path.relative_to(root)
        violations: list[dict] = []

        # ── Primary: PyYAML node-level walk (gives exact paths + line numbers)
        try:
            node = yaml.compose(content)
            if node is not None:
                _walk_yaml_node(node, "", violations)
        except yaml.YAMLError:
            # ── Fallback: regex line scan
            violations = _scan_yml_fallback(content, rel)

        if violations:
            files_with_issues.append(str(rel))
            details.append(f"  ✘ {rel}  ({len(violations)} violación(es))")
            for v in violations:
                # Build the "fix" suggestion by stripping the default
                fix = v["full_value"].replace(
                    f"${{{v['var_name']}:{v['default']}}}",
                    f"${{{v['var_name']}}}",
                )
                details.append(
                    f"       Línea {v['line']:>4}  [{v['path']}]"
                )
                details.append(
                    f"              Actual:     {v['full_value']}"
                )
                details.append(
                    f"              Corregido:  {fix}"
                )
            all_violations.extend(violations)
        else:
            files_clean.append(str(rel))
            details.append(f"  ✔ {rel}")

    total     = len(yml_files)
    n_issues  = len(files_with_issues)
    n_violations = len(all_violations)
    passed    = n_violations == 0

    header = (
        f"application.yml: {total - n_issues}/{total} archivo(s) sin valores por defecto. "
        + ("Todos correctos ✔" if passed
           else f"{n_violations} variable(s) con default en {n_issues} archivo(s).")
    )
    footer = [
        "",
        "  ℹ Regla: ${VAR:valor_por_defecto} → debe ser ${VAR}",
        f"  ℹ Rutas excluidas: {', '.join(sorted(YML_EXCLUDED_PREFIXES))}.*",
    ]
    return CheckResult(passed=passed, message=header, details=details + footer)


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION 8 — Gradle: librería obligatoria Banco Pichincha
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_LIBRARY   = "com.pichincha.bnc:lib-bnc-api-client:1.1.0"
_LIB_BNC_RE        = re.compile(r"com\.pichincha(?:\.bnc)?:(lib-[\w\-]+(?::\S+)?)")
_GRADLE_DEP_RE     = re.compile(
    r"""(?:implementation|api|compileOnly|runtimeOnly)\s*[('"]([^'")\s]+)['")]"""
)


def _find_gradle_files(root: Path) -> list[Path]:
    found = list(root.glob("**/build.gradle")) + list(root.glob("**/build.gradle.kts"))
    return [f for f in found if "test" not in [p.lower() for p in f.parts]]


def _collect_bnc_libs_from_gradle(root: Path) -> set[str]:
    """Return all com.pichincha lib-* dependencies declared in any Gradle file."""
    libs: set[str] = set()
    for gf in _find_gradle_files(root):
        content = file_content(gf)
        for m in _GRADLE_DEP_RE.finditer(content):
            dep = m.group(1)
            if "com.pichincha" in dep and "lib-" in dep:
                # Normalise to  lib-name:version  (strip group)
                parts = dep.split(":")
                if len(parts) >= 2:
                    libs.add(":".join(parts[1:]))   # e.g. lib-bnc-api-client:1.1.0
    return libs


def check_gradle_library(root: Path) -> CheckResult:
    """
    Verifica que al menos un build.gradle declare la librería obligatoria:
      implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0'
    """
    gradle_files = _find_gradle_files(root)
    details: list[str] = []

    if not gradle_files:
        return CheckResult(
            passed=False,
            message="No se encontraron archivos build.gradle en el proyecto.",
            details=["✘ Sin Gradle — no se puede verificar la librería obligatoria."],
        )

    found_required = False
    for gf in gradle_files:
        content = file_content(gf)
        rel     = gf.relative_to(root)
        if REQUIRED_LIBRARY in content:
            found_required = True
            details.append(f"  ✔ {rel}  →  '{REQUIRED_LIBRARY}' presente")
        else:
            details.append(f"  ✘ {rel}  →  '{REQUIRED_LIBRARY}' NO encontrada")

    passed = found_required
    header = (
        f"Librería obligatoria '{REQUIRED_LIBRARY}' "
        + ("✔ encontrada." if passed else "✘ NO declarada en ningún build.gradle.")
    )
    return CheckResult(passed=passed, message=header, details=details)


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION 9 — catalog-info.yaml
# ─────────────────────────────────────────────────────────────────────────────

_AZURE_URL_RE    = re.compile(
    r"https://dev\.azure\.com/BancoPichinchaEC/([\w\-]+)/_git/([\w\-]+)",
    re.IGNORECASE,
)
_CONFLUENCE_RE   = re.compile(
    r"https://pichincha\.atlassian\.net/wiki/spaces", re.IGNORECASE
)
_UUID_RE         = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_OWNER_EMAIL_RE  = re.compile(r".+@pichincha\.com$", re.IGNORECASE)

REQUIRED_METADATA = {
    "namespace":   "tnd-middleware",
    "name":        "tpl-middleware",
}
FORBIDDEN_DESCRIPTION = "comming soon"
REQUIRED_LIFECYCLE    = "test"


def _load_catalog(root: Path) -> tuple[Optional[Path], Optional[dict], str]:
    """Find and parse catalog-info.yaml. Returns (path, data, error_msg)."""
    candidates = list(root.glob("catalog-info.yaml")) + list(root.glob("catalog-info.yml"))
    if not candidates:
        return None, None, "No se encontró catalog-info.yaml en la raíz del proyecto."
    path = candidates[0]
    try:
        data = yaml.safe_load(file_content(path))
        return path, data, ""
    except yaml.YAMLError as e:
        return path, None, f"Error parseando catalog-info.yaml: {e}"


def check_catalog_info(root: Path) -> CheckResult:
    """
    Valida catalog-info.yaml:
      metadata : namespace, name, description (≠ 'comming soon')
      links    : [0] URL Azure DevOps válida con BancoPichinchaEC/tpl-middleware
                 [2] URL Confluence con pichincha.atlassian.net/wiki/spaces
      annotations: dev.azure.com/project-repo  →  <proyecto>/<repositorio>
                   sonarcloud.io/project-key    →  UUID estándar
      spec     : owner con @pichincha.com
                 dependsOn incluye las lib-bnc-* usadas en Gradle
                 lifecycle = 'test'
    """
    catalog_path, data, err = _load_catalog(root)
    details: list[str] = []

    if err:
        return CheckResult(passed=False, message=err, details=[f"  ✘ {err}"])

    rel    = catalog_path.relative_to(root)
    errors = 0

    def ok(msg: str):
        details.append(f"  ✔ {msg}")

    def fail(msg: str):
        nonlocal errors
        errors += 1
        details.append(f"  ✘ {msg}")

    # ── metadata ──────────────────────────────────────────────────────────────
    details.append("── metadata")
    metadata = data.get("metadata") or {}

    for field_name, expected in REQUIRED_METADATA.items():
        val = str(metadata.get(field_name, "")).strip()
        if val == expected:
            ok(f"metadata.{field_name} = '{val}'")
        else:
            fail(f"metadata.{field_name}: esperado '{expected}', encontrado '{val or '(vacío)'}'")

    description = str(metadata.get("description", "")).strip()
    if not description:
        fail("metadata.description está vacío")
    elif description.lower() == FORBIDDEN_DESCRIPTION.lower():
        fail(f"metadata.description sigue siendo el placeholder '{FORBIDDEN_DESCRIPTION}'")
    else:
        ok(f"metadata.description está definida: '{description[:60]}'")

    # ── links ─────────────────────────────────────────────────────────────────
    details.append("── links")
    links = data.get("spec", {}).get("links", []) or []
    # Try top-level links too (Backstage supports both)
    if not links:
        links = metadata.get("links", []) or []

    azure_url    = ""
    azure_project = ""
    azure_repo    = ""

    # link[0] — Azure DevOps
    if len(links) < 1:
        fail("links[0] no existe — se esperaba URL Azure DevOps")
    else:
        url0 = str((links[0] or {}).get("url", "")).strip()
        m    = _AZURE_URL_RE.search(url0)
        if m:
            azure_project = m.group(1)
            azure_repo    = m.group(2)
            azure_url     = url0
            ok(f"links[0] URL Azure DevOps válida: {url0}")
        else:
            fail(
                f"links[0] no es una URL Azure DevOps válida con "
                f"'https://dev.azure.com/BancoPichinchaEC/tpl-middleware'. "
                f"Valor: '{url0 or '(vacío)'}'"
            )

    # link[2] — Confluence
    if len(links) < 3:
        fail("links[2] no existe — se esperaba URL Confluence")
    else:
        url2 = str((links[2] or {}).get("url", "")).strip()
        if _CONFLUENCE_RE.search(url2):
            ok(f"links[2] URL Confluence válida: {url2}")
        else:
            fail(
                f"links[2] no contiene 'https://pichincha.atlassian.net/wiki/spaces'. "
                f"Valor: '{url2 or '(vacío)'}'"
            )

    # ── annotations ───────────────────────────────────────────────────────────
    details.append("── annotations")
    annotations = metadata.get("annotations") or {}

    # dev.azure.com/project-repo
    proj_repo = str(annotations.get("dev.azure.com/project-repo", "")).strip()
    if azure_project and azure_repo:
        expected_pr = f"{azure_project}/{azure_repo}"
        if proj_repo == expected_pr:
            ok(f"annotations dev.azure.com/project-repo = '{proj_repo}'")
        else:
            fail(
                f"annotations dev.azure.com/project-repo: "
                f"esperado '{expected_pr}' (de links[0]), encontrado '{proj_repo or '(vacío)'}'"
            )
    else:
        if proj_repo:
            ok(f"annotations dev.azure.com/project-repo = '{proj_repo}' (sin URL Azure para validar formato)")
        else:
            fail("annotations dev.azure.com/project-repo está vacío")

    # sonarcloud.io/project-key
    sonar_key = str(annotations.get("sonarcloud.io/project-key", "")).strip()
    if _UUID_RE.match(sonar_key):
        ok(f"annotations sonarcloud.io/project-key = '{sonar_key}' (UUID válido)")
    else:
        fail(
            f"annotations sonarcloud.io/project-key no es un UUID válido. "
            f"Patrón esperado: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx. "
            f"Valor: '{sonar_key or '(vacío)'}'"
        )

    # ── spec ──────────────────────────────────────────────────────────────────
    details.append("── spec")
    spec = data.get("spec") or {}

    # owner
    owner = str(spec.get("owner", "")).strip()
    if _OWNER_EMAIL_RE.match(owner):
        ok(f"spec.owner = '{owner}'")
    else:
        fail(
            f"spec.owner debe ser un usuario @pichincha.com. "
            f"Valor: '{owner or '(vacío)'}'"
        )

    # lifecycle
    lifecycle = str(spec.get("lifecycle", "")).strip()
    if lifecycle == REQUIRED_LIFECYCLE:
        ok(f"spec.lifecycle = '{lifecycle}'")
    else:
        fail(
            f"spec.lifecycle debe ser '{REQUIRED_LIFECYCLE}'. "
            f"Valor: '{lifecycle or '(vacío)'}'"
        )

    # dependsOn — must include every lib-bnc-* used in Gradle
    depends_on   = spec.get("dependsOn") or []
    gradle_libs  = _collect_bnc_libs_from_gradle(root)
    details.append(f"  ℹ Librerías Banco Pichincha en Gradle: {', '.join(sorted(gradle_libs)) or 'ninguna'}")

    for lib in sorted(gradle_libs):
        lib_name    = lib.split(":")[0]  # e.g. lib-bnc-api-client
        # Accept  component:lib-name  or  component:lib-name:version
        in_depends  = any(lib_name in str(d) for d in depends_on)
        if in_depends:
            ok(f"spec.dependsOn incluye '{lib_name}'")
        else:
            fail(
                f"spec.dependsOn no incluye 'component:{lib_name}' "
                f"(librería usada en Gradle: {lib})"
            )

    if not gradle_libs and not depends_on:
        ok("spec.dependsOn: sin librerías Banco Pichincha que verificar")

    passed  = errors == 0
    header  = (
        f"catalog-info.yaml ({rel}): "
        + ("todas las validaciones correctas ✔" if passed
           else f"{errors} campo(s) con errores.")
    )
    return CheckResult(passed=passed, message=header, details=details)


# ─────────────────────────────────────────────────────────────────────────────
# MARKDOWN REPORT
# ─────────────────────────────────────────────────────────────────────────────

STATUS_ICON = {True: "✅", False: "❌", None: "⚠️"}
BADGE_PASS = "![PASS](https://img.shields.io/badge/status-PASS-brightgreen)"
BADGE_FAIL = "![FAIL](https://img.shields.io/badge/status-FAIL-red)"


BADGE_WARN = "![WARN](https://img.shields.io/badge/status-WARN-yellow)"

def _check_section(
    title: str,
    check: Optional[CheckResult],
    section_num: int
) -> list[str]:
    if check is None:
        return [f"### {section_num}. {title}", "", "> ⚠️ Validación no ejecutada.", ""]

    if check.warning:
        badge = BADGE_WARN
        icon  = "⚠️"
    else:
        icon  = STATUS_ICON[check.passed]
        badge = BADGE_PASS if check.passed else BADGE_FAIL

    lines = [
        f"### {section_num}. {title}  {badge}",
        "",
        f"{icon} **{check.message}**",
        "",
    ]
    if check.details:
        lines.append("```")
        lines.extend(check.details)
        lines.append("```")
        lines.append("")
    if check.observations:
        lines.append("> **⚠ Observaciones para revisión manual:**")
        for obs in check.observations:
            lines.append(f"> - {obs}")
        lines.append("")
    return lines


def _wsdl_sections(wsdl_checks: list[CheckResult], start_num: int) -> list[str]:
    lines = []
    all_passed  = all(c.passed for c in wsdl_checks)
    any_warning = any(c.warning  for c in wsdl_checks)
    if not all_passed:
        overall_badge = BADGE_FAIL
        overall_icon  = "❌"
        overall_msg   = "Hay WSDL que no cumplen la regla REST/SOAP."
    elif any_warning:
        overall_badge = BADGE_WARN
        overall_icon  = "⚠️"
        overall_msg   = "WSDL pasan con observaciones — verificar framework manualmente."
    else:
        overall_badge = BADGE_PASS
        overall_icon  = "✅"
        overall_msg   = "Todos los WSDL cumplen la regla REST/SOAP."

    lines += [
        f"### {start_num}. Validación WSDL → Framework  {overall_badge}",
        "",
        f"{overall_icon} **{overall_msg}**",
        "",
    ]
    for i, check in enumerate(wsdl_checks, 1):
        if check.warning:
            sub_icon = "⚠️"
        else:
            sub_icon = STATUS_ICON[check.passed]
        lines.append(f"#### WSDL {i}: {sub_icon} {check.message}")
        lines.append("")
        if check.details:
            lines.append("```")
            lines.extend(check.details)
            lines.append("```")
            lines.append("")
        if check.observations:
            lines.append("> **⚠ Observaciones para revisión manual:**")
            for obs in check.observations:
                lines.append(f"> - {obs}")
            lines.append("")
    return lines


def generate_markdown(report: ValidationReport) -> str:
    # Compute overall
    checks_results = [
        report.layers_check.passed if report.layers_check else None,
        all(c.passed for c in report.wsdl_checks) if report.wsdl_checks else True,
        report.controller_annotation_check.passed if report.controller_annotation_check else None,
        report.service_annotation_check.passed if report.service_annotation_check else None,
        report.layer_navigation_check.passed if report.layer_navigation_check else None,
        report.service_business_logic_check.passed if report.service_business_logic_check else None,
        report.application_yml_check.passed if report.application_yml_check else None,
    ]
    total    = len([c for c in checks_results if c is not None])
    passed   = len([c for c in checks_results if c is True])
    all_ok   = passed == total
    overall  = "🟢 APROBADO" if all_ok else "🔴 REVISAR"
    overall_badge = BADGE_PASS if all_ok else BADGE_FAIL

    lines: list[str] = [
        "# 📋 Reporte de Validación — Arquitectura Hexagonal",
        "",
        f"> **Proyecto:** `{report.project_path}`  ",
        f"> **Fecha:**    `{report.timestamp}`  ",
        f"> **Resultado:** {overall}  {overall_badge}",
        "",
        "---",
        "",
        "## 🔍 Resumen Ejecutivo",
        "",
        f"| Checks automatizados pasados | {passed} / {total} |",
        "|---|---|",
        f"| Capas válidas | {'✅' if (report.layers_check and report.layers_check.passed) else '❌'} |",
        f"| WSDL / Framework correcto | {('⚠️' if any(c.warning for c in report.wsdl_checks) else '✅') if all(c.passed for c in report.wsdl_checks) else ('✅ N/A' if not report.wsdl_checks else '❌')} |",
        f"| @BpTraceable en controladores (excl. tests) | {'✅' if (report.controller_annotation_check and report.controller_annotation_check.passed) else '❌'} |",
        f"| @BpLogger en servicios | {'✅' if (report.service_annotation_check and report.service_annotation_check.passed) else '❌'} |",
        f"| Sin navegación cruzada entre capas | {'✅' if (report.layer_navigation_check and report.layer_navigation_check.passed) else '❌'} |",
        f"| Servicios con lógica de negocio pura | {'✅' if (report.service_business_logic_check and report.service_business_logic_check.passed) else '❌'} |",
        f"| application.yml sin valores por defecto | {'✅' if (report.application_yml_check and report.application_yml_check.passed) else '❌'} |",
        f"| Librería obligatoria lib-bnc-api-client | {'✅' if (report.gradle_library_check and report.gradle_library_check.passed) else '❌'} |",
        f"| catalog-info.yaml válido | {'✅' if (report.catalog_info_check and report.catalog_info_check.passed) else '❌'} |",
        "",
        "---",
        "",
        "## ✅ Checks Automatizados",
        "",
    ]

    # Section 1 – Layers
    lines += _check_section(
        "Estructura de Capas (application / domain / infrastructure)",
        report.layers_check,
        1
    )

    # Section 2 – WSDL
    if report.wsdl_checks:
        lines += _wsdl_sections(report.wsdl_checks, 2)
    else:
        lines += [
            "### 2. Validación WSDL → Framework  " + BADGE_PASS,
            "",
            "✅ **No se encontraron archivos WSDL. Validación omitida.**",
            "",
        ]

    # Section 3 – Controllers
    lines += _check_section(
        "Anotación @BpTraceable en Controladores (excluye tests)",
        report.controller_annotation_check,
        3
    )

    # Section 4 – Services annotation
    lines += _check_section(
        "Anotación @BpLogger en Servicios",
        report.service_annotation_check,
        4
    )

    # Section 5 – Layer navigation
    lines += _check_section(
        "Sin Navegación Cruzada entre Capas",
        report.layer_navigation_check,
        5
    )

    # Section 6 – Service business logic
    lines += _check_section(
        "Service Business Logic — Servicios sin métodos utilitarios",
        report.service_business_logic_check,
        6
    )

    # Scoring legend for section 6
    lines += [
        "> **Leyenda de scores (sección 6):**  ",
        "> `static (+3)` · `nombre util (+2)` · `StringUtils (+2)` · "
        "`solo tipos JDK (+2)` · `manip. string (+1~2)` · `nombre borderline (+1)`  ",
        "> Un método se reporta si su score ≥ umbral configurado (default: 3).",
        "",
    ]

    # Section 7 – application.yml
    lines += _check_section(
        "application.yml — Variables sin valores por defecto",
        report.application_yml_check,
        7
    )

    # Section 8 – Gradle required library
    lines += _check_section(
        "Gradle — Librería obligatoria Banco Pichincha",
        report.gradle_library_check,
        8
    )

    # Section 9 – catalog-info.yaml
    lines += _check_section(
        "catalog-info.yaml — Metadata, Links, Annotations y Specs",
        report.catalog_info_check,
        9
    )

    # Manual review section (items 2 and 4 now automated)
    lines += [
        "---",
        "",
        "## 🔎 Revisión Manual Requerida",
        "",
        "> Los siguientes puntos no pueden ser validados automáticamente y requieren revisión humana.",
        "",
        "| # | Ítem de Revisión | Responsable | Estado |",
        "|---|---|---|---|",
        "| 1 | **Archivos Helm** — Verificar values.yaml, templates/, Chart.yaml: recursos, límites, variables de entorno, secrets y configuración de réplicas. | Dev / DevOps | ⬜ Pendiente |",
        "| 2 | **Archivos de migración** — Confirmar que NO existen archivos Flyway (`V*.sql`) ni Liquibase (`changelog*.xml/yaml`) si no son requeridos por la arquitectura. | Dev | ⬜ Pendiente |",
        "| 3 | **Confirmación manual check 6** — Los métodos flaggeados por el score heurístico pueden tener falsos positivos. Confirmar con el Tech Lead si cada método señalado realmente debe extraerse a una clase util. | Tech Lead | ⬜ Pendiente |",
        "",
        "---",
        "",
        "## 📐 Reglas de Arquitectura Hexagonal Aplicadas",
        "",
        "```",
        "┌─────────────────────────────────────────────────────┐",
        "│                   INFRAESTRUCTURA                   │",
        "│  (Controllers, Repositories, Clients, Config, etc.) │",
        "│                        │                            │",
        "│               implements/uses                       │",
        "│                        ▼                            │",
        "│              APLICACIÓN (Use Cases)                 │",
        "│           (Orchestration, DTOs, Ports)              │",
        "│                        │                            │",
        "│               implements/uses                       │",
        "│                        ▼                            │",
        "│                    DOMINIO                          │",
        "│         (Entities, Business Rules, Events)          │",
        "│                  ← NÚCLEO PURO →                    │",
        "└─────────────────────────────────────────────────────┘",
        "",
        "Reglas de importación:",
        "  domain       → NO puede importar application ni infrastructure",
        "  application  → NO puede importar infrastructure",
        "  infrastructure → puede importar domain y application",
        "```",
        "",
        "---",
        "",
        f"*Reporte generado automáticamente por `validate_hexagonal.py` el {report.timestamp}*",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CONSOLE OUTPUT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def color_result(passed: bool) -> str:
    return f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"


def print_check(title: str, check: Optional[CheckResult]):
    if check is None:
        print(f"  {YELLOW}⚠  {title}: no ejecutado{RESET}")
        return
    if check.warning:
        print(f"  [{YELLOW}WARN{RESET}] {title}")
        for o in check.observations:
            print(f"         ⚠ {o}")
    else:
        status = color_result(check.passed)
        print(f"  [{status}] {title}")
        if not check.passed:
            for d in check.details:
                print(f"         {d}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run_validations(project_path: str, output_dir: Optional[str], threshold: int = DEFAULT_THRESHOLD) -> ValidationReport:
    root = Path(project_path).resolve()
    if not root.exists():
        print(f"{RED}Error: El directorio '{root}' no existe.{RESET}")
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report = ValidationReport(project_path=str(root), timestamp=timestamp)

    print(f"\n{BOLD}{CYAN}═══════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}{CYAN}   Validador de Arquitectura Hexagonal — Java{RESET}")
    print(f"{BOLD}{CYAN}═══════════════════════════════════════════════════════{RESET}")
    print(f"  Proyecto: {root}")
    print(f"  Fecha:    {timestamp}\n")

    print(f"\n{BOLD}[ 1/9 ] Validando estructura de capas...{RESET}")
    report.layers_check = check_layers(root)
    print_check("Capas hexagonales", report.layers_check)

    print(f"\n{BOLD}[ 2/9 ] Validando WSDL y framework...{RESET}")
    report.wsdl_checks = check_wsdl(root)
    for wc in report.wsdl_checks:
        print_check(f"WSDL: {wc.message[:60]}", wc)

    print(f"\n{BOLD}[ 3/9 ] Validando @BpTraceable en controladores (excluye tests)...{RESET}")
    report.controller_annotation_check = check_controller_annotation(root)
    print_check("@BpTraceable", report.controller_annotation_check)

    print(f"\n{BOLD}[ 4/9 ] Validando @BpLogger en servicios...{RESET}")
    report.service_annotation_check = check_service_annotation(root)
    print_check("@BpLogger", report.service_annotation_check)

    print(f"\n{BOLD}[ 5/9 ] Validando navegación entre capas...{RESET}")
    report.layer_navigation_check = check_layer_navigation(root)
    print_check("Sin navegación cruzada", report.layer_navigation_check)

    print(f"\n{BOLD}[ 6/9 ] Validando lógica de negocio en servicios (umbral={threshold})...{RESET}")
    report.service_business_logic_check = check_service_business_logic(root, threshold)
    print_check("Service Business Logic", report.service_business_logic_check)

    print(f"\n{BOLD}[ 7/9 ] Validando application.yml...{RESET}")
    report.application_yml_check = check_application_yml(root)
    print_check("application.yml sin defaults", report.application_yml_check)

    print(f"\n{BOLD}[ 8/9 ] Validando librería obligatoria en Gradle...{RESET}")
    report.gradle_library_check = check_gradle_library(root)
    print_check("lib-bnc-api-client", report.gradle_library_check)

    print(f"\n{BOLD}[ 9/9 ] Validando catalog-info.yaml...{RESET}")
    report.catalog_info_check = check_catalog_info(root)
    print_check("catalog-info.yaml", report.catalog_info_check)

    # Generate markdown
    md_content = generate_markdown(report)

    out_dir = Path(output_dir) if output_dir else root
    out_dir.mkdir(parents=True, exist_ok=True)
    md_file = out_dir / f"hexagonal_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    md_file.write_text(md_content, encoding="utf-8")

    # Summary
    checks = [
        report.layers_check,
        report.controller_annotation_check,
        report.service_annotation_check,
        report.layer_navigation_check,
        report.service_business_logic_check,
        report.application_yml_check,
        report.gradle_library_check,
        report.catalog_info_check,
    ] + report.wsdl_checks

    passed_count = sum(1 for c in checks if c and c.passed)
    total_count  = len([c for c in checks if c is not None])

    print(f"\n{BOLD}{'═' * 55}{RESET}")
    overall_color = GREEN if passed_count == total_count else RED
    print(
        f"  {BOLD}Resultado: {overall_color}{passed_count}/{total_count} checks pasados{RESET}"
    )
    print(f"  Reporte guardado en: {CYAN}{md_file}{RESET}")
    print(f"{BOLD}{'═' * 55}{RESET}\n")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Validador de arquitectura hexagonal para proyectos Java.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python validate_hexagonal.py /ruta/a/mi/proyecto
  python validate_hexagonal.py /ruta/a/mi/proyecto --output ./reportes
  python validate_hexagonal.py . --output /tmp/reports --threshold 4
        """
    )
    parser.add_argument(
        "project_path",
        help="Ruta al directorio raíz del proyecto Java."
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Directorio donde guardar el reporte Markdown (default: raíz del proyecto)."
    )
    parser.add_argument(
        "--threshold", "-t",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=f"Umbral de score para la validación de lógica de negocio (default: {DEFAULT_THRESHOLD}). "
             "Subir a 4-5 para menos falsos positivos, bajar a 2 para más estrictez."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Exportar también un resumen JSON junto al Markdown."
    )

    args   = parser.parse_args()
    report = run_validations(args.project_path, args.output, args.threshold)

    if args.json:
        out_dir = Path(args.output) if args.output else Path(args.project_path).resolve()
        json_file = out_dir / f"hexagonal_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        summary = {
            "project_path": report.project_path,
            "timestamp": report.timestamp,
            "threshold_business_logic": args.threshold,
            "layers_check": {"passed": report.layers_check.passed, "message": report.layers_check.message} if report.layers_check else None,
            "wsdl_checks": [{"passed": c.passed, "message": c.message} for c in report.wsdl_checks],
            "controller_annotation_check": {"passed": report.controller_annotation_check.passed, "message": report.controller_annotation_check.message} if report.controller_annotation_check else None,
            "service_annotation_check": {"passed": report.service_annotation_check.passed, "message": report.service_annotation_check.message} if report.service_annotation_check else None,
            "layer_navigation_check": {"passed": report.layer_navigation_check.passed, "message": report.layer_navigation_check.message} if report.layer_navigation_check else None,
            "service_business_logic_check": {"passed": report.service_business_logic_check.passed, "message": report.service_business_logic_check.message} if report.service_business_logic_check else None,
            "application_yml_check": {"passed": report.application_yml_check.passed, "message": report.application_yml_check.message} if report.application_yml_check else None,
            "gradle_library_check": {"passed": report.gradle_library_check.passed, "message": report.gradle_library_check.message} if report.gradle_library_check else None,
            "catalog_info_check": {"passed": report.catalog_info_check.passed, "message": report.catalog_info_check.message} if report.catalog_info_check else None,
        }
        json_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  JSON guardado en: {json_file}\n")


if __name__ == "__main__":
    main()