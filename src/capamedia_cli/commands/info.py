"""capamedia info - dashboard de pendientes del workspace (v0.23.12).

Muestra un resumen consolidado de archivos faltantes y handoffs pendientes
para cerrar un servicio migrado. Contempla los 3 tipos: WAS, BUS (IIB), ORQ.

Lee de:
  - .capamedia/config.yaml            (service_name)
  - .capamedia/properties-report.yaml (properties pendientes del banco)
  - .capamedia/secrets-report.yaml    (secretos KV, solo WAS con BD)
  - legacy/ + umps/                   (para detectar source_type)

Muestra:
  - Tipo del servicio (WAS/BUS/ORQ) + framework
  - Properties faltantes del banco (pending inputs)
  - Secretos KV requeridos (WAS con BD)
  - Downstream/integraciones (UMPs, TX repos, servicios invocados)
  - Handoffs pendientes (catalog-info owner, sonar key, etc.)
  - Siguiente paso concreto segun el tipo
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated  # noqa: F401

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _read_yaml_safe(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, yaml.YAMLError):
        return None


def _detect_source_type(workspace: Path, service_name: str) -> tuple[str, bool]:
    """Devuelve (source_type, has_bancs) detectando desde legacy si esta."""
    legacy_root = workspace / "legacy"
    if not legacy_root.is_dir():
        return ("", False)

    # Buscar el unico subdir bajo legacy/
    legacy_subs = [p for p in legacy_root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if len(legacy_subs) != 1:
        return ("", False)

    legacy_path = legacy_subs[0]
    try:
        from capamedia_cli.core.legacy_analyzer import (
            detect_bancs_connection,
            detect_source_kind,
        )
        st = detect_source_kind(legacy_path, service_name)
        hb, _ = detect_bancs_connection(legacy_path)
        return (st, hb)
    except Exception:
        return ("", False)


def _resolve_workspace(workspace: Path | None) -> Path:
    """Resuelve el workspace root desde el CWD o desde un path explicito."""
    if workspace:
        return workspace.resolve()
    cwd = Path.cwd().resolve()
    # Si el CWD tiene .capamedia/config.yaml, es un workspace directo
    if (cwd / ".capamedia" / "config.yaml").is_file():
        return cwd
    # Si esta bajo destino/<subdir>, subir 2 niveles
    if cwd.parent.name == "destino":
        return cwd.parent.parent
    return cwd


def _render_properties_section(workspace: Path) -> None:
    report = _read_yaml_safe(workspace / ".capamedia" / "properties-report.yaml")
    if report is None:
        console.print(
            "\n[bold cyan]Properties del banco[/bold cyan]\n"
            "  [dim]sin .capamedia/properties-report.yaml (correr "
            "`capamedia clone` o `capamedia review` para generarlo)[/dim]"
        )
        return

    shared = report.get("shared_catalog_keys_used") or {}
    specific = report.get("service_specific_properties") or []

    console.print("\n[bold cyan]Properties del banco[/bold cyan]")

    # Shared catalog - informativo, no bloqueante
    if shared:
        console.print("  [green]Catalogo compartido (embebido en CLI, no requiere accion):[/green]")
        for fname, keys in shared.items():
            key_count = len(keys) if isinstance(keys, list) else 0
            console.print(f"    [green]✓[/green] {fname} ({key_count} keys)")

    # Specific - pendientes o entregados
    if specific:
        pending = [p for p in specific if p.get("status") == "PENDING_FROM_BANK"]
        delivered = [p for p in specific if p.get("status") != "PENDING_FROM_BANK"]

        if delivered:
            console.print("  [green]Entregados / resueltos:[/green]")
            for p in delivered:
                console.print(
                    f"    [green]✓[/green] {p['file']} "
                    f"({p.get('status', 'OK')})"
                )

        if pending:
            console.print(f"  [red]Pendientes del banco ({len(pending)}):[/red]")
            for p in pending:
                keys_list = p.get("keys_used") or []
                source = p.get("source") or "service"
                console.print(
                    f"    [red]✗[/red] [bold]{p['file']}[/bold] "
                    f"({len(keys_list)} keys - source: {source})"
                )
                if keys_list:
                    keys_preview = ", ".join(keys_list[:6])
                    suffix = "..." if len(keys_list) > 6 else ""
                    console.print(f"      [dim]keys: {keys_preview}{suffix}[/dim]")
            console.print(
                "    [dim]-> pegar en `.capamedia/inputs/` o en la raiz del workspace[/dim]"
            )


def _render_secrets_section(workspace: Path, source_type: str, has_bancs: bool) -> None:
    report = _read_yaml_safe(workspace / ".capamedia" / "secrets-report.yaml")

    console.print("\n[bold cyan]Secretos Azure Key Vault[/bold cyan]")

    if report is None:
        if source_type == "was":
            console.print(
                "  [dim]sin .capamedia/secrets-report.yaml "
                "(no aplica si el WAS no tiene BD, o falta correr `review` para generarlo)[/dim]"
            )
        else:
            console.print(
                f"  [dim](no aplica a {source_type.upper() or 'desconocido'} - "
                "solo WAS con BD requiere secretos KV)[/dim]"
            )
        return

    if not report.get("has_database"):
        console.print(
            "  [dim]servicio sin BD - no requiere secretos KV del catalogo BPTPSRE[/dim]"
        )
        return

    required = report.get("secrets_required") or []
    unknown = report.get("jndi_references_unknown") or []

    if required:
        table = Table(show_header=True, header_style="bold cyan", padding=(0, 1))
        table.add_column("JNDI", style="cyan")
        table.add_column("BD")
        table.add_column("Secretos KV")
        for sr in required:
            table.add_row(
                sr.get("jndi", "?"),
                sr.get("base_de_datos", "?"),
                f"{sr.get('user_secret', '?')}\n{sr.get('password_secret', '?')}",
            )
        console.print(table)
        console.print(
            "  [dim]-> declarar en `helm/values-{dev,test,prod}.yml` bloque "
            "`container.secret:` con name/location (ver bank-secrets.md)[/dim]"
        )
    else:
        console.print(
            "  [dim]BD detectada pero sin JNDI en el catalogo oficial[/dim]"
        )

    if unknown:
        unique_jndi = sorted({h.get("jndi") for h in unknown if h.get("jndi")})
        console.print(
            f"\n  [yellow]JNDI fuera del catalogo oficial ({len(unique_jndi)}):[/yellow]"
        )
        for j in unique_jndi:
            console.print(f"    [yellow]?[/yellow] {j}")
        console.print(
            "    [dim]-> consultar con SRE; si es nuevo, agregar a bank-secrets.md[/dim]"
        )


def _render_downstream_section(
    workspace: Path, source_type: str, has_bancs: bool,
) -> None:
    """Muestra TX, UMPs, o servicios downstream segun el tipo."""
    console.print("\n[bold cyan]Downstream / Integraciones[/bold cyan]")

    umps_root = workspace / "umps"
    ump_dirs = (
        [p.name for p in umps_root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if umps_root.is_dir() else []
    )

    tx_root = workspace / "tx"
    tx_dirs = (
        [p.name for p in tx_root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if tx_root.is_dir() else []
    )

    if source_type == "orq":
        # ORQ invoca servicios migrados de tpl-middleware, NO legacy
        console.print(
            "  [dim]Tipo ORQ -> invoca servicios migrados en tpl-middleware[/dim]\n"
            "  [dim]Verificar en el codigo Java cuales servicios externos llama.[/dim]\n"
            "  [dim]Regla 10.5: NUNCA referenciar sqb-msa-<svc> o ws-<svc>-was[/dim]"
        )
        return

    if source_type == "bus":
        console.print(
            f"  UMPs clonadas: [bold]{len(ump_dirs)}[/bold] "
            f"({', '.join(ump_dirs[:5])}{'...' if len(ump_dirs) > 5 else ''})"
        )
        console.print(
            f"  TX repos clonados: [bold]{len(tx_dirs)}[/bold] "
            f"({', '.join(tx_dirs[:5])}{'...' if len(tx_dirs) > 5 else ''})"
        )
        if has_bancs:
            console.print(
                "  [dim]Conecta a BANCS - matriz MCP fuerza REST+WebFlux (override)[/dim]"
            )
        return

    if source_type == "was":
        console.print(
            f"  UMPs clonadas: [bold]{len(ump_dirs)}[/bold] "
            f"({', '.join(ump_dirs[:5])}{'...' if len(ump_dirs) > 5 else ''})"
        )
        if tx_dirs:
            console.print(
                f"  TX repos: [bold]{len(tx_dirs)}[/bold] "
                f"(poco comun en WAS - verificar si realmente aplican)"
            )
        return

    # Desconocido
    console.print(
        f"  UMPs: {len(ump_dirs)}, TX repos: {len(tx_dirs)}"
    )


def _render_handoffs_section(workspace: Path) -> None:
    """Items que no pueden ser autofixeados - handoff al owner/ops."""
    console.print("\n[bold cyan]Handoffs pendientes (NO son bugs del codigo)[/bold cyan]")

    items: list[tuple[str, str]] = []

    # catalog-info.yaml
    destino = workspace / "destino"
    if destino.is_dir():
        subs = [p for p in destino.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if len(subs) == 1:
            catalog_yml = subs[0] / "catalog-info.yaml"
            if catalog_yml.is_file():
                content = catalog_yml.read_text(encoding="utf-8", errors="replace")
                if "TODO@pichincha.com" in content or "<placeholder" in content.lower():
                    items.append((
                        "catalog-info.yaml",
                        "completar spec.owner con email real + URL Confluence",
                    ))
                if "<uuid-de-sonarcloud>" in content or "SONARCLOUD_PROJECT_KEY" in content:
                    items.append((
                        "catalog-info.yaml",
                        "copiar sonarcloud.io/project-key tras primer pipeline",
                    ))

    # .sonarlint/connectedMode.json
    sonarlint = workspace / ".sonarlint" / "connectedMode.json"
    if sonarlint.is_file():
        content = sonarlint.read_text(encoding="utf-8", errors="replace")
        if "<PROJECT_KEY_FROM_SONARCLOUD>" in content:
            items.append((
                ".sonarlint/connectedMode.json",
                "reemplazar placeholder con project_key real de SonarCloud",
            ))

    if not items:
        console.print("  [green]Sin handoffs pendientes detectables[/green]")
        return

    for file_, action in items:
        console.print(f"  [yellow]~[/yellow] [cyan]{file_}[/cyan]: {action}")


def _render_next_step(
    workspace: Path, source_type: str, has_pending_properties: bool,
) -> None:
    """Sugiere el siguiente paso concreto segun el estado."""
    console.print("\n[bold]Siguiente paso[/bold]")

    if has_pending_properties:
        console.print(
            "  1) Pedir los .properties pendientes al owner del servicio\n"
            "  2) Pegar en [cyan].capamedia/inputs/<file>.properties[/cyan] "
            "(o en la raiz del workspace)\n"
            "  3) [cyan]capamedia checklist[/cyan] (o `/doublecheck` en Claude Code)"
        )
        return

    # Si no hay pending properties, siguiente paso depende de si ya hay reports
    if (workspace / ".capamedia" / "reports").is_dir():
        console.print(
            "  [cyan]capamedia review[/cyan]  (completo, incluye validator oficial)"
        )
    else:
        console.print(
            "  [cyan]capamedia checklist[/cyan]  (check + autofixes)\n"
            "  Luego [cyan]capamedia review[/cyan]  (validator oficial incluido)"
        )


def info(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace", "-w",
            help="Workspace root (default: CWD o parent de destino/<proj>/).",
        ),
    ] = None,
) -> None:
    """Dashboard de pendientes del workspace (archivos, secretos, handoffs).

    Lee los reportes generados por clone/review y muestra un resumen
    consolidado de que esta entregado y que falta. Contempla los 3 tipos:
    WAS, BUS (IIB), ORQ.
    """
    ws = _resolve_workspace(workspace)

    # Leer service_name del config.yaml
    config = _read_yaml_safe(ws / ".capamedia" / "config.yaml") or {}
    service_name = str(config.get("service_name") or ws.name)

    # Detectar source_type del legacy
    source_type, has_bancs = _detect_source_type(ws, service_name)

    # Header
    source_display = source_type.upper() or "DESCONOCIDO"
    bancs_display = "SI" if has_bancs else "NO"
    console.print(
        Panel.fit(
            f"[bold]capamedia info[/bold]\n"
            f"Servicio: [cyan]{service_name}[/cyan]\n"
            f"Tipo: [cyan]{source_display}[/cyan] · invocaBancs: [cyan]{bancs_display}[/cyan]\n"
            f"Workspace: [cyan]{ws}[/cyan]",
            border_style="cyan",
        )
    )

    # Secciones
    _render_properties_section(ws)
    _render_secrets_section(ws, source_type, has_bancs)
    _render_downstream_section(ws, source_type, has_bancs)
    _render_handoffs_section(ws)

    # Siguiente paso (basado en pending)
    report = _read_yaml_safe(ws / ".capamedia" / "properties-report.yaml")
    has_pending_props = False
    if report:
        specific = report.get("service_specific_properties") or []
        has_pending_props = any(
            p.get("status") == "PENDING_FROM_BANK" for p in specific
        )
    _render_next_step(ws, source_type, has_pending_props)
