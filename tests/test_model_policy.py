"""Tests para la fuente unica de modelos (core/model_policy.py).

Previene el drift que motivo v0.27.2: el mapeo de modelos quedaba hardcodeado
en cada adapter y se desactualizaba (ej. `claude-opus-4-7` cuando ya existia
`claude-opus-4-8`). Ahora hay una sola fuente y este guard impide que vuelvan a
aparecer IDs de modelo Claude hardcodeados fuera de `model_policy.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

from capamedia_cli.core import model_policy

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "capamedia_cli"

# Patron de ID de modelo Claude concreto: claude-<tier>-<major>-<minor>
_CLAUDE_MODEL_RE = re.compile(r"claude-(?:opus|sonnet|haiku)-\d")


def test_opus_tier_resolves_to_latest() -> None:
    """El tier `opus` debe mapear al modelo vigente (Opus 4.8 desde v0.28.0)."""
    assert model_policy.anthropic_model("opus") == "claude-opus-4-8"


def test_opencode_prefix_applied() -> None:
    assert model_policy.opencode_model("sonnet") == "anthropic/claude-sonnet-4-6"
    assert model_policy.opencode_model("opus").startswith(
        model_policy.OPENCODE_PROVIDER_PREFIX
    )


def test_unknown_tier_passes_through() -> None:
    """Un ID concreto (override del asset) se devuelve tal cual."""
    assert model_policy.anthropic_model("claude-opus-4-9") == "claude-opus-4-9"


def test_default_tier_is_sonnet() -> None:
    assert model_policy.DEFAULT_TIER == "sonnet"
    assert model_policy.default_anthropic_model() == model_policy.anthropic_model("sonnet")


def test_no_hardcoded_claude_model_ids_outside_model_policy() -> None:
    """Ningun .py de src/ debe hardcodear IDs de modelo Claude, salvo
    model_policy.py (la fuente unica) y los tests."""
    offenders: list[str] = []
    for py in SRC_ROOT.rglob("*.py"):
        if py.name == "model_policy.py":
            continue
        if "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _CLAUDE_MODEL_RE.search(line):
                rel = py.relative_to(SRC_ROOT)
                offenders.append(f"{rel}:{line_no} -> {stripped[:90]}")
    assert not offenders, (
        "IDs de modelo Claude hardcodeados fuera de model_policy.py:\n"
        + "\n".join(offenders)
    )
