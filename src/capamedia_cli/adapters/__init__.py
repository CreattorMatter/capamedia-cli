"""Registry of harness adapters."""

from __future__ import annotations

from capamedia_cli.adapters.base import HarnessAdapter
from capamedia_cli.adapters.claude import ClaudeCodeAdapter
from capamedia_cli.adapters.codex import CodexAdapter
from capamedia_cli.adapters.copilot import CopilotAdapter
from capamedia_cli.adapters.cursor import CursorAdapter
from capamedia_cli.adapters.opencode import OpencodeAdapter
from capamedia_cli.adapters.windsurf import WindsurfAdapter

ADAPTERS: dict[str, type[HarnessAdapter]] = {
    "copilot": CopilotAdapter,
    "claude": ClaudeCodeAdapter,
    "opencode": OpencodeAdapter,
    "codex": CodexAdapter,
    "cursor": CursorAdapter,
    "windsurf": WindsurfAdapter,
}

ALL_HARNESSES = tuple(ADAPTERS.keys())


def get_adapter(name: str) -> HarnessAdapter:
    """Instantiate an adapter by name."""
    if name not in ADAPTERS:
        valid = ", ".join(ALL_HARNESSES)
        raise ValueError(f"Unknown harness '{name}'. Valid: {valid}, all, none")
    return ADAPTERS[name]()


def resolve_harnesses(value: str | None) -> list[str]:
    """Resolve the --ai flag value into a list of harness names.

    Accepts: None (→ all), 'all', 'none', a single name, or a CSV.
    """
    if value is None or value == "all":
        return list(ALL_HARNESSES)
    if value == "none":
        return []

    names = [n.strip().lower() for n in value.split(",") if n.strip()]
    invalid = [n for n in names if n not in ADAPTERS]
    if invalid:
        valid = ", ".join(ALL_HARNESSES)
        raise ValueError(
            f"Unknown harness(es): {', '.join(invalid)}. Valid: {valid}, all, none"
        )
    # Preserve order but deduplicate
    seen: set[str] = set()
    result: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result


__all__ = [
    "ADAPTERS",
    "ALL_HARNESSES",
    "HarnessAdapter",
    "get_adapter",
    "resolve_harnesses",
]
