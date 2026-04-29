"""Google Docs friendly service documentation generator.

The generator is deterministic: it reads the migrated project, legacy hints,
Discovery, reports and runtime config, then emits a complete HTML or Markdown
document that can be imported into Google Docs.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

from capamedia_cli.core.discovery import (
    DiscoveryEntry,
    detect_discovery_workspace,
    find_discovery_workbook,
    load_discovery_entry,
)
from capamedia_cli.core.legacy_analyzer import analyze_wsdl, find_wsdl

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
    status: str


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
    tx_codes: list[str] = field(default_factory=list)
    env_vars: list[EnvVarDoc] = field(default_factory=list)
    tests: list[TestDoc] = field(default_factory=list)
    test_classes: list[str] = field(default_factory=list)
    report_excerpt: str = ""
    generated_from: list[Path] = field(default_factory=list)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _first_match(pattern: str, text: str, default: str = "") -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
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
        candidates.extend(
            [
                migrated / "MIGRATION_REPORT.md",
                migrated / "README.md",
                migrated / "migration-context.json",
            ]
        )
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
        r"##\s+Explicacion de la Logica de Negocio\s+(.+?)(?:\n##\s+|\Z)",
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
        framework = "Spring WebFlux"
    elif "spring-boot-starter-web-services" in build or "@Endpoint" in _read(migrated / "MIGRATION_REPORT.md"):
        framework = "Spring MVC + Spring WS"
    elif "spring-boot-starter-web" in build:
        framework = "Spring MVC"
    else:
        framework = "Spring Boot"
    return spring, gradle_version, framework


def _collect_wsdl_info(migrated: Path | None, legacy: Path | None) -> tuple[list[str], str]:
    for root in (migrated, legacy):
        if root is None or not root.exists():
            continue
        wsdl = find_wsdl(root)
        if wsdl:
            info = analyze_wsdl(wsdl)
            return info.operation_names, info.target_namespace
    return [], ""


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
        "CCC_BANCS_CONNECT_TIMEOUT": "Timeout de conexion BANCS.",
        "CCC_BANCS_READ_TIMEOUT": "Timeout de lectura BANCS.",
        "CCC_BANCS_MAX_IN_MEMORY_SIZE": "Buffer maximo para respuestas BANCS.",
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
        return "Configuracion de logging."
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
                default=default or "",
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


def _collect_tests(migrated: Path | None, discovery: DiscoveryEntry | None, tx_codes: list[str]) -> tuple[list[TestDoc], list[str]]:
    test_classes: list[str] = []
    tests: list[TestDoc] = []
    if migrated is not None:
        for path in sorted((migrated / "src" / "test").rglob("*.java")):
            rel = path.relative_to(migrated)
            test_classes.append(str(rel).replace("\\", "/"))
            text = _read(path)
            for method in re.findall(r"(?:@Test\s+)?(?:public\s+)?void\s+([A-Za-z0-9_]+)\s*\(", text):
                tests.append(
                    TestDoc(
                        test_id=f"TC-{len(tests) + 1:02d}",
                        case=method,
                        input_or_condition=str(rel).replace("\\", "/"),
                        expected="Validado por test automatizado",
                        status="Detectado",
                    )
                )

    if discovery is not None:
        for case in discovery.edge_cases:
            tests.append(
                TestDoc(
                    test_id=f"EC-{len(tests) + 1:02d}",
                    case=case.code,
                    input_or_condition=case.evidence,
                    expected=f"Cubrir edge case Discovery: {case.title}",
                    status="Requiere decision/documentacion",
                )
            )

    for tx in tx_codes:
        tests.append(
            TestDoc(
                test_id=f"TX-{tx}",
                case=f"Operación BANCS TX{tx}",
                input_or_condition=f"Invocacion a ws-tx{tx}",
                expected="Request, response, errores y timeouts trazados",
                status="Verificar cobertura",
            )
        )
    return tests[:80], test_classes


def _report_excerpt(reports: str) -> str:
    for heading in ("Explicacion de la Logica de Negocio", "Business Logic", "Step-by-Step Business Logic"):
        section = _first_match(rf"##\s+{re.escape(heading)}\s+(.+?)(?:\n##\s+|\Z)", reports)
        if section:
            clean = re.sub(r"\n{3,}", "\n\n", section.strip())
            return clean[:2500]
    return ""


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
        else (migrated_path.name if migrated_path else service)
    )
    reports, report_paths = _collect_report_texts(workspace, migrated_path, service)
    spring, gradle, framework = _build_gradle_info(migrated_path)
    operations, namespace = _collect_wsdl_info(migrated_path, legacy_path)
    tx_codes = _collect_tx_codes(migrated_path, reports, discovery)
    env_vars = _collect_env_vars(migrated_path)
    tests, test_classes = _collect_tests(migrated_path, discovery, tx_codes)
    endpoint = f"/IntegrationBus/soap/{_display_service(service)}" if service else "/IntegrationBus/soap/<Servicio>"

    return ServiceDocumentation(
        service_name=_display_service(service),
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
        tx_codes=tx_codes,
        env_vars=env_vars,
        tests=tests,
        test_classes=test_classes,
        report_excerpt=_report_excerpt(reports),
        generated_from=report_paths,
    )


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        safe = [cell.replace("\n", "<br>") if cell else "-" for cell in row]
        lines.append("| " + " | ".join(safe) + " |")
    return "\n".join(lines)


def render_markdown(doc: ServiceDocumentation) -> str:
    discovery = doc.discovery
    tx_label = f"TX{doc.tx_codes[0]}" if doc.tx_codes else "TX"
    lines: list[str] = [
        f"# {doc.service_name} - Documentación de Servicio",
        "",
        f"# {doc.service_name}",
        f"## {doc.migrated_name}",
        "",
        doc.description,
        "",
        "## Referencias del Proyecto",
        "",
        _md_table(
            ["#", "Tipo", "Recurso", "Descripción", "Enlace"],
            [
                ["1", "Repositorio", "Código fuente del servicio", doc.migrated_name, f"https://dev.azure.com/BancoPichinchaEC/tpl-middleware/_git/{doc.migrated_name}"],
                ["2", "Legacy", "Código fuente original", discovery.code_repo if discovery and discovery.code_repo else (doc.legacy_path.name if doc.legacy_path else "-"), discovery.link_code if discovery and discovery.link_code else "-"],
                ["3", "Spec", "Especificacion WSDL/casos", discovery.spec_path if discovery and discovery.spec_path else "-", discovery.link_wsdl if discovery and discovery.link_wsdl else "-"],
            ],
        ),
        "",
        "## Tecnologías",
        "",
        f"- Lenguaje: {doc.java_version}",
        f"- Construcción y gestión de dependencias: Gradle {doc.gradle_version or '(ver wrapper)'}",
        f"- Framework: {doc.spring_boot_version or 'Spring Boot'}",
        f"- Web: {doc.framework or 'Spring Boot'}",
        "- Arquitectura: Hexagonal (Ports & Adapters)",
        "- Cobertura de código: JaCoCo mínimo 75% de instrucciones",
        "- Testing: JUnit 5 + Mockito",
        "",
        "## Arquitectura del Microservicio",
        "",
        f"El microservicio `{doc.migrated_name}` expone `{doc.endpoint_path}` y aplica arquitectura hexagonal.",
        f"Origen legacy detectado: `{doc.source_kind or 'NO EVIDENCE'}`.",
        "",
        "## Configuración de Entorno de Desarrollo",
        "",
        "### Prerrequisitos",
        "",
        "- Java 21 instalado",
        "- Gradle wrapper del proyecto",
        "- Acceso a Azure Artifacts",
        "- Variables `ARTIFACT_USERNAME` y `ARTIFACT_TOKEN` configuradas",
        "",
        "### Configurar credenciales para Azure Artifacts",
        "",
        "```bash",
        "export ARTIFACT_USERNAME=<usuario>",
        "export ARTIFACT_TOKEN=<token>",
        "```",
        "",
        "### Generar clases desde WSDL",
        "",
        "```bash",
        "./gradlew generateJavaFromWsdl",
        "```",
        "",
        "### Compilar sin ejecutar tests",
        "",
        "```bash",
        "./gradlew clean build -x test",
        "```",
        "",
        "## Variables dentro del Vault",
        "",
    ]
    vault_rows = [[v.name, v.description, v.source] for v in doc.env_vars if v.vault]
    lines.append(_md_table(["Variable", "Descripción", "Fuente"], vault_rows) if vault_rows else "No se detectaron variables de secreto por nombre.")
    lines.extend(["", "## Variables en dev.yml y application.yml", ""])
    env_rows = [[str(i + 1), v.name, v.description, v.default or "(sin default)", v.source] for i, v in enumerate(doc.env_vars)]
    lines.append("Las siguientes variables se configuran en Helm y se referencian desde `application.yml`.")
    phone_rows = [row for row in env_rows if "PHONE" in row[1] or "CEL" in row[1]]
    bancs_rows = [row for row in env_rows if "BANCS" in row[1] and "CIRCUIT_BREAKER" not in row[1]]
    cb_rows = [row for row in env_rows if "CIRCUIT_BREAKER" in row[1] or "RESILIENCE" in row[1]]
    log_rows = [row for row in env_rows if "LOG" in row[1] or "PAYLOAD" in row[1] or "TRACE" in row[1]]
    lines.extend(["", "### Normalización de Teléfono", ""])
    lines.append(_md_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], phone_rows) if phone_rows else "No se detectaron variables específicas de teléfono.")
    lines.extend(["", f"### Servicio Bancs API Client ({tx_label})", ""])
    lines.append(_md_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], bancs_rows) if bancs_rows else "No se detectaron variables Bancs.")
    lines.extend(["", "### Circuit Breaker (Resilience4j)", ""])
    lines.append(_md_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], cb_rows) if cb_rows else "No se detectaron variables de circuit breaker.")
    lines.extend(["", "### Logging", ""])
    lines.append(_md_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], log_rows) if log_rows else "No se detectaron variables de logging.")
    lines.extend(
        [
            "",
            "## Cómo Ejecutar",
            "",
            "### Ejecutar localmente",
            "",
            "```bash",
            "./gradlew bootRun",
            "curl http://localhost:8080/actuator/health",
            "```",
            "",
            "- Health: `http://localhost:8080/actuator/health`",
            f"- Endpoint SOAP: `http://localhost:8080{doc.endpoint_path}`",
            "",
            "### Ejecutar en puerto alternativo (si 8080 está en uso)",
            "",
            "```bash",
            "./gradlew bootRun --args='--server.port=8081'",
            "```",
            "",
            "### Verificar que el servicio está activo",
            "",
            "```bash",
            "curl http://localhost:8080/actuator/health",
            "```",
            "",
            "## API Endpoints",
            "",
            f"### SOAP - POST {doc.endpoint_path}",
            "",
            f"- Endpoint: `http://localhost:8080{doc.endpoint_path}`",
            "- Método: POST - Content-Type: `text/xml`, `application/xml` o `application/soap+xml`",
            f"- Namespace: `{doc.namespace or 'NO EVIDENCE'}`",
            f"- Operaciones: `{', '.join(doc.operations) if doc.operations else 'NO EVIDENCE'}`",
            "",
            "### Params (entrada bodyIn)",
            "",
            _md_table(
                ["#", "Campo", "Tipo", "Obligatorio", "Descripción"],
                [["1", "bodyIn", "object", "Si", "Estructura de entrada segun WSDL/XSD legacy."]],
            ),
            "",
            "### Cada contactosTransaccional",
            "",
            _md_table(
                ["#", "Campo", "Tipo", "Obligatorio", "Descripción"],
                [["1", "<campo>", "string", "NO EVIDENCE", "Completar desde ANALISIS/WSDL cuando aplique."]],
            ),
            "",
            "### Endpoints Consumidos",
            "",
        ]
    )
    tx_rows = [[str(i + 1), f"Bancs TX{tx}", f"ws-tx{tx}", "Operación BANCS detectada en código/reportes"] for i, tx in enumerate(doc.tx_codes)]
    lines.append(_md_table(["#", "Servicio", "URL / Transacción", "Descripción"], tx_rows) if tx_rows else "No se detectaron TX BANCS.")
    lines.extend(["", "## Explicación de la Lógica de Negocio", ""])
    if doc.report_excerpt:
        lines.append(doc.report_excerpt)
    else:
        lines.append(doc.description)
    if discovery and discovery.edge_cases:
        lines.extend(["", "### Discovery edge cases", ""])
        lines.append(_md_table(["Código", "Severidad", "Evidencia"], [[case.code, case.severity, case.evidence] for case in discovery.edge_cases]))
    lines.extend(
        [
            "",
            "## Resultado de la API",
            "",
            "La operación retorna HTTP 200 para respuestas de negocio y estructura `<error>` para códigos funcionales. Los errores técnicos inesperados deben seguir el manejo definido por el stack migrado.",
            "",
            "### Ejemplo de request",
            "",
            "```xml",
            "<soapenv:Envelope>",
            "  <soapenv:Body>",
            "    <!-- Request segun WSDL/XSD legacy -->",
            "  </soapenv:Body>",
            "</soapenv:Envelope>",
            "```",
            "",
            "### Ejemplo de response",
            "",
            "```xml",
            "<soapenv:Envelope>",
            "  <soapenv:Body>",
            "    <!-- Response segun contrato migrado -->",
            "  </soapenv:Body>",
            "</soapenv:Envelope>",
            "```",
            "",
            "## Estructura del Resultado de la API",
            "",
            "### error - Resultado de la Operación",
            "",
            _md_table(
                ["#", "Campo", "Descripción"],
                [
                    ["1", "codigo", "Código de resultado o error."],
                    ["2", "mensaje", "Mensaje técnico/funcional."],
                    ["3", "mensajeNegocio", "Campo reservado para DataPower; no poblar con valor real."],
                    ["4", "tipo", "INFO, ERROR o FATAL segun estructura oficial."],
                    ["5", "recurso", f"{doc.service_name}/<Operación>."],
                    ["6", "componente", "Servicio, método o TX según origen del error."],
                    ["7", "backend", "Código backend oficial."],
                ],
            ),
            "",
            "## Pruebas",
            "",
            "Las pruebas se ejecutan con JUnit 5 y la cobertura mínima requerida es 75% de instrucciones.",
        ]
    )
    if doc.test_classes:
        lines.extend(["", "Clases de test detectadas:", ""])
        lines.extend(f"- `{klass}`" for klass in doc.test_classes)
    lines.extend(["", "## Casos de Pruebas", ""])
    test_rows = [[t.test_id, t.case, t.input_or_condition, t.expected, t.status] for t in doc.tests]
    validation_rows = [row for row in test_rows if "valid" in row[1].lower() or "cif" in row[1].lower() or row[0].startswith("EC-")]
    tx_test_rows = [row for row in test_rows if row[0].startswith("TX-") or "bancs" in row[1].lower()]
    normalization_rows = [row for row in test_rows if "normal" in row[1].lower() or "telefono" in row[1].lower() or "email" in row[1].lower()]
    lines.extend(["", "### Validaciones de Entrada", ""])
    lines.append(_md_table(["ID", "Caso", "Entrada", "Resultado esperado", "Estado"], validation_rows) if validation_rows else "No se detectaron tests específicos de validación de entrada.")
    lines.extend(["", "### Operaciones BANCS", ""])
    lines.append(_md_table(["ID", "Caso", "Condición", "Resultado esperado", "Estado"], tx_test_rows) if tx_test_rows else "No se detectaron tests específicos de operaciones BANCS.")
    lines.extend(["", "### Normalizaciones", ""])
    lines.append(_md_table(["ID", "Caso", "Entrada", "Resultado esperado", "Estado"], normalization_rows) if normalization_rows else "No se detectaron tests específicos de normalización.")
    lines.extend(["", "## TX BANCS - Mapeo de Campos", ""])
    if doc.tx_codes:
        for tx in doc.tx_codes:
            lines.extend(
                [
                    f"### TX {tx} - Request",
                    "",
                    _md_table(
                        ["Campo", "Valor", "Fijo/Dinamico"],
                        [
                            ["transactionId", tx, "Fijo"],
                            ["request", "Mapeo segun ANALISIS/WSDL/TX", "Dinamico"],
                            ["response", "Mapeo segun respuesta BANCS", "Dinamico"],
                        ],
                    ),
                    "",
                    f"### TX {tx} - Response (Query)",
                    "",
                    _md_table(
                        ["Campo BANCS", "Descripción"],
                        [
                            ["codigo", "Código de respuesta BANCS."],
                            ["mensaje", "Mensaje de respuesta BANCS."],
                            ["body", "Estructura segun TX y Core Adapter."],
                        ],
                    ),
                    "",
                ]
            )
    else:
        lines.append("No se detectaron TX BANCS.")
    lines.extend(["", "## Fuentes usadas", ""])
    for path in doc.generated_from:
        lines.append(f"- `{path}`")
    return "\n".join(lines).strip() + "\n"


def _html_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "<p>No se detecto informacion para esta tabla.</p>"
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{html.escape(cell or '-')}</td>" for cell in row) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _markdown_to_html_fragment(markdown: str) -> str:
    lines = []
    in_code = False
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                lines.append("</code></pre>")
            else:
                lines.append("<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            lines.append(html.escape(line) + "\n")
        elif not line:
            lines.append("")
        elif line.startswith("### "):
            lines.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            lines.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            lines.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("- "):
            lines.append(f"<p>&bull; {html.escape(line[2:])}</p>")
        elif line.startswith("|"):
            continue
        else:
            lines.append(f"<p>{html.escape(line)}</p>")
    return "\n".join(lines)


def render_html(doc: ServiceDocumentation) -> str:
    discovery = doc.discovery
    tx_label = f"TX{doc.tx_codes[0]}" if doc.tx_codes else "TX"
    vault_rows = [[v.name, v.description, v.source] for v in doc.env_vars if v.vault]
    env_rows = [[str(i + 1), v.name, v.description, v.default or "(sin default)", v.source] for i, v in enumerate(doc.env_vars)]
    tx_rows = [[str(i + 1), f"Bancs TX{tx}", f"ws-tx{tx}", "Operación BANCS detectada en código/reportes"] for i, tx in enumerate(doc.tx_codes)]
    test_rows = [[t.test_id, t.case, t.input_or_condition, t.expected, t.status] for t in doc.tests]
    phone_rows = [row for row in env_rows if "PHONE" in row[1] or "CEL" in row[1]]
    bancs_rows = [row for row in env_rows if "BANCS" in row[1] and "CIRCUIT_BREAKER" not in row[1]]
    cb_rows = [row for row in env_rows if "CIRCUIT_BREAKER" in row[1] or "RESILIENCE" in row[1]]
    log_rows = [row for row in env_rows if "LOG" in row[1] or "PAYLOAD" in row[1] or "TRACE" in row[1]]
    validation_rows = [
        row for row in test_rows
        if "valid" in row[1].lower() or "cif" in row[1].lower() or row[0].startswith("EC-")
    ]
    tx_test_rows = [row for row in test_rows if row[0].startswith("TX-") or "bancs" in row[1].lower()]
    normalization_rows = [
        row for row in test_rows
        if "normal" in row[1].lower() or "telefono" in row[1].lower() or "email" in row[1].lower()
    ]

    parts: list[str] = [
        f"<h1>{html.escape(doc.service_name)} - Documentación de Servicio</h1>",
        f"<h1>{html.escape(doc.service_name)}</h1>",
        f"<h2>{html.escape(doc.migrated_name)}</h2>",
        f"<p>{html.escape(doc.description)}</p>",
        "<h2>Referencias del Proyecto</h2>",
        _html_table(
            ["#", "Tipo", "Recurso", "Descripción", "Enlace"],
            [
                ["1", "Repositorio", "Código fuente del servicio", doc.migrated_name, f"https://dev.azure.com/BancoPichinchaEC/tpl-middleware/_git/{doc.migrated_name}"],
                ["2", "Legacy", "Código fuente original", discovery.code_repo if discovery and discovery.code_repo else (doc.legacy_path.name if doc.legacy_path else "-"), discovery.link_code if discovery and discovery.link_code else "-"],
                ["3", "Spec", "Especificacion WSDL/casos", discovery.spec_path if discovery and discovery.spec_path else "-", discovery.link_wsdl if discovery and discovery.link_wsdl else "-"],
            ],
        ),
        "<h2>Tecnologías</h2>",
        "<ul>",
        f"<li>Lenguaje: {html.escape(doc.java_version)}</li>",
        f"<li>Construcción y gestión de dependencias: Gradle {html.escape(doc.gradle_version or '(ver wrapper)')}</li>",
        f"<li>Framework: {html.escape(doc.spring_boot_version or 'Spring Boot')}</li>",
        f"<li>Web: {html.escape(doc.framework or 'Spring Boot')}</li>",
        "<li>Arquitectura: Hexagonal (Ports & Adapters)</li>",
        "<li>Cobertura de código: JaCoCo mínimo 75% de instrucciones</li>",
        "<li>Testing: JUnit 5 + Mockito</li>",
        "</ul>",
        "<h2>Arquitectura del Microservicio</h2>",
        f"<p>El microservicio <code>{html.escape(doc.migrated_name)}</code> expone <code>{html.escape(doc.endpoint_path)}</code> y aplica arquitectura hexagonal.</p>",
        f"<p>Origen legacy detectado: <code>{html.escape(doc.source_kind or 'NO EVIDENCE')}</code>.</p>",
        "<h2>Configuración de Entorno de Desarrollo</h2>",
        "<h3>Prerrequisitos</h3>",
        "<ul><li>Java 21 instalado</li><li>Gradle wrapper del proyecto</li><li>Acceso a Azure Artifacts</li><li>Variables ARTIFACT_USERNAME y ARTIFACT_TOKEN configuradas</li></ul>",
        "<h3>Configurar credenciales para Azure Artifacts</h3>",
        "<pre><code>export ARTIFACT_USERNAME=&lt;usuario&gt;\nexport ARTIFACT_TOKEN=&lt;token&gt;</code></pre>",
        "<h3>Generar clases desde WSDL</h3>",
        "<pre><code>./gradlew generateJavaFromWsdl</code></pre>",
        "<h3>Compilar sin ejecutar tests</h3>",
        "<pre><code>./gradlew clean build -x test</code></pre>",
        "<h2>Variables dentro del Vault</h2>",
        _html_table(["Variable", "Descripción", "Fuente"], vault_rows) if vault_rows else "<p>No se detectaron variables de secreto por nombre.</p>",
        "<h2>Variables en dev.yml y application.yml</h2>",
        "<p>Las siguientes variables se configuran en Helm y se referencian desde <code>application.yml</code>.</p>",
        "<h3>Normalización de Teléfono</h3>",
        _html_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], phone_rows)
        if phone_rows else "<p>No se detectaron variables específicas de teléfono.</p>",
        f"<h3>Servicio Bancs API Client ({html.escape(tx_label)})</h3>",
        _html_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], bancs_rows)
        if bancs_rows else "<p>No se detectaron variables Bancs.</p>",
        "<h3>Circuit Breaker (Resilience4j)</h3>",
        _html_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], cb_rows)
        if cb_rows else "<p>No se detectaron variables de circuit breaker.</p>",
        "<h3>Logging</h3>",
        _html_table(["#", "Variable", "Descripción", "Valor por defecto", "Fuente"], log_rows)
        if log_rows else "<p>No se detectaron variables de logging.</p>",
        "<h2>Cómo Ejecutar</h2>",
        "<h3>Ejecutar localmente</h3>",
        "<pre><code>./gradlew bootRun\ncurl http://localhost:8080/actuator/health</code></pre>",
        "<p>Health: <code>http://localhost:8080/actuator/health</code></p>",
        f"<p>Endpoint SOAP: <code>http://localhost:8080{html.escape(doc.endpoint_path)}</code></p>",
        "<h3>Ejecutar en puerto alternativo (si 8080 está en uso)</h3>",
        "<pre><code>./gradlew bootRun --args='--server.port=8081'</code></pre>",
        "<h3>Verificar que el servicio está activo</h3>",
        "<pre><code>curl http://localhost:8080/actuator/health</code></pre>",
        "<h2>API Endpoints</h2>",
        f"<h3>SOAP - POST {html.escape(doc.endpoint_path)}</h3>",
        f"<p>Endpoint: <code>http://localhost:8080{html.escape(doc.endpoint_path)}</code></p>",
        "<p>Método: POST - Content-Type: <code>text/xml</code>, <code>application/xml</code> o <code>application/soap+xml</code></p>",
        f"<p>Namespace: <code>{html.escape(doc.namespace or 'NO EVIDENCE')}</code></p>",
        f"<p>Operaciones: <code>{html.escape(', '.join(doc.operations) if doc.operations else 'NO EVIDENCE')}</code></p>",
        "<h3>Params (entrada bodyIn)</h3>",
        _html_table(
            ["#", "Campo", "Tipo", "Obligatorio", "Descripción"],
            [["1", "bodyIn", "object", "Si", "Estructura de entrada segun WSDL/XSD legacy."]],
        ),
        "<h3>Cada contactosTransaccional</h3>",
        _html_table(
            ["#", "Campo", "Tipo", "Obligatorio", "Descripción"],
            [["1", "<campo>", "string", "NO EVIDENCE", "Completar desde ANALISIS/WSDL cuando aplique."]],
        ),
        "<h3>Endpoints Consumidos</h3>",
        _html_table(["#", "Servicio", "URL / Transacción", "Descripción"], tx_rows) if tx_rows else "<p>No se detectaron TX BANCS.</p>",
        "<h2>Explicación de la Lógica de Negocio</h2>",
        f"<p>{html.escape(doc.report_excerpt or doc.description)}</p>",
    ]
    if discovery and discovery.edge_cases:
        parts.extend(
            [
                "<h3>Discovery edge cases</h3>",
                _html_table(
                    ["Código", "Severidad", "Evidencia"],
                    [[case.code, case.severity, case.evidence] for case in discovery.edge_cases],
                ),
            ]
        )
    parts.extend(
        [
            "<h2>Resultado de la API</h2>",
            "<p>La operación retorna HTTP 200 para respuestas de negocio y estructura &lt;error&gt; para códigos funcionales. Los errores técnicos inesperados deben seguir el manejo definido por el stack migrado.</p>",
            "<h3>Ejemplo de request</h3>",
            "<pre><code>&lt;soapenv:Envelope&gt;\n  &lt;soapenv:Body&gt;\n    &lt;!-- Request segun WSDL/XSD legacy --&gt;\n  &lt;/soapenv:Body&gt;\n&lt;/soapenv:Envelope&gt;</code></pre>",
            "<h3>Ejemplo de response</h3>",
            "<pre><code>&lt;soapenv:Envelope&gt;\n  &lt;soapenv:Body&gt;\n    &lt;!-- Response segun contrato migrado --&gt;\n  &lt;/soapenv:Body&gt;\n&lt;/soapenv:Envelope&gt;</code></pre>",
            "<h2>Estructura del Resultado de la API</h2>",
            "<h3>error - Resultado de la Operación</h3>",
            _html_table(
                ["#", "Campo", "Descripción"],
                [
                    ["1", "codigo", "Código de resultado o error."],
                    ["2", "mensaje", "Mensaje técnico/funcional."],
                    ["3", "mensajeNegocio", "Campo reservado para DataPower; no poblar con valor real."],
                    ["4", "tipo", "INFO, ERROR o FATAL segun estructura oficial."],
                    ["5", "recurso", f"{doc.service_name}/<Operación>."],
                    ["6", "componente", "Servicio, método o TX según origen del error."],
                    ["7", "backend", "Código backend oficial."],
                ],
            ),
            "<h2>Pruebas</h2>",
            "<p>Las pruebas se ejecutan con JUnit 5 y la cobertura mínima requerida es 75% de instrucciones.</p>",
        ]
    )
    if doc.test_classes:
        items = "".join(f"<li><code>{html.escape(klass)}</code></li>" for klass in doc.test_classes)
        parts.append(f"<p>Clases de test detectadas:</p><ul>{items}</ul>")
    parts.extend(
        [
            "<h2>Casos de Pruebas</h2>",
            "<h3>Validaciones de Entrada</h3>",
            _html_table(["ID", "Caso", "Entrada", "Resultado esperado", "Estado"], validation_rows)
            if validation_rows else "<p>No se detectaron tests específicos de validación de entrada.</p>",
            "<h3>Operaciones BANCS</h3>",
            _html_table(["ID", "Caso", "Condición", "Resultado esperado", "Estado"], tx_test_rows)
            if tx_test_rows else "<p>No se detectaron tests específicos de operaciones BANCS.</p>",
            "<h3>Normalizaciones</h3>",
            _html_table(["ID", "Caso", "Entrada", "Resultado esperado", "Estado"], normalization_rows)
            if normalization_rows else "<p>No se detectaron tests específicos de normalización.</p>",
            "<h2>TX BANCS - Mapeo de Campos</h2>",
        ]
    )
    if doc.tx_codes:
        for tx in doc.tx_codes:
            parts.extend(
                [
                    f"<h3>TX {html.escape(tx)} - Request</h3>",
                    _html_table(
                        ["Campo", "Valor", "Fijo/Dinamico"],
                        [
                            ["transactionId", tx, "Fijo"],
                            ["request", "Mapeo segun ANALISIS/WSDL/TX", "Dinamico"],
                            ["response", "Mapeo segun respuesta BANCS", "Dinamico"],
                        ],
                    ),
                    f"<h3>TX {html.escape(tx)} - Response (Query)</h3>",
                    _html_table(
                        ["Campo BANCS", "Descripción"],
                        [
                            ["codigo", "Código de respuesta BANCS."],
                            ["mensaje", "Mensaje de respuesta BANCS."],
                            ["body", "Estructura segun TX y Core Adapter."],
                        ],
                    ),
                ]
            )
    else:
        parts.append("<p>No se detectaron TX BANCS.</p>")
    if doc.generated_from:
        parts.append("<h2>Fuentes usadas</h2>")
        parts.append("<ul>" + "".join(f"<li><code>{html.escape(str(path))}</code></li>" for path in doc.generated_from) + "</ul>")
    fragment = "\n".join(parts)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(doc.service_name)} - Documentación de Servicio</title>
  <style>
    body {{ font-family: Arial, sans-serif; color: #172b4d; line-height: 1.45; }}
    h1 {{ color: #0c3b5f; font-size: 28px; margin-top: 28px; }}
    h2 {{ color: #124f7c; border-bottom: 1px solid #d7e2ea; padding-bottom: 4px; margin-top: 24px; }}
    h3 {{ color: #1d5f8f; margin-top: 18px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0 18px; }}
    th {{ background: #eaf3f8; color: #0c3b5f; font-weight: 700; }}
    th, td {{ border: 1px solid #b8c7d3; padding: 6px 8px; vertical-align: top; }}
    code, pre {{ background: #f5f7fa; color: #253858; }}
    pre {{ padding: 10px; border: 1px solid #dfe1e6; overflow-wrap: break-word; white-space: pre-wrap; }}
  </style>
</head>
<body>
{fragment}
</body>
</html>
"""


def write_documentation(doc: ServiceDocumentation, output: Path, output_format: str) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "md":
        output.write_text(render_markdown(doc), encoding="utf-8")
    else:
        output.write_text(render_html(doc), encoding="utf-8")
    return output
