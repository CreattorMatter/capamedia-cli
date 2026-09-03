"""Base contract for all harness adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from capamedia_cli.core.canonical import CanonicalAsset
from capamedia_cli.core.context_budget import context_document, prompt_body_for_harness


class HarnessAdapter(ABC):
    """Abstract base class that every harness adapter must implement.

    Each adapter renders canonical assets into files that the target AI tool
    (Copilot, Claude Code, opencode, Codex, Cursor, Windsurf) understands
    natively. Adapters declare which primitives they support so the dispatcher
    can skip the rest with a warning.
    """

    name: str = ""
    display_name: str = ""
    supported_primitives: frozenset[str] = frozenset()
    # v0.41.0: presupuesto de contexto. False (default) = archivo auto-cargado
    # slim + canonicals bajo demanda + prompts grandes partidos. True = el
    # comportamiento previo (todo concatenado inline), `capamedia init
    # --inline-context`.
    inline_context: bool = False

    def supports(self, primitive: str) -> bool:
        return primitive in self.supported_primitives

    def prompt_body(self, asset: CanonicalAsset, target_dir: Path) -> tuple[str, list[Path]]:
        """Cuerpo a renderizar para un prompt (indice si es grande) y las partes escritas."""
        return prompt_body_for_harness(asset, target_dir, inline_context=self.inline_context)

    def context_text(
        self, assets: list[CanonicalAsset], target_dir: Path, heading: str
    ) -> tuple[str, list[Path]]:
        """Texto del archivo auto-cargado del harness y los canonicals bajo demanda escritos."""
        return context_document(
            assets, target_dir, heading=heading, inline_context=self.inline_context
        )

    @abstractmethod
    def render_prompt(
        self, asset: CanonicalAsset, target_dir: Path
    ) -> list[Path]: ...

    @abstractmethod
    def render_agent(
        self, asset: CanonicalAsset, target_dir: Path
    ) -> list[Path]: ...

    @abstractmethod
    def render_skill(
        self, asset: CanonicalAsset, target_dir: Path
    ) -> list[Path]: ...

    @abstractmethod
    def render_context(
        self, assets: list[CanonicalAsset], target_dir: Path
    ) -> list[Path]: ...

    def render_settings(self, target_dir: Path) -> list[Path]:
        """Optional: generate harness-specific settings file (permissions, model, etc.)."""
        return []

    def render_all(
        self,
        assets: dict[str, list[CanonicalAsset]],
        target_dir: Path,
        *,
        inline_context: bool | None = None,
    ) -> tuple[list[Path], list[str]]:
        """Dispatch: render every canonical asset through this adapter.

        `inline_context=True` reproduce el render previo a v0.41.0 (todo el
        contexto concatenado en el archivo auto-cargado, prompts sin partir).

        Returns a tuple of (written paths, warnings).
        """
        if inline_context is not None:
            self.inline_context = inline_context
        written: list[Path] = []
        warnings: list[str] = []

        for asset in assets.get("prompt", []):
            if self.supports("prompt"):
                written.extend(self.render_prompt(asset, target_dir))
            else:
                warnings.append(f"{self.display_name}: prompts not supported, skipping {asset.name}")

        for asset in assets.get("agent", []):
            if self.supports("agent"):
                written.extend(self.render_agent(asset, target_dir))
            else:
                warnings.append(f"{self.display_name}: agents not supported, skipping {asset.name}")

        for asset in assets.get("skill", []):
            if self.supports("skill"):
                written.extend(self.render_skill(asset, target_dir))
            else:
                warnings.append(f"{self.display_name}: skills not supported, skipping {asset.name}")

        if self.supports("context"):
            written.extend(self.render_context(assets.get("context", []), target_dir))

        written.extend(self.render_settings(target_dir))

        return written, warnings


def model_hint_comment(asset: CanonicalAsset) -> str:
    """Generate a comment line suggesting the preferred model.

    Used by adapters that don't support declaring a model natively
    (Copilot, Cursor, Windsurf).
    """
    pm = asset.preferred_model
    if not pm:
        return ""

    parts: list[str] = []
    if "anthropic" in pm:
        parts.append(f"Claude: {pm['anthropic']}")
    if "openai" in pm:
        parts.append(f"OpenAI: {pm['openai']}")
    if "google" in pm:
        parts.append(f"Gemini: {pm['google']}")

    if not parts:
        return ""

    joined = " | ".join(parts)
    return f"<!-- 💡 Modelo recomendado — {joined}. Seleccionalo en tu cliente antes de ejecutar. -->"
