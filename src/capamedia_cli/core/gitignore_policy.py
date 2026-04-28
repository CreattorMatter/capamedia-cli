"""Politica de `.gitignore` para artefactos locales CapaMedia/AI.

Los repos migrados que se suben a Azure DevOps no deben arrastrar runtime
local del workspace, prompts de harnesses ni archivos de QA manual.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitignoreRequirement:
    entry: str
    aliases: tuple[str, ...] = ()


DEPLOYMENT_GITIGNORE_HEADER = "# CapaMedia/AI local artifacts - do not deploy to Azure DevOps"

DEPLOYMENT_GITIGNORE_REQUIREMENTS: tuple[GitignoreRequirement, ...] = (
    GitignoreRequirement(".capamedia/"),
    GitignoreRequirement(".codex/"),
    GitignoreRequirement(".claude/"),
    GitignoreRequirement(".cursor/"),
    GitignoreRequirement(".windsurf/"),
    GitignoreRequirement(".opencode/"),
    GitignoreRequirement(".github/prompts/"),
    GitignoreRequirement(".vscode/"),
    GitignoreRequirement(".idea/"),
    GitignoreRequirement(".mcp.json"),
    GitignoreRequirement("FABRICS_PROMPT_*.md", aliases=("FABRICS_PROMPT*.md",)),
    GitignoreRequirement("QA_STATUS.md"),
    GitignoreRequirement("TRAMAS.txt"),
)


DEPLOYMENT_GITIGNORE_ENTRIES: tuple[str, ...] = tuple(
    requirement.entry for requirement in DEPLOYMENT_GITIGNORE_REQUIREMENTS
)


def _normalize_gitignore_line(line: str) -> str:
    return line.strip().replace("\\", "/")


def _accepted_variants(requirement: GitignoreRequirement) -> set[str]:
    variants = {requirement.entry, *requirement.aliases}
    expanded: set[str] = set()
    for variant in variants:
        normalized = _normalize_gitignore_line(variant)
        expanded.add(normalized)
        if normalized.endswith("/"):
            expanded.add(normalized.rstrip("/"))
            expanded.add(f"{normalized}*")
        else:
            expanded.add(f"{normalized}/")
    return expanded


def parse_gitignore_entries(text: str) -> set[str]:
    entries: set[str] = set()
    for raw_line in text.splitlines():
        line = _normalize_gitignore_line(raw_line)
        if not line or line.startswith("#"):
            continue
        entries.add(line)
    return entries


def missing_deployment_gitignore_entries(text: str) -> list[str]:
    entries = parse_gitignore_entries(text)
    missing: list[str] = []
    for requirement in DEPLOYMENT_GITIGNORE_REQUIREMENTS:
        if not (entries & _accepted_variants(requirement)):
            missing.append(requirement.entry)
    return missing


def format_deployment_gitignore_block() -> str:
    return "\n".join((DEPLOYMENT_GITIGNORE_HEADER, *DEPLOYMENT_GITIGNORE_ENTRIES))


def ensure_deployment_gitignore(project_dir: Path) -> list[str]:
    """Append missing deployment-hygiene entries to `<project>/.gitignore`.

    Returns the entries that were added.
    """
    gitignore = project_dir / ".gitignore"
    current = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    missing = missing_deployment_gitignore_entries(current)
    if not missing:
        return []

    block = "\n".join((DEPLOYMENT_GITIGNORE_HEADER, *missing))
    prefix = current.rstrip()
    new_text = f"{prefix}\n\n{block}\n" if prefix else f"{block}\n"
    gitignore.write_text(new_text, encoding="utf-8")
    return missing
