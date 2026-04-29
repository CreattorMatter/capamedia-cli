"""Commands for reading Discovery OLA workbooks."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit, urlunsplit

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli.core.auth import build_azure_git_env
from capamedia_cli.core.discovery import (
    DISCOVERY_DEFAULT_SHEET,
    DISCOVERY_WORKBOOK_NAME,
    DiscoveryEntry,
    DiscoverySpecArtifact,
    DiscoverySpecProbe,
    detect_discovery_workspace,
    find_discovery_workbook,
    load_discovery_entry,
    render_discovery_markdown,
)

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")
console = Console()


def _repo_url_without_query(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _probe_spec_repo(entry: DiscoveryEntry, spec_root: Path) -> DiscoverySpecProbe:
    if not entry.link_wsdl or not entry.spec_path:
        return DiscoverySpecProbe(status="skipped", error="LINK WSDL sin repo/path parseable")

    repo_url = _repo_url_without_query(entry.link_wsdl)
    repo_dir = spec_root / (entry.spec_repo or "spec")
    spec_root.mkdir(parents=True, exist_ok=True)
    git_env = os.environ.copy()
    git_env.update(build_azure_git_env())

    try:
        if not (repo_dir / ".git").exists():
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--filter=blob:none",
                    "--sparse",
                    repo_url,
                    str(repo_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
                env=git_env,
            )
        subprocess.run(
            ["git", "-C", str(repo_dir), "sparse-checkout", "set", entry.spec_path.lstrip("/")],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
            env=git_env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return DiscoverySpecProbe(status="error", repo_dir=repo_dir, error=str(exc))

    target = repo_dir / entry.spec_path.lstrip("/")
    artifacts: list[DiscoverySpecArtifact] = []
    if target.exists():
        for file in sorted(p for p in target.rglob("*") if p.is_file()):
            suffix = file.suffix.lower().lstrip(".") or "file"
            artifacts.append(DiscoverySpecArtifact(path=file, kind=suffix))
    return DiscoverySpecProbe(status="ok", repo_dir=repo_dir, artifacts=artifacts)


def discovery_edge_cases(
    service_name: Annotated[
        str | None,
        typer.Argument(help="Servicio legacy o nombre migrado (ej: wsclientes0028)"),
    ] = None,
    xlsx: Annotated[
        Path | None,
        typer.Option(
            "--xlsx",
            "-x",
            help=(
                f"Override del Excel discovery. Si falta, busca {DISCOVERY_WORKBOOK_NAME} "
                "en el workspace, .capamedia, discovery, ancestros, el paquete CLI y Downloads."
            ),
        ),
    ] = None,
    sheet: Annotated[
        str,
        typer.Option("--sheet", help="Hoja del discovery"),
    ] = DISCOVERY_DEFAULT_SHEET,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Escribe un markdown con el resultado"),
    ] = None,
    probe_spec: Annotated[
        bool,
        typer.Option(
            "--probe-spec",
            help="Clona sparse el LINK WSDL y lista artefactos del path del servicio",
        ),
    ] = False,
    spec_root: Annotated[
        Path | None,
        typer.Option("--spec-root", help="Carpeta cache para sparse checkout del repo de specs"),
    ] = None,
    here: Annotated[
        bool,
        typer.Option(
            "--here",
            help="Autodetecta servicio/workspace desde CWD, destino/ y legacy/.",
        ),
    ] = False,
) -> None:
    """Lee Discovery y devuelve edge cases/casos de desborde del servicio."""
    context = detect_discovery_workspace(Path.cwd()) if here else None
    resolved_service = service_name or (context.service_name if context else "")
    if not resolved_service:
        console.print("[red]FAIL[/red] indica <servicio> o usa --here dentro del workspace")
        raise typer.Exit(1)

    workbook = find_discovery_workbook(context.root if context else Path.cwd(), explicit=xlsx)
    if workbook is None:
        console.print(
            f"[red]FAIL[/red] no encontre {DISCOVERY_WORKBOOK_NAME}. "
            "Ponelo en el workspace, .capamedia/, discovery/, un ancestro, Downloads, "
            "o usa --xlsx. El paquete CLI deberia traer una copia canonica."
        )
        raise typer.Exit(1)

    entry = load_discovery_entry(workbook, resolved_service, sheet_name=sheet)
    if entry is None:
        console.print(f"[red]FAIL[/red] {resolved_service} no encontrado en {workbook}")
        raise typer.Exit(1)

    console.print(
        Panel.fit(
            f"[bold]Discovery edge-cases[/bold]\n"
            f"Servicio: [cyan]{entry.service}[/cyan]\n"
            f"Migrado:  [cyan]{entry.migrated_name or '?'}[/cyan]\n"
            f"Spec:     [cyan]{entry.spec_path or '?'}[/cyan]\n"
            f"Excel:    [cyan]{workbook}[/cyan]",
            border_style="cyan",
        )
    )
    if context:
        console.print(
            "[dim]Workspace: "
            f"{context.root} | legacy={context.legacy_path or '-'} | "
            f"destino={context.migrated_path or '-'}[/dim]"
        )

    table = Table(title="Edge cases discovery", title_style="bold cyan")
    table.add_column("Codigo", style="cyan")
    table.add_column("Severidad", style="bold")
    table.add_column("Evidencia")
    if entry.edge_cases:
        for case in entry.edge_cases:
            style = "red" if case.severity == "high" else "yellow"
            table.add_row(case.code, f"[{style}]{case.severity.upper()}[/{style}]", case.evidence[:120])
    else:
        table.add_row("-", "-", "Sin edge cases detectados por discovery")
    console.print(table)

    if entry.weight_flags:
        console.print("[bold]Flags de complejidad:[/bold] " + "; ".join(entry.weight_flags))
    if entry.observations:
        console.print(f"[bold]Observacion:[/bold] {entry.observations}")
    console.print(f"[bold]LINK WSDL:[/bold] {entry.link_wsdl or '-'}")
    console.print(f"[bold]LINK CODIGO:[/bold] {entry.link_code or '-'}")

    if probe_spec:
        root = spec_root or (Path.cwd() / ".capamedia" / "specs")
        probe = _probe_spec_repo(entry, root)
        if probe.status == "ok":
            console.print(
                f"[green]OK[/green] spec sparse checkout: {len(probe.artifacts)} artefacto(s)"
            )
            for artifact in probe.artifacts[:20]:
                console.print(f"  - {artifact.kind}: {artifact.path}")
        else:
            console.print(f"[yellow]SPEC {probe.status.upper()}[/yellow] {probe.error}")

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_discovery_markdown(entry), encoding="utf-8")
        console.print(f"[bold]Reporte:[/bold] [cyan]{output}[/cyan]")


app.command("edge-case")(discovery_edge_cases)
app.command("edge-cases", hidden=True)(discovery_edge_cases)
