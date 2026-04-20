"""Loader for canonical assets (prompts, agents, skills, context)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from capamedia_cli.core.frontmatter import parse_frontmatter

AssetType = Literal["prompt", "agent", "skill", "context"]

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"
CANONICAL_ROOT = DATA_ROOT / "canonical"
SCHEMA_FILE = CANONICAL_ROOT / "schema.json"


@dataclass
class CanonicalAsset:
    """A canonical asset loaded from data/canonical/."""

    source: Path
    asset_type: AssetType
    frontmatter: dict[str, Any]
    body: str
    extra_files: list[Path] = field(default_factory=list)

    @property
    def name(self) -> str:
        name = self.frontmatter.get("name")
        if not name:
            return self.source.stem.replace(".md", "")
        return str(name)

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title", self.name))

    @property
    def description(self) -> str:
        return str(self.frontmatter.get("description", ""))

    @property
    def complexity(self) -> str:
        return str(self.frontmatter.get("complexity", "medium"))

    @property
    def preferred_model(self) -> dict[str, str]:
        raw = self.frontmatter.get("preferred_model") or {}
        return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}

    @property
    def fallback_model(self) -> str:
        return str(self.frontmatter.get("fallback_model", "sonnet"))

    @property
    def allowed_tools(self) -> list[str]:
        raw = self.frontmatter.get("allowed_tools") or []
        return list(raw) if isinstance(raw, list) else []

    @property
    def harness_overrides(self) -> dict[str, dict[str, Any]]:
        raw = self.frontmatter.get("harness_overrides") or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def override_for(self, harness: str) -> dict[str, Any]:
        return self.harness_overrides.get(harness, {})


def _load_file(path: Path, asset_type: AssetType) -> CanonicalAsset:
    content = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)
    return CanonicalAsset(source=path, asset_type=asset_type, frontmatter=fm, body=body)


def _load_skill(skill_dir: Path) -> CanonicalAsset | None:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None
    asset = _load_file(skill_file, "skill")
    extras = [p for p in skill_dir.iterdir() if p.is_file() and p.name != "SKILL.md"]
    asset.extra_files = extras
    return asset


def load_canonical_assets(root: Path | None = None) -> dict[AssetType, list[CanonicalAsset]]:
    """Load all canonical assets grouped by type."""
    canonical = root or CANONICAL_ROOT
    result: dict[AssetType, list[CanonicalAsset]] = {
        "prompt": [],
        "agent": [],
        "skill": [],
        "context": [],
    }

    prompts_dir = canonical / "prompts"
    if prompts_dir.exists():
        for f in sorted(prompts_dir.glob("*.md")):
            result["prompt"].append(_load_file(f, "prompt"))

    agents_dir = canonical / "agents"
    if agents_dir.exists():
        for f in sorted(agents_dir.glob("*.md")):
            result["agent"].append(_load_file(f, "agent"))

    skills_dir = canonical / "skills"
    if skills_dir.exists():
        for sd in sorted(skills_dir.iterdir()):
            if sd.is_dir():
                skill = _load_skill(sd)
                if skill:
                    result["skill"].append(skill)

    context_dir = canonical / "context"
    if context_dir.exists():
        for f in sorted(context_dir.glob("*.md")):
            result["context"].append(_load_file(f, "context"))

    return result


def load_schema() -> dict[str, Any]:
    if not SCHEMA_FILE.exists():
        return {}
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
