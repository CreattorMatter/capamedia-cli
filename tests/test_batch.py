"""Tests para el modulo batch."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.commands.batch import (
    BatchRow,
    _read_services_file,
    _write_csv_report,
    _write_markdown_report,
)


def test_read_services_file_ignores_comments(tmp_path: Path) -> None:
    f = tmp_path / "services.txt"
    f.write_text(
        "# Comentario inicial\n"
        "wsclientes0007\n"
        "\n"
        "# otro\n"
        "wsclientes0030 # inline\n"
        "   wsclientes0013   \n",
        encoding="utf-8",
    )
    result = _read_services_file(f)
    assert result == ["wsclientes0007", "wsclientes0030", "wsclientes0013"]


def test_read_services_file_missing_raises(tmp_path: Path) -> None:
    import typer
    try:
        _read_services_file(tmp_path / "notfound.txt")
        raise AssertionError("expected typer.BadParameter")
    except typer.BadParameter:
        pass


def test_write_markdown_report_has_summary(tmp_path: Path) -> None:
    rows = [
        BatchRow("svc1", "ok", "", {"ops": "1", "framework": "REST"}),
        BatchRow("svc2", "fail", "clone error", {}),
        BatchRow("svc3", "ok", "", {"ops": "2", "framework": "SOAP"}),
    ]
    dest = _write_markdown_report("complexity", rows, tmp_path, ["ops", "framework"])
    content = dest.read_text(encoding="utf-8")
    assert "Batch `complexity`" in content
    assert "**OK:** 2" in content
    assert "**FAIL:** 1" in content
    assert "svc1" in content and "svc2" in content


def test_write_csv_report_has_header_and_rows(tmp_path: Path) -> None:
    rows = [
        BatchRow("svc1", "ok", "", {"ops": "1"}),
        BatchRow("svc2", "ok", "", {"ops": "2"}),
    ]
    dest = _write_csv_report("complexity", rows, tmp_path, ["ops"])
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "service,status,detail,ops"
    assert len(lines) == 3


def test_batch_row_default_fields() -> None:
    r = BatchRow("svc", "ok", "", {})
    assert r.service == "svc"
    assert r.status == "ok"
    assert r.fields == {}
