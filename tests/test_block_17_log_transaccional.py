"""Tests para Block 17: Log transaccional (solo ORQ)."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import CheckContext, run_block_17


def _mk_orq_project(tmp_path: Path, name: str = "tnd-msa-sp-orqclientes0027") -> Path:
    project = tmp_path / name
    project.mkdir()
    return project


def _mk_non_orq_project(tmp_path: Path, name: str = "tnd-msa-sp-wsclientes0007") -> Path:
    project = tmp_path / name
    project.mkdir()
    return project


# ---------------------------------------------------------------------------
# Skip behavior: solo corre en ORQ
# ---------------------------------------------------------------------------


def test_block_17_skipped_for_non_orq(tmp_path: Path) -> None:
    """Proyectos no-ORQ no generan ningun result (block skipped)."""
    project = _mk_non_orq_project(tmp_path)
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    assert results == []


def test_block_17_activates_on_orq(tmp_path: Path) -> None:
    """Con ORQ en el nombre, el block corre."""
    project = _mk_orq_project(tmp_path)
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    # Sin build.gradle ni yml, todos fallan salvo 17.4 que skipea sin adapters
    assert len(results) >= 3
    ids = {r.id for r in results}
    assert "17.1" in ids
    assert "17.2" in ids
    assert "17.3" in ids


# ---------------------------------------------------------------------------
# 17.1 — dependencia lib-event-logs
# ---------------------------------------------------------------------------


def test_17_1_passes_with_webflux_variant(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    (project / "build.gradle").write_text(
        "dependencies {\n"
        "    implementation 'com.pichincha.common:lib-event-logs-webflux:1.0.0'\n"
        "}\n",
        encoding="utf-8",
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r171 = next(r for r in results if r.id == "17.1")
    assert r171.status == "pass"
    assert "webflux" in r171.detail


def test_17_1_passes_with_mvc_variant(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    (project / "build.gradle").write_text(
        "dependencies {\n"
        "    implementation 'com.pichincha.common:lib-event-logs-mvc:1.0.0'\n"
        "}\n",
        encoding="utf-8",
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r171 = next(r for r in results if r.id == "17.1")
    assert r171.status == "pass"


def test_17_1_fails_without_lib_event_logs(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    (project / "build.gradle").write_text(
        "dependencies { implementation 'org.springframework.boot:spring-boot-starter-webflux' }\n",
        encoding="utf-8",
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r171 = next(r for r in results if r.id == "17.1")
    assert r171.status == "fail"
    assert r171.severity == "high"


# ---------------------------------------------------------------------------
# 17.2 / 17.3 — application.yml
# ---------------------------------------------------------------------------


def _mk_complete_orq_yml(project: Path) -> None:
    res = project / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "spring:\n"
        "  kafka:\n"
        "    properties:\n"
        "      bootstrap:\n"
        "        servers: ${KAFKA_SERVER}\n"
        "logging:\n"
        "  level:\n"
        "    org:\n"
        "      apache:\n"
        "        kafka: ${CCC_LOG_LEVEL_KAFKA}\n"
        "    com:\n"
        "      pichincha:\n"
        "        common: ${CCC_LOG_LEVEL_EVENT_LOGS}\n"
        "        common.trace.logger: ${CCC_LOG_LEVEL_TRACE_LOGGER}\n"
        "  event:\n"
        "    mode: 'EXTERNAL'\n"
        "    kafka:\n"
        "      topic:\n"
        "        name: ${KAFKA_TOPIC_AUDITOR}\n",
        encoding="utf-8",
    )


def _mk_helm_with_log_levels(
    project: Path, trace_logger_value: str = "INFO", omit_in: str = ""
) -> None:
    """helm/dev|test|prod.yml con las 3 CCC_LOG_LEVEL_*. `omit_in` deja un helm
    sin las env vars para simular drift."""
    helm = project / "helm"
    helm.mkdir(exist_ok=True)
    for env in ("dev", "test", "prod"):
        if env == omit_in:
            body = "variables:\n  configmap: {}\n"
        else:
            body = (
                "variables:\n"
                "  configmap:\n"
                '    - name: "CCC_LOG_LEVEL_KAFKA"\n'
                '      value: "OFF"\n'
                '    - name: "CCC_LOG_LEVEL_EVENT_LOGS"\n'
                '      value: "OFF"\n'
                '    - name: "CCC_LOG_LEVEL_TRACE_LOGGER"\n'
                f'      value: "{trace_logger_value}"\n'
            )
        (helm / f"{env}.yml").write_text(body, encoding="utf-8")


def test_17_2_passes_with_both_blocks(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    _mk_complete_orq_yml(project)
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r172 = next(r for r in results if r.id == "17.2")
    assert r172.status == "pass"


def test_17_2_fails_without_spring_kafka(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    res = project / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "logging:\n  event:\n    mode: 'EXTERNAL'\n", encoding="utf-8"
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r172 = next(r for r in results if r.id == "17.2")
    assert r172.status == "fail"
    assert "spring.kafka" in r172.detail


def test_17_3_passes_with_kafka_level_externalized(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    _mk_complete_orq_yml(project)
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r173 = next(r for r in results if r.id == "17.3")
    assert r173.status == "pass"


def test_17_3_fails_with_kafka_off_hardcoded(tmp_path: Path) -> None:
    """El literal `kafka: OFF` viejo ya no alcanza: el nivel se externaliza
    (orqproductos0061 commit 5e92bfa)."""
    project = _mk_orq_project(tmp_path)
    res = project / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "logging:\n  level:\n    org:\n      apache:\n        kafka: OFF\n",
        encoding="utf-8",
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r173 = next(r for r in results if r.id == "17.3")
    assert r173.status == "fail"
    assert r173.severity == "medium"
    assert "CCC_LOG_LEVEL_KAFKA" in (r173.suggested_fix or "")


def test_17_3_fails_without_kafka_level(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    res = project / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "spring:\n  kafka: {}\nlogging:\n  event: {}\n", encoding="utf-8"
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r173 = next(r for r in results if r.id == "17.3")
    assert r173.status == "fail"
    assert r173.severity == "medium"


# ---------------------------------------------------------------------------
# 17.4 — @EventAudit en adapters
# ---------------------------------------------------------------------------


def test_17_4_passes_with_event_audit(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    adapter_dir = project / "src" / "main" / "java" / "com" / "p" / "infrastructure" / "output" / "adapter"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "FooAdapter.java").write_text(
        "@Component\npublic class FooAdapter {\n"
        "    @EventAudit(service = \"X\", method = \"Y\", type = AuditType.T)\n"
        "    public void doIt() {}\n"
        "}\n",
        encoding="utf-8",
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r174 = next(r for r in results if r.id == "17.4")
    assert r174.status == "pass"


def test_17_4_fails_when_adapter_has_no_event_audit(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    adapter_dir = project / "src" / "main" / "java" / "com" / "p" / "infrastructure" / "output" / "adapter"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "BareAdapter.java").write_text(
        "@Component\npublic class BareAdapter {\n"
        "    public void doIt() {}\n"
        "}\n",
        encoding="utf-8",
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r174 = next(r for r in results if r.id == "17.4")
    assert r174.status == "fail"
    assert r174.severity == "high"


def test_17_4_skips_when_no_adapters(tmp_path: Path) -> None:
    """Si el proyecto no tiene carpeta adapter, el check pasa con skip."""
    project = _mk_orq_project(tmp_path)
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r174 = next(r for r in results if r.id == "17.4")
    assert r174.status == "pass"
    assert "skip" in r174.detail.lower()


# ---------------------------------------------------------------------------
# 17.5 — niveles de log libs banco externalizados en application.yml
# ---------------------------------------------------------------------------


def test_17_5_passes_with_lib_levels_externalized(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    _mk_complete_orq_yml(project)
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r175 = next(r for r in results if r.id == "17.5")
    assert r175.status == "pass"


def test_17_5_fails_without_lib_levels(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    res = project / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "logging:\n  level:\n    org:\n      apache:\n"
        "        kafka: ${CCC_LOG_LEVEL_KAFKA}\n",
        encoding="utf-8",
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r175 = next(r for r in results if r.id == "17.5")
    assert r175.status == "fail"
    assert r175.severity == "medium"
    assert "com.pichincha.common" in r175.detail
    assert "trace.logger" in r175.detail


# ---------------------------------------------------------------------------
# 17.6 — env vars CCC_LOG_LEVEL_* en los 3 Helm
# ---------------------------------------------------------------------------


def test_17_6_passes_with_expected_helm_values(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    _mk_helm_with_log_levels(project)
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r176 = next(r for r in results if r.id == "17.6")
    assert r176.status == "pass"


def test_17_6_fails_with_wrong_trace_logger_value(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    _mk_helm_with_log_levels(project, trace_logger_value="DEBUG")
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r176 = next(r for r in results if r.id == "17.6")
    assert r176.status == "fail"
    assert r176.severity == "medium"
    assert "CCC_LOG_LEVEL_TRACE_LOGGER" in r176.detail
    assert "'INFO'" in r176.detail


def test_17_6_fails_when_one_helm_misses_vars(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    _mk_helm_with_log_levels(project, omit_in="prod")
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r176 = next(r for r in results if r.id == "17.6")
    assert r176.status == "fail"
    assert "prod.yml" in r176.detail
    assert "no declarada" in r176.detail


def test_17_6_skipped_without_helm_dir(tmp_path: Path) -> None:
    """Sin helm por-entorno el check se omite (igual que los 7.x de Helm)."""
    project = _mk_orq_project(tmp_path)
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    assert not any(r.id == "17.6" for r in results)


# ---------------------------------------------------------------------------
# 17.7 — @BpLogger junto a @EventAudit en adapters
# ---------------------------------------------------------------------------


def _mk_adapter(project: Path, name: str, body: str) -> None:
    adapter_dir = (
        project / "src" / "main" / "java" / "com" / "p"
        / "infrastructure" / "output" / "adapter"
    )
    adapter_dir.mkdir(parents=True, exist_ok=True)
    (adapter_dir / name).write_text(body, encoding="utf-8")


def test_17_7_passes_when_audited_adapters_have_bplogger(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    _mk_adapter(
        project,
        "FooAdapter.java",
        "import com.pichincha.common.trace.logger.annotation.BpLogger;\n"
        "@Component\npublic class FooAdapter {\n"
        "    @BpLogger\n"
        "    @EventAudit(service = \"X\", method = \"Y\", type = AuditType.T)\n"
        "    public void doIt() {}\n"
        "}\n",
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r177 = next(r for r in results if r.id == "17.7")
    assert r177.status == "pass"


def test_17_7_fails_when_audited_adapter_lacks_bplogger(tmp_path: Path) -> None:
    project = _mk_orq_project(tmp_path)
    _mk_adapter(
        project,
        "BareAdapter.java",
        "@Component\npublic class BareAdapter {\n"
        "    @EventAudit(service = \"X\", method = \"Y\", type = AuditType.T)\n"
        "    public void doIt() {}\n"
        "}\n",
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r177 = next(r for r in results if r.id == "17.7")
    assert r177.status == "fail"
    assert r177.severity == "high"
    assert "BareAdapter.java" in r177.detail


def test_17_7_skips_without_audited_adapters(tmp_path: Path) -> None:
    """Sin @EventAudit no hay que exigir @BpLogger aca: la falta de auditoria
    la reporta 17.4."""
    project = _mk_orq_project(tmp_path)
    _mk_adapter(
        project,
        "PlainAdapter.java",
        "@Component\npublic class PlainAdapter { public void doIt() {} }\n",
    )
    results = run_block_17(CheckContext(migrated_path=project, legacy_path=None))
    r177 = next(r for r in results if r.id == "17.7")
    assert r177.status == "pass"
    assert "17.4" in r177.detail
