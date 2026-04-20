"""Tests for the deterministic checklist rules."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import (
    CheckContext,
    run_block_1,
    run_block_14,
    run_block_7,
)


def _make_migrated(tmp_path: Path) -> Path:
    """Create a minimal migrated project layout for tests."""
    root = tmp_path / "migrated"
    (root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "domain").mkdir(parents=True)
    (root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "application").mkdir(parents=True)
    (root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "infrastructure").mkdir(parents=True)
    (root / "src" / "main" / "resources").mkdir(parents=True)
    return root


def test_block_1_passes_with_all_layers(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    layer_check = [r for r in results if r.id == "1.1"][0]
    assert layer_check.status == "pass"


def test_block_1_fails_if_domain_imports_spring(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    bad = root / "src/main/java/com/pichincha/sp/domain/Bad.java"
    bad.write_text(
        "package com.pichincha.sp.domain;\n"
        "import org.springframework.stereotype.Component;\n"
        "public class Bad {}\n",
        encoding="utf-8",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = [r for r in results if r.id == "1.2"][0]
    assert check.status == "fail"
    assert check.severity == "high"


def test_block_7_detects_hardcoded_password(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    yml = root / "src/main/resources/application.yml"
    yml.write_text(
        "spring:\n"
        "  datasource:\n"
        "    password: my-secret-hardcoded\n",
        encoding="utf-8",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    secret_check = [r for r in results if r.id == "7.2"][0]
    assert secret_check.status == "fail"


def test_block_7_passes_with_env_var(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    yml = root / "src/main/resources/application.yml"
    yml.write_text(
        "spring:\n"
        "  datasource:\n"
        "    password: ${CCC_DB_PASSWORD}\n",
        encoding="utf-8",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    secret_check = [r for r in results if r.id == "7.2"][0]
    assert secret_check.status == "pass"


def test_block_14_detects_placeholder_projectkey(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    sonarlint_dir = root / ".sonarlint"
    sonarlint_dir.mkdir()
    (sonarlint_dir / "connectedMode.json").write_text(
        '{"sonarCloudOrganization": "bancopichinchaec", "projectKey": "<PROJECT_KEY_FROM_SONARCLOUD>"}',
        encoding="utf-8",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_14(ctx)
    key_check = [r for r in results if r.id == "14.3"][0]
    assert key_check.status == "fail"


def test_block_14_passes_with_real_projectkey(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    sonarlint_dir = root / ".sonarlint"
    sonarlint_dir.mkdir()
    (sonarlint_dir / "connectedMode.json").write_text(
        '{"sonarCloudOrganization": "bancopichinchaec", "projectKey": "69ac437e-c29a-4734-9b62-dbdeb572e01b"}',
        encoding="utf-8",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_14(ctx)
    key_check = [r for r in results if r.id == "14.3"][0]
    assert key_check.status == "pass"


def test_block_14_fails_with_wrong_organization(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    sonarlint_dir = root / ".sonarlint"
    sonarlint_dir.mkdir()
    (sonarlint_dir / "connectedMode.json").write_text(
        '{"sonarCloudOrganization": "wrong-org", "projectKey": "abc123"}',
        encoding="utf-8",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_14(ctx)
    org_check = [r for r in results if r.id == "14.2"][0]
    assert org_check.status == "fail"
