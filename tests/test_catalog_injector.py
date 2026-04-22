"""Tests para el inyector de catalogos oficiales al FABRICS/MIGRATE prompt."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from capamedia_cli.core.catalog_injector import (
    CatalogSnapshot,
    contains_catalog_block,
    detect_relevant_tx,
    format_for_prompt,
    load_catalogs,
)
from capamedia_cli.core.legacy_analyzer import UmpInfo

# --- fixtures ----------------------------------------------------------------


_TX_CATALOG_SAMPLE = [
    {
        "tx": "067010",
        "tipo": "RX",
        "dominio": "CLIENTES Y MARKETING",
        "capacidad": "Gestion de Clientes",
        "tribu": "TRIBU DE SEGMENTOS Y NEGOCIOS DIGITALES",
        "adaptador": "tnd-msa-ad-bnc-customers-profile",
    },
    {
        "tx": "067050",
        "tipo": None,
        "dominio": "CLIENTES Y MARKETING",
        "capacidad": "Gestion de Clientes",
        "tribu": "TRIBU DE SEGMENTOS Y NEGOCIOS DIGITALES",
        "adaptador": "tnd-msa-ad-bnc-customers-profile",
    },
    {
        "tx": "060480",
        "tipo": None,
        "dominio": "CLIENTES Y MARKETING",
        "capacidad": "Gestion de Clientes",
        "tribu": "TRIBU DE SEGMENTOS Y NEGOCIOS DIGITALES",
        "adaptador": "tnd-msa-ad-bnc-customers-profile",
    },
]

_BACKEND_CODES_SAMPLE = """<BACKEND>
  <backcode id="00638" aplicacion="iib" descripcion="Middleware Integracion (IIB)" />
  <backcode id="00045" aplicacion="bancs_app" descripcion="Core Bancario (BANCS)" />
  <backcode id="00633" aplicacion="was" descripcion="Middleware Integracion Tecnico (WAS)" />
</BACKEND>
"""


def _build_prompts_dir(root: Path, *, with_tx: bool = True, with_backend: bool = True) -> Path:
    prompts = root / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    if with_tx:
        (prompts / "tx-adapter-catalog.json").write_text(
            json.dumps(_TX_CATALOG_SAMPLE), encoding="utf-8"
        )
    if with_backend:
        backend_dir = prompts / "sqb-cfg-codigosBackend-config"
        backend_dir.mkdir(parents=True, exist_ok=True)
        (backend_dir / "codigosBackend.xml").write_text(_BACKEND_CODES_SAMPLE, encoding="utf-8")
    return prompts


# --- load_catalogs -----------------------------------------------------------


def test_load_catalogs_full_sources(tmp_path: Path) -> None:
    capamedia_root = tmp_path / "CapaMedia"
    _build_prompts_dir(capamedia_root)
    workspace = tmp_path / "ws" / "wsclientes0006"
    workspace.mkdir(parents=True)

    snap = load_catalogs(workspace, capamedia_root=capamedia_root)

    assert "067010" in snap.tx_mappings
    assert snap.tx_mappings["067010"]["adaptador"] == "tnd-msa-ad-bnc-customers-profile"
    assert snap.tx_mappings["067010"]["tipo"] == "RX"
    # null tipo se normaliza a "" (no crashea)
    assert snap.tx_mappings["067050"]["tipo"] == ""
    assert snap.backend_codes["iib"] == "00638"
    assert snap.backend_codes["bancs_app"] == "00045"
    assert snap.error_structure_rules, "rules PDF siempre presentes"
    assert any("mensajeNegocio" in r for r in snap.error_structure_rules)
    assert len(snap.source_paths) == 2


def test_load_catalogs_partial_only_tx(tmp_path: Path) -> None:
    capamedia_root = tmp_path / "CapaMedia"
    _build_prompts_dir(capamedia_root, with_backend=False)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    snap = load_catalogs(workspace, capamedia_root=capamedia_root)
    assert snap.tx_mappings
    assert not snap.backend_codes
    # error rules siempre presentes (son constantes del modulo)
    assert snap.error_structure_rules


def test_load_catalogs_partial_only_backend(tmp_path: Path) -> None:
    capamedia_root = tmp_path / "CapaMedia"
    _build_prompts_dir(capamedia_root, with_tx=False)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    snap = load_catalogs(workspace, capamedia_root=capamedia_root)
    assert not snap.tx_mappings
    assert snap.backend_codes["iib"] == "00638"


def test_load_catalogs_no_sources_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    workspace = tmp_path / "isolated"
    workspace.mkdir()
    # capamedia_root inexistente: no hay prompts dir
    bogus = tmp_path / "nope"

    with caplog.at_level(logging.WARNING, logger="capamedia_cli.core.catalog_injector"):
        snap = load_catalogs(workspace, capamedia_root=bogus)

    assert not snap.tx_mappings
    assert not snap.backend_codes
    assert any("catalogos oficiales no encontrados" in m for m in caplog.messages)


def test_load_catalogs_workspace_cache_overrides_global(tmp_path: Path) -> None:
    # Global tiene 067010, pero workspace cache tiene solo 099999: gana cache
    capamedia_root = tmp_path / "CapaMedia"
    _build_prompts_dir(capamedia_root)
    workspace = tmp_path / "ws"
    cache = workspace / ".capamedia" / "catalogs"
    cache.mkdir(parents=True)
    (cache / "tx-adapter-catalog.json").write_text(
        json.dumps(
            [
                {
                    "tx": "099999",
                    "tipo": "TX",
                    "dominio": "TEST",
                    "capacidad": "",
                    "tribu": "",
                    "adaptador": "test-adapter",
                }
            ]
        ),
        encoding="utf-8",
    )

    snap = load_catalogs(workspace, capamedia_root=capamedia_root)
    assert "099999" in snap.tx_mappings
    assert "067010" not in snap.tx_mappings, "cache local debe ganar"


def test_load_catalogs_malformed_json_graceful(tmp_path: Path) -> None:
    capamedia_root = tmp_path / "CapaMedia"
    prompts = capamedia_root / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "tx-adapter-catalog.json").write_text("{ this is not json", encoding="utf-8")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    # No debe tirar, devuelve snapshot sin tx pero con error_rules.
    snap = load_catalogs(workspace, capamedia_root=capamedia_root)
    assert snap.tx_mappings == {}


# --- format_for_prompt -------------------------------------------------------


def _make_full_snapshot() -> CatalogSnapshot:
    return CatalogSnapshot(
        tx_mappings={
            "067010": {
                "tx": "067010",
                "tipo": "RX",
                "dominio": "CLIENTES Y MARKETING",
                "capacidad": "Gestion de Clientes",
                "tribu": "TRIBU DE SEGMENTOS",
                "adaptador": "tnd-msa-ad-bnc-customers-profile",
            },
            "060480": {
                "tx": "060480",
                "tipo": "",
                "dominio": "CLIENTES",
                "capacidad": "",
                "tribu": "",
                "adaptador": "tnd-msa-ad-bnc-customers-profile",
            },
        },
        backend_codes={"iib": "00638", "bancs_app": "00045", "was": "00633"},
        error_structure_rules=[
            "mensajeNegocio: vacio. Lo gestiona DataPower.",
            "backend: usar codigosBackend.xml. IIB=00638.",
        ],
        source_paths=[Path("/tmp/tx.json"), Path("/tmp/codigos.xml")],
    )


def test_format_for_prompt_full_catalog_no_filter() -> None:
    snap = _make_full_snapshot()
    text = format_for_prompt(snap)
    assert "Catalogos oficiales" in text
    assert "067010" in text
    assert "060480" in text
    assert "tnd-msa-ad-bnc-customers-profile" in text
    assert "iib` -> **00638**" in text
    assert "bancs_app` -> **00045**" in text
    assert "mensajeNegocio" in text


def test_format_for_prompt_with_relevant_tx_filter() -> None:
    snap = _make_full_snapshot()
    text = format_for_prompt(snap, relevant_tx=["067010"])
    assert "067010" in text
    assert "060480" not in text  # no relevante


def test_format_for_prompt_uncatalogued_tx_emits_warning_bullet() -> None:
    snap = _make_full_snapshot()
    text = format_for_prompt(snap, relevant_tx=["067010", "999999"])
    assert "067010" in text
    assert "WARN TX 999999" in text
    assert "NEEDS_HUMAN_CATALOG_MAPPING" in text


def test_format_for_prompt_accepts_tx_prefix() -> None:
    # TX prefijado se normaliza
    snap = _make_full_snapshot()
    text = format_for_prompt(snap, relevant_tx=["TX067010"])
    assert "067010" in text


def test_format_for_prompt_empty_snapshot_returns_empty_string() -> None:
    assert format_for_prompt(CatalogSnapshot()) == ""


def test_format_for_prompt_backend_priority_order() -> None:
    snap = _make_full_snapshot()
    snap.backend_codes = {"zzz_custom": "00001", "iib": "00638", "bancs_app": "00045"}
    text = format_for_prompt(snap)
    # iib aparece antes que zzz_custom (priority list)
    assert text.index("iib") < text.index("zzz_custom")


# --- contains_catalog_block --------------------------------------------------


def test_contains_catalog_block_true_for_injected() -> None:
    snap = _make_full_snapshot()
    rendered = format_for_prompt(snap)
    assert contains_catalog_block(rendered)


def test_contains_catalog_block_false_for_plain_text() -> None:
    assert not contains_catalog_block("hola mundo")
    assert not contains_catalog_block("")


# --- detect_relevant_tx ------------------------------------------------------


def test_detect_relevant_tx_from_umps(tmp_path: Path) -> None:
    umps = [
        UmpInfo(name="UMPClientes0002", tx_codes=["067010", "060480"]),
        UmpInfo(name="UMPClientes0020", tx_codes=["TX067050"]),
    ]
    found = detect_relevant_tx(tmp_path, "wsclientes0006", analysis_umps=umps)
    assert set(found) == {"067010", "060480", "067050"}


def test_detect_relevant_tx_from_cloned_tx_dir(tmp_path: Path) -> None:
    tx_dir = tmp_path / "tx"
    (tx_dir / "sqb-cfg-067010-TX").mkdir(parents=True)
    (tx_dir / "sqb-cfg-060480-TX").mkdir(parents=True)
    (tx_dir / "random-file").mkdir(parents=True)

    found = detect_relevant_tx(tmp_path, "wsclientes0006")
    assert set(found) == {"067010", "060480"}


def test_detect_relevant_tx_from_complexity_md(tmp_path: Path) -> None:
    (tmp_path / "COMPLEXITY_wsclientes0006.md").write_text(
        "Reporte\n\n| UMP | TX | Extraido |\n|---|---|---|\n| UMP1 | 067010 | SI |\n",
        encoding="utf-8",
    )
    found = detect_relevant_tx(tmp_path, "wsclientes0006")
    assert "067010" in found


def test_detect_relevant_tx_union_no_duplicates(tmp_path: Path) -> None:
    umps = [UmpInfo(name="UMP1", tx_codes=["067010"])]
    tx_dir = tmp_path / "tx"
    (tx_dir / "sqb-cfg-067010-TX").mkdir(parents=True)
    (tx_dir / "sqb-cfg-060480-TX").mkdir(parents=True)
    found = detect_relevant_tx(tmp_path, "wsclientes0006", analysis_umps=umps)
    assert found == sorted({"067010", "060480"})


# --- integracion: fabric FABRICS_PROMPT --------------------------------------


def test_integration_fabrics_prompt_write_includes_catalog(tmp_path: Path) -> None:
    # Simula que el fabric helper corre y escribe FABRICS_PROMPT_<svc>.md
    from capamedia_cli.commands.fabrics import _write_fabrics_prompt
    from capamedia_cli.core.legacy_analyzer import LegacyAnalysis, WsdlInfo

    capamedia_root = tmp_path / "CapaMedia"
    _build_prompts_dir(capamedia_root)
    workspace = capamedia_root / "capamedia-cli" / "wsclientes0006"
    workspace.mkdir(parents=True)

    analysis = LegacyAnalysis(
        source_kind="iib",
        wsdl=WsdlInfo(path=tmp_path / "x.wsdl", operation_count=1, operation_names=["op"]),
        umps=[UmpInfo(name="UMPClientes0002", tx_codes=["067010"])],
        framework_recommendation="rest",
        complexity="medium",
    )

    path = _write_fabrics_prompt(
        workspace,
        "wsclientes0006",
        project_name="tnd-msa-sp-wsclientes0006",
        project_path=str(workspace / "destino"),
        namespace="tnd",
        tecnologia="bus",
        project_type="rest",
        analysis=analysis,
    )
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Catalogos oficiales" in content
    assert "067010" in content
    assert "tnd-msa-ad-bnc-customers-profile" in content
    assert contains_catalog_block(content)


# --- integracion: batch migrate prompt ---------------------------------------


def test_integration_batch_migrate_prompt_injects_catalog(tmp_path: Path) -> None:
    from capamedia_cli.commands.batch import _build_batch_migrate_prompt

    capamedia_root = tmp_path / "CapaMedia"
    _build_prompts_dir(capamedia_root)
    workspace = capamedia_root / "capamedia-cli" / "wsclientes0006"
    workspace.mkdir(parents=True)
    tx_dir = workspace / "tx"
    (tx_dir / "sqb-cfg-067010-TX").mkdir(parents=True)

    project = workspace / "destino" / "tnd-msa-sp-wsclientes0006"
    project.mkdir(parents=True)

    prompt_body = "Prompt base plain sin catalogos."
    prompt = _build_batch_migrate_prompt("wsclientes0006", workspace, project, prompt_body)
    assert "Servicio objetivo: wsclientes0006" in prompt
    assert contains_catalog_block(prompt)
    assert "067010" in prompt


def test_integration_batch_migrate_prompt_avoids_duplication(tmp_path: Path) -> None:
    from capamedia_cli.commands.batch import _build_batch_migrate_prompt

    capamedia_root = tmp_path / "CapaMedia"
    _build_prompts_dir(capamedia_root)
    workspace = capamedia_root / "capamedia-cli" / "wsclientes0006"
    workspace.mkdir(parents=True)

    project = workspace / "destino" / "p"
    project.mkdir(parents=True)

    # prompt_body ya contiene el bloque (p. ej. viene del FABRICS_PROMPT)
    existing_block = format_for_prompt(
        CatalogSnapshot(
            tx_mappings={
                "067010": {
                    "tx": "067010",
                    "tipo": "RX",
                    "dominio": "X",
                    "capacidad": "",
                    "tribu": "",
                    "adaptador": "y",
                }
            },
            backend_codes={"iib": "00638"},
            error_structure_rules=["regla de prueba"],
            source_paths=[],
        )
    )
    prompt_body = "Prompt base con catalogo ya inyectado.\n\n" + existing_block

    prompt = _build_batch_migrate_prompt("wsclientes0006", workspace, project, prompt_body)
    # Solo una vez el marcador (no duplicacion)
    assert prompt.count("## Catalogos oficiales") == 1


def test_integration_batch_migrate_uncatalogued_tx_warns(tmp_path: Path) -> None:
    from capamedia_cli.commands.batch import _build_batch_migrate_prompt

    capamedia_root = tmp_path / "CapaMedia"
    _build_prompts_dir(capamedia_root)
    workspace = capamedia_root / "capamedia-cli" / "wsclientes0999"
    workspace.mkdir(parents=True)

    # Forzamos una TX que NO esta en el catalogo
    tx_dir = workspace / "tx"
    (tx_dir / "sqb-cfg-999999-TX").mkdir(parents=True)

    project = workspace / "destino" / "p"
    project.mkdir(parents=True)

    prompt = _build_batch_migrate_prompt("wsclientes0999", workspace, project, "base")
    assert "NEEDS_HUMAN_CATALOG_MAPPING" in prompt
    assert "999999" in prompt
