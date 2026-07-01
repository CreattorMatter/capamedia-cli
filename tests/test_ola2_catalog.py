"""Tests del loader del catalogo de Discovery Ola 2 (core/ola2_catalog.py)."""

from __future__ import annotations

from capamedia_cli.core import ola2_catalog as cat


def test_catalog_loads_meta() -> None:
    c = cat.load_catalog()
    assert c["meta"]["ola"] == 2
    assert len(c["services"]) >= 25
    assert c["meta"]["n_relations"] >= 30


def test_orchestrators_listed() -> None:
    orq = cat.list_orchestrators()
    for expected in ("ORQProductos0015", "ORQProductos0019", "ORQProductos0061"):
        assert expected in orq
    assert cat.is_orchestrator("ORQProductos0019")
    assert not cat.is_orchestrator("WSProductos0033")


def test_get_service_canonicalizes_case() -> None:
    s = cat.get_service("orqproductos0015")  # lowercase a proposito
    assert s is not None
    assert s["name"] == "ORQProductos0015"
    assert s["complexity"] == "Alta"
    assert s["legacy_type"] == "ORQ"


def test_downstreams_with_flags() -> None:
    ds = cat.get_downstreams("ORQProductos0015")
    names = {d["service"] for d in ds}
    assert {"WSReglas0010", "WSTecnicos0027", "WSProductos0033", "WSTecnicos0082"} <= names
    d033 = next(d for d in ds if d["service"] == "WSProductos0033")
    assert d033["in_discovery"] is True
    reglas = next(d for d in ds if d["service"] == "WSReglas0010")
    assert reglas["in_ola1"] is True  # WSReglas0010 ya migrado en Ola 1


def test_discovery_ficha_and_regex_codes() -> None:
    f = cat.get_discovery("ORQProductos0015")
    assert f is not None
    assert f["acronimo"].lower() == "tmp"
    assert "integraciones_raw" in f
    # codigos WS*/ORQ* extraidos del texto libre (cross-check con la tabla de relaciones)
    assert "WSReglas0010" in f["integraciones_codes"]
    assert "WSProductos0033" in f["integraciones_codes"]


def test_unknown_service_is_safe() -> None:
    assert cat.get_service("WSNoExiste9999") is None
    assert not cat.is_known("WSNoExiste9999")
    assert cat.get_downstreams("WSNoExiste9999") == []
    assert cat.get_discovery("WSNoExiste9999") is None


# -- P0: endurecimiento de la clave de identidad -----------------------------


def test_resolve_migrated_name_form() -> None:
    """El nombre migrado (tpr-msa-sp-...) resuelve al mismo servicio (bug del prefijo)."""
    assert cat.is_orchestrator("tpr-msa-sp-orqproductos0019")
    assert cat.is_known("tnd-msa-sp-wsclientes0043")
    s = cat.get_service("tpr-msa-sp-orqproductos0019")
    assert s is not None and s["name"] == "ORQProductos0019"


def test_resolve_case_insensitive_no_mangling() -> None:
    """Lookup por minusculas contra los keys reales: robusto al case sin reconstruir
    el nombre (no rompe camelCase interno tipo WSCuentaCorriente en futuros relevamientos)."""
    assert cat.get_service("ORQPRODUCTOS0019")["name"] == "ORQProductos0019"
    assert cat.get_service("orqproductos0019")["name"] == "ORQProductos0019"


def test_known_distinguishes_absent_from_empty_downstreams() -> None:
    """is_known separa 'ausente del catalogo' de 'servicio sin downstreams'."""
    assert not cat.is_known("ORQProductos9999")  # ausente del catalogo
    assert cat.get_downstreams("ORQProductos9999") == []
    # WS conocido no-orquestador: downstreams vacio pero is_known True
    assert cat.is_known("WSProductos0033")
    assert not cat.is_orchestrator("WSProductos0033")
    assert cat.get_downstreams("WSProductos0033") == []
