"""capamedia adopt <svc> - adopta un workspace no-canonico al layout del CLI.

Escenario: el usuario migro un servicio fuera del CLI y tiene la estructura
plana:

    D:\\path\\0026\\
      csg-msa-sp-wsclientes0026\\     <- el proyecto migrado
      ws-wsclientes0026-was\\          <- el legacy
      MIGRATION_REPORT.md
      ANALISIS_*.md
      ...

`capamedia adopt` detecta esos subdirectorios por pattern y los mueve a la
convencion del CLI (`destino/<svc>/` + `legacy/<svc>/`). Opcionalmente corre
`init` para dejar el workspace listo para `review`/`doublecheck`.

Flujo esperado:

    cd D:\\path\\0026
    capamedia adopt wsclientes0026 --init
    capamedia review      # autodetect funciona
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

console = Console()


# Patterns para detectar subdirectorios que deben ir a legacy/
_LEGACY_PATTERNS = [
    re.compile(r"^ws-[a-z]+\d{4}-was$", re.IGNORECASE),     # ws-<svc>-was
    re.compile(r"^ms-[a-z]+\d{4}-was$", re.IGNORECASE),     # ms-<svc>-was
    re.compile(r"^ump-[a-z]+\d{4}-was$", re.IGNORECASE),    # ump-<ump>-was (UMPs)
    re.compile(r"^sqb-msa-[a-z]+\d{4}$", re.IGNORECASE),    # sqb-msa-<svc> (IIB)
]

# Patterns para detectar subdirectorios que deben ir a destino/
_DESTINO_NAMESPACES = ("csg", "tnd", "tpr", "tmp", "tia", "tct")
_DESTINO_PATTERNS = [
    re.compile(rf"^{ns}-msa-sp-[a-z]+\d{{4}}$", re.IGNORECASE)
    for ns in _DESTINO_NAMESPACES
]


def _matches_any(patterns: list[re.Pattern], name: str) -> bool:
    return any(p.match(name) for p in patterns)


def _classify_subdir(path: Path) -> str | None:
    """Devuelve 'legacy' | 'destino' | None segun el nombre del directorio."""
    name = path.name
    if _matches_any(_LEGACY_PATTERNS, name):
        return "legacy"
    if _matches_any(_DESTINO_PATTERNS, name):
        return "destino"
    return None


def adopt(
    service_name: Annotated[
        str | None,
        typer.Argument(
            help="Nombre del servicio (ej: wsclientes0026). Si se omite, "
            "se intenta inferir del nombre del directorio CWD o de los "
            "subdirectorios detectados.",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace", "-w",
            help="Workspace root (default: CWD).",
        ),
    ] = None,
    init: Annotated[
        bool,
        typer.Option(
            "--init",
            help="Correr `capamedia init` despues de reorganizar. "
            "Default harness: claude. Equivale a `adopt` + `init` en una linea.",
        ),
    ] = False,
    init_ai: Annotated[
        str,
        typer.Option(
            "--init-ai",
            help="Harness para el init automatico. Default: claude. "
            "CSV permitido (ej: claude,codex). Solo aplica si --init esta activo.",
        ),
    ] = "claude",
    yes: Annotated[
        bool,
        typer.Option(
            "--yes", "-y",
            help="No pedir confirmacion; ejecutar los moves directo.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Mostrar que se haria pero no modificar nada.",
        ),
    ] = False,
) -> None:
    """Adopta un workspace pre-existente al layout del CLI (v0.23.11).

    Detecta subdirectorios con patterns conocidos (ws-*-was, sqb-msa-*,
    csg/tnd/tpr/tmp/tia/tct-msa-sp-*) y los mueve a `legacy/` + `destino/`
    segun corresponda. Permite luego correr `init` para completar el setup.
    """
    # v0.20.1: auto-padding del service_name si se paso
    if service_name:
        from capamedia_cli.commands.clone import normalize_service_name

        normalized, was_padded = normalize_service_name(service_name)
        if was_padded:
            console.print(
                f"[yellow]Tip:[/yellow] [cyan]{service_name}[/cyan] -> "
                f"[cyan]{normalized}[/cyan] (auto-padded a 4 digitos)"
            )
            service_name = normalized

    ws = (workspace or Path.cwd()).resolve()
    if not ws.is_dir():
        console.print(f"[red]Error:[/red] workspace no existe: {ws}")
        raise typer.Exit(code=2)

    # Escanear subdirectorios del workspace
    legacy_moves: list[tuple[Path, Path]] = []   # (src, dest)
    destino_moves: list[tuple[Path, Path]] = []

    for entry in sorted(ws.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        # Saltear las carpetas destino/legacy/umps que ya existan
        if entry.name in ("legacy", "destino", "umps", "tx", "gold-ref"):
            continue

        kind = _classify_subdir(entry)
        if kind == "legacy":
            target = ws / "legacy" / entry.name
            legacy_moves.append((entry, target))
        elif kind == "destino":
            target = ws / "destino" / entry.name
            destino_moves.append((entry, target))

    total_moves = len(legacy_moves) + len(destino_moves)

    # Inferir service_name si no se paso
    if service_name is None:
        # Del directorio CWD o del primer match de legacy/destino
        candidates = []
        for src, _ in legacy_moves + destino_moves:
            # Extraer el <svc> del nombre (ultimo \d{4} fragment)
            m = re.search(r"([a-z]+\d{4})", src.name, re.IGNORECASE)
            if m:
                candidates.append(m.group(1).lower())
        if candidates:
            # Usar el mas frecuente
            from collections import Counter
            service_name = Counter(candidates).most_common(1)[0][0]
            console.print(
                f"[dim]Service name inferido de los subdirectorios: "
                f"[cyan]{service_name}[/cyan][/dim]"
            )
        else:
            # Del nombre del CWD si parece valido
            cwd_name = ws.name.lower()
            if re.match(r"^[a-z]+\d{4}$", cwd_name) or re.match(r"^\d{4}$", cwd_name):
                service_name = cwd_name
            else:
                service_name = "unknown"

    # Mostrar plan
    console.print(
        Panel.fit(
            f"[bold]capamedia adopt[/bold]\n"
            f"Servicio: [cyan]{service_name}[/cyan]\n"
            f"Workspace: [cyan]{ws}[/cyan]\n"
            f"Moves detectados: [bold]{total_moves}[/bold]"
            f" ({len(legacy_moves)} legacy + {len(destino_moves)} destino)\n"
            f"Init automatico: {'SI (' + init_ai + ')' if init else 'NO'}\n"
            f"Dry run: {'SI' if dry_run else 'NO'}",
            border_style="cyan",
        )
    )

    if total_moves == 0:
        console.print(
            "\n[yellow]No se detectaron subdirectorios con patterns conocidos[/yellow]\n"
            "  Legacy patterns: ws-*-was, ms-*-was, ump-*-was, sqb-msa-*\n"
            f"  Destino patterns: {', '.join(_DESTINO_NAMESPACES)}-msa-sp-*\n"
        )
        if not init:
            raise typer.Exit(code=0)

    if total_moves > 0:
        # Tabla del plan
        table = Table(title="Plan de reorganizacion", title_style="bold cyan")
        table.add_column("De", style="yellow")
        table.add_column("A", style="green")
        table.add_column("Kind", style="dim")
        for src, dest in legacy_moves:
            table.add_row(src.name + "/", f"legacy/{dest.name}/", "legacy")
        for src, dest in destino_moves:
            table.add_row(src.name + "/", f"destino/{dest.name}/", "destino")
        console.print(table)

        if dry_run:
            console.print("\n[dim]--dry-run activo; no se toca nada.[/dim]")
            return

        # Confirmar
        if not yes:
            if not Confirm.ask("\nProceder con los moves?", default=True):
                console.print("[yellow]Cancelado.[/yellow]")
                raise typer.Exit(code=0)

        # Ejecutar moves
        (ws / "legacy").mkdir(exist_ok=True)
        (ws / "destino").mkdir(exist_ok=True)

        executed: list[str] = []
        for src, dest in legacy_moves + destino_moves:
            if dest.exists():
                console.print(
                    f"[yellow]Skip[/yellow] {src.name}: {dest} ya existe"
                )
                continue
            try:
                shutil.move(str(src), str(dest))
                executed.append(f"{src.name} -> {dest.relative_to(ws)}")
            except OSError as exc:
                console.print(
                    f"[red]FAIL[/red] {src.name}: {exc}"
                )
                continue

        console.print(
            f"\n[green]OK[/green] {len(executed)} subdirectorio(s) reubicado(s):"
        )
        for line in executed:
            console.print(f"  [dim]{line}[/dim]")

    # Init automatico si se pidio
    if init:
        console.print(f"\n[bold]Corriendo init ({init_ai})...[/bold]")
        try:
            from capamedia_cli.adapters import resolve_harnesses
            from capamedia_cli.commands.init import scaffold_project

            harnesses = resolve_harnesses(init_ai)
            total, warnings = scaffold_project(
                target_dir=ws,
                service_name=service_name,
                harnesses=harnesses,
            )
            console.print(
                f"  [green]OK[/green] {total} archivo(s) generado(s) "
                f"({', '.join(harnesses)})"
            )
            for w in warnings[:5]:
                console.print(f"  [yellow]warn[/yellow] {w}")
        except Exception as exc:
            console.print(
                f"  [red]FAIL[/red] init: {type(exc).__name__}: {exc}\n"
                f"  Correlo manual: [cyan]capamedia init {service_name} --ai {init_ai}[/cyan]"
            )
            raise typer.Exit(code=1) from exc

    # Siguiente paso
    console.print("\n[bold]Siguiente paso:[/bold]")
    if init:
        console.print(
            "  [cyan]capamedia review[/cyan]  (autodetecta destino/ y legacy/)"
        )
    else:
        console.print(
            f"  [cyan]capamedia init {service_name} --ai claude[/cyan]  "
            "(genera .claude/, CLAUDE.md, .mcp.json, etc.)"
        )
        console.print(
            "  [cyan]capamedia review[/cyan]  (despues del init)"
        )
