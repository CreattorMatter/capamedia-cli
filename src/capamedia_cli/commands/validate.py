"""capamedia validate-hexagonal - wrapper sobre el script oficial del banco.

Invoca el `validate_hexagonal.py` vendor-pinned (en `data/vendor/`) y mapea
los resultados a nuestro sistema de CheckResult para integrarlos con el
resto del reporting del CLI.

Filosofia:
- El script oficial es la **fuente de verdad** para el gate de PR.
- No lo modificamos; lo pinamos en `data/vendor/` y lo corremos de afuera.
- Cuando el banco publique una version nueva, `validate-hexagonal sync`
  la baja y actualizamos el pin.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

app = typer.Typer(
    help=(
        "Corre el validador oficial del banco (9 checks formales de "
        "arquitectura hexagonal) sobre un proyecto migrado."
    ),
    no_args_is_help=True,
)


def _vendor_script_path() -> Path:
    """Ruta absoluta al script vendor-pinned."""
    here = Path(__file__).resolve().parent
    return here.parent / "data" / "vendor" / "validate_hexagonal.py"


def _load_vendor_module():
    """Carga el vendor script como modulo importable (para API use)."""
    path = _vendor_script_path()
    if not path.exists():
        raise FileNotFoundError(
            f"vendor validate_hexagonal.py no encontrado en {path}"
        )
    spec = importlib.util.spec_from_file_location("capamedia_vendor_hexagonal", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("no se pudo cargar el modulo vendor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@app.command("run")
def validate_run(
    project_path: Annotated[
        Path,
        typer.Argument(
            help="Ruta al proyecto Java migrado (destino/tnd-msa-sp-<svc>/).",
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Directorio para el reporte markdown"),
    ] = None,
    threshold: Annotated[
        int,
        typer.Option(
            "--threshold",
            "-t",
            help="Umbral para check 6 (service business logic). 3 default, 4-5 mas permisivo.",
        ),
    ] = 3,
    json_out: Annotated[
        bool, typer.Option("--json", help="Exportar resumen JSON")
    ] = False,
    fail_on_warn: Annotated[
        bool,
        typer.Option(
            "--fail-on-warn",
            help="Exit 1 tambien si algun check pasa con WARN",
        ),
    ] = False,
) -> None:
    """Corre el script oficial del banco. Exit 1 si falla algun check."""
    project_path = project_path.resolve()
    if not project_path.is_dir():
        console.print(f"[red]Proyecto no existe:[/red] {project_path}")
        raise typer.Exit(code=2)

    script = _vendor_script_path()
    if not script.exists():
        console.print(
            f"[red]FATAL:[/red] vendor script no encontrado en {script}. "
            "Correr `capamedia validate-hexagonal sync` o reinstalar."
        )
        raise typer.Exit(code=2)

    cmd = [
        sys.executable,
        str(script),
        str(project_path),
        "--threshold",
        str(threshold),
    ]
    if output is not None:
        cmd.extend(["--output", str(output.resolve())])
    if json_out:
        cmd.append("--json")

    # Forzar UTF-8 en Windows (el script usa caracteres Unicode que cp1252 no soporta)
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    console.print(
        Panel.fit(
            "[bold]capamedia validate-hexagonal[/bold]\n"
            f"Proyecto: [cyan]{project_path}[/cyan]\n"
            f"Script oficial: [cyan]{script.name}[/cyan] (vendor-pinned)\n"
            f"Threshold check 6: {threshold}",
            border_style="cyan",
        )
    )

    # Pasamos la salida tal cual (el script ya imprime con colores ANSI)
    result = subprocess.run(cmd, env=env, check=False)
    if result.returncode != 0:
        console.print(
            "\n[yellow]Nota:[/yellow] el script oficial terminó con exit != 0. "
            "Ver el reporte markdown generado."
        )
    # El script no hace sys.exit(1) en caso de FAIL, asi que leemos el JSON
    # o simplemente devolvemos el returncode tal cual.
    raise typer.Exit(code=result.returncode)


@app.command("summary")
def validate_summary(
    project_path: Annotated[
        Path,
        typer.Argument(help="Ruta al proyecto Java migrado."),
    ],
    threshold: Annotated[int, typer.Option("--threshold", "-t")] = 3,
) -> None:
    """Corre el script oficial y devuelve tabla resumida (sin output completo)."""
    project_path = project_path.resolve()
    module = _load_vendor_module()

    # Uso programatico del script vendor
    report = module.run_validations(
        str(project_path),
        output_dir=None,
        threshold=threshold,
    )

    table = Table(
        title="Validacion oficial del banco (9 checks)",
        title_style="bold cyan",
    )
    table.add_column("#", justify="right")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Message")

    def _row(num: str, name: str, check) -> None:  # type: ignore[no-untyped-def]
        if check is None:
            table.add_row(num, name, "[dim]N/A[/dim]", "(no ejecutado)")
            return
        status_style = "green" if check.passed else "red"
        label = "PASS" if check.passed else "FAIL"
        if getattr(check, "warning", False):
            status_style = "yellow"
            label = "WARN"
        table.add_row(
            num, name, f"[{status_style}]{label}[/{status_style}]",
            check.message[:90]
        )

    _row("1", "Capas hexagonales", report.layers_check)
    if report.wsdl_checks:
        for i, c in enumerate(report.wsdl_checks, 1):
            _row(f"2.{i}", f"WSDL [{i}/{len(report.wsdl_checks)}]", c)
    else:
        table.add_row("2", "WSDL framework", "[dim]N/A[/dim]", "sin WSDL")
    _row("3", "@BpTraceable (controllers)", report.controller_annotation_check)
    _row("4", "@BpLogger (services)", report.service_annotation_check)
    _row("5", "Sin navegacion cruzada", report.layer_navigation_check)
    _row("6", "Service business logic puro", report.service_business_logic_check)
    _row("7", "application.yml sin defaults", report.application_yml_check)
    _row("8", "Gradle lib-bnc-api-client", report.gradle_library_check)
    _row("9", "catalog-info.yaml", report.catalog_info_check)

    console.print(table)

    all_checks = (
        [report.layers_check]
        + list(report.wsdl_checks)
        + [
            report.controller_annotation_check,
            report.service_annotation_check,
            report.layer_navigation_check,
            report.service_business_logic_check,
            report.application_yml_check,
            report.gradle_library_check,
            report.catalog_info_check,
        ]
    )
    passed = sum(1 for c in all_checks if c and c.passed)
    total = sum(1 for c in all_checks if c is not None)
    color = "green" if passed == total else "red"
    console.print(
        f"\n[bold]Resultado:[/bold] [{color}]{passed}/{total} checks pasados[/{color}]"
    )
    if passed < total:
        console.print(
            "\n[yellow]Este PR seria rechazado por el reviewer oficial.[/yellow] "
            "Correr `capamedia check --auto-fix` para ver cuantos se pueden "
            "corregir automaticamente."
        )
        raise typer.Exit(code=1)


@app.command("sync")
def validate_sync(
    source: Annotated[
        Path,
        typer.Option(
            "--from",
            help="Ruta a la nueva version del script oficial (local o URL)",
        ),
    ],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Aplicar sin confirmar"),
    ] = False,
) -> None:
    """Actualiza el script vendor-pinned desde una fuente nueva."""
    source = source.expanduser().resolve()
    if not source.exists():
        console.print(f"[red]Source no existe:[/red] {source}")
        raise typer.Exit(code=2)

    target = _vendor_script_path()
    if target.exists():
        old_size = target.stat().st_size
    else:
        old_size = 0
    new_size = source.stat().st_size

    console.print(
        Panel.fit(
            "[bold]validate-hexagonal sync[/bold]\n"
            f"Source: [cyan]{source}[/cyan] ({new_size} bytes)\n"
            f"Target: [cyan]{target}[/cyan] ({old_size} bytes)",
            border_style="cyan",
        )
    )

    if not yes:
        from rich.prompt import Confirm

        if not Confirm.ask("Aplicar actualizacion?"):
            console.print("[yellow]Cancelado.[/yellow]")
            raise typer.Exit(code=0)

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    console.print(f"[green]OK[/green] script actualizado: {target}")


@app.command("auto-fix")
def validate_auto_fix(
    project_path: Annotated[
        Path,
        typer.Argument(help="Ruta al proyecto migrado."),
    ],
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            help="Descripcion del servicio para catalog-info.yaml (regla 9)",
        ),
    ] = None,
    owner: Annotated[
        str | None,
        typer.Option(
            "--owner",
            help="Email @pichincha.com para spec.owner de catalog-info.yaml",
        ),
    ] = None,
    rules: Annotated[
        str | None,
        typer.Option(
            "--rules",
            help="Subset CSV de reglas a aplicar (ej '4,7'). Default: todas (4,7,8,9).",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Solo mostrar que se haria, sin modificar"),
    ] = False,
) -> None:
    """Aplica los 4 autofixes deterministas del script oficial (reglas 4, 7, 8, 9)."""
    from capamedia_cli.core.bank_autofix import run_bank_autofix

    project_path = project_path.resolve()
    if not project_path.is_dir():
        console.print(f"[red]Proyecto no existe:[/red] {project_path}")
        raise typer.Exit(code=2)

    rules_list = None
    if rules:
        rules_list = [r.strip() for r in rules.split(",") if r.strip()]

    console.print(
        Panel.fit(
            "[bold]validate-hexagonal auto-fix[/bold]\n"
            f"Proyecto: [cyan]{project_path}[/cyan]\n"
            f"Reglas: {rules_list or 'todas (4, 7, 8, 9)'}\n"
            f"Dry run: {'SI' if dry_run else 'NO'}",
            border_style="cyan",
        )
    )

    if dry_run:
        console.print(
            "\n[yellow]dry-run:[/yellow] sin cambios aplicados. "
            "Correr sin `--dry-run` para ejecutar."
        )
        return

    results = run_bank_autofix(
        project_path,
        rules=rules_list,
        description=description,
        owner=owner,
    )

    table = Table(title="Bank autofix results", title_style="bold cyan")
    table.add_column("Regla")
    table.add_column("Status")
    table.add_column("Cambios")
    table.add_column("Notas")
    for r in results:
        status = "[green]APPLIED[/green]" if r.applied else "[dim]skip[/dim]"
        changes = "\n".join(r.changes) if r.changes else "-"
        table.add_row(r.rule, status, changes, r.notes or "-")
    console.print(table)

    applied = sum(1 for r in results if r.applied)
    console.print(
        f"\n[bold]Autofixes aplicados:[/bold] {applied}/{len(results)}"
    )
    manual = [r for r in results if r.applied and r.notes]
    if manual:
        console.print(
            "\n[yellow]Revisar manualmente:[/yellow]"
        )
        for r in manual:
            console.print(f"  - Regla {r.rule}: {r.notes}")
    console.print(
        "\n[dim]Sugerido:[/dim] re-correr `capamedia validate-hexagonal "
        "summary <path>` para ver cuantos checks pasan ahora."
    )
