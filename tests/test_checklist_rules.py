"""Tests for the deterministic checklist rules."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from openpyxl import Workbook

from capamedia_cli.core.checklist_rules import (
    CheckContext,
    run_block_0,
    run_block_1,
    run_block_7,
    run_block_13,
    run_block_14,
    run_block_15,
    run_block_21,
    run_block_22,
)
from capamedia_cli.core.discovery import DISCOVERY_WORKBOOK_NAME
from capamedia_cli.core.gitignore_policy import format_deployment_gitignore_block


def _make_migrated(tmp_path: Path) -> Path:
    """Create a minimal migrated project layout for tests."""
    root = tmp_path / "migrated"
    (root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "domain").mkdir(parents=True)
    (root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "application").mkdir(parents=True)
    (root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "infrastructure").mkdir(parents=True)
    (root / "src" / "main" / "resources").mkdir(parents=True)
    return root


def _make_discovery_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Validacion de servicios"
    ws.append(
        [
            "Servicio",
            "Nuevo nombre",
            "TRIBU",
            "ACRONIMO",
            "Tecnologia",
            "Tipo",
            "Integraciones / Consume",
            "Cache Adicional al config",
            "Archivo o servicio de donde obtiene informacion para cache",
            "Interaccion con proveedores externos",
            "Metodos que expone",
            "Peso del servicio",
            "Complejidad del servicio",
            "Observacion Discovery",
            "LINK WSDL",
            "LINK CODIGO",
            "Consumen tecnologia deprecada",
            "Peso",
        ]
    )
    ws.append(
        [
            "WSClientes0028",
            "tnd-msa-sp-wsclientes0028",
            "TRIBU",
            "tnd",
            "Bus Omnicanalidad",
            "WS",
            "UMPClientes0020 -> TX067050",
            "",
            "",
            "",
            "ActualizarEmailLocalizacion33",
            "13",
            "Bajo",
            "Validar las descripciones de las tx.",
            "specs",
            "code",
            "",
            "Alta",
        ]
    )
    ws["O2"].hyperlink = (
        "https://dev.azure.com/BancoPichinchaEC/adi-especificaciones-tecnicas/"
        "_git/adi-doc-tecspec-tribu-integracion-apis?path=/sp%20-%20Soporte/"
        "tnd-msa-sp-wsclientes0028"
    )
    ws["P2"].hyperlink = (
        "https://dev.azure.com/BancoPichinchaEC/tpl-bus-omnicanal/"
        "_git/sqb-msa-wsclientes0028"
    )
    wb.save(path)


def _by_id(results, check_id: str):
    return next(r for r in results if r.id == check_id)


def test_block_1_passes_with_all_layers(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    layer_check = _by_id(results, "1.1")
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
    check = _by_id(results, "1.2")
    assert check.status == "fail"
    assert check.severity == "high"


def test_block_1_warns_on_legacy_port_layout_for_peer_review(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    legacy_output_port = (
        root
        / "src"
        / "main"
        / "java"
        / "com"
        / "pichincha"
        / "sp"
        / "application"
        / "port"
        / "output"
        / "ClienteOutputPort.java"
    )
    legacy_output_port.parent.mkdir(parents=True, exist_ok=True)
    legacy_output_port.write_text(
        "package com.pichincha.sp.application.port.output;\n"
        "public interface ClienteOutputPort {}\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = _by_id(results, "1.3b")

    assert check.status == "fail"
    assert check.severity == "medium"
    assert "application/input/port" in check.suggested_fix


def test_block_1_accepts_canonical_peer_review_port_layout(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    canonical_output_port = (
        root
        / "src"
        / "main"
        / "java"
        / "com"
        / "pichincha"
        / "sp"
        / "application"
        / "output"
        / "port"
        / "ClienteOutputPort.java"
    )
    canonical_output_port.parent.mkdir(parents=True, exist_ok=True)
    canonical_output_port.write_text(
        "package com.pichincha.sp.application.output.port;\n"
        "public interface ClienteOutputPort {}\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = _by_id(results, "1.3b")

    assert check.status == "pass"


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
    secret_check = _by_id(results, "7.2")
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
    secret_check = _by_id(results, "7.2")
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
    key_check = _by_id(results, "14.3")
    assert key_check.status == "fail"


def test_block_14_passes_with_real_projectkey(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    sonarlint_dir = root / ".sonarlint"
    sonarlint_dir.mkdir()
    (sonarlint_dir / "connectedMode.json").write_text(
        '{"sonarCloudOrganization": "bancopichinchaec", "projectKey": "69ac437e-c29a-4734-9b62-dbdeb572e01b"}',
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(format_deployment_gitignore_block() + "\n", encoding="utf-8")
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_14(ctx)
    key_check = _by_id(results, "14.3")
    assert key_check.status == "pass"
    ignore_check = _by_id(results, "14.4")
    assert ignore_check.status == "pass"
    hygiene_check = _by_id(results, "14.6")
    assert hygiene_check.status == "pass"


def test_block_14_fails_when_deployment_gitignore_entries_missing(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    sonarlint_dir = root / ".sonarlint"
    sonarlint_dir.mkdir()
    (sonarlint_dir / "connectedMode.json").write_text(
        '{"sonarCloudOrganization": "bancopichinchaec", "projectKey": "69ac437e-c29a-4734-9b62-dbdeb572e01b"}',
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(".gradle/\nbuild/\n", encoding="utf-8")

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_14(ctx)

    hygiene_check = _by_id(results, "14.6")
    assert hygiene_check.status == "fail"
    assert hygiene_check.severity == "high"
    assert ".capamedia/" in hygiene_check.detail
    assert ".sonarlint/connectedMode.json" in hygiene_check.suggested_fix


def test_block_14_fails_when_sonarlint_binding_is_gitignored(tmp_path: Path, monkeypatch) -> None:
    root = _make_migrated(tmp_path)
    sonarlint_dir = root / ".sonarlint"
    sonarlint_dir.mkdir()
    (sonarlint_dir / "connectedMode.json").write_text(
        '{"sonarCloudOrganization": "bancopichinchaec", "projectKey": "69ac437e-c29a-4734-9b62-dbdeb572e01b"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "capamedia_cli.core.checklist_rules.subprocess.run",
        Mock(return_value=Mock(returncode=0)),
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_14(ctx)

    ignore_check = _by_id(results, "14.4")
    assert ignore_check.status == "fail"
    assert ignore_check.severity == "medium"


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
    org_check = _by_id(results, "14.2")
    assert org_check.status == "fail"


def test_block_0_rejects_bancs_artifacts_for_was(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    resources = root / "src/main/resources"
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "WSClientes0154.wsdl").write_text(
        '<definitions xmlns="http://schemas.xmlsoap.org/wsdl/">'
        '<portType name="P"><operation name="op"/></portType></definitions>',
        encoding="utf-8",
    )
    controller = (
        root
        / "src/main/java/com/pichincha/sp/infrastructure/input/adapter/rest/FooController.java"
    )
    controller.parent.mkdir(parents=True, exist_ok=True)
    controller.write_text(
        "package com.pichincha.sp.infrastructure.input.adapter.rest;\n"
        "import org.springframework.web.bind.annotation.RestController;\n"
        "@RestController class FooController {}\n",
        encoding="utf-8",
    )
    (root / "build.gradle").write_text(
        "dependencies { implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0' }\n",
        encoding="utf-8",
    )
    (root / "catalog-info.yaml").write_text(
        "spec:\n  dependsOn:\n    - component:lib-bnc-api-client\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was")
    results = run_block_0(ctx)
    check = _by_id(results, "0.2d")

    assert check.status == "fail"
    assert check.severity == "high"
    assert "BANCS no aplica" in check.detail


def test_block_0_allows_bancs_artifacts_for_iib_with_bancs(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    resources = root / "src/main/resources"
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "WSClientes0006.wsdl").write_text(
        '<definitions xmlns="http://schemas.xmlsoap.org/wsdl/">'
        '<portType name="P"><operation name="op"/></portType></definitions>',
        encoding="utf-8",
    )
    controller = (
        root
        / "src/main/java/com/pichincha/sp/infrastructure/input/adapter/rest/FooController.java"
    )
    controller.parent.mkdir(parents=True, exist_ok=True)
    controller.write_text(
        "package com.pichincha.sp.infrastructure.input.adapter.rest;\n"
        "import org.springframework.web.bind.annotation.RestController;\n"
        "@RestController class FooController {}\n",
        encoding="utf-8",
    )
    (root / "build.gradle").write_text(
        "dependencies { implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0' }\n",
        encoding="utf-8",
    )

    ctx = CheckContext(
        migrated_path=root,
        legacy_path=None,
        source_type="iib",
        has_bancs=True,
    )
    results = run_block_0(ctx)
    check = _by_id(results, "0.2d")

    assert check.status == "pass"


def test_block_13_requires_was_connection_test_query(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    (root / "build.gradle").write_text(
        "dependencies { implementation 'org.springframework.boot:spring-boot-starter-data-jpa' }\n",
        encoding="utf-8",
    )
    (root / "src/main/resources/application.yml").write_text(
        "spring:\n"
        "  datasource:\n"
        "    hikari:\n"
        "      maximum-pool-size: ${CCC_DB_POOL_MAX}\n"
        "  jpa:\n"
        "    hibernate:\n"
        "      ddl-auto: validate\n"
        "    open-in-view: false\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was")
    results = run_block_13(ctx)
    check = _by_id(results, "13.11")

    assert check.status == "fail"
    assert check.severity == "high"
    assert "connection-test-query: SELECT 1" in check.suggested_fix


def test_block_13_accepts_was_connection_test_query(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    (root / "build.gradle").write_text(
        "dependencies { implementation 'org.springframework.boot:spring-boot-starter-data-jpa' }\n",
        encoding="utf-8",
    )
    (root / "src/main/resources/application.yml").write_text(
        "spring:\n"
        "  datasource:\n"
        "    hikari:\n"
        "      maximum-pool-size: ${CCC_DB_POOL_MAX}\n"
        "      connection-test-query: SELECT 1\n"
        "  jpa:\n"
        "    hibernate:\n"
        "      ddl-auto: validate\n"
        "    open-in-view: false\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None, source_type="was")
    results = run_block_13(ctx)
    check = _by_id(results, "13.11")

    assert check.status == "pass"


def test_block_15_allows_empty_mensaje_negocio_slot(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    mapper = root / "src/main/java/com/pichincha/sp/infrastructure/ErrorMapper.java"
    mapper.write_text(
        "package com.pichincha.sp.infrastructure;\n"
        "class ErrorMapper { void map(Error e) { e.setMensajeNegocio(\"\"); } }\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)
    check = _by_id(results, "15.1")

    assert check.status == "pass"
    assert "aceptado" in check.detail


def test_block_15_rejects_real_mensaje_negocio_value(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    mapper = root / "src/main/java/com/pichincha/sp/infrastructure/ErrorMapper.java"
    mapper.write_text(
        "package com.pichincha.sp.infrastructure;\n"
        "class ErrorMapper { void map(Error e) { e.setMensajeNegocio(\"Cliente ok\"); } }\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_15(ctx)
    check = _by_id(results, "15.1")

    assert check.status == "fail"
    assert check.severity == "high"


def test_block_21_tx_mapping_passes_when_java_and_yaml_match(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    (root / "src/main/resources/application.yml").write_text(
        "bancs:\n  webclients:\n    ws-tx067050:\n      base-url: ${CCC_BANCS_BASE_URL}\n",
        encoding="utf-8",
    )
    adapter = root / "src/main/java/com/pichincha/sp/infrastructure/CustomerBancsAdapter.java"
    adapter.write_text(
        "package com.pichincha.sp.infrastructure;\n"
        "class CustomerBancsAdapter { static final String TRANSACTION_ID = \"067050\"; }\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None, has_bancs=True)
    results = run_block_21(ctx)
    check = _by_id(results, "21.1")

    assert check.status == "pass"


def test_block_21_tx_mapping_fails_when_java_and_yaml_differ(tmp_path: Path) -> None:
    root = _make_migrated(tmp_path)
    (root / "src/main/resources/application.yml").write_text(
        "bancs:\n  webclients:\n    ws-tx067050:\n      base-url: ${CCC_BANCS_BASE_URL}\n",
        encoding="utf-8",
    )
    adapter = root / "src/main/java/com/pichincha/sp/infrastructure/CustomerBancsAdapter.java"
    adapter.write_text(
        "package com.pichincha.sp.infrastructure;\n"
        "class CustomerBancsAdapter { void call() { request.transactionId(\"067051\"); } }\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None, has_bancs=True)
    results = run_block_21(ctx)
    check = _by_id(results, "21.1")

    assert check.status == "fail"
    assert check.severity == "high"
    assert "067050" in check.detail
    assert "067051" in check.detail


def test_block_22_fails_when_discovery_report_is_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "wsclientes0028"
    project = workspace / "destino" / "tnd-msa-sp-wsclientes0028"
    (project / "src/main/java").mkdir(parents=True)
    _make_discovery_workbook(workspace / DISCOVERY_WORKBOOK_NAME)

    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_22(ctx)
    check = _by_id(results, "22.1")

    assert check.status == "fail"
    assert check.severity == "high"
    assert "no hay" in check.detail


def test_block_22_fails_when_edge_case_coverage_is_pending(tmp_path: Path) -> None:
    workspace = tmp_path / "wsclientes0028"
    project = workspace / "destino" / "tnd-msa-sp-wsclientes0028"
    (project / "src/main/java").mkdir(parents=True)
    _make_discovery_workbook(workspace / DISCOVERY_WORKBOOK_NAME)
    (workspace / "COMPLEXITY_wsclientes0028.md").write_text(
        "## Discovery / edge cases\n"
        "- Spec path: /sp - Soporte/tnd-msa-sp-wsclientes0028\n"
        "- Code repo: sqb-msa-wsclientes0028\n"
        "DISCOVERY_EDGE_CASES:\n"
        "- edge_cases: tx_description_validation\n"
        "## Discovery edge-case coverage\n"
        "| tx_description_validation | PENDIENTE | <pendiente_validar> |\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_22(ctx)
    check = _by_id(results, "22.2")

    assert check.status == "fail"
    assert check.severity == "high"
    assert "tx_description_validation" in check.detail


def test_block_22_passes_when_edge_case_has_decision_and_file_trace(tmp_path: Path) -> None:
    workspace = tmp_path / "wsclientes0028"
    project = workspace / "destino" / "tnd-msa-sp-wsclientes0028"
    (project / "src/main/java").mkdir(parents=True)
    _make_discovery_workbook(workspace / DISCOVERY_WORKBOOK_NAME)
    (project / "MIGRATION_REPORT.md").write_text(
        "## Discovery / edge cases\n"
        "- Spec path: /sp - Soporte/tnd-msa-sp-wsclientes0028\n"
        "- Code repo: sqb-msa-wsclientes0028\n"
        "DISCOVERY_EDGE_CASES:\n"
        "- edge_cases: tx_description_validation\n"
        "## Discovery edge-case coverage\n"
        "| Codigo | Decision | Implementacion / test |\n"
        "|---|---|---|\n"
        "| tx_description_validation | Decision: implemented | "
        "File: src/test/java/CustomerAdapterTest.java |\n",
        encoding="utf-8",
    )

    ctx = CheckContext(migrated_path=project, legacy_path=None)
    results = run_block_22(ctx)
    report_check = _by_id(results, "22.1")
    coverage_check = _by_id(results, "22.2")

    assert report_check.status == "pass"
    assert coverage_check.status == "pass"
