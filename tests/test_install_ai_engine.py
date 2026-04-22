"""Tests para el comportamiento de `capamedia install` con alternativas AI.

Regla: el package 'AI engine CLI' debe estar OK si cualquiera de Codex CLI
o Claude Code CLI esta presente. Esto evita instalar Codex cuando el
usuario ya tiene Claude Code.
"""

from __future__ import annotations

from unittest.mock import patch

from capamedia_cli.commands.install import PACKAGES, Package


def _ai_engine_package() -> Package:
    return next(p for p in PACKAGES if "AI engine" in p.name)


def test_ai_engine_package_configured_with_claude_alternative() -> None:
    pkg = _ai_engine_package()
    # Primario sigue siendo codex (auto-install via npm)
    assert pkg.check_command[0] == "codex"
    # Alternativa: claude
    alt_names = [name for name, _cmd in pkg.alternative_checks]
    assert "Claude Code CLI" in alt_names


def test_ai_engine_ok_when_only_claude_present() -> None:
    """Con claude --version OK y codex ausente, el requisito esta cumplido."""
    pkg = _ai_engine_package()

    def fake_which(exe: str) -> str | None:
        if exe == "claude":
            return "/usr/bin/claude"
        return None

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    with (
        patch("capamedia_cli.commands.install.shutil.which", side_effect=fake_which),
        patch("capamedia_cli.commands.install.subprocess.run", return_value=_Proc()),
    ):
        assert pkg.is_installed() is True
        assert pkg.detected_alternative() == "Claude Code CLI"


def test_ai_engine_ok_when_only_codex_present() -> None:
    """Con codex primario presente, no se mira la alternativa."""
    pkg = _ai_engine_package()

    def fake_which(exe: str) -> str | None:
        if exe == "codex":
            return "/usr/bin/codex"
        return None

    class _Proc:
        returncode = 0

    with (
        patch("capamedia_cli.commands.install.shutil.which", side_effect=fake_which),
        patch("capamedia_cli.commands.install.subprocess.run", return_value=_Proc()),
    ):
        assert pkg.is_installed() is True
        # Primario OK -> sin "alternativa detectada"
        assert pkg.detected_alternative() is None


def test_ai_engine_fails_when_neither_present() -> None:
    pkg = _ai_engine_package()

    with patch("capamedia_cli.commands.install.shutil.which", return_value=None):
        assert pkg.is_installed() is False
        assert pkg.detected_alternative() is None


def test_ai_engine_prefers_primary_when_both_present() -> None:
    """Si ambos estan, el primario (codex) gana — no se reporta alternativa."""
    pkg = _ai_engine_package()

    def fake_which(exe: str) -> str | None:
        return f"/usr/bin/{exe}"

    class _Proc:
        returncode = 0

    with (
        patch("capamedia_cli.commands.install.shutil.which", side_effect=fake_which),
        patch("capamedia_cli.commands.install.subprocess.run", return_value=_Proc()),
    ):
        assert pkg.is_installed() is True
        # Primario OK -> None
        assert pkg.detected_alternative() is None
