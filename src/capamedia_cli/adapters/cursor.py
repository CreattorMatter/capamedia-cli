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
        body = f"{hint}\n\n{asset.body}" if hint else asset.body
        dest.write_text(serialize_frontmatter(fm, body), encoding="utf-8")
        return [dest]

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
        parts = []
        for a in assets:
            parts.append(f"## {a.title}\n\n{a.body}")
        dest.write_text(
            serialize_frontmatter(fm, "\n\n".join(parts)), encoding="utf-8"
        )
        return [dest]
