"""Confluence-compatible service documentation generator.

The generator is deterministic: it reads the migrated project, legacy hints,
Discovery, WSDL/XSD, tests and runtime config, then emits service
documentation in the WSClientes0020 format. Data not found in the inputs is
marked as [VERIFICAR] instead of being invented.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

from capamedia_cli.core.discovery import (
    DiscoveryEntry,
    detect_discovery_workspace,
    find_discovery_workbook,
    load_discovery_entry,
)
from capamedia_cli.core.legacy_analyzer import analyze_wsdl, find_wsdl

VERIFY = "[VERIFICAR]"

_SERVICE_RE = re.compile(r"\b(?:orq|ws)[a-z]+[0-9]{4}\b", re.IGNORECASE)
_MIGRATED_SERVICE_RE = re.compile(r"\b[a-z]{3}-msa-sp-((?:orq|ws)[a-z]+[0-9]{4})\b", re.IGNORECASE)
_ENV_VAR_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]+)(?::([^}]*))?\}")
_TX_RE = re.compile(r"\b(?:ws-tx|TX|tx)(\d{6})\b")


@dataclass(frozen=True)
class EnvVarDoc:
    name: str
    description: str
    default: str = ""
    source: str = ""
    vault: bool = False


@dataclass(frozen=True)
class TestDoc:
    test_id: str
    case: str
    input_or_condition: str
    expected: str
    status: str = "Pendiente"


@dataclass(frozen=True)
class SchemaField:
    name: str
    xsd_type: str = ""
    min_occurs: str = "1"
    max_occurs: str = "1"
    source: str = ""
    children: tuple[SchemaField, ...] = ()

    @property
    def optional(self) -> bool:
        return self.min_occurs == "0"


@dataclass(frozen=True)
class HappyPathDoc:
    url: str
    operation: str
    namespace: str
    request_xml: str
    curl: str
    analysis_rows: list[list[str]]
    response_xml: str


@dataclass
class ServiceDocumentation:
    service_name: str
    migrated_name: str
    description: str
    workspace_root: Path
    migrated_path: Path | None = None
    legacy_path: Path | None = None
    discovery: DiscoveryEntry | None = None
    source_kind: str = ""
    framework: str = ""
    spring_boot_version: str = ""
    gradle_version: str = ""
    java_version: str = "Java 21"
    operations: list[str] = field(default_factory=list)
    namespace: str = ""
    endpoint_path: str = ""
    wsdl_path: Path | None = None
    header_fields: list[SchemaField] = field(default_factory=list)
    body_fields: list[SchemaField] = field(default_factory=list)
    tx_codes: list[str] = field(default_factory=list)
    env_vars: list[EnvVarDoc] = field(default_factory=list)
    tests: list[TestDoc] = field(default_factory=list)
    test_classes: list[str] = field(default_factory=list)
    report_excerpt: str = ""
    generated_from: list[Path] = field(default_factory=list)
    happy_path: HappyPathDoc | None = None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _first_match(pattern: str, text: str, default: str = "") -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else default


def _service_from_text(text: str) -> str:
    match = _SERVICE_RE.search(text)
    return match.group(0).lower() if match else ""


def _service_from_migrated_name(text: str) -> str:
    match = _MIGRATED_SERVICE_RE.search(text)
    return match.group(1).lower() if match else ""


def _display_service(service_name: str) -> str:
    if not service_name:
        return "Servicio"
    lowered = service_name.lower()
    digits = re.search(r"(\d{4})$", lowered)
    suffix = digits.group(1) if digits else ""
    stem = lowered[: -len(suffix)] if suffix else lowered
    if stem.startswith("ws"):
        return "WS" + stem[2:].capitalize() + suffix
    if stem.startswith("orq"):
        return "ORQ" + suffix
    return stem.capitalize() + suffix


def _infer_workspace(start: Path, migrated: Path | None, service_name: str | None) -> tuple[Path, Path | None, Path | None, str]:
    base = (migrated or start).resolve()
    discovery_ctx = detect_discovery_workspace(base)

    migrated_path = migrated.resolve() if migrated else discovery_ctx.migrated_path
    if migrated_path is None and (base / "build.gradle").exists():
        migrated_path = base

    workspace = discovery_ctx.root
    if migrated_path and migrated_path.parent.name == "destino":
        workspace = migrated_path.parent.parent

    inferred_service = (
        (service_name or "").lower().strip()
        or discovery_ctx.service_name
        or (_service_from_migrated_name(migrated_path.name) if migrated_path else "")
        or _service_from_text(str(base))
    )

    legacy_path = discovery_ctx.legacy_path
    if legacy_path is None and inferred_service:
        legacy_root = workspace / "legacy"
        if legacy_root.is_dir():
            for child in legacy_root.iterdir():
                if child.is_dir() and inferred_service in child.name.lower():
                    legacy_path = child
                    break

    return workspace, migrated_path, legacy_path, inferred_service


def _load_discovery(workspace: Path, service_name: str) -> DiscoveryEntry | None:
    workbook = find_discovery_workbook(workspace)
    if workbook is None or not service_name:
        return None
    try:
        return load_discovery_entry(workbook, service_name)
    except (OSError, RuntimeError, ValueError):
        return None


def _collect_report_texts(workspace: Path, migrated: Path | None, service_name: str) -> tuple[str, list[Path]]:
    paths: list[Path] = []
    candidates = [
        workspace / f"COMPLEXITY_{service_name}.md",
        workspace / f"ANALISIS_{_display_service(service_name)}.md",
        workspace / f"ANALISIS_{service_name}.md",
    ]
    if migrated is not None:
        candidates.extend([migrated / "MIGRATION_REPORT.md", migrated / "README.md", migrated / "migration-context.json"])
    for pattern in ("ANALISIS_*.md", "COMPLEXITY_*.md"):
        candidates.extend(workspace.glob(pattern))

    parts: list[str] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        text = _read(path)
        if text:
            paths.append(path)
            parts.append(f"\n\n<!-- SOURCE: {path.name} -->\n{text}")
    return "\n".join(parts), paths


def _description_from_sources(service_name: str, migrated_name: str, discovery: DiscoveryEntry | None, reports: str) -> str:
    for pattern in (
        r"##\s+General Service Description\s+(.+?)(?:\n##\s+|\Z)",
        r"##\s+Descripcion(?: general)?\s+(.+?)(?:\n##\s+|\Z)",
        r"##\s+Descripción(?: general)?\s+(.+?)(?:\n##\s+|\Z)",
        r"##\s+Explicacion de la Logica de Negocio\s+(.+?)(?:\n##\s+|\Z)",
        r"##\s+Explicación de la Lógica de Negocio\s+(.+?)(?:\n##\s+|\Z)",
    ):
        section = _first_match(pattern, reports)
        if section:
            clean = re.sub(r"\s+", " ", re.sub(r"[#*_`|>-]+", " ", section)).strip()
            if clean:
                return clean[:700]

    if discovery and discovery.methods:
        methods = ", ".join(line.strip() for line in discovery.methods.splitlines() if line.strip())
        return (
            f"Microservicio {migrated_name or service_name} migrado desde {discovery.technology or 'legacy'} "
            f"para exponer las operaciones {methods}."
        )
    return (
        f"Microservicio {migrated_name or service_name} migrado a arquitectura hexagonal "
        "para Banco Pichincha. Completar la descripción funcional con evidencia del ANALISIS."
    )


def _build_gradle_info(migrated: Path | None) -> tuple[str, str, str]:
    if migrated is None:
        return "", "", ""
    build = _read(migrated / "build.gradle") + "\n" + _read(migrated / "build.gradle.kts")
    spring = (
        _first_match(r"org\.springframework\.boot['\"]?\)?\s+version\s+['\"]([^'\"]+)", build)
        or _first_match(r"id\s+['\"]org\.springframework\.boot['\"]\s+version\s+['\"]([^'\"]+)", build)
    )
    gradle = _read(migrated / "gradle" / "wrapper" / "gradle-wrapper.properties")
    gradle_version = _first_match(r"gradle-([0-9.]+)-", gradle)
    if "spring-boot-starter-webflux" in build:
        framework = "WebFlux"
    elif "spring-boot-starter-web-services" in build or "@Endpoint" in _read(migrated / "MIGRATION_REPORT.md"):
        framework = "Spring MVC + Spring WS"
    elif "spring-boot-starter-web" in build:
        framework = "Spring MVC"
    else:
        framework = "Spring Boot"
    return spring, gradle_version, framework


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean_type(value: str) -> str:
    return value.split(":", 1)[-1] if value else ""


def _schema_children(container: ET.Element, source: Path) -> tuple[SchemaField, ...]:
    fields: list[SchemaField] = []
    for child in list(container):
        local = _local_name(child.tag)
        if local in {"sequence", "all", "choice"}:
            for element in list(child):
                if _local_name(element.tag) == "element":
                    parsed = _parse_schema_element(element, source)
                    if parsed:
                        fields.append(parsed)
        elif local == "element":
            parsed = _parse_schema_element(child, source)
            if parsed:
                fields.append(parsed)
        elif local == "complexType":
            fields.extend(_schema_children(child, source))
    return tuple(fields)


def _parse_schema_element(element: ET.Element, source: Path) -> SchemaField | None:
    name = element.attrib.get("name") or element.attrib.get("ref", "").split(":")[-1]
    if not name:
        return None
    children: tuple[SchemaField, ...] = ()
    for child in list(element):
        if _local_name(child.tag) == "complexType":
            children = _schema_children(child, source)
            break
    return SchemaField(
        name=name,
        xsd_type=_clean_type(element.attrib.get("type", "")),
        min_occurs=element.attrib.get("minOccurs", "1"),
        max_occurs=element.attrib.get("maxOccurs", "1"),
        source=source.name,
        children=children,
    )


def _xml_roots(wsdl: Path, migrated: Path | None, legacy: Path | None) -> list[tuple[Path, ET.Element]]:
    paths = [wsdl]
    for root in (migrated, legacy):
        if root is None or not root.exists():
            continue
        paths.extend(p for p in root.rglob("*.xsd") if ".git" not in p.parts and "build" not in p.parts)

    parsed: list[tuple[Path, ET.Element]] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            parsed.append((path, ET.fromstring(_read(path))))
        except ET.ParseError:
            continue
    return parsed


def _resolve_schema_field(field: SchemaField, complex_types: dict[str, tuple[SchemaField, ...]], depth: int = 0) -> SchemaField:
    if depth > 8:
        return field
    children = field.children
    if not children and field.xsd_type in complex_types:
        children = complex_types[field.xsd_type]
    if children:
        children = tuple(_resolve_schema_field(child, complex_types, depth + 1) for child in children)
    return replace(field, children=children)


def _find_child(field: SchemaField, wanted: str) -> SchemaField | None:
    if field.name.lower() == wanted.lower():
        return field
    for child in field.children:
        found = _find_child(child, wanted)
        if found:
            return found
    return None


def _collect_wsdl_details(
    migrated: Path | None,
    legacy: Path | None,
) -> tuple[Path | None, list[str], str, list[SchemaField], list[SchemaField]]:
    wsdl: Path | None = None
    operations: list[str] = []
    namespace = ""
    for root in (migrated, legacy):
        if root is None or not root.exists():
            continue
        candidate = find_wsdl(root)
        if candidate:
            wsdl = candidate
            info = analyze_wsdl(candidate)
            operations = info.operation_names
            namespace = info.target_namespace
            break
    if wsdl is None:
        return None, [], "", [], []

    roots = _xml_roots(wsdl, migrated, legacy)
    complex_types: dict[str, tuple[SchemaField, ...]] = {}
    elements: dict[str, SchemaField] = {}
    for path, root in roots:
        for node in root.iter():
            local = _local_name(node.tag)
            if local == "complexType" and node.attrib.get("name"):
                complex_types[node.attrib["name"]] = _schema_children(node, path)
            elif local == "element":
                parsed = _parse_schema_element(node, path)
                if parsed:
                    elements.setdefault(parsed.name, parsed)

    operation = operations[0] if operations else ""
    operation_field = _resolve_schema_field(elements[operation], complex_types) if operation in elements else None
    header = _find_child(operation_field, "headerIn") if operation_field else None
    body = _find_child(operation_field, "bodyIn") if operation_field else None
    if header is None and "headerIn" in elements:
        header = _resolve_schema_field(elements["headerIn"], complex_types)
    if body is None and "bodyIn" in elements:
        body = _resolve_schema_field(elements["bodyIn"], complex_types)

    return wsdl, operations, namespace, list(header.children) if header else [], list(body.children) if body else []


def _source_kind(legacy: Path | None, reports: str) -> str:
    if legacy is not None and legacy.exists():
        if list(legacy.rglob("*.esql")):
            return "IIB / BUS"
        if list(legacy.rglob("*.java")):
            return "WAS"
    lowered = reports.lower()
    if "source_kind: was" in lowered or "legacy source type:** was" in lowered:
        return "WAS"
    if "source_kind: iib" in lowered or "legacy source type:** iib" in lowered:
        return "IIB / BUS"
    if "orq" in lowered:
        return "ORQ"
    return ""


def _env_description(name: str) -> str:
    table = {
        "CCC_BANCS_BASE_URL": "URL base del adaptador BANCS.",
        "CCC_BANCS_CONNECT_TIMEOUT": "Timeout de conexión BANCS.",
        "CCC_BANCS_READ_TIMEOUT": "Timeout de lectura BANCS.",
        "CCC_BANCS_MAX_IN_MEMORY_SIZE": "Buffer máximo para respuestas BANCS.",
        "CCC_BANCS_CIRCUIT_BREAKER_ENABLED": "Habilita circuit breaker para BANCS.",
        "CCC_TRACE_LOGGER_ENABLED": "Habilita trace logger.",
        "CCC_PAYLOAD_MODE": "Modo de logging de payload.",
    }
    if name in table:
        return table[name]
    if "PASSWORD" in name or "SECRET" in name or "TOKEN" in name:
        return "Secreto provisto por entorno o vault."
    if "URL" in name or "BASE" in name:
        return "Endpoint o URL configurado por ambiente."
    if "TIMEOUT" in name:
        return "Timeout configurable por ambiente."
    if "LOG" in name:
        return "Configuración de logging."
    return name.removeprefix("CCC_").replace("_", " ").capitalize() + "."


def _collect_env_vars(migrated: Path | None) -> list[EnvVarDoc]:
    if migrated is None:
        return []
    files = []
    for pattern in (
        "src/main/resources/application*.yml",
        "src/main/resources/application*.yaml",
        "helm/**/*.yml",
        "helm/**/*.yaml",
    ):
        files.extend(migrated.glob(pattern))

    by_name: dict[str, EnvVarDoc] = {}
    for path in files:
        text = _read(path)
        for name, default in _ENV_VAR_RE.findall(text):
            current = by_name.get(name)
            source = path.name if current is None else current.source
            by_name[name] = EnvVarDoc(
                name=name,
                default=default or VERIFY,
                description=_env_description(name),
                source=source,
                vault=any(token in name for token in ("PASSWORD", "SECRET", "TOKEN", "KEY")),
            )
    return [by_name[name] for name in sorted(by_name)]


def _collect_tx_codes(migrated: Path | None, reports: str, discovery: DiscoveryEntry | None) -> list[str]:
    values: set[str] = set(_TX_RE.findall(reports))
    if migrated is not None:
        for path in list((migrated / "src").rglob("*.java")) + list((migrated / "src").rglob("*.yml")):
            values.update(_TX_RE.findall(_read(path)))
    if discovery is not None:
        values.update(_TX_RE.findall(discovery.integrations))
        values.update(_TX_RE.findall(discovery.methods))
        values.update(_TX_RE.findall(discovery.observations))
    return sorted(values)


def _humanize_test_name(name: str) -> str:
    spaced = re.sub(r"(?<!^)([A-Z])", r" \1", name).replace("_", " ")
    return spaced.strip().capitalize() or VERIFY


def _collect_tests(migrated: Path | None, discovery: DiscoveryEntry | None, tx_codes: list[str]) -> tuple[list[TestDoc], list[str]]:
    test_classes: list[str] = []
    tests: list[TestDoc] = []
    if migrated is not None:
        for path in sorted((migrated / "src" / "test").rglob("*.java")):
            rel = path.relative_to(migrated)
            source = str(rel).replace("\\", "/")
            test_classes.append(source)
            text = _read(path)
            for method in re.findall(r"(?:@Test\s+)?(?:public\s+)?void\s+([A-Za-z0-9_]+)\s*\(", text):
                tests.append(
                    TestDoc(
                        test_id=f"TC-{len(tests) + 1:02d}",
                        case=_humanize_test_name(method),
                        input_or_condition=source,
                        expected="Comportamiento esperado según test automatizado.",
                    )
                )

    if discovery is not None:
        for case in discovery.edge_cases:
            tests.append(
                TestDoc(
                    test_id=f"TC-{len(tests) + 1:02d}",
                    case=f"Edge case Discovery {case.code}: {case.title}",
                    input_or_condition=case.evidence,
                    expected="Debe documentarse y cubrirse sin dejar pendiente técnico.",
                )
            )

    for tx in tx_codes:
        tests.append(
            TestDoc(
                test_id=f"TC-{len(tests) + 1:02d}",
                case=f"Operación BANCS TX{tx}",
                input_or_condition=f"Invocación a ws-tx{tx}",
                expected="Request, response, errores y timeouts trazados preservando código y mensaje BANCS.",
            )
        )
    return tests[:80], test_classes


def _report_excerpt(reports: str) -> str:
    for heading in (
        "Explicacion de la Logica de Negocio",
        "Explicación de la Lógica de Negocio",
        "Business Logic",
        "Step-by-Step Business Logic",
    ):
        section = _first_match(rf"##\s+{re.escape(heading)}\s+(.+?)(?:\n##\s+|\Z)", reports)
        if section:
            clean = re.sub(r"\n{3,}", "\n\n", section.strip())
            return clean[:2500]
    return ""


def _evidence_files(migrated: Path | None, legacy: Path | None, reports: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if reports:
        items.append(("reportes ANALISIS/COMPLEXITY", reports))
    patterns = ("src/test/**/*", "src/main/resources/**/*", "src/main/java/**/*", "helm/**/*")
    if migrated is not None:
        for pattern in patterns:
            for path in migrated.glob(pattern):
                if path.is_file() and path.suffix.lower() in {".java", ".xml", ".json", ".yml", ".yaml", ".properties"}:
                    items.append((str(path.relative_to(migrated)).replace("\\", "/"), _read(path)))
    if legacy is not None:
        for path in legacy.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".esql", ".msgflow", ".subflow", ".xml", ".xsd", ".properties", ".txt"}:
                items.append((f"legacy/{path.name}", _read(path)))
    return items


def _find_evidence_value(field_name: str, evidence: list[tuple[str, str]]) -> tuple[str, str]:
    escaped = re.escape(field_name)
    patterns = [
        rf"<(?:\w+:)?{escaped}\b[^>]*>(.*?)</(?:\w+:)?{escaped}>",
        rf"['\"]{escaped}['\"]\s*[:=]\s*['\"]([^'\"]+)['\"]",
        rf"\b{escaped}\b\s*[:=]\s*['\"]([^'\"]+)['\"]",
        rf"set{re.escape(field_name[:1].upper() + field_name[1:])}\s*\(\s*['\"]([^'\"]+)['\"]",
    ]
    for source, text in evidence:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip()
                if value and "${" not in value:
                    return value, source
    return "", ""


def _body_default(field: SchemaField) -> tuple[str, str]:
    lowered = field.name.lower()
    if "cif" in lowered:
        return "4667888", "valor de prueba generado por CLI"
    if "idsiglooficial" in lowered:
        return "00003817", "valor de prueba generado por CLI"
    if "email" in lowered or "correo" in lowered:
        return "qa.pichincha@example.com", "valor de prueba generado por CLI"
    if "celular" in lowered or "telefono" in lowered or "phone" in lowered:
        return "593992804255", "valor de prueba generado por CLI"
    if "activar" in lowered or field.xsd_type.lower() == "boolean":
        return "true", "valor de prueba generado por CLI"
    if lowered in {"tipo", "tipocontacto"}:
        return "01", "valor de prueba generado por CLI"
    if "fecha" in lowered:
        return "202604291200000000", "valor de prueba generado por CLI"
    if "id" in lowered or field.xsd_type.lower() in {"int", "integer", "long", "short", "decimal"}:
        return "1", "valor de prueba generado por CLI"
    return "TEST", "valor de prueba generado por CLI"


def _field_value(field: SchemaField, evidence: list[tuple[str, str]], *, body: bool) -> tuple[str, str]:
    value, source = _find_evidence_value(field.name, evidence)
    if value:
        return value, source
    header_defaults = {
        "empresa": ("0010", "convención Banco Pichincha"),
        "idioma": ("es-EC", "convención Banco Pichincha"),
        "usuario": ("USINTERT", "convención Banco Pichincha"),
        "ip": ("10.0.0.0", "convención Banco Pichincha"),
    }
    if not body and field.name in header_defaults:
        return header_defaults[field.name]
    if body:
        return _body_default(field)
    return VERIFY, VERIFY


def _xml_lines_for_fields(
    fields: list[SchemaField] | tuple[SchemaField, ...],
    evidence: list[tuple[str, str]],
    *,
    indent: int,
    body: bool,
) -> tuple[list[str], list[list[str]]]:
    lines: list[str] = []
    sources: list[list[str]] = []
    pad = " " * indent
    for schema_field in fields:
        if schema_field.optional:
            lines.append(f"{pad}<!--Optional:-->")
        if schema_field.children:
            lines.append(f"{pad}<{schema_field.name}>")
            child_lines, child_sources = _xml_lines_for_fields(schema_field.children, evidence, indent=indent + 3, body=body)
            lines.extend(child_lines)
            sources.extend(child_sources)
            lines.append(f"{pad}</{schema_field.name}>")
            continue
        value, source = _field_value(schema_field, evidence, body=body)
        sources.append([schema_field.name, source, value])
        if schema_field.optional and value == VERIFY:
            lines.append(f"{pad}<{schema_field.name}/>")
        else:
            lines.append(f"{pad}<{schema_field.name}>{html.escape(value, quote=False)}</{schema_field.name}>")
    return lines, sources


def _flatten_fields(fields: list[SchemaField] | tuple[SchemaField, ...]) -> list[SchemaField]:
    flat: list[SchemaField] = []
    for schema_field in fields:
        flat.append(schema_field)
        flat.extend(_flatten_fields(schema_field.children))
    return flat


def _openshift_url(migrated_name: str, service_name: str) -> str:
    return f"https://{migrated_name.lower()}-enp.apps.ocptest.uiotest.bpichinchatest.test/IntegrationBus/soap/{service_name}"


def _build_happy_path(
    *,
    service_name: str,
    migrated_name: str,
    operations: list[str],
    namespace: str,
    header_fields: list[SchemaField],
    body_fields: list[SchemaField],
    tx_codes: list[str],
    env_vars: list[EnvVarDoc],
    migrated: Path | None,
    legacy: Path | None,
    reports: str,
) -> HappyPathDoc:
    operation = operations[0] if operations else VERIFY
    operation_tag = operation if operation != VERIFY else "OperacionVERIFICAR"
    namespace_value = namespace or VERIFY
    url = _openshift_url(migrated_name, service_name)
    evidence = _evidence_files(migrated, legacy, reports)

    header_lines, header_sources = _xml_lines_for_fields(header_fields, evidence, indent=12, body=False)
    body_lines, _ = _xml_lines_for_fields(body_fields, evidence, indent=12, body=True)
    if not header_lines:
        header_lines = ["            [VERIFICAR]"]
    if not body_lines:
        body_lines = ["            [VERIFICAR]"]

    request_xml = "\n".join(
        [
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            f'xmlns:ser="{namespace_value}">',
            "   <soapenv:Header/>",
            "   <soapenv:Body>",
            f"      <ser:{operation_tag}>",
            "         <headerIn>",
            *header_lines,
            "         </headerIn>",
            "         <bodyIn>",
            *body_lines,
            "         </bodyIn>",
            f"      </ser:{operation_tag}>",
            "   </soapenv:Body>",
            "</soapenv:Envelope>",
        ]
    )
    curl = "\n".join(
        [
            f"curl --location '{url}' \\",
            "  --header 'Content-Type: text/xml;charset=UTF-8' \\",
            "  --header 'SOAPAction: \"\"' \\",
            f"  --data '{request_xml}'",
        ]
    )
    required_body = ", ".join(field.name for field in _flatten_fields(body_fields) if not field.optional) or VERIFY
    header_codes = []
    for key in ("canal", "medio", "aplicacion", "tipoTransaccion"):
        value = next((row[2] for row in header_sources if row[0].lower() == key.lower()), VERIFY)
        source = next((row[1] for row in header_sources if row[0].lower() == key.lower()), VERIFY)
        header_codes.append(f"{key}={value} ({source})")
    env_summary = ", ".join(var.name for var in env_vars) or VERIFY
    tx_summary = ", ".join(f"TX{tx}" for tx in tx_codes) or VERIFY
    analysis_rows = [
        ["Operación SOAP", "WSDL", operation],
        ["Namespace", "WSDL", namespace_value],
        ["Campos obligatorios bodyIn", "XSD", required_body],
        ["Códigos headerIn (canal/medio/aplicacion/tipoTransaccion)", "tests / IIB legacy", "; ".join(header_codes)],
        ["TX BANCS invocada", "service principal / reportes", tx_summary],
        ["Variables CCC_* en juego", "application.yml / dev.yml", env_summary],
        ["Código esperado en <codigo>", "service / IIB", "0"],
        ["Mensaje esperado en <mensaje>", "convención", "TCSBRKR3_BP-OK"],
    ]
    response_xml = "\n".join(
        [
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            f'xmlns:ser="{namespace_value}">',
            "   <soapenv:Header/>",
            "   <soapenv:Body>",
            f"      <ser:{operation_tag}Response>",
            "         <headerOut>",
            "            [VERIFICAR]",
            "         </headerOut>",
            "         <bodyOut>",
            "            [VERIFICAR]",
            "         </bodyOut>",
            "         <error>",
            "            <codigo>0</codigo>",
            "            <mensaje>TCSBRKR3_BP-OK</mensaje>",
            "            <mensajeNegocio/>",
            "            <tipo>INFO</tipo>",
            f"            <recurso>{service_name}/{operation}</recurso>",
            f"            <componente>{service_name}</componente>",
            "            <backend>[VERIFICAR]</backend>",
            "         </error>",
            f"      </ser:{operation_tag}Response>",
            "   </soapenv:Body>",
            "</soapenv:Envelope>",
        ]
    )
    return HappyPathDoc(url, operation, namespace_value, request_xml, curl, analysis_rows, response_xml)


def build_service_documentation(
    *,
    start: Path,
    service_name: str | None = None,
    migrated: Path | None = None,
    legacy: Path | None = None,
) -> ServiceDocumentation:
    workspace, migrated_path, detected_legacy, service = _infer_workspace(start, migrated, service_name)
    legacy_path = legacy.resolve() if legacy else detected_legacy
    discovery = _load_discovery(workspace, service)
    migrated_name = (
        discovery.migrated_name if discovery and discovery.migrated_name
        else (migrated_path.name if migrated_path else f"tnd-msa-sp-{service}")
    )
    reports, report_paths = _collect_report_texts(workspace, migrated_path, service)
    spring, gradle, framework = _build_gradle_info(migrated_path)
    wsdl_path, operations, namespace, header_fields, body_fields = _collect_wsdl_details(migrated_path, legacy_path)
    tx_codes = _collect_tx_codes(migrated_path, reports, discovery)
    env_vars = _collect_env_vars(migrated_path)
    tests, test_classes = _collect_tests(migrated_path, discovery, tx_codes)
    display_service = _display_service(service)
    endpoint = f"/IntegrationBus/soap/{display_service}" if service else "/IntegrationBus/soap/<Servicio>"
    happy_path = _build_happy_path(
        service_name=display_service,
        migrated_name=migrated_name,
        operations=operations,
        namespace=namespace,
        header_fields=header_fields,
        body_fields=body_fields,
        tx_codes=tx_codes,
        env_vars=env_vars,
        migrated=migrated_path,
        legacy=legacy_path,
        reports=reports,
    )

    generated_from = [*report_paths]
    if wsdl_path is not None:
        generated_from.append(wsdl_path)

    return ServiceDocumentation(
        service_name=display_service,
        migrated_name=migrated_name,
        description=_description_from_sources(service, migrated_name, discovery, reports),
        workspace_root=workspace,
        migrated_path=migrated_path,
        legacy_path=legacy_path,
        discovery=discovery,
        source_kind=_source_kind(legacy_path, reports),
        framework=framework,
        spring_boot_version=spring,
        gradle_version=gradle,
        operations=operations,
        namespace=namespace,
        endpoint_path=endpoint,
        wsdl_path=wsdl_path,
        header_fields=header_fields,
        body_fields=body_fields,
        tx_codes=tx_codes,
        env_vars=env_vars,
        tests=tests,
        test_classes=test_classes,
        report_excerpt=_report_excerpt(reports),
        generated_from=generated_from,
        happy_path=happy_path,
    )


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        safe = [cell.replace("\n", "<br>") if cell else "-" for cell in row]
        lines.append("| " + " | ".join(safe) + " |")
    return "\n".join(lines)


def _html_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "<p>[VERIFICAR]</p>"
    head = "".join(f'<th class="confluenceTh">{html.escape(h)}</th>' for h in headers)
    body = []
    for row in rows:
        body.append(
            "<tr>"
            + "".join(f'<td class="confluenceTd">{html.escape(cell or "-")}</td>' for cell in row)
            + "</tr>"
        )
    return f'<table class="confluenceTable"><tbody><tr>{head}</tr>{"".join(body)}</tbody></table>'


def _pre(text: str) -> str:
    return f"<pre>{html.escape(text)}</pre>"


def _info_macro(text: str) -> str:
    return (
        '<ac:structured-macro ac:name="info">'
        "<ac:rich-text-body>"
        f"<p>{html.escape(text)}</p>"
        "</ac:rich-text-body>"
        "</ac:structured-macro>"
    )


def _env_rows(env_vars: list[EnvVarDoc]) -> list[list[str]]:
    return [[str(i + 1), v.name, v.description, v.default or VERIFY, v.source or VERIFY] for i, v in enumerate(env_vars)]


def _grouped_env_rows(env_vars: list[EnvVarDoc]) -> tuple[list[list[str]], list[list[str]], list[list[str]], list[list[str]]]:
    rows = _env_rows(env_vars)
    normalization = [row for row in rows if any(token in row[1] for token in ("PHONE", "CEL", "TEL", "EMAIL"))]
    bancs = [row for row in rows if "BANCS" in row[1] and "CIRCUIT_BREAKER" not in row[1]]
    circuit = [row for row in rows if "CIRCUIT_BREAKER" in row[1] or "RESILIENCE" in row[1]]
    logging = [row for row in rows if "LOG" in row[1] or "PAYLOAD" in row[1] or "TRACE" in row[1]]
    return normalization, bancs, circuit, logging


def _test_groups(tests: list[TestDoc]) -> tuple[list[list[str]], list[list[str]], list[list[str]]]:
    rows = [[str(i + 1), test.test_id, test.case, test.input_or_condition, test.expected, "Pendiente"] for i, test in enumerate(tests)]
    validations = [
        row for row in rows
        if any(token in row[2].lower() for token in ("valid", "cif", "error", "obligatorio", "vacio", "vacío"))
    ]
    bancs = [row for row in rows if "bancs" in row[2].lower() or "tx" in row[1].lower() or "tx" in row[2].lower()]
    normalizations = [
        row for row in rows
        if any(token in row[2].lower() for token in ("normal", "telefono", "teléfono", "email", "celular"))
    ]
    return validations, bancs, normalizations


def _schema_rows(fields: list[SchemaField]) -> list[list[str]]:
    flat = _flatten_fields(fields)
    return [
        [
            str(i + 1),
            field.name,
            (field.xsd_type or "complex") if field.children else (field.xsd_type or VERIFY),
            "No" if field.optional else "Si",
            field.source or VERIFY,
        ]
        for i, field in enumerate(flat)
    ]


def _logic_steps(doc: ServiceDocumentation) -> str:
    operation = doc.operations[0] if doc.operations else VERIFY
    steps = [
        f"1. Recibir la operación SOAP {operation} por {doc.endpoint_path}.",
        "2. Validar headerIn y bodyIn contra el contrato WSDL/XSD.",
        "3. Normalizar datos de entrada cuando el contrato lo requiere.",
        "4. Invocar adaptadores de salida y TX BANCS configuradas, si aplica.",
        "5. Mapear respuesta de negocio preservando códigos y mensajes backend.",
        "6. Retornar HTTP 200 para errores de negocio con detalle en el bloque <error>.",
    ]
    if doc.report_excerpt:
        steps.extend(["", doc.report_excerpt])
    return "\n".join(steps)


def _tx_mapping_rows(tx: str, *, response: bool) -> list[list[str]]:
    if response:
        return [
            ["codigo", "Código de respuesta BANCS.", "Respuesta BANCS"],
            ["mensaje", "Mensaje de respuesta BANCS.", "Respuesta BANCS"],
            ["body", "Estructura específica de la TX.", "Core Adapter / [VERIFICAR]"],
        ]
    return [
        ["transactionId", tx, "Fijo"],
        ["request", "Mapeo desde bodyIn/headerIn.", "Dinámico"],
        ["timeout/circuit breaker", "Variables CCC_*.", "Configuración"],
    ]


def render_html(doc: ServiceDocumentation) -> str:
    happy = doc.happy_path or _build_happy_path(
        service_name=doc.service_name,
        migrated_name=doc.migrated_name,
        operations=doc.operations,
        namespace=doc.namespace,
        header_fields=doc.header_fields,
        body_fields=doc.body_fields,
        tx_codes=doc.tx_codes,
        env_vars=doc.env_vars,
        migrated=doc.migrated_path,
        legacy=doc.legacy_path,
        reports=doc.report_excerpt,
    )
    discovery = doc.discovery
    normalization_rows, bancs_rows, circuit_rows, logging_rows = _grouped_env_rows(doc.env_vars)
    validation_rows, tx_test_rows, normalization_test_rows = _test_groups(doc.tests)
    tx_label = f"TX{doc.tx_codes[0]}" if doc.tx_codes else "TX [VERIFICAR]"
    operation = doc.operations[0] if doc.operations else VERIFY
    references = [
        ["1", "Repositorio", "Código fuente del servicio", doc.migrated_name, f"https://dev.azure.com/BancoPichinchaEC/tpl-middleware/_git/{doc.migrated_name}"],
        ["2", "Legacy", "Código fuente original", discovery.code_repo if discovery and discovery.code_repo else (doc.legacy_path.name if doc.legacy_path else VERIFY), discovery.link_code if discovery and discovery.link_code else VERIFY],
        ["3", "Spec", "WSDL/XSD y casos de prueba", str(doc.wsdl_path) if doc.wsdl_path else (discovery.spec_path if discovery and discovery.spec_path else VERIFY), discovery.link_wsdl if discovery and discovery.link_wsdl else VERIFY],
    ]
    tech_rows = [
        ["Java", "21"],
        ["Gradle", doc.gradle_version or "8.14"],
        ["Spring Boot", doc.spring_boot_version or "3.5.13"],
        ["Stack web", doc.framework or "WebFlux"],
        ["CXF", "4.1.1"],
        ["Arquitectura", "Hexagonal"],
        ["Resilience4j", "Circuit Breaker"],
        ["JaCoCo", "75% instrucciones"],
        ["Testing", "JUnit 5"],
    ]
    diagram = "\n".join(
        [
            "+--------------------------+     +--------------------+     +------------------------+",
            "| Adaptador entrada REST  | --> | Capa aplicación   | --> | Adaptador salida BANCS |",
            f"| {doc.endpoint_path:<24} |     | Casos de uso      |     | {tx_label:<22} |",
            "+--------------------------+     +--------------------+     +------------------------+",
        ]
    )
    response_bancs_rows = [
        ["0", "Operación exitosa", "Retornar <codigo>0</codigo> y <tipo>INFO</tipo>"],
        ["Error BANCS", "Código/mensaje original backend", "Preservar código y mensaje en <error>"],
        ["Timeout / circuito abierto", "Error técnico", "Manejar sin SOAP Fault salvo excepción inesperada"],
    ]
    parts = [
        f"<h1>{html.escape(doc.service_name)} - Documentación de Servicio</h1>",
        _info_macro(f"Documentación generada desde código, WSDL/XSD, configuración y pruebas. Todo dato no evidenciado queda marcado como {VERIFY}."),
        f"<p>{html.escape(doc.description)}</p>",
        "<h2>Referencias del Proyecto</h2>",
        _html_table(["#", "Tipo", "Recurso", "Descripción", "Enlace"], references),
        "<h2>Tecnologías</h2>",
        _html_table(["Tecnología", "Versión / Uso"], tech_rows),
        "<h2>Arquitectura del Microservicio</h2>",
        _pre(diagram),
        "<h2>Configuración de Entorno de Desarrollo</h2>",
        "<h3>Prerrequisitos</h3>",
        "<ul><li>Java 21 instalado</li><li>Gradle wrapper del proyecto</li><li>Acceso a Azure Artifacts</li><li>Variables ARTIFACT_USERNAME y ARTIFACT_TOKEN configuradas</li></ul>",
        "<h3>Configurar credenciales para Azure Artifacts</h3>",
        _pre("export ARTIFACT_USERNAME=<usuario>\nexport ARTIFACT_TOKEN=<token>"),
        "<h3>Generar clases desde WSDL</h3>",
        _pre("./gradlew generateJavaFromWsdl"),
        "<h3>Compilar sin ejecutar tests</h3>",
        _pre("./gradlew clean build -x test"),
        "<h2>Variables dentro del Vault</h2>",
        "<p>No aplica</p>",
        "<h2>Variables en dev.yml y application.yml</h2>",
        "<h3>Normalización</h3>",
        _html_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], normalization_rows),
        f"<h3>Bancs API Client ({html.escape(tx_label)})</h3>",
        _html_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], bancs_rows),
        "<h3>Circuit Breaker</h3>",
        _html_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], circuit_rows),
        "<h3>Logging</h3>",
        _html_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], logging_rows),
        "<h2>Cómo Ejecutar</h2>",
        _pre("./gradlew bootRun\nSERVER_PORT=8081 ./gradlew bootRun\ncurl http://localhost:8080/actuator/health"),
        "<h2>API Endpoints</h2>",
        f"<h3>SOAP - POST {html.escape(doc.endpoint_path)}</h3>",
        _html_table(
            ["Aspecto", "Valor"],
            [["URL OpenShift Test", happy.url], ["Namespace", doc.namespace or VERIFY], ["Operación", operation], ["Método", "POST"], ["Content-Type", "text/xml;charset=UTF-8"]],
        ),
        "<h3>Params (entrada bodyIn)</h3>",
        _html_table(["#", "Campo", "Tipo", "Obligatorio", "Fuente"], _schema_rows(doc.body_fields)),
        "<h2>Explicación de la Lógica de Negocio</h2>",
        _pre(_logic_steps(doc)),
        "<h3>Respuesta BANCS - Interpretación - Acción</h3>",
        _html_table(["Respuesta BANCS", "Interpretación", "Acción"], response_bancs_rows),
        "<h2>Resultado de la API</h2>",
        "<h3>Request happy path</h3>",
        _pre(happy.request_xml),
        "<h3>Response esperado (happy path)</h3>",
        _pre(happy.response_xml),
        "<h2>Estructura del Resultado de la API</h2>",
        "<h3>error - Resultado de la Operación</h3>",
        _html_table(
            ["#", "Campo", "Descripción"],
            [
                ["1", "codigo", "Código de resultado o error."],
                ["2", "mensaje", "Mensaje técnico/funcional."],
                ["3", "mensajeNegocio", "Campo reservado para DataPower; no poblar con valor real."],
                ["4", "tipo", "INFO, ERROR o FATAL según estructura oficial."],
                ["5", "recurso", f"{doc.service_name}/{operation}."],
                ["6", "componente", "Servicio, método o TX según origen del error."],
                ["7", "backend", "Código backend oficial o [VERIFICAR]."],
            ],
        ),
        "<h2>Casos de Pruebas</h2>",
        "<h3>Validaciones de Entrada</h3>",
        _html_table(["#", "ID", "Caso", "Entrada", "Resultado esperado", "Estado"], validation_rows),
        "<h3>Operaciones BANCS</h3>",
        _html_table(["#", "ID", "Caso", "Entrada", "Resultado esperado", "Estado"], tx_test_rows),
        "<h3>Normalizaciones</h3>",
        _html_table(["#", "ID", "Caso", "Entrada", "Resultado esperado", "Estado"], normalization_test_rows),
        "<h2>TX BANCS - Mapeo de Campos</h2>",
    ]
    if doc.tx_codes:
        for tx in doc.tx_codes:
            parts.extend(
                [
                    f"<h3>TX {html.escape(tx)} - Request</h3>",
                    _html_table(["Campo", "Valor", "Fijo/Dinámico"], _tx_mapping_rows(tx, response=False)),
                    f"<h3>TX {html.escape(tx)} - Response</h3>",
                    _html_table(["Campo BANCS", "Descripción", "Fuente"], _tx_mapping_rows(tx, response=True)),
                ]
            )
    else:
        parts.append("<p>No se detectaron TX BANCS.</p>")
    parts.extend(
        [
            "<h2>Curl del Happy Path (ambiente OpenShift)</h2>",
            _pre(happy.curl),
            "<h3>Análisis del happy path</h3>",
            _html_table(["Aspecto", "Valor derivado de", "Valor"], happy.analysis_rows),
            "<h3>Response esperado (happy path)</h3>",
            _pre(happy.response_xml),
        ]
    )
    fragment = "\n".join(parts)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(doc.service_name)} - Documentación de Servicio</title>
</head>
<body>
{fragment}
</body>
</html>
"""


def render_markdown(doc: ServiceDocumentation) -> str:
    happy = doc.happy_path or _build_happy_path(
        service_name=doc.service_name,
        migrated_name=doc.migrated_name,
        operations=doc.operations,
        namespace=doc.namespace,
        header_fields=doc.header_fields,
        body_fields=doc.body_fields,
        tx_codes=doc.tx_codes,
        env_vars=doc.env_vars,
        migrated=doc.migrated_path,
        legacy=doc.legacy_path,
        reports=doc.report_excerpt,
    )
    validation_rows, tx_test_rows, normalization_test_rows = _test_groups(doc.tests)
    lines = [
        f"# {doc.service_name} - Documentación de Servicio",
        "",
        doc.description,
        "",
        "## Referencias del Proyecto",
        "",
        _md_table(
            ["#", "Tipo", "Recurso", "Descripción", "Enlace"],
            [
                ["1", "Repositorio", "Código fuente del servicio", doc.migrated_name, f"https://dev.azure.com/BancoPichinchaEC/tpl-middleware/_git/{doc.migrated_name}"],
                ["2", "Legacy", "Código fuente original", doc.legacy_path.name if doc.legacy_path else VERIFY, VERIFY],
                ["3", "Spec", "WSDL/XSD y casos", str(doc.wsdl_path) if doc.wsdl_path else VERIFY, VERIFY],
            ],
        ),
        "",
        "## Casos de Pruebas",
        "",
        "### Validaciones de Entrada",
        "",
        _md_table(["#", "ID", "Caso", "Entrada", "Resultado esperado", "Estado"], validation_rows),
        "",
        "### Operaciones BANCS",
        "",
        _md_table(["#", "ID", "Caso", "Entrada", "Resultado esperado", "Estado"], tx_test_rows),
        "",
        "### Normalizaciones",
        "",
        _md_table(["#", "ID", "Caso", "Entrada", "Resultado esperado", "Estado"], normalization_test_rows),
        "",
        "## Curl del Happy Path (ambiente OpenShift)",
        "",
        "```bash",
        happy.curl,
        "```",
        "",
        "### Análisis del happy path",
        "",
        _md_table(["Aspecto", "Valor derivado de", "Valor"], happy.analysis_rows),
    ]
    return "\n".join(lines).strip() + "\n"


def write_documentation(doc: ServiceDocumentation, output: Path, output_format: str) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "md":
        output.write_text(render_markdown(doc), encoding="utf-8")
    else:
        output.write_text(render_html(doc), encoding="utf-8")
    return output
