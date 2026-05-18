"""capamedia auth - bootstrap no interactivo de credenciales para batch."""

from __future__ import annotations

import os
import shutil
import subprocess
from base64 import b64encode
from pathlib import Path
from typing import Annotated, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli.commands import fabrics
from capamedia_cli.core.auth import (
    AZURE_PAT_ENV_VARS,
    OPENAI_API_KEY_ENV_VARS,
    resolve_artifact_token,
    resolve_azure_devops_pat,
    resolve_openai_api_key,
)

console = Console()

app = typer.Typer(
    help="Bootstrap de credenciales para Fabrics, Azure DevOps y Codex.",
    no_args_is_help=True,
)

AZURE_DEVOPS_PROBE_URL = "https://dev.azure.com/BancoPichinchaEC/_apis/projects?api-version=7.1"
AZURE_ARTIFACTS_PROBE_URL = (
    "https://feeds.dev.azure.com/BancoPichinchaEC/arq-framework/"
    "_apis/packaging/Feeds/Framework?api-version=7.1-preview.1"
)


def _write_env_file(path: Path, payload: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in payload.items() if value]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _clean_env_payload(payload: dict[str, str | None]) -> dict[str, str]:
    return {key: value.strip() for key, value in payload.items() if value and value.strip()}


def _persist_user_environment(values: dict[str, str]) -> None:
    """Persist environment variables for future shells under the current user.

    Windows is the primary target for the VDI flow, so we write HKCU\\Environment
    directly instead of shelling out to `setx` with secrets in argv. On Unix-like
    systems we write a dotenv-compatible file under ~/.capamedia/user.env.
    """
    clean = _clean_env_payload(values)
    if not clean:
        return

    if os.name == "nt":
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            for name, value in clean.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                os.environ[name] = value
        _broadcast_windows_environment_change()
        return

    env_file = Path.home() / ".capamedia" / "user.env"
    existing: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            existing[key.strip()] = value.strip()
    existing.update(clean)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "\n".join(f"{key}={value}" for key, value in sorted(existing.items())) + "\n",
        encoding="utf-8",
    )
    try:
        env_file.chmod(0o600)
    except OSError:
        pass
    os.environ.update(clean)


def _split_path(value: str, sep: str) -> list[str]:
    return [part for part in value.split(sep) if part]


def _merge_path_entries(current: str, entries: Iterable[Path], sep: str = os.pathsep) -> str:
    parts = _split_path(current, sep)
    seen = {part.casefold() if os.name == "nt" else part for part in parts}
    for entry in entries:
        raw = str(entry).strip()
        if not raw:
            continue
        normalized = str(Path(os.path.expandvars(raw)).expanduser())
        key = normalized.casefold() if os.name == "nt" else normalized
        if key in seen:
            continue
        parts.append(normalized)
        seen.add(key)
    return sep.join(parts)


def _append_user_path_entries(path_entries: list[Path]) -> None:
    if not path_entries:
        return

    if os.name == "nt":
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            "Environment",
            0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        ) as key:
            try:
                current, value_type = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                try:
                    current, value_type = winreg.QueryValueEx(key, "PATH")
                except FileNotFoundError:
                    current, value_type = "", winreg.REG_EXPAND_SZ
            merged = _merge_path_entries(str(current), path_entries, sep=";")
            winreg.SetValueEx(key, "Path", 0, value_type, merged)
            os.environ["PATH"] = _merge_path_entries(os.environ.get("PATH", ""), path_entries)
        _broadcast_windows_environment_change()
        return

    env_file = Path.home() / ".capamedia" / "path.sh"
    merged = _merge_path_entries(os.environ.get("PATH", ""), path_entries)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(f'export PATH="{merged}"\n', encoding="utf-8")
    os.environ["PATH"] = merged


def _broadcast_windows_environment_change() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        hwnd_broadcast = 0xFFFF
        wm_settingchange = 0x001A
        smto_abortifhung = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast,
            wm_settingchange,
            0,
            "Environment",
            smto_abortifhung,
            5000,
            None,
        )
    except Exception:
        # La persistencia ya quedo escrita; el broadcast solo evita reabrir sesion.
        pass


def _pat_auth_header(token: str) -> str:
    encoded = b64encode(f":{token}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _probe_pat_endpoint(name: str, url: str, token: str) -> tuple[str, str, str]:
    request = Request(
        url,
        headers={
            "Authorization": _pat_auth_header(token),
            "Accept": "application/json",
            "User-Agent": "capamedia-cli",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            status = int(response.status)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError(f"{name} rechazo el PAT ({exc.code}). Revisa permisos o expiracion.") from None
        raise RuntimeError(f"{name} devolvio HTTP {exc.code}.") from None
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"{name} no respondio: {reason}") from None
    except TimeoutError:
        raise RuntimeError(f"{name} no respondio antes del timeout.") from None

    if not 200 <= status < 300:
        raise RuntimeError(f"{name} devolvio HTTP {status}.")
    return (name, "ok", "PAT validado")


def _validate_pat_access(token: str) -> list[tuple[str, str, str]]:
    """Valida que el PAT sirva para los dos usos que configura `capamedia pat`."""
    return [
        _probe_pat_endpoint("Azure DevOps", AZURE_DEVOPS_PROBE_URL, token),
        _probe_pat_endpoint("Azure Artifacts", AZURE_ARTIFACTS_PROBE_URL, token),
    ]


def _print_pat_validation(results: list[tuple[str, str, str]]) -> None:
    table = Table(title="Prueba de PAT", title_style="bold cyan")
    table.add_column("Componente", style="cyan")
    table.add_column("Estado", style="bold")
    table.add_column("Detalle")
    for component, status, detail in results:
        label = "[green]OK[/green]" if status == "ok" else f"[red]{status.upper()}[/red]"
        table.add_row(component, label, detail)
    console.print()
    console.print(table)


def _codex_login_with_api_key(api_key: str) -> str:
    if shutil.which("codex") is None:
        raise RuntimeError("codex no esta instalado; corre `capamedia install` primero")

    result = subprocess.run(
        ["codex", "login", "--with-api-key"],
        input=api_key + "\n",
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "login fallido").strip()
        raise RuntimeError(detail.splitlines()[-1] if detail else "login fallido")

    status = subprocess.run(
        ["codex", "login", "status"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=os.environ.copy(),
    )
    if status.returncode != 0:
        detail = (status.stderr or status.stdout or "no pude verificar el login").strip()
        raise RuntimeError(detail.splitlines()[-1] if detail else "no pude verificar el login")
    return (status.stdout or status.stderr or "login ok").strip().splitlines()[0]


@app.command("configure-user")
def configure_user(
    artifact_token: Annotated[
        str | None,
        typer.Option(
            "--artifact-token",
            "--token",
            help="Azure Artifacts PAT para Fabrics/NPM. Si se omite, usa CAPAMEDIA_ARTIFACT_TOKEN/ARTIFACT_TOKEN.",
        ),
    ] = None,
    azure_pat: Annotated[
        str | None,
        typer.Option(
            "--azure-pat",
            "--pat",
            "--personal-access-token",
            help="Azure DevOps PAT para clones unattended. Si se omite, usa CAPAMEDIA_AZDO_PAT/AZURE_DEVOPS_EXT_PAT.",
        ),
    ] = None,
    path_entries: Annotated[
        list[Path] | None,
        typer.Option(
            "--path",
            help="Entrada para agregar al PATH del usuario. Repetible.",
        ),
    ] = None,
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            "-s",
            help="Donde registrar Fabrics si hay artifact token: 'global' (~/.mcp.json) o 'project' (./.mcp.json)",
        ),
    ] = "global",
    configure_fabrics: Annotated[
        bool,
        typer.Option(
            "--configure-fabrics/--no-configure-fabrics",
            help="Registra MCP Fabrics y refresca ~/.npmrc cuando hay artifact token.",
        ),
    ] = True,
    refresh_npmrc: Annotated[
        bool,
        typer.Option(
            "--refresh-npmrc/--no-refresh-npmrc",
            help="Actualiza ~/.npmrc al registrar Fabrics.",
        ),
    ] = True,
    force: Annotated[
        bool,
        typer.Option("--force/--no-force", help="Sobrescribe configuracion Fabrics existente"),
    ] = True,
) -> None:
    """Configura credenciales y PATH persistentes para el usuario actual."""
    resolved_artifact = resolve_artifact_token(artifact_token)
    resolved_azure = resolve_azure_devops_pat(azure_pat)
    paths = path_entries or []

    if not any((resolved_artifact, resolved_azure, paths)):
        console.print(
            "[red]Error:[/red] no recibi token/PAT ni PATH. "
            "Usa `--token`, `--pat` y/o `--path`."
        )
        raise typer.Exit(1)

    console.print(
        Panel.fit(
            "[bold]CapaMedia auth configure-user[/bold]\n"
            "Configura credenciales persistentes del usuario actual sin imprimir secretos.",
            border_style="cyan",
        )
    )

    env_payload: dict[str, str] = {}
    if resolved_artifact:
        env_payload["CAPAMEDIA_ARTIFACT_TOKEN"] = resolved_artifact
        env_payload["ARTIFACT_TOKEN"] = resolved_artifact
    if resolved_azure:
        env_payload["CAPAMEDIA_AZDO_PAT"] = resolved_azure
        env_payload["AZURE_DEVOPS_EXT_PAT"] = resolved_azure

    results: list[tuple[str, str, str]] = []

    if env_payload:
        _persist_user_environment(env_payload)
        labels = ", ".join(env_payload.keys())
        results.append(("User env", "ok", f"variables persistidas: {labels}"))

    if paths:
        _append_user_path_entries(paths)
        results.append(("PATH usuario", "ok", f"{len(paths)} entrada(s) procesada(s)"))

    if configure_fabrics and resolved_artifact:
        try:
            fabrics.setup(
                scope=scope,
                token=resolved_artifact,
                force=force,
                refresh_npmrc=refresh_npmrc,
            )
            results.append(("Fabrics", "ok", f"registrado en scope={scope}"))
        except typer.Exit:
            results.append(("Fabrics", "fail", "setup fallo"))
            raise
    elif configure_fabrics and not resolved_artifact:
        results.append(("Fabrics", "skip", "sin artifact token"))

    table = Table(title="User auth config", title_style="bold cyan")
    table.add_column("Componente", style="cyan")
    table.add_column("Estado", style="bold")
    table.add_column("Detalle")
    for component, status, detail in results:
        label = {
            "ok": "[green]OK[/green]",
            "skip": "[yellow]SKIP[/yellow]",
            "fail": "[red]FAIL[/red]",
        }.get(status, status)
        table.add_row(component, label, detail)
    console.print()
    console.print(table)
    console.print(
        "\n[dim]Nota: las variables de usuario aplican a terminales nuevas. "
        "Si una terminal ya estaba abierta, cerrala y abrila de nuevo.[/dim]"
    )


def pat(
    personal_access_token: Annotated[
        str,
        typer.Argument(
            help="Personal Access Token unico para Azure Artifacts y Azure DevOps.",
        ),
    ],
    path_entries: Annotated[
        list[Path] | None,
        typer.Option(
            "--path",
            help="Entrada para agregar al PATH del usuario. Repetible.",
        ),
    ] = None,
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            "-s",
            help="Donde registrar Fabrics: 'global' (~/.mcp.json) o 'project' (./.mcp.json)",
        ),
    ] = "global",
    configure_fabrics: Annotated[
        bool,
        typer.Option(
            "--configure-fabrics/--no-configure-fabrics",
            help="Registra MCP Fabrics y refresca ~/.npmrc.",
        ),
    ] = True,
    refresh_npmrc: Annotated[
        bool,
        typer.Option(
            "--refresh-npmrc/--no-refresh-npmrc",
            help="Actualiza ~/.npmrc al registrar Fabrics.",
        ),
    ] = True,
    force: Annotated[
        bool,
        typer.Option("--force/--no-force", help="Sobrescribe configuracion Fabrics existente"),
    ] = True,
) -> None:
    """Valida y configura CapaMedia usando un unico PAT con permisos amplios."""
    token = personal_access_token.strip()
    if not token:
        console.print("[red]Error:[/red] PAT vacio.")
        raise typer.Exit(1)

    try:
        validation_results = _validate_pat_access(token)
    except RuntimeError as exc:
        console.print(f"[red]FAIL[/red] Prueba de PAT: {exc}")
        raise typer.Exit(1) from None
    _print_pat_validation(validation_results)

    configure_user(
        artifact_token=token,
        azure_pat=token,
        path_entries=path_entries,
        scope=scope,
        configure_fabrics=configure_fabrics,
        refresh_npmrc=refresh_npmrc,
        force=force,
    )


@app.command("bootstrap")
def bootstrap(
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            "-s",
            help="Donde registrar Fabrics: 'global' (~/.mcp.json) o 'project' (./.mcp.json)",
        ),
    ] = "global",
    artifact_token: Annotated[
        str | None,
        typer.Option("--artifact-token", help="Azure Artifacts PAT para Fabrics"),
    ] = None,
    azure_pat: Annotated[
        str | None,
        typer.Option("--azure-pat", help="Azure DevOps PAT para git clone unattended"),
    ] = None,
    openai_api_key: Annotated[
        str | None,
        typer.Option("--openai-api-key", help="OpenAI API key para autenticar Codex CLI"),
    ] = None,
    env_file: Annotated[
        Path | None,
        typer.Option(
            "--env-file",
            help="Opcional: escribe un archivo dotenv con las credenciales resueltas",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force/--no-force", help="Sobrescribe configuracion Fabrics existente"),
    ] = True,
    refresh_npmrc: Annotated[
        bool,
        typer.Option(
            "--refresh-npmrc/--no-refresh-npmrc",
            help="Actualiza ~/.npmrc al registrar Fabrics",
        ),
    ] = True,
) -> None:
    """Prepara una maquina para correr batch pipeline sin prompts de credenciales."""
    resolved_artifact = resolve_artifact_token(artifact_token)
    resolved_azure = resolve_azure_devops_pat(azure_pat)
    resolved_openai = resolve_openai_api_key(openai_api_key)

    if not any((resolved_artifact, resolved_azure, resolved_openai, env_file)):
        console.print(
            "[red]Error:[/red] no recibi credenciales. "
            f"Usa opciones directas o las env vars {', '.join(AZURE_PAT_ENV_VARS + OPENAI_API_KEY_ENV_VARS + ('CAPAMEDIA_ARTIFACT_TOKEN',))}."
        )
        raise typer.Exit(1)

    console.print(
        Panel.fit(
            "[bold]CapaMedia auth bootstrap[/bold]\n"
            "Objetivo: dejar Fabrics, Azure DevOps y Codex listos para batch unattended.",
            border_style="cyan",
        )
    )

    results: list[tuple[str, str, str]] = []

    if resolved_artifact:
        try:
            fabrics.setup(
                scope=scope,
                token=resolved_artifact,
                force=force,
                refresh_npmrc=refresh_npmrc,
            )
            results.append(("Fabrics", "ok", f"registrado en scope={scope}"))
        except typer.Exit as exc:
            results.append(("Fabrics", "fail", f"setup fallo (exit {exc.exit_code})"))
            raise

    if resolved_openai:
        try:
            detail = _codex_login_with_api_key(resolved_openai)
            results.append(("Codex auth", "ok", detail))
        except RuntimeError as exc:
            results.append(("Codex auth", "fail", str(exc)))
            console.print(f"[red]FAIL[/red] {exc}")
            raise typer.Exit(1) from None

    if resolved_azure:
        results.append(
            (
                "Azure DevOps",
                "ok",
                "PAT detectado; `capamedia clone` usara auth por env sin prompts",
            )
        )

    if env_file:
        payload = {
            "CAPAMEDIA_ARTIFACT_TOKEN": resolved_artifact or "",
            "CAPAMEDIA_AZDO_PAT": resolved_azure or "",
            "OPENAI_API_KEY": resolved_openai or "",
        }
        written = _write_env_file(env_file, payload)
        results.append(("Env file", "ok", str(written)))

    table = Table(title="Bootstrap auth", title_style="bold cyan")
    table.add_column("Componente", style="cyan")
    table.add_column("Estado", style="bold")
    table.add_column("Detalle")
    for component, status, detail in results:
        label = {
            "ok": "[green]OK[/green]",
            "warn": "[yellow]WARN[/yellow]",
            "fail": "[red]FAIL[/red]",
        }.get(status, status)
        table.add_row(component, label, detail)
    console.print()
    console.print(table)

    if resolved_azure and not env_file:
        console.print()
        console.print(
            "[yellow]Recordatorio:[/yellow] el Azure PAT no se persiste solo. "
            "Dejalo exportado como `CAPAMEDIA_AZDO_PAT` en tu shell/runner o usa `--env-file`."
        )
