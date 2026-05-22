"""Tests para core/ola_policy.py — politica OLA 2 + version de lib-bnc-api-client."""

from __future__ import annotations

from capamedia_cli.core.ola_policy import (
    LIB_BNC_API_CLIENT_OLA1,
    LIB_BNC_API_CLIENT_OLA2,
    OLA2_SERVICES,
    is_ola2,
    lib_bnc_api_client_version,
    normalize_service,
    ola_label,
)


def test_ola2_services_has_25_entrega_1() -> None:
    """La entrega 1 de OLA 2 tiene 25 servicios (5 ORQ + 20 WS)."""
    assert len(OLA2_SERVICES) == 25


def test_normalize_service_extracts_token_from_repo_name() -> None:
    assert normalize_service("tnd-msa-sp-wsclientes0042") == "wsclientes0042"
    assert normalize_service("sqb-msa-orqproductos0015") == "orqproductos0015"
    assert normalize_service("WSClientes0042") == "wsclientes0042"
    assert normalize_service("tpr-msa-sp-WSProductos0033") == "wsproductos0033"


def test_normalize_service_handles_empty_and_unknown() -> None:
    assert normalize_service("") == ""
    assert normalize_service(None) == ""
    assert normalize_service("algo-raro") == "algo-raro"


def test_is_ola2_true_for_listed_services() -> None:
    assert is_ola2("orqproductos0015") is True
    assert is_ola2("wsclientes0042") is True
    assert is_ola2("wstecnicos0082") is True
    # con prefijo de repo
    assert is_ola2("tnd-msa-sp-wsproductos0033") is True
    # case-insensitive
    assert is_ola2("WSSeguridad0028") is True


def test_is_ola2_false_for_unlisted_services() -> None:
    assert is_ola2("wsclientes0011") is False
    assert is_ola2("wstecnicos0008") is False
    assert is_ola2("orqclientes0027") is False
    assert is_ola2("") is False
    assert is_ola2(None) is False


def test_lib_bnc_api_client_version_ola2_is_2_0_0() -> None:
    assert lib_bnc_api_client_version("wsclientes0042") == "2.0.0"
    assert lib_bnc_api_client_version("tnd-msa-sp-orqproductos0061") == "2.0.0"
    assert LIB_BNC_API_CLIENT_OLA2 == "2.0.0"


def test_lib_bnc_api_client_version_ola1_is_1_1_0() -> None:
    assert lib_bnc_api_client_version("wsclientes0011") == "1.1.0"
    assert lib_bnc_api_client_version("orqclientes0027") == "1.1.0"
    assert lib_bnc_api_client_version(None) == "1.1.0"
    assert LIB_BNC_API_CLIENT_OLA1 == "1.1.0"


def test_ola_label() -> None:
    assert ola_label("wsclientes0042") == "OLA 2"
    assert ola_label("wsclientes0011") == "OLA 1"
