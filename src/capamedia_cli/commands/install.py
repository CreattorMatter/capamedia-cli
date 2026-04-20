"""capamedia install - instala el toolchain completo para migraciones de Capa Media.

Detecta el sistema operativo y usa el gestor de paquetes apropiado:
  - Windows -> winget
  - macOS   -> brew
  - Linux   -> apt / dnf / pacman (detectado por distro)

Componentes automatizables:
  - Git (necesario para clone de repos Azure DevOps)
  - Java 21 (Eclipse Temurin)
  - Gradle 8.x
  - Node.js LTS (requerido por el MCP Fabrics via npx)
  - Python 3.12 (para este CLI mismo)
  - uv (gestor de paquetes Python)
  - VS Code (IDE principal soportado)
  - Extension SonarQube for IDE (si VS Code esta instalado)

Componentes NO automatizables (solo guia al usuario):
  - Azure DevOps PAT (login interactivo en navegador con GCM)
  - SonarCloud connected mode binding (login web)
  - MCP Fabrics token (requiere pegar token manualmente la primera vez)
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()


@dataclass(frozen=True)
class Package:
    """A package that can be auto-installed via a package manager."""

    name: str
    check_command: list[str]
    winget_id: str | None = None
    brew_id: str | None = None
    apt_id: str | None = None
    optional: bool = False
    note: str = ""

    def is_installed(self) -> bool:
        exe = self.check_command[0]
        if shutil.which(exe) is None:
            return False
        try:
            subprocess.run(
                self.check_command,
                capture_output=True,
                check=False,
                timeout=10,
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False


PACKAGES: list[Package] = [
    Package(
        name="Git",
        check_command=["git", "--version"],
        winget_id="Git.Git",
        brew_id="git",
        apt_id="git",
    ),
    Package(
        name="Java 21 (Eclipse Temurin)",
        check_command=["java", "-version"],
        winget_id="EclipseAdoptium.Temurin.21.JDK",
        brew_id="--cask temurin@21",
        apt_id="openjdk-21-jdk",
    ),
    Package(
        name="Gradle",
        check_command=["gradle", "--version"],
        winget_id="Gradle.Gradle",
        brew_id="gradle",
        apt_id="gradle",
    ),
    Package(
        name="Node.js LTS (requerido para MCP Fabrics via npx)",
        check_command=["node", "--version"],
        winget_id="OpenJS.NodeJS.LTS",
        brew_id="node@20",
        apt_id="nodejs",
    ),
    Package(
        name="Python 3.12",
        check_command=["python", "--version"],
        winget_id="Python.Python.3.12",
        brew_id="python@3.12",
        apt_id="python3.12",
    ),
    Package(
        name="uv (Python package manager)",
        check_command=["uv", "--version"],
        winget_id="astral-sh.uv",
        brew_id="uv",
        apt_id=None,
        note="Linux: instalar con 'curl -LsSf https://astral.sh/uv/install.sh | sh'",
    ),
    Package(
        name="VS Code",
        check_command=["code", "--version"],
        winget_id="Microsoft.VisualStudioCode",
        brew_id="--cask visual-studio-code",
        apt_id=None,
        optional=True,
        note="Opcional: cualquier IDE compatible (Cursor, Windsurf, IntelliJ) sirve",
    ),
    Package(
        name="Docker Desktop",
        check_command=["docker", "--version"],
        winget_id="Docker.DockerDesktop",
        brew_id="--cask docker",
        apt_id="docker.io",
        optional=True,
        note="Opcional: solo si queres build local de imagen. Tests locales corren sin Docker.",
    ),
]


def _detect_os() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


def _get_installer_command(package: Package, os_name: str) -> list[str] | None:
    if os_name == "windows" and package.winget_id:
        return ["winget", "install", "--id", package.winget_id, "--accept-source-agreements", "--accept-package-agreements", "-e"]
    if os_name == "macos" and package.brew_id:
        parts = package.brew_id.split()
        return ["brew", "install", *parts]
    if os_name == "linux" and package.apt_id:
        return ["sudo", "apt-get", "install", "-y", package.apt_id]
    return None


def _install_sonarlint_extension() -> bool:
    """Install SonarQube for IDE extension in VS Code if code CLI is available."""
    if shutil.which("code") is None:
        return False
    try:
        result = subprocess.run(
            ["code", "--install-extension", "SonarSource.sonarlint-vscode"],
            capture_output=True,
            check=False,
            timeout=120,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install_toolchain(
    skip_optional: bool = typer.Option(
        False,
        "--skip-optional",
        help="No intentar instalar componentes opcionales (VS Code, Docker)",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="No pedir confirmacion antes de instalar",
    ),
) -> None:
    """Instala el toolchain completo para migraciones de Capa Media."""
    os_name = _detect_os()
    console.print(
        Panel.fit(
            f"[bold]CapaMedia - Install Toolchain[/bold]\nSistema detectado: [cyan]{os_name}[/cyan]",
            border_style="cyan",
        )
    )

    # Scan what's installed
    table = Table(title="Estado actual del toolchain", show_lines=False)
    table.add_column("Componente", style="cyan")
    table.add_column("Estado", style="bold")
    table.add_column("Accion", style="yellow")

    to_install: list[Package] = []
    for pkg in PACKAGES:
        if pkg.optional and skip_optional:
            table.add_row(pkg.name, "[dim]saltado[/dim]", "--skip-optional")
            continue
        if pkg.is_installed():
            table.add_row(pkg.name, "[green]OK[/green]", "-")
            continue
        cmd = _get_installer_command(pkg, os_name)
        if cmd:
            table.add_row(pkg.name, "[red]falta[/red]", f"instalar via {cmd[0]}")
            to_install.append(pkg)
        else:
            table.add_row(pkg.name, "[red]falta[/red]", f"manual ({pkg.note})")

    console.print(table)

    if not to_install:
        console.print("\n[bold green]Todo el toolchain automatizable ya esta instalado.[/bold green]")
        _print_manual_steps()
        raise typer.Exit(0)

    if not yes:
        confirm = typer.confirm(
            f"\nInstalar {len(to_install)} componente(s) faltante(s)?",
            default=True,
        )
        if not confirm:
            console.print("[yellow]Cancelado por el usuario.[/yellow]")
            raise typer.Exit(1)

    # Install
    failures: list[str] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for pkg in to_install:
            cmd = _get_installer_command(pkg, os_name)
            if cmd is None:
                continue
            task = progress.add_task(f"Instalando {pkg.name}...", total=None)
            try:
                result = subprocess.run(cmd, capture_output=True, check=False, timeout=600)
                if result.returncode != 0:
                    failures.append(pkg.name)
                progress.update(task, completed=1)
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                failures.append(f"{pkg.name} ({e})")
                progress.update(task, completed=1)

    # SonarLint extension (if VS Code available)
    if shutil.which("code"):
        console.print("\nInstalando extension SonarQube for IDE en VS Code...")
        if _install_sonarlint_extension():
            console.print("[green]  OK SonarQube for IDE instalado[/green]")
        else:
            console.print("[yellow]  Fallo la instalacion de la extension (reintentar manual)[/yellow]")

    if failures:
        console.print(f"\n[red]Fallaron {len(failures)} instalaciones:[/red]")
        for f in failures:
            console.print(f"  [red]- {f}[/red]")
        console.print("Reintenta manualmente o consulta los docs del paquete.")
    else:
        console.print("\n[bold green]Toolchain instalado correctamente.[/bold green]")

    # Mostrar estado del cache del MCP Fabrics
    console.print()
    _check_mcp_fabrics_cache()

    _print_manual_steps()


def _check_mcp_fabrics_cache() -> None:
    """Informa si el MCP Fabrics ya esta cacheado en npx.

    No intenta descargarlo (requiere .npmrc valido que quiza no lo este).
    Solo verifica si existe el cache. El usuario puede forzar el cache despues
    con `capamedia fabrics setup --refresh-npmrc` + `npx @pichincha/fabrics-project --version`.
    """
    from capamedia_cli.core.mcp_launcher import _find_cached_mcp

    cached = _find_cached_mcp()
    if cached:
        console.print(f"[green]MCP Fabrics cacheado:[/green] {cached}")
    else:
        console.print(
            "[yellow]MCP Fabrics no cacheado[/yellow] (el primer `capamedia fabrics generate` lo bajara)"
        )


def _print_manual_steps() -> None:
    """Imprime la guia de los pasos manuales que el CLI no puede automatizar."""
    console.print()
    console.print(
        Panel(
            (
                "[bold]Pasos manuales (no automatizables):[/bold]\n\n"
                "1. [cyan]Azure DevOps PAT[/cyan] (para clone de repos del banco)\n"
                "   -> corre: git clone https://dev.azure.com/BancoPichinchaEC/_git/<cualquiera>\n"
                "      el navegador abre, login con creds del banco, GCM guarda el PAT\n\n"
                "2. [cyan]SonarCloud binding[/cyan]\n"
                "   -> abri VS Code, ve al sidebar de SonarQube\n"
                "   -> 'Add SonarQube Cloud Connection' - login con Azure DevOps\n"
                "   -> nombre de conexion: [bold]bancopichinchaec[/bold] (literal)\n\n"
                "3. [cyan]MCP Fabrics token[/cyan]\n"
                "   -> corre: [bold]capamedia fabrics setup[/bold]\n"
                "      (te guia para registrar el MCP en ~/.claude/settings.json)\n\n"
                "Despues de los 3 pasos, verifica todo con:\n"
                "   [bold]capamedia check-install[/bold]"
            ),
            border_style="yellow",
            title="Pasos manuales",
        )
    )
