"""capamedia setup - bootstrap de maquina runner."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli.commands import auth, doctor, install
from capamedia_cli.core.machine_config import (
    default_auth_env_path,
    default_machine_config_path,
    default_queue_dir,
    load_machine_config,
    machine_config_defaults,
    write_machine_config,
)

console = Console()

app = typer.Typer(
    help="Bootstrap de maquina runner para la fabrica automatica.",
    no_args_is_help=True,
)


def _build_machine_payload(
    existing: dict[str, Any],
    *,
    provider: str,
    auth_mode: str,
    scope: str,
    workspace_root: Path,
    queue_dir: Path,
    env_file: Path,
    codex_bin: str,
    claude_bin: str,
    codex_model: str,
    claude_model: str,
    workers: int,
    namespace: str,
    group_id: str,
    timeout_minutes: int,
    retries: int,
    follow_interval_seconds: int,
    skip_optional_install: bool,
    run_check: bool,
) -> dict[str, Any]:
    payload = dict(existing)
    payload["provider"] = provider
    payload["auth_mode"] = auth_mode
    payload["scope"] = scope
    payload["workspace_root"] = str(workspace_root)
    payload["queue_dir"] = str(queue_dir)
    payload["env_file"] = str(env_file)
    payload.setdefault("defaults", {})
    payload["defaults"].update(
        {
            "workers": workers,
            "namespace": namespace,
            "group_id": group_id,
            "timeout_minutes": timeout_minutes,
            "retries": retries,
            "follow_interval_seconds": follow_interval_seconds,
            "skip_optional_install": skip_optional_install,
            "run_check": run_check,
        }
    )
    payload.setdefault("providers", {})
    payload["providers"].setdefault("codex", {})
    payload["providers"]["codex"].update(
        {
            "bin": codex_bin,
            "auth_mode": "api" if provider == "codex" and auth_mode == "api" else "session",
            "model": codex_model,
            "reasoning_effort": "high",
        }
    )
    payload["providers"].setdefault("claude", {})
    payload["providers"]["claude"].update(
        {
            "bin": claude_bin,
            "auth_mode": "session",
            "model": claude_model,
            "effort": "high",
            "permission_mode": "bypassPermissions",
        }
    )
    return payload


@app.command("machine")
def setup_machine(
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help="Runner principal de la fabrica: codex o claude.",
            case_sensitive=False,
        ),
    ] = "codex",
    auth_mode: Annotated[
        str,
        typer.Option(
            "--auth-mode",
            help="Modo de auth del runner principal: session o api.",
            case_sensitive=False,
        ),
    ] = "session",
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            help="Scope para MCPs y bootstrap: global o project.",
            case_sensitive=False,
        ),
    ] = "global",
    workspace_root: Annotated[
        Path | None,
        typer.Option(
            "--workspace-root",
            help="Root por defecto donde viven los workspaces/lotes del runner.",
        ),
    ] = None,
    queue_dir: Annotated[
        Path | None,
        typer.Option(
            "--queue-dir",
            help="Directorio machine-local para colas de servicios.",
        ),
    ] = None,
    env_file: Annotated[
        Path | None,
        typer.Option(
            "--env-file",
            help="dotenv machine-local para secretos del runner.",
        ),
    ] = None,
    artifact_token: Annotated[
        str | None,
        typer.Option("--artifact-token", help="Azure Artifacts PAT para Fabrics."),
    ] = None,
    azure_pat: Annotated[
        str | None,
        typer.Option("--azure-pat", help="Azure DevOps PAT para git unattended."),
    ] = None,
    codex_api_key: Annotated[
        str | None,
        typer.Option(
            "--codex-api-key",
            "--openai-api-key",
            help="API key opcional para Codex cuando auth_mode=api.",
        ),
    ] = None,
    codex_bin: Annotated[
        str,
        typer.Option("--codex-bin", help="Binario de Codex CLI."),
    ] = "codex",
    claude_bin: Annotated[
        str,
        typer.Option("--claude-bin", help="Binario de Claude Code CLI."),
    ] = "claude",
    codex_model: Annotated[
        str,
        typer.Option("--codex-model", help="Modelo por defecto para runner=codex."),
    ] = "gpt-5.4",
    claude_model: Annotated[
        str,
        typer.Option("--claude-model", help="Modelo por defecto para runner=claude."),
    ] = "opus",
    workers: Annotated[int, typer.Option("--workers", help="Workers default del worker.")] = 2,
    namespace: Annotated[str, typer.Option("--namespace", help="Namespace default de Fabrics.")] = "tnd",
    group_id: Annotated[str, typer.Option("--group-id", help="groupId default del arquetipo.")] = "com.pichincha.sp",
    timeout_minutes: Annotated[
        int,
        typer.Option("--timeout-minutes", help="Timeout default por servicio."),
    ] = 90,
    retries: Annotated[
        int,
        typer.Option("--retries", help="Reintentos default por servicio."),
    ] = 1,
    follow_interval_seconds: Annotated[
        int,
        typer.Option("--follow-interval-seconds", help="Cadencia default del worker loop."),
    ] = 300,
    refresh_npmrc: Annotated[
        bool,
        typer.Option("--refresh-npmrc/--no-refresh-npmrc", help="Actualiza ~/.npmrc para Fabrics."),
    ] = True,
    skip_install: Annotated[
        bool,
        typer.Option("--skip-install", help="No reinstala/verifica toolchain automatizable."),
    ] = False,
    skip_optional_install: Annotated[
        bool,
        typer.Option("--skip-optional-install", help="No instala VS Code/Docker/Claude opcional."),
    ] = False,
    skip_doctor: Annotated[
        bool,
        typer.Option("--skip-doctor", help="No ejecuta doctor al final."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force/--no-force", help="Sobrescribe config existente cuando aplique."),
    ] = True,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="No pedir confirmacion en install."),
    ] = True,
) -> None:
    """Bootstrap reproducible de la maquina runner."""
    provider = provider.strip().lower()
    auth_mode = auth_mode.strip().lower()
    scope = scope.strip().lower()
    if provider not in {"codex", "claude"}:
        raise typer.BadParameter("provider debe ser `codex` o `claude`")
    if auth_mode not in {"session", "api"}:
        raise typer.BadParameter("auth_mode debe ser `session` o `api`")
    if scope not in {"global", "project"}:
        raise typer.BadParameter("scope debe ser `global` o `project`")
    if provider == "claude" and auth_mode == "api":
        raise typer.BadParameter("runner=claude solo soporta auth_mode=session")

    workspace_root = (workspace_root or Path.cwd()).expanduser().resolve()
    queue_dir = (queue_dir or default_queue_dir()).expanduser().resolve()
    env_file = (env_file or default_auth_env_path()).expanduser().resolve()
    queue_dir.mkdir(parents=True, exist_ok=True)
    env_file.parent.mkdir(parents=True, exist_ok=True)

    console.print(
        Panel.fit(
            "[bold]capamedia setup machine[/bold]\n"
            f"provider={provider} · auth_mode={auth_mode} · scope={scope}\n"
            f"workspace_root={workspace_root}",
            border_style="cyan",
        )
    )

    if not skip_install:
        install.install_toolchain(skip_optional=skip_optional_install, yes=yes)

    auth.bootstrap(
        scope=scope,
        artifact_token=artifact_token,
        azure_pat=azure_pat,
        openai_api_key=codex_api_key,
        env_file=env_file,
        force=force,
        refresh_npmrc=refresh_npmrc,
    )

    existing = machine_config_defaults()
    existing.update(load_machine_config())
    payload = _build_machine_payload(
        existing,
        provider=provider,
        auth_mode=auth_mode,
        scope=scope,
        workspace_root=workspace_root,
        queue_dir=queue_dir,
        env_file=env_file,
        codex_bin=codex_bin,
        claude_bin=claude_bin,
        codex_model=codex_model,
        claude_model=claude_model,
        workers=workers,
        namespace=namespace,
        group_id=group_id,
        timeout_minutes=timeout_minutes,
        retries=retries,
        follow_interval_seconds=follow_interval_seconds,
        skip_optional_install=skip_optional_install,
        run_check=True,
    )
    config_path = write_machine_config(payload, default_machine_config_path())

    table = Table(title="Machine config", title_style="bold cyan")
    table.add_column("Campo", style="cyan")
    table.add_column("Valor", style="bold")
    table.add_row("Config", str(config_path))
    table.add_row("Provider", provider)
    table.add_row("Auth mode", auth_mode)
    table.add_row("Workspace root", str(workspace_root))
    table.add_row("Queue dir", str(queue_dir))
    table.add_row("Env file", str(env_file))
    console.print()
    console.print(table)

    if provider == "claude" and auth_mode == "session":
        console.print(
            "[yellow]Recordatorio:[/yellow] Claude requiere session local activa con `claude auth login`."
        )

    if skip_doctor:
        return

    report = doctor.run_doctor()
    if report.classification != "READY":
        console.print(
            f"[red]Doctor final:[/red] {report.classification} · {report.reason}. "
            "Corre `capamedia doctor` para el detalle completo."
        )
        raise typer.Exit(1)
