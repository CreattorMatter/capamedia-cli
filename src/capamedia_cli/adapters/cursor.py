"""Cursor adapter (MDC rules)."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.adapters.base import HarnessAdapter, model_hint_comment
from capamedia_cli.core.canonical import CanonicalAsset
from capamedia_cli.core.frontmatter import serialize_frontmatter


class CursorAdapter(HarnessAdapter):
    name = "cursor"
    display_name = "Cursor"
    supported_primitives = frozenset({"prompt", "agent", "context"})

    def _write_rule(
        self,
        asset: CanonicalAsset,
        target_dir: Path,
        always_apply: bool = False,
    ) -> list[Path]:
        out_dir = target_dir / ".cursor" / "rules"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.mdc"
        override = asset.override_for("cursor")
        fm: dict[str, object] = {
            "description": asset.description,
            "alwaysApply": bool(override.get("alwaysApply", always_apply)),
        }
        globs = override.get("globs")
        if globs:
            fm["globs"] = globs
        hint = model_hint_comment(asset)
        raw_body, parts = (
            self.prompt_body(asset, target_dir) if asset.asset_type == "prompt" else (asset.body, [])
        )
        body = f"{hint}\n\n{raw_body}" if hint else raw_body
        dest.write_text(serialize_frontmatter(fm, body), encoding="utf-8")
        return [dest, *parts]

    def render_prompt(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        return self._write_rule(asset, target_dir, always_apply=False)

    def render_agent(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        return self._write_rule(asset, target_dir, always_apply=False)

    def render_skill(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        return []

    def render_context(
        self, assets: list[CanonicalAsset], target_dir: Path
    ) -> list[Path]:
        out_dir = target_dir / ".cursor" / "rules"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / "apim-context.mdc"
        fm = {
            "description": "SpecAPI APIM project context (tribes, conventions, patterns)",
            "alwaysApply": True,
        }
        text, on_demand = self.context_text(assets, target_dir, "# Contexto del proyecto")
        dest.write_text(serialize_frontmatter(fm, text), encoding="utf-8")
        return [dest, *on_demand]
