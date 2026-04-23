"""Tests para normalize_service_name (v0.20.1): auto-padding a 4 digitos."""

from __future__ import annotations

from capamedia_cli.commands.clone import normalize_service_name


def test_pads_two_digit_suffix() -> None:
    """wsclientes76 -> wsclientes0076 (caso del bug reportado por Julian)."""
    norm, was_padded = normalize_service_name("wsclientes76")
    assert norm == "wsclientes0076"
    assert was_padded is True


def test_pads_single_digit_suffix() -> None:
    norm, was_padded = normalize_service_name("wstecnicos8")
    assert norm == "wstecnicos0008"
    assert was_padded is True


def test_pads_three_digit_suffix() -> None:
    norm, was_padded = normalize_service_name("orq123")
    assert norm == "orq0123"
    assert was_padded is True


def test_does_not_pad_four_digits() -> None:
    """Ya tiene 4 digitos, no tocar."""
    norm, was_padded = normalize_service_name("wsclientes0076")
    assert norm == "wsclientes0076"
    assert was_padded is False


def test_preserves_five_or_more_digits() -> None:
    """Caso improbable pero no se rompe: >4 digitos se respetan."""
    norm, was_padded = normalize_service_name("wstecnicos12345")
    assert norm == "wstecnicos12345"
    assert was_padded is False


def test_lowercases_input() -> None:
    """WsClientes76 -> wsclientes0076 (case-insensitive)."""
    norm, was_padded = normalize_service_name("WsClientes76")
    assert norm == "wsclientes0076"
    assert was_padded is True


def test_strips_whitespace() -> None:
    norm, was_padded = normalize_service_name("  wsclientes76  ")
    assert norm == "wsclientes0076"
    assert was_padded is True


def test_name_without_trailing_digits_unchanged() -> None:
    """Nombre que no termina en digitos se retorna igual."""
    norm, was_padded = normalize_service_name("foo")
    assert norm == "foo"
    assert was_padded is False


def test_ump_name_also_padded() -> None:
    """UMPs siguen la misma convencion: umptecnicos23 -> umptecnicos0023."""
    norm, was_padded = normalize_service_name("umptecnicos23")
    assert norm == "umptecnicos0023"
    assert was_padded is True


def test_empty_string_is_safe() -> None:
    norm, was_padded = normalize_service_name("")
    assert norm == ""
    assert was_padded is False


def test_only_digits_not_padded() -> None:
    """Edge case: solo digitos sin prefijo. El regex pide al menos 1 letra."""
    norm, was_padded = normalize_service_name("123")
    assert norm == "123"
    assert was_padded is False


def test_orqclientes_variants() -> None:
    """Variantes ORQ con nombres compuestos."""
    norm, was_padded = normalize_service_name("orqclientes62")
    assert norm == "orqclientes0062"
    assert was_padded is True


def test_ms_prefix_variant() -> None:
    """ms<x>0001 variant (algunos WAS usan ms-<svc>-was)."""
    norm, was_padded = normalize_service_name("msclientes7")
    assert norm == "msclientes0007"
    assert was_padded is True
