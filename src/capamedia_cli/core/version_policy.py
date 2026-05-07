"""Version baselines used by CapaMedia migration rules."""

from __future__ import annotations

import re

SPRING_BOOT_BASELINE_VERSION = "3.5.14"


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
