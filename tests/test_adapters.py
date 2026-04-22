"""Tests for harness adapters."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.adapters import ALL_HARNESSES, get_adapter, resolve_harnesses
from capamedia_cli.core.canonical import load_canonical_assets


def test_all_6_harnesses_registered() -> None:
    assert set(ALL_HARNESSES) == {"claude", "cursor", "windsurf", "copilot", "codex", "opencode"}


def test_get_adapter_returns_instance() -> None:
    adapter = get_adapter("claude")
    assert adapter.name == "claude"


def test_get_adapter_unknown_raises() -> None:
    try:
        get_adapter("doesnotexist")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "Unknown harness" in str(e)


def test_resolve_harnesses_all() -> None:
    result = resolve_harnesses("all")
    assert set(result) == set(ALL_HARNESSES)


def test_resolve_harnesses_none() -> None:
    assert resolve_harnesses("none") == []


def test_resolve_harnesses_csv() -> None:
    result = resolve_harnesses("claude,cursor")
    assert result == ["claude", "cursor"]


def test_resolve_harnesses_dedupe() -> None:
    result = resolve_harnesses("claude,cursor,claude")
    assert result == ["claude", "cursor"]


def test_resolve_harnesses_invalid_raises() -> None:
    try:
        resolve_harnesses("claude,wat")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "wat" in str(e)


def test_claude_adapter_renders_to_tmp(tmp_path: Path) -> None:
    """Smoke test: the Claude adapter renders all canonicals without crashing."""
    assets = load_canonical_assets()
    adapter = get_adapter("claude")
    written, warnings = adapter.render_all(assets, tmp_path)
    assert len(written) > 0
    # Should create .claude/ subtree
    assert (tmp_path / ".claude").exists()
    # At least commands should be there
    commands_dir = tmp_path / ".claude" / "commands"
    if commands_dir.exists():
        assert any(commands_dir.glob("*.md"))


def test_codex_adapter_renders_agents_and_skills(tmp_path: Path) -> None:
    assets = load_canonical_assets()
    adapter = get_adapter("codex")
    written, warnings = adapter.render_all(assets, tmp_path)

    assert len(written) > 0
    assert all("not supported" not in warning for warning in warnings)
    assert (tmp_path / ".codex" / "prompts").exists()
    assert (tmp_path / ".codex" / "agents" / "migrador.toml").exists()
    assert (tmp_path / ".agents" / "skills" / "migrar" / "SKILL.md").exists()
    assert (tmp_path / ".codex" / "config.toml").exists()
