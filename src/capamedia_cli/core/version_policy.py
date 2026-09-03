"""Version baselines used by CapaMedia migration rules."""

from __future__ import annotations

import re

# Baseline oficial aprobado para servicios OLA.
#
# 2026-09 (correos BPTPSRE Alexis Padilla / Juan Guillermo Callapina): "todos
# los proyectos nuevos van en Spring Boot 4". El MCP Fabrics `v20260827161016`
# ya emite `4.1.1`. Historial: 3.5.14 (v0.23.33) -> 3.5.15 (v0.35.0) -> 4.1.1
# (v0.40.0).
#
# Politica de versiones (Check 8.1 + autofix fix_spring_boot_plugin_version):
#   - NUNCA bajar una version: si el MCP emite algo mayor, se conserva.
#   - Subir solo dentro de la misma linea mayor: 3.5.x < 3.5.15 -> 3.5.15;
#     4.x < 4.1.1 -> 4.1.1. El salto 3.x -> 4.x cambia artifactIds
#     (lib-trace-logger-sb4) y librerias, asi que lo decide el migrador en el
#     Block 1 del prompt (proyecto nuevo) o un PR de librerias (proyecto
#     existente), no un autofix ciego.
SPRING_BOOT_BASELINE_VERSION = "4.1.1"

# Linea SB3 todavia aceptada para proyectos EXISTENTES (WARN en Check 8.1, no
# FAIL HIGH): no se rompe lo ya construido, pero el upgrade a SB4 queda
# pendiente. Por debajo de este valor si es FAIL HIGH (scaffold viejo).
SPRING_BOOT_LEGACY_BASELINE_VERSION = "3.5.15"

# Build minimo del MCP Fabrics (`@pichincha/fabrics-project`) que emite el
# baseline SB4. Los packages del banco son `1.0.0-alpha.<timestamp>`; el
# timestamp es lo que se compara (ver `mcp_build_is_current`).
MCP_MIN_VERSION = "v20260827161016"

# Excepcion oficial (v0.27.0): en proyectos WebFlux el pin
# `io.netty:*:4.1.136.Final` esta permitido porque cierra los CVEs Snyk 2026-05/07
# del netty-codec-http sin esperar al proximo BOM. Cualquier otra version
# manual sigue bloqueada por Check 8.7. MVC/SOAP: ningun pin manual permitido.
#
# SOLO Spring Boot 3.5.x. SB4 trae Reactor Netty 1.3.x / Netty 4.2.x de fabrica:
# pinear 4.1.136.Final ahi seria un DOWNGRADE que rompe Reactor Netty. En SB4
# los Checks 8.8/8.10 no aplican y 8.7 marca cualquier pin 4.1.x como
# downgrade (`<pendiente_validar>` BPTPSRE: criterio unico Netty/Jackson 3).
#
# Historial: 4.1.133.Final (v0.27.0) -> 4.1.135.Final (Snyk 2026-06) ->
# 4.1.136.Final (Snyk 2026-07).
#
# Fuente unica: el canonical (bank-official-rules.md Regla 8.5, checklist-rules.md
# Check 8.7, migrate-rest-full.md) debe citar este mismo valor. El test
# test_version_policy_canonical_sync lo verifica para evitar el drift que causo
# v0.27.2 (codigo y canonical desincronizados).
NETTY_WEBFLUX_ALLOWED_VERSION = "4.1.136.Final"

# Plugin Gradle de peer review del banco (`architectureReview`). Es el gate que
# Azure corre en el PR: aunque el pipeline ejecuta `gradle build -x test`, el
# task `architectureReview` sigue corriendo y bloquea el merge. La version la
# fija el banco; un scaffold viejo de Fabrics puede traer una anterior.
#
# Historial: 1.1.0 (scaffold Fabrics) -> 1.1.2 (2026-07).
#
# Fuente unica igual que Netty: el canonical debe citar este mismo valor y el
# test test_version_policy_sync lo verifica.
PEER_REVIEW_PLUGIN_ID = "com.pichincha.frm-plugin-peer-review-gradle"
PEER_REVIEW_PLUGIN_VERSION = "1.1.2"

# Arbol core de Netty que debe quedar pineado a NETTY_WEBFLUX_ALLOWED_VERSION en
# proyectos WebFlux (el BOM de Spring Boot 3.5.x trae io.netty 4.1.121.Final
# vulnerable). Pinear solo `netty-codec*` deja transitivos cercanos
# (netty-handler-proxy, etc.) en version vulnerable — Snyk reporto 9 CVEs en
# WSClientes0013 (2026-05-29). Incluye `netty-transport-native-unix-common`
# porque es el modulo Java puro (platform-independent) que comparten los
# transportes nativos — NO un binario por-SO. Excluye intencionalmente los
# binarios nativos con classifier por SO (`netty-transport-native-epoll`,
# `netty-transport-native-kqueue`) y los SSL bindings opcionales
# (`netty-tcnative-*`). Se pinean con doble mecanismo: dependencyManagement
# `dependency` + resolutionStrategy `force`.
NETTY_CORE_MODULES: tuple[str, ...] = (
    "netty-common",
    "netty-buffer",
    "netty-transport",
    "netty-transport-native-unix-common",
    "netty-resolver",
    "netty-resolver-dns",
    "netty-codec",
    "netty-codec-dns",
    "netty-codec-http",
    "netty-codec-http2",
    "netty-codec-socks",
    "netty-handler",
    "netty-handler-proxy",
)


# Pins de seguridad CVE-driven para el stack WebFlux (BUS REST + ORQ), del mismo
# Snyk report 2026-06 que el arbol Netty (Check 8.8). SOLO WebFlux: reactor-netty
# y spring-kafka no existen en MVC/SOAP, y el resto se overridea junto al pin
# Netty en el mismo bloque `dependencyManagement`. Cada uno va como
# `dependency 'group:artifact:version'`.
#
# spring-framework-bom NO va aca: es un `mavenBom` import (estructura distinta),
# ver SPRING_FRAMEWORK_BOM_PIN abajo.
WEBFLUX_SECURITY_DEPENDENCY_PINS: dict[str, str] = {
    "io.micrometer:micrometer-core": "1.15.12",
    "io.projectreactor.netty:reactor-netty-http": "1.2.18",
    "org.springframework.retry:spring-retry": "2.0.13",
    "org.springframework.kafka:spring-kafka": "3.3.16",
}

# Override del Spring Framework BOM (CVE 2026-06). Va como
# `imports { mavenBom 'org.springframework:spring-framework-bom:6.2.19' }`
# dentro de `dependencyManagement`, NO como `dependency`.
SPRING_FRAMEWORK_BOM_COORD = "org.springframework:spring-framework-bom"
SPRING_FRAMEWORK_BOM_VERSION = "6.2.19"


# lib-trace-logger: observabilidad por defecto (trace-logger + payload) en TODO
# servicio OLA — orquestador Y microservicio (a diferencia del log transaccional
# lib-event-logs, que sigue siendo exclusivo de orquestadores). Referencia
# validada: orqproductos0044 rama feature/dev-BTHCCC-9015 (commit 52ea1a8).
#
# Spring Boot 4 cambia el artifactId: `lib-trace-logger` (SB3, 1.4.0) ->
# `lib-trace-logger-sb4` (SB4, 1.2.0). Mismos FQCN de los extractores y
# anotaciones (verificado en el jar), solo cambia el paquete de
# RequestInformationContextHolder. Check 8.13 exige el artifact que corresponde
# al major de Spring Boot; autofix fix_trace_logger_sb4_artifact lo reescribe.
#
# Fuente unica: el canonical (migrate-rest-full.md, migrate-soap-full.md,
# checklist-rules.md) y los Checks 7.7/7.8/8.13 de checklist_rules deben citar
# este mismo valor.
LIB_TRACE_LOGGER_COORD = "com.pichincha.common:lib-trace-logger-sb4"
LIB_TRACE_LOGGER_VERSION = "1.2.0"
LIB_TRACE_LOGGER_SB3_COORD = "com.pichincha.common:lib-trace-logger"
LIB_TRACE_LOGGER_SB3_VERSION = "1.4.0"

# lib-event-logs (log transaccional, SOLO ORQ). SB4 requiere 2.0.0; la linea
# SB3 sigue en 1.0.x. Check 8.14 exige >= 2.0.0 cuando el plugin SB es >= 4.
LIB_EVENT_LOGS_GROUP = "com.pichincha.common"
LIB_EVENT_LOGS_VERSION = "2.0.0"
LIB_EVENT_LOGS_SB3_VERSION = "1.0.0"

# Sondas Kubernetes (Spring Boot 4, correo BPTPSRE 2026-08): los probes Helm
# apuntan a los endpoints dedicados, no al agregado /actuator/health. Ambas
# formas de shell (grep -q canonica, cut del MCP) se aceptan; lo que se valida
# es el path. Requiere `management.endpoint.health.probes.enabled` via la env
# var de abajo con valor "true" en los 3 Helm.
ACTUATOR_LIVENESS_PATH = "/actuator/health/liveness"
ACTUATOR_READINESS_PATH = "/actuator/health/readiness"
ACTUATOR_PROBES_ENV_VAR = "CCC_ACTUATOR_HEALTH_PROBES_ENABLED"


def parse_numeric_version(version: str) -> tuple[int, ...]:
    """Return numeric version parts, ignoring suffixes such as -SNAPSHOT."""
    parts = re.findall(r"\d+", version)
    return tuple(int(part) for part in parts)


def is_version_lower(actual: str, expected: str) -> bool:
    """Compare dotted numeric versions with zero padding."""
    actual_parts = parse_numeric_version(actual)
    expected_parts = parse_numeric_version(expected)
    size = max(len(actual_parts), len(expected_parts))
    actual_padded = actual_parts + (0,) * (size - len(actual_parts))
    expected_padded = expected_parts + (0,) * (size - len(expected_parts))
    return actual_padded < expected_padded


def spring_boot_major(version: str | None) -> int:
    """Major numerico del plugin Spring Boot (0 si no se puede parsear)."""
    parts = parse_numeric_version(version or "")
    return parts[0] if parts else 0


def is_spring_boot_4(version: str | None) -> bool:
    """True si la version del plugin es de la linea Spring Boot 4.x o superior."""
    return spring_boot_major(version) >= 4


def spring_boot_target_version(current: str | None) -> str | None:
    """Version a la que debe SUBIR el plugin, o None si ya cumple.

    Nunca baja: `4.2.0` -> None; `3.5.16` -> None (linea SB3 aceptada).
    Sube dentro de la misma linea mayor: `3.5.14` -> `3.5.15`; `4.0.0` -> `4.1.1`.
    El salto 3.x -> 4.x no se automatiza aqui (ver SPRING_BOOT_BASELINE_VERSION).
    """
    if not current:
        return None
    if is_spring_boot_4(current):
        target = SPRING_BOOT_BASELINE_VERSION
    else:
        target = SPRING_BOOT_LEGACY_BASELINE_VERSION
    return target if is_version_lower(current, target) else None


def lib_trace_logger_coord(spring_boot_version: str | None) -> tuple[str, str]:
    """(coordenada, version) de lib-trace-logger para el major de Spring Boot.

    Sin version detectable se asume el baseline vigente (SB4).
    """
    if spring_boot_version and not is_spring_boot_4(spring_boot_version):
        return LIB_TRACE_LOGGER_SB3_COORD, LIB_TRACE_LOGGER_SB3_VERSION
    return LIB_TRACE_LOGGER_COORD, LIB_TRACE_LOGGER_VERSION


def lib_event_logs_version(spring_boot_version: str | None) -> str:
    """Version minima de lib-event-logs-* segun el major de Spring Boot."""
    if spring_boot_version and not is_spring_boot_4(spring_boot_version):
        return LIB_EVENT_LOGS_SB3_VERSION
    return LIB_EVENT_LOGS_VERSION


_MCP_BUILD_TS_RE = re.compile(r"(\d{14})")


def mcp_build_timestamp(version: str | None) -> str:
    """Timestamp `YYYYMMDDhhmmss` embebido en una version de MCP Fabrics.

    Acepta `v20260827161016` (como lo cita BPTPSRE) y
    `1.0.0-alpha.20260827161016` (npm package). Cadena vacia si no hay.
    """
    m = _MCP_BUILD_TS_RE.search(version or "")
    return m.group(1) if m else ""


def mcp_build_is_current(version: str | None) -> bool | None:
    """True si el build del MCP es >= MCP_MIN_VERSION (emite SB4).

    None si la version no trae timestamp (no se puede decidir).
    """
    ts = mcp_build_timestamp(version)
    if not ts:
        return None
    return ts >= mcp_build_timestamp(MCP_MIN_VERSION)
