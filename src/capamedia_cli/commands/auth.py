"""capamedia auth - bootstrap no interactivo de credenciales para batch."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

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


def _write_env_file(path: Path, payload: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in payload.items() if value]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


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
