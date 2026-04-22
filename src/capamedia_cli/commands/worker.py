"""capamedia worker - loop local para ejecutar lotes unattended."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from capamedia_cli.commands import batch, doctor
from capamedia_cli.core.machine_config import load_machine_config, machine_paths, provider_config

console = Console()

app = typer.Typer(
    help="Worker local que consume una cola y dispara batch pipeline/migrate.",
    no_args_is_help=True,
)


def _default_queue_file(mode: str, queue_dir: Path) -> Path:
    filename = "services.txt" if mode == "pipeline" else "migrate.txt"
    return queue_dir / filename


def _run_once(
    *,
    mode: str,
    queue_file: Path,
    root: Path,
    provider: str,
    runner_bin: str,
    model: str | None,
    workers: int,
    namespace: str,
    group_id: str,
    timeout_minutes: int,
    retries: int,
    skip_check: bool,
) -> None:
    if mode == "pipeline":
        ai = "claude,codex" if provider == "claude" else "codex"
        batch.batch_pipeline(
            file=queue_file,
            namespace=namespace,
            ai=ai,
            workers=workers,
            root=root,
            group_id=group_id,
            artifact_token=None,
            provider=provider,
            runner_bin=runner_bin,
            model=model,
            prompt_file=None,
            timeout_minutes=timeout_minutes,
            shallow=False,
            skip_tx=False,
            skip_check=skip_check,
            resume=True,
            retries=retries,
            unsafe=False,
        )
        return

    batch.batch_migrate(
        file=queue_file,
        workers=workers,
        root=root,
        provider=provider,
        runner_bin=runner_bin,
        model=model,
        prompt_file=None,
        timeout_minutes=timeout_minutes,
        skip_check=skip_check,
        resume=True,
        retries=retries,
        unsafe=False,
    )


@app.command("run")
def run_worker(
    mode: Annotated[
        str,
        typer.Option("--mode", help="pipeline o migrate.", case_sensitive=False),
    ] = "pipeline",
    queue: Annotated[
        Path | None,
        typer.Option("--queue", help="Archivo txt/csv/xlsx con servicios."),
    ] = None,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Root donde viven los workspaces del lote."),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Runner principal: codex o claude.", case_sensitive=False),
    ] = None,
    runner_bin: Annotated[
        str | None,
        typer.Option("--runner-bin", help="Binario del runner seleccionado."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Modelo override para el runner."),
    ] = None,
    namespace: Annotated[
        str | None,
        typer.Option("--namespace", help="Namespace de Fabrics para mode=pipeline."),
    ] = None,
    group_id: Annotated[
        str | None,
        typer.Option("--group-id", help="groupId del arquetipo."),
    ] = None,
    workers: Annotated[int | None, typer.Option("--workers")] = None,
    timeout_minutes: Annotated[int | None, typer.Option("--timeout-minutes")] = None,
    retries: Annotated[int | None, typer.Option("--retries")] = None,
    interval_seconds: Annotated[
        int | None,
        typer.Option("--interval-seconds", help="Cadencia del loop cuando no es --once."),
    ] = None,
    once: Annotated[
        bool,
        typer.Option("--once", help="Ejecuta una sola pasada y sale."),
    ] = False,
    skip_check: Annotated[
        bool,
        typer.Option("--skip-check", help="No correr checklist post-migracion."),
    ] = False,
    skip_doctor: Annotated[
        bool,
        typer.Option("--skip-doctor", help="No validar readiness antes de arrancar."),
    ] = False,
) -> None:
    """Corre la fabrica local usando machine.toml como contrato principal."""
    mode = mode.strip().lower()
    if mode not in {"pipeline", "migrate"}:
        raise typer.BadParameter("mode debe ser `pipeline` o `migrate`")

    machine = load_machine_config()
    paths = machine_paths(machine)
    defaults = machine.get("defaults", {})
    if not isinstance(defaults, dict):
        defaults = {}

    resolved_provider = (provider or machine.get("provider") or "codex").strip().lower()
    if resolved_provider not in {"codex", "claude"}:
        raise typer.BadParameter("provider debe ser `codex` o `claude`")

    provider_defaults = provider_config(machine, resolved_provider)
    resolved_root = (root or paths["workspace_root"]).expanduser().resolve()
    resolved_queue = (queue or _default_queue_file(mode, paths["queue_dir"])).expanduser().resolve()
    resolved_runner_bin = runner_bin or str(provider_defaults.get("bin") or resolved_provider)
    resolved_model = model or str(provider_defaults.get("model") or "")
    resolved_workers = workers or int(defaults.get("workers", 2) or 2)
    resolved_namespace = namespace or str(defaults.get("namespace", "tnd"))
    resolved_group_id = group_id or str(defaults.get("group_id", "com.pichincha.sp"))
    resolved_timeout = timeout_minutes or int(defaults.get("timeout_minutes", 90) or 90)
    resolved_retries = retries or int(defaults.get("retries", 1) or 1)
    resolved_interval = interval_seconds or int(defaults.get("follow_interval_seconds", 300) or 300)

    if not resolved_queue.exists():
        raise typer.BadParameter(f"cola no existe: {resolved_queue}")

    console.print(
        Panel.fit(
            "[bold]capamedia worker run[/bold]\n"
            f"mode={mode} · provider={resolved_provider} · queue={resolved_queue}\n"
            f"root={resolved_root} · workers={resolved_workers} · retries={resolved_retries}",
            border_style="cyan",
        )
    )

    if not skip_doctor:
        readiness = doctor.run_doctor()
        if readiness.classification != "READY":
            console.print(
                f"[red]worker bloqueado:[/red] {readiness.classification} · {readiness.reason}. "
                "Corre `capamedia doctor`."
            )
            raise typer.Exit(1)

    while True:
        _run_once(
            mode=mode,
            queue_file=resolved_queue,
            root=resolved_root,
            provider=resolved_provider,
            runner_bin=resolved_runner_bin,
            model=resolved_model,
            workers=resolved_workers,
            namespace=resolved_namespace,
            group_id=resolved_group_id,
            timeout_minutes=resolved_timeout,
            retries=resolved_retries,
            skip_check=skip_check,
        )
        if once:
            return
        time.sleep(resolved_interval)
