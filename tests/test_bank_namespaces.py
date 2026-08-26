"""Guard anti-drift de los namespaces de catalogo del banco.

Motivacion: la lista `<ns>-msa-sp-*` estaba duplicada en 4 modulos
(fabrics/qa, adopt, clone, bank_autofix) y divergio. `tmi` se agrego en v0.30.1
SOLO al prompt de `fabrics generate`, asi que un repo `tmi-msa-sp-*` quedaba
invisible para `clone --migrated` y para `adopt`: el usuario podia elegir el
namespace pero el resto del CLI no lo reconocia.

Estos tests fijan `core.ola_policy.BANK_NAMESPACES` como fuente unica.
"""

from __future__ import annotations

import re

from capamedia_cli.commands.adopt import _DESTINO_NAMESPACES, _DESTINO_PATTERNS
from capamedia_cli.commands.clone import MIGRATED_NAMESPACES
from capamedia_cli.commands.fabrics import NAMESPACE_OPTIONS
from capamedia_cli.core.ola_policy import BANK_NAMESPACES


def test_taa_is_an_available_namespace() -> None:
    """`taa` debe poder elegirse en `capamedia fabrics generate`."""
    assert "taa" in BANK_NAMESPACES
    assert "taa" in NAMESPACE_OPTIONS


def test_tca_is_an_available_namespace() -> None:
    """`tca` debe poder elegirse en `capamedia fabrics generate`."""
    assert "tca" in BANK_NAMESPACES
    assert "tca" in NAMESPACE_OPTIONS


def test_fse_is_an_available_namespace() -> None:
    """`fse` debe poder elegirse en `capamedia fabrics generate`."""
    assert "fse" in BANK_NAMESPACES
    assert "fse" in NAMESPACE_OPTIONS


def test_namespace_options_single_source() -> None:
    """Los 3 consumidores derivan de BANK_NAMESPACES, no de copias locales.

    Si este test falla es porque alguien volvio a hardcodear la lista: agregar
    el namespace en `BANK_NAMESPACES` y hacer que el modulo la importe.
    """
    assert tuple(NAMESPACE_OPTIONS) == BANK_NAMESPACES
    assert tuple(_DESTINO_NAMESPACES) == BANK_NAMESPACES
    assert tuple(MIGRATED_NAMESPACES) == BANK_NAMESPACES


def test_namespaces_are_wellformed() -> None:
    """Prefijos de 3 letras minusculas, sin duplicados."""
    assert len(set(BANK_NAMESPACES)) == len(BANK_NAMESPACES)
    for ns in BANK_NAMESPACES:
        assert re.fullmatch(r"[a-z]{3}", ns), f"namespace malformado: {ns!r}"


def test_adopt_detects_every_namespace() -> None:
    """`adopt` debe mover a destino/ un proyecto de CUALQUIER namespace vigente.

    Es el bug concreto que tuvo `tmi`: elegible en fabrics pero no adoptable.
    """
    for ns in BANK_NAMESPACES:
        candidate = f"{ns}-msa-sp-wsclientes0026"
        assert any(p.match(candidate) for p in _DESTINO_PATTERNS), (
            f"adopt no reconoce `{candidate}` como proyecto migrado"
        )
