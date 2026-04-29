"""Tests para el autofix registry (HIGH+MEDIUM del checklist BPTPSRE)."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.autofix import (
    AUTOFIX_REGISTRY,
    AutofixReport,
    Violation,
    fix_abstract_to_interface,
    fix_backend_from_catalog,
    fix_bancs_exception_wrapping,
    fix_componente_from_catalog,
    fix_lombok_slf4j_removal,
    fix_recurso_format,
    fix_remove_mensajeNegocio_setter,
    fix_slf4j_to_bplogger,
    run_autofix_loop,
)
from capamedia_cli.core.checklist_rules import CheckResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_root(tmp_path: Path, name: str = "WSClientes0099") -> Path:
    """Crea un layout base hexagonal suficiente para los tests."""
    root = tmp_path / name
    for pkg in ("application", "domain", "infrastructure"):
        (root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / pkg).mkdir(
            parents=True, exist_ok=True
        )
    (root / "src" / "main" / "resources").mkdir(parents=True, exist_ok=True)
    return root


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _violation(check_id: str, severity: str = "high") -> Violation:
    return Violation(
        check_id=check_id,
        severity=severity,
        file=Path(""),
        line=0,
        message="test",
        evidence="test",
    )


def _result(check_id: str, severity: str, status: str = "fail") -> CheckResult:
    return CheckResult(
        id=check_id,
        block="Test",
        title=f"test {check_id}",
        status=status,
        severity=severity if status == "fail" else "",
    )


# ---------------------------------------------------------------------------
# Individual fix tests (mínimo 8)
# ---------------------------------------------------------------------------


def test_fix_abstract_to_interface_converts_port_and_adapter(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    port_file = (
        root
        / "src/main/java/com/pichincha/sp/application/port/output/ClientePort.java"
    )
    _write(
        port_file,
        "package com.pichincha.sp.application.port.output;\n"
        "public abstract class ClientePort {\n"
        "    public abstract String obtener(String id);\n"
        "}\n",
    )
    adapter_file = (
        root / "src/main/java/com/pichincha/sp/infrastructure/ClienteBancsAdapter.java"
    )
    _write(
        adapter_file,
        "package com.pichincha.sp.infrastructure;\n"
        "import com.pichincha.sp.application.port.output.ClientePort;\n"
        "public class ClienteBancsAdapter extends ClientePort {\n"
        "    public String obtener(String id) { return id; }\n"
        "}\n",
    )

    result = fix_abstract_to_interface(root, _violation("1.3"))
    assert result.applied is True
    assert len(result.files_modified) == 2
    assert "public interface ClientePort" in port_file.read_text(encoding="utf-8")
    assert "public abstract" not in port_file.read_text(encoding="utf-8")
    assert "implements ClientePort" in adapter_file.read_text(encoding="utf-8")
    assert "extends ClientePort" not in adapter_file.read_text(encoding="utf-8")


def test_fix_abstract_to_interface_noop_when_no_port(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    file = root / "src/main/java/com/pichincha/sp/domain/Cliente.java"
    _write(file, "package com.pichincha.sp.domain;\npublic class Cliente {}\n")
    result = fix_abstract_to_interface(root, _violation("1.3"))
    assert result.applied is False


def test_fix_slf4j_to_bplogger_replaces_annotation_and_import(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    file = root / "src/main/java/com/pichincha/sp/application/ClienteService.java"
    _write(
        file,
        "package com.pichincha.sp.application;\n"
        "import lombok.extern.slf4j.Slf4j;\n"
        "import org.slf4j.LoggerFactory;\n"
        "@Slf4j\n"
        "public class ClienteService {}\n",
    )
    result = fix_slf4j_to_bplogger(root, _violation("2.2"))
    assert result.applied is True
    new_text = file.read_text(encoding="utf-8")
    assert "@BpLogger" in new_text
    assert "@Slf4j" not in new_text
    assert "org.slf4j" not in new_text
    assert "import com.pichincha.bp.traces.BpLogger" in new_text


def test_fix_lombok_slf4j_removal_only_strips_annotation(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    file = root / "src/main/java/com/pichincha/sp/application/Utility.java"
    _write(
        file,
        "package com.pichincha.sp.application;\n"
        "import lombok.extern.slf4j.Slf4j;\n"
        "@Slf4j\n"
        "public class Utility {}\n",
    )
    result = fix_lombok_slf4j_removal(root, _violation("2.2"))
    assert result.applied is True
    text = file.read_text(encoding="utf-8")
    assert "@Slf4j" not in text
    assert "lombok.extern.slf4j.Slf4j" not in text
    assert "@BpLogger" not in text  # este fix NO inyecta BpLogger


def test_fix_bancs_exception_wrapping_adds_catch(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    helper = (
        root
        / "src/main/java/com/pichincha/sp/infrastructure/BancsClientHelper.java"
    )
    _write(
        helper,
        "package com.pichincha.sp.infrastructure;\n"
        "public class BancsClientHelper {\n"
        "    public String call() {\n"
        "        try {\n"
        "            return doCall();\n"
        "        } catch (IllegalStateException e) {\n"
        "            throw new RuntimeException(e);\n"
        "        }\n"
        "    }\n"
        "    private String doCall() { return \"x\"; }\n"
        "}\n",
    )
    result = fix_bancs_exception_wrapping(root, _violation("5.1"))
    assert result.applied is True
    text = helper.read_text(encoding="utf-8")
    assert "catch (RuntimeException" in text
    assert "BancsOperationException" in text


def test_fix_bancs_exception_wrapping_skips_when_already_present(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    helper = (
        root
        / "src/main/java/com/pichincha/sp/infrastructure/BancsClientHelper.java"
    )
    _write(
        helper,
        "package com.pichincha.sp.infrastructure;\n"
        "public class BancsClientHelper {\n"
        "    public String call() {\n"
        "        try { return \"x\"; }\n"
        "        catch (RuntimeException e) { throw new RuntimeException(e); }\n"
        "    }\n"
        "}\n",
    )
    result = fix_bancs_exception_wrapping(root, _violation("5.1"))
    assert result.applied is False


def test_fix_remove_mensajenegocio_setter_deletes_calls(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    file = (
        root
        / "src/main/java/com/pichincha/sp/infrastructure/ErrorMapper.java"
    )
    _write(
        file,
        "package com.pichincha.sp.infrastructure;\n"
        "public class ErrorMapper {\n"
        "    public void map(Error e) {\n"
        "        e.setCodigo(\"001\");\n"
        "        e.setMensajeNegocio(\"Hola negocio\");\n"
        "        e.setMensaje(\"hola\");\n"
        "    }\n"
        "}\n",
    )
    result = fix_remove_mensajeNegocio_setter(root, _violation("15.1"))
    assert result.applied is True
    text = file.read_text(encoding="utf-8")
    assert "setMensajeNegocio" not in text
    assert "setCodigo" in text
    assert "setMensaje" in text  # no confundir con mensajeNegocio


def test_fix_remove_mensajenegocio_preserves_empty_slot(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    file = (
        root
        / "src/main/java/com/pichincha/sp/infrastructure/ErrorMapper.java"
    )
    _write(
        file,
        "package com.pichincha.sp.infrastructure;\n"
        "public class ErrorMapper {\n"
        "    public void map(Error e) {\n"
        "        e.setMensajeNegocio(\"\");\n"
        "        e.setMensaje(\"hola\");\n"
        "    }\n"
        "}\n",
    )

    result = fix_remove_mensajeNegocio_setter(root, _violation("15.1"))
    text = file.read_text(encoding="utf-8")

    assert result.applied is False
    assert 'setMensajeNegocio("")' in text


def test_fix_recurso_format_adds_service_slash_method(tmp_path: Path) -> None:
    root = _make_root(tmp_path, name="WSClientes0099")
    file = (
        root
        / "src/main/java/com/pichincha/sp/infrastructure/ClienteController.java"
    )
    _write(
        file,
        "package com.pichincha.sp.infrastructure;\n"
        "import org.springframework.web.bind.annotation.*;\n"
        "@RestController\n"
        "public class ClienteController {\n"
        "    @PostMapping(\"/obtener\")\n"
        "    public void handle(Error e) {\n"
        "        e.setRecurso(\"ClienteController\");\n"
        "    }\n"
        "}\n",
    )
    result = fix_recurso_format(root, _violation("15.2", "medium"))
    assert result.applied is True
    text = file.read_text(encoding="utf-8")
    assert "/" in text.split("setRecurso")[1].split(")")[0]


def test_fix_recurso_format_noop_when_already_has_slash(tmp_path: Path) -> None:
    root = _make_root(tmp_path, name="WSClientes0099")
    file = (
        root / "src/main/java/com/pichincha/sp/infrastructure/ClienteMapper.java"
    )
    _write(
        file,
        "package com.pichincha.sp.infrastructure;\n"
        "public class ClienteMapper {\n"
        "    public void m(Error e) { e.setRecurso(\"WSClientes0099/obtener\"); }\n"
        "}\n",
    )
    result = fix_recurso_format(root, _violation("15.2", "medium"))
    assert result.applied is False


def test_fix_componente_from_catalog_normalizes_to_service_name(tmp_path: Path) -> None:
    root = _make_root(tmp_path, name="WSClientes0099")
    file = (
        root / "src/main/java/com/pichincha/sp/infrastructure/ComponenteMapper.java"
    )
    _write(
        file,
        "package com.pichincha.sp.infrastructure;\n"
        "public class ComponenteMapper {\n"
        "    public void m(Error e) { e.setComponente(\"algo-raro\"); }\n"
        "}\n",
    )
    result = fix_componente_from_catalog(root, _violation("15.3", "medium"))
    assert result.applied is True
    assert 'setComponente("WSClientes0099")' in file.read_text(encoding="utf-8")


def test_fix_componente_from_catalog_keeps_valid_values(tmp_path: Path) -> None:
    root = _make_root(tmp_path, name="WSClientes0099")
    file = (
        root / "src/main/java/com/pichincha/sp/infrastructure/ComponenteMapper.java"
    )
    _write(
        file,
        "package com.pichincha.sp.infrastructure;\n"
        "public class ComponenteMapper {\n"
        "    public void m(Error e) { e.setComponente(\"TX012345\"); }\n"
        "}\n",
    )
    result = fix_componente_from_catalog(root, _violation("15.3", "medium"))
    assert result.applied is False
    assert 'setComponente("TX012345")' in file.read_text(encoding="utf-8")


def test_fix_backend_from_catalog_replaces_zeros_with_bancs_code(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    file = (
        root / "src/main/java/com/pichincha/sp/infrastructure/BancsErrorMapper.java"
    )
    _write(
        file,
        "package com.pichincha.sp.infrastructure;\n"
        "public class BancsErrorMapper {\n"
        "    public void m(Error e) { e.setBackend(\"00000\"); }\n"
        "}\n",
    )
    result = fix_backend_from_catalog(root, _violation("15.4"))
    assert result.applied is True
    assert 'setBackend("00045")' in file.read_text(encoding="utf-8")


def test_fix_backend_from_catalog_uses_iib_code_for_non_bancs(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    file = (
        root / "src/main/java/com/pichincha/sp/infrastructure/DefaultErrorMapper.java"
    )
    _write(
        file,
        "package com.pichincha.sp.infrastructure;\n"
        "public class DefaultErrorMapper {\n"
        "    public void m(Error e) { e.setBackend(\"999\"); }\n"
        "}\n",
    )
    result = fix_backend_from_catalog(root, _violation("15.4"))
    assert result.applied is True
    assert 'setBackend("00638")' in file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


def test_registry_has_at_least_expected_ids() -> None:
    expected = {"1.3", "2.2", "5.1", "15.1", "15.2", "15.3", "15.4"}
    assert expected.issubset(set(AUTOFIX_REGISTRY.keys()))


def test_registry_total_fix_functions_is_at_least_8() -> None:
    total = sum(len(fns) for fns in AUTOFIX_REGISTRY.values())
    assert total >= 8


# ---------------------------------------------------------------------------
# Loop tests (end-to-end)
# ---------------------------------------------------------------------------


def _install_scene_3high_2medium(tmp_path: Path) -> Path:
    """Monta una escena con 3 HIGH (1.3, 15.1, 15.4) y 2 MEDIUM (15.2, 15.3)
    todos autofixeables por el registry."""
    root = _make_root(tmp_path, name="WSClientes0099")

    # 1.3 HIGH - port como abstract class
    _write(
        root
        / "src/main/java/com/pichincha/sp/application/port/output/ClientePort.java",
        "package com.pichincha.sp.application.port.output;\n"
        "public abstract class ClientePort {\n"
        "    public abstract String obtener(String id);\n"
        "}\n",
    )
    _write(
        root
        / "src/main/java/com/pichincha/sp/infrastructure/ClienteBancsAdapter.java",
        "package com.pichincha.sp.infrastructure;\n"
        "import com.pichincha.sp.application.port.output.ClientePort;\n"
        "public class ClienteBancsAdapter extends ClientePort {\n"
        "    public String obtener(String id) { return id; }\n"
        "}\n",
    )

    # 15.1 HIGH + 15.2 MEDIUM + 15.3 MEDIUM + 15.4 HIGH en un solo mapper
    _write(
        root
        / "src/main/java/com/pichincha/sp/infrastructure/BancsErrorMapper.java",
        "package com.pichincha.sp.infrastructure;\n"
        "public class BancsErrorMapper {\n"
        "    public void map(Error e) {\n"
        "        e.setMensajeNegocio(\"negocio\");\n"
        "        e.setRecurso(\"BancsErrorMapper\");\n"
        "        e.setComponente(\"xxx\");\n"
        "        e.setBackend(\"00000\");\n"
        "    }\n"
        "}\n",
    )
    # Hint de metodo para recurso
    _write(
        root
        / "src/main/java/com/pichincha/sp/infrastructure/ClienteController.java",
        "package com.pichincha.sp.infrastructure;\n"
        "public class ClienteController {\n"
        "    @PostMapping(\"/obtener\") public void x() {}\n"
        "}\n",
    )
    return root


def test_loop_converges_when_all_violations_autofixable(tmp_path: Path) -> None:
    root = _install_scene_3high_2medium(tmp_path)

    call_count = {"n": 0}
    scripted_results: list[list[CheckResult]] = [
        # Ronda 1: los 5 issues
        [
            _result("1.3", "high"),
            _result("15.1", "high"),
            _result("15.4", "high"),
            _result("15.2", "medium"),
            _result("15.3", "medium"),
        ],
        # Ronda 2: todo limpio
        [_result("1.1", "", status="pass")],
        # Final rerun
        [_result("1.1", "", status="pass")],
    ]

    def rerun() -> list[CheckResult]:
        idx = min(call_count["n"], len(scripted_results) - 1)
        call_count["n"] += 1
        return scripted_results[idx]

    report = run_autofix_loop(root, rerun, max_iter=3)
    assert isinstance(report, AutofixReport)
    assert report.converged is True
    assert report.needs_human is False
    assert report.total_applied >= 5  # al menos un fix por cada violation
    assert report.iterations <= 3


def test_loop_needs_human_after_iter_budget(tmp_path: Path) -> None:
    """Si despues de 3 rondas el check sigue reportando fallos, NEEDS_HUMAN."""
    root = _make_root(tmp_path)
    # Archivo en estado que ningun fix puede resolver (issue en ID que NO
    # esta en el registry: 7.2 secret hardcoded, por ejemplo)
    _write(
        root / "src/main/java/com/pichincha/sp/domain/Dummy.java",
        "package com.pichincha.sp.domain;\npublic class Dummy {}\n",
    )

    call_count = {"n": 0}

    def rerun() -> list[CheckResult]:
        call_count["n"] += 1
        # Siempre devuelve el mismo issue HIGH no autofixeable
        return [_result("7.2", "high")]

    report = run_autofix_loop(root, rerun, max_iter=3)
    # 7.2 no esta en el registry => nada que aplicar => loop corta temprano
    assert report.converged is False
    assert report.needs_human is True
    assert report.total_applied == 0
    assert any(r["check_id"] == "7.2" for r in report.remaining)


def test_loop_writes_log_when_log_dir_given(tmp_path: Path) -> None:
    root = _install_scene_3high_2medium(tmp_path)

    call_count = {"n": 0}
    scripted: list[list[CheckResult]] = [
        [_result("15.1", "high")],
        [_result("1.1", "", status="pass")],
        [_result("1.1", "", status="pass")],
    ]

    def rerun() -> list[CheckResult]:
        idx = min(call_count["n"], len(scripted) - 1)
        call_count["n"] += 1
        return scripted[idx]

    log_dir = root / ".capamedia" / "autofix"
    report = run_autofix_loop(root, rerun, max_iter=3, log_dir=log_dir)
    assert report.log_path is not None
    assert report.log_path.exists()
    log_text = report.log_path.read_text(encoding="utf-8")
    assert "Applied" in log_text
    assert "iterations=" in log_text


def test_loop_stops_if_no_progress(tmp_path: Path) -> None:
    """Si el fix no puede aplicar nada (codigo ya limpio o patron ambiguo),
    no debe iterar indefinidamente."""
    root = _make_root(tmp_path)
    # 15.1 HIGH pero sin el setter (el fix no va a encontrar nada)
    _write(
        root / "src/main/java/com/pichincha/sp/infrastructure/Clean.java",
        "package com.pichincha.sp.infrastructure;\npublic class Clean {}\n",
    )

    call_count = {"n": 0}

    def rerun() -> list[CheckResult]:
        call_count["n"] += 1
        return [_result("15.1", "high")]

    report = run_autofix_loop(root, rerun, max_iter=3)
    assert report.converged is False
    # Debe haber cortado tras 1 iteracion al no hacer progreso
    assert report.iterations == 1
