"""Tests para local_resolver.py."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.local_resolver import find_local_legacy


def test_find_local_legacy_was_aplicacion(tmp_path: Path) -> None:
    """Detecta WAS clasico con -aplicacion + -infraestructura hermanos."""
    capa_media = tmp_path / "CapaMedia"
    repo = capa_media / "0010-WSC" / "legacy" / "_repo"
    apl = repo / "wsclientes0010-aplicacion"
    infra = repo / "wsclientes0010-infraestructura"
    apl.mkdir(parents=True)
    infra.mkdir(parents=True)

    result = find_local_legacy("WSClientes0010", capa_media)
    # Debe retornar el padre _repo/ que contiene ambos
    assert result == repo


def test_find_local_legacy_variant(tmp_path: Path) -> None:
    """Si solo hay un _variants/, lo retorna."""
    capa_media = tmp_path / "CapaMedia"
    variant = capa_media / "0023-ORQ" / "legacy" / "_variants" / "tpr-msa-sp-orqclientes0023"
    variant.mkdir(parents=True)

    result = find_local_legacy("ORQClientes0023", capa_media)
    assert result == variant


def test_find_local_legacy_no_match_returns_none(tmp_path: Path) -> None:
    capa_media = tmp_path / "CapaMedia"
    capa_media.mkdir()
    assert find_local_legacy("WSClientes9999", capa_media) is None


def test_find_local_legacy_iib_clone(tmp_path: Path) -> None:
    """Si fue clonado por el CLI, lo detecta."""
    capa_media = tmp_path / "CapaMedia"
    clone_dir = capa_media / "0007" / "legacy" / "sqb-msa-wsclientes0007"
    clone_dir.mkdir(parents=True)

    result = find_local_legacy("WSClientes0007", capa_media)
    assert result == clone_dir


def test_find_local_legacy_no_capa_media_root(tmp_path: Path) -> None:
    """Si el root no existe, retorna None sin crashear."""
    nonexistent = tmp_path / "doesnotexist"
    assert find_local_legacy("WSClientes0010", nonexistent) is None


def test_find_local_legacy_repo_directo_con_wsdl(tmp_path: Path) -> None:
    """v0.3.3 estrategia 2b: legacy/_repo/ con WSDL directo (caso WSReglas0010)."""
    capa_media = tmp_path / "CapaMedia"
    repo = capa_media / "0010-WSR" / "legacy" / "_repo"
    repo.mkdir(parents=True)
    # Simular archivos directos en _repo/ (sin subcarpeta -aplicacion)
    (repo / "WSReglas0010.wsdl").write_text("<wsdl/>", encoding="utf-8")
    (repo / "pom.xml").write_text("<project/>", encoding="utf-8")
    (repo / "com").mkdir()

    result = find_local_legacy("WSReglas0010", capa_media)
    assert result == repo


def test_find_local_legacy_repo_directo_iib_con_msgflow(tmp_path: Path) -> None:
    """Variant: legacy/_repo/ con .msgflow + IBMdefined (IIB clasico)."""
    capa_media = tmp_path / "CapaMedia"
    repo = capa_media / "0007" / "legacy" / "_repo"
    repo.mkdir(parents=True)
    (repo / "WSClientes0007.msgflow").write_text("<msgflow/>", encoding="utf-8")
    (repo / "IBMdefined").mkdir()

    result = find_local_legacy("WSClientes0007", capa_media)
    assert result == repo
