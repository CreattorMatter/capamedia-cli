"""Tests para Block 20 (v0.23.0): ORQ invoca servicio migrado, no legacy."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import CheckContext, run_block_20


def _mk(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_block_20_skip_for_non_orq(tmp_path: Path) -> None:
    """Solo corre cuando source_type=orq. WAS/BUS no activan el check."""
    project = tmp_path / "proj"
    (project / "src" / "main").mkdir(parents=True)
    ctx = CheckContext(
        migrated_path=project, legacy_path=None, source_type="was",
    )
    results = run_block_20(ctx)
    assert results == []


def test_block_20_pass_when_orq_has_no_bad_references(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    _mk(
        project / "src" / "main" / "resources" / "application.yml",
        """services:
  wsclientes0076:
    url: \${CCC_WSCLIENTES0076_URL}
""",
    )
    ctx = CheckContext(migrated_path=project, legacy_path=None, source_type="orq")
    results = run_block_20(ctx)
    assert len(results) == 1
    assert results[0].status == "pass"


def test_block_20_fails_on_sqb_msa_in_yml(tmp_path: Path) -> None:
    """URL apuntando al legacy `sqb-msa-wsclientes0023` → FAIL HIGH."""
    project = tmp_path / "proj"
    _mk(
        project / "src" / "main" / "resources" / "application.yml",
        """services:
  wsclientes0023:
    url: "http://legacy/sqb-msa-wsclientes0023/getCliente"
""",
    )
    ctx = CheckContext(migrated_path=project, legacy_path=None, source_type="orq")
    results = run_block_20(ctx)
    fails = [r for r in results if r.status == "fail"]
    assert len(fails) == 1
    assert fails[0].severity == "high"
    assert "wsclientes0023" in fails[0].title
    assert "migrado" in fails[0].suggested_fix.lower()


def test_block_20_fails_on_ws_was_in_java(tmp_path: Path) -> None:
    """Adapter referenciando `ws-wsclientes0076-was` → FAIL HIGH."""
    project = tmp_path / "proj"
    _mk(
        project / "src" / "main" / "java" / "Adapter.java",
        'String url = "https://host/ws-wsclientes0076-was/api";',
    )
    ctx = CheckContext(migrated_path=project, legacy_path=None, source_type="orq")
    results = run_block_20(ctx)
    fails = [r for r in results if r.status == "fail"]
    assert len(fails) == 1
    assert "wsclientes0076" in fails[0].title


def test_block_20_ignores_self_reference_to_orq(tmp_path: Path) -> None:
    """Una referencia al propio ORQ (ej. `orqclientes0027`) no es falla."""
    project = tmp_path / "proj"
    _mk(
        project / "src" / "main" / "java" / "Config.java",
        'String my = "sqb-msa-orqclientes0027";',  # auto-referencia ok
    )
    ctx = CheckContext(migrated_path=project, legacy_path=None, source_type="orq")
    results = run_block_20(ctx)
    fails = [r for r in results if r.status == "fail"]
    assert fails == []


def test_block_20_multiple_offenders(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    _mk(
        project / "src" / "main" / "resources" / "application.yml",
        """a: "sqb-msa-wsclientes0023"
b: "ws-wsclientes0076-was"
""",
    )
    ctx = CheckContext(migrated_path=project, legacy_path=None, source_type="orq")
    results = run_block_20(ctx)
    fails = [r for r in results if r.status == "fail"]
    assert len(fails) == 2
