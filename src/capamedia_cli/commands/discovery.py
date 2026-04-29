"""Commands for reading Discovery OLA workbooks."""

from __future__ import annotations

import os
import shutil
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
    rank_spec_candidate,
    render_discovery_markdown,
    service_suffix_key,
    spec_parent_path,
)

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")
console = Console()


def _repo_url_without_query(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _run_git(args: list[str], *, env: dict[str, str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _sparse_set(repo_dir: Path, sparse_path: str, *, env: dict[str, str]) -> None:
    _run_git(["git", "-C", str(repo_dir), "sparse-checkout", "set", sparse_path.strip("/")], env=env)


def _collect_spec_artifacts(target: Path) -> list[DiscoverySpecArtifact]:
    artifacts: list[DiscoverySpecArtifact] = []
    if not target.exists():
        return artifacts
    allowed = {".wsdl", ".xsd"}
    for file in sorted(p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in allowed):
        suffix = file.suffix.lower().lstrip(".") or "file"
        artifacts.append(DiscoverySpecArtifact(path=file, kind=suffix))
    return artifacts


def _resolve_spec_target(entry: DiscoveryEntry, repo_dir: Path, *, env: dict[str, str]) -> tuple[Path | None, str, str]:
    requested = entry.spec_path.strip("/")
    requested_target = repo_dir / requested
    if requested and requested_target.exists():
        return requested_target, requested, ""

    parent = spec_parent_path(entry.spec_path)
    if not parent:
        return None, "", f"path no existe y no se pudo inferir carpeta padre: {entry.spec_path}"

    _sparse_set(repo_dir, parent, env=env)
    parent_dir = repo_dir / parent.strip("/")
    if not parent_dir.exists():
        return None, "", f"carpeta padre no existe en specs: /{parent}"

    service_key = service_suffix_key(" ".join([entry.service, entry.migrated_name, entry.spec_path]))
    candidates = [child for child in parent_dir.iterdir() if child.is_dir()]
    ranked = sorted(
        (
            (rank_spec_candidate(child.name, service_key, entry.acronym), child)
            for child in candidates
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] == 0:
        return None, "", f"no encontre carpeta candidata para {service_key} bajo /{parent}"

    resolved = ranked[0][1]
    resolved_sparse_path = str(resolved.relative_to(repo_dir)).replace("\\", "/")
    _sparse_set(repo_dir, resolved_sparse_path, env=env)
    return resolved, resolved_sparse_path, ""


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
            _run_git(
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
                timeout=180,
                env=git_env,
            )
        _sparse_set(repo_dir, entry.spec_path, env=git_env)
    except (OSError, subprocess.SubprocessError) as exc:
        return DiscoverySpecProbe(
            status="error",
            repo_dir=repo_dir,
            requested_path=entry.spec_path,
            error=str(exc),
        )

    try:
        target, resolved_path, error = _resolve_spec_target(entry, repo_dir, env=git_env)
    except (OSError, subprocess.SubprocessError) as exc:
        return DiscoverySpecProbe(
            status="error",
            repo_dir=repo_dir,
            requested_path=entry.spec_path,
            error=str(exc),
        )
    if target is None:
        return DiscoverySpecProbe(
            status="not_found",
            repo_dir=repo_dir,
            requested_path=entry.spec_path,
            error=error,
        )

    artifacts = _collect_spec_artifacts(target)
    return DiscoverySpecProbe(
        status="ok",
        repo_dir=repo_dir,
        artifacts=artifacts,
        resolved_path="/" + resolved_path.strip("/"),
        requested_path=entry.spec_path,
    )


def _copy_spec_artifacts(probe: DiscoverySpecProbe, destination: Path) -> list[Path]:
    copied: list[Path] = []
    if probe.status != "ok" or not probe.artifacts:
        return copied
    destination.mkdir(parents=True, exist_ok=True)
    for artifact in probe.artifacts:
        target = destination / artifact.path.name
        shutil.copy2(artifact.path, target)
        copied.append(target)
    return copied


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
            help="Clona sparse el LINK WSDL y lista artefactos del path del servicio. Con --here se activa automaticamente.",
        ),
    ] = False,
    materialize_spec: Annotated[
        bool,
        typer.Option(
            "--materialize-spec/--no-materialize-spec",
            help="Copia WSDL/XSD encontrados a src/test/resources/discovery/<servicio> del migrado.",
        ),
    ] = True,
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

    probe: DiscoverySpecProbe | None = None
    copied_artifacts: list[Path] = []
    should_probe_spec = probe_spec or here
    if should_probe_spec:
        root_base = context.root if context else Path.cwd()
        root = spec_root or (root_base / ".capamedia" / "specs")
        probe = _probe_spec_repo(entry, root)
        if probe.status == "ok":
            console.print(
                f"[green]OK[/green] spec sparse checkout: {len(probe.artifacts)} artefacto(s)"
            )
            if probe.requested_path and probe.resolved_path and probe.requested_path != probe.resolved_path:
                console.print(
                    "[yellow]Spec path corregido por sufijo de servicio:[/yellow] "
                    f"{probe.requested_path} -> {probe.resolved_path}"
                )
            for artifact in probe.artifacts[:20]:
                console.print(f"  - {artifact.kind}: {artifact.path}")
            if materialize_spec and context and context.migrated_path:
                service_key = entry.service.lower()
                destination = context.migrated_path / "src" / "test" / "resources" / "discovery" / service_key
                copied_artifacts = _copy_spec_artifacts(probe, destination)
                if copied_artifacts:
                    console.print(
                        f"[green]OK[/green] {len(copied_artifacts)} WSDL/XSD copiado(s) al migrado: {destination}"
                    )
        else:
            console.print(f"[yellow]SPEC {probe.status.upper()}[/yellow] {probe.error}")

    if output is None and here and context:
        if context.migrated_path:
            output = context.migrated_path / "DISCOVERY_EDGE_CASES.md"
        else:
            output = context.root / f"DISCOVERY_EDGE_CASES_{entry.service.lower()}.md"

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            render_discovery_markdown(
                entry,
                spec_probe=probe,
                copied_artifacts=copied_artifacts,
            ),
            encoding="utf-8",
        )
        console.print(f"[bold]Reporte:[/bold] [cyan]{output}[/cyan]")


app.command("edge-case")(discovery_edge_cases)
app.command("edge-cases", hidden=True)(discovery_edge_cases)
