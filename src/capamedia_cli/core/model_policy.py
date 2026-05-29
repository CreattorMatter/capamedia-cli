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

# Lineup Codex (OpenAI) por tier logico. Centralizado aca (antes vivia en
# adapters/codex.py) para tener UN solo lugar donde se mapea tier -> modelo,
# sin importar el engine. `gpt-5.5` para el trabajo pesado, `gpt-5.4-mini`
# para el fast-path (equivalente al tier haiku).
CODEX_MODELS: dict[str, str] = {
    "opus": "gpt-5.5",
    "sonnet": "gpt-5.5",
    "haiku": "gpt-5.4-mini",
}

# Reasoning effort default de Codex. Claude lo ignora.
DEFAULT_CODEX_REASONING_EFFORT = "xhigh"

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


def codex_model(tier: str) -> str:
    """Devuelve el ID concreto del modelo Codex para un tier logico.

    Si `tier` ya es un ID concreto (no esta en el mapa), se devuelve tal cual.
    """
    return CODEX_MODELS.get(tier, tier)


def engine_model(tier: str, engine_name: str) -> str:
    """Traduce un tier logico al modelo concreto del engine activo.

    El orquestador razona en tiers (rol); cada engine lo materializa en su
    propio lineup. `claude`/`auto` -> Anthropic; `codex` -> OpenAI.
    """
    if engine_name == "codex":
        return codex_model(tier)
    return anthropic_model(tier)


def default_anthropic_model() -> str:
    """Modelo Anthropic del tier default."""
    return anthropic_model(DEFAULT_TIER)


def default_opencode_model() -> str:
    """Modelo opencode del tier default."""
    return opencode_model(DEFAULT_TIER)


def default_codex_model() -> str:
    """Modelo Codex del tier default."""
    return codex_model(DEFAULT_TIER)
