"""Tests for harness adapters."""

from __future__ import annotations

import tomllib
from pathlib import Path

from capamedia_cli.adapters import ALL_HARNESSES, get_adapter, resolve_harnesses
from capamedia_cli.core.canonical import load_canonical_assets

FORBIDDEN_RENDERED_ARCHETYPE_PHRASES = [
    "SOAP controllers sobre WebFlux",
    "Ports son ABSTRACT CLASSES",
    "Ports son abstract classes",
    "WSDL de 1 op al stack REST+WebFlux",
    "1 op va a REST/WebFlux",
    "cualquier WAS con DB",
    "spring-boot-starter-webflux faltante en scaffold SOAP",
    "debio ir REST+WebFlux",
    "debi\u00f3 ir REST+WebFlux",
]


def _read_rendered_text(paths: list[Path]) -> str:
    chunks: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
    return "\n".join(chunks)


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
    written, _warnings = adapter.render_all(assets, tmp_path)
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


def test_codex_adapter_defaults_to_gpt_55_xhigh(tmp_path: Path) -> None:
    assets = load_canonical_assets()
    adapter = get_adapter("codex")
    adapter.render_all(assets, tmp_path)

    config = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert config["model"] == "gpt-5.5"
    assert config["model_reasoning_effort"] == "xhigh"

    migrador = tomllib.loads(
        (tmp_path / ".codex" / "agents" / "migrador.toml").read_text(encoding="utf-8")
    )
    assert migrador["model"] == "gpt-5.5"
    assert migrador["model_reasoning_effort"] == "xhigh"


def test_codex_adapter_medium_assets_use_high_reasoning(tmp_path: Path) -> None:
    assets = load_canonical_assets()
    adapter = get_adapter("codex")
    adapter.render_all(assets, tmp_path)

    analista = tomllib.loads(
        (tmp_path / ".codex" / "agents" / "analista-legacy.toml").read_text(encoding="utf-8")
    )
    assert analista["model"] == "gpt-5.5"
    assert analista["model_reasoning_effort"] == "high"


def test_rendered_harness_outputs_preserve_bptpsre_matrix_guards(tmp_path: Path) -> None:
    """Render all harnesses and ensure no adapter reintroduces archetype drift."""
    assets = load_canonical_assets()
    offenders: list[str] = []

    for harness in ALL_HARNESSES:
        target = tmp_path / harness
        written, _warnings = get_adapter(harness).render_all(assets, target)
        rendered_text = _read_rendered_text(written)

        assert "bank-mcp-matrix.md" in rendered_text, harness
        assert "REST + Spring MVC" in rendered_text, harness
        assert "SOAP + Spring MVC" in rendered_text, harness

        for phrase in FORBIDDEN_RENDERED_ARCHETYPE_PHRASES:
            if phrase in rendered_text:
                offenders.append(f"{harness}: {phrase}")

    assert not offenders, "Rendered harness drift:\n  " + "\n  ".join(offenders)
