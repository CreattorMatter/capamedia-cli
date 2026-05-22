"""Tests for Block 2 log coverage.

Cubre:
- 2.8: cobertura de log INFO en componentes clave
- 2.9: cobertura de log DEBUG en componentes clave
"""

from __future__ import annotations

from pathlib import Path
from capamedia_cli.core.checklist_rules import CheckContext, run_block_2


def _make_migrated(tmp_path: Path) -> Path:
    root = tmp_path / "migrated"
    base = root / "src" / "main" / "java" / "com" / "pichincha" / "sp"
    (base / "infrastructure" / "input" / "adapter" / "rest" / "impl").mkdir(parents=True)
    return root


def _write_java(root: Path, relative: str, body: str) -> Path:
    f = root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / relative
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    return f


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


def test_2_8_and_2_9_fails_when_logs_missing(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/rest/impl/CustomerController.java",
        """
        package com.pichincha.sp.infrastructure.input.adapter.rest.impl;
        public class CustomerController {
            public void execute() {
                # only error/warn logs or no logs at all
                log.error("some error");
            }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_2(ctx)

    check_info = _find(results, "2.8")
    check_debug = _find(results, "2.9")

    assert check_info is not None
    assert check_info.status == "fail"
    assert "Falta log INFO" in check_info.detail
    assert check_info.severity == "info"

    assert check_debug is not None
    assert check_debug.status == "fail"
    assert "Falta log DEBUG" in check_debug.detail
    assert check_debug.severity == "info"


def test_2_8_and_2_9_passes_when_logs_present(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    _write_java(
        root,
        "infrastructure/input/adapter/rest/impl/CustomerController.java",
        """
        package com.pichincha.sp.infrastructure.input.adapter.rest.impl;
        public class CustomerController {
            public void execute() {
                log.info("Starting processing...");
                log.debug("Debug mapping details");
            }
        }
        """,
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_2(ctx)

    check_info = _find(results, "2.8")
    check_debug = _find(results, "2.9")

    assert check_info is not None
    assert check_info.status == "pass"

    assert check_debug is not None
    assert check_debug.status == "pass"
