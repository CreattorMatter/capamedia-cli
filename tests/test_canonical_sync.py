"""Tests para `capamedia canonical sync` / `diff`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from capamedia_cli.commands import canonical as canonical_cmd

runner = CliRunner()


FM_CANONICAL = """---
name: analisis-servicio
title: Analisis legacy
type: prompt
---

# Body original canonical

Contenido canonico que sera reemplazado.
"""

FM_CANONICAL_ORQ = """---
name: analisis-orq
title: Analisis ORQ
type: prompt
---

# Body ORQ original

cosas.
"""

BODY_SOURCE_UPDATED = """# Prompt: Pre-Migration - Legacy IIB Analysis

> Version actualizada por Julian.

## ROLE

Senior legacy analyst con cambios frescos.
"""


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    """Crea un arbol source tipico de Julian."""
    root = tmp_path / "prompts-source"
    (root / "pre-migracion").mkdir(parents=True)
    (root / "migracion" / "REST").mkdir(parents=True)
    (root / "post-migracion").mkdir(parents=True)
    (root / "configuracion-claude-code").mkdir(parents=True)
    return root


@pytest.fixture
def canonical_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Crea un canonical root aislado y patchea _canonical_root para apuntar alli."""
    root = tmp_path / "canonical"
    (root / "prompts").mkdir(parents=True)
    (root / "context").mkdir(parents=True)
    monkeypatch.setattr(canonical_cmd, "_canonical_root", lambda: root)
    return root


# ---------------------------------------------------------------------------
# Diff collection behaviour
# ---------------------------------------------------------------------------


def test_identical_files_are_skipped_from_updates(
    source_root: Path, canonical_root: Path
) -> None:
    """Source identico al body del canonical (con fm preservado) => IDENTICAL."""
    (canonical_root / "prompts" / "analisis-servicio.md").write_text(
        FM_CANONICAL, encoding="utf-8"
    )
    # El source tiene solo el body que el canonical ya tiene post-fm.
    body = FM_CANONICAL.split("---", 2)[2].lstrip("\n")
    (source_root / "pre-migracion" / "01-analisis-servicio.md").write_text(
        body, encoding="utf-8"
    )

    entries = canonical_cmd._collect_diffs(source_root, canonical_root, "**/*.md")
    by_status = {e.status for e in entries}
    assert "IDENTICAL" in by_status
    assert "UPDATED" not in by_status


def test_source_updated_produces_diff_and_apply(
    source_root: Path, canonical_root: Path
) -> None:
    (canonical_root / "prompts" / "analisis-servicio.md").write_text(
        FM_CANONICAL, encoding="utf-8"
    )
    (source_root / "pre-migracion" / "01-analisis-servicio.md").write_text(
        BODY_SOURCE_UPDATED, encoding="utf-8"
    )

    entries = canonical_cmd._collect_diffs(source_root, canonical_root, "**/*.md")
    updated = [e for e in entries if e.status == "UPDATED"]
    assert len(updated) == 1
    assert updated[0].plus_lines > 0
    assert updated[0].minus_lines > 0
    assert updated[0].diff_text  # tenemos diff real

    canonical_cmd._apply_changes(entries)
    final = (canonical_root / "prompts" / "analisis-servicio.md").read_text(
        encoding="utf-8"
    )
    # Frontmatter preservado.
    assert final.startswith("---")
    assert "name: analisis-servicio" in final
    # Body reemplazado.
    assert "Version actualizada por Julian." in final
    assert "Contenido canonico que sera reemplazado." not in final


def test_canonical_missing_is_new(source_root: Path, canonical_root: Path) -> None:
    (source_root / "pre-migracion" / "01-analisis-servicio.md").write_text(
        BODY_SOURCE_UPDATED, encoding="utf-8"
    )
    entries = canonical_cmd._collect_diffs(source_root, canonical_root, "**/*.md")
    new = [e for e in entries if e.status == "NEW"]
    assert len(new) == 1
    assert new[0].plus_lines == len(BODY_SOURCE_UPDATED.splitlines())

    canonical_cmd._apply_changes(entries)
    target = canonical_root / "prompts" / "analisis-servicio.md"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == BODY_SOURCE_UPDATED


def test_source_missing_produces_orphan_and_never_deletes(
    source_root: Path, canonical_root: Path
) -> None:
    (canonical_root / "prompts" / "analisis-orq.md").write_text(
        FM_CANONICAL_ORQ, encoding="utf-8"
    )
    # No escribimos ningun source para ese archivo.

    entries = canonical_cmd._collect_diffs(source_root, canonical_root, "**/*.md")
    orphans = [e for e in entries if e.status == "ORPHAN"]
    assert any(o.rel_display == "prompts/analisis-orq.md" for o in orphans)

    canonical_cmd._apply_changes(entries)
    # Orphans jamas se borran.
    assert (canonical_root / "prompts" / "analisis-orq.md").exists()


def test_frontmatter_preservation_source_without_fm(
    source_root: Path, canonical_root: Path
) -> None:
    """Source sin fm + canonical con fm => se conserva fm del canonical."""
    (canonical_root / "prompts" / "analisis-servicio.md").write_text(
        FM_CANONICAL, encoding="utf-8"
    )
    (source_root / "pre-migracion" / "01-analisis-servicio.md").write_text(
        BODY_SOURCE_UPDATED, encoding="utf-8"
    )
    entries = canonical_cmd._collect_diffs(source_root, canonical_root, "**/*.md")
    canonical_cmd._apply_changes(entries)

    result = (canonical_root / "prompts" / "analisis-servicio.md").read_text(
        encoding="utf-8"
    )
    # Frontmatter del canonical preservado tal cual (campos + valores).
    assert "name: analisis-servicio" in result
    assert "title: Analisis legacy" in result
    assert "type: prompt" in result
    # Body es el del source.
    assert "Version actualizada por Julian." in result


def test_mapping_by_filename_also_works(
    source_root: Path, canonical_root: Path
) -> None:
    """Aunque el source ponga el archivo suelto con el mismo nombre, debe mapear."""
    (canonical_root / "prompts" / "analisis-servicio.md").write_text(
        FM_CANONICAL, encoding="utf-8"
    )
    # Sin subcarpeta pre-migracion, con el nombre canonical directo.
    (source_root / "analisis-servicio.md").write_text(
        BODY_SOURCE_UPDATED, encoding="utf-8"
    )
    entries = canonical_cmd._collect_diffs(source_root, canonical_root, "**/*.md")
    updated = [e for e in entries if e.status == "UPDATED"]
    assert len(updated) == 1
    assert updated[0].target_path == canonical_root / "prompts" / "analisis-servicio.md"


def test_unmapped_source_is_skipped(source_root: Path, canonical_root: Path) -> None:
    (source_root / "totally-random.md").write_text("hola", encoding="utf-8")
    entries = canonical_cmd._collect_diffs(source_root, canonical_root, "**/*.md")
    skipped = [e for e in entries if e.status == "SKIPPED"]
    assert len(skipped) == 1
    assert skipped[0].skip_reason == "no mapping"


def test_context_mapping_for_claude_config(
    source_root: Path, canonical_root: Path
) -> None:
    """configuracion-claude-code/*.md -> canonical/context/<name>."""
    (canonical_root / "context" / "hexagonal.md").write_text(
        "body viejo", encoding="utf-8"
    )
    (source_root / "configuracion-claude-code" / "hexagonal.md").write_text(
        "body nuevo", encoding="utf-8"
    )
    entries = canonical_cmd._collect_diffs(source_root, canonical_root, "**/*.md")
    updated = [e for e in entries if e.status == "UPDATED"]
    assert len(updated) == 1
    assert updated[0].target_path == canonical_root / "context" / "hexagonal.md"


# ---------------------------------------------------------------------------
# CLI end-to-end behaviour (typer runner)
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write(source_root: Path, canonical_root: Path) -> None:
    target = canonical_root / "prompts" / "analisis-servicio.md"
    target.write_text(FM_CANONICAL, encoding="utf-8")
    original = target.read_text(encoding="utf-8")
    (source_root / "pre-migracion" / "01-analisis-servicio.md").write_text(
        BODY_SOURCE_UPDATED, encoding="utf-8"
    )

    result = runner.invoke(
        canonical_cmd.app,
        ["sync", "--source", str(source_root), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert target.read_text(encoding="utf-8") == original
    assert "dry-run" in result.output.lower()


def test_yes_skips_confirm(source_root: Path, canonical_root: Path) -> None:
    target = canonical_root / "prompts" / "analisis-servicio.md"
    target.write_text(FM_CANONICAL, encoding="utf-8")
    (source_root / "pre-migracion" / "01-analisis-servicio.md").write_text(
        BODY_SOURCE_UPDATED, encoding="utf-8"
    )

    log_dir = source_root.parent / ".capamedia" / "canonical-sync"
    # Aseguramos que Confirm.ask no se llama en modo --yes.
    with patch.object(canonical_cmd.Confirm, "ask", return_value=False) as mock_ask:
        result = runner.invoke(
            canonical_cmd.app,
            [
                "sync",
                "--source",
                str(source_root),
                "--yes",
                "--log-dir",
                str(log_dir),
            ],
        )

    assert result.exit_code == 0, result.output
    mock_ask.assert_not_called()
    assert "Version actualizada por Julian." in target.read_text(encoding="utf-8")
    # Log se escribio.
    logs = list(log_dir.glob("*.log"))
    assert len(logs) == 1


def test_no_changes_exits_zero(source_root: Path, canonical_root: Path) -> None:
    result = runner.invoke(
        canonical_cmd.app,
        ["sync", "--source", str(source_root), "--yes"],
    )
    assert result.exit_code == 0
    assert "No hay cambios" in result.output


def test_invalid_source_fails(tmp_path: Path, canonical_root: Path) -> None:
    assert canonical_root.exists()  # fixture activa el monkeypatch
    bogus = tmp_path / "does-not-exist"
    result = runner.invoke(
        canonical_cmd.app,
        ["sync", "--source", str(bogus), "--dry-run"],
    )
    assert result.exit_code == 2
    assert "no existe" in result.output.lower()


def test_diff_subcommand_never_writes(
    source_root: Path, canonical_root: Path
) -> None:
    target = canonical_root / "prompts" / "analisis-servicio.md"
    target.write_text(FM_CANONICAL, encoding="utf-8")
    original = target.read_text(encoding="utf-8")
    (source_root / "pre-migracion" / "01-analisis-servicio.md").write_text(
        BODY_SOURCE_UPDATED, encoding="utf-8"
    )

    result = runner.invoke(
        canonical_cmd.app,
        ["diff", "--source", str(source_root)],
    )
    assert result.exit_code == 0
    assert target.read_text(encoding="utf-8") == original
