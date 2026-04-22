"""capamedia canonical - sync de prompts vivos de CapaMedia hacia el canonical del CLI.

Subcomandos:
  - sync   Muestra diff entre source y canonical, pide confirm y aplica.
  - diff   Solo muestra diff, nunca escribe.

Flujo:
    Julian mantiene prompts en C:/Dev/Banco Pichincha/CapaMedia/prompts/**
    El CLI tiene la copia canonica en src/capamedia_cli/data/canonical/prompts/**
    Este comando mapea uno a otro por nombre, diffea y (opcional) aplica.

Preservacion de frontmatter:
    El canonical tiene YAML frontmatter (---...---) pero los sources de Julian
    son markdown plano. Al aplicar, si el source NO tiene frontmatter y el
    canonical SI, preservamos el frontmatter del canonical y reemplazamos
    unicamente el body. Nunca borramos orphans (canonical que no tiene source).
"""

from __future__ import annotations

import datetime as dt
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from capamedia_cli.core.frontmatter import parse_frontmatter, serialize_frontmatter

console = Console()

app = typer.Typer(
    help="Gestion del canonical de prompts/skills/agents/context.",
    no_args_is_help=True,
)


# Mapeo explicito source-relative -> canonical-relative.
# El source tiene prefijos numericos (01-, 02-, 03-) y subcarpetas temeticas
# que no estan en el canonical.
EXPLICIT_MAPPINGS: dict[str, str] = {
    "pre-migracion/01-analisis-servicio.md": "prompts/analisis-servicio.md",
    "pre-migracion/analisis-servicio.md": "prompts/analisis-servicio.md",
    "pre-migracion/01-analisis-orq.md": "prompts/analisis-orq.md",
    "pre-migracion/analisis-orq.md": "prompts/analisis-orq.md",
    "migracion/REST/02-REST-migrar-servicio.md": "prompts/migrate-rest-full.md",
    "migracion/migrate-rest-full.md": "prompts/migrate-rest-full.md",
    "migracion/SOAP/02-SOAP-migrar-servicio.md": "prompts/migrate-soap-full.md",
    "migracion/migrate-soap-full.md": "prompts/migrate-soap-full.md",
    "post-migracion/03-checklist.md": "prompts/checklist-rules.md",
    "post-migracion/checklist-rules.md": "prompts/checklist-rules.md",
}


@dataclass
class DiffEntry:
    """Un archivo con su estado de diff contra canonical."""

    source_path: Path  # ruta absoluta al archivo fuente (o canonical en ORPHAN)
    target_path: Path  # ruta absoluta al canonical donde iria el contenido
    rel_display: str  # path relativo para mostrar en la tabla
    status: str  # UPDATED | NEW | ORPHAN | SKIPPED | IDENTICAL
    plus_lines: int = 0
    minus_lines: int = 0
    diff_text: str = ""
    new_content: str = ""  # contenido ya resuelto con frontmatter preservation
    skip_reason: str = ""


def _canonical_root() -> Path:
    """Ubicacion del canonical empaquetado con el CLI."""
    return Path(__file__).resolve().parent.parent / "data" / "canonical"


def _map_source_to_canonical(
    source_file: Path, source_root: Path, canonical_root: Path
) -> Path | None:
    """Dado un archivo source absoluto, devuelve su canonical destino o None.

    Estrategia (en orden):
    1. Match exacto en EXPLICIT_MAPPINGS usando rel path con '/'.
    2. Archivos en configuracion-claude-code/**/*.md -> context/ por nombre.
    3. Fallback por nombre de archivo contra canonical/prompts/<name>.
    4. None si nada matchea.
    """
    try:
        rel = source_file.relative_to(source_root)
    except ValueError:
        return None

    rel_key = rel.as_posix()

    if rel_key in EXPLICIT_MAPPINGS:
        return canonical_root / EXPLICIT_MAPPINGS[rel_key]

    parts = rel.parts
    if parts and parts[0] == "configuracion-claude-code":
        return canonical_root / "context" / rel.name

    # Fallback: si existe con el mismo nombre en canonical/prompts, mapear alli.
    prompts_candidate = canonical_root / "prompts" / rel.name
    if prompts_candidate.exists():
        return prompts_candidate

    return None


def _resolve_new_content(source_text: str, canonical_text: str) -> str:
    """Aplica preservacion de frontmatter.

    - source sin fm + canonical con fm -> preservar fm del canonical, body del source.
    - source con fm + canonical con fm -> preservar fm del canonical, body del source.
    - source con fm + canonical sin fm -> preservar fm del source + body del source (= source tal cual).
    - ninguno con fm -> source tal cual.
    """
    src_fm, src_body = parse_frontmatter(source_text)
    can_fm, _ = parse_frontmatter(canonical_text)

    if can_fm:
        return serialize_frontmatter(can_fm, src_body if src_fm else source_text)

    return source_text


def _collect_diffs(
    source_root: Path,
    canonical_root: Path,
    include_glob: str,
) -> list[DiffEntry]:
    """Recorre source + canonical y construye la lista de DiffEntry."""
    entries: list[DiffEntry] = []
    seen_canonicals: set[Path] = set()

    for source_file in sorted(source_root.glob(include_glob)):
        if not source_file.is_file():
            continue

        target = _map_source_to_canonical(source_file, source_root, canonical_root)
        rel = source_file.relative_to(source_root).as_posix()

        if target is None:
            entries.append(
                DiffEntry(
                    source_path=source_file,
                    target_path=source_file,  # placeholder, no se usa
                    rel_display=rel,
                    status="SKIPPED",
                    skip_reason="no mapping",
                )
            )
            continue

        seen_canonicals.add(target)
        source_text = source_file.read_text(encoding="utf-8")

        if not target.exists():
            new_content = source_text
            entries.append(
                DiffEntry(
                    source_path=source_file,
                    target_path=target,
                    rel_display=target.relative_to(canonical_root).as_posix(),
                    status="NEW",
                    plus_lines=len(new_content.splitlines()),
                    minus_lines=0,
                    diff_text="",
                    new_content=new_content,
                )
            )
            continue

        canonical_text = target.read_text(encoding="utf-8")
        new_content = _resolve_new_content(source_text, canonical_text)

        if new_content == canonical_text:
            entries.append(
                DiffEntry(
                    source_path=source_file,
                    target_path=target,
                    rel_display=target.relative_to(canonical_root).as_posix(),
                    status="IDENTICAL",
                )
            )
            continue

        diff_lines = list(
            difflib.unified_diff(
                canonical_text.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"canonical/{target.relative_to(canonical_root).as_posix()}",
                tofile=f"source/{rel}",
            )
        )
        plus = sum(
            1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
        )
        minus = sum(
            1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
        )
        entries.append(
            DiffEntry(
                source_path=source_file,
                target_path=target,
                rel_display=target.relative_to(canonical_root).as_posix(),
                status="UPDATED",
                plus_lines=plus,
                minus_lines=minus,
                diff_text="".join(diff_lines),
                new_content=new_content,
            )
        )

    # Orphans: canonical que nunca vimos en source.
    for canonical_file in sorted(canonical_root.rglob("*.md")):
        if canonical_file in seen_canonicals:
            continue
        entries.append(
            DiffEntry(
                source_path=canonical_file,
                target_path=canonical_file,
                rel_display=canonical_file.relative_to(canonical_root).as_posix(),
                status="ORPHAN",
            )
        )

    return entries


def _render_table(entries: list[DiffEntry]) -> None:
    table = Table(title="Canonical sync - diff summary", show_lines=False)
    table.add_column("path", style="cyan", no_wrap=False)
    table.add_column("status", style="bold")
    table.add_column("+lines", justify="right", style="green")
    table.add_column("-lines", justify="right", style="red")

    status_styles = {
        "UPDATED": "yellow",
        "NEW": "green",
        "ORPHAN": "magenta",
        "SKIPPED": "dim",
        "IDENTICAL": "dim",
    }

    for entry in entries:
        style = status_styles.get(entry.status, "white")
        plus = str(entry.plus_lines) if entry.plus_lines else "-"
        minus = str(entry.minus_lines) if entry.minus_lines else "-"
        label = f"[{entry.status}]"
        if entry.status == "SKIPPED" and entry.skip_reason:
            label = f"[SKIPPED: {entry.skip_reason}]"
        table.add_row(entry.rel_display, f"[{style}]{label}[/{style}]", plus, minus)

    console.print(table)


def _count_actionable(entries: list[DiffEntry]) -> int:
    return sum(1 for e in entries if e.status in ("UPDATED", "NEW"))


def _apply_changes(entries: list[DiffEntry]) -> list[DiffEntry]:
    """Escribe los archivos UPDATED y NEW. Devuelve los que fueron aplicados."""
    applied: list[DiffEntry] = []
    for entry in entries:
        if entry.status not in ("UPDATED", "NEW"):
            continue
        entry.target_path.parent.mkdir(parents=True, exist_ok=True)
        entry.target_path.write_text(entry.new_content, encoding="utf-8")
        applied.append(entry)
    return applied


def _write_log(applied: list[DiffEntry], log_dir: Path) -> Path:
    """Persiste diffs aplicados en .capamedia/canonical-sync/<timestamp>.log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = log_dir / f"{timestamp}.log"
    lines: list[str] = [
        f"# canonical sync log {timestamp}",
        f"# entries applied: {len(applied)}",
        "",
    ]
    for entry in applied:
        lines.append(f"## {entry.status} {entry.rel_display}")
        lines.append(f"source: {entry.source_path}")
        lines.append(f"target: {entry.target_path}")
        lines.append("")
        if entry.diff_text:
            lines.append(entry.diff_text)
        else:
            lines.append("(no prior content; NEW file)")
        lines.append("")
    log_file.write_text("\n".join(lines), encoding="utf-8")
    return log_file


def _print_diffs(entries: list[DiffEntry]) -> None:
    for entry in entries:
        if entry.status == "UPDATED" and entry.diff_text:
            console.print(
                Panel(
                    entry.diff_text.rstrip(),
                    title=f"diff: {entry.rel_display}",
                    border_style="yellow",
                )
            )


@app.command("sync")
def canonical_sync(
    source: Annotated[
        Path,
        typer.Option(
            "--source",
            help="Root de los prompts vivos de CapaMedia (p.ej. .../CapaMedia/prompts).",
        ),
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Solo mostrar diff; no escribir nada.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Aplicar sin pedir confirmacion.")
    ] = False,
    include_glob: Annotated[
        str, typer.Option("--include", help="Glob relativo al source root.")
    ] = "**/*.md",
    log_dir: Annotated[
        Path,
        typer.Option(
            "--log-dir",
            help="Directorio donde persistir el log de diffs aplicados.",
        ),
    ] = Path(".capamedia/canonical-sync"),
) -> None:
    """Sincroniza los prompts vivos de CapaMedia con el canonical del CLI."""
    source = source.expanduser().resolve()
    if not source.is_dir():
        console.print(f"[red]source no existe o no es directorio:[/red] {source}")
        raise typer.Exit(code=2)

    canonical_root = _canonical_root()

    entries = _collect_diffs(source, canonical_root, include_glob)
    _render_table(entries)
    _print_diffs(entries)

    actionable = _count_actionable(entries)
    if actionable == 0:
        console.print("[green]No hay cambios para aplicar.[/green]")
        return

    if dry_run:
        console.print(
            f"[cyan]--dry-run:[/cyan] {actionable} cambio(s) detectado(s); no se escribio nada."
        )
        return

    if not yes and not Confirm.ask(f"Aplicar {actionable} cambio(s)?", default=False):
        console.print("[yellow]Abortado por el usuario.[/yellow]")
        raise typer.Exit(code=1)

    applied = _apply_changes(entries)
    log_file = _write_log(applied, log_dir)
    console.print(
        f"[green]Aplicados {len(applied)} archivo(s).[/green] "
        f"Log: [cyan]{log_file}[/cyan]"
    )


@app.command("diff")
def canonical_diff(
    source: Annotated[
        Path,
        typer.Option("--source", help="Root de los prompts vivos de CapaMedia."),
    ],
    include_glob: Annotated[
        str, typer.Option("--include", help="Glob relativo al source root.")
    ] = "**/*.md",
) -> None:
    """Muestra el diff entre source y canonical sin aplicar cambios."""
    source = source.expanduser().resolve()
    if not source.is_dir():
        console.print(f"[red]source no existe o no es directorio:[/red] {source}")
        raise typer.Exit(code=2)

    canonical_root = _canonical_root()
    entries = _collect_diffs(source, canonical_root, include_glob)
    _render_table(entries)
    _print_diffs(entries)

    actionable = _count_actionable(entries)
    console.print(
        f"[cyan]Detectados[/cyan] {actionable} cambio(s). Usa 'capamedia canonical sync' para aplicarlos."
    )


# ---------------------------------------------------------------------------
# audit — verifica que cada regla del canonical tenga MUST/NEVER + ejemplo NO
# ---------------------------------------------------------------------------

AUDIT_FILES = (
    "prompts/migrate-rest-full.md",
    "prompts/migrate-soap-full.md",
    "prompts/checklist-rules.md",
    "context/bancs.md",
    "context/hexagonal.md",
    "context/code-style.md",
    "context/security.md",
    "context/bank-official-rules.md",  # las 9 reglas del banco - deben tener todas MUST/NEVER
    "agents/migrador.md",
    "agents/validador-hex.md",
)

# Reglas oficiales del banco (validate_hexagonal.py) que DEBEN existir en el
# canonical con MUST/NEVER + ejemplo NO. El audit falla si alguna falta.
OFFICIAL_BANK_RULES = {
    "1": "Capas application/domain/infrastructure",
    "2": "WSDL framework (1 op REST+WebFlux, 2+ SOAP+MVC)",
    "3": "@BpTraceable controllers",
    "4": "@BpLogger services",
    "5": "Sin navegacion cruzada entre capas",
    "6": "Services sin metodos utilitarios",
    "7": "application.yml sin ${VAR:default}",
    "8": "Gradle lib-bnc-api-client obligatoria",
    "9": "catalog-info.yaml completo",
}

# Palabras que marcan reglas operativas (si una seccion tiene estas palabras
# DEBE tener tambien MUST/NEVER/OBLIGATORIO/PROHIBIDO con claridad).
RULE_MARKERS = ("Rule ", "Regla ", "### ", "- **")
IMPERATIVE_MARKERS = (
    "MUST",
    "NEVER",
    "SIEMPRE",
    "NUNCA",
    "PROHIBIDO",
    "OBLIGATORIO",
    "REQUIRED",
    "FORBIDDEN",
)
NEG_EXAMPLE_MARKERS = ("// NO", "// BAD", "// WRONG", "# NO", "# BAD", "# WRONG")


@dataclass
class AuditEntry:
    file_path: str
    total_sections: int
    sections_with_imperative: int
    sections_with_neg_example: int
    missing_imperative: list[str]  # titulos sin MUST/NEVER
    missing_neg_example: list[str]  # titulos sin ejemplo NO


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Divide un markdown en (titulo, cuerpo) por headings `##`/`###`."""
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("### "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_body)))
            current_title = line.lstrip("#").strip()
            current_body = []
        else:
            if current_title is not None:
                current_body.append(line)
    if current_title is not None:
        sections.append((current_title, "\n".join(current_body)))
    return sections


def _audit_file(path: Path, relative_name: str) -> AuditEntry:
    text = path.read_text(encoding="utf-8")
    sections = _split_sections(text)
    imperative_count = 0
    neg_example_count = 0
    missing_imp: list[str] = []
    missing_neg: list[str] = []
    for title, body in sections:
        # Solo auditamos secciones que parezcan reglas operativas
        looks_like_rule = any(m.lower() in title.lower() for m in ("rule", "regla")) or any(
            body.lstrip().startswith(prefix) for prefix in ("- **", "* **")
        )
        if not looks_like_rule:
            continue
        has_imperative = any(m in body.upper() for m in IMPERATIVE_MARKERS)
        has_neg_example = any(m in body for m in NEG_EXAMPLE_MARKERS)
        if has_imperative:
            imperative_count += 1
        else:
            missing_imp.append(title[:80])
        if has_neg_example:
            neg_example_count += 1
        else:
            missing_neg.append(title[:80])
    return AuditEntry(
        file_path=relative_name,
        total_sections=len([s for s in sections if any(
            m.lower() in s[0].lower() for m in ("rule", "regla")
        ) or any(s[1].lstrip().startswith(p) for p in ("- **", "* **"))]),
        sections_with_imperative=imperative_count,
        sections_with_neg_example=neg_example_count,
        missing_imperative=missing_imp,
        missing_neg_example=missing_neg,
    )


@app.command("audit")
def canonical_audit(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Listar titulos sin MUST/NEVER")
    ] = False,
) -> None:
    """Audita el canonical: cada regla debe tener MUST/NEVER + ejemplo negativo."""
    root = _canonical_root()
    entries: list[AuditEntry] = []
    for relative in AUDIT_FILES:
        path = root / relative
        if not path.exists():
            console.print(f"[yellow]SKIP[/yellow] {relative} (no existe)")
            continue
        entries.append(_audit_file(path, relative))

    table = Table(title="Auditoria canonical MUST/NEVER + ejemplos NO", title_style="bold cyan")
    table.add_column("Archivo")
    table.add_column("Reglas", justify="right")
    table.add_column("Con imperativo", justify="right")
    table.add_column("Con ejemplo NO", justify="right")
    table.add_column("Gap imperativo", justify="right")
    table.add_column("Gap ejemplo NO", justify="right")
    total_gap_imp = 0
    total_gap_neg = 0
    for e in entries:
        gap_imp = len(e.missing_imperative)
        gap_neg = len(e.missing_neg_example)
        total_gap_imp += gap_imp
        total_gap_neg += gap_neg
        style_imp = "green" if gap_imp == 0 else "yellow" if gap_imp < 3 else "red"
        style_neg = "green" if gap_neg == 0 else "yellow" if gap_neg < 3 else "red"
        table.add_row(
            e.file_path,
            str(e.total_sections),
            str(e.sections_with_imperative),
            str(e.sections_with_neg_example),
            f"[{style_imp}]{gap_imp}[/{style_imp}]",
            f"[{style_neg}]{gap_neg}[/{style_neg}]",
        )
    console.print(table)
    console.print(
        f"\n[bold]Total gaps:[/bold] {total_gap_imp} sin imperativo · "
        f"{total_gap_neg} sin ejemplo NO"
    )
    if verbose:
        console.print()
        for e in entries:
            if not e.missing_imperative and not e.missing_neg_example:
                continue
            console.print(f"[bold cyan]{e.file_path}[/bold cyan]")
            if e.missing_imperative:
                console.print("  [yellow]Sin MUST/NEVER:[/yellow]")
                for t in e.missing_imperative:
                    console.print(f"    - {t}")
            if e.missing_neg_example:
                console.print("  [yellow]Sin ejemplo NO:[/yellow]")
                for t in e.missing_neg_example:
                    console.print(f"    - {t}")
    # Chequeo adicional: las 9 reglas del banco deben estar presentes
    bank_file = root / "context" / "bank-official-rules.md"
    missing_bank_rules: list[str] = []
    if bank_file.exists():
        bank_text = bank_file.read_text(encoding="utf-8")
        for rule_id, rule_name in OFFICIAL_BANK_RULES.items():
            # Heuristica: busca "Regla N" o "Rule N" en el archivo
            pattern = f"Regla {rule_id}"
            if pattern not in bank_text and f"Rule {rule_id}" not in bank_text:
                missing_bank_rules.append(f"{rule_id} ({rule_name})")
    else:
        missing_bank_rules = [
            f"{rid} ({name})" for rid, name in OFFICIAL_BANK_RULES.items()
        ]

    if missing_bank_rules:
        console.print(
            "\n[red]Faltan reglas oficiales del banco en el canonical:[/red]"
        )
        for r in missing_bank_rules:
            console.print(f"  - {r}")
        console.print(
            "[dim]Agregar cada regla faltante a "
            "`context/bank-official-rules.md` con MUST/NEVER + ejemplo.[/dim]"
        )
    else:
        console.print(
            "\n[green]OK[/green] las 9 reglas oficiales del banco estan en "
            "`context/bank-official-rules.md`."
        )

    if total_gap_imp > 0 or total_gap_neg > 0:
        console.print(
            "\n[yellow]Sugerencia:[/yellow] agregar MUST/NEVER y un ejemplo "
            "negativo (// NO) a cada regla operativa. Reduce alucinaciones "
            "de la AI."
        )
