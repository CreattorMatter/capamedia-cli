"""opencode adapter."""

from __future__ import annotations

import json
from pathlib import Path

from capamedia_cli.adapters.base import HarnessAdapter
from capamedia_cli.core.canonical import CanonicalAsset
from capamedia_cli.core.frontmatter import serialize_frontmatter

MODEL_MAP = {
    "opus": "anthropic/claude-opus-4-7",
    "sonnet": "anthropic/claude-sonnet-4-6",
    "haiku": "anthropic/claude-haiku-4-5",
}


def _resolve_model(asset: CanonicalAsset) -> str | None:
    pm = asset.preferred_model
    anthropic = pm.get("anthropic")
    if anthropic and not anthropic.startswith("anthropic/"):
        return f"anthropic/{anthropic}"
    if anthropic:
        return anthropic
    fb = asset.fallback_model
    return MODEL_MAP.get(fb)


class OpencodeAdapter(HarnessAdapter):
    name = "opencode"
    display_name = "opencode"
    supported_primitives = frozenset({"prompt", "agent", "skill", "context"})

    def render_prompt(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        out_dir = target_dir / ".opencode" / "commands"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.md"
        fm: dict[str, object] = {"description": asset.description}
        model = _resolve_model(asset)
        if model:
            fm["model"] = model
        dest.write_text(serialize_frontmatter(fm, asset.body), encoding="utf-8")
        return [dest]

    def render_agent(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        out_dir = target_dir / ".opencode" / "agents"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.md"
        fm: dict[str, object] = {
            "name": asset.name,
            "description": asset.description,
        }
        model = _resolve_model(asset)
        if model:
            fm["model"] = model
        if asset.allowed_tools:
            fm["tools"] = asset.allowed_tools
        dest.write_text(serialize_frontmatter(fm, asset.body), encoding="utf-8")
        return [dest]

    def render_skill(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        skill_dir = target_dir / ".opencode" / "skills" / asset.name
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
        dest_agents = target_dir / "AGENTS.md"
        parts = ["# Contexto del proyecto\n"]
        for a in assets:
            parts.append(f"\n## {a.title}\n\n{a.body}")

        written: list[Path] = []
        if dest_agents.exists():
            existing = dest_agents.read_text(encoding="utf-8")
            marker = "<!-- capamedia:context -->"
            if marker not in existing:
                dest_agents.write_text(
                    existing + f"\n\n{marker}\n" + "\n".join(parts), encoding="utf-8"
                )
        else:
            dest_agents.write_text(
                "<!-- capamedia:context -->\n" + "\n".join(parts), encoding="utf-8"
            )
        written.append(dest_agents)

        opencode_json = target_dir / "opencode.json"
        if not opencode_json.exists():
            opencode_json.write_text(
                json.dumps(
                    {
                        "$schema": "https://opencode.ai/config.json",
                        "model": "anthropic/claude-sonnet-4-6",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        written.append(opencode_json)

        return written
