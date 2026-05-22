"""capamedia qa - prepara el workspace para la compuerta pre-QA `/qa`.

El CLI clona el legacy + el migrado y deja el workspace listo. El analisis QA
en si lo corre el slash command `/qa` (canonico, instalado por
`capamedia init`): Paso 1 analisis comparativo legacy vs migrado, Paso 2
handoff al agente `qe-migration` para los artefactos QA bajo `docs/qa/**`.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli import __version__
from capamedia_cli.commands.clone import (
    AZURE_FALLBACK_PATTERNS,
    _git_clone,
    normalize_service_name,
)
from capamedia_cli.commands.fabrics import (
    NAMESPACE_OPTIONS,
    _autodetect_service_name_from_config,
)

console = Console()

app = typer.Typer(
    help="Prepara el workspace (legacy + migrado) para la compuerta pre-QA /qa.",
    no_args_is_help=True,
)


@dataclass(frozen=True)
class QaWorkspace:
    service: str
    workspace: Path
    legacy_path: Path | None
    destino_path: Path | None


def _has_gradle_build(path: Path) -> bool:
    return (path / "build.gradle").exists() or (path / "build.gradle.kts").exists()


def _safe_rel(path: Path | None, root: Path) -> str:
    if path is None:
        return "(no encontrado)"
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _infer_service_name(service_name: str | None, workspace: Path) -> str:
    raw = (
        service_name
        or _autodetect_service_name_from_config(workspace)
        or workspace.name
    )
    service, _ = normalize_service_name(raw)
    return service


def _write_config(workspace: Path, service: str) -> Path:
    capamedia_dir = workspace / ".capamedia"
    capamedia_dir.mkdir(parents=True, exist_ok=True)
    path = capamedia_dir / "config.yaml"

    data: dict[str, object] = {}
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                data = dict(loaded)
        except (OSError, yaml.YAMLError):
            data = {}

    data["service_name"] = service
    data.setdefault("version", __version__)
    data.setdefault("ai", ["claude"])
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def _find_existing_legacy(workspace: Path, service: str) -> Path | None:
    base = workspace / "legacy"
    if not base.is_dir():
        return None
    candidates = sorted(p for p in base.iterdir() if p.is_dir())
    if not candidates:
        return None
    preferred_names = (
        f"sqb-msa-{service}",
        f"ws-{service}-was",
        f"ms-{service}-was",
    )
    for name in preferred_names:
        candidate = base / name
        if candidate.is_dir():
            return candidate
    preferred = [p for p in candidates if service in p.name.lower()]
    return preferred[0] if preferred else candidates[0]


def _find_existing_destino(workspace: Path, service: str) -> Path | None:
    base = workspace / "destino"
    if not base.is_dir():
        return None
    candidates = sorted(p for p in base.iterdir() if p.is_dir())
    if not candidates:
        return None
    with_gradle = [p for p in candidates if _has_gradle_build(p)]
    pool = with_gradle or candidates
    preferred = [p for p in pool if service in p.name.lower()]
    return preferred[0] if preferred else pool[0]


def _clone_legacy(workspace: Path, service: str, *, shallow: bool) -> Path:
    errors: list[str] = []
    for project_key, pattern in AZURE_FALLBACK_PATTERNS:
        if project_key not in {"bus", "was"}:
            continue
        repo_name = pattern.format(svc=service)
        dest = workspace / "legacy" / repo_name
        ok, err = _git_clone(repo_name, dest, project_key=project_key, shallow=shallow)
        if ok:
            return dest
        if err:
            errors.append(f"{project_key}/{repo_name}: {err}")
    detail = "; ".join(errors[-3:]) if errors else "sin candidatos"
    raise RuntimeError(f"no se pudo clonar legacy para {service}: {detail}")


def _candidate_destino_repos(
    service: str,
    *,
    namespace: str | None,
    destino_repo: str | None,
) -> list[str]:
    if destino_repo:
        return [destino_repo]
    namespaces = [namespace] if namespace else NAMESPACE_OPTIONS
    return [f"{ns}-msa-sp-{service}" for ns in namespaces if ns]


def _clone_destino(
    workspace: Path,
    service: str,
    *,
    namespace: str | None,
    destino_repo: str | None,
    shallow: bool,
) -> Path:
    errors: list[str] = []
    for repo_name in _candidate_destino_repos(
        service,
        namespace=namespace,
        destino_repo=destino_repo,
    ):
        dest = workspace / "destino" / repo_name
        ok, err = _git_clone(repo_name, dest, project_key="middleware", shallow=shallow)
        if ok:
            return dest
        if err:
            errors.append(f"middleware/{repo_name}: {err}")
    detail = "; ".join(errors[-4:]) if errors else "sin candidatos"
    raise RuntimeError(f"no se pudo clonar destino migrado para {service}: {detail}")


def _write_pack_metadata(qw: QaWorkspace) -> Path:
    qa_dir = qw.workspace / ".capamedia" / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    path = qa_dir / "pack.json"
    payload = {
        "generated_by": "capamedia qa pack",
        "cli_version": __version__,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "service": qw.service,
        "workspace": str(qw.workspace),
        "legacy_path": str(qw.legacy_path) if qw.legacy_path else "",
        "destino_path": str(qw.destino_path) if qw.destino_path else "",
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _render_summary(qw: QaWorkspace) -> None:
    table = Table(title="CapaMedia QA pack", title_style="bold cyan")
    table.add_column("Item", style="cyan")
    table.add_column("Estado")
    table.add_column("Path")
    table.add_row(
        "legacy",
        "[green]OK[/green]" if qw.legacy_path else "[red]MISSING[/red]",
        _safe_rel(qw.legacy_path, qw.workspace),
    )
    table.add_row(
        "destino",
        "[green]OK[/green]" if qw.destino_path else "[red]MISSING[/red]",
        _safe_rel(qw.destino_path, qw.workspace),
    )
    table.add_row("comando QA", "[green]/qa[/green]", "instalado por capamedia init")
    console.print(table)


def _prepare_workspace(
    *,
    service: str,
    workspace: Path,
    legacy_path: Path | None,
    destino_path: Path | None,
) -> QaWorkspace:
    _write_config(workspace, service)
    qw = QaWorkspace(
        service=service,
        workspace=workspace,
        legacy_path=legacy_path,
        destino_path=destino_path,
    )
    _write_pack_metadata(qw)
    return qw


@app.command("pack")
def pack(
    service_name: Annotated[
        str | None,
        typer.Argument(
            help="Servicio a preparar. Si se omite, usa .capamedia/config.yaml o el nombre del CWD.",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", "-w", help="Workspace root (default: CWD)"),
    ] = None,
    namespace: Annotated[
        str | None,
        typer.Option(
            "--namespace",
            "-n",
            help="Namespace del repo migrado (tnd/tpr/csg/tmp/tia/tct). Si se omite, prueba todos.",
        ),
    ] = None,
    destino_repo: Annotated[
        str | None,
        typer.Option("--destino-repo", help="Nombre exacto del repo migrado en middleware."),
    ] = None,
    shallow: Annotated[
        bool,
        typer.Option("--shallow/--full", help="Usa git clone --depth 1 para los repos."),
    ] = True,
    no_clone: Annotated[
        bool,
        typer.Option("--no-clone", help="No intenta clonar; solo ubica lo local."),
    ] = False,
) -> None:
    """Trae/ubica legacy + destino y deja el workspace listo para el comando `/qa`."""
    ws = (workspace or Path.cwd()).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    service = _infer_service_name(service_name, ws)

    if namespace and namespace not in NAMESPACE_OPTIONS:
        raise typer.BadParameter(
            f"namespace invalido: {namespace}. Opciones: {', '.join(NAMESPACE_OPTIONS)}"
        )

    console.print(
        Panel.fit(
            f"[bold]CapaMedia QA pack[/bold]\n"
            f"Servicio: [cyan]{service}[/cyan]\n"
            f"Workspace: [cyan]{ws}[/cyan]",
            border_style="cyan",
        )
    )

    legacy_path = _find_existing_legacy(ws, service)
    destino_path = _find_existing_destino(ws, service)

    if not no_clone and legacy_path is None:
        console.print("[bold]Clonando legacy[/bold] (BUS/WAS)...")
        try:
            legacy_path = _clone_legacy(ws, service, shallow=shallow)
            console.print(f"  [green]OK[/green] {_safe_rel(legacy_path, ws)}")
        except RuntimeError as exc:
            console.print(f"  [red]FAIL[/red] {exc}")

    if not no_clone and destino_path is None:
        console.print("[bold]Clonando destino migrado[/bold] (middleware)...")
        try:
            destino_path = _clone_destino(
                ws,
                service,
                namespace=namespace,
                destino_repo=destino_repo,
                shallow=shallow,
            )
            console.print(f"  [green]OK[/green] {_safe_rel(destino_path, ws)}")
        except RuntimeError as exc:
            console.print(f"  [red]FAIL[/red] {exc}")

    qw = _prepare_workspace(
        service=service,
        workspace=ws,
        legacy_path=legacy_path,
        destino_path=destino_path,
    )
    _render_summary(qw)

    if qw.legacy_path is None or qw.destino_path is None:
        console.print(
            "\n[yellow]Pack parcial:[/yellow] completa legacy/ y destino/ y luego corre "
            "[cyan]capamedia qa prepare[/cyan]."
        )
    console.print(
        "\n[bold]Siguiente paso:[/bold]\n"
        "  1. Abri el workspace con tu harness AI (Claude Code recomendado).\n"
        "  2. Ejecuta el slash command [cyan]/qa[/cyan]:\n"
        "     - Paso 1: analisis comparativo legacy vs migrado (go/no-go).\n"
        "     - Paso 2: handoff al agente [cyan]qe-migration[/cyan] (artefactos QA en docs/qa/**).\n"
        "  Si [cyan]/qa[/cyan] no aparece, corre [cyan]capamedia init --here[/cyan] para instalarlo.\n"
    )


@app.command("prepare")
def prepare(
    service_name: Annotated[
        str | None,
        typer.Argument(
            help="Servicio a preparar. Si se omite, usa .capamedia/config.yaml o el nombre del CWD.",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", "-w", help="Workspace root (default: CWD)"),
    ] = None,
) -> None:
    """Ubica legacy + destino locales y actualiza la config, sin clonar."""
    ws = (workspace or Path.cwd()).resolve()
    service = _infer_service_name(service_name, ws)
    legacy_path = _find_existing_legacy(ws, service)
    destino_path = _find_existing_destino(ws, service)
    qw = _prepare_workspace(
        service=service,
        workspace=ws,
        legacy_path=legacy_path,
        destino_path=destino_path,
    )
    _render_summary(qw)
    if qw.legacy_path is None or qw.destino_path is None:
        raise typer.Exit(1)
