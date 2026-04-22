"""OpenAI Codex CLI adapter."""

from __future__ import annotations

from pathlib import Path

import tomli_w

from capamedia_cli.adapters.base import HarnessAdapter, model_hint_comment
from capamedia_cli.core.canonical import CanonicalAsset
from capamedia_cli.core.codex_mcp import (
    ensure_capamedia_mcp_server,
    load_codex_config,
    write_codex_config,
)
from capamedia_cli.core.frontmatter import serialize_frontmatter

DEFAULT_CODEX_MODEL = "gpt-5.4"
DEFAULT_CODEX_REASONING_EFFORT = "high"


def _override(asset: CanonicalAsset) -> dict[str, object]:
    raw = asset.override_for("codex")
    return raw if isinstance(raw, dict) else {}


def _resolve_model(asset: CanonicalAsset) -> str:
    override = _override(asset)
    model = override.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return DEFAULT_CODEX_MODEL


def _resolve_reasoning(asset: CanonicalAsset) -> str:
    override = _override(asset)
    effort = override.get("model_reasoning_effort")
    if isinstance(effort, str) and effort.strip():
        return effort.strip()
    return DEFAULT_CODEX_REASONING_EFFORT


def _resolve_sandbox_mode(asset: CanonicalAsset) -> str:
    override = _override(asset)
    sandbox_mode = override.get("sandbox_mode")
    if isinstance(sandbox_mode, str) and sandbox_mode.strip():
        return sandbox_mode.strip()
    write_like_tools = {"Write", "Edit", "Task", "Agent"}
    if any(tool in write_like_tools for tool in asset.allowed_tools):
        return "workspace-write"
    return "read-only"


def _resolve_description(asset: CanonicalAsset) -> str:
    override = _override(asset)
    description = override.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return asset.description


def _merge_doc_fallbacks(raw: object) -> list[str]:
    values = list(raw) if isinstance(raw, list) else []
    required = ["CLAUDE.md", ".claude.md"]
    seen: set[str] = set()
    merged: list[str] = []
    for value in [*values, *required]:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def _build_codex_settings(target_dir: Path, existing: dict[str, object]) -> dict[str, object]:
    data = dict(existing)
    data.setdefault("model", DEFAULT_CODEX_MODEL)
    data.setdefault("model_reasoning_effort", DEFAULT_CODEX_REASONING_EFFORT)
    data.setdefault("approval_policy", "on-request")
    data.setdefault("sandbox_mode", "workspace-write")
    data["project_doc_fallback_filenames"] = _merge_doc_fallbacks(
        data.get("project_doc_fallback_filenames")
    )

    agents = dict(data.get("agents") or {})
    agents.setdefault("max_threads", 6)
    agents.setdefault("max_depth", 1)
    data["agents"] = agents

    sandbox_workspace_write = dict(data.get("sandbox_workspace_write") or {})
    sandbox_workspace_write.setdefault("network_access", True)
    data["sandbox_workspace_write"] = sandbox_workspace_write

    profiles = dict(data.get("profiles") or {})
    batch = dict(profiles.get("batch") or {})
    batch.setdefault("model", DEFAULT_CODEX_MODEL)
    batch.setdefault("model_reasoning_effort", DEFAULT_CODEX_REASONING_EFFORT)
    batch.setdefault("approval_policy", "never")
    batch.setdefault("sandbox_mode", "workspace-write")
    batch_workspace = dict(batch.get("sandbox_workspace_write") or {})
    batch_workspace.setdefault("network_access", True)
    batch["sandbox_workspace_write"] = batch_workspace
    profiles["batch"] = batch
    data["profiles"] = profiles

    ensure_capamedia_mcp_server(data, root=target_dir)
    return data


def _resolve_body(asset: CanonicalAsset) -> str:
    override = _override(asset)
    body = override.get("body")
    if isinstance(body, str) and body.strip():
        return body
    return asset.body


class CodexAdapter(HarnessAdapter):
    name = "codex"
    display_name = "OpenAI Codex CLI"
    supported_primitives = frozenset({"prompt", "agent", "skill", "context"})

    def render_prompt(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        out_dir = target_dir / ".codex" / "prompts"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.md"
        fm = {"name": asset.name, "description": _resolve_description(asset)}
        hint = model_hint_comment(asset)
        body = _resolve_body(asset)
        body = f"{hint}\n\n{body}" if hint else body
        dest.write_text(serialize_frontmatter(fm, body), encoding="utf-8")
        return [dest]

    def render_agent(self, asset: CanonicalAsset, target_dir: Path) -> list[Path]:
        out_dir = target_dir / ".codex" / "agents"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{asset.name}.toml"
        payload = {
            "name": asset.name,
            "description": _resolve_description(asset),
            "model": _resolve_model(asset),
            "model_reasoning_effort": _resolve_reasoning(asset),
            "sandbox_mode": _resolve_sandbox_mode(asset),
            "developer_instructions": _resolve_body(asset).strip(),
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
        existing = load_codex_config(config)
        write_codex_config(config, _build_codex_settings(target_dir, existing))
        rules_dir = codex_dir / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        rules = rules_dir / "default.rules"
        if not rules.exists():
            rules.write_text(
                "# Conservative rules for unattended migration workspaces.\n"
                "prefix_rule(\n"
                "    pattern = [\"git\", \"status\"],\n"
                "    decision = \"allow\",\n"
                "    justification = \"Workspace status checks are safe in automation.\",\n"
                "    match = [\"git status --short\"],\n"
                ")\n\n"
                "prefix_rule(\n"
                "    pattern = [\"git\", \"diff\"],\n"
                "    decision = \"allow\",\n"
                "    justification = \"Diff inspection is safe in automation.\",\n"
                "    match = [\"git diff --stat\"],\n"
                ")\n\n"
                "prefix_rule(\n"
                "    pattern = [\"rg\"],\n"
                "    decision = \"allow\",\n"
                "    justification = \"Fast repo search is safe in automation.\",\n"
                "    match = [\"rg build.gradle destino\"],\n"
                ")\n\n"
                "prefix_rule(\n"
                "    pattern = [\"./gradlew\"],\n"
                "    decision = \"allow\",\n"
                "    justification = \"Project-local Gradle validation is expected in migration runs.\",\n"
                "    match = [\"./gradlew clean build\"],\n"
                ")\n\n"
                "prefix_rule(\n"
                "    pattern = [\"git\", \"reset\", \"--hard\"],\n"
                "    decision = \"forbidden\",\n"
                "    justification = \"Do not discard workspace changes during migration runs.\",\n"
                "    match = [\"git reset --hard HEAD\"],\n"
                ")\n\n"
                "prefix_rule(\n"
                "    pattern = [\"git\", \"checkout\", \"--\"],\n"
                "    decision = \"forbidden\",\n"
                "    justification = \"Do not revert files to an old revision during migration runs.\",\n"
                "    match = [\"git checkout -- src/main/java/App.java\"],\n"
                ")\n\n"
                "prefix_rule(\n"
                "    pattern = [\"rm\", \"-rf\"],\n"
                "    decision = \"forbidden\",\n"
                "    justification = \"Use targeted file edits instead of recursive deletion.\",\n"
                "    match = [\"rm -rf build\"],\n"
                ")\n",
                encoding="utf-8",
            )
        manifest = target_dir / ".agents" / "README.md"
        if not manifest.exists():
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(
                "# Repo Skills\n\n"
                "This directory contains repo-scoped Codex skills discovered automatically by Codex.\n",
                encoding="utf-8",
            )
        return [config, rules, manifest]
