"""Politica de esfuerzo del orquestador: complejidad del servicio -> recursos.

Dimension 2 del documento de arquitectura (docs/ARQUITECTURA_ORQUESTADOR.md):
el CLI ya calcula la complejidad de cada servicio (`score_complexity` en
legacy_analyzer) pero no la usaba para orquestar. Esta politica traduce
LOW/MEDIUM/HIGH al nivel de esfuerzo que el orquestador asigna por servicio.

DECISION DEL OWNER (2026-05-28): el modelo es **siempre Opus 4.8** — calidad
sobre costo. La complejidad NO modula el modelo (es opus para todos); modula
las dimensiones que sí tiene sentido escalar:
  - `reasoning_effort` (solo Codex; Claude lo ignora).
  - `extra_retries` sobre el `--retries` base (los servicios complejos fallan
    mas y merecen mas intentos).
  - `needs_human_gate`: los HIGH se senalizan para revision humana del operador
    del lote (no bloquean, avisan).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Tier de modelo fijo. Decision del owner: siempre Opus 4.8.
ALWAYS_OPUS_TIER = "opus"

# Complejidad por defecto cuando no se puede resolver (neutral: ni el minimo ni
# el maximo esfuerzo).
DEFAULT_COMPLEXITY = "medium"

VALID_COMPLEXITIES = ("low", "medium", "high")


@dataclass(frozen=True)
class EffortProfile:
    """Recursos que el orquestador asigna a un servicio segun su complejidad."""

    complexity: str
    model_tier: str          # siempre ALWAYS_OPUS_TIER (decision owner 2026-05-28)
    reasoning_effort: str    # solo aplica a Codex; Claude lo ignora
    extra_retries: int       # reintentos adicionales sobre el --retries base
    needs_human_gate: bool   # HIGH -> senalizar revision humana (no bloquea)


# Tabla de esfuerzo. model_tier = opus en las tres filas (siempre Opus).
_EFFORT_BY_COMPLEXITY: dict[str, EffortProfile] = {
    "low": EffortProfile("low", ALWAYS_OPUS_TIER, "high", 0, False),
    "medium": EffortProfile("medium", ALWAYS_OPUS_TIER, "xhigh", 1, False),
    "high": EffortProfile("high", ALWAYS_OPUS_TIER, "xhigh", 2, True),
}


def effort_for(complexity: str | None) -> EffortProfile:
    """Perfil de esfuerzo para una complejidad. Default MEDIUM si no es valida."""
    key = (complexity or "").strip().lower()
    return _EFFORT_BY_COMPLEXITY.get(key, _EFFORT_BY_COMPLEXITY[DEFAULT_COMPLEXITY])


# Linea del reporte de clone: "- **Complejidad:** `LOW`". Match en la misma
# linea para no cruzar a otras secciones.
_COMPLEXITY_LINE_RE = re.compile(
    r"complejidad[^\n]*?\b(low|medium|high)\b", re.IGNORECASE
)


def resolve_service_complexity(workspace: Path, service: str) -> str:
    """Resuelve la complejidad de un servicio de forma barata y robusta.

    Orden de resolucion:
      1. `COMPLEXITY_<service>.md` del workspace (output deterministico de
         `capamedia clone` / `batch complexity`). Es la fuente preferida.
      2. Recalculo con `analyze_legacy` sobre `<workspace>/legacy` si existe.
      3. Default MEDIUM (neutral) si no hay evidencia.

    Nunca lanza: ante cualquier error devuelve el default.
    """
    md = workspace / f"COMPLEXITY_{service}.md"
    if md.is_file():
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        match = _COMPLEXITY_LINE_RE.search(text)
        if match:
            return match.group(1).lower()

    legacy_root = workspace / "legacy"
    if legacy_root.is_dir():
        try:
            from capamedia_cli.core.legacy_analyzer import analyze_legacy

            analysis = analyze_legacy(legacy_root, service_name=service, umps_root=None)
            if analysis.complexity in VALID_COMPLEXITIES:
                return analysis.complexity
        except Exception:
            pass

    return DEFAULT_COMPLEXITY
