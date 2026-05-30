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
# `io.netty:*:4.1.133.Final` esta permitido porque cierra los CVEs Snyk 2026-05
# del netty-codec-http sin esperar al proximo BOM. Cualquier otra version
# manual sigue bloqueada por Check 8.7. MVC/SOAP: ningun pin manual permitido.
#
# Fuente unica: el canonical (bank-official-rules.md Regla 8.5, checklist-rules.md
# Check 8.7, migrate-rest-full.md) debe citar este mismo valor. El test
# test_version_policy_canonical_sync lo verifica para evitar el drift que causo
# v0.27.2 (codigo y canonical desincronizados).
NETTY_WEBFLUX_ALLOWED_VERSION = "4.1.133.Final"

# Arbol core de Netty que debe quedar pineado a NETTY_WEBFLUX_ALLOWED_VERSION en
# proyectos WebFlux (el BOM de Spring Boot 3.5.x trae io.netty 4.1.121.Final
# vulnerable). Pinear solo `netty-codec*` deja transitivos cercanos
# (netty-handler-proxy, etc.) en version vulnerable — Snyk reporto 9 CVEs en
# WSClientes0013 (2026-05-29). Excluye intencionalmente los binarios nativos
# (`netty-transport-native-*`, se versionan por SO) y los SSL bindings opcionales
# (`netty-tcnative-*`). Se pinean con doble mecanismo: dependencyManagement
# `dependency` + resolutionStrategy `force`.
NETTY_CORE_MODULES: tuple[str, ...] = (
    "netty-common",
    "netty-buffer",
    "netty-transport",
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
