from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_vendor_validator():
    path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "capamedia_cli"
        / "data"
        / "vendor"
        / "validate_hexagonal.py"
    )
    spec = importlib.util.spec_from_file_location("vendor_validate_hexagonal", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_wsdl(path: Path, *, operations: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ops = "\n".join(f'<wsdl:operation name="op{i}"/>' for i in range(operations))
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" '
        'targetNamespace="http://example.com">\n'
        '<wsdl:portType name="SvcPort">\n'
        f"{ops}\n"
        "</wsdl:portType>\n"
        "</definitions>\n",
        encoding="utf-8",
    )


def _write_webflux_build(project: Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "build.gradle").write_text(
        "dependencies { implementation 'org.springframework.boot:spring-boot-starter-webflux' }\n",
        encoding="utf-8",
    )


def _write_fabrics_metadata(workspace: Path, *, invoca_bancs: bool) -> None:
    capamedia = workspace / ".capamedia"
    capamedia.mkdir(parents=True, exist_ok=True)
    (capamedia / "fabrics.json").write_text(
        json.dumps(
            {
                "source_kind": "iib",
                "tecnologia": "bus",
                "invoca_bancs": str(invoca_bancs).lower(),
                "operation_count": "2",
                "project_type": "rest",
                "web_framework": "webflux",
            }
        ),
        encoding="utf-8",
    )


def test_vendor_validator_allows_bus_bancs_multi_op_webflux(tmp_path: Path) -> None:
    validator = _load_vendor_validator()
    workspace = tmp_path / "wstecnicos0006"
    project = workspace / "destino" / "tnd-msa-sp-wstecnicos0006"
    _write_webflux_build(project)
    _write_wsdl(project / "src" / "main" / "resources" / "legacy" / "svc.wsdl", operations=2)
    _write_fabrics_metadata(workspace, invoca_bancs=True)

    results = validator.check_wsdl(project)

    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].warning is False
    assert "invocaBancs=true" in results[0].message


def test_vendor_validator_keeps_multi_op_soap_rule_without_bancs(tmp_path: Path) -> None:
    validator = _load_vendor_validator()
    workspace = tmp_path / "wstecnicos0006"
    project = workspace / "destino" / "tnd-msa-sp-wstecnicos0006"
    _write_webflux_build(project)
    _write_wsdl(project / "src" / "main" / "resources" / "legacy" / "svc.wsdl", operations=2)
    _write_fabrics_metadata(workspace, invoca_bancs=False)

    results = validator.check_wsdl(project)

    assert len(results) == 1
    assert results[0].passed is False
    assert "se esperaba SOAP + MVC" in results[0].message
