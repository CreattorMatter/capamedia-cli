"""capamedia check-install - verifica el toolchain completo.

Agrupa los chequeos por categoria:
  - Toolchain base (Git, Java, Gradle, Node, Codex, Python, uv)
  - IDE + extensions
  - Integraciones del banco (Azure DevOps, Fabrics, SonarCloud)
  - Auth de Codex
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from capamedia_cli.commands.fabrics import inspect_fabrics_workspace
from capamedia_cli.core.auth import AZURE_PAT_ENV_VARS, OPENAI_API_KEY_ENV_VARS, resolve_azure_devops_pat

console = Console()


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # "ok", "warn", "fail"
    detail: str
    fix: str = ""


def _run_command(cmd: list[str]) -> tuple[bool, str]:
    """Run a command and return (success, first line of output)."""
    if shutil.which(cmd[0]) is None:
        return False, ""
    try:
        result = subprocess.run(cmd, capture_output=True, check=False, timeout=10, text=True)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, ""
    output = (result.stdout or result.stderr or "").strip().splitlines()
    return result.returncode == 0, (output[0] if output else "")


def _check_git() -> CheckResult:
    ok, ver = _run_command(["git", "--version"])
    if ok:
        return CheckResult("Git", "ok", ver)
    return CheckResult("Git", "fail", "no instalado", "capamedia install")


def _check_java() -> CheckResult:
    ok, ver = _run_command(["java", "-version"])
    if not ok:
        return CheckResult("Java", "fail", "no instalado", "capamedia install")
    if "21" not in ver:
        return CheckResult("Java", "warn", f"{ver} (se recomienda Java 21)", "instalar Eclipse Temurin 21")
    return CheckResult("Java", "ok", ver)


def _check_gradle() -> CheckResult:
    ok, ver = _run_command(["gradle", "--version"])
    if ok:
        return CheckResult("Gradle", "ok", ver)
    return CheckResult("Gradle", "fail", "no instalado", "capamedia install")


def _check_node() -> CheckResult:
    ok, ver = _run_command(["node", "--version"])
    if not ok:
        return CheckResult("Node.js", "fail", "no instalado (requerido por MCP Fabrics)", "capamedia install")
    return CheckResult("Node.js", "ok", ver)


def _check_codex() -> CheckResult:
    ok, ver = _run_command(["codex", "--version"])
    if ok:
        return CheckResult("Codex CLI", "ok", ver)
    return CheckResult(
        "Codex CLI",
        "fail",
        "no instalado (requerido por batch migrate/pipeline)",
        "capamedia install",
    )


def _check_python() -> CheckResult:
    ok, ver = _run_command(["python", "--version"])
    if not ok:
        return CheckResult("Python", "fail", "no instalado", "capamedia install")
    return CheckResult("Python", "ok", ver)


def _check_uv() -> CheckResult:
    ok, ver = _run_command(["uv", "--version"])
    if ok:
        return CheckResult("uv", "ok", ver)
    return CheckResult("uv", "warn", "no instalado (opcional pero recomendado)", "capamedia install")


def _check_vscode() -> CheckResult:
    ok, ver = _run_command(["code", "--version"])
    if ok:
        return CheckResult("VS Code", "ok", ver)
    return CheckResult("VS Code", "warn", "no detectado (podes usar Cursor/Windsurf/IntelliJ)", "")


def _check_sonarlint_extension() -> CheckResult:
    """Check if SonarQube for IDE extension is installed in VS Code."""
    if shutil.which("code") is None:
        return CheckResult("SonarQube for IDE (VS Code ext)", "warn", "VS Code no detectado", "")
    try:
        result = subprocess.run(
            ["code", "--list-extensions"],
            capture_output=True,
            check=False,
            timeout=15,
            text=True,
        )
        if "SonarSource.sonarlint-vscode" in (result.stdout or ""):
            return CheckResult("SonarQube for IDE (VS Code ext)", "ok", "instalado")
        return CheckResult(
            "SonarQube for IDE (VS Code ext)",
            "fail",
            "no instalado",
            "code --install-extension SonarSource.sonarlint-vscode",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CheckResult("SonarQube for IDE (VS Code ext)", "warn", "no pudo verificarse", "")


def _check_mcp_fabrics_config() -> CheckResult:
    """Check Fabrics using the same preflight logic que usa batch pipeline."""
    status = inspect_fabrics_workspace(Path.cwd())
    if status["status"] == "ok":
        return CheckResult("MCP Fabrics", "ok", status["detail"])
    return CheckResult(
        "MCP Fabrics",
        "fail",
        status["detail"],
        "capamedia auth bootstrap --scope global o capamedia fabrics setup",
    )


def _check_azure_devops_auth() -> CheckResult:
    """Check env-based PAT first, then Git Credential Manager."""
    pat = resolve_azure_devops_pat()
    if pat:
        return CheckResult(
            "Azure DevOps auth",
            "ok",
            f"PAT presente por env ({'/'.join(AZURE_PAT_ENV_VARS)})",
        )

    try:
        input_text = "protocol=https\nhost=dev.azure.com\npath=BancoPichinchaEC\n\n"
        result = subprocess.run(
            ["git", "credential-manager", "get"],
            input=input_text,
            capture_output=True,
            check=False,
            timeout=10,
            text=True,
        )
        if result.returncode == 0 and "password=" in (result.stdout or ""):
            return CheckResult("Azure DevOps auth", "ok", "token valido en Git Credential Manager")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return CheckResult(
        "Azure DevOps auth",
        "fail",
        "sin PAT por env y sin token usable en Git Credential Manager",
        "export CAPAMEDIA_AZDO_PAT=... o corre `git clone https://dev.azure.com/...` una vez",
    )


def _check_codex_auth() -> CheckResult:
    ok, detail = _run_command(["codex", "login", "status"])
    if ok:
        return CheckResult("Codex auth", "ok", detail)
    return CheckResult(
        "Codex auth",
        "fail",
        f"sin login activo (tambien podes bootstrapear por API key en {'/'.join(OPENAI_API_KEY_ENV_VARS)})",
        "capamedia auth bootstrap --openai-api-key ...",
    )


def _check_sonarcloud_binding() -> CheckResult:
    """Check if current workspace has a SonarCloud binding."""
    binding = Path.cwd() / ".sonarlint" / "connectedMode.json"
    if not binding.exists():
        return CheckResult(
            "SonarCloud binding",
            "warn",
            "no hay binding en este workspace",
            "abri VS Code y Share Configuration desde SonarQube",
        )
    try:
        data = json.loads(binding.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CheckResult("SonarCloud binding", "fail", "archivo corrupto", "")
    org = data.get("sonarCloudOrganization", "")
    if org != "bancopichinchaec":
        return CheckResult(
            "SonarCloud binding",
            "fail",
            f"organizacion incorrecta: {org}",
            "debe ser 'bancopichinchaec' literal",
        )
    project = data.get("projectKey", "")
    if not project or "<" in project:
        return CheckResult(
            "SonarCloud binding",
            "warn",
            "projectKey es placeholder",
            "reemplaza con el UUID real del proyecto en SonarCloud",
        )
    return CheckResult("SonarCloud binding", "ok", f"org=bancopichinchaec, project={project[:12]}...")


CHECKS = {
    "Toolchain base": [
        _check_git,
        _check_java,
        _check_gradle,
        _check_node,
        _check_codex,
        _check_python,
        _check_uv,
    ],
    "IDE y extensions": [
        _check_vscode,
        _check_sonarlint_extension,
    ],
    "Integraciones y auth": [
        _check_azure_devops_auth,
        _check_mcp_fabrics_config,
        _check_codex_auth,
        _check_sonarcloud_binding,
    ],
}


def check_install() -> None:
    """Verifica el estado de todo el toolchain para trabajar con CapaMedia."""
    total_ok = 0
    total_warn = 0
    total_fail = 0

    for category, checks in CHECKS.items():
        table = Table(title=category, title_style="bold cyan", show_lines=False)
        table.add_column("Componente", style="cyan", no_wrap=True)
        table.add_column("Estado", style="bold", width=6)
        table.add_column("Detalle")
        table.add_column("Fix sugerido", style="yellow")

        for check_fn in checks:
            result = check_fn()
            if result.status == "ok":
                total_ok += 1
                icon = "[green]OK[/green]"
            elif result.status == "warn":
                total_warn += 1
                icon = "[yellow]WARN[/yellow]"
            else:
                total_fail += 1
                icon = "[red]FAIL[/red]"
            table.add_row(result.name, icon, result.detail, result.fix or "-")

        console.print(table)
        console.print()

    summary_color = "green" if total_fail == 0 else "red"
    console.print(
        f"[bold {summary_color}]Resumen: {total_ok} OK · {total_warn} WARN · {total_fail} FAIL[/bold {summary_color}]"
    )

    if total_fail > 0:
        console.print(
            "[red]Hay bloqueos para arrancar. Corre los fixes sugeridos o re-ejecuta [bold]capamedia install[/bold].[/red]"
        )
        raise typer.Exit(1)

    if total_warn > 0:
        console.print(
            "[yellow]Hay warnings. El flujo funciona pero puede tener limitaciones. Revisa los fixes sugeridos.[/yellow]"
        )
        raise typer.Exit(0)

    console.print("[green]Todo OK. Estas listo para migrar.[/green]")
