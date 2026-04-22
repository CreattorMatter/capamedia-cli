"""Tests para `capamedia canonical audit` (auditoria MUST/NEVER del canonical)."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.commands.canonical import (
    AuditEntry,
    _audit_file,
    _split_sections,
)


def test_split_sections_basic() -> None:
    text = """
## Intro
body 1

## Rule 1
body 2

### Rule 1.1
body 3
"""
    sections = _split_sections(text)
    assert len(sections) == 3
    assert sections[0][0] == "Intro"
    assert "body 1" in sections[0][1]


def test_audit_file_with_imperative(tmp_path: Path) -> None:
    path = tmp_path / "rules.md"
    path.write_text(
        """
## Rule 1 — Ports are interfaces
MUST use interface for ports. NEVER abstract class.

```java
public abstract class CustomerPort { // NO
```

## Rule 2 — No slf4j
NEVER import org.slf4j.

```java
import org.slf4j.Logger; // NO
```
""",
        encoding="utf-8",
    )
    entry = _audit_file(path, "rules.md")
    assert entry.total_sections == 2
    assert entry.sections_with_imperative == 2
    assert entry.sections_with_neg_example == 2
    assert entry.missing_imperative == []
    assert entry.missing_neg_example == []


def test_audit_file_detects_gaps(tmp_path: Path) -> None:
    path = tmp_path / "rules.md"
    path.write_text(
        """
## Rule 1 — Vague rule
Vague description without imperative.

## Rule 2 — With MUST
MUST be strict.
""",
        encoding="utf-8",
    )
    entry = _audit_file(path, "rules.md")
    assert entry.total_sections == 2
    assert entry.sections_with_imperative == 1
    assert len(entry.missing_imperative) == 1
    assert "Vague rule" in entry.missing_imperative[0]
    assert len(entry.missing_neg_example) == 2  # ninguna tiene ejemplo NO


def test_audit_file_ignores_non_rule_sections(tmp_path: Path) -> None:
    path = tmp_path / "prose.md"
    path.write_text(
        """
## Introduction
Just prose, no rule.

## Background
More prose.
""",
        encoding="utf-8",
    )
    entry = _audit_file(path, "prose.md")
    # Sin prefijos "rule/regla/- **", nada es regla
    assert entry.total_sections == 0


def test_audit_file_detects_bullet_rules(tmp_path: Path) -> None:
    """Secciones cuyo body arranca con bullets `- **` son reglas."""
    path = tmp_path / "bullets.md"
    path.write_text(
        """
## Configuracion
- **NEVER hardcodear secretos** en codigo
- **SIEMPRE usar ${CCC_*}** env vars
""",
        encoding="utf-8",
    )
    entry = _audit_file(path, "bullets.md")
    assert entry.total_sections == 1
    assert entry.sections_with_imperative == 1


def test_audit_entry_dataclass() -> None:
    e = AuditEntry(
        file_path="x",
        total_sections=3,
        sections_with_imperative=2,
        sections_with_neg_example=1,
        missing_imperative=["Vague"],
        missing_neg_example=["Rule X", "Rule Y"],
    )
    assert e.total_sections == 3
    assert len(e.missing_imperative) == 1
