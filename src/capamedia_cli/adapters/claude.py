"""Claude Code adapter (Anthropic's CLI)."""

from __future__ import annotations

import json
from pathlib import Path

from capamedia_cli.adapters.base import HarnessAdapter
from capamedia_cli.core.canonical import CanonicalAsset
from capamedia_cli.core.frontmatter import serialize_frontmatter


MODEL_MAP = {
    "opus": "claude-opus-4-7",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
}


def _resolve_model(asset: CanonicalAsset) -> str | None:
    pm = asset.preferred_model
    anthropic = pm.get("anthropic")
    if anthropic:
        return str(anthropic)
    fb = asset.fallback_model
    return MODEL_MAP.get(fb, fb) if fb else None


class ClaudeCodeAdapter(HarnessAdapter):
    name = "claude"
    display_name = "Claude Code"
    supported_primitives = frozenset({"prompt", "agent", "skill", "context"})

    def render_prompt(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        out_dir = target_dir / ".claude" / "commands"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.md"
        fm: dict[str, object] = {"description": asset.description}
        if asset.allowed_tools:
            fm["allowed-tools"] = ", ".join(asset.allowed_tools)
        model = _resolve_model(asset)
        if model:
            fm["model"] = model
        dest.write_text(serialize_frontmatter(fm, asset.body), encoding="utf-8")
        return [dest]

    def render_agent(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        out_dir = target_dir / ".claude" / "agents"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.md"
        fm: dict[str, object] = {
            "name": asset.name,
            "description": asset.description,
        }
        if asset.allowed_tools:
            fm["tools"] = asset.allowed_tools
        model = _resolve_model(asset)
        if model:
            fm["model"] = model
        dest.write_text(serialize_frontmatter(fm, asset.body), encoding="utf-8")
        return [dest]

    def render_skill(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        skill_dir = target_dir / ".claude" / "skills" / asset.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        dest = skill_dir / "SKILL.md"
        fm = {"name": asset.name, "description": asset.description}
        dest.write_text(serialize_frontmatter(fm, asset.body), encoding="utf-8")
        written = [dest]
        for extra in asset.extra_files:
            target = skill_dir / extra.relative_to(asset.source.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(extra.read_bytes())
            written.append(target)
        return written

    def render_context(
        self, assets: list[CanonicalAsset], target_dir: Path
    ) -> list[Path]:
        dest = target_dir / "CLAUDE.md"
        parts = ["# Contexto del proyecto\n"]
        for a in assets:
            parts.append(f"\n## {a.title}\n\n{a.body}")
        dest.write_text("\n".join(parts), encoding="utf-8")
        return [dest]

    def render_settings(self, target_dir: Path) -> list[Path]:
        settings_dir = target_dir / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        dest = settings_dir / "settings.json"
        settings = {
            "permissions": {
                "allow": [
                    "Bash(uv run capamedia:*)",
                    "Bash(capamedia:*)",
                    "Bash(az apim:*)",
                    "Bash(az account:*)",
                    "Bash(git status)",
                    "Bash(git diff:*)",
                    "Bash(git log:*)",
                ],
            },
        }
        dest.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return [dest]
