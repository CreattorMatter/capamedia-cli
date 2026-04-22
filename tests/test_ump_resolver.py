"""Tests para _resolve_ump_repo — UMPs con fallback multi-proyecto."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from capamedia_cli.commands.clone import (
    UMP_AZURE_FALLBACK_PATTERNS_IIB,
    UMP_AZURE_FALLBACK_PATTERNS_WAS,
    _resolve_ump_repo,
)


def test_patterns_iib_prefers_sqb_msa() -> None:
    first_proj, first_pattern = UMP_AZURE_FALLBACK_PATTERNS_IIB[0]
    assert first_proj == "bus"
    assert first_pattern == "sqb-msa-{ump}"


def test_patterns_was_prefers_ump_was() -> None:
    """Para servicios WAS, el primer pattern es `ump-<ump>-was`."""
    first_proj, first_pattern = UMP_AZURE_FALLBACK_PATTERNS_WAS[0]
    assert first_proj == "was"
    assert first_pattern == "ump-{ump}-was"


def test_resolve_ump_for_was_tries_was_pattern_first(tmp_path: Path) -> None:
    """Caso real wstecnicos0008: UMP umptecnicos0023 vive en
    tpl-integration-services-was/ump-umptecnicos0023-was. Con parent_kind=was,
    se prueba ese patron primero."""
    calls: list[tuple[str, str]] = []

    def fake_git_clone(repo_name, dest, *, project_key, shallow):
        calls.append((project_key, repo_name))
        # Solo matchea ump-umptecnicos0023-was
        if project_key == "was" and repo_name == "ump-umptecnicos0023-was":
            dest.mkdir(parents=True, exist_ok=True)
            return (True, "")
        return (False, "not found")

    with patch("capamedia_cli.commands.clone._git_clone", side_effect=fake_git_clone):
        resolved, proj, repo = _resolve_ump_repo(
            "umptecnicos0023", tmp_path, shallow=False, parent_kind="was"
        )

    assert resolved is not None
    assert proj == "was"
    assert repo == "ump-umptecnicos0023-was"
    # Primera llamada debe ser al patron WAS (no al sqb-msa de IIB)
    assert calls[0] == ("was", "ump-umptecnicos0023-was")


def test_resolve_ump_for_iib_tries_sqb_msa_first(tmp_path: Path) -> None:
    """Caso IIB/ORQ clasico: UMP vive en tpl-bus-omnicanal/sqb-msa-<ump>."""
    calls: list[tuple[str, str]] = []

    def fake_git_clone(repo_name, dest, *, project_key, shallow):
        calls.append((project_key, repo_name))
        if project_key == "bus" and repo_name == "sqb-msa-umpclientes0002":
            dest.mkdir(parents=True, exist_ok=True)
            return (True, "")
        return (False, "not found")

    with patch("capamedia_cli.commands.clone._git_clone", side_effect=fake_git_clone):
        resolved, proj, repo = _resolve_ump_repo(
            "umpclientes0002", tmp_path, shallow=False, parent_kind="iib"
        )

    assert resolved is not None
    assert proj == "bus"
    assert repo == "sqb-msa-umpclientes0002"
    assert calls[0] == ("bus", "sqb-msa-umpclientes0002")


def test_resolve_ump_falls_back_to_alternative_project(tmp_path: Path) -> None:
    """Si la UMP de un WAS no esta en ump-<ump>-was, probar ms-<ump>-was."""
    call_count = {"n": 0}

    def fake_git_clone(repo_name, dest, *, project_key, shallow):
        call_count["n"] += 1
        if repo_name == "ms-umptecnicos0023-was":
            dest.mkdir(parents=True, exist_ok=True)
            return (True, "")
        return (False, "not found")

    with patch("capamedia_cli.commands.clone._git_clone", side_effect=fake_git_clone):
        resolved, proj, repo = _resolve_ump_repo(
            "umptecnicos0023", tmp_path, shallow=False, parent_kind="was"
        )

    assert resolved is not None
    assert repo == "ms-umptecnicos0023-was"
    assert call_count["n"] == 2  # ump-X-was falla, ms-X-was pasa


def test_resolve_ump_returns_none_when_nothing_matches(tmp_path: Path) -> None:
    with patch(
        "capamedia_cli.commands.clone._git_clone",
        return_value=(False, "404 not found"),
    ):
        resolved, proj, repo = _resolve_ump_repo(
            "umpXnoexiste0000", tmp_path, shallow=False, parent_kind="was"
        )
    assert resolved is None
    assert proj == ""
    assert repo == ""


def test_resolve_ump_iib_fallback_to_was_project(tmp_path: Path) -> None:
    """Caso edge: un IIB que usa una UMP que fue migrada a WAS. El patron
    IIB falla pero el WAS matchea."""

    def fake_git_clone(repo_name, dest, *, project_key, shallow):
        if project_key == "was" and repo_name == "ump-umpshared0001-was":
            dest.mkdir(parents=True, exist_ok=True)
            return (True, "")
        return (False, "not found")

    with patch("capamedia_cli.commands.clone._git_clone", side_effect=fake_git_clone):
        resolved, proj, repo = _resolve_ump_repo(
            "umpshared0001", tmp_path, shallow=False, parent_kind="iib"
        )
    # Por fallback llega al patron WAS
    assert resolved is not None
    assert repo == "ump-umpshared0001-was"
