"""GitHub Copilot adapter."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.adapters.base import HarnessAdapter, model_hint_comment
from capamedia_cli.core.canonical import CanonicalAsset
from capamedia_cli.core.frontmatter import serialize_frontmatter


class CopilotAdapter(HarnessAdapter):
    name = "copilot"
    display_name = "GitHub Copilot"
    supported_primitives = frozenset({"prompt", "agent", "context"})

    def render_prompt(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        out_dir = target_dir / ".github" / "prompts"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.prompt.md"
        fm = {
            "mode": "agent",
            "description": asset.description,
        }
        hint = model_hint_comment(asset)
        raw_body, parts = self.prompt_body(asset, target_dir)
        body = f"{hint}\n\n{raw_body}" if hint else raw_body
        dest.write_text(serialize_frontmatter(fm, body), encoding="utf-8")
        return [dest, *parts]

    def render_agent(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        out_dir = target_dir / ".github" / "agents"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.agent.md"
        fm = {"name": asset.name, "description": asset.description}
        hint = model_hint_comment(asset)
        body = f"{hint}\n\n{asset.body}" if hint else asset.body
        dest.write_text(serialize_frontmatter(fm, body), encoding="utf-8")
        return [dest]

    def render_skill(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        return []

    def render_context(
        self, assets: list[CanonicalAsset], target_dir: Path
    ) -> list[Path]:
        out_dir = target_dir / ".github"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / "copilot-instructions.md"
        text, on_demand = self.context_text(assets, target_dir, "# Copilot instructions")
        dest.write_text(text, encoding="utf-8")
        return [dest, *on_demand]
