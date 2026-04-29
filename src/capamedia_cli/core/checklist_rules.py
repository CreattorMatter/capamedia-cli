"""Checklist BPTPSRE - implementacion determinista (sin AI) de los 15 bloques.

Cada bloque es una funcion que recibe contexto y retorna una lista de CheckResult.
El comando `capamedia check` orquesta todas las funciones y produce el reporte.

Los bloques son espejo de `prompts/post-migracion/03-checklist.md` del repo original.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from capamedia_cli.core.gitignore_policy import (
    DEPLOYMENT_GITIGNORE_ENTRIES,
    format_deployment_gitignore_block,
    missing_deployment_gitignore_entries,
)

# -- Result dataclass -------------------------------------------------------


@dataclass
class CheckResult:
    id: str
    block: str
    title: str
    status: str  # "pass" | "fail"
    severity: str = ""  # "high" | "medium" | "low" (solo si status=fail)
    detail: str = ""
    suggested_fix: str = ""


@dataclass
class CheckContext:
    migrated_path: Path
    legacy_path: Path | None
    project_type: str = ""  # "rest" | "soap" (detectado en BLOQUE 0)
    operation_count: int = 0
    has_database: bool = False
    # v0.3.2: lista de dominios distintos invocados via UMPs.
    # Si esta poblado, el Check 1.4 usa la regla "1 port por dominio".
    # Si es None, cae al check viejo (solo Bancs unico).
    ump_domains: list = None  # type: ignore[assignment]
    # v0.22.0: matriz MCP-driven (BUS + invocaBancs -> REST override,
    # ORQ -> siempre WebFlux, WAS -> ops count decide)
    source_type: str = ""       # "bus" | "was" | "orq" | "unknown" | ""
    has_bancs: bool = False     # flag invocaBancs (MCP)


# -- Helpers ---------------------------------------------------------------


def _grep_files(root: Path, pattern: str, file_glob: str = "**/*.java") -> list[tuple[Path, int, str]]:
    """Return list of (file, line_no, line) matching regex pattern."""
    matches: list[tuple[Path, int, str]] = []
    regex = re.compile(pattern)
    for f in root.rglob(file_glob):
        if ".git" in f.parts or "build" in f.parts:
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    matches.append((f, i, line.rstrip()))
        except OSError:
            continue
    return matches


def _file_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


def _git_ignores(root: Path, relative_path: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", relative_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _read_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _relative_display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("/", "\\")
    except ValueError:
        return str(path)


def _matrix_requires_bancs(ctx: CheckContext) -> bool:
    return (ctx.source_type or "").lower() in {"bus", "iib"} and ctx.has_bancs


def _active_bancs_artifacts(root: Path) -> list[str]:
    """Detecta artefactos BANCS activos; ignora XSD/WSDL legacy embebidos."""
    artifacts: list[str] = []

    for gf in list(root.rglob("build.gradle")) + list(root.rglob("build.gradle.kts")):
        if ".git" in gf.parts or "build" in gf.parts:
            continue
        if "lib-bnc-api-client" in _read_or_empty(gf):
            artifacts.append(str(gf.relative_to(root)))

    catalog = root / "catalog-info.yaml"
    if "lib-bnc-api-client" in _read_or_empty(catalog):
        artifacts.append("catalog-info.yaml")

    lombok = root / "src" / "lombok.config"
    if "BancsService" in _read_or_empty(lombok):
        artifacts.append("src/lombok.config")

    resources = root / "src"
    for yml in list(resources.rglob("application*.yml")) + list(resources.rglob("application*.yaml")):
        if ".git" in yml.parts or "legacy" in [p.lower() for p in yml.parts]:
            continue
        text = _read_or_empty(yml)
        if re.search(r"(?m)^bancs\s*:", text) or "CCC_BANCS_" in text:
            artifacts.append(str(yml.relative_to(root)))

    src_java = root / "src" / "main" / "java"
    for java in src_java.rglob("*.java"):
        if ".git" in java.parts or "build" in java.parts:
            continue
        text = _read_or_empty(java)
        if (
            "com.pichincha.bnc" in text
            or "@BancsService" in text
            or "BancsClientHelper" in text
            or "BancsOperationException" in text
        ):
            artifacts.append(str(java.relative_to(root)))

    return sorted(set(artifacts))


def _allowed_mensaje_negocio_slot(line: str) -> bool:
    """True when mensajeNegocio is intentionally emitted empty/null for the contract."""
    return (
        re.search(
            r"setMensajeNegocio\s*\(\s*(?:\"\"|''|null|StringUtils\.EMPTY|EMPTY)\s*\)",
            line,
        )
        is not None
    )


def _collect_tx_codes_from_yaml(text: str) -> set[str]:
    return set(re.findall(r"\bws-tx(\d{6})\b", text, flags=re.IGNORECASE))


def _collect_tx_codes_from_java(src_java: Path) -> set[str]:
    codes: set[str] = set()
    patterns = [
        re.compile(r"\bws-tx(\d{6})\b", re.IGNORECASE),
        re.compile(r"\btransactionId\s*\(\s*[\"'](\d{6})[\"']\s*\)", re.IGNORECASE),
        re.compile(r"\bTRANSACTION_ID\b\s*=\s*[\"'](\d{6})[\"']", re.IGNORECASE),
    ]
    for java in src_java.rglob("*.java"):
        if ".git" in java.parts or "build" in java.parts or "test" in [p.lower() for p in java.parts]:
            continue
        text = _read_or_empty(java)
        for pattern in patterns:
            codes.update(pattern.findall(text))
    return codes


_HIGH_DISCOVERY_EDGE_CODES = {
    "deprecated_or_repoint",
    "mq_or_event",
    "external_provider",
    "same_name_bus_was_or_missing_source",
    "tx_description_validation",
    "missing_source_request",
}

_DISCOVERY_PENDING_RE = re.compile(
    r"\b(pendiente|tbd|todo|not_probed|not_provided|sin\s+decision|no\s+evidence)\b|"
    r"<pendiente_validar>",
    re.IGNORECASE,
)

_DISCOVERY_COVERAGE_MARKERS = (
    "decision",
    "implemented",
    "implementado",
    "resuelto",
    "validado",
    "no aplica",
    "blocked_by_permissions",
    "archivo:",
    "file:",
    "test:",
    "prueba:",
)


def _workspace_root_for_migrated(migrated_path: Path) -> Path:
    if migrated_path.parent.name == "destino":
        return migrated_path.parent.parent
    return migrated_path


def _token_present(text: str, token: str) -> bool:
    return token.lower() in text.lower()


def _discovery_report_files(workspace_root: Path, migrated_path: Path) -> list[Path]:
    candidates: list[Path] = []
    for root, patterns in (
        (
            workspace_root,
            [
                "COMPLEXITY_*.md",
                "ANALISIS_*.md",
                "DISCOVERY_EDGE_CASES*.md",
                ".capamedia/reports/*.md",
            ],
        ),
        (
            migrated_path,
            [
                "MIGRATION_REPORT.md",
                "README.md",
                "DISCOVERY_EDGE_CASES*.md",
                "CHECKLIST_*.md",
                "src/test/**/*.java",
            ],
        ),
    ):
        for pattern in patterns:
            candidates.extend(p for p in root.glob(pattern) if p.is_file())

    seen: set[Path] = set()
    files: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        files.append(candidate)
    return files


def _discovery_edge_case_status(text: str, code: str) -> str:
    """Return covered, pending, or missing for a Discovery edge-case code."""
    lowered = text.lower()
    code_lower = code.lower()
    positions = [match.start() for match in re.finditer(re.escape(code_lower), lowered)]
    if not positions:
        return "missing"

    has_pending = False
    for pos in positions:
        window = lowered[max(0, pos - 500): pos + 500]
        if _DISCOVERY_PENDING_RE.search(window):
            has_pending = True
            continue
        if any(marker in window for marker in _DISCOVERY_COVERAGE_MARKERS):
            return "covered"
    return "pending" if has_pending else "missing"


def _deployment_gitignore_check(ctx: CheckContext) -> CheckResult:
    gitignore = ctx.migrated_path / ".gitignore"
    if not gitignore.exists():
        missing = list(DEPLOYMENT_GITIGNORE_ENTRIES)
        detail = ".gitignore faltante en el proyecto migrado"
    else:
        missing = missing_deployment_gitignore_entries(_read_or_empty(gitignore))
        detail = f"faltan entradas: {', '.join(missing)}" if missing else ""

    if missing:
        return CheckResult(
            "14.6",
            "Block 14",
            ".gitignore excluye artefactos CapaMedia/AI",
            "fail",
            severity="high",
            detail=detail,
            suggested_fix=(
                "Agregar al .gitignore del proyecto migrado este bloque:\n"
                f"{format_deployment_gitignore_block()}\n"
                "No ignorar .sonarlint/connectedMode.json: ese binding si se versiona."
            ),
        )

    return CheckResult(
        "14.6",
        "Block 14",
        ".gitignore excluye artefactos CapaMedia/AI",
        "pass",
        detail="artefactos locales CapaMedia/AI ignorados para Azure DevOps",
    )


def _expected_framework(
    source_type: str, has_bancs: bool, ops_count: int
) -> tuple[str, str]:
    """Matriz MCP-driven oficial del banco (v0.23.14).

    Fuente: `bank-mcp-matrix.md` canonical + PDF `BPTPSRE-Modos de uso`.

    Returns (expected_framework, reason) donde framework es "rest" | "soap".

    Reglas del MCP oficial (en orden de prioridad):
      Regla 1 — invocaBancs=true (override total) -> webflux + rest
      Regla 2 — deploymentType=orquestador       -> webflux + rest + lib-event-logs
      Regla 3 — projectType=soap + microservicio -> mvc + soap + spring-web-service
      (sin regla) caso base WAS 1 op / BUS sin BANCS 1 op -> rest

    Mapeo source_type interno -> parametros MCP del banco:
      orq                  -> deploymentType=orquestador (Regla 2)
      iib/bus + has_bancs  -> invocaBancs=true (Regla 1)
      iib/bus sin bancs    -> deploymentType=microservicio (Regla 3 si 2+ ops)
      was                  -> deploymentType=microservicio, framework=mvc siempre
    """
    src = (source_type or "").lower()

    # Regla 1 — invocaBancs=true (override total, prioridad maxima)
    if src in ("bus", "iib") and has_bancs:
        return (
            "rest",
            "Regla 1 MCP: invocaBancs=true fuerza webflux+rest (override total)",
        )

    # Regla 2 — deploymentType=orquestador
    if src == "orq":
        return (
            "rest",
            "Regla 2 MCP: deploymentType=orquestador -> webflux+rest + lib-event-logs",
        )

    # WAS — siempre framework=mvc, projectType decide por ops
    if src == "was":
        if ops_count == 1:
            return ("rest", "WAS 1 op -> mvc+rest (microservicio, caso base)")
        return (
            "soap",
            f"WAS {ops_count} ops -> Regla 3 MCP: mvc+soap + spring-web-service",
        )

    # BUS sin BANCS — por ops_count (Regla 3 si 2+ ops)
    if src in ("bus", "iib"):
        if ops_count == 1:
            return (
                "rest",
                "BUS sin BANCS 1 op (Apis) -> webflux+rest (caso base)",
            )
        return (
            "soap",
            f"BUS sin BANCS {ops_count} ops -> Regla 3 MCP: mvc+soap + spring-web-service",
        )

    # Fallback: sin source_type detectable, usar conteo de ops
    if ops_count == 1:
        return ("rest", "1 op -> rest (sin source_type, fallback a conteo)")
    return (
        "soap",
        f"{ops_count} ops -> soap (sin source_type, fallback a conteo)",
    )


# -- Block 0: Pre-check con analisis cruzado legacy vs migrado ---------------


def run_block_0(ctx: CheckContext) -> list[CheckResult]:
    from capamedia_cli.core.legacy_analyzer import analyze_wsdl, find_wsdl

    results: list[CheckResult] = []
    src_java = ctx.migrated_path / "src" / "main" / "java"

    # 0.1 - Tipo de proyecto
    has_endpoint = len(_grep_files(src_java, r"@Endpoint\b")) > 0 if src_java.exists() else False
    has_controller = len(_grep_files(src_java, r"@RestController\b")) > 0 if src_java.exists() else False
    if has_endpoint and not has_controller:
        ctx.project_type = "soap"
        results.append(CheckResult("0.1", "Block 0", "Tipo de proyecto", "pass", detail="SOAP detectado (@Endpoint encontrado)"))
    elif has_controller and not has_endpoint:
        ctx.project_type = "rest"
        results.append(CheckResult("0.1", "Block 0", "Tipo de proyecto", "pass", detail="REST detectado (@RestController encontrado)"))
    elif has_endpoint and has_controller:
        results.append(CheckResult("0.1", "Block 0", "Tipo de proyecto", "fail", severity="high", detail="Proyecto tiene AMBOS @Endpoint y @RestController", suggested_fix="Decidir uno y remover el otro"))
    else:
        results.append(CheckResult("0.1", "Block 0", "Tipo de proyecto", "fail", severity="high", detail="No se detecto ni @Endpoint ni @RestController", suggested_fix="Completar el controller/endpoint del proyecto"))

    # 0.2 - Count ops
    migrated_wsdl = find_wsdl(ctx.migrated_path / "src" / "main" / "resources")
    if not migrated_wsdl:
        migrated_wsdl = find_wsdl(ctx.migrated_path)
    ops_migrated = 0
    if migrated_wsdl:
        info = analyze_wsdl(migrated_wsdl)
        ops_migrated = info.operation_count
        ctx.operation_count = ops_migrated
    else:
        results.append(CheckResult("0.2a", "Block 0", "WSDL presente en migrado", "fail", severity="high", detail="No se encontro *.wsdl en src/main/resources/", suggested_fix="Copiar el WSDL del legacy"))
        return results

    # Cross-check con legacy si esta disponible
    ops_legacy = 0
    legacy_wsdl = None
    if ctx.legacy_path:
        legacy_wsdl = find_wsdl(ctx.legacy_path)
        if legacy_wsdl:
            ops_legacy = analyze_wsdl(legacy_wsdl).operation_count

    if legacy_wsdl and ops_legacy != ops_migrated:
        results.append(CheckResult(
            "0.2b", "Block 0", "Count ops legacy == migrado", "fail", severity="high",
            detail=f"legacy={ops_legacy} vs migrado={ops_migrated}",
            suggested_fix="Revisar si se perdio o duplico alguna operacion al copiar el WSDL",
        ))
    elif ctx.legacy_path and not legacy_wsdl:
        results.append(CheckResult("0.2b", "Block 0", "Count ops legacy vs migrado", "fail", severity="medium", detail="Legacy path provisto pero WSDL legacy no encontrado"))

    # v0.22.0: matriz MCP-driven.
    # - BUS (IIB) + invocaBancs=true -> REST+WebFlux (override, ignora ops)
    # - ORQ                          -> REST+WebFlux (siempre)
    # - WAS                          -> 1 op=REST+MVC, 2+ ops=SOAP+MVC
    # - unknown                      -> fallback al conteo de ops (comportamiento legacy)
    expected_fw, reason = _expected_framework(
        ctx.source_type, ctx.has_bancs, ops_migrated
    )
    actual_fw = ctx.project_type
    ops_ref = ops_legacy if ops_legacy > 0 else ops_migrated

    # Construir el diálogo conversacional con todos los datos de la matriz
    src_disp = (ctx.source_type or "unknown").upper()
    bancs_disp = "SI" if ctx.has_bancs else "NO"
    if expected_fw == actual_fw:
        dialogo = (
            f"source={src_disp} · invocaBancs={bancs_disp} · {ops_ref} op(s) "
            f"-> {actual_fw.upper()} ({reason}). OK."
        )
        results.append(CheckResult("0.2c", "Block 0", "Framework vs matriz MCP", "pass", detail=dialogo))
    else:
        dialogo = (
            f"source={src_disp} · invocaBancs={bancs_disp} · {ops_ref} op(s) "
            f"-> deberia ir {expected_fw.upper()} ({reason}). "
            f"Se migro como {actual_fw.upper()} -> MAL-CLASIFICADO"
        )
        results.append(CheckResult(
            "0.2c", "Block 0", "Framework vs matriz MCP", "fail",
            severity="high", detail=dialogo,
            suggested_fix="Reclasificar segun matriz: BUS+invocaBancs/ORQ -> REST+WebFlux, WAS 1op -> REST+MVC, WAS 2+ops -> SOAP+MVC",
        ))

    # 0.2d - BANCS solo cuando la matriz lo permite.
    src_known = (ctx.source_type or "").lower() in {"was", "orq", "bus", "iib"}
    bancs_artifacts = _active_bancs_artifacts(ctx.migrated_path)
    if src_known and not _matrix_requires_bancs(ctx) and bancs_artifacts:
        results.append(
            CheckResult(
                "0.2d",
                "Block 0",
                "Artefactos BANCS vs matriz MCP",
                "fail",
                severity="high",
                detail=(
                    f"source={src_disp} · invocaBancs={bancs_disp}; "
                    f"BANCS no aplica pero hay artefactos: {bancs_artifacts[:8]}"
                ),
                suggested_fix=(
                    "Eliminar lib-bnc-api-client, dependsOn lib-bnc, "
                    "lombok BancsService y configuracion bancs/CCC_BANCS. "
                    "BANCS solo aplica a BUS/IIB con invocaBancs=true."
                ),
            )
        )
    elif src_known:
        status_detail = (
            "BANCS requerido por matriz"
            if _matrix_requires_bancs(ctx)
            else "sin artefactos BANCS activos"
        )
        results.append(
            CheckResult(
                "0.2d",
                "Block 0",
                "Artefactos BANCS vs matriz MCP",
                "pass",
                detail=status_detail,
            )
        )

    # 0.3 - Operation names match
    if legacy_wsdl:
        legacy_info = analyze_wsdl(legacy_wsdl)
        migrated_info = analyze_wsdl(migrated_wsdl)
        legacy_names = set(legacy_info.operation_names)
        migrated_names = set(migrated_info.operation_names)
        if legacy_names == migrated_names:
            results.append(CheckResult("0.3", "Block 0", "Operation names match", "pass"))
        else:
            missing = legacy_names - migrated_names
            extra = migrated_names - legacy_names
            detail = []
            if missing:
                detail.append(f"Faltantes: {', '.join(sorted(missing))}")
            if extra:
                detail.append(f"De mas: {', '.join(sorted(extra))}")
            results.append(CheckResult("0.3", "Block 0", "Operation names match", "fail", severity="high", detail=" | ".join(detail)))

    # 0.4 - targetNamespace match
    if legacy_wsdl:
        if analyze_wsdl(legacy_wsdl).target_namespace == analyze_wsdl(migrated_wsdl).target_namespace:
            results.append(CheckResult("0.4", "Block 0", "targetNamespace match", "pass"))
        else:
            results.append(CheckResult(
                "0.4", "Block 0", "targetNamespace match", "fail", severity="high",
                detail=f"legacy={analyze_wsdl(legacy_wsdl).target_namespace} | migrado={analyze_wsdl(migrated_wsdl).target_namespace}",
                suggested_fix="Restaurar namespace original o migracion coordinada con callers",
            ))

    # 0.5 - XSDs referenciados existen
    migrated_info = analyze_wsdl(migrated_wsdl)
    missing_schemas: list[str] = []
    for sl in migrated_info.schema_locations:
        basename = Path(sl).name
        found = any(ctx.migrated_path.rglob(basename))
        if not found:
            missing_schemas.append(sl)
    if missing_schemas:
        results.append(CheckResult("0.5", "Block 0", "XSDs referenciados presentes", "fail", severity="high", detail=f"Faltan: {', '.join(missing_schemas)}"))
    else:
        results.append(CheckResult("0.5", "Block 0", "XSDs referenciados presentes", "pass"))

    return results


# -- Block 1: Arquitectura hexagonal ----------------------------------------


def run_block_1(ctx: CheckContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    src_java = ctx.migrated_path / "src" / "main" / "java"

    # 1.1 - Capas presentes
    expected_layers = ["application", "domain", "infrastructure"]
    present = [layer for layer in expected_layers if any(src_java.rglob(f"{layer}/"))]
    if len(present) == 3:
        results.append(CheckResult("1.1", "Block 1", "Capas hexagonales presentes", "pass", detail=f"{', '.join(present)}"))
    else:
        missing = set(expected_layers) - set(present)
        results.append(CheckResult("1.1", "Block 1", "Capas hexagonales presentes", "fail", severity="high", detail=f"faltan: {missing}"))

    # 1.2 - Domain sin imports framework
    forbidden_imports = r"import (org\.springframework|jakarta\.persistence|org\.springframework\.web|javax\.ws)"
    forbidden_found: list[str] = []
    for d in src_java.rglob("domain"):
        if not d.is_dir():
            continue
        for f in d.rglob("*.java"):
            text = _read_or_empty(f)
            if re.search(forbidden_imports, text):
                forbidden_found.append(str(f.relative_to(ctx.migrated_path)))
    if forbidden_found:
        results.append(CheckResult("1.2", "Block 1", "Domain sin imports framework", "fail", severity="high", detail=f"{len(forbidden_found)} archivo(s) con imports prohibidos"))
    else:
        results.append(CheckResult("1.2", "Block 1", "Domain sin imports framework", "pass"))

    # 1.3 - Ports son interfaces (NUNCA abstract classes)
    for app_dir in src_java.rglob("application"):
        if not app_dir.is_dir():
            continue
        abstract_ports: list[str] = []
        for f in app_dir.rglob("**/port/**/*.java"):
            text = _read_or_empty(f)
            if re.search(r"public abstract class \w+Port\b", text):
                abstract_ports.append(f.name)
        if abstract_ports:
            results.append(
                CheckResult(
                    "1.3",
                    "Block 1",
                    "Ports son interfaces",
                    "fail",
                    severity="high",
                    detail=f"{len(abstract_ports)} port(s) como abstract class: {', '.join(abstract_ports[:3])}",
                    suggested_fix="Convertir a `public interface`",
                )
            )
        else:
            results.append(CheckResult("1.3", "Block 1", "Ports son interfaces", "pass"))
        break

    # 1.3b - Layout de ports compatible con peer-review del banco
    legacy_port_layouts = [
        p
        for pattern in ("application/port/input", "application/port/output")
        for p in src_java.rglob(pattern)
        if p.exists()
    ]
    if legacy_port_layouts:
        details = ", ".join(
            str(p.relative_to(ctx.migrated_path)) for p in legacy_port_layouts
        )
        results.append(
            CheckResult(
                "1.3b",
                "Block 1",
                "Layout de ports peer-review compatible",
                "fail",
                severity="medium",
                detail=f"Layout legacy detectado: {details}",
                suggested_fix=(
                    "Mover ports a application/input/port y application/output/port "
                    "para evitar penalizacion de Paquetes en architectureReview."
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                "1.3b",
                "Block 1",
                "Layout de ports peer-review compatible",
                "pass",
            )
        )

    # 1.4 - UN output port POR DOMINIO de UMP invocado
    # Regla actualizada (v0.3.2): el numero de output ports debe coincidir con la
    # cantidad de dominios distintos de UMPs invocados por el servicio. Cada UMP
    # de un mismo dominio se consolida en 1 solo port/adapter del dominio.

    # Listar todos los *OutputPort en layout canonico y legacy.
    actual_ports: list[str] = []
    output_port_patterns = (
        "application/output/port/*OutputPort.java",
        "application/port/output/*OutputPort.java",
    )
    for pattern in output_port_patterns:
        for f in src_java.rglob(pattern):
            actual_ports.append(f.stem)

    # Si tenemos contexto de UMPs (provistos por el orquestador del check), comparamos
    expected_domains = getattr(ctx, "ump_domains", None)
    if expected_domains is not None:
        # Detectar a que dominio pertenece cada port encontrado
        from capamedia_cli.core.domain_mapping import SERVICE_PREFIX_TO_DOMAIN, UMP_PREFIX_TO_DOMAIN

        all_domain_names = {d.pascal for d in SERVICE_PREFIX_TO_DOMAIN.values()} | {
            d.pascal for d in UMP_PREFIX_TO_DOMAIN.values()
        }
        ports_by_domain: dict[str, list[str]] = {}
        for port in actual_ports:
            for dom in all_domain_names:
                if port.startswith(dom):
                    ports_by_domain.setdefault(dom, []).append(port)
                    break

        expected_set = {d.pascal for d in expected_domains}
        actual_set = set(ports_by_domain.keys())

        missing = expected_set - actual_set
        extra = actual_set - expected_set
        duplicated = {d: ps for d, ps in ports_by_domain.items() if len(ps) > 1}

        if missing:
            results.append(
                CheckResult(
                    "1.4",
                    "Block 1",
                    "1 output port por dominio de UMP invocado",
                    "fail",
                    severity="high",
                    detail=f"Faltan ports para dominios: {sorted(missing)}",
                    suggested_fix=(
                        "Agregar 1 output port por cada dominio. Ej: para UMPSeguridad* "
                        "crear SecurityOutputPort + SecurityBancsAdapter."
                    ),
                )
            )
        elif duplicated:
            dup_str = ", ".join(f"{d}: {len(ps)} ports" for d, ps in duplicated.items())
            results.append(
                CheckResult(
                    "1.4",
                    "Block 1",
                    "1 output port por dominio de UMP invocado",
                    "fail",
                    severity="high",
                    detail=f"Dominios con mas de 1 port: {dup_str}",
                    suggested_fix="Consolidar los ports del mismo dominio en uno solo (Rule FB-JG)",
                )
            )
        elif extra:
            results.append(
                CheckResult(
                    "1.4",
                    "Block 1",
                    "1 output port por dominio de UMP invocado",
                    "pass",
                    detail=f"OK ({len(actual_set)} dominios). Extras no requeridos: {sorted(extra)}",
                )
            )
        else:
            results.append(
                CheckResult(
                    "1.4",
                    "Block 1",
                    "1 output port por dominio de UMP invocado",
                    "pass",
                    detail=f"{len(actual_set)} dominios = {len(expected_set)} esperados",
                )
            )
    else:
        # Fallback al comportamiento viejo (sin contexto de UMPs): solo contar Bancs
        bancs_ports = sum(
            1 for p in actual_ports if "bancs" in p.lower()
        )
        if bancs_ports == 0:
            results.append(
                CheckResult(
                    "1.4",
                    "Block 1",
                    "Output port unico (sin contexto de UMPs)",
                    "pass",
                    detail="0 ports Bancs detectados",
                )
            )
        elif bancs_ports == 1:
            results.append(
                CheckResult(
                    "1.4", "Block 1", "Output port unico (sin contexto de UMPs)", "pass"
                )
            )
        else:
            results.append(
                CheckResult(
                    "1.4",
                    "Block 1",
                    "Output port unico (sin contexto de UMPs)",
                    "fail",
                    severity="high",
                    detail=f"{bancs_ports} ports Bancs detectados",
                    suggested_fix=(
                        "Consolidar por dominio. Pasar ump_domains a CheckContext "
                        "para validacion mas precisa."
                    ),
                )
            )

    # 1.5 - Application no importa infrastructure
    bad_imports: list[str] = []
    for f in src_java.rglob("application/**/*.java"):
        text = _read_or_empty(f)
        if re.search(r"import .+\.infrastructure\.", text):
            bad_imports.append(f.name)
    if bad_imports:
        results.append(CheckResult("1.5", "Block 1", "Application no importa infrastructure", "fail", severity="high", detail=f"{len(bad_imports)} archivo(s) violan la regla"))
    else:
        results.append(CheckResult("1.5", "Block 1", "Application no importa infrastructure", "pass"))

    return results


# -- Block 2: Logging ------------------------------------------------------


def run_block_2(ctx: CheckContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    src_java = ctx.migrated_path / "src" / "main" / "java"

    # 2.1 - @BpTraceable en controllers
    controllers = list(src_java.rglob("*Controller.java")) + list(src_java.rglob("*Endpoint.java"))
    missing_traceable: list[str] = []
    for f in controllers:
        text = _read_or_empty(f)
        if "@BpTraceable" not in text:
            missing_traceable.append(f.name)
    if missing_traceable:
        results.append(CheckResult("2.1", "Block 2", "@BpTraceable en controllers", "fail", severity="high", detail=f"{len(missing_traceable)} sin anotacion"))
    else:
        results.append(CheckResult("2.1", "Block 2", "@BpTraceable en controllers", "pass", detail=f"{len(controllers)} controller(s)"))

    # 2.2 - Sin imports de org.slf4j
    slf4j = _grep_files(src_java, r"import org\.slf4j\.")
    if slf4j:
        results.append(CheckResult("2.2", "Block 2", "Sin imports org.slf4j", "fail", severity="high", detail=f"{len(slf4j)} hit(s)", suggested_fix="Usar @Slf4j de Lombok, nunca import directo"))
    else:
        results.append(CheckResult("2.2", "Block 2", "Sin imports org.slf4j", "pass"))

    return results


# -- Block 5: Error handling (simplificado) --------------------------------


def run_block_5(ctx: CheckContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    src_java = ctx.migrated_path / "src" / "main" / "java"

    # 5.1 - BancsClientHelper atrapa RuntimeException
    helpers = list(src_java.rglob("*BancsClientHelper*.java"))
    if not helpers:
        helpers = list(src_java.rglob("*BancsHelper*.java"))
    if helpers:
        text = _read_or_empty(helpers[0])
        if re.search(r"catch\s*\(\s*RuntimeException", text):
            results.append(CheckResult("5.1", "Block 5", "BancsClientHelper catchea RuntimeException", "pass"))
        else:
            results.append(CheckResult("5.1", "Block 5", "BancsClientHelper catchea RuntimeException", "fail", severity="high", detail="helper no atrapa RuntimeException", suggested_fix="Agregar catch (RuntimeException e) { throw new BancsOperationException(...); }"))

    return results


# -- Block 7: Config externa -----------------------------------------------


def run_block_7(ctx: CheckContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    app_yml = ctx.migrated_path / "src" / "main" / "resources" / "application.yml"

    # 7.1 - application.yml existe
    if not _file_exists(app_yml):
        results.append(CheckResult("7.1", "Block 7", "application.yml presente", "fail", severity="high", detail="archivo faltante"))
        return results
    results.append(CheckResult("7.1", "Block 7", "application.yml presente", "pass"))

    # 7.2 - Secrets via ${CCC_*}
    text = _read_or_empty(app_yml)
    hardcoded: list[str] = []
    for line in text.splitlines():
        if re.search(r"(password|token|secret|user):\s*[^$\s][^\s]*", line, re.IGNORECASE) and "${" not in line:
            hardcoded.append(line.strip())
    if hardcoded:
        results.append(CheckResult("7.2", "Block 7", "Secrets via env vars", "fail", severity="high", detail=f"{len(hardcoded)} valores hardcoded"))
    else:
        results.append(CheckResult("7.2", "Block 7", "Secrets via env vars", "pass"))

    # 7.3 - Helm probes
    helm_dir = ctx.migrated_path / "helm"
    if helm_dir.exists():
        missing_probes: list[str] = []
        for f in helm_dir.rglob("values*.yml"):
            text = _read_or_empty(f)
            if "livenessProbe" not in text or "readinessProbe" not in text:
                missing_probes.append(f.name)
        if missing_probes:
            results.append(CheckResult("7.3", "Block 7", "Helm probes en todos los values", "fail", severity="high", detail=f"falta en {', '.join(missing_probes)}"))
        else:
            results.append(CheckResult("7.3", "Block 7", "Helm probes en todos los values", "pass"))

        # 7.4 - Helm HPA averageValue oficial del banco
        hpa_files = [
            helm_dir / name
            for name in (
                "dev.yml",
                "test.yml",
                "prod.yml",
                "values-dev.yml",
                "values-test.yml",
                "values-prod.yml",
                "values-dev.yaml",
                "values-test.yaml",
                "values-prod.yaml",
            )
            if (helm_dir / name).exists()
        ]
        wrong_hpa_values: list[str] = []
        checked_hpa_values = 0
        for f in hpa_files:
            text = _read_or_empty(f)
            for match in re.finditer(r"(?m)^\s*averageValue\s*:\s*[\"']?([^\"'\s#]+)", text):
                checked_hpa_values += 1
                value = match.group(1)
                if value != "100m":
                    rel = _relative_display(f, ctx.migrated_path)
                    wrong_hpa_values.append(f"{rel} - averageValue: '{value}' -> debe ser '100m'")
        if wrong_hpa_values:
            results.append(
                CheckResult(
                    "7.4",
                    "Block 7",
                    "Helm HPA averageValue",
                    "fail",
                    severity="high",
                    detail="; ".join(wrong_hpa_values),
                    suggested_fix="Cambiar averageValue a 100m en helm/dev.yml, helm/test.yml y helm/prod.yml.",
                )
            )
        elif checked_hpa_values:
            results.append(CheckResult("7.4", "Block 7", "Helm HPA averageValue", "pass"))

    return results


# -- Block 13: WAS+DB specifics --------------------------------------------


def run_block_13(ctx: CheckContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    build_gradle = ctx.migrated_path / "build.gradle"
    app_yml = ctx.migrated_path / "src" / "main" / "resources" / "application.yml"

    if not _file_exists(build_gradle):
        return results

    gradle_text = _read_or_empty(build_gradle)
    has_jpa = "spring-boot-starter-data-jpa" in gradle_text
    if not has_jpa:
        return results  # No aplica BLOQUE 13

    # 13.1 - JPA y WebFlux no conviven
    has_webflux = "spring-boot-starter-webflux" in gradle_text
    if has_jpa and has_webflux:
        results.append(CheckResult("13.1", "Block 13", "JPA + WebFlux NO conviven", "fail", severity="high", detail="build.gradle tiene AMBOS starters", suggested_fix="Remover webflux si hay JPA, usar MVC"))
    else:
        results.append(CheckResult("13.1", "Block 13", "JPA + WebFlux NO conviven", "pass"))

    # 13.4 - ddl-auto validate
    yml_text = _read_or_empty(app_yml)
    ddl_match = re.search(r"ddl-auto:\s*(\w+)", yml_text)
    if ddl_match:
        val = ddl_match.group(1)
        if val == "validate":
            results.append(CheckResult("13.4", "Block 13", "ddl-auto: validate", "pass"))
        else:
            results.append(CheckResult("13.4", "Block 13", "ddl-auto: validate", "fail", severity="high", detail=f"valor actual: {val}"))

    # 13.5 - open-in-view: false
    if "open-in-view: false" in yml_text:
        results.append(CheckResult("13.5", "Block 13", "open-in-view: false", "pass"))
    else:
        results.append(CheckResult("13.5", "Block 13", "open-in-view: false", "fail", severity="medium", detail="falta o es true"))

    # 13.11 - WAS + Hikari must validate connections with SELECT 1.
    if (ctx.source_type or "").lower() == "was":
        if re.search(r"connection-test-query\s*:\s*SELECT\s+1\b", yml_text, re.IGNORECASE):
            results.append(
                CheckResult(
                    "13.11",
                    "Block 13",
                    "WAS Hikari connection-test-query",
                    "pass",
                    detail="connection-test-query: SELECT 1 presente",
                )
            )
        else:
            results.append(
                CheckResult(
                    "13.11",
                    "Block 13",
                    "WAS Hikari connection-test-query",
                    "fail",
                    severity="high",
                    detail="WAS con JPA/Hikari no define connection-test-query: SELECT 1",
                    suggested_fix=(
                        "Agregar bajo spring.datasource.hikari: "
                        "`connection-test-query: SELECT 1`"
                    ),
                )
            )

    return results


# -- Block 15: Estructura de error (PDF BPTPSRE oficial) -------------------


def run_block_15(ctx: CheckContext) -> list[CheckResult]:
    """Valida la estructura del bloque <error> del PDF oficial BPTPSRE.

    8 campos contractuales: codigo, mensaje, mensajeNegocio, tipo, recurso,
    componente, backend, severidad. Reglas:
    - mensajeNegocio: NUNCA lo setea el microservicio (lo pone DataPower)
    - recurso: formato <NOMBRE_SERVICIO>/<METODO>
    - componente IIB: <NOMBRE_SERVICIO> / ApiClient / TX<NNNNNN>
    - componente WAS: <NOMBRE_SERVICIO>, <METODO>, <VALOR_ARCHIVO_CONFIG>
    - backend: viene del catalogo codigosBackend.xml, NO hardcoded arbitrario
    """
    results: list[CheckResult] = []
    src_java = ctx.migrated_path / "src" / "main" / "java"
    if not src_java.exists():
        return results

    # 15.1 - mensajeNegocio no debe tener valor real desde el codigo.
    # Empty/null is allowed to preserve the SOAP/DataPower slot when JAXB would
    # otherwise omit the element.
    hits = _grep_files(src_java, r"setMensajeNegocio\s*\(")
    bad = [(f, ln, line) for f, ln, line in hits if not _allowed_mensaje_negocio_slot(line)]
    empty_slots = [(f, ln, line) for f, ln, line in hits if _allowed_mensaje_negocio_slot(line)]
    if bad:
        results.append(
            CheckResult(
                "15.1",
                "Block 15",
                "mensajeNegocio sin valor real desde el codigo",
                "fail",
                severity="high",
                detail=(
                    f"{len(bad)} hit(s) con valor real: DataPower gestiona "
                    "mensajeNegocio; el servicio solo puede emitir null/vacio."
                ),
                suggested_fix=(
                    "No poblar mensajeNegocio con texto de negocio. Usar null o "
                    '"" solo cuando el contrato SOAP requiere que el tag exista.'
                ),
            )
        )
    else:
        detail = (
            f"{len(empty_slots)} setter(s) null/vacio aceptado(s) para preservar el slot SOAP"
            if empty_slots
            else ""
        )
        results.append(
            CheckResult(
                "15.1",
                "Block 15",
                "mensajeNegocio sin valor real desde el codigo",
                "pass",
                detail=detail,
            )
        )

    # 15.2 - recurso con formato <service>/<method>
    recurso_matches = _grep_files(src_java, r"setRecurso\s*\(\s*[\"']")
    if not recurso_matches:
        results.append(
            CheckResult(
                "15.2",
                "Block 15",
                "recurso populado en algun mapper/resolver",
                "fail",
                severity="medium",
                detail="No se encontro setRecurso(...) en ningun archivo",
                suggested_fix="El mapper del error debe setear recurso = 'service-name/method-name'",
            )
        )
    else:
        # Ver si al menos un hit tiene formato '/'
        has_slash = False
        for _f, _ln, line in recurso_matches:
            if "/" in line:
                has_slash = True
                break
        if has_slash:
            results.append(
                CheckResult(
                    "15.2",
                    "Block 15",
                    "recurso con formato service/method",
                    "pass",
                    detail=f"{len(recurso_matches)} hit(s), al menos uno con '/'",
                )
            )
        else:
            results.append(
                CheckResult(
                    "15.2",
                    "Block 15",
                    "recurso con formato service/method",
                    "fail",
                    severity="medium",
                    detail="setRecurso encontrado pero ninguno tiene '/' en el valor",
                    suggested_fix="Formato esperado: '<nombre-servicio>/<metodo>'",
                )
            )

    # 15.3 - componente con valor valido (IIB: service/ApiClient/TXnnnnnn)
    comp_matches = _grep_files(src_java, r"setComponente\s*\(\s*[\"']")
    if comp_matches:
        valid_patterns = (
            re.compile(r"TX\d{6}"),  # TX plus 6 digits
            re.compile(r"ApiClient"),
        )
        has_valid = False
        for _f, _ln, line in comp_matches:
            if any(p.search(line) for p in valid_patterns):
                has_valid = True
                break
            # Tambien vale literal service-name (ej 'WSClientes0007')
            if re.search(r"[\"']WS\w+\d+[\"']|[\"']ORQ\w+\d+[\"']|[\"']tnd-msa-", line):
                has_valid = True
                break
        if has_valid:
            results.append(
                CheckResult(
                    "15.3",
                    "Block 15",
                    "componente con valor reconocido (service/ApiClient/TX)",
                    "pass",
                )
            )
        else:
            results.append(
                CheckResult(
                    "15.3",
                    "Block 15",
                    "componente con valor reconocido (service/ApiClient/TX)",
                    "fail",
                    severity="medium",
                    detail="setComponente encontrado pero sin valor valido reconocido",
                    suggested_fix="Usar uno de: <nombre-servicio>, 'ApiClient', 'TX<6-digitos>'",
                )
            )
    else:
        results.append(
            CheckResult(
                "15.3",
                "Block 15",
                "componente populado en algun mapper",
                "fail",
                severity="medium",
                detail="No se encontro setComponente(...) en ningun archivo",
            )
        )

    # 15.4 - backend no hardcoded arbitrario (debe venir del catalogo, codigos tipicos de 5 digitos)
    backend_matches = _grep_files(src_java, r"setBackend\s*\(\s*[\"']([0-9]+)[\"']")
    if backend_matches:
        # Codigos conocidos del catalogo: 00045 (Bancs), 00638 (IIB/Bus), 00640 (DataPower), etc.
        # Warning si vemos un codigo que parece inventado (ej "00000" o ""999")
        suspect = [
            (f, ln, line) for f, ln, line in backend_matches if '"00000"' in line or '"999"' in line
        ]
        if suspect:
            results.append(
                CheckResult(
                    "15.4",
                    "Block 15",
                    "backend codes del catalogo (no inventados)",
                    "fail",
                    severity="high",
                    detail=f"{len(suspect)} hit(s) con codigos sospechosos (00000/999)",
                    suggested_fix="Usar codigos del catalogo: 00045 (Bancs), 00638 (IIB), 00640 (DataPower)",
                )
            )
        else:
            results.append(
                CheckResult(
                    "15.4",
                    "Block 15",
                    "backend codes del catalogo (no inventados)",
                    "pass",
                    detail=f"{len(backend_matches)} hit(s), todos con codigos plausibles",
                )
            )
    # Si no hay setBackend, no penalizamos (puede venir de constants)

    return results


# -- Block 14: SonarLint ----------------------------------------------------


def run_block_14(ctx: CheckContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    binding = ctx.migrated_path / ".sonarlint" / "connectedMode.json"

    # 14.1 - Existe
    if not _file_exists(binding):
        results.append(CheckResult("14.1", "Block 14", ".sonarlint/connectedMode.json presente", "fail", severity="high", detail="archivo faltante", suggested_fix="Bindar en VS Code y Share Configuration"))
        results.append(_deployment_gitignore_check(ctx))
        return results
    results.append(CheckResult("14.1", "Block 14", ".sonarlint/connectedMode.json presente", "pass"))

    # 14.2 - org correcto
    try:
        data = json.loads(_read_or_empty(binding))
    except json.JSONDecodeError:
        results.append(CheckResult("14.2", "Block 14", "connectedMode.json valido", "fail", severity="high", detail="JSON invalido"))
        results.append(_deployment_gitignore_check(ctx))
        return results
    if data.get("sonarCloudOrganization") == "bancopichinchaec":
        results.append(CheckResult("14.2", "Block 14", "org = bancopichinchaec", "pass"))
    else:
        results.append(CheckResult("14.2", "Block 14", "org = bancopichinchaec", "fail", severity="high", detail=f"actual: {data.get('sonarCloudOrganization', '')}"))

    # 14.3 - projectKey no es placeholder
    key = data.get("projectKey", "")
    if not key or "<" in key:
        results.append(CheckResult("14.3", "Block 14", "projectKey no es placeholder", "fail", severity="high", detail=f"actual: {key}"))
    else:
        results.append(CheckResult("14.3", "Block 14", "projectKey no es placeholder", "pass"))

    # 14.4 - El binding compartido no puede quedar ignorado por .gitignore.
    if _git_ignores(ctx.migrated_path, ".sonarlint/connectedMode.json"):
        results.append(
            CheckResult(
                "14.4",
                "Block 14",
                ".sonarlint/connectedMode.json no gitignored",
                "fail",
                severity="medium",
                detail="git check-ignore marca el binding como ignorado",
                suggested_fix=(
                    "Ajustar .gitignore: ignorar cache local de .sonarlint/* pero "
                    "mantener !.sonarlint/connectedMode.json"
                ),
            )
        )
    else:
        results.append(
            CheckResult("14.4", "Block 14", ".sonarlint/connectedMode.json no gitignored", "pass")
        )

    results.append(_deployment_gitignore_check(ctx))
    return results


# -- Block 16: SonarCloud custom rules (non-official_bank_script) ----------
#
# Reglas que no estan en validate_hexagonal.py pero que SonarCloud del banco
# reporta como violations en Quality Gate. Fuente: config custom del banco en
# SonarCloud; no tenemos el script, solo la heuristica observada.


TEST_CLASS_ANNOTATIONS = (
    "@SpringBootTest",
    "@WebMvcTest",
    "@WebFluxTest",
    "@DataJpaTest",
    "@JsonTest",
    "@RestClientTest",
    "@JdbcTest",
    "@ExtendWith",                 # JUnit 5 (SpringExtension, MockitoExtension)
    "@RunWith",                    # JUnit 4 legacy (SpringRunner)
    "@AutoConfigureMockMvc",
)


def run_block_16(ctx: CheckContext) -> list[CheckResult]:
    """Block 16: SonarCloud custom rule — test classes must declare a test
    annotation (@SpringBootTest / @WebMvcTest / @ExtendWith / etc.).

    Busca `*Test.java` / `*Tests.java` bajo `src/test/java/**`. Si alguno no
    tiene ninguna de las anotaciones reconocidas, lo flaggea con severidad
    MEDIUM. Autofix disponible en `core/bank_autofix.fix_add_test_annotation`.
    """
    results: list[CheckResult] = []
    test_root = ctx.migrated_path / "src" / "test" / "java"
    if not test_root.exists():
        results.append(
            CheckResult(
                "16.1", "Block 16", "Anotacion de test en @Test classes",
                "pass", detail="sin src/test/java/",
            )
        )
        return results

    test_files = [
        f
        for f in test_root.rglob("*.java")
        if f.name.endswith("Test.java") or f.name.endswith("Tests.java")
    ]
    if not test_files:
        results.append(
            CheckResult(
                "16.1", "Block 16", "Anotacion de test en @Test classes",
                "pass", detail="sin archivos *Test.java",
            )
        )
        return results

    missing: list[str] = []
    for f in test_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        has_any = any(ann in text for ann in TEST_CLASS_ANNOTATIONS)
        if not has_any:
            missing.append(str(f.relative_to(ctx.migrated_path)))

    if missing:
        results.append(
            CheckResult(
                "16.1", "Block 16", "Anotacion de test en @Test classes",
                "fail", severity="medium",
                detail=(
                    f"{len(missing)}/{len(test_files)} sin anotacion de test "
                    f"(SonarCloud custom). Requerida: @SpringBootTest, "
                    f"@WebMvcTest, @WebFluxTest, @DataJpaTest, @ExtendWith, etc. "
                    f"Primeros: {', '.join(missing[:3])}"
                ),
                suggested_fix=(
                    "Agregar @SpringBootTest al test o usar @ExtendWith"
                    "(MockitoExtension.class) para unit tests puros."
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                "16.1", "Block 16", "Anotacion de test en @Test classes",
                "pass",
                detail=f"{len(test_files)}/{len(test_files)} con anotacion correcta",
            )
        )

    return results


# -- Main orchestrator -----------------------------------------------------


# -- Block 17: Log transaccional (EXCLUSIVO ORQ) ---------------------------
#
# Librería `com.pichincha.common:lib-event-logs-webflux:1.0.0` que publica
# request/response al topico Kafka de auditoria (CE_EVENTOS). Luego
# WSTecnicos0038 (servicio tecnico compartido del banco, NO es nuestro)
# aplica plantillas XML y publica el JSON final en CE_TRANSACCIONAL que
# consume Elastic/Observabilidad.
#
# AMBITO ESTRICTO: aplica UNICAMENTE a orquestadores (ORQ).
# Cita literal del PDF 1 (Estructura Log Transaccional):
#   "Los eventos se generan unicamente en los orquestadores."
#
# No aplica a:
#   - WAS  (microservicios REST/MVC terminales): NO llevan @EventAudit ni
#          lib-event-logs. Si aparecen, son error de copy-paste.
#   - BUS  (SOAP IIB migrados a Java): usan su propio tracing, no esta lib.
#   - UMPs (stores embebidos en WAS): componentes internos, no aplican.
#
# Fuentes oficiales:
#   - BPTPSRE-Estructura Log Transaccional-220426-215404.pdf (flujo, mapeo)
#   - BPTPSRE-Libreria Log Transaccional-220426-202920.pdf (lib, config)
# Canonical: context/log-transaccional-orq.md (7 reglas LT-1..LT-7)


def _looks_like_orq(ctx: CheckContext) -> bool:
    """Heuristica: el proyecto es ORQ si el nombre contiene 'orq'.
    Ej: `tnd-msa-sp-orqclientes0027`. Tambien respeta metadata del
    catalog-info.yaml si existe."""
    name = ctx.migrated_path.name.lower()
    if "orq" in name:
        return True
    # Fallback: leer catalog-info.yaml (algunos equipos no meten 'orq' en el
    # nombre del repo pero si en el title/tags).
    catalog = ctx.migrated_path / "catalog-info.yaml"
    if catalog.exists():
        try:
            txt = catalog.read_text(encoding="utf-8", errors="ignore").lower()
            if "orq" in txt:
                return True
        except OSError:
            pass
    return False


def run_block_17(ctx: CheckContext) -> list[CheckResult]:
    """Block 17: Log transaccional — EXCLUSIVO ORQ.

    Si el proyecto no es ORQ (WAS/BUS/UMP), el bloque se omite por completo
    — NO emite ni PASS ni FAIL. Las reglas LT-1..LT-7 solo aplican a ORQ.

    Checks cuando es ORQ:
      17.1 - dependencia lib-event-logs-webflux en build.gradle
      17.2 - bloques spring.kafka + logging.event en application.yml
      17.3 - logging.level.org.apache.kafka: OFF presente
      17.4 - al menos 1 @EventAudit en adapters
    """
    if not _looks_like_orq(ctx):
        # Skip block entero: el proyecto no es ORQ, las reglas no aplican.
        # (Cita PDF 1: "los eventos se generan unicamente en los orquestadores")
        return []

    results: list[CheckResult] = []
    root = ctx.migrated_path

    # 17.1 dependencia lib-event-logs-*
    gradle_text = ""
    for gf in root.rglob("build.gradle"):
        if "test" in gf.parts:
            continue
        try:
            gradle_text += gf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    has_webflux_logs = "lib-event-logs-webflux" in gradle_text
    has_mvc_logs = "lib-event-logs-mvc" in gradle_text
    if has_webflux_logs or has_mvc_logs:
        variant = "webflux" if has_webflux_logs else "mvc"
        results.append(
            CheckResult(
                "17.1", "Block 17", "Dependencia lib-event-logs (ORQ)",
                "pass",
                detail=f"lib-event-logs-{variant}:1.0.0 presente",
            )
        )
    else:
        results.append(
            CheckResult(
                "17.1", "Block 17", "Dependencia lib-event-logs (ORQ)",
                "fail", severity="high",
                detail=(
                    "ORQ sin `com.pichincha.common:lib-event-logs-webflux:1.0.0` "
                    "(o -mvc) en build.gradle"
                ),
                suggested_fix=(
                    "Agregar implementation 'com.pichincha.common:"
                    "lib-event-logs-webflux:1.0.0' al bloque dependencies"
                ),
            )
        )

    # 17.2 / 17.3 bloques spring.kafka + logging.event en yml
    yml_texts: list[str] = []
    for y in root.rglob("application.yml"):
        if any(p.lower() in {"test", "tests"} for p in y.parts[:-1]):
            continue
        try:
            yml_texts.append(y.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    full_yml = "\n".join(yml_texts)
    has_spring_kafka = "spring:" in full_yml and "kafka:" in full_yml
    has_logging_event = "logging:" in full_yml and "event:" in full_yml
    # Check 17.3: heuristica lineal (evita catastrophic backtracking del
    # regex anidado previo). Buscamos `kafka: OFF` y `apache:` en el mismo
    # yml; asumimos que si ambos aparecen, es la config `logging.level.org.
    # apache.kafka: OFF` correcta. Caso borde (kafka: OFF fuera de apache:)
    # es extremadamente raro en configs reales.
    has_kafka_off = "apache:" in full_yml and "kafka: OFF" in full_yml

    if has_spring_kafka and has_logging_event:
        results.append(
            CheckResult(
                "17.2", "Block 17", "spring.kafka + logging.event en yml",
                "pass", detail="bloques presentes",
            )
        )
    else:
        missing = []
        if not has_spring_kafka:
            missing.append("spring.kafka")
        if not has_logging_event:
            missing.append("logging.event")
        results.append(
            CheckResult(
                "17.2", "Block 17", "spring.kafka + logging.event en yml",
                "fail", severity="high",
                detail=f"faltan bloques: {', '.join(missing)}",
                suggested_fix=(
                    "Copiar los bloques del canonical "
                    "`context/log-transaccional-orq.md` a application.yml"
                ),
            )
        )

    if has_kafka_off:
        results.append(
            CheckResult(
                "17.3", "Block 17", "logging.level.org.apache.kafka: OFF",
                "pass", detail="Kafka logs apagados en el pod",
            )
        )
    else:
        results.append(
            CheckResult(
                "17.3", "Block 17", "logging.level.org.apache.kafka: OFF",
                "fail", severity="medium",
                detail="el pod se va a llenar de logs Kafka",
                suggested_fix=(
                    "Agregar en application.yml: logging.level.org.apache.kafka: OFF"
                ),
            )
        )

    # 17.4 @EventAudit en al menos 1 adapter
    event_audit_hits = 0
    adapter_files = 0
    for java in root.rglob("*.java"):
        if "test" in [p.lower() for p in java.parts]:
            continue
        if "adapter" not in [p.lower() for p in java.parts]:
            continue
        adapter_files += 1
        try:
            text = java.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "@EventAudit" in text:
            event_audit_hits += 1

    if event_audit_hits > 0:
        results.append(
            CheckResult(
                "17.4", "Block 17", "@EventAudit en adapters",
                "pass",
                detail=f"{event_audit_hits}/{adapter_files} adapter(s) anotados",
            )
        )
    elif adapter_files == 0:
        results.append(
            CheckResult(
                "17.4", "Block 17", "@EventAudit en adapters",
                "pass",
                detail="sin adapters en el proyecto (skip)",
            )
        )
    else:
        results.append(
            CheckResult(
                "17.4", "Block 17", "@EventAudit en adapters",
                "fail", severity="high",
                detail=f"0/{adapter_files} adapter(s) con @EventAudit",
                suggested_fix=(
                    'Agregar @EventAudit(service="<SvcName>", '
                    'method="<OpName>", type=AuditType.T) al metodo que invoca '
                    "downstream en cada adapter"
                ),
            )
        )

    return results


# -- Block 18: Detector inverso — log transaccional fuera de ORQ ------------
#
# Contra-regla del Block 17: si un WAS/BUS/UMP tiene restos de log
# transaccional (lib-event-logs en build.gradle, @EventAudit en codigo,
# bloques logging.event/spring.kafka en application.yml), es un error de
# copy-paste desde un ORQ y debe removerse.
#
# Cita PDF 1 (Estructura Log Transaccional):
#   "Los eventos se generan unicamente en los orquestadores."
#
# Solo corre cuando el proyecto NO es ORQ. En ORQ el Block 17 valida lo
# contrario (que si esten).


def run_block_18(ctx: CheckContext) -> list[CheckResult]:
    """Block 18: detecta log transaccional indebido en WAS/BUS/UMP.

    Checks (solo corren si NO es ORQ):
      18.1 - NO debe haber dependencia lib-event-logs-* en build.gradle
      18.2 - NO debe haber bloque logging.event en application.yml
      18.3 - NO debe haber @EventAudit en ningun .java del proyecto
    """
    if _looks_like_orq(ctx):
        # En ORQ esto es responsabilidad del Block 17, no aplicar aqui.
        return []

    results: list[CheckResult] = []
    root = ctx.migrated_path

    # 18.1 — lib-event-logs-* en build.gradle
    gradle_hits: list[str] = []
    for gf in root.rglob("build.gradle"):
        if "test" in gf.parts:
            continue
        try:
            txt = gf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "lib-event-logs" in txt:
            gradle_hits.append(str(gf.relative_to(root)))

    if gradle_hits:
        results.append(
            CheckResult(
                "18.1", "Block 18", "lib-event-logs en WAS/BUS (prohibido)",
                "fail", severity="high",
                detail=(
                    f"Dependencia lib-event-logs-* encontrada en: "
                    f"{', '.join(gradle_hits)}. Log transaccional es "
                    "EXCLUSIVO de orquestadores (cita PDF Estructura Log "
                    "Transaccional: 'los eventos se generan unicamente en "
                    "los orquestadores')."
                ),
                suggested_fix=(
                    "Remover linea `implementation "
                    "'com.pichincha.common:lib-event-logs-*'` del "
                    "build.gradle"
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                "18.1", "Block 18", "lib-event-logs en WAS/BUS (prohibido)",
                "pass",
                detail="sin dependencia lib-event-logs (correcto para no-ORQ)",
            )
        )

    # 18.2 — logging.event / spring.kafka auditor en application.yml
    # Markers unicos de la config de lib-event-logs (cualquiera con 1 hit
    # es suficiente senal de que alguien copio-pego de un ORQ).
    lt_markers = [
        "KAFKA_TOPIC_AUDITOR",     # env var exclusiva del lib
        "mode: 'EXTERNAL'",        # literal del yml de la libreria
        'mode: "EXTERNAL"',
        "lib-event-logs",
        "logging:\n  event:",      # bloque logging.event anidado (YAML indent 2)
        "event:\n    mode:",       # variante con indent distinto
        "xml:\n  template:\n    templates:",  # bloque plantillas XML
    ]
    yml_hits: list[str] = []
    for yml in list(root.rglob("application*.yml")) + list(
        root.rglob("application*.yaml")
    ):
        if "test" in yml.parts:
            continue
        try:
            txt = yml.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(m in txt for m in lt_markers):
            yml_hits.append(str(yml.relative_to(root)))

    if yml_hits:
        results.append(
            CheckResult(
                "18.2", "Block 18", "logging.event en yml WAS/BUS (prohibido)",
                "fail", severity="high",
                detail=(
                    f"Bloque logging.event/spring.kafka de auditoria "
                    f"encontrado en: {', '.join(yml_hits)}. Aplica solo a "
                    "ORQs."
                ),
                suggested_fix=(
                    "Remover los bloques `spring.kafka`, `logging.event` "
                    "y `xml.template.templates` del application.yml"
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                "18.2", "Block 18", "logging.event en yml WAS/BUS (prohibido)",
                "pass",
                detail="yml sin bloques de log transaccional (correcto)",
            )
        )

    # 18.3 — @EventAudit en codigo Java
    audit_hits: list[str] = []
    for jf in root.rglob("*.java"):
        if "test" in jf.parts or "build" in jf.parts:
            continue
        try:
            txt = jf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "@EventAudit" in txt:
            audit_hits.append(str(jf.relative_to(root)))

    if audit_hits:
        results.append(
            CheckResult(
                "18.3", "Block 18", "@EventAudit en WAS/BUS (prohibido)",
                "fail", severity="high",
                detail=(
                    f"Anotacion @EventAudit encontrada en: "
                    f"{', '.join(audit_hits[:5])}"
                    f"{'...' if len(audit_hits) > 5 else ''}"
                ),
                suggested_fix=(
                    "Remover @EventAudit y su import "
                    "`com.pichincha.common.lib.event.logs.*` de los "
                    "adapters del WAS/BUS"
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                "18.3", "Block 18", "@EventAudit en WAS/BUS (prohibido)",
                "pass",
                detail="sin @EventAudit en .java (correcto)",
            )
        )

    return results


_GENERIC_CLASS_NAMES = {
    "Service", "ServiceImpl",
    "Adapter",
    "Port", "InputPort", "OutputPort",
    "Controller",
    "Mapper",
    "Helper",
    "Request", "Response",
    "Dto",
    "Config",
    "Constants",
    "Exception",
    "Entity", "Repository",
}


_CLASS_DECL_RE = re.compile(
    r"^\s*public\s+(?:final\s+|abstract\s+)?"
    r"(?:class|interface|record|enum)\s+(\w+)",
    re.MULTILINE,
)


def run_block_3(ctx: CheckContext) -> list[CheckResult]:
    """Block 3 (v0.22.0): Naming profesional - sin nombres genericos.

    Clases e interfaces publicas deben tener un prefijo de dominio. Nombres
    como `Service.java`, `Adapter.java`, `Request.java` sin prefijo generan
    ambiguedad y no pasan peer review (check 3.5 del canonical).

    FAIL HIGH por cada clase con nombre en la blocklist `_GENERIC_CLASS_NAMES`.
    """
    results: list[CheckResult] = []
    src_java = ctx.migrated_path / "src" / "main" / "java"
    if not src_java.is_dir():
        return results

    offenders: list[tuple[str, Path]] = []
    for java_file in src_java.rglob("*.java"):
        if ".git" in java_file.parts or "build" in java_file.parts:
            continue
        try:
            text = java_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _CLASS_DECL_RE.finditer(text):
            class_name = match.group(1)
            if class_name in _GENERIC_CLASS_NAMES:
                offenders.append((class_name, java_file))

    if not offenders:
        results.append(CheckResult(
            "3.5", "Block 3", "Naming profesional - sin nombres genericos",
            "pass",
            detail="todas las clases/interfaces/records tienen prefijo de dominio",
        ))
        return results

    for class_name, java_file in offenders:
        rel = java_file.relative_to(ctx.migrated_path) if java_file.is_relative_to(ctx.migrated_path) else java_file
        results.append(CheckResult(
            f"3.5.{class_name}", "Block 3",
            f"Clase generica `{class_name}` sin prefijo de dominio",
            "fail",
            severity="high",
            detail=f"{rel}: clase se llama `{class_name}` (nombre generico)",
            suggested_fix=(
                f"Renombrar a algo especifico del dominio, ej "
                f"Customer{class_name}, Bancs{class_name}, "
                f"<Operation>{class_name}. El sufijo tecnico esta bien, "
                "lo que falta es el prefijo de negocio."
            ),
        ))

    return results


def run_block_19(ctx: CheckContext) -> list[CheckResult]:
    """Block 19 (v0.21.0): Properties delivery audit.

    Chequea que los `.properties` que `capamedia clone` marco como
    PENDING_FROM_BANK hayan sido entregados por el owner del servicio. Busca
    en `.capamedia/inputs/` (convencion oficial) y fallbacks.

    - PASS por archivo DELIVERED (todas las keys presentes)
    - FAIL MEDIUM por archivo PARTIAL (faltan keys)
    - FAIL MEDIUM por archivo STILL_PENDING
    - Skip si no hay properties-report.yaml (proyecto no paso por clone v0.19+)
    """
    from capamedia_cli.core.properties_delivery import audit_properties_delivery

    results: list[CheckResult] = []

    # El workspace es el parent de destino/<proj>/ o el project mismo si no
    # esta bajo destino/.
    if ctx.migrated_path.parent.name == "destino":
        workspace = ctx.migrated_path.parent.parent
    else:
        workspace = ctx.migrated_path

    audit = audit_properties_delivery(workspace)

    if audit.report_missing:
        # Proyecto pre-v0.19 sin properties-report.yaml. Skip silencioso:
        # el check solo aplica cuando clone detecto properties pendientes.
        return results

    pending_entries = [
        f for f in audit.files
        if f.status in ("DELIVERED", "PARTIAL", "STILL_PENDING")
    ]

    if not pending_entries:
        # No hay archivos pending en el reporte (todo era SHARED_CATALOG)
        results.append(
            CheckResult(
                "19.0", "Block 19", "Properties delivery audit",
                "pass",
                detail=(
                    "properties-report.yaml no lista archivos pendientes del "
                    "banco (todo resuelto por catalogo embebido)"
                ),
            )
        )
        return results

    for pf in pending_entries:
        check_id = f"19.{pf.file_name}"
        title = f"`{pf.file_name}` entregado por el owner"

        if pf.status == "DELIVERED":
            results.append(
                CheckResult(
                    check_id, "Block 19", title,
                    "pass",
                    detail=(
                        f"entregado en {pf.delivered_path} con "
                        f"{len(pf.keys_delivered)} keys ({len(pf.keys_declared)} requeridas)"
                    ),
                )
            )
        elif pf.status == "PARTIAL":
            results.append(
                CheckResult(
                    check_id, "Block 19", title,
                    "fail",
                    severity="medium",
                    detail=(
                        f"archivo encontrado en {pf.delivered_path} pero faltan "
                        f"{len(pf.keys_missing)} keys: {', '.join(pf.keys_missing)}"
                    ),
                    suggested_fix=(
                        "Pedir al owner las keys faltantes o agregarlas al archivo. "
                        "Luego re-correr `capamedia checklist` (o `/doublecheck` en "
                        "Claude Code) para re-detectar e inyectar. Mientras tanto, "
                        "`application.yml` mantiene placeholders ${CCC_*} para las "
                        "keys que faltan."
                    ),
                )
            )
        else:  # STILL_PENDING
            results.append(
                CheckResult(
                    check_id, "Block 19", title,
                    "fail",
                    severity="medium",
                    detail=(
                        f"NO ENTREGADO. Requiere {len(pf.keys_declared)} keys: "
                        f"{', '.join(pf.keys_declared)}. Source: {pf.source_hint}"
                    ),
                    suggested_fix=(
                        f"Pedir al owner el archivo {pf.file_name} y pegarlo en "
                        f"CUALQUIERA de estas ubicaciones (orden de prioridad): "
                        f"(1) `<workspace>/.capamedia/inputs/{pf.file_name}` (recomendado, "
                        f"gitignored); "
                        f"(2) `<workspace>/inputs/{pf.file_name}`; "
                        f"(3) `<workspace>/{pf.file_name}` (directo en la raiz). "
                        f"Luego re-correr `capamedia checklist` (o `/doublecheck` en "
                        f"Claude Code) para que lo autodetecte e inyecte los valores "
                        f"en `application.yml`."
                    ),
                )
            )

    return results


def run_block_20(ctx: CheckContext) -> list[CheckResult]:
    """Block 20 (v0.23.0): ORQ invoca al servicio MIGRADO, no al legacy.

    Solo aplica a servicios con `source_type=orq`. Busca en el codigo Java
    y YAML del migrado referencias a `sqb-msa-<svc>` o `ws-<svc>-was` como
    endpoint/URL/base-path, que indicarian que el ORQ esta apuntando al
    servicio legacy del target en vez del migrado.
    """
    results: list[CheckResult] = []
    if ctx.source_type != "orq":
        return results  # solo aplica a ORQ

    src_dir = ctx.migrated_path / "src" / "main"
    if not src_dir.is_dir():
        return results

    # Patrones de referencias INCORRECTAS al legacy del target
    bad_patterns = [
        (re.compile(r'["\'`](?:/|https?://[^"\'`]*/)?sqb-msa-([a-z]+\d{4})[^"\'`]*["\'`]'),
         "sqb-msa-<svc>"),
        (re.compile(r'["\'`](?:/|https?://[^"\'`]*/)?ws-([a-z]+\d{4})-was[^"\'`]*["\'`]'),
         "ws-<svc>-was"),
    ]

    offenders: list[tuple[Path, str, str]] = []
    for f in src_dir.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix not in (".java", ".yml", ".yaml", ".properties", ".xml"):
            continue
        if "build" in f.parts or "target" in f.parts:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for regex, label in bad_patterns:
            for m in regex.finditer(text):
                svc_name = m.group(1)
                # Excluir si el svc_name es el propio ORQ (ej. "orqclientes0027"
                # referenciado en su propio artifactId).
                if svc_name.startswith("orq"):
                    continue
                offenders.append((f, label, svc_name))

    if not offenders:
        results.append(CheckResult(
            "20.1", "Block 20",
            "ORQ no referencia legacy del servicio target",
            "pass",
            detail="no se encontraron referencias a sqb-msa-<svc>/ws-<svc>-was en src/main/",
        ))
        return results

    # Un FAIL HIGH por cada ocurrencia
    for f, pattern_label, svc_name in offenders:
        try:
            rel = f.relative_to(ctx.migrated_path)
        except ValueError:
            rel = f
        results.append(CheckResult(
            f"20.1.{svc_name}", "Block 20",
            f"ORQ referencia legacy del target `{svc_name}`",
            "fail",
            severity="high",
            detail=f"{rel}: contiene referencia a `{pattern_label}` del servicio `{svc_name}`",
            suggested_fix=(
                f"El ORQ debe invocar al servicio MIGRADO `<namespace>-msa-sp-{svc_name}` "
                "en tpl-middleware, NO al legacy. Cambiar el endpoint/URL a la version "
                "deployada del servicio migrado (configurable via ${CCC_<SVC>_URL} o similar)."
            ),
        ))

    return results


def run_block_21(ctx: CheckContext) -> list[CheckResult]:
    """Block 21: TX detected in adapters must match application.yml webclients."""
    src_java = ctx.migrated_path / "src" / "main" / "java"
    app_yml = ctx.migrated_path / "src" / "main" / "resources" / "application.yml"
    if not src_java.exists() or not app_yml.exists():
        return []

    yml_codes = _collect_tx_codes_from_yaml(_read_or_empty(app_yml))
    java_codes = _collect_tx_codes_from_java(src_java)
    if not yml_codes and not java_codes:
        return []

    results: list[CheckResult] = []
    missing_in_yml = sorted(java_codes - yml_codes)
    unused_in_java = sorted(yml_codes - java_codes)
    if missing_in_yml or unused_in_java:
        details: list[str] = []
        if missing_in_yml:
            details.append(f"en Java y no en application.yml: {', '.join(missing_in_yml)}")
        if unused_in_java:
            details.append(f"en application.yml y no en adapters Java: {', '.join(unused_in_java)}")
        results.append(
            CheckResult(
                "21.1",
                "Block 21",
                "TX mapping Java vs application.yml",
                "fail",
                severity="high",
                detail="; ".join(details),
                suggested_fix=(
                    "Alinear cada `transactionId(\"NNNNNN\")` / `@BancsService(\"ws-txNNNNNN\")` "
                    "con una entrada `bancs.webclients.ws-txNNNNNN` en application.yml. "
                    "No adivinar TX: usar el ANALISIS/COMPLEXITY generado desde legacy+UMP."
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                "21.1",
                "Block 21",
                "TX mapping Java vs application.yml",
                "pass",
                detail=f"TX alineados: {', '.join(sorted(yml_codes))}",
            )
        )
    return results


def run_block_22(ctx: CheckContext) -> list[CheckResult]:
    """Block 22: Discovery edge cases must be traced and covered."""
    try:
        from capamedia_cli.core.discovery import (
            detect_discovery_workspace,
            find_discovery_workbook,
            load_discovery_entry,
        )
    except ImportError:
        return []

    workspace_root = _workspace_root_for_migrated(ctx.migrated_path)
    discovery_ctx = detect_discovery_workspace(ctx.migrated_path)
    service_name = discovery_ctx.service_name
    if not service_name:
        return []

    workbook = find_discovery_workbook(workspace_root)
    if workbook is None:
        return []

    results: list[CheckResult] = []
    try:
        entry = load_discovery_entry(workbook, service_name)
    except (OSError, ValueError, RuntimeError) as exc:
        return [
            CheckResult(
                "22.0",
                "Block 22",
                "Discovery OLA legible",
                "fail",
                severity="medium",
                detail=f"no se pudo leer Discovery para {service_name}: {exc}",
                suggested_fix="Corregir el Excel Discovery canonico o pasar una copia valida con CAPAMEDIA_DISCOVERY_XLSX.",
            )
        ]

    if entry is None:
        return []

    results.append(
        CheckResult(
            "22.0",
            "Block 22",
            "Discovery OLA row",
            "pass",
            detail=f"{entry.service} desde {workbook}",
        )
    )

    report_files = _discovery_report_files(workspace_root, ctx.migrated_path)
    report_text = "\n".join(_read_or_empty(path) for path in report_files)
    if not report_text.strip():
        results.append(
            CheckResult(
                "22.1",
                "Block 22",
                "Discovery presente en analisis/reporte",
                "fail",
                severity="high",
                detail="no hay COMPLEXITY/ANALISIS/MIGRATION_REPORT con Discovery edge cases",
                suggested_fix=(
                    "Ejecutar `capamedia discovery edge-case --here --output "
                    ".capamedia/reports/discovery-edge-cases.md` o regenerar "
                    "COMPLEXITY/ANALISIS con la seccion DISCOVERY_EDGE_CASES."
                ),
            )
        )
        return results

    missing_refs: list[str] = []
    if entry.spec_path and not _token_present(report_text, entry.spec_path):
        missing_refs.append(f"spec_path={entry.spec_path}")
    if entry.code_repo and not _token_present(report_text, entry.code_repo):
        missing_refs.append(f"code_repo={entry.code_repo}")

    missing_codes = [
        case.code for case in entry.edge_cases
        if not _token_present(report_text, case.code)
    ]
    if missing_refs or missing_codes:
        detail_parts = []
        if missing_refs:
            detail_parts.append("faltan refs: " + ", ".join(missing_refs))
        if missing_codes:
            detail_parts.append("faltan edge cases: " + ", ".join(missing_codes))
        results.append(
            CheckResult(
                "22.1",
                "Block 22",
                "Discovery presente en analisis/reporte",
                "fail",
                severity="high",
                detail="; ".join(detail_parts),
                suggested_fix=(
                    "El reporte debe listar spec_path, code_repo y todos los "
                    "codigos de edge case detectados por Discovery."
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                "22.1",
                "Block 22",
                "Discovery presente en analisis/reporte",
                "pass",
                detail=f"{len(entry.edge_cases)} edge case(s) trazados en reporte",
            )
        )

    if not entry.edge_cases:
        results.append(
            CheckResult(
                "22.2",
                "Block 22",
                "Coverage de edge cases Discovery",
                "pass",
                detail="Discovery no detecto edge cases para este servicio",
            )
        )
        return results

    high_pending: list[str] = []
    medium_pending: list[str] = []
    for case in entry.edge_cases:
        status = _discovery_edge_case_status(report_text, case.code)
        if status == "covered":
            continue
        bucket = high_pending if case.code in _HIGH_DISCOVERY_EDGE_CODES else medium_pending
        bucket.append(f"{case.code} ({status})")

    if high_pending:
        results.append(
            CheckResult(
                "22.2",
                "Block 22",
                "Coverage de edge cases Discovery",
                "fail",
                severity="high",
                detail="sin decision/coverage explicita: " + ", ".join(high_pending),
                suggested_fix=(
                    "Para cada edge case HIGH, documentar en MIGRATION_REPORT.md "
                    "o DISCOVERY_EDGE_CASES.md la decision, archivo(s) tocados y "
                    "prueba asociada. No dejar PENDIENTE/TBD."
                ),
            )
        )
    elif medium_pending:
        results.append(
            CheckResult(
                "22.2",
                "Block 22",
                "Coverage de edge cases Discovery",
                "fail",
                severity="medium",
                detail="sin decision/coverage explicita: " + ", ".join(medium_pending),
                suggested_fix=(
                    "Para cada edge case de soporte, dejar trazabilidad en "
                    "MIGRATION_REPORT.md o DISCOVERY_EDGE_CASES.md con decision, "
                    "configuracion/test/handoff y estado final."
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                "22.2",
                "Block 22",
                "Coverage de edge cases Discovery",
                "pass",
                detail="todos los edge cases tienen decision/coverage sin pendientes",
            )
        )
    return results


ALL_BLOCKS = [
    ("Block 0", run_block_0),
    ("Block 1", run_block_1),
    ("Block 2", run_block_2),
    ("Block 3", run_block_3),  # v0.22.0: naming profesional
    ("Block 5", run_block_5),
    ("Block 7", run_block_7),
    ("Block 13", run_block_13),
    ("Block 14", run_block_14),
    ("Block 15", run_block_15),
    ("Block 16", run_block_16),
    ("Block 17", run_block_17),
    ("Block 18", run_block_18),
    ("Block 19", run_block_19),
    ("Block 20", run_block_20),  # v0.23.0: ORQ -> migrado, no legacy
    ("Block 21", run_block_21),  # v0.23.20: TX Java/YAML consistency
    ("Block 22", run_block_22),  # v0.23.22: Discovery edge-case coverage loop
]


def run_all_blocks(ctx: CheckContext) -> list[CheckResult]:
    """Run all blocks and return flat list of CheckResults."""
    all_results: list[CheckResult] = []
    for name, fn in ALL_BLOCKS:
        try:
            all_results.extend(fn(ctx))
        except Exception as e:
            all_results.append(CheckResult(f"{name}-error", name, f"{name} orchestration", "fail", severity="medium", detail=f"error ejecutando bloque: {e}"))
    return all_results
