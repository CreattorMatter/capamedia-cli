"""OpenAI Codex CLI adapter."""

from __future__ import annotations

from pathlib import Path

import tomli_w

from capamedia_cli.adapters.base import HarnessAdapter, model_hint_comment
from capamedia_cli.core.canonical import CanonicalAsset
from capamedia_cli.core.frontmatter import serialize_frontmatter

MODEL_MAP = {
    "opus": "gpt-5.3-codex",
    "sonnet": "gpt-5.1-codex",
    "haiku": "gpt-5.4-mini",
}


def _resolve_model(asset: CanonicalAsset) -> str:
    preferred = asset.preferred_model.get("openai")
    if preferred:
        return preferred
    return MODEL_MAP.get(asset.fallback_model, "gpt-5.1-codex")


def _resolve_reasoning(asset: CanonicalAsset) -> str:
    if asset.complexity == "high":
        return "high"
    if asset.complexity == "low":
        return "low"
    return "medium"


def _resolve_sandbox_mode(asset: CanonicalAsset) -> str:
    write_like_tools = {"Write", "Edit", "Task", "Agent"}
    if any(tool in write_like_tools for tool in asset.allowed_tools):
        return "workspace-write"
    return "read-only"


class CodexAdapter(HarnessAdapter):
    name = "codex"
    display_name = "OpenAI Codex CLI"
    supported_primitives = frozenset({"prompt", "agent", "skill", "context"})

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
        out_dir = target_dir / ".codex" / "agents"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.toml"
        payload = {
            "name": asset.name,
            "description": asset.description,
            "model": _resolve_model(asset),
            "model_reasoning_effort": _resolve_reasoning(asset),
            "sandbox_mode": _resolve_sandbox_mode(asset),
            "developer_instructions": asset.body.strip(),
        }
        dest.write_bytes(tomli_w.dumps(payload).encode("utf-8"))
        return [dest]

    def render_skill(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        skill_dir = target_dir / ".agents" / "skills" / asset.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        dest = skill_dir / "SKILL.md"
        dest.write_text(asset.source.read_text(encoding="utf-8"), encoding="utf-8")
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
        return written

    def render_settings(self, target_dir: Path) -> list[Path]:
        codex_dir = target_dir / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        config = codex_dir / "config.toml"
        if not config.exists():
            config.write_bytes(
                tomli_w.dumps(
                    {
                        "model": "gpt-5.1-codex",
                        "approval-policy": "on-failure",
                        "agents": {
                            "max_threads": 6,
                            "max_depth": 1,
                        },
                    }
                ).encode("utf-8")
            )
        manifest = target_dir / ".agents" / "README.md"
        if not manifest.exists():
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(
                "# Repo Skills\n\n"
                "This directory contains repo-scoped Codex skills discovered automatically by Codex.\n",
                encoding="utf-8",
            )
        return [config, manifest]
