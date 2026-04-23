"""Tests para Block 19 del checklist (v0.21.0): Properties delivery audit."""

from __future__ import annotations

from pathlib import Path

import yaml

from capamedia_cli.core.checklist_rules import CheckContext, run_block_19


def _setup_workspace_with_report(
    tmp_path: Path, report: dict
) -> tuple[Path, Path]:
    """Crea estructura workspace/destino/proj y el properties-report.yaml."""
    ws = tmp_path / "service"
    project = ws / "destino" / "tpr-msa-sp-service"
    project.mkdir(parents=True)

    (ws / ".capamedia").mkdir(parents=True)
    (ws / ".capamedia" / "properties-report.yaml").write_text(
        yaml.safe_dump(report, sort_keys=False), encoding="utf-8",
    )
    return ws, project


def test_block_19_skip_when_no_report(tmp_path: Path) -> None:
    """Sin properties-report.yaml, Block 19 no emite results (skip)."""
    project = tmp_path / "destino" / "p"
    project.mkdir(parents=True)
    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_19(ctx)
    assert results == []


def test_block_19_pass_when_no_pending_in_report(tmp_path: Path) -> None:
    """Reporte con solo SHARED_CATALOG -> 1 result PASS."""
    report = {
        "service_specific_properties": [
            {"file": "catalog.properties", "status": "SHARED_CATALOG",
             "source": "bank-shared-catalog", "keys_used": []},
        ],
    }
    ws, project = _setup_workspace_with_report(tmp_path, report)
    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_19(ctx)

    assert len(results) == 1
    assert results[0].status == "pass"
    assert "catalogo embebido" in results[0].detail


def test_block_19_fail_when_file_still_pending(tmp_path: Path) -> None:
    """Archivo declarado PENDING sin entrega -> FAIL MEDIUM con hint."""
    report = {
        "service_specific_properties": [
            {"file": "pending.properties", "status": "PENDING_FROM_BANK",
             "source": "service", "keys_used": ["K1", "K2"]},
        ],
    }
    ws, project = _setup_workspace_with_report(tmp_path, report)
    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_19(ctx)

    assert len(results) == 1
    r = results[0]
    assert r.status == "fail"
    assert r.severity == "medium"
    # El nombre aparece en id/title; las keys en detail
    assert "pending.properties" in r.id
    assert "pending.properties" in r.title
    assert "K1" in r.detail
    assert "K2" in r.detail
    assert ".capamedia/inputs/pending.properties" in r.suggested_fix


def test_block_19_pass_when_file_delivered_fully(tmp_path: Path) -> None:
    """Archivo con TODAS las keys declaradas -> PASS."""
    report = {
        "service_specific_properties": [
            {"file": "full.properties", "status": "PENDING_FROM_BANK",
             "source": "service", "keys_used": ["K1", "K2"]},
        ],
    }
    ws, project = _setup_workspace_with_report(tmp_path, report)
    inputs = ws / ".capamedia" / "inputs"
    inputs.mkdir()
    (inputs / "full.properties").write_text(
        "K1=v1\nK2=v2\n", encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_19(ctx)

    assert len(results) == 1
    assert results[0].status == "pass"
    assert "entregado en" in results[0].detail


def test_block_19_fail_medium_when_partial(tmp_path: Path) -> None:
    """Archivo entregado pero con keys faltantes -> FAIL MEDIUM."""
    report = {
        "service_specific_properties": [
            {"file": "partial.properties", "status": "PENDING_FROM_BANK",
             "source": "ump:x", "keys_used": ["K1", "K2", "K3"]},
        ],
    }
    ws, project = _setup_workspace_with_report(tmp_path, report)
    inputs = ws / ".capamedia" / "inputs"
    inputs.mkdir()
    (inputs / "partial.properties").write_text("K1=v1\n", encoding="utf-8")

    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_19(ctx)

    r = results[0]
    assert r.status == "fail"
    assert r.severity == "medium"
    assert "faltan" in r.detail
    assert "K2" in r.detail
    assert "K3" in r.detail


def test_block_19_resolves_workspace_root_from_destino_path(tmp_path: Path) -> None:
    """Cuando migrated_path esta bajo destino/, workspace es 2 niveles arriba."""
    report = {
        "service_specific_properties": [
            {"file": "x.properties", "status": "PENDING_FROM_BANK",
             "source": "service", "keys_used": ["K"]},
        ],
    }
    ws, project = _setup_workspace_with_report(tmp_path, report)
    assert project.parent.name == "destino"

    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_19(ctx)
    # Si hubiera usado project en vez de workspace, no encontraria el report
    assert len(results) == 1
    assert results[0].block == "Block 19"


def test_block_19_multiple_files_mixed_status(tmp_path: Path) -> None:
    """Reporte con 3 archivos: 1 DELIVERED + 1 PARTIAL + 1 STILL_PENDING."""
    report = {
        "service_specific_properties": [
            {"file": "good.properties", "status": "PENDING_FROM_BANK",
             "source": "service", "keys_used": ["K"]},
            {"file": "partial.properties", "status": "PENDING_FROM_BANK",
             "source": "service", "keys_used": ["K1", "K2"]},
            {"file": "missing.properties", "status": "PENDING_FROM_BANK",
             "source": "ump:x", "keys_used": ["X"]},
        ],
    }
    ws, project = _setup_workspace_with_report(tmp_path, report)
    inputs = ws / ".capamedia" / "inputs"
    inputs.mkdir()
    (inputs / "good.properties").write_text("K=v\n", encoding="utf-8")
    (inputs / "partial.properties").write_text("K1=v1\n", encoding="utf-8")
    # missing.properties NO se crea

    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_19(ctx)
    assert len(results) == 3

    by_file = {r.id: r for r in results}
    assert by_file["19.good.properties"].status == "pass"
    assert by_file["19.partial.properties"].status == "fail"
    assert by_file["19.partial.properties"].severity == "medium"
    assert by_file["19.missing.properties"].status == "fail"
    assert by_file["19.missing.properties"].severity == "medium"
