"""Tests for the canonical asset loader."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.canonical import CANONICAL_ROOT, load_canonical_assets
from capamedia_cli.core.frontmatter import parse_frontmatter, serialize_frontmatter


def test_load_canonical_assets_returns_all_types() -> None:
    assets = load_canonical_assets()
    assert "prompt" in assets
    assert "agent" in assets
    assert "skill" in assets
    assert "context" in assets


def test_slash_commands_are_loaded() -> None:
    """The 4 main slash commands must be present."""
    assets = load_canonical_assets()
    names = {a.name for a in assets["prompt"]}
    assert "clone" in names
    assert "fabric" in names
    assert "migrate" in names
    assert "check" in names


def test_full_prompts_are_loaded() -> None:
    """The 5 detailed prompts ported from PromptCapaMedia must be present."""
    assets = load_canonical_assets()
    names = {a.name for a in assets["prompt"]}
    assert "analisis-servicio" in names
    assert "analisis-orq" in names
    assert "migrate-rest-full" in names
    assert "migrate-soap-full" in names
    assert "checklist-rules" in names


def test_agents_are_loaded() -> None:
    assets = load_canonical_assets()
    names = {a.name for a in assets["agent"]}
    assert "analista-legacy" in names
    assert "migrador" in names
    assert "qa-generator" in names
    assert "validador-hex" in names


def test_skills_are_loaded() -> None:
    assets = load_canonical_assets()
    names = {a.name for a in assets["skill"]}
    assert "pre-migracion" in names
    assert "migrar" in names
    assert "post-migracion" in names


def test_context_are_loaded() -> None:
    assets = load_canonical_assets()
    names = {a.name for a in assets["context"]}
    assert "hexagonal" in names
    assert "bancs" in names
    assert "security" in names
    assert "code-style" in names
    assert "sonarlint" in names


def test_frontmatter_roundtrip() -> None:
    fm = {"name": "test", "description": "hello", "allowed_tools": ["Read", "Write"]}
    body = "# Title\n\nBody content.\n"
    serialized = serialize_frontmatter(fm, body)
    parsed_fm, parsed_body = parse_frontmatter(serialized)
    assert parsed_fm["name"] == "test"
    assert parsed_fm["description"] == "hello"
    assert parsed_fm["allowed_tools"] == ["Read", "Write"]
    assert parsed_body == body


def test_frontmatter_missing_returns_empty_dict() -> None:
    content = "# Just a title\n\nNo frontmatter here.\n"
    fm, body = parse_frontmatter(content)
    assert fm == {}
    assert body == content


def test_canonical_migration_assets_align_ports_with_interfaces() -> None:
    targets = [
        CANONICAL_ROOT / "prompts" / "migrate.md",
        CANONICAL_ROOT / "context" / "hexagonal.md",
        CANONICAL_ROOT / "agents" / "migrador.md",
        CANONICAL_ROOT / "skills" / "migrar" / "SKILL.md",
    ]

    forbidden = [
        "Puertos son abstract classes, nunca interfaces.",
        "Ports son ABSTRACT CLASSES, nunca interfaces",
        "Crear abstract class ports + service impl",
    ]

    for path in targets:
        content = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in content, f"{Path(path).name} still contains outdated rule: {phrase}"


def test_canonical_batch_prompts_are_not_claude_only_or_gold_ref_driven() -> None:
    migrate = (CANONICAL_ROOT / "prompts" / "migrate.md").read_text(encoding="utf-8")
    fabric = (CANONICAL_ROOT / "prompts" / "fabric.md").read_text(encoding="utf-8")
    clone = (CANONICAL_ROOT / "prompts" / "clone.md").read_text(encoding="utf-8")

    assert ".claude/agents/migrador.md" not in migrate
    assert "gold-ref/" not in migrate
    assert "cp -r .codex destino" in fabric
    assert "Artefactos del harness" in fabric
    assert "mkdir -p gold-ref" not in clone
