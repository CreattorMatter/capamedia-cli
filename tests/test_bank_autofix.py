"""Tests para core/bank_autofix.py - autofixes de las 4 reglas deterministas
del script oficial validate_hexagonal.py."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.bank_autofix import (
    fix_add_bplogger_to_service,
    fix_add_libbnc_dependency,
    fix_catalog_info_scaffold,
    fix_yml_remove_defaults,
    run_bank_autofix,
)

# ---------------------------------------------------------------------------
# Regla 4 — @BpLogger
# ---------------------------------------------------------------------------


def test_bplogger_added_to_public_service_method(tmp_path: Path) -> None:
    svc_dir = tmp_path / "src" / "main" / "java" / "com" / "pichincha" / "sp" / "application" / "service"
    svc_dir.mkdir(parents=True)
    svc = svc_dir / "CustomerServiceImpl.java"
    svc.write_text(
        "package com.pichincha.sp.application.service;\n\n"
        "import org.springframework.stereotype.Service;\n"
        "import lombok.RequiredArgsConstructor;\n\n"
        "@Service\n"
        "@RequiredArgsConstructor\n"
        "public class CustomerServiceImpl {\n"
        "    public Mono<Customer> getCustomer(String id) {\n"
        "        return null;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    result = fix_add_bplogger_to_service(tmp_path)
    assert result.applied
    updated = svc.read_text(encoding="utf-8")
    assert "com.pichincha.common.trace.logger.annotation.BpLogger" in updated
    assert "@BpLogger" in updated


def test_bplogger_skipped_if_already_present(tmp_path: Path) -> None:
    svc_dir = tmp_path / "svc"
    svc_dir.mkdir()
    svc = svc_dir / "Foo.java"
    svc.write_text(
        "import com.pichincha.common.trace.logger.annotation.BpLogger;\n\n"
        "@Service\npublic class Foo {\n"
        "    @BpLogger\n    public void run() {}\n"
        "}\n",
        encoding="utf-8",
    )
    result = fix_add_bplogger_to_service(tmp_path)
    assert not result.applied
    assert "ya tenian" in (result.notes or "").lower() or "@BpLogger" in svc.read_text(encoding="utf-8")


def test_bplogger_empty_result_when_no_service(tmp_path: Path) -> None:
    result = fix_add_bplogger_to_service(tmp_path)
    assert not result.applied
    assert "no se encontraron" in (result.notes or "").lower()


# ---------------------------------------------------------------------------
# Regla 7 — application.yml sin ${VAR:default}
# ---------------------------------------------------------------------------


def test_yml_defaults_removed(tmp_path: Path) -> None:
    res_dir = tmp_path / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    yml = res_dir / "application.yml"
    yml.write_text(
        "customer:\n"
        "  datasource: ${CCC_DS:default-ds}\n"
        "  timeout: ${CCC_TIMEOUT:30000}\n"
        "bancs:\n"
        "  base-url: ${CCC_BANCS_BASE_URL:http://localhost:9080/bancs}\n",
        encoding="utf-8",
    )
    result = fix_yml_remove_defaults(tmp_path)
    assert result.applied
    updated = yml.read_text(encoding="utf-8")
    assert "${CCC_DS}" in updated
    assert "${CCC_TIMEOUT}" in updated
    assert ":default-ds}" not in updated
    assert ":30000}" not in updated


def test_yml_preserves_optimus_web_defaults(tmp_path: Path) -> None:
    res_dir = tmp_path / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    yml = res_dir / "application.yml"
    yml.write_text(
        "optimus:\n"
        "  web:\n"
        "    filter:\n"
        "      excluded: ${OPTIMUS_EXCLUDED:/actuator}\n"
        "customer:\n"
        "  ds: ${CCC_DS:keep-stripped}\n",
        encoding="utf-8",
    )
    result = fix_yml_remove_defaults(tmp_path)
    assert result.applied
    updated = yml.read_text(encoding="utf-8")
    # optimus.web.* preserva el default
    assert "${OPTIMUS_EXCLUDED:/actuator}" in updated
    # customer.* pierde el default
    assert "${CCC_DS}" in updated


def test_yml_no_change_if_already_clean(tmp_path: Path) -> None:
    res_dir = tmp_path / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    yml = res_dir / "application.yml"
    yml.write_text("customer:\n  ds: ${CCC_DS}\n", encoding="utf-8")
    result = fix_yml_remove_defaults(tmp_path)
    assert not result.applied


# ---------------------------------------------------------------------------
# Regla 8 — lib-bnc-api-client
# ---------------------------------------------------------------------------


def test_libbnc_added_if_missing(tmp_path: Path) -> None:
    gradle = tmp_path / "build.gradle"
    gradle.write_text(
        "plugins { id 'java' }\n\n"
        "dependencies {\n"
        "    implementation 'org.springframework.boot:spring-boot-starter-webflux'\n"
        "}\n",
        encoding="utf-8",
    )
    result = fix_add_libbnc_dependency(tmp_path)
    assert result.applied
    updated = gradle.read_text(encoding="utf-8")
    assert "com.pichincha.bnc:lib-bnc-api-client:1.1.0" in updated


def test_libbnc_no_change_if_already_present(tmp_path: Path) -> None:
    gradle = tmp_path / "build.gradle"
    gradle.write_text(
        "dependencies {\n"
        "    implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0-alpha.20260409'\n"
        "}\n",
        encoding="utf-8",
    )
    result = fix_add_libbnc_dependency(tmp_path)
    assert not result.applied


def test_libbnc_no_gradle_file(tmp_path: Path) -> None:
    result = fix_add_libbnc_dependency(tmp_path)
    assert not result.applied


# ---------------------------------------------------------------------------
# Regla 9 — catalog-info.yaml
# ---------------------------------------------------------------------------


def test_catalog_info_generated(tmp_path: Path) -> None:
    # Proyecto con nombre de repo reconocible
    repo_dir = tmp_path / "tnd-msa-sp-wsclientes0007"
    repo_dir.mkdir()
    # Gradle con un par de lib-bnc-*
    (repo_dir / "build.gradle").write_text(
        "implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0'\n"
        "implementation 'com.pichincha.common:lib-trace-logger:1.4.0'\n",
        encoding="utf-8",
    )
    result = fix_catalog_info_scaffold(
        repo_dir,
        description="Consulta contacto transaccional",
        owner="ops@pichincha.com",
    )
    assert result.applied
    ci = repo_dir / "catalog-info.yaml"
    content = ci.read_text(encoding="utf-8")
    assert "namespace: tnd-middleware" in content
    assert "name: tpl-middleware" in content
    assert "lifecycle: test" in content
    assert "owner: ops@pichincha.com" in content
    assert "tnd-msa-sp-wsclientes0007" in content
    assert "Consulta contacto transaccional" in content
    assert "component:lib-bnc-api-client" in content
    assert "component:lib-trace-logger" in content


def test_catalog_info_preserves_real_values(tmp_path: Path) -> None:
    repo_dir = tmp_path / "tnd-msa-sp-real"
    repo_dir.mkdir()
    ci = repo_dir / "catalog-info.yaml"
    # Si ya tiene un catalog-info bueno (sin placeholders), no debe sobreescribir
    ci.write_text(
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Component\n"
        "metadata:\n"
        "  namespace: tnd-middleware\n"
        "  name: tpl-middleware\n"
        "  description: real\n"
        "spec:\n"
        "  owner: real@pichincha.com\n"
        "  lifecycle: test\n",
        encoding="utf-8",
    )
    result = fix_catalog_info_scaffold(repo_dir)
    assert not result.applied
    assert "real@pichincha.com" in ci.read_text(encoding="utf-8")


def test_catalog_info_reads_sonar_uuid_from_sonarlint(tmp_path: Path) -> None:
    repo_dir = tmp_path / "tnd-msa-sp-svc"
    repo_dir.mkdir()
    sonar = repo_dir / ".sonarlint"
    sonar.mkdir()
    (sonar / "connectedMode.json").write_text(
        '{"sonarCloudOrganization": "bancopichinchaec", '
        '"projectKey": "46ce6caa-d7d5-49b5-9c8a-0958a64589c5"}',
        encoding="utf-8",
    )
    result = fix_catalog_info_scaffold(repo_dir, owner="x@pichincha.com")
    content = (repo_dir / "catalog-info.yaml").read_text(encoding="utf-8")
    assert "46ce6caa-d7d5-49b5-9c8a-0958a64589c5" in content
    assert "<SET-sonarcloud-UUID>" not in content
    _ = result.applied


def test_catalog_info_flags_manual_review_when_no_sonar(tmp_path: Path) -> None:
    repo_dir = tmp_path / "svc"
    repo_dir.mkdir()
    result = fix_catalog_info_scaffold(repo_dir, owner="x@pichincha.com")
    assert result.applied
    assert "sonarcloud" in (result.notes or "").lower()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def test_run_bank_autofix_runs_all_four(tmp_path: Path) -> None:
    # Setup minimal project
    svc_dir = tmp_path / "src" / "main" / "java" / "pkg"
    svc_dir.mkdir(parents=True)
    (svc_dir / "Svc.java").write_text(
        "import org.springframework.stereotype.Service;\n"
        "@Service\npublic class Svc { public void run() {} }\n",
        encoding="utf-8",
    )
    res_dir = tmp_path / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    (res_dir / "application.yml").write_text(
        "customer:\n  ds: ${CCC_DS:x}\n", encoding="utf-8"
    )
    (tmp_path / "build.gradle").write_text(
        "dependencies {}\n", encoding="utf-8"
    )

    results = run_bank_autofix(tmp_path)
    assert len(results) == 4
    rules_applied = {r.rule for r in results if r.applied}
    # Deberia aplicar 4, 7, 8, 9
    assert "4" in rules_applied
    assert "7" in rules_applied
    assert "8" in rules_applied
    assert "9" in rules_applied


def test_run_bank_autofix_subset(tmp_path: Path) -> None:
    (tmp_path / "build.gradle").write_text(
        "dependencies {}\n", encoding="utf-8"
    )
    results = run_bank_autofix(tmp_path, rules=["8"])
    assert len(results) == 1
    assert results[0].rule == "8"
