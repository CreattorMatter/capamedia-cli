"""Tests for Block 7.1c - catalog-info.yaml metadata.name fixed value."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import CheckContext, run_block_7


def _make_project(
    tmp_path: Path,
    *,
    catalog_name: str,
    app_name: str = "tnd-msa-sp-wsclientes0011",
    namespace: str = "tnd-middleware",
) -> Path:
    root = tmp_path / app_name
    (root / "src" / "main" / "resources").mkdir(parents=True)
    (root / "src" / "main" / "resources" / "application.yml").write_text(
        "spring:\n"
        "  application:\n"
        f"    name: {app_name}\n",
        encoding="utf-8",
    )
    (root / "catalog-info.yaml").write_text(
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Component\n"
        "metadata:\n"
        f"  name: {catalog_name}\n"
        f"  namespace: {namespace}\n"
        "spec:\n"
        "  type: service\n",
        encoding="utf-8",
    )
    return root


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


def test_7_1c_tpl_middleware_passes(tmp_path: Path) -> None:
    root = _make_project(tmp_path, catalog_name="tpl-middleware")

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.1c")

    assert check is not None
    assert check.status == "pass"


def test_7_1c_component_name_is_high(tmp_path: Path) -> None:
    root = _make_project(tmp_path, catalog_name="tnd-msa-sp-wsclientes0011")

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.1c")

    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"
    assert "tpl-middleware" in check.detail


def test_7_1c_missing_name_is_high(tmp_path: Path) -> None:
    root = _make_project(tmp_path, catalog_name="")
    (root / "catalog-info.yaml").write_text(
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Component\n"
        "metadata:\n"
        "  namespace: tnd-middleware\n"
        "spec:\n"
        "  type: service\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.1c")

    assert check.status == "fail"
    assert check.severity == "high"


def test_7_1b_namespace_uses_component_name_not_catalog_name(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        catalog_name="tpl-middleware",
        app_name="csg-msa-sp-wsreglas0010",
        namespace="tnd-middleware",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.1b")

    assert check.status == "fail"
    assert "csg-middleware" in check.detail


def test_7_1c_no_catalog_skips(tmp_path: Path) -> None:
    root = tmp_path / "tnd-msa-sp-wsclientes0011"
    (root / "src" / "main" / "resources").mkdir(parents=True)
    (root / "src" / "main" / "resources" / "application.yml").write_text(
        "spring:\n  application:\n    name: tnd-msa-sp-wsclientes0011\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.1c")
    assert check is None
