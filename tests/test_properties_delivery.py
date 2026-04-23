"""Tests para properties_delivery (v0.21.0): audit + autofix inject."""

from __future__ import annotations

from pathlib import Path

import yaml

from capamedia_cli.core.properties_delivery import (
    audit_properties_delivery,
    inject_delivered_properties,
)


def _write_report(workspace: Path, report: dict) -> None:
    (workspace / ".capamedia").mkdir(parents=True, exist_ok=True)
    (workspace / ".capamedia" / "properties-report.yaml").write_text(
        yaml.safe_dump(report, sort_keys=False), encoding="utf-8"
    )


def _minimal_report(file_name: str, keys: list[str]) -> dict:
    return {
        "generated_by": "capamedia clone",
        "service_specific_properties": [
            {
                "file": file_name,
                "status": "PENDING_FROM_BANK",
                "source": "service",
                "keys_used": keys,
            }
        ],
    }


# ---------------------------------------------------------------------------
# audit_properties_delivery
# ---------------------------------------------------------------------------


def test_audit_report_missing_yields_empty(tmp_path: Path) -> None:
    """Sin properties-report.yaml, audit retorna report_missing=True."""
    audit = audit_properties_delivery(tmp_path)
    assert audit.report_missing is True
    assert audit.files == []


def test_audit_still_pending_when_no_input_file(tmp_path: Path) -> None:
    """Archivo declarado en reporte pero no en disco -> STILL_PENDING."""
    _write_report(tmp_path, _minimal_report("wsclientes0076.properties", ["KEY1", "KEY2"]))
    audit = audit_properties_delivery(tmp_path)
    assert len(audit.files) == 1
    f = audit.files[0]
    assert f.status == "STILL_PENDING"
    assert f.keys_declared == ["KEY1", "KEY2"]
    assert f.delivered_path is None


def test_audit_delivered_when_all_keys_present_in_canonical_path(tmp_path: Path) -> None:
    """Archivo en .capamedia/inputs/ con todas las keys -> DELIVERED."""
    _write_report(tmp_path, _minimal_report("wsclientes0076.properties", ["KEY1", "KEY2"]))
    inputs = tmp_path / ".capamedia" / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "wsclientes0076.properties").write_text(
        "KEY1=value1\nKEY2=value2\n", encoding="utf-8",
    )

    audit = audit_properties_delivery(tmp_path)
    f = audit.files[0]
    assert f.status == "DELIVERED"
    assert f.values == {"KEY1": "value1", "KEY2": "value2"}
    assert f.keys_missing == []


def test_audit_partial_when_some_keys_missing(tmp_path: Path) -> None:
    """Archivo en disco pero sin todas las keys -> PARTIAL."""
    _write_report(tmp_path, _minimal_report("a.properties", ["K1", "K2", "K3"]))
    inputs = tmp_path / ".capamedia" / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "a.properties").write_text("K1=v1\nK2=v2\n", encoding="utf-8")

    audit = audit_properties_delivery(tmp_path)
    f = audit.files[0]
    assert f.status == "PARTIAL"
    assert f.keys_missing == ["K3"]
    assert "K3" not in f.values


def test_audit_cascade_workspace_root_fallback(tmp_path: Path) -> None:
    """Si no esta en .capamedia/inputs/, busca en raiz del workspace."""
    _write_report(tmp_path, _minimal_report("ws.properties", ["K1"]))
    (tmp_path / "ws.properties").write_text("K1=v1\n", encoding="utf-8")

    audit = audit_properties_delivery(tmp_path)
    assert audit.files[0].status == "DELIVERED"


def test_audit_cascade_inputs_without_capamedia(tmp_path: Path) -> None:
    """Cascade: <workspace>/inputs/<file> (sin .capamedia/)."""
    _write_report(tmp_path, _minimal_report("ws.properties", ["K1"]))
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "ws.properties").write_text("K1=v1\n", encoding="utf-8")

    audit = audit_properties_delivery(tmp_path)
    assert audit.files[0].status == "DELIVERED"


def test_audit_cascade_legacy_inline_fallback(tmp_path: Path) -> None:
    """Fallback recursivo en legacy/ si el owner lo dejo inline."""
    _write_report(tmp_path, _minimal_report("inline.properties", ["K1"]))
    legacy_dir = tmp_path / "legacy" / "ws-xxx-was" / "src" / "main" / "resources"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "inline.properties").write_text("K1=legacy_value\n", encoding="utf-8")

    audit = audit_properties_delivery(tmp_path)
    f = audit.files[0]
    assert f.status == "DELIVERED"
    assert f.values["K1"] == "legacy_value"


def test_audit_skip_non_pending_entries(tmp_path: Path) -> None:
    """Entries con status SHARED_CATALOG o SAMPLE_IN_REPO -> NOT_PENDING (no audit)."""
    report = {
        "service_specific_properties": [
            {
                "file": "shared.properties",
                "status": "SHARED_CATALOG",
                "source": "bank-shared-catalog",
                "keys_used": ["X"],
            },
        ],
    }
    _write_report(tmp_path, report)
    audit = audit_properties_delivery(tmp_path)
    assert audit.files[0].status == "NOT_PENDING"
    assert audit.has_pending is False


def test_audit_has_pending_property(tmp_path: Path) -> None:
    _write_report(tmp_path, _minimal_report("x.properties", ["K"]))
    audit = audit_properties_delivery(tmp_path)
    assert audit.has_pending is True
    assert audit.has_delivered is False


def test_audit_tolerates_malformed_yaml(tmp_path: Path) -> None:
    (tmp_path / ".capamedia").mkdir()
    (tmp_path / ".capamedia" / "properties-report.yaml").write_text(
        "[[[ not valid yaml", encoding="utf-8",
    )
    audit = audit_properties_delivery(tmp_path)
    assert audit.report_missing is True


# ---------------------------------------------------------------------------
# inject_delivered_properties
# ---------------------------------------------------------------------------


def test_inject_replaces_ccc_placeholder_with_literal(tmp_path: Path) -> None:
    """URL_XML delivered -> ${CCC_TX_ATTRIBUTES_XML_PATH} reemplazado por literal."""
    _write_report(tmp_path, _minimal_report("umpclientes0025.properties", ["URL_XML"]))
    inputs = tmp_path / ".capamedia" / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "umpclientes0025.properties").write_text(
        "URL_XML=/apps/proy/conf/attrs.xml\n",
        encoding="utf-8",
    )

    project = tmp_path / "destino" / "tpr-msa-sp-x"
    yml_dir = project / "src" / "main" / "resources"
    yml_dir.mkdir(parents=True)
    (yml_dir / "application.yml").write_text(
        "transaction-attributes:\n  xml-path: ${CCC_TX_ATTRIBUTES_XML_PATH}\n",
        encoding="utf-8",
    )

    audit = audit_properties_delivery(tmp_path)
    report = inject_delivered_properties(audit, project)

    assert report.total_replacements == 1
    content = (yml_dir / "application.yml").read_text(encoding="utf-8")
    assert '"/apps/proy/conf/attrs.xml"' in content
    assert "${CCC_TX_ATTRIBUTES_XML_PATH}" not in content


def test_inject_replaces_placeholder_with_default(tmp_path: Path) -> None:
    """${CCC_X:default} tambien se reemplaza por el valor literal."""
    _write_report(tmp_path, _minimal_report("f.properties", ["URL_XML"]))
    inputs = tmp_path / ".capamedia" / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "f.properties").write_text("URL_XML=/real/path.xml\n", encoding="utf-8")

    project = tmp_path / "destino" / "p"
    (project / "src" / "main" / "resources").mkdir(parents=True)
    (project / "src" / "main" / "resources" / "application.yml").write_text(
        "x: ${CCC_TX_ATTRIBUTES_XML_PATH:/fallback/default.xml}\n",
        encoding="utf-8",
    )

    audit = audit_properties_delivery(tmp_path)
    report = inject_delivered_properties(audit, project)

    assert report.total_replacements == 1
    content = (project / "src" / "main" / "resources" / "application.yml").read_text(
        encoding="utf-8"
    )
    assert '"/real/path.xml"' in content


def test_inject_skips_partial_files(tmp_path: Path) -> None:
    """PARTIAL files no se inyectan (evita mezclar reales + placeholders)."""
    _write_report(tmp_path, _minimal_report("x.properties", ["URL_XML", "RECURSO"]))
    inputs = tmp_path / ".capamedia" / "inputs"
    inputs.mkdir(parents=True)
    # Solo 1 de 2 keys -> PARTIAL
    (inputs / "x.properties").write_text("URL_XML=/path.xml\n", encoding="utf-8")

    project = tmp_path / "destino" / "p"
    (project / "src" / "main" / "resources").mkdir(parents=True)
    yml = project / "src" / "main" / "resources" / "application.yml"
    yml.write_text(
        "x: ${CCC_TX_ATTRIBUTES_XML_PATH}\n",
        encoding="utf-8",
    )

    audit = audit_properties_delivery(tmp_path)
    assert audit.files[0].status == "PARTIAL"
    report = inject_delivered_properties(audit, project)

    # PARTIAL no inyecta
    assert report.total_replacements == 0
    assert "${CCC_TX_ATTRIBUTES_XML_PATH}" in yml.read_text(encoding="utf-8")


def test_inject_handles_multiple_yml_files(tmp_path: Path) -> None:
    """application-dev.yml, application-prod.yml - todos se actualizan."""
    _write_report(tmp_path, _minimal_report("x.properties", ["URL_XML"]))
    (tmp_path / ".capamedia" / "inputs").mkdir(parents=True)
    (tmp_path / ".capamedia" / "inputs" / "x.properties").write_text(
        "URL_XML=/common/path.xml\n", encoding="utf-8",
    )

    project = tmp_path / "destino" / "p"
    resources = project / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "application.yml").write_text(
        "x: ${CCC_TX_ATTRIBUTES_XML_PATH}\n", encoding="utf-8",
    )
    (resources / "application-dev.yml").write_text(
        "x: ${CCC_TX_ATTRIBUTES_XML_PATH}\n", encoding="utf-8",
    )
    (resources / "application-prod.yml").write_text(
        "x: ${CCC_TX_ATTRIBUTES_XML_PATH}\n", encoding="utf-8",
    )

    audit = audit_properties_delivery(tmp_path)
    report = inject_delivered_properties(audit, project)

    assert report.total_replacements == 3
    assert len(report.files_modified) == 3


def test_inject_noop_when_no_delivered_files(tmp_path: Path) -> None:
    """Si todos los archivos son STILL_PENDING, no se inyecta nada."""
    _write_report(tmp_path, _minimal_report("pending.properties", ["K"]))
    project = tmp_path / "destino" / "p"
    (project / "src" / "main" / "resources").mkdir(parents=True)

    audit = audit_properties_delivery(tmp_path)
    assert audit.files[0].status == "STILL_PENDING"
    report = inject_delivered_properties(audit, project)
    assert report.total_replacements == 0


def test_inject_returns_empty_when_no_yml_files(tmp_path: Path) -> None:
    """Si no hay application.yml en el destino, retorna sin errores."""
    _write_report(tmp_path, _minimal_report("x.properties", ["URL_XML"]))
    (tmp_path / ".capamedia" / "inputs").mkdir(parents=True)
    (tmp_path / ".capamedia" / "inputs" / "x.properties").write_text(
        "URL_XML=/v.xml\n", encoding="utf-8",
    )
    project = tmp_path / "destino" / "empty"
    project.mkdir(parents=True)

    audit = audit_properties_delivery(tmp_path)
    report = inject_delivered_properties(audit, project)
    assert report.total_replacements == 0
    assert report.files_modified == []
