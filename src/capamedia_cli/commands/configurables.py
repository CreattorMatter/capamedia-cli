"""`capamedia configurables` — consulta el CSV operativo de configurables.

Existe para que el agente migrador NO haga `grep` a mano sobre ese archivo. El
CSV esta en ISO-8859-1 con delimitador `;`, y un `grep` en locale UTF-8 sale con
codigo 1 y sin salida: indistinguible de "no encontrado". Esa confusion produjo
un falso negativo real en la migracion de WSSeguridad0069 (2026-09-03), donde
`UMPSeguridad0087Config` (con la `url` y el `ns` de Cyxtera DetectID) se reporto
como ausente teniendo 12 filas en el CSV.

Contrato de exit codes (lo que el `|| echo "NO ENCONTRADO"` borraba):

  0 -> hay filas. Respuesta afirmativa.
  1 -> el CSV se leyo bien y la clave NO esta. Respuesta negativa DEFINITIVA:
       recien aca aplica "documentar como pendiente del SRE".
  2 -> el CSV no se pudo localizar o leer. NO hay respuesta; nunca concluir
       que la configurable no existe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from capamedia_cli.core.configurables import (
    CSV_ENCODING,
    ConfigurablesCsvError,
    as_yaml_block,
    distinct_configurables,
    find_configurables_csv,
    load_rows,
    lookup,
    rows_with_encoding_artifacts,
)

console = Console()

EXIT_FOUND = 0
EXIT_NOT_IN_CSV = 1
EXIT_CSV_UNAVAILABLE = 2


def _emit_json(payload: dict) -> None:
    """JSON en una linea por stdout plano.

    NO usar `console.print_json`: Rich lo colorea y lo envuelve a 80 columnas,
    lo que puede romper el `json.loads` del agente que consume la salida.
    """
    typer.echo(json.dumps(payload, ensure_ascii=False))


def configurables(
    name: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Nombre del configurable a buscar (ej. UMPSeguridad0087Config). "
                "Si se omite, lista los configurables disponibles."
            )
        ),
    ] = None,
    variable: Annotated[
        str | None,
        typer.Option("--variable", "-v", help="Filtrar tambien por nombre de Variable"),
    ] = None,
    exact: Annotated[
        bool,
        typer.Option("--exact", help="Match exacto del nombre (default: substring)"),
    ] = False,
    csv_path: Annotated[
        Path | None,
        typer.Option("--csv", help="Path explicito al CSV (o a la carpeta que lo contiene)"),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Salida JSON en una linea (para consumo de agentes)"),
    ] = False,
    as_yaml: Annotated[
        bool,
        typer.Option("--yaml", help="Emitir el bloque application.yml listo para pegar"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximo de filas a mostrar (0 = todas)"),
    ] = 0,
) -> None:
    """Consulta el CSV de configurables del banco con el encoding correcto.

    El CSV es ISO-8859-1 con delimitador `;` y columnas
    `Configurable;Variable;Valor`. Exit code 1 = leido y no esta (definitivo);
    exit code 2 = no se pudo leer (sin respuesta, no concluir ausencia).
    """
    path = find_configurables_csv(Path.cwd(), csv_path)
    if path is None:
        message = (
            "CSV de configurables no encontrado. NO concluyas que la configurable no "
            "existe: no hay respuesta. Busca `ConfigurablesBusOmni*.csv` en el repo "
            "local PromptCapaMedia y pasalo con --csv."
        )
        if as_json:
            _emit_json({"status": "csv_unavailable", "detail": message})
        else:
            console.print(f"[red]FAIL[/red] {message}")
        raise typer.Exit(EXIT_CSV_UNAVAILABLE)

    try:
        rows = load_rows(path)
    except ConfigurablesCsvError as exc:
        if as_json:
            _emit_json({"status": "csv_unavailable", "detail": str(exc)})
        else:
            console.print(f"[red]FAIL[/red] {exc}")
        raise typer.Exit(EXIT_CSV_UNAVAILABLE) from None

    names = distinct_configurables(rows)

    # Sin nombre: inventario. Nunca truncamos en silencio (concluir ausencia
    # desde una lista cortada fue parte del falso negativo original).
    if not name:
        if as_json:
            _emit_json(
                {
                    "status": "ok",
                    "csv": str(path),
                    "encoding": CSV_ENCODING,
                    "rows": len(rows),
                    "configurables": names,
                }
            )
            raise typer.Exit(EXIT_FOUND)
        console.print(f"[dim]{path}[/dim]")
        console.print(
            f"[bold]{len(names)}[/bold] configurables distintos en "
            f"[bold]{len(rows)}[/bold] filas ({CSV_ENCODING}, delimitador ';')\n"
        )
        shown = names if limit <= 0 else names[:limit]
        for item in shown:
            console.print(f"  {item}")
        if len(shown) < len(names):
            console.print(
                f"\n[yellow]Mostrando {len(shown)} de {len(names)}[/yellow] "
                "(usa --limit 0 para la lista completa; no concluyas ausencia "
                "desde una lista truncada)"
            )
        raise typer.Exit(EXIT_FOUND)

    hits = lookup(rows, name, variable=variable, exact=exact)

    if not hits:
        detail = (
            f"'{name}'"
            + (f" con variable '{variable}'" if variable else "")
            + f" no esta en el CSV ({len(rows)} filas leidas OK). "
            "Respuesta definitiva: documentalo como pendiente del SRE, no inventes el valor."
        )
        if as_json:
            _emit_json(
                {"status": "not_found", "csv": str(path), "query": name, "detail": detail}
            )
        else:
            console.print(f"[yellow]NOT FOUND[/yellow] {detail}")
        raise typer.Exit(EXIT_NOT_IN_CSV)

    shown_rows = hits if limit <= 0 else hits[:limit]

    if as_json:
        _emit_json(
            {
                "status": "ok",
                "csv": str(path),
                "query": name,
                "total": len(hits),
                "rows": [
                    {"configurable": r.configurable, "variable": r.variable, "valor": r.valor}
                    for r in shown_rows
                ],
            }
        )
        raise typer.Exit(EXIT_FOUND)

    if as_yaml:
        console.print(as_yaml_block(shown_rows))
        raise typer.Exit(EXIT_FOUND)

    table = Table(title=f"Configurables: {name}", title_style="bold cyan")
    table.add_column("Configurable", style="cyan")
    table.add_column("Variable")
    table.add_column("Valor", style="bold")
    for row in shown_rows:
        table.add_row(row.configurable, row.variable, row.valor)
    console.print(table)
    console.print(
        f"[dim]{len(shown_rows)} de {len(hits)} fila(s) | {path.name} | {CSV_ENCODING}[/dim]"
    )

    suspicious = rows_with_encoding_artifacts(shown_rows)
    if suspicious:
        console.print(
            f"\n[yellow]WARN[/yellow] {len(suspicious)} valor(es) traen un acento mal "
            "codificado en el CSV de origen (ej. `Notificacion` con byte 0xE2). NO copies "
            "ese literal a application.yml: pedi el texto exacto al SRE."
        )
    raise typer.Exit(EXIT_FOUND)
