"""Version baselines used by CapaMedia migration rules."""

from __future__ import annotations

import re

# Baseline oficial aprobado para servicios OLA.
#
# Nota 2026-05: se descarto usar Spring Boot 4.x como baseline general por
# compatibilidad con los arquetipos/librerias actuales del banco. La mitigacion
# de riesgos transitivos se mantiene por reglas especificas: sin Undertow
# activo (Check 8.2) y sin pins manuales de io.netty:* (Check 8.7).
SPRING_BOOT_BASELINE_VERSION = "3.5.14"

# Excepcion oficial (v0.27.0): en proyectos WebFlux el pin
# `io.netty:*:4.1.136.Final` esta permitido porque cierra los CVEs Snyk 2026-05/07
# del netty-codec-http sin esperar al proximo BOM. Cualquier otra version
# manual sigue bloqueada por Check 8.7. MVC/SOAP: ningun pin manual permitido.
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
# Fuente unica: el canonical (migrate-rest-full.md, migrate-soap-full.md,
# checklist-rules.md) y los Checks 7.7/7.8 de checklist_rules deben citar este
# mismo valor. Coordenada gradle: `com.pichincha.common:lib-trace-logger:<version>`.
LIB_TRACE_LOGGER_COORD = "com.pichincha.common:lib-trace-logger"
LIB_TRACE_LOGGER_VERSION = "1.4.0"


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
