"""Fuente unica de verdad para los modelos de IA que el CLI orquesta.

Centraliza el mapeo de "tier logico" (`opus`/`sonnet`/`haiku`) al ID concreto
del modelo por proveedor. Antes esto vivia duplicado y hardcodeado en cada
adapter (`adapters/claude.py`, `adapters/opencode.py`), lo que provoco drift:
el mapeo quedo en `claude-opus-4-7` cuando ya existia `claude-opus-4-8`.

Politica de actualizacion: cuando Anthropic libera un modelo nuevo, se
actualiza UNICAMENTE este archivo. `capamedia doctor` avisa si el mapeo quedo
atras respecto del modelo activo de la sesion.

Vision de orquestador (ver docs/ARQUITECTURA_ORQUESTADOR.md): el tier logico
expresa el ROL, no el modelo. `opus` = rol que necesita razonamiento profundo y
contexto grande (analista de legacy, migrador de servicios HIGH); `sonnet` = el
grueso del trabajo (migracion tipica, doublecheck); `haiku` = workers baratos y
paralelos (revisores por dimension, documentador).
"""

from __future__ import annotations

# Lineup Anthropic vigente. Unico lugar donde se actualizan los IDs de modelo.
ANTHROPIC_MODELS: dict[str, str] = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
}

# Default cuando un asset no declara tier (`fallback_model`). El grueso del
# trabajo de migracion corre en sonnet por relacion costo/capacidad.
DEFAULT_TIER = "sonnet"

# Prefijo que usa opencode para enrutar a Anthropic.
OPENCODE_PROVIDER_PREFIX = "anthropic/"


def anthropic_model(tier: str) -> str:
    """Devuelve el ID concreto del modelo Anthropic para un tier logico.

    Si `tier` ya es un ID concreto (no esta en el mapa), se devuelve tal cual
    para permitir overrides explicitos desde el frontmatter del asset.
    """
    return ANTHROPIC_MODELS.get(tier, tier)


def opencode_model(tier: str) -> str:
    """Igual que `anthropic_model` pero con el prefijo de proveedor de opencode."""
    model = anthropic_model(tier)
    if model.startswith(OPENCODE_PROVIDER_PREFIX):
        return model
    return f"{OPENCODE_PROVIDER_PREFIX}{model}"


def default_anthropic_model() -> str:
    """Modelo Anthropic del tier default."""
    return anthropic_model(DEFAULT_TIER)


def default_opencode_model() -> str:
    """Modelo opencode del tier default."""
    return opencode_model(DEFAULT_TIER)
