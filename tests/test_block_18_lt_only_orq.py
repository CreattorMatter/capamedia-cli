"""Tests para Block 18: detector inverso — log transaccional prohibido fuera de ORQ.

El log transaccional (lib-event-logs + @EventAudit + spring.kafka/logging.event)
es EXCLUSIVO de orquestadores. Si aparece en WAS/BUS, es un error de copy-paste
y debe marcarse como FAIL.

Fuente: BPTPSRE-Estructura Log Transaccional - cita literal "los eventos se
generan unicamente en los orquestadores".
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import CheckContext, run_block_18


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_was_project(tmp_path: Path, name: str = "tnd-msa-sp-wsclientes0007") -> Path:
    project = tmp_path / name
    project.mkdir()
    return project


def _mk_orq_project(tmp_path: Path, name: str = "tnd-msa-sp-orqclientes0027") -> Path:
    project = tmp_path / name
    project.mkdir()
    return project


# ---------------------------------------------------------------------------
# Skip behavior: solo corre en NO-ORQ
# ---------------------------------------------------------------------------


def test_block_18_skipped_for_orq(tmp_path: Path) -> None:
    """En ORQ, Block 18 no corre (el que valida es el 17)."""
    project = _mk_orq_project(tmp_path)
    # Poner restos LT; Block 18 igual no debe correr en ORQ
    (project / "build.gradle").write_text(
        "implementation 'com.pichincha.common:lib-event-logs-webflux:1.0.0'\n",
        encoding="utf-8",
    )
    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    assert results == []


def test_block_18_activates_on_was(tmp_path: Path) -> None:
    """En WAS, Block 18 emite los 3 checks (18.1, 18.2, 18.3)."""
    project = _mk_was_project(tmp_path)
    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    ids = {r.id for r in results}
    assert ids == {"18.1", "18.2", "18.3"}


# ---------------------------------------------------------------------------
# 18.1 — lib-event-logs en build.gradle (prohibido en WAS)
# ---------------------------------------------------------------------------


def test_18_1_fails_when_was_has_lib_event_logs_webflux(tmp_path: Path) -> None:
    project = _mk_was_project(tmp_path)
    (project / "build.gradle").write_text(
        "dependencies {\n"
        "    implementation 'com.pichincha.common:lib-event-logs-webflux:1.0.0'\n"
        "}\n",
        encoding="utf-8",
    )
    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    r = next(r for r in results if r.id == "18.1")
    assert r.status == "fail"
    assert r.severity == "high"
    assert "build.gradle" in r.detail


def test_18_1_fails_when_was_has_lib_event_logs_mvc(tmp_path: Path) -> None:
    project = _mk_was_project(tmp_path)
    (project / "build.gradle").write_text(
        "implementation 'com.pichincha.common:lib-event-logs-mvc:1.0.0'\n",
        encoding="utf-8",
    )
    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    r = next(r for r in results if r.id == "18.1")
    assert r.status == "fail"


def test_18_1_passes_when_was_has_no_lib_event_logs(tmp_path: Path) -> None:
    project = _mk_was_project(tmp_path)
    (project / "build.gradle").write_text(
        "dependencies {\n"
        "    implementation 'org.springframework.boot:spring-boot-starter-web'\n"
        "}\n",
        encoding="utf-8",
    )
    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    r = next(r for r in results if r.id == "18.1")
    assert r.status == "pass"


# ---------------------------------------------------------------------------
# 18.2 — logging.event / spring.kafka en yml (prohibido en WAS)
# ---------------------------------------------------------------------------


def test_18_2_fails_when_was_has_logging_event(tmp_path: Path) -> None:
    project = _mk_was_project(tmp_path)
    res = project / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "logging:\n  event:\n    mode: 'EXTERNAL'\n",
        encoding="utf-8",
    )
    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    r = next(r for r in results if r.id == "18.2")
    assert r.status == "fail"
    assert r.severity == "high"


def test_18_2_fails_when_was_has_kafka_topic_auditor(tmp_path: Path) -> None:
    project = _mk_was_project(tmp_path)
    res = project / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "spring:\n"
        "  kafka:\n"
        "    properties:\n"
        "      bootstrap:\n"
        "        servers: ${KAFKA_SERVER}\n"
        "    producer:\n"
        "      key-serializer: StringSerializer\n"
        "KAFKA_TOPIC_AUDITOR_VAR: x  # shouldn't appear\n",
        encoding="utf-8",
    )
    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    r = next(r for r in results if r.id == "18.2")
    assert r.status == "fail"


def test_18_2_passes_when_was_yml_clean(tmp_path: Path) -> None:
    project = _mk_was_project(tmp_path)
    res = project / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "spring:\n  application:\n    name: wsclientes0007\n",
        encoding="utf-8",
    )
    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    r = next(r for r in results if r.id == "18.2")
    assert r.status == "pass"


# ---------------------------------------------------------------------------
# 18.3 — @EventAudit en .java (prohibido en WAS)
# ---------------------------------------------------------------------------


def test_18_3_fails_when_was_has_event_audit(tmp_path: Path) -> None:
    project = _mk_was_project(tmp_path)
    adapter_dir = project / "src" / "main" / "java" / "com" / "p" / "adapter"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "BancsAdapter.java").write_text(
        "@Component\npublic class BancsAdapter {\n"
        "    @EventAudit(service=\"X\", method=\"Y\", type=AuditType.T)\n"
        "    public void call() {}\n"
        "}\n",
        encoding="utf-8",
    )
    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    r = next(r for r in results if r.id == "18.3")
    assert r.status == "fail"
    assert r.severity == "high"
    assert "BancsAdapter.java" in r.detail


def test_18_3_passes_when_was_has_no_event_audit(tmp_path: Path) -> None:
    project = _mk_was_project(tmp_path)
    adapter_dir = project / "src" / "main" / "java" / "com" / "p" / "adapter"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "CleanAdapter.java").write_text(
        "@Component\npublic class CleanAdapter {\n    public void call() {}\n}\n",
        encoding="utf-8",
    )
    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    r = next(r for r in results if r.id == "18.3")
    assert r.status == "pass"


def test_18_3_ignores_test_java_files(tmp_path: Path) -> None:
    """Archivos en test/ no deben disparar 18.3 (solo production)."""
    project = _mk_was_project(tmp_path)
    test_dir = project / "src" / "test" / "java" / "com" / "p"
    test_dir.mkdir(parents=True)
    (test_dir / "SomeTest.java").write_text(
        "// mock of @EventAudit for testing\n",
        encoding="utf-8",
    )
    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    r = next(r for r in results if r.id == "18.3")
    # el texto "@EventAudit" en comentarios de test no debe disparar fail
    # (nuestro filtro excluye paths con "test")
    assert r.status == "pass"


# ---------------------------------------------------------------------------
# Integración: WAS con restos múltiples falla en los 3 checks
# ---------------------------------------------------------------------------


def test_block_18_all_three_fail_when_was_is_dirty(tmp_path: Path) -> None:
    """WAS con copy-paste completo de un ORQ: 3 fails."""
    project = _mk_was_project(tmp_path)
    (project / "build.gradle").write_text(
        "implementation 'com.pichincha.common:lib-event-logs-mvc:1.0.0'\n",
        encoding="utf-8",
    )
    res = project / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "logging:\n  event:\n    mode: 'EXTERNAL'\n",
        encoding="utf-8",
    )
    adapter_dir = project / "src" / "main" / "java" / "com" / "p" / "adapter"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "X.java").write_text(
        "@EventAudit public class X {}", encoding="utf-8"
    )

    results = run_block_18(CheckContext(migrated_path=project, legacy_path=None))
    fails = [r for r in results if r.status == "fail"]
    assert len(fails) == 3
    assert {r.id for r in fails} == {"18.1", "18.2", "18.3"}
