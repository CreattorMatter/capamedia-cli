"""Tests del catalogo de adaptadores BANCS (loader + inyeccion al prompt)."""

from __future__ import annotations

from pathlib import Path

import capamedia_cli
from capamedia_cli.core import bancs_adapters as ba
from capamedia_cli.core.catalog_injector import (
    contains_bancs_adapters_block,
    format_bancs_adapters_block,
)

_JSON = Path(capamedia_cli.__file__).parent / "data" / "catalog" / "bancs_adapters.json"


# -- loader -------------------------------------------------------------------


def test_catalog_loads_with_adapters_and_tx() -> None:
    cat = ba.load_adapters_catalog()
    assert len(cat["adapters"]) >= 8
    assert len(cat["tx_map"]) >= 50
    assert cat["meta"]["ola"] == 2


def test_get_adapter_for_tx_known() -> None:
    info = ba.get_adapter_for_tx("060480")  # perfil cliente (TX clasica)
    assert info is not None
    assert info["adapter"] == "tnd-msa-ad-bnc-customers-profile"
    assert "arq-adaptadores.svc.cluster.local" in info["url_internal"]


def test_get_adapter_for_tx_normalizes_forms() -> None:
    base = ba.get_adapter_for_tx("060480")
    assert ba.get_adapter_for_tx("TX060480") == base
    assert ba.get_adapter_for_tx("TRX 060480") == base
    assert ba.get_adapter_for_tx("60480") == base  # zero-pad a 6 digitos


def test_get_adapter_for_tx_unknown_and_garbage() -> None:
    assert ba.get_adapter_for_tx("999999") is None
    assert ba.get_adapter_for_tx("") is None
    assert ba.get_adapter_for_tx("no-es-tx") is None


def test_float_tx_from_numbers_normalized() -> None:
    """La hoja Ownership traia TX como floats (60602.0) -> 060602."""
    info = ba.get_adapter_for_tx("060602")
    assert info is not None
    assert info["adapter"] == "tpr-msa-ad-bnc-products-ownership"


def test_json_is_sanitized_no_curls_cookies_pii() -> None:
    """El JSON shipped JAMAS contiene material sensible del .numbers fuente.
    Patrones ESTRUCTURALES (espejo de la guardia del generador), no strings sueltos."""
    import re

    raw = _JSON.read_text(encoding="utf-8")
    forbidden = [
        ("cookie", re.compile(r"(?i)cookie")),
        ("curl", re.compile(r"(?i)\bcurl\b")),
        ("header-flag", re.compile(r"--header")),
        ("body-bancs", re.compile(r"(?i)transactionid|bancsuser")),
        ("token-hex32", re.compile(r"(?i)\b[0-9a-f]{32}\b")),
        ("cedula-10dig", re.compile(r"\b\d{10}\b")),
        ("auth", re.compile(r"(?i)authorization|bearer")),
        ("x-headers", re.compile(r"(?i)x-guid|x-session|x-device")),
        ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ]
    for label, pattern in forbidden:
        assert not pattern.search(raw), f"patron '{label}' se colo en bancs_adapters.json"


def test_typo_tx_resolved_from_curl() -> None:
    """M2: el label TX067728 era un typo; el curl ejecuta 067228 -> manda el curl,
    con la discrepancia auditada en obs."""
    assert ba.get_adapter_for_tx("067728") is None
    info = ba.get_adapter_for_tx("067228")
    assert info is not None
    assert info["adapter"] == "taa-msa-ad-bnc-products-compliance"
    assert "label decia TX067728" in info["obs"]


def test_missing_json_degrades_gracefully(monkeypatch, tmp_path: Path) -> None:
    """Sin JSON (instalacion rota) el loader degrada a vacio, sin crash (L9)."""
    ba.load_adapters_catalog.cache_clear()
    monkeypatch.setattr(ba, "_CATALOG_PATH", tmp_path / "no-existe.json")
    try:
        assert ba.get_adapter_for_tx("060480") is None
        assert ba.list_adapters() == []
        assert ba.known_tx_codes() == []
    finally:
        ba.load_adapters_catalog.cache_clear()


# -- inyeccion ----------------------------------------------------------------


def test_block_maps_tx_to_adapters() -> None:
    block = format_bancs_adapters_block(["060480", "064020"])
    assert contains_bancs_adapters_block(block)
    assert "tnd-msa-ad-bnc-customers-profile" in block
    assert "tpr-msa-ad-bnc-products-details" in block
    assert "CCC_BANCS_ADAPTER_" in block  # nota: URL real siempre via env vars


def test_block_lists_unknown_tx_separately() -> None:
    block = format_bancs_adapters_block(["060480", "999999"])
    assert "SIN adaptador relevado" in block
    assert "999999" in block
    assert "tx-adapter-catalog.json" in block  # apunta a la fuente autoritativa (M3)


def test_block_misses_normalized_and_deduped() -> None:
    """L4: los misses tambien se normalizan y dedupean (TX999999 == 999999)."""
    block = format_bancs_adapters_block(["060480", "TX999999", "999999", "99999"])
    assert block.count("999999") == 1  # '099999' (de 99999) es otra TX distinta
    assert "099999" in block


def test_block_nota_has_concrete_env_var_pattern() -> None:
    """L6: la NOTA nombra el patron oficial concreto, no un CCC_* generico."""
    block = format_bancs_adapters_block(["060480"])
    assert "CCC_BANCS_ADAPTER_" in block
    assert "bancs.webclients" in block
    assert "VERIFICAR contra el ESQL" in block  # L5: el ESQL es el arbitro


def test_block_empty_when_no_known_tx() -> None:
    assert format_bancs_adapters_block(["999999"]) == ""
    assert format_bancs_adapters_block([]) == ""


def test_block_dedupes_tx() -> None:
    block = format_bancs_adapters_block(["060480", "TX060480", "60480"])
    assert block.count("| 060480 |") == 1


def test_build_prompt_injects_adapters_for_bancs_tx(tmp_path: Path) -> None:
    """Workspace con TX clonada (sqb-cfg-060480-TX) -> el prompt trae el bloque."""
    from capamedia_cli.commands.batch import _build_batch_migrate_prompt

    (tmp_path / "tx" / "sqb-cfg-060480-TX").mkdir(parents=True)
    out = _build_batch_migrate_prompt("WSClientes0011", tmp_path, tmp_path / "mig", "BASE")
    assert contains_bancs_adapters_block(out)
    assert "tnd-msa-ad-bnc-customers-profile" in out


def test_build_prompt_no_adapters_without_tx(tmp_path: Path) -> None:
    from capamedia_cli.commands.batch import _build_batch_migrate_prompt

    out = _build_batch_migrate_prompt("WSProductos0033", tmp_path, tmp_path / "mig", "BASE")
    assert not contains_bancs_adapters_block(out)


def test_canonical_bancs_md_lists_adapters_bidirectional() -> None:
    """bancs.md <-> JSON en sincronia BIDIRECCIONAL (L7): ni falta ni sobra."""
    import re

    md = (
        Path(capamedia_cli.__file__).parent / "data" / "canonical" / "context" / "bancs.md"
    ).read_text(encoding="utf-8")
    in_md = set(re.findall(r"`([a-z]{3}-msa-ad-bnc-[a-z0-9-]+)`", md))
    in_json = set(ba.load_adapters_catalog()["adapters"])
    assert in_md == in_json, f"drift doc<->catalogo: solo-md={in_md - in_json} solo-json={in_json - in_md}"
    assert "arq-adaptadores.svc.cluster.local" in md
