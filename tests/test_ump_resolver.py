"""Tests para _resolve_ump_repo — UMPs con fallback multi-proyecto."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from capamedia_cli.commands.clone import (
    UMP_AZURE_FALLBACK_PATTERNS_IIB,
    UMP_AZURE_FALLBACK_PATTERNS_WAS,
    _resolve_ump_repo,
    _ump_name_variants,
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


def test_ump_name_variants_preserve_legacy_camel_case() -> None:
    assert _ump_name_variants("UMPClientes0020") == [
        "UMPClientes0020",
        "umpClientes0020",
        "umpclientes0020",
    ]


def test_resolve_ump_for_iib_tries_mixed_case_repo_variant(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def fake_git_clone(repo_name, dest, *, project_key, shallow):
        calls.append((project_key, repo_name))
        if project_key == "bus" and repo_name == "sqb-msa-umpClientes0020":
            dest.mkdir(parents=True, exist_ok=True)
            return (True, "")
        return (False, "not found")

    with patch("capamedia_cli.commands.clone._git_clone", side_effect=fake_git_clone):
        resolved, proj, repo = _resolve_ump_repo(
            "UMPClientes0020", tmp_path, shallow=False, parent_kind="iib"
        )

    assert resolved is not None
    assert proj == "bus"
    assert repo == "sqb-msa-umpClientes0020"
    assert calls[:2] == [
        ("bus", "sqb-msa-UMPClientes0020"),
        ("bus", "sqb-msa-umpClientes0020"),
    ]


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
        resolved, _proj, repo = _resolve_ump_repo(
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
        resolved, _proj, repo = _resolve_ump_repo(
            "umpshared0001", tmp_path, shallow=False, parent_kind="iib"
        )
    # Por fallback llega al patron WAS
    assert resolved is not None
    assert repo == "ump-umpshared0001-was"


# ---------------------------------------------------------------------------
# Modulos legados con prefijo `ms` (ms-<dep>-was)
# ---------------------------------------------------------------------------


def test_resolve_ms_module_tries_ms_pattern_first_for_was(tmp_path: Path) -> None:
    """Caso real msadministracion0048: vive en
    tpl-integration-services-was/ms-msadministracion0048-was."""
    calls: list[tuple[str, str]] = []

    def fake_git_clone(repo_name, dest, *, project_key, shallow):
        calls.append((project_key, repo_name))
        if project_key == "was" and repo_name == "ms-msadministracion0048-was":
            dest.mkdir(parents=True, exist_ok=True)
            return (True, "")
        return (False, "not found")

    with patch("capamedia_cli.commands.clone._git_clone", side_effect=fake_git_clone):
        resolved, proj, repo = _resolve_ump_repo(
            "msadministracion0048", tmp_path, shallow=False, parent_kind="was"
        )

    assert resolved is not None
    assert proj == "was"
    assert repo == "ms-msadministracion0048-was"
    assert calls[0] == ("was", "ms-msadministracion0048-was")
    assert resolved == tmp_path / "umps" / "ms-msadministracion0048-was"


def test_resolve_ms_module_tries_ms_pattern_first_for_iib(tmp_path: Path) -> None:
    """Aunque el consumidor sea IIB, un `ms*` se busca primero en ms-<dep>-was."""
    calls: list[tuple[str, str]] = []

    def fake_git_clone(repo_name, dest, *, project_key, shallow):
        calls.append((project_key, repo_name))
        if project_key == "was" and repo_name == "ms-msadministracion0048-was":
            dest.mkdir(parents=True, exist_ok=True)
            return (True, "")
        return (False, "not found")

    with patch("capamedia_cli.commands.clone._git_clone", side_effect=fake_git_clone):
        resolved, _proj, repo = _resolve_ump_repo(
            "msadministracion0048", tmp_path, shallow=False, parent_kind="iib"
        )

    assert resolved is not None
    assert repo == "ms-msadministracion0048-was"
    assert calls[0] == ("was", "ms-msadministracion0048-was")


def test_ms_module_name_variants_preserve_casing() -> None:
    assert _ump_name_variants("MSAdministracion0048") == [
        "MSAdministracion0048",
        "msAdministracion0048",
        "msadministracion0048",
    ]


def test_ump_patterns_still_prefer_ump_repo_for_ump_names(tmp_path: Path) -> None:
    """El reordenamiento por prefijo `ms` no afecta a las UMP clasicas."""
    calls: list[tuple[str, str]] = []

    def fake_git_clone(repo_name, dest, *, project_key, shallow):
        calls.append((project_key, repo_name))
        return (False, "not found")

    with patch("capamedia_cli.commands.clone._git_clone", side_effect=fake_git_clone):
        _resolve_ump_repo(
            "umptecnicos0023", tmp_path, shallow=False, parent_kind="was"
        )

    assert calls[0] == ("was", "ump-umptecnicos0023-was")


def test_info_gap_counts_cloned_ms_module(tmp_path: Path) -> None:
    """`capamedia info` no debe reportar como faltante un modulo `ms` ya
    traido: el nombre se extrae de la carpeta `ms-<dep>-was`."""
    from capamedia_cli.commands.info import _detect_ump_gap

    legacy = tmp_path / "legacy" / "ws-wsclientes0076-was"
    legacy.mkdir(parents=True)
    (legacy / "pom.xml").write_text(
        "<project><dependencies>"
        "<dependency><artifactId>msadministracion0048-dominio</artifactId></dependency>"
        "</dependencies></project>",
        encoding="utf-8",
    )
    (tmp_path / "umps" / "ms-msadministracion0048-was").mkdir(parents=True)

    referenced, cloned, missing = _detect_ump_gap(tmp_path, "was")

    assert referenced == ["msadministracion0048"]
    assert cloned == {"msadministracion0048"}
    assert missing == set()
