"""YAML frontmatter parser and serializer for canonical markdown files."""

from __future__ import annotations

from typing import Any

import yaml

DELIMITER = "---"


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split a markdown file into (frontmatter_dict, body).

    Returns ({}, content) if no frontmatter is present.
    """
    if not content.startswith(DELIMITER):
        return {}, content

    parts = content.split(DELIMITER, 2)
    if len(parts) < 3:
        return {}, content

    raw_fm = parts[1].strip()
    body = parts[2].lstrip("\n")

    data = yaml.safe_load(raw_fm) or {}
    if not isinstance(data, dict):
        return {}, content

    return data, body


def serialize_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize a dict + body back into a markdown file with YAML frontmatter."""
    if not frontmatter:
        return body

    fm_yaml = yaml.dump(
        frontmatter,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).rstrip()

    return f"{DELIMITER}\n{fm_yaml}\n{DELIMITER}\n\n{body}"
