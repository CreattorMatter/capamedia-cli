"""Tests for `capamedia discovery` support."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook

from capamedia_cli.core.discovery import (
    initial_repo_tasks,
    read_discovery_rows,
    run_discovery,
    scan_repo,
)

DISCOVERY_HEADERS = [
    "Servicios",
    "Responsable",
    "Complejidad",
    "Observaciones",
    "Observación Discovery",
    "LINK WSDL",
    "LINK CODIGO",
    "# Integraciones",
    "Integraciones / Consume",
    "Nuevo nombre",
    "Descripción / Funcionalidad",
    "TRIBU",
    "ACRONIMO",
    "Tecnologia",
    "Tipo",
    "Tecnologia del backend",
    "Tecnologia para despliegue de servicio migrado",
    "Protocolos de consumo",
    "Cache Adicional al config",
    "Archivo o servicio de donde obtiene informacion para cache",
    "Interacción con proveedores externos",
    "Metodos que expone",
    "OLA",
    "Consumen tecnologia deprecada",
]


def _write_discovery_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Discovery"
    ws.append(DISCOVERY_HEADERS)
    ws.append(
        [
            "WSClientes0007",
            "Sebas",
            "Medio",
            "",
            "Revisar backend WSClientes0045",
            "https://dev.azure.com/BancoPichinchaEC/adi/_git/wsdl",
            "sqb-msa-wsclientes0007 - Repos",
            "2",
            (
                "UMPClientes0002 -> ConsultarInformacionBasica01 -> TX060480\n"
                "WSClientes0045 -> Consulta externa\n"
                "jndi.clientes.riesgo.01 / BDD: SRVPPRD\n"
            ),
            "tnd-msa-sp-wsclientes0007",
            "Consulta contacto",
            "TRIBU",
            "tnd",
            "Bus Omnicanalidad",
            "WS",
            "TXT BANCS",
            "ON-PREMISE",
            "SOAP",
            "Ninguna",
            "",
            "https://api.equifax.com/v2/score",
            "ConsultarContactoTransaccional01",
            "1",
            "",
        ]
    )
    ws.append(
        [
            "WSTecnicos0036",
            "",
            "Alto",
            "",
            "",
            "",
            "ws-wstecnicos0036-was - Repos",
            "1",
            "UMPTecnicos0031 --> BDD: PPOMNICA / ESQUEMA: CATALOGA",
            "tnd-msa-sp-wstecnicos0036",
            "",
            "",
            "tnd",
            "Was Omnicanalidad",
            "WS",
            "BDD PPOMNICA",
            "ON-PREMISE",
            "SOAP",
            "Persiste catalogo en cache",
            "PPOMNICA.CATALOGA.OMN_CAT_MAESTRO",
            "Ninguno",
            "ConsultarDetalleTransaccionDelay01",
            "1",
            "",
        ]
    )
    wb.save(path)


def test_read_discovery_rows_extracts_dependencies(tmp_path: Path) -> None:
    xlsx = tmp_path / "SERVICIOS.xlsx"
    _write_discovery_workbook(xlsx)

    sheet, rows = read_discovery_rows(xlsx)

    assert sheet == "Discovery"
    assert len(rows) == 2
    first = rows[0]
    assert first.service == "WSClientes0007"
    assert first.legacy_repo == "sqb-msa-wsclientes0007"
    assert first.migration_repo == "tnd-msa-sp-wsclientes0007"
    assert "UMPClientes0002" in first.excel_umps
    assert "060480" in first.excel_txs
    assert "WSClientes0045" in first.excel_downstream_services
    assert "jndi.clientes.riesgo.01" in first.excel_jndi
    assert "api.equifax.com" in first.excel_external_domains


def test_initial_repo_tasks_dedupes_service_ump_and_tx(tmp_path: Path) -> None:
    xlsx = tmp_path / "SERVICIOS.xlsx"
    _write_discovery_workbook(xlsx)
    _, rows = read_discovery_rows(xlsx)

    tasks = initial_repo_tasks(rows, tmp_path / "OLA1")
    repos = {task.repo_name for task in tasks}

    assert "sqb-msa-wsclientes0007" in repos
    assert "ws-wstecnicos0036-was" in repos
    assert "sqb-msa-umpclientes0002" in repos
    assert "sqb-cfg-060480-TX" in repos


def test_scan_repo_finds_config_without_secret_values(tmp_path: Path) -> None:
    repo = tmp_path / "sqb-msa-wsclientes0007"
    repo.mkdir()
    (repo / "app.properties").write_text(
        "service.url=https://api.equifax.com/v2/score\n"
        "db.password=super-secret\n"
        "jndi.name=jndi.clientes.riesgo.01\n",
        encoding="utf-8",
    )
    (repo / "flow.esql").write_text(
        "SET Environment.UMPSubflow.ump = 'UMPClientes0002';\n"
        "SET transactionId = '060480';\n",
        encoding="utf-8",
    )

    scan = scan_repo("sqb-msa-wsclientes0007", repo)

    assert "UMPClientes0002" in scan.umps
    assert "060480" in scan.txs
    assert "app.properties" in scan.property_files
    assert "db.password" in scan.secret_keys
    assert "super-secret" not in scan.secret_keys
    assert "api.equifax.com" in scan.external_domains


def test_run_discovery_no_clone_generates_report(tmp_path: Path) -> None:
    xlsx = tmp_path / "SERVICIOS.xlsx"
    _write_discovery_workbook(xlsx)

    result = run_discovery(
        name="OLA1",
        workbook_path=xlsx,
        root=tmp_path,
        clone=False,
        workers=1,
    )

    assert result.output_dir == tmp_path / "OLA1"
    assert result.report_path.exists()
    assert any(repo.status == "skipped" for repo in result.repo_results)

    wb = load_workbook(result.report_path, read_only=True)
    assert {"Resumen", "Servicios", "Dependencias", "Repos", "Caveats", "Repo Scan"}.issubset(
        set(wb.sheetnames)
    )
