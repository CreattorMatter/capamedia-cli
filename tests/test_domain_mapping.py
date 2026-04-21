"""Tests para domain_mapping.py."""

from __future__ import annotations

from capamedia_cli.core.domain_mapping import (
    UNKNOWN_DOMAIN,
    domains_for_umps,
    expected_port_names,
    get_domain,
    get_ump_domain,
    umps_grouped_by_domain,
)


def test_get_domain_wsclientes() -> None:
    d = get_domain("WSClientes0007")
    assert d.pascal == "Customer"
    assert d.lower == "customer"


def test_get_domain_wsreglas() -> None:
    assert get_domain("WSReglas0010").pascal == "Rules"


def test_get_domain_wstecnicos() -> None:
    assert get_domain("WSTecnicos0036").pascal == "Technical"


def test_get_domain_orqclientes_same_as_ws() -> None:
    assert get_domain("ORQClientes0023").pascal == "Customer"


def test_get_domain_unknown_falls_back() -> None:
    assert get_domain("WSDesconocido9999") == UNKNOWN_DOMAIN


def test_get_ump_domain_clientes() -> None:
    assert get_ump_domain("UMPClientes0002").pascal == "Customer"


def test_get_ump_domain_seguridad() -> None:
    assert get_ump_domain("UMPSeguridad0001").pascal == "Security"


def test_get_ump_domain_cuentas() -> None:
    assert get_ump_domain("UMPCuentas0010").pascal == "Account"


def test_domains_for_umps_dedupes() -> None:
    domains = domains_for_umps(
        ["UMPClientes0002", "UMPClientes0020", "UMPClientes0028"]
    )
    assert len(domains) == 1
    assert domains[0].pascal == "Customer"


def test_domains_for_umps_multi_domain() -> None:
    domains = domains_for_umps(
        ["UMPClientes0002", "UMPSeguridad0001", "UMPCuentas0010"]
    )
    pascals = {d.pascal for d in domains}
    assert pascals == {"Customer", "Security", "Account"}


def test_umps_grouped_by_domain() -> None:
    grouped = umps_grouped_by_domain(
        ["UMPClientes0002", "UMPClientes0020", "UMPSeguridad0001"]
    )
    assert grouped["Customer"] == ["UMPClientes0002", "UMPClientes0020"]
    assert grouped["Security"] == ["UMPSeguridad0001"]


def test_expected_port_names_includes_pascal_domain() -> None:
    names = expected_port_names("WSClientes0007")
    assert "CustomerOutputPort" in names
    assert "CustomerBancsOutputPort" in names
