"""OpenAI Codex CLI adapter."""

from __future__ import annotations

from pathlib import Path

import tomli_w

from capamedia_cli.adapters.base import HarnessAdapter, model_hint_comment
from capamedia_cli.core.canonical import CanonicalAsset
from capamedia_cli.core.frontmatter import serialize_frontmatter


class CodexAdapter(HarnessAdapter):
    name = "codex"
    display_name = "OpenAI Codex CLI"
    supported_primitives = frozenset({"prompt", "context"})

    def render_prompt(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        out_dir = target_dir / ".codex" / "prompts"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.md"
        fm = {"name": asset.name, "description": asset.description}
        hint = model_hint_comment(asset)
        body = f"{hint}\n\n{asset.body}" if hint else asset.body
        dest.write_text(serialize_frontmatter(fm, body), encoding="utf-8")
        return [dest]

    def render_agent(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        return []

    def render_skill(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        return []

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
        return written

    def render_settings(self, target_dir: Path) -> list[Path]:
        codex_dir = target_dir / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        config = codex_dir / "config.toml"
        if not config.exists():
            config.write_bytes(
                tomli_w.dumps(
                    {
                        "model": "gpt-5-codex",
                        "approval-policy": "on-failure",
                    }
                ).encode("utf-8")
            )
        return [config]
