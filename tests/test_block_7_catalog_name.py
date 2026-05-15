"""Tests for Block 7.1c — catalog-info.yaml metadata.name pattern.

Regla 9 de bank-official-rules.md (linea 509): "metadata.name: <namespace>-msa-sp-<servicio>
(nombre real del componente, no el proyecto Azure)".

Bug detectado en wstecnicos0008 branch feature/dev-BTHCCC-5954 (2026-05):
    metadata:
      namespace: tct-middleware
      name: tpl-middleware        ← tpl-middleware es el PROYECTO Azure,
                                     no el componente.
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import CheckContext, run_block_7


def _make_project(tmp_path: Path, catalog_name: str) -> Path:
    root = tmp_path / "migrated"
    (root / "src" / "main" / "resources").mkdir(parents=True)
    (root / "src" / "main" / "resources" / "application.yml").write_text(
        "spring:\n  application:\n    name: test\n", encoding="utf-8"
    )
    (root / "catalog-info.yaml").write_text(
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Component\n"
        "metadata:\n"
        f"  name: {catalog_name}\n"
        "  namespace: tnd-middleware\n"
        "spec:\n"
        "  type: service\n",
        encoding="utf-8",
    )
    return root


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


def test_7_1c_azure_project_name_is_high(tmp_path: Path) -> None:
    """`name: tpl-middleware` (proyecto Azure) -> HIGH."""
    root = _make_project(tmp_path, catalog_name="tpl-middleware")

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.1c")

    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"
    assert "tpl-middleware" in check.detail


def test_7_1c_other_azure_project_name_is_high(tmp_path: Path) -> None:
    """`name: tpl-bus-omnicanal` (otro proyecto Azure conocido) -> HIGH."""
    root = _make_project(tmp_path, catalog_name="tpl-bus-omnicanal")

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.1c")

    assert check.status == "fail"
    assert check.severity == "high"


def test_7_1c_pattern_mismatch_is_high(tmp_path: Path) -> None:
    """`name` que no matchea `<ns>-msa-sp-<svc>` -> HIGH."""
    root = _make_project(tmp_path, catalog_name="wsclientes0011-migrated")

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.1c")

    assert check.status == "fail"
    assert check.severity == "high"
    assert "no matchea" in check.detail.lower()


def test_7_1c_canonical_name_passes(tmp_path: Path) -> None:
    """`tnd-msa-sp-wsclientes0011` -> PASS."""
    root = _make_project(tmp_path, catalog_name="tnd-msa-sp-wsclientes0011")

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.1c")

    assert check.status == "pass"


def test_7_1c_supports_other_namespace_prefixes(tmp_path: Path) -> None:
    """Soporta cualquier prefijo de 3 letras: tct, csg, tia, tpr, tmp, etc."""
    for ns in ("tct", "csg", "tia", "tpr", "tmp", "bpe"):
        root_for_ns = tmp_path / ns
        root_for_ns.mkdir()
        root = _make_project(root_for_ns, catalog_name=f"{ns}-msa-sp-wstecnicos0008")
        ctx = CheckContext(migrated_path=root, legacy_path=None)
        results = run_block_7(ctx)
        check = _find(results, "7.1c")
        assert check.status == "pass", f"ns={ns} should pass"


def test_7_1c_no_catalog_skips(tmp_path: Path) -> None:
    """Sin catalog-info.yaml el check no se emite."""
    root = tmp_path / "no-catalog"
    (root / "src" / "main" / "resources").mkdir(parents=True)
    (root / "src" / "main" / "resources" / "application.yml").write_text(
        "spring:\n  application:\n    name: x\n", encoding="utf-8"
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.1c")
    assert check is None
