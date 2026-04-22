"""capamedia status - verifica que todo lo necesario este listo para el flujo.

A diferencia de `check-install` (que chequea toolchain + detalle exhaustivo),
`status` responde una sola pregunta: **"estoy listo para migrar?"**. Da una
tabla corta con cada requisito + su estado, y un veredicto global.

IMPORTANTE: NO chequea `OPENAI_API_KEY`. No usamos tokens API pagos; solo
suscripciones (Claude Max o ChatGPT Plus/Pro). El engine headless consume
de la suscripcion del usuario, no de un billing API.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from capamedia_cli.core.engine import available_engines

console = Console()


@dataclass
class StatusCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _check_binary(name: str, version_args: list[str] | None = None) -> StatusCheck:
    """Verifica que un binario este en PATH."""
    if shutil.which(name) is None:
        return StatusCheck(
            name=name, ok=False, detail="no encontrado en PATH"
        )
    detail = "encontrado en PATH"
    if version_args:
        try:
            out = subprocess.run(
                [name, *version_args],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if out.returncode == 0 and out.stdout.strip():
                first_line = out.stdout.strip().splitlines()[0]
                detail = first_line[:60]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return StatusCheck(name=name, ok=True, detail=detail)


def _check_engines() -> StatusCheck:
    """Al menos un engine (Claude o Codex) autenticado - suscripcion, no API."""
    engines = available_engines()
    claude_ok, claude_reason = engines.get("claude", (False, "no check"))
    codex_ok, codex_reason = engines.get("codex", (False, "no check"))

    parts: list[str] = []
    parts.append(f"claude={'OK' if claude_ok else 'no'} ({claude_reason[:30]})")
    parts.append(f"codex={'OK' if codex_ok else 'no'} ({codex_reason[:30]})")

    ok = claude_ok or codex_ok
    return StatusCheck(
        name="AI engine (suscripcion)",
        ok=ok,
        detail=" | ".join(parts),
    )


def _check_azure_pat() -> StatusCheck:
    """PAT de Azure DevOps disponible (env o Git Credential Manager)."""
    for var in ("CAPAMEDIA_AZDO_PAT", "AZURE_DEVOPS_EXT_PAT"):
        if os.environ.get(var, "").strip():
            return StatusCheck(
                name="Azure DevOps PAT",
                ok=True,
                detail=f"env {var} configurada",
            )
    # Fallback: chequear si git puede listar remotes auth-protected via GCM
    # Skipeamos el network check — solo reportamos que no hay env var
    return StatusCheck(
        name="Azure DevOps PAT",
        ok=False,
        detail="sin env var (CAPAMEDIA_AZDO_PAT / AZURE_DEVOPS_EXT_PAT)",
    )


def _check_artifacts_token() -> StatusCheck:
    """Token de Azure Artifacts (para npm @pichincha/ y Gradle plugin del banco)."""
    for var in ("CAPAMEDIA_ARTIFACT_TOKEN", "ARTIFACT_TOKEN"):
        if os.environ.get(var, "").strip():
            return StatusCheck(
                name="Azure Artifacts token",
                ok=True,
                detail=f"env {var} configurada",
            )
    return StatusCheck(
        name="Azure Artifacts token",
        ok=False,
        detail="sin env var (CAPAMEDIA_ARTIFACT_TOKEN / ARTIFACT_TOKEN)",
    )


def _check_fabrics_mcp() -> StatusCheck:
    """El MCP Fabrics esta registrado en algun .mcp.json."""
    from pathlib import Path

    candidates = [
        Path.cwd() / ".mcp.json",
        Path.home() / ".mcp.json",
    ]
    for c in candidates:
        if not c.exists():
            continue
        try:
            import json as _json

            data = _json.loads(c.read_text(encoding="utf-8"))
        except Exception:
            continue
        servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
        if "fabrics" in servers:
            return StatusCheck(
                name="MCP Fabrics",
                ok=True,
                detail=f"registrado en {c}",
            )
    return StatusCheck(
        name="MCP Fabrics",
        ok=False,
        detail="sin server 'fabrics' en .mcp.json (correr `capamedia fabrics setup`)",
    )


def _check_java21() -> StatusCheck:
    """Java 21 disponible en JAVA_HOME o PATH."""
    # Preferencia: JAVA_HOME apuntando a 21
    java_home = os.environ.get("JAVA_HOME", "")
    if java_home:
        try:
            from pathlib import Path

            release = Path(java_home) / "release"
            if release.exists():
                content = release.read_text(encoding="utf-8", errors="ignore")
                if 'JAVA_VERSION="21' in content:
                    return StatusCheck(
                        name="Java 21",
                        ok=True,
                        detail=f"JAVA_HOME={java_home}",
                    )
        except OSError:
            pass

    # Fallback: java --version
    java_bin = shutil.which("java")
    if java_bin:
        try:
            out = subprocess.run(
                [java_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            combined = (out.stdout or "") + (out.stderr or "")
            if "21" in combined.splitlines()[0] if combined else "":
                return StatusCheck(
                    name="Java 21",
                    ok=True,
                    detail=combined.splitlines()[0][:60],
                )
            return StatusCheck(
                name="Java 21",
                ok=False,
                detail=f"java en PATH pero no es 21: {combined.splitlines()[0][:60] if combined else '?'}",
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return StatusCheck(
        name="Java 21",
        ok=False,
        detail="java no encontrado (correr `capamedia install`)",
    )


def status_command() -> None:
    """Verifica que todo lo necesario este listo para migrar.

    NO chequea OpenAI API key. Usamos suscripciones (Claude Max / ChatGPT),
    no tokens API pagos.
    """
    console.print(
        Panel.fit(
            "[bold]capamedia status[/bold] — listo para migrar?",
            border_style="cyan",
        )
    )

    checks: list[StatusCheck] = [
        # Toolchain basico
        _check_binary("git", ["--version"]),
        _check_java21(),
        _check_binary("gradle", ["--version"]),
        _check_binary("node", ["--version"]),
        # AI engine — al menos uno
        _check_engines(),
        # Credenciales (env vars, no API keys)
        _check_azure_pat(),
        _check_artifacts_token(),
        # MCP Fabrics registrado
        _check_fabrics_mcp(),
    ]

    table = Table(title="Status checks", title_style="bold cyan")
    table.add_column("Componente")
    table.add_column("Estado", justify="center")
    table.add_column("Detalle")

    for c in checks:
        status_str = (
            "[green]OK[/green]" if c.ok else "[red]FAIL[/red]"
        )
        table.add_row(c.name, status_str, c.detail)

    console.print(table)

    all_required_ok = all(c.ok for c in checks if c.required)
    failed_required = [c for c in checks if c.required and not c.ok]

    if all_required_ok:
        console.print(
            "\n[bold green]Listo para migrar[/bold green]. Podes correr "
            "`capamedia clone <servicio>`."
        )
    else:
        console.print(
            f"\n[bold red]Faltan {len(failed_required)} componente(s) "
            f"obligatorios.[/bold red] Arreglar en orden:"
        )
        for c in failed_required:
            console.print(f"  - [red]{c.name}[/red]: {c.detail}")
        console.print(
            "\n[dim]Pasos sugeridos:[/dim]\n"
            "  [dim]1. `capamedia install`                  # toolchain[/dim]\n"
            "  [dim]2. `claude login` o `codex login`       # suscripcion[/dim]\n"
            "  [dim]3. `capamedia auth bootstrap --artifact-token T --azure-pat T --scope global`[/dim]\n"
            "  [dim]4. `capamedia fabrics setup --refresh-npmrc`[/dim]"
        )
        raise typer.Exit(code=1)
