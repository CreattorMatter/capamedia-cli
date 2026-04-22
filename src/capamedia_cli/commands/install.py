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
  - Codex CLI (requerido por batch migrate / batch pipeline)
  - Python 3.12 (para este CLI mismo)
  - uv (gestor de paquetes Python)
  - VS Code (IDE principal soportado)
  - Extension SonarQube for IDE (si VS Code esta instalado)

Componentes parcialmente automatizables:
  - Azure DevOps PAT (via env CAPAMEDIA_AZDO_PAT o login interactivo/GCM)
  - Codex auth (via `capamedia auth bootstrap` o `codex login`)
  - MCP Fabrics token (via `capamedia auth bootstrap` o `capamedia fabrics setup`)

Componentes NO automatizables (solo guia al usuario):
  - SonarCloud connected mode binding (login web)
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()


@dataclass(frozen=True)
class Package:
    """A package that can be auto-installed via a package manager.

    `alternative_checks`: lista de (nombre_legible, check_command) que tambien
    satisfacen el requisito. Util para componentes con alternativas como
    Claude Code CLI vs Codex CLI — si alguno de los dos esta, la dependencia
    esta cumplida y no hay que instalar el otro.
    """

    name: str
    check_command: list[str]
    winget_id: str | None = None
    brew_id: str | None = None
    apt_id: str | None = None
    windows_install_command: list[str] | None = None
    macos_install_command: list[str] | None = None
    linux_install_command: list[str] | None = None
    optional: bool = False
    note: str = ""
    alternative_checks: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def _binary_responds(self, cmd: list[str] | tuple[str, ...]) -> bool:
        exe = cmd[0]
        if shutil.which(exe) is None:
            return False
        try:
            subprocess.run(
                list(cmd),
                capture_output=True,
                check=False,
                timeout=10,
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def detected_alternative(self) -> str | None:
        """Retorna el nombre legible de la alternativa detectada, o None."""
        if self._binary_responds(self.check_command):
            return None  # primario OK, sin alternativa
        for alt_name, alt_cmd in self.alternative_checks:
            if self._binary_responds(alt_cmd):
                return alt_name
        return None

    def is_installed(self) -> bool:
        """True si el primario o cualquier alternativa responde."""
        if self._binary_responds(self.check_command):
            return True
        return any(
            self._binary_responds(alt_cmd) for _, alt_cmd in self.alternative_checks
        )


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
        name="AI engine CLI (Claude Code o Codex)",
        # Primario: Codex (npm install automatico). Pero si el usuario ya
        # tiene Claude Code CLI, la dependencia esta cumplida y NO se
        # instala Codex — consume la suscripcion que ya tiene (Claude Max
        # o ChatGPT Plus/Pro; nunca tokens API pagos).
        check_command=["codex", "--version"],
        alternative_checks=(
            ("Claude Code CLI", ("claude", "--version")),
        ),
        windows_install_command=["npm", "install", "-g", "@openai/codex"],
        macos_install_command=["npm", "install", "-g", "@openai/codex"],
        linux_install_command=["npm", "install", "-g", "@openai/codex"],
        note=(
            "Si ya tenes Claude Code (`claude --version` responde), NO se "
            "instala Codex. Con uno alcanza. Despues hacer `claude login` "
            "o `codex login` con tu suscripcion."
        ),
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


# URLs de descarga manual para cuando ningun package manager responde.
# El user puede bajar el instalador directo desde la pagina oficial.
MANUAL_DOWNLOAD_URLS: dict[str, str] = {
    "Git": "https://git-scm.com/download/win",
    "Java 21 (Eclipse Temurin)": "https://adoptium.net/temurin/releases/?version=21",
    "Gradle": "https://gradle.org/releases/",
    "Node.js LTS (requerido para MCP Fabrics via npx)": "https://nodejs.org/en/download",
    "Python 3.12": "https://www.python.org/downloads/",
    "uv (Python package manager)": "https://astral.sh/uv/install.ps1",
    "VS Code": "https://code.visualstudio.com/download",
    "Docker Desktop": "https://www.docker.com/products/docker-desktop/",
}


def _winget_available() -> bool:
    return shutil.which("winget") is not None


def _scoop_available() -> bool:
    return shutil.which("scoop") is not None


def _choco_available() -> bool:
    return shutil.which("choco") is not None


def _get_installer_command(package: Package, os_name: str) -> list[str] | None:
    """Devuelve el comando de install apropiado segun OS + package manager
    disponible. Prioridad en Windows: winget > scoop > choco."""
    if os_name == "windows" and package.windows_install_command:
        return package.windows_install_command
    if os_name == "macos" and package.macos_install_command:
        return package.macos_install_command
    if os_name == "linux" and package.linux_install_command:
        return package.linux_install_command

    if os_name == "windows":
        if package.winget_id and _winget_available():
            return [
                "winget",
                "install",
                "--id",
                package.winget_id,
                "--accept-source-agreements",
                "--accept-package-agreements",
                "-e",
            ]
        # Fallback a scoop si winget no esta
        if package.winget_id and _scoop_available():
            # scoop usa nombres propios, no winget IDs. Heuristica por id comun.
            scoop_name = {
                "Gradle.Gradle": "gradle",
                "Microsoft.VisualStudioCode": "vscode",
                "Git.Git": "git",
                "OpenJS.NodeJS.LTS": "nodejs-lts",
                "Docker.DockerDesktop": "docker",
                "EclipseAdoptium.Temurin.21.JDK": "temurin21-jdk",
                "astral-sh.uv": "uv",
                "Python.Python.3.12": "python",
            }.get(package.winget_id)
            if scoop_name:
                return ["scoop", "install", scoop_name]
        # Fallback a choco si ni winget ni scoop
        if package.winget_id and _choco_available():
            choco_name = {
                "Gradle.Gradle": "gradle",
                "Microsoft.VisualStudioCode": "vscode",
                "Git.Git": "git",
                "OpenJS.NodeJS.LTS": "nodejs-lts",
                "Docker.DockerDesktop": "docker-desktop",
                "EclipseAdoptium.Temurin.21.JDK": "temurin21",
            }.get(package.winget_id)
            if choco_name:
                return ["choco", "install", "-y", choco_name]
        return None
    if os_name == "macos" and package.brew_id:
        parts = package.brew_id.split()
        return ["brew", "install", *parts]
    if os_name == "linux" and package.apt_id:
        return ["sudo", "apt-get", "install", "-y", package.apt_id]
    return None


def _ensure_winget_on_windows() -> bool:
    """En Windows: si winget no esta, intenta instalarlo automatico
    descargando el `App Installer` (.msixbundle) desde https://aka.ms/getwinget
    y registrandolo con `Add-AppxPackage`. Si falla, retorna False y el
    caller cae al fallback (scoop / choco / URLs manuales).

    Solo intenta en Windows. En macOS/Linux no aplica (no existe winget).
    """
    if platform.system().lower() != "windows":
        return False
    if _winget_available():
        return True

    console.print(
        "[yellow]winget no encontrado. Intentando instalarlo "
        "automaticamente (App Installer)...[/yellow]"
    )

    ps_script = (
        "$ProgressPreference = 'silentlyContinue'; "
        "$tmp = Join-Path $env:TEMP 'winget-appinstaller.msixbundle'; "
        "Invoke-WebRequest -Uri https://aka.ms/getwinget -OutFile $tmp; "
        "Add-AppxPackage -Path $tmp"
    )
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script,
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        console.print(f"  [red]Error invocando PowerShell: {exc}[/red]")
        _print_manual_winget_install()
        return False

    if result.returncode == 0 and _winget_available():
        console.print("  [green]OK[/green] winget instalado correctamente.")
        return True

    err = (result.stderr or "").strip()[:300]
    console.print(
        "  [red]No se pudo instalar winget automatico[/red]"
        + (f" ({err})" if err else "")
    )
    _print_manual_winget_install()
    return False


def _print_manual_winget_install() -> None:
    console.print(
        "\n[yellow]Instalar winget manual:[/yellow]\n"
        "  Opcion A - Microsoft Store:\n"
        "    1. Abri Microsoft Store\n"
        "    2. Busca 'App Installer' (publisher: Microsoft Corporation)\n"
        "    3. Install / Update\n"
        "  Opcion B - PowerShell (copiar/pegar):\n"
        "    $ProgressPreference='silentlyContinue'\n"
        "    Invoke-WebRequest -Uri https://aka.ms/getwinget -OutFile $env:TEMP\\wg.msixbundle\n"
        "    Add-AppxPackage $env:TEMP\\wg.msixbundle\n"
        "  Opcion C - scoop (alternativa):\n"
        "    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned\n"
        "    irm get.scoop.sh | iex\n"
    )


def _warn_if_no_package_manager(os_name: str) -> None:
    """Imprime warning arriba de la tabla si no hay package manager disponible.

    En Windows, antes del warning intenta auto-instalar winget. Si el intento
    es exitoso, el warning no se imprime (el flujo sigue normal).
    """
    if os_name != "windows":
        return

    # Intento auto-install de winget si falta
    if not _winget_available():
        _ensure_winget_on_windows()

    # Re-evaluar tras el intento
    if _winget_available() or _scoop_available() or _choco_available():
        return
    console.print(
        "[yellow]ATENCION:[/yellow] no hay `winget`, `scoop` ni `choco` "
        "disponibles. Los paquetes faltantes van a requerir descarga "
        "MANUAL. La tabla va a mostrar la URL de cada uno.\n"
    )


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

    _warn_if_no_package_manager(os_name)

    # Scan what's installed
    table = Table(title="Estado actual del toolchain", show_lines=False)
    table.add_column("Componente", style="cyan")
    table.add_column("Estado", style="bold")
    table.add_column("Accion", style="yellow")

    manual_downloads: list[tuple[str, str]] = []

    to_install: list[Package] = []
    for pkg in PACKAGES:
        if pkg.optional and skip_optional:
            table.add_row(pkg.name, "[dim]saltado[/dim]", "--skip-optional")
            continue
        if pkg.is_installed():
            alt = pkg.detected_alternative()
            action = f"[dim]{alt} detectado[/dim]" if alt else "-"
            table.add_row(pkg.name, "[green]OK[/green]", action)
            continue
        cmd = _get_installer_command(pkg, os_name)
        if cmd:
            table.add_row(pkg.name, "[red]falta[/red]", f"instalar via {cmd[0]}")
            to_install.append(pkg)
        else:
            url = MANUAL_DOWNLOAD_URLS.get(pkg.name, "")
            if url:
                table.add_row(
                    pkg.name, "[red]falta[/red]", f"MANUAL: {url}"
                )
                manual_downloads.append((pkg.name, url))
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

        # Dar URLs de descarga manual para los que fallaron
        failed_names = {
            f.split(" (")[0] for f in failures
        }  # quitar " (error)" del final
        manual_retry: list[tuple[str, str]] = [
            (pkg.name, MANUAL_DOWNLOAD_URLS[pkg.name])
            for pkg in PACKAGES
            if pkg.name in failed_names and pkg.name in MANUAL_DOWNLOAD_URLS
        ]
        if manual_retry:
            console.print(
                "\n[bold yellow]Descarga manual (pegar URL en el browser):[/bold yellow]"
            )
            for name, url in manual_retry:
                console.print(f"  [cyan]{name}[/cyan]: {url}")
            console.print(
                "\n[dim]Tip: si todos los fallos son 'WinError 2: archivo no "
                "encontrado', te falta el package manager (winget/scoop/choco). "
                "Instala uno o descarga manual con las URLs de arriba.[/dim]"
            )
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
                "1. [cyan]Auth bootstrap[/cyan] (recomendado para correr batch unattended)\n"
                "   -> corre: [bold]capamedia auth bootstrap --scope global[/bold]\n"
                "      y pasa `--artifact-token` y `--azure-pat` (los 2 PATs de Azure DevOps)\n"
                "      No se necesita OpenAI API key: el engine headless consume la\n"
                "      suscripcion del usuario (Claude Max o ChatGPT Plus/Pro).\n"
                "      Hacer `claude login` o `codex login` UNA vez antes del bootstrap.\n\n"
                "2. [cyan]SonarCloud binding[/cyan]\n"
                "   -> abri VS Code, ve al sidebar de SonarQube\n"
                "   -> 'Add SonarQube Cloud Connection' - login con Azure DevOps\n"
                "   -> nombre de conexion: [bold]bancopichinchaec[/bold] (literal)\n\n"
                "Despues del bootstrap y del binding, verifica todo con:\n"
                "   [bold]capamedia check-install[/bold]"
            ),
            border_style="yellow",
            title="Pasos manuales",
        )
    )
