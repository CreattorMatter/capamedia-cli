"""Checklist BPTPSRE - implementacion determinista (sin AI) de los 15 bloques.

Cada bloque es una funcion que recibe contexto y retorna una lista de CheckResult.
El comando `capamedia check` orquesta todas las funciones y produce el reporte.

Los bloques son espejo de `prompts/post-migracion/03-checklist.md` del repo original.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

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


def _read_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


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

    # Dialogo conversacional - cruce con framework
    expected_fw = "rest" if ops_migrated == 1 else "soap"
    actual_fw = ctx.project_type
    ops_ref = ops_legacy if ops_legacy > 0 else ops_migrated
    if expected_fw == actual_fw:
        dialogo = f"Son {ops_ref} op(s), va {actual_fw.upper()}. Esta OK? Si, esta OK."
        results.append(CheckResult("0.2c", "Block 0", "Framework vs operaciones", "pass", detail=dialogo))
    else:
        if ops_migrated == 1 and actual_fw == "soap" and ctx.has_database:
            results.append(CheckResult("0.2c", "Block 0", "Framework vs operaciones", "pass", detail="1 op + BD => SOAP MVC (excepcion JPA)"))
        else:
            dialogo = f"Son {ops_ref} op(s) => deberia ir {expected_fw.upper()}. Se migro como {actual_fw.upper()} => MAL-CLASIFICADO"
            results.append(CheckResult("0.2c", "Block 0", "Framework vs operaciones", "fail", severity="high", detail=dialogo, suggested_fix="Reclasificar el proyecto al framework correcto"))

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
        for f in app_dir.rglob("port/**/*.java"):
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

    # 1.4 - UN output port POR DOMINIO de UMP invocado
    # Regla actualizada (v0.3.2): el numero de output ports debe coincidir con la
    # cantidad de dominios distintos de UMPs invocados por el servicio. Cada UMP
    # de un mismo dominio se consolida en 1 solo port/adapter del dominio.

    # Listar todos los *OutputPort en application/**/port/output/
    actual_ports: list[str] = []
    for f in src_java.rglob("application/**/port/output/*OutputPort.java"):
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

    # 15.1 - mensajeNegocio NUNCA debe ser seteado desde el codigo
    bad = _grep_files(src_java, r"setMensajeNegocio\s*\(\s*[\"']")
    if bad:
        results.append(
            CheckResult(
                "15.1",
                "Block 15",
                "mensajeNegocio NO debe setearse desde el codigo",
                "fail",
                severity="high",
                detail=f"{len(bad)} hit(s): el PDF oficial dice que mensajeNegocio lo setea DataPower",
                suggested_fix="Dejar mensajeNegocio = null o no llamar al setter en el mapper",
            )
        )
    else:
        results.append(
            CheckResult("15.1", "Block 15", "mensajeNegocio NO se setea desde el codigo", "pass")
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
        return results
    results.append(CheckResult("14.1", "Block 14", ".sonarlint/connectedMode.json presente", "pass"))

    # 14.2 - org correcto
    try:
        data = json.loads(_read_or_empty(binding))
    except json.JSONDecodeError:
        results.append(CheckResult("14.2", "Block 14", "connectedMode.json valido", "fail", severity="high", detail="JSON invalido"))
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

    return results


# -- Main orchestrator -----------------------------------------------------


ALL_BLOCKS = [
    ("Block 0", run_block_0),
    ("Block 1", run_block_1),
    ("Block 2", run_block_2),
    ("Block 5", run_block_5),
    ("Block 7", run_block_7),
    ("Block 13", run_block_13),
    ("Block 14", run_block_14),
    ("Block 15", run_block_15),
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
