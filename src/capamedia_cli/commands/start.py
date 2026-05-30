"""capamedia start - wizard orquestador "un click" (alias: go, wizard).

North Star (docs/BLUEPRINT_WIZARD_GO.md): un comando que migra un servicio de
0 a 100 con subagentes de punta a punta. Se construye por fases incrementales.

- **Fase 1**: fachada NO-interactiva sobre `batch._process_pipeline_service`
  (clone -> init -> fabrics -> migrate, con resume idempotente). Fuerza Opus 4.8.
- **Fase 2 (esta version)**: capa de entrada interactiva — Panel "Bienvenido a
  Capa Media", preflight verde/rojo NO-bloqueante (PAT + engine), menú raíz
  numerado (estilo Claude Code, sin deps nuevas: `rich.Prompt.ask(choices=...)`),
  y detección de `wizard.json` para reanudar. El sub-wizard de inputs (pedir
  servicio/OLA/rama interactivamente) llega en la Fase 3.

Reglas firmes: modelo SIEMPRE Opus 4.8 (el wizard nunca pregunta modelo); no se
reimplementa lógica (se reusan funciones existentes); el wizard CONVIVE con los
comandos shell/batch, no los reemplaza.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from capamedia_cli import __version__
from capamedia_cli.commands.init import LOGO
from capamedia_cli.core.auth import probe_azure_devops_pat
from capamedia_cli.core.engine import available_engines, engine_from_env, select_engine
from capamedia_cli.core.model_policy import anthropic_model, engine_model

console = Console()

WIZARD_STATE_FILE = "wizard.json"
# Modelo mostrado en la bienvenida (claude-first). El modelo REAL que se pasa al
# pipeline se deriva del engine activo con engine_model("opus", engine.name) —
# claude -> claude-opus-4-8, codex -> gpt-5.5 (el tope de cada engine).
OPUS_MODEL = anthropic_model("opus")


# ── Persistencia de decisiones (contrato para las fases siguientes) ──────────


def _save_wizard_decisions(service_workspace: Path, decisions: dict) -> Path:
    """Persiste las decisiones del wizard en <service_workspace>/.capamedia/wizard.json.

    NO es el state de progreso del pipeline (eso lo maneja batch_state con
    run_kind="pipeline"); son las decisiones de entrada para no re-preguntar.
    """
    cap = service_workspace / ".capamedia"
    cap.mkdir(parents=True, exist_ok=True)
    dest = cap / WIZARD_STATE_FILE
    dest.write_text(json.dumps(decisions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def load_wizard_decisions(service_workspace: Path) -> dict:
    """Lee las decisiones guardadas; {} si no existe o esta corrupto."""
    dest = service_workspace / ".capamedia" / WIZARD_STATE_FILE
    if dest.is_file():
        try:
            data = json.loads(dest.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _find_resumable(root: Path) -> list[str]:
    """Servicios con un wizard.json previo bajo `root` (para ofrecer reanudar)."""
    found: list[str] = []
    if not root.is_dir():
        return found
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / ".capamedia" / WIZARD_STATE_FILE).is_file():
            found.append(child.name)
    return found


# ── Bienvenida + preflight (Fase 2) ──────────────────────────────────────────


def _welcome_panel() -> None:
    console.print(LOGO.format(version=__version__))
    console.print(
        Panel.fit(
            "[bold cyan]Bienvenido a Capa Media[/bold cyan]\n"
            f"Orquestador de migracion · v{__version__}\n"
            f"Modelo: [magenta]{OPUS_MODEL}[/magenta] [dim](siempre Opus — calidad sobre costo)[/dim]",
            border_style="cyan",
        )
    )


def _run_preflight(claude_bin: str, codex_bin: str) -> dict:
    """Chequeo verde/rojo NO-bloqueante de los prerequisitos. Solo informa.

    Devuelve un dict con el estado para que el menu lo muestre sin re-chequear.
    """
    pat_status, pat_detail = probe_azure_devops_pat()
    engines = available_engines(claude_bin=claude_bin, codex_bin=codex_bin)
    return {"pat": (pat_status, pat_detail), "engines": engines}


def _render_preflight(preflight: dict) -> None:
    table = Table(title="Preflight (no bloquea — solo avisa)", title_style="bold cyan")
    table.add_column("Check")
    table.add_column("Estado")
    table.add_column("Detalle")

    pat_status, pat_detail = preflight["pat"]
    pat_ok = pat_status == "ok"
    table.add_row(
        "Azure DevOps PAT",
        "[green]OK[/green]" if pat_ok else f"[yellow]{pat_status.upper()}[/yellow]",
        pat_detail if not pat_ok else "PAT con acceso de lectura",
    )

    for name, (ok, detail) in preflight["engines"].items():
        marker = "[green]OK[/green]" if ok else "[yellow]no disponible[/yellow]"
        table.add_row(f"Engine {name}", marker, detail)

    console.print(table)
    if not preflight["engines"].get("claude", (False, ""))[0]:
        console.print(
            "[yellow]Aviso:[/yellow] el engine 'claude' no esta disponible; la "
            "migracion con Opus requiere Claude CLI. Instalalo o usa --engine codex."
        )


# ── Menu raiz (Fase 2) ────────────────────────────────────────────────────────

_MENU_OPTIONS = [
    ("1", "Iniciar migracion guiada"),
    ("2", "Configuracion: Harnesses (read-only)"),
    ("3", "Configuracion: Credenciales (read-only)"),
    ("4", "Engine y modelo (read-only)"),
    ("0", "Salir"),
]


def _root_menu() -> str:
    table = Table(show_header=False, box=None, padding=(0, 2))
    for key, label in _MENU_OPTIONS:
        table.add_row(f"[bold cyan]{key}[/bold cyan]", label)
    console.print(table)
    return Prompt.ask(
        "Elegi una opcion",
        choices=[k for k, _ in _MENU_OPTIONS],
        default="1",
    )


def _show_harnesses_readonly() -> None:
    from capamedia_cli.adapters import ALL_HARNESSES

    console.print(
        Panel.fit(
            "Harnesses soportados (edicion interactiva en una fase futura):\n"
            + ", ".join(ALL_HARNESSES),
            title="Harnesses",
            border_style="cyan",
        )
    )


def _show_engine_model_readonly(preflight: dict) -> None:
    lines = [f"Modelo: [magenta]{OPUS_MODEL}[/magenta] (siempre Opus — no configurable)"]
    for name, (ok, detail) in preflight["engines"].items():
        lines.append(f"Engine {name}: {'disponible' if ok else 'no disponible'} — {detail}")
    console.print(Panel.fit("\n".join(lines), title="Engine y modelo", border_style="cyan"))


# ── Sub-wizard de inputs (Fase 3) — recolecta SIN tocar red ──────────────────


def _ask_service(default: str | None = None) -> str:
    """Pide el servicio (no vacio) y lo normaliza (auto-padding a 4 digitos)."""
    from capamedia_cli.commands.clone import normalize_service_name

    while True:
        raw = (
            Prompt.ask("Servicio a migrar", default=default)
            if default
            else Prompt.ask("Servicio a migrar")
        )
        if raw and raw.strip():
            break
        console.print("[yellow]El servicio no puede estar vacio.[/yellow]")
    normalized, padded = normalize_service_name(raw)
    if padded:
        console.print(f"[dim]Normalizado: {raw} -> {normalized}[/dim]")
    return normalized


def _show_ola(service: str) -> tuple[str, str]:
    """Deriva y MUESTRA la OLA + version de lib (del catalogo oficial ola_policy).

    No se pregunta: la version de lib-bnc-api-client la determina is_ola2 sobre
    el catalogo oficial. El wizard la informa para transparencia.
    """
    from capamedia_cli.core.ola_policy import lib_bnc_api_client_version, ola_label

    label = ola_label(service)
    lib = lib_bnc_api_client_version(service)
    console.print(
        Panel.fit(
            f"OLA detectada: [bold]{label}[/bold]\n"
            f"lib-bnc-api-client: [magenta]{lib}[/magenta] "
            "[dim](derivado del catalogo oficial — no configurable aqui)[/dim]",
            title="OLA",
            border_style="cyan",
        )
    )
    return label, lib


def _ask_namespace(default: str = "tnd") -> str:
    from capamedia_cli.commands.fabrics import NAMESPACE_OPTIONS

    return Prompt.ask("Acronimo / namespace", choices=NAMESPACE_OPTIONS, default=default)


def _ask_branch_optional() -> str | None:
    """Rama deseada (opcional, sin tocar red). None = auto-detectar al clonar."""
    if not Confirm.ask("Especificar rama destino?", default=False):
        return None
    branch = Prompt.ask("Rama (ej: feature/dev-BTHCCC-1234)").strip()
    return branch or None


def _resolve_branch_interactive(
    repo_path: Path, requested_branch: str | None, service: str
) -> tuple[str, str]:
    """Resuelve la rama de un repo migrado YA CLONADO en `repo_path` (toca git).

    Reusa los helpers de clone. Convierte el caso 'ambiguous' (hoy error duro en
    `clone-migrated`) en un PICKER numerado de ramas remotas, con opcion de crear
    una feature nueva. Para los demas modos (explicit/auto/default) delega tal
    cual. Devuelve (branch, mode).
    """
    from capamedia_cli.commands.clone import (
        _auto_checkout_migrated_branch,
        _checkout_branch,
        _list_remote_branches,
    )

    branch, mode, error = _auto_checkout_migrated_branch(repo_path, requested_branch)
    if mode != "ambiguous":
        if error:
            console.print(f"[yellow]Rama ({mode}): {error}[/yellow]")
        else:
            console.print(f"[green]Rama:[/green] {branch or '(default)'} [dim]({mode})[/dim]")
        return branch, mode

    branches = _list_remote_branches(repo_path)
    new_branch = f"feature/migracion-{service}"
    console.print("[yellow]Multiples ramas candidatas — elegi una:[/yellow]")
    table = Table(show_header=False, box=None, padding=(0, 2))
    for i, b in enumerate(branches, 1):
        table.add_row(f"[cyan]{i}[/cyan]", b)
    table.add_row("[cyan]0[/cyan]", f"[+] crear {new_branch}")
    console.print(table)
    sel = Prompt.ask("Rama", choices=[str(i) for i in range(len(branches) + 1)], default="0")

    if sel == "0":
        result = subprocess.run(
            ["git", "-C", str(repo_path), "checkout", "-B", new_branch],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            console.print(
                f"[red]No se pudo crear {new_branch}: "
                f"{(result.stderr or result.stdout or '').strip()}[/red]"
            )
        else:
            console.print(f"[green]Rama creada y posicionada:[/green] {new_branch}")
        return new_branch, "created"

    chosen = branches[int(sel) - 1]
    ok, err = _checkout_branch(repo_path, chosen)
    if not ok:
        console.print(f"[red]checkout de {chosen} fallo: {err}[/red]")
    else:
        console.print(f"[green]Rama posicionada:[/green] {chosen}")
    return chosen, "picker"


def _derive_azure_target(namespace: str, service: str) -> str:
    """Repo destino migrado (derivado): tpl-middleware/<ns>-msa-sp-<svc>."""
    from capamedia_cli.commands.clone import AZURE_PROJECTS

    return f"{AZURE_PROJECTS['middleware']}/{namespace}-msa-sp-{service}"


def _ask_harnesses() -> list[str]:
    """Harnesses para el scaffold. Default: solo claude (siempre Opus). Ofrece el
    picker completo si el usuario quiere agregar otros."""
    if not Confirm.ask(
        "Configurar harnesses adicionales? (default: solo claude)", default=False
    ):
        return ["claude"]
    from capamedia_cli.commands.init import _interactive_harness_picker

    chosen = _interactive_harness_picker()
    if "claude" not in chosen:
        chosen.append("claude")  # forzamos claude — el wizard migra con Opus
    return chosen


_COMPLEXITY_COLOR = {"low": "green", "medium": "yellow", "high": "red"}


def _run_clone_with_progress(service: str, workspace: Path, shallow: bool, skip_tx: bool) -> bool:
    """Trae el legacy (clone_service). Devuelve True si completo. Idempotente:
    detecta el legacy local si ya esta. No rompe el wizard si falla — el pipeline
    lo reintenta."""
    from capamedia_cli.commands.clone import clone_service

    workspace.mkdir(parents=True, exist_ok=True)
    console.print(f"[cyan]Trayendo legacy de {service}...[/cyan]")
    try:
        clone_service(service, workspace=workspace, shallow=shallow, skip_tx=skip_tx)
        return True
    except typer.Exit:
        console.print("[yellow]El clone reporto un problema; el pipeline lo reintentara.[/yellow]")
        return False
    except Exception as exc:  # best-effort
        console.print(
            f"[yellow]Clone fallo ({type(exc).__name__}); el pipeline lo reintentara.[/yellow]"
        )
        return False


def _render_analysis_summary(workspace: Path, service: str) -> None:
    """Resumen visual del analisis (Fase 5). Cierra el gap "el COMPLEXITY_<svc>.md
    se escribe pero no se muestra": lo lee y lo presenta con badge de complejidad
    + EffortProfile + aviso de gate humano si HIGH. PURA lectura, no toca red."""
    from capamedia_cli.core.effort_policy import effort_for, resolve_service_complexity

    complexity = resolve_service_complexity(workspace, service)
    profile = effort_for(complexity)
    color = _COMPLEXITY_COLOR.get(complexity, "white")

    md = workspace / f"COMPLEXITY_{service}.md"
    body_lines: list[str] = []
    if md.is_file():
        text = md.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- **") or stripped.startswith("|"):
                body_lines.append(stripped)
    body = (
        "\n".join(body_lines)
        if body_lines
        else "[dim]sin reporte de analisis (COMPLEXITY_*.md)[/dim]"
    )

    console.print(
        Panel(
            f"{body}\n\n"
            f"Complejidad: [{color}]{complexity.upper()}[/{color}] · "
            f"Modelo: [magenta]{profile.model_tier}[/magenta] (Opus) · "
            f"retries extra: +{profile.extra_retries}",
            title=f"Resumen del analisis — {service}",
            border_style=color,
        )
    )
    if profile.needs_human_gate:
        console.print(
            "[yellow]Servicio HIGH: se sugiere revision humana del migrado "
            "(complejidad alta).[/yellow]"
        )


def _detect_and_prepare_flow(
    service: str, namespace: str, ws: Path, branch: str | None
) -> str:
    """Flujo "ambos" (decision owner): detecta si el servicio YA tiene destino
    migrado en tpl-middleware y rutea.

    - Si el destino existe -> modo "retomar": queda clonado en `destino/` y se
      posiciona la rama con el picker de Fase 4 (`_resolve_branch_interactive`).
    - Si no existe -> modo "nuevo": Fabrics generara el destino en el pipeline.

    Reusa `clone._clone_migrated_repos` con el namespace ya elegido (1 intento de
    red). Nunca lanza: ante error de red, asume modo "nuevo" e informa.
    Devuelve "retomar" | "nuevo".
    """
    from capamedia_cli.commands.clone import _clone_migrated_repos

    try:
        results = _clone_migrated_repos(service, ws, namespace=namespace)
    except Exception as exc:  # best-effort: no romper el wizard ante error de red
        console.print(
            f"[yellow]No se pudo verificar destino migrado ({type(exc).__name__}). "
            "Modo nuevo.[/yellow]"
        )
        return "nuevo"

    cloned = [r for r in results if getattr(r, "path", None)]
    if not cloned:
        console.print(
            "[cyan]Modo nuevo[/cyan]: sin migrado previo en tpl-middleware; "
            "Fabrics generara el destino."
        )
        return "nuevo"

    dest = cloned[0].path
    console.print(f"[cyan]Modo retomar[/cyan]: destino existente -> [dim]{dest}[/dim]")
    _resolve_branch_interactive(dest, branch, service)
    return "retomar"


def _confirm_plan(inputs: dict, model: str) -> bool:
    """Resumen pre-ejecucion + gate humano. Default NO (banca)."""
    table = Table(title="Plan de migracion", title_style="bold cyan")
    table.add_column("Campo")
    table.add_column("Valor")
    table.add_row("Servicio", inputs["service"])
    table.add_row("OLA", inputs["ola_label"])
    table.add_row("lib-bnc-api-client", inputs["lib_version"])
    table.add_row("Namespace", inputs["namespace"])
    table.add_row("Azure destino", inputs["azure_target"])
    table.add_row("Rama", inputs["branch"] or "(pendiente integracion)")
    table.add_row("Harnesses", ", ".join(inputs["harnesses"]))
    table.add_row("Modelo", f"{model} (siempre Opus)")
    console.print(table)
    return Confirm.ask("Ejecutar la migracion?", default=False)


def _collect_inputs_interactive(
    *, service: str | None = None, namespace: str | None = None, branch: str | None = None
) -> dict | None:
    """Recolecta TODAS las decisiones del wizard. NO toca red. Devuelve el dict
    de inputs, o None si el usuario cancela en cualquier gate."""
    console.print("\n[bold cyan]Sub-wizard de inputs[/bold cyan] [dim](no toca red)[/dim]")
    svc = service or _ask_service()
    ola_label_value, lib_version = _show_ola(svc)
    ns = namespace or _ask_namespace()
    azure_target = _derive_azure_target(ns, svc)
    console.print(f"Azure destino (derivado): [cyan]{azure_target}[/cyan]")
    if not Confirm.ask("Confirmas el destino?", default=True):
        console.print("[yellow]Cancelado.[/yellow]")
        return None
    harnesses = _ask_harnesses()
    branch_value = branch if branch else _ask_branch_optional()
    inputs = {
        "service": svc,
        "namespace": ns,
        "branch": branch_value,
        "ola_label": ola_label_value,
        "lib_version": lib_version,
        "azure_target": azure_target,
        "harnesses": harnesses,
    }
    # El modelo se muestra como el de claude (engine default del wizard).
    if not _confirm_plan(inputs, OPUS_MODEL):
        console.print("[yellow]Cancelado por el usuario en el resumen.[/yellow]")
        return None
    return inputs


# ── Fachada Fase 1 (reusable desde flags y desde el menu) ────────────────────


def _run_doublecheck_with_gate(
    *,
    service: str,
    ws: Path,
    engine,
    model: str | None,
    timeout_minutes: int,
    unsafe: bool,
    resume: bool,
) -> None:
    """Fase 6: corre el doublecheck AI tras el pipeline y aplica el GATE humano.

    Reusa `ai._process_doublecheck_workspace` (no reimplementa). Si el verdict es
    BLOCKED_BY_HIGH o hay findings HIGH, FRENA con aviso de revision humana — NO
    hay auto-push ni PR (gate critico de banca). El modelo es el del engine activo
    (tier opus). No rompe el wizard si el doublecheck no puede correr.
    """
    from capamedia_cli.commands.ai import _process_doublecheck_workspace
    from capamedia_cli.commands.batch import _ensure_migrate_schema

    console.print("\n[cyan]Doble check AI (post-migracion)...[/cyan]")
    workspace = ws / service
    schema_path = _ensure_migrate_schema(ws)
    try:
        row = _process_doublecheck_workspace(
            service,
            workspace,
            schema_path,
            engine=engine,
            model=model,
            prompt_file=None,
            timeout_minutes=timeout_minutes,
            unsafe=unsafe,
            resume=resume,
        )
    except Exception as exc:  # best-effort: el wizard no muere por el doublecheck
        console.print(
            f"[yellow]El doble check no pudo completarse ({type(exc).__name__}). "
            "Corre `capamedia ai doublecheck` manualmente.[/yellow]"
        )
        return

    verdict = str(row.fields.get("verdict", "?"))
    high = str(row.fields.get("high", "?"))
    blocked = row.status != "ok" or verdict.startswith("BLOCKED_BY_HIGH")

    if blocked:
        console.print(
            Panel.fit(
                f"[bold yellow]GATE: revision humana requerida[/bold yellow]\n"
                f"Verdict: [red]{verdict}[/red] · HIGH: {high}\n"
                f"{row.detail}\n\n"
                "[dim]El wizard NO hace push ni abre PR. Revisa los findings HIGH, "
                "corregilos (o corre `capamedia ai doublecheck`) y vuelve a "
                "ejecutar con --resume.[/dim]",
                title="Doble check — BLOQUEADO",
                border_style="red",
            )
        )
        raise typer.Exit(2)

    console.print(f"[green]Doble check OK[/green] · verdict: {verdict}")


def _run_pipeline_facade(
    *,
    service: str,
    namespace: str,
    branch: str | None,
    ws: Path,
    engine_name: str,
    claude_bin: str,
    codex_bin: str,
    ai: str,
    group_id: str,
    artifact_token: str | None,
    timeout_minutes: int,
    shallow: bool,
    skip_tx: bool,
    skip_check: bool,
    unsafe: bool,
    resume: bool,
    skip_doublecheck: bool = False,
) -> None:
    """Orquesta el pipeline existente para UN servicio, forzando Opus 4.8.

    No reimplementa logica: importa y llama `batch._process_pipeline_service`.
    Tras el pipeline encadena el doublecheck con gate BLOCKED_BY_HIGH (Fase 6).
    """
    from capamedia_cli.adapters import resolve_harnesses
    from capamedia_cli.commands.batch import (
        _ensure_migrate_schema,
        _process_pipeline_service,
    )
    from capamedia_cli.commands.init import _save_config

    env_pref = engine_from_env()
    eff_engine_name = env_pref or engine_name
    try:
        engine = select_engine(eff_engine_name, claude_bin=claude_bin, codex_bin=codex_bin)
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None

    harnesses = resolve_harnesses(ai)
    if engine.name not in harnesses:
        harnesses.append(engine.name)

    # Tier "opus" SIEMPRE (decision owner), traducido al modelo del engine activo:
    # claude -> claude-opus-4-8, codex -> gpt-5.5. Evita pasarle un modelo Claude
    # a Codex (o viceversa).
    model = engine_model("opus", engine.name)

    # Flujo "ambos": detectar destino migrado existente (retomar) vs nuevo. En
    # retomar trae el destino y posiciona la rama; el pipeline corre con resume.
    flow_mode = _detect_and_prepare_flow(service, namespace, ws, branch)

    # Fase 5: traer legacy + resumen visual del analisis ANTES del pipeline
    # (cumple la vision "trae legacy -> resumen -> correr fabrics"). El clone es
    # idempotente: el pipeline luego re-detecta el legacy local.
    if _run_clone_with_progress(service, ws / service, shallow, skip_tx):
        _render_analysis_summary(ws / service, service)

    schema_path = _ensure_migrate_schema(ws)

    decisions = {
        "service": service,
        "namespace": namespace,
        "branch": branch,
        "engine": engine.name,
        "model": model,
        "harnesses": harnesses,
        "group_id": group_id,
        "root": str(ws),
        "flow_mode": flow_mode,
        "phase": "1-skeleton",
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    wizard_path = _save_wizard_decisions(ws / service, decisions)
    # Persistir tambien config.yaml (formato init) para que otros comandos del
    # CLI reconozcan el workspace sin re-preguntar harnesses.
    try:
        (ws / service).mkdir(parents=True, exist_ok=True)
        _save_config(ws / service, service, harnesses)
    except Exception:
        pass  # config.yaml es best-effort; el wizard.json es la fuente del wizard

    console.print(
        Panel.fit(
            "[bold]capamedia start[/bold]\n"
            f"Servicio: [cyan]{service}[/cyan] · Namespace: {namespace} · "
            f"Rama: {branch or '[dim](pendiente integracion)[/dim]'}\n"
            f"Engine: [green]{engine.name}[/green] · Modelo: [magenta]{model}[/magenta] "
            "[dim](tier opus del engine activo)[/dim]\n"
            f"Harnesses: {', '.join(harnesses)} · Resume: {'SI' if resume else 'NO'}\n"
            f"Decisiones: [dim]{wizard_path}[/dim]",
            border_style="cyan",
        )
    )

    row = _process_pipeline_service(
        service,
        ws,
        schema_path,
        harnesses=harnesses,
        artifact_token=artifact_token,
        namespace=namespace,
        group_id=group_id,
        engine=engine,
        model=model,
        prompt_file=None,
        timeout_minutes=timeout_minutes,
        skip_tx=skip_tx,
        shallow=shallow,
        skip_check=skip_check,
        unsafe=unsafe,
        reasoning_effort=None,
        resume=resume,
        scheduler=None,
    )

    status_color = "green" if row.status == "ok" else "red"
    console.print(f"\n[bold {status_color}]pipeline {row.status}[/bold {status_color}]: {row.detail}")
    if row.status != "ok":
        raise typer.Exit(1)

    # Fase 6: doublecheck encadenado con gate BLOCKED_BY_HIGH (sin auto-push).
    if not skip_doublecheck:
        _run_doublecheck_with_gate(
            service=service,
            ws=ws,
            engine=engine,
            model=model,
            timeout_minutes=timeout_minutes,
            unsafe=unsafe,
            resume=resume,
        )


def start_command(
    service: Annotated[
        str | None,
        typer.Option("--service", "-s", help="Servicio a migrar (ej: wsclientes0076)"),
    ] = None,
    namespace: Annotated[
        str | None,
        typer.Option("--namespace", "-n", help="Acronimo de nomenclatura: tnd|tpr|csg|tmp|tia|tct"),
    ] = None,
    branch: Annotated[
        str | None,
        typer.Option(
            "--branch",
            "-b",
            help="Rama destino. Se registra; su integracion (verificar/crear/posicionar) llega en una fase posterior.",
        ),
    ] = None,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Carpeta raiz del workspace (default: CWD)"),
    ] = None,
    engine_name: Annotated[
        str,
        typer.Option("--engine", help="Engine AI headless: claude | codex | auto (default claude)"),
    ] = "claude",
    claude_bin: Annotated[str, typer.Option("--claude-bin", help="Binario de Claude Code CLI")] = "claude",
    codex_bin: Annotated[str, typer.Option("--codex-bin", help="Binario de Codex CLI")] = "codex",
    ai: Annotated[str, typer.Option("--ai", help="Harness(es) CSV para el scaffold (default claude)")] = "claude",
    group_id: Annotated[str, typer.Option("--group-id")] = "com.pichincha.sp",
    artifact_token: Annotated[
        str | None,
        typer.Option("--artifact-token", help="Override del token para renderizar .mcp.json"),
    ] = None,
    timeout_minutes: Annotated[int, typer.Option("--timeout-minutes", help="Timeout maximo de migrate")] = 90,
    shallow: Annotated[bool, typer.Option("--shallow", help="Clone superficial")] = False,
    skip_tx: Annotated[bool, typer.Option("--skip-tx", help="No clonar repos de TX")] = False,
    skip_check: Annotated[bool, typer.Option("--skip-check", help="No ejecutar checklist post-migracion")] = False,
    skip_doublecheck: Annotated[bool, typer.Option("--skip-doublecheck", help="No correr el doble check AI tras la migracion")] = False,
    unsafe: Annotated[bool, typer.Option("--unsafe", help="Permisos full para el engine")] = False,
    resume: Annotated[bool, typer.Option("--resume", help="Reanuda saltando etapas ya exitosas")] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="No-interactivo (CI/SSH): corre sin menu ni confirmaciones."),
    ] = False,
) -> None:
    """Wizard orquestador "un click" (Fase 2: bienvenida + menu; fachada no-interactiva con flags).

    Modo no-interactivo: con --service y --namespace (o --yes), corre el pipeline
    directo, forzando Opus 4.8. Modo interactivo (TTY, sin flags completos):
    bienvenida + preflight + menu. El sub-wizard de inputs llega en la Fase 3.
    """
    ws = (root or Path.cwd()).resolve()
    ws.mkdir(parents=True, exist_ok=True)

    facade_kwargs = {
        "branch": branch,
        "ws": ws,
        "engine_name": engine_name,
        "claude_bin": claude_bin,
        "codex_bin": codex_bin,
        "ai": ai,
        "group_id": group_id,
        "artifact_token": artifact_token,
        "timeout_minutes": timeout_minutes,
        "shallow": shallow,
        "skip_tx": skip_tx,
        "skip_check": skip_check,
        "skip_doublecheck": skip_doublecheck,
        "unsafe": unsafe,
    }

    is_tty = sys.stdin.isatty()
    interactive = is_tty and not yes and not (service and namespace)

    # Modo no-interactivo: flags completos, --yes, o sin TTY (CI/SSH).
    if not interactive:
        if not (service and namespace):
            raise typer.BadParameter(
                "Modo no-interactivo (--yes o sin TTY): se requieren --service y --namespace. "
                "El sub-wizard interactivo de inputs llega en una fase posterior."
            )
        _run_pipeline_facade(service=service, namespace=namespace, resume=resume, **facade_kwargs)
        return

    # ── Modo interactivo (Fase 2) ──
    _welcome_panel()
    preflight = _run_preflight(claude_bin, codex_bin)
    _render_preflight(preflight)

    resumable = _find_resumable(ws)
    if resumable:
        console.print(
            f"[dim]Servicios con sesion previa (wizard.json) en este root: "
            f"{', '.join(resumable)}[/dim]"
        )

    while True:
        choice = _root_menu()
        if choice == "0":
            console.print("[dim]Hasta luego.[/dim]")
            return
        if choice == "2":
            _show_harnesses_readonly()
            continue
        if choice == "3":
            _render_preflight(preflight)
            continue
        if choice == "4":
            _show_engine_model_readonly(preflight)
            continue
        if choice == "1":
            # Atajo: service+namespace por flag -> corre directo.
            if service and namespace:
                _run_pipeline_facade(
                    service=service, namespace=namespace, resume=resume, **facade_kwargs
                )
                return
            # Reanudar una sesion previa solo si el usuario NO especifico service
            # por flag (evita reanudar X cuando pediste migrar Y).
            if resumable and not service:
                svc = resumable[0]
                if Confirm.ask(f"Reanudar sesion previa de {svc}?", default=True):
                    prev = load_wizard_decisions(ws / svc)
                    ns = prev.get("namespace")
                    if ns:
                        console.print(f"[cyan]Reanudando[/cyan] {svc} (namespace={ns})")
                        _run_pipeline_facade(
                            service=svc, namespace=ns, resume=True, **facade_kwargs
                        )
                        return
            # Fase 3: sub-wizard de inputs (recolecta sin tocar red) + gate.
            inputs = _collect_inputs_interactive(
                service=service, namespace=namespace, branch=branch
            )
            if inputs is None:
                return
            run_kwargs = dict(facade_kwargs)
            run_kwargs["branch"] = inputs["branch"]
            run_kwargs["ai"] = ",".join(inputs["harnesses"])
            _run_pipeline_facade(
                service=inputs["service"],
                namespace=inputs["namespace"],
                resume=resume,
                **run_kwargs,
            )
            return
