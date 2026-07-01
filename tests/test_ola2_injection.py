"""Tests del Punto A: inyeccion del bloque de downstreams Ola2 en el prompt."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.catalog_injector import (
    _CATALOG_MARKER,
    _OLA2_DOWNSTREAMS_MARKER,
    _cell,
    contains_ola2_downstreams_block,
    format_ola2_downstreams_block,
)


def test_block_for_orchestrator_lists_all_downstreams() -> None:
    block = format_ola2_downstreams_block("ORQProductos0019")
    assert contains_ola2_downstreams_block(block)
    rows = [ln for ln in block.splitlines() if ln.startswith(("| WS", "| ORQ"))]
    assert len(rows) == 17  # ORQProductos0019 tiene 17 downstreams
    assert "Bus Omnicanalidad" in block  # tecnologia real de un downstream con ficha


def test_block_has_hard_note_forbidding_mandatory_derivation() -> None:
    block = format_ola2_downstreams_block("ORQProductos0015")
    assert "RETURN FALSE" in block
    assert "ESQL" in block
    assert "mandatory" in block.lower()


def test_block_empty_for_non_orchestrator_and_unknown() -> None:
    assert format_ola2_downstreams_block("WSClientes0024") == ""  # WS conocido, no ORQ
    assert format_ola2_downstreams_block("WSProductos0033") == ""
    assert format_ola2_downstreams_block("ORQProductos9999") == ""  # ausente (entrega 2+)


def test_block_case_and_form_insensitive() -> None:
    canonical = format_ola2_downstreams_block("ORQProductos0019")
    assert canonical != ""
    assert format_ola2_downstreams_block("orqproductos0019") == canonical
    assert format_ola2_downstreams_block("tpr-msa-sp-orqproductos0019") == canonical


def test_downstream_without_ficha_shows_dash() -> None:
    block = format_ola2_downstreams_block("ORQProductos0019")
    row = next(ln for ln in block.splitlines() if ln.startswith("| WSTecnicos0063 "))
    assert "| no |" in row  # in_discovery=no
    assert "| - |" in row  # sin ficha -> tecnologia/metodos "-"


def test_markers_do_not_collide() -> None:
    assert not contains_ola2_downstreams_block(_CATALOG_MARKER + " (cargados automaticamente...)")
    assert _OLA2_DOWNSTREAMS_MARKER != _CATALOG_MARKER


# -- integracion en el ensamblado del prompt de migracion --------------------


def test_build_prompt_injects_ola2_for_orq(tmp_path: Path) -> None:
    from capamedia_cli.commands.batch import _build_batch_migrate_prompt

    out = _build_batch_migrate_prompt("ORQProductos0019", tmp_path, tmp_path / "mig", "PROMPT BASE")
    assert contains_ola2_downstreams_block(out)
    assert "PROMPT BASE" in out


def test_build_prompt_no_ola2_for_ws(tmp_path: Path) -> None:
    from capamedia_cli.commands.batch import _build_batch_migrate_prompt

    out = _build_batch_migrate_prompt("WSProductos0033", tmp_path, tmp_path / "mig", "PROMPT BASE")
    assert not contains_ola2_downstreams_block(out)


def test_build_prompt_does_not_duplicate_block(tmp_path: Path) -> None:
    from capamedia_cli.commands.batch import _build_batch_migrate_prompt

    pre = format_ola2_downstreams_block("ORQProductos0019")
    out = _build_batch_migrate_prompt("ORQProductos0019", tmp_path, tmp_path / "mig", pre)
    assert out.count(_OLA2_DOWNSTREAMS_MARKER) == 1


# -- fixes del review: escape de pipe (M1) + guardrail anti-skip in_ola1 (M2) --


def test_cell_escapes_pipe_and_collapses_whitespace() -> None:
    assert _cell("a | b") == r"a \| b"  # pipe escapado -> no rompe la tabla
    assert _cell("x\n  y\tz") == "x y z"  # colapsa \n/tabs/espacios
    assert _cell("") == "-"
    assert _cell(None) == "-"


def test_pipe_in_field_does_not_break_table(monkeypatch) -> None:
    """Un metodo con '|' se escapa en el bloque (M1): no inyecta columnas espurias."""
    import capamedia_cli.core.ola2_catalog as ola2

    real = ola2.get_discovery

    def fake(name: str):
        fic = dict(real(name) or {})
        fic["metodos_expone"] = "m1 | m2"
        return fic

    monkeypatch.setattr(ola2, "get_discovery", fake)
    block = format_ola2_downstreams_block("ORQProductos0015")
    assert r"m1 \| m2" in block  # el pipe quedo escapado


def test_block_note_forbids_skipping_by_in_ola1() -> None:
    """La NOTA DURA prohibe saltear una delegacion por in_ola1=si (M2)."""
    block = format_ola2_downstreams_block("ORQProductos0015")
    low = block.lower()
    assert "in_ola1" in low
    assert "nunca saltees" in low
