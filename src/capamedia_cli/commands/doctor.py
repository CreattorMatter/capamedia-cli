"""capamedia doctor - diagnostico operativo de la fabrica."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from capamedia_cli import __version__
from capamedia_cli.commands.check_install import (
    CheckResult,
    _check_claude,
    _check_claude_auth,
    _check_codex,
    _check_codex_auth,
    collect_check_results,
    summarize_check_results,
)
from capamedia_cli.core.auth import (
    resolve_artifact_token,
    resolve_azure_devops_pat,
    resolve_codex_api_key,
)
from capamedia_cli.core.canonical import CANONICAL_ROOT, load_canonical_assets
from capamedia_cli.core.machine_config import (
    default_machine_config_path,
    load_machine_config,
    provider_config,
)

console = Console()


@dataclass(frozen=True)
class DoctorReport:
    classification: str
    reason: str
    config_path: Path
    machine_config: dict[str, Any]
    categories: dict[str, list[CheckResult]]
    extras: list[CheckResult]
    total_ok: int
    total_warn: int
    total_fail: int


def _make_result(name: str, status: str, detail: str, fix: str = "") -> CheckResult:
    return CheckResult(name=name, status=status, detail=detail, fix=fix)


def _service_name_from_workspace(workspace: Path) -> str:
    return workspace.resolve().name


def _check_machine_setup(config_path: Path, machine_config: dict[str, Any]) -> CheckResult:
    if not config_path.exists():
        return _make_result(
            "Machine setup",
            "fail",
            f"no existe config machine-local en {config_path}",
            "capamedia setup machine",
        )

    provider = str(machine_config.get("provider", "")).strip().lower() or "codex"
    auth_mode = str(machine_config.get("auth_mode", "")).strip().lower() or "session"
    return _make_result(
        "Machine setup",
        "ok",
        f"config presente · provider={provider} · auth_mode={auth_mode}",
    )


def _check_selected_provider_binary(machine_config: dict[str, Any]) -> CheckResult:
    provider = str(machine_config.get("provider", "codex")).strip().lower() or "codex"
    result = _check_claude() if provider == "claude" else _check_codex()

    if result.status == "ok":
        return _make_result("Selected provider binary", "ok", f"{provider}: {result.detail}")

    return _make_result(
        "Selected provider binary",
        "fail",
        f"{provider}: {result.detail}",
        result.fix,
    )


def _check_selected_provider_auth(machine_config: dict[str, Any]) -> CheckResult:
    provider = str(machine_config.get("provider", "codex")).strip().lower() or "codex"
    auth_mode = str(machine_config.get("auth_mode", "session")).strip().lower() or "session"
    provider_data = provider_config(machine_config, provider)

    if auth_mode == "api" and provider == "codex":
        if provider_data.get("auth_mode") == "api" and resolve_codex_api_key():
            return _make_result(
                "Selected provider auth",
                "ok",
                "codex configurado para auth_mode=api",
            )
        return _make_result(
            "Selected provider auth",
            "fail",
            "codex configurado en auth_mode=api pero no hay CODEX_API_KEY/OPENAI_API_KEY",
            "export CODEX_API_KEY=... o corre capamedia setup machine --auth-mode api",
        )

    result = _check_claude_auth() if provider == "claude" else _check_codex_auth()

    if result.status == "ok":
        return _make_result("Selected provider auth", "ok", f"{provider}: {result.detail}")

    return _make_result(
        "Selected provider auth",
        "fail",
        f"{provider}: {result.detail}",
        result.fix,
    )


def _check_workspace_inputs(workspace: Path | None) -> CheckResult | None:
    if workspace is None:
        return None

    from capamedia_cli.commands.batch import _find_legacy_root

    ws = workspace.expanduser().resolve()
    if not ws.exists():
        return _make_result("Legacy inputs", "fail", f"workspace no existe: {ws}", "")

    legacy_root = _find_legacy_root(ws, _service_name_from_workspace(ws))
    if legacy_root is None or not legacy_root.exists():
        return _make_result(
            "Legacy inputs",
            "fail",
            "no se encontro material legacy/WSDL utilizable para este workspace",
            "verifica clone/input corpus antes de batch pipeline",
        )

    return _make_result("Legacy inputs", "ok", f"legacy encontrado en {legacy_root}")


def _resolve_project_probe(workspace: Path | None, project: Path | None) -> Path | None:
    if project is not None:
        return project.expanduser().resolve()

    if workspace is None:
        return None

    from capamedia_cli.commands.batch import (
        _find_migrated_project,
        _find_project_from_fabrics_metadata,
    )

    ws = workspace.expanduser().resolve()
    return _find_project_from_fabrics_metadata(ws) or _find_migrated_project(ws, _service_name_from_workspace(ws))


def _probe_build_project(project: Path | None) -> CheckResult | None:
    if project is None:
        return None

    if not project.exists():
        return _make_result("Build plugin probe", "fail", f"proyecto no existe: {project}", "")

    gradle_cmd = ["./gradlew", "help", "--no-daemon"]
    if not (project / "gradlew").exists():
        gradle_cmd = ["gradle", "help", "--no-daemon"]

    try:
        from capamedia_cli.commands.batch import _resolve_java21_home
    except Exception:
        def _resolve_java21_home() -> None:
            return None

    java_home = _resolve_java21_home()
    if not java_home:
        return _make_result(
            "Build plugin probe",
            "fail",
            "no se encontro Java 21 local para validar el build",
            "capamedia install o revisar JAVA_HOME",
        )

    env = {
        "JAVA_HOME": java_home,
        "ARTIFACT_USERNAME": "BancoPichinchaEC",
        "PATH": f"{java_home}/bin:{os.environ.get('PATH', '')}",
    }
    artifact_token = resolve_artifact_token() or resolve_azure_devops_pat()
    if artifact_token:
        env["ARTIFACT_TOKEN"] = artifact_token

    merged_env = {**os.environ, **env}

    try:
        result = subprocess.run(
            gradle_cmd,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=5 * 60,
            check=False,
            env=merged_env,
        )
    except FileNotFoundError:
        return _make_result(
            "Build plugin probe",
            "fail",
            f"no se encontro `{gradle_cmd[0]}` para validar el proyecto",
            "instala Gradle o usa wrapper",
        )
    except subprocess.TimeoutExpired:
        return _make_result("Build plugin probe", "fail", "timeout validando plugin/build corporativo", "")

    if result.returncode == 0:
        return _make_result("Build plugin probe", "ok", f"build help resolvio en {project}")

    combined = "\n".join(part for part in (result.stdout or "", result.stderr or "") if part).lower()
    if "frm-plugin-peer-review-gradle" in combined or (
        "plugin" in combined and "not found" in combined
    ):
        return _make_result(
            "Build plugin probe",
            "fail",
            "plugin corporativo Gradle no resolvible en este entorno",
            "revisar Azure Artifacts / repo corporativo / plugin mirror",
        )

    tail = (result.stderr or result.stdout or "build help fallo").strip().splitlines()
    detail = tail[-1] if tail else "build help fallo"
    return _make_result("Build plugin probe", "fail", detail[:220], "")


def _classify(categories: dict[str, list[CheckResult]], extras: list[CheckResult]) -> tuple[str, str]:
    failures = [result for checks in categories.values() for result in checks if result.status == "fail"]
    failures.extend(result for result in extras if result.status == "fail")
    if not failures:
        return ("READY", "sin bloqueos duros")

    names = {result.name for result in failures}
    if "Selected provider auth" in names:
        return ("BLOCKED_PROVIDER_AUTH", "el runner seleccionado no tiene auth usable")
    if "Azure DevOps auth" in names or "MCP Fabrics" in names:
        return ("BLOCKED_CORP_REPO", "faltan accesos corporativos para git o artifacts")
    if "Build plugin probe" in names:
        return ("BLOCKED_BUILD_PLUGIN", "el plugin/build corporativo no resuelve en esta maquina")
    if "Legacy inputs" in names:
        return ("BLOCKED_INPUT", "faltan insumos legacy para el workspace")
    return ("BLOCKED_TOOLCHAIN", failures[0].detail)


def run_doctor(
    *,
    workspace: Path | None = None,
    project: Path | None = None,
    probe_build: bool = False,
) -> DoctorReport:
    config_path = default_machine_config_path()
    machine_config = load_machine_config(config_path)
    categories = collect_check_results()

    extras = [
        _check_machine_setup(config_path, machine_config),
        _check_selected_provider_binary(machine_config),
        _check_selected_provider_auth(machine_config),
    ]

    workspace_result = _check_workspace_inputs(workspace)
    if workspace_result is not None:
        extras.append(workspace_result)

    if probe_build:
        build_result = _probe_build_project(_resolve_project_probe(workspace, project))
        if build_result is not None:
            extras.append(build_result)

    extra_category = "Factory readiness"
    categories = {**categories, extra_category: extras}
    total_ok, total_warn, total_fail = summarize_check_results(categories)
    classification, reason = _classify(categories, extras)

    return DoctorReport(
        classification=classification,
        reason=reason,
        config_path=config_path,
        machine_config=machine_config,
        categories=categories,
        extras=extras,
        total_ok=total_ok,
        total_warn=total_warn,
        total_fail=total_fail,
    )


def _render_summary(report: DoctorReport, workspace: Path | None, project: Path | None) -> None:
    assets = load_canonical_assets()
    machine_provider = str(report.machine_config.get("provider", "codex"))
    auth_mode = str(report.machine_config.get("auth_mode", "session"))

    table = Table(title="CapaMedia Doctor", title_style="bold cyan")
    table.add_column("Item", style="cyan")
    table.add_column("Valor", style="bold")
    table.add_row("Doctor", report.classification)
    table.add_row("Reason", report.reason)
    table.add_row("CLI version", f"capamedia v{__version__}")
    table.add_row("Python", f"{sys.version.split()[0]} ({platform.python_implementation()})")
    table.add_row("Platform", f"{platform.system()} {platform.release()}")
    table.add_row("CWD", str(Path.cwd()))
    table.add_row("Machine config", str(report.config_path))
    table.add_row("Provider", machine_provider)
    table.add_row("Auth mode", auth_mode)
    table.add_row("Workspace probe", str(workspace.expanduser().resolve()) if workspace else "-")
    table.add_row("Project probe", str(project.expanduser().resolve()) if project else "-")
    table.add_row("Canonical root", str(CANONICAL_ROOT))
    table.add_row("Prompts", str(len(assets.get("prompt", []))))
    table.add_row("Agents", str(len(assets.get("agent", []))))
    table.add_row("Skills", str(len(assets.get("skill", []))))
    table.add_row("Context files", str(len(assets.get("context", []))))
    console.print(table)


def _render_categories(categories: dict[str, list[CheckResult]]) -> None:
    for category, checks in categories.items():
        table = Table(title=category, title_style="bold cyan", show_lines=False)
        table.add_column("Componente", style="cyan", no_wrap=True)
        table.add_column("Estado", style="bold", width=6)
        table.add_column("Detalle")
        table.add_column("Fix sugerido", style="yellow")

        for result in checks:
            label = {
                "ok": "[green]OK[/green]",
                "warn": "[yellow]WARN[/yellow]",
                "fail": "[red]FAIL[/red]",
            }.get(result.status, result.status)
            table.add_row(result.name, label, result.detail, result.fix or "-")
        console.print(table)
        console.print()


def doctor(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            help="Workspace de un servicio para validar insumos legacy y metadata local.",
        ),
    ] = None,
    project: Annotated[
        Path | None,
        typer.Option(
            "--project",
            help="Proyecto Gradle a validar para plugin/build corporativo.",
        ),
    ] = None,
    probe_build: Annotated[
        bool,
        typer.Option(
            "--probe-build/--no-probe-build",
            help="Intenta resolver el build/plugin corporativo del proyecto indicado.",
        ),
    ] = False,
) -> None:
    """Clasifica si la maquina esta READY o en algun estado BLOCKED_*."""
    report = run_doctor(workspace=workspace, project=project, probe_build=probe_build)
    _render_summary(report, workspace, project)
    console.print()
    _render_categories(report.categories)
    console.print(
        f"[bold]{report.classification}[/bold] · {report.total_ok} OK · "
        f"{report.total_warn} WARN · {report.total_fail} FAIL"
    )

    if report.classification != "READY":
        raise typer.Exit(1)
