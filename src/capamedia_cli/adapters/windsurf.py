"""Windsurf adapter."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.adapters.base import HarnessAdapter, model_hint_comment
from capamedia_cli.core.canonical import CanonicalAsset
from capamedia_cli.core.frontmatter import serialize_frontmatter


class WindsurfAdapter(HarnessAdapter):
    name = "windsurf"
    display_name = "Windsurf"
    supported_primitives = frozenset({"prompt", "agent", "context"})

    def _write_rule(
        self, asset: CanonicalAsset, target_dir: Path, trigger: str = "manual"
    ) -> list[Path]:
        out_dir = target_dir / ".windsurf" / "rules"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.md"
        override = asset.override_for("windsurf")
        fm: dict[str, object] = {
            "trigger": override.get("trigger", trigger),
            "description": asset.description,
        }
        globs = override.get("globs")
        if globs:
            fm["globs"] = globs
        hint = model_hint_comment(asset)
        body = f"{hint}\n\n{asset.body}" if hint else asset.body
        dest.write_text(serialize_frontmatter(fm, body), encoding="utf-8")
        return [dest]

    def render_prompt(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        return self._write_rule(asset, target_dir)

    def render_agent(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        return self._write_rule(asset, target_dir)

    def render_skill(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        return []

    def render_context(
        self, assets: list[CanonicalAsset], target_dir: Path
    ) -> list[Path]:
        dest = target_dir / ".windsurfrules"
        parts = ["# SpecAPI APIM context\n"]
        for a in assets:
            parts.append(f"\n## {a.title}\n\n{a.body}")
        dest.write_text("\n".join(parts), encoding="utf-8")
        return [dest]
