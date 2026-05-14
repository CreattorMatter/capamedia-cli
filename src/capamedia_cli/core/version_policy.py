"""Version baselines used by CapaMedia migration rules."""

from __future__ import annotations

import re

# Baseline oficial decidido tras Snyk reports 2026-05 (Slack: kevin armas /
# Jean Pierre Garcia / Alexis Padilla):
#   - 10 CVEs HIGH activas: 3 Jackson 3.0.1 (transitiva de
#     logstash-logback-encoder 9.0), 4 Netty 4.1.132 (transitiva de WebFlux
#     3.5.14, ademas pinneada en dependencyManagement viejo), 3 Undertow.
#   - Snyk recomienda subir `spring-boot-starter-webflux` >= 4.0.0.
#   - Jean Pierre confirma "4.0.6 mejor de una vez" (mas nueva que la
#     recomendacion minima de Snyk).
# Spring Boot 4.0.6 ya trae Jackson 3.1.x y Netty mas nuevo por BOM, lo cual
# resuelve las 7 CVEs transitivas con un solo bump. Undertow se sigue
# bloqueando por Check 8.2.
SPRING_BOOT_BASELINE_VERSION = "4.0.6"


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
