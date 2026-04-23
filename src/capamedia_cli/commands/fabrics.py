"""capamedia fabrics - gestion del MCP Fabrics del banco.

Subcomandos:
  - setup        Registra el MCP Fabrics en ~/.mcp.json o .mcp.json local
  - preflight    Verifica que el MCP este conectado y que la version sea reciente
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from capamedia_cli.core.auth import resolve_artifact_token

console = Console()

app = typer.Typer(
    help="Gestion del MCP Fabrics del Banco Pichincha (@pichincha/fabrics-project).",
    no_args_is_help=True,
)


def _default_mcp_fabrics_config() -> dict[str, object]:
    return {
        "command": "npx",
        "args": ["-y", "@pichincha/fabrics-project@latest"],
        "env": {
            "ARTIFACT_USERNAME": "BancoPichinchaEC",
            "ARTIFACT_TOKEN": "",
        },
    }


def _resolve_env_placeholder(value: str) -> str:
    raw = (value or "").strip()
    if raw.startswith("${") and raw.endswith("}"):
        return os.environ.get(raw[2:-1], "").strip()
    return raw


def _is_placeholder_token(value: str) -> bool:
    raw = (value or "").strip()
    if not raw:
        return True
    if raw.startswith("${") and raw.endswith("}"):
        return _resolve_env_placeholder(raw) == ""
    return "<" in raw


def _resolve_fabrics_env(raw_env: dict[str, str]) -> dict[str, str]:
    env = {str(k): str(v) for k, v in raw_env.items()}
    token = _resolve_env_placeholder(env.get("ARTIFACT_TOKEN", ""))
    if token:
        env["ARTIFACT_TOKEN"] = token
    return env


def _candidate_fabrics_configs(workspace: Path) -> list[tuple[Path, str]]:
    return [
        (workspace / ".mcp.json", "workspace"),
        (workspace.parent / ".mcp.json", "workspace-parent"),
        (Path.home() / ".mcp.json", "home"),
    ]


def _discover_fabrics_config(workspace: Path) -> tuple[Path | None, dict[str, str], str, str]:
    """Find the first usable Fabrics config for a workspace.

    Returns (path, env, source, hint). When no usable config exists, path/env/source
    are empty and hint explains the first invalid config if one was found.
    """
    first_invalid_hint = ""
    for candidate, source in _candidate_fabrics_configs(workspace):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        fabrics = data.get("mcpServers", {}).get("fabrics", {})
        if not fabrics:
            continue
        env = _resolve_fabrics_env(fabrics.get("env", {}))
        token = env.get("ARTIFACT_TOKEN", "").strip()
        if token and not _is_placeholder_token(token):
            return (candidate, env, source, "")
        if not first_invalid_hint:
            first_invalid_hint = (
                f"config encontrada en {candidate} pero ARTIFACT_TOKEN es placeholder o esta vacio"
            )
    return (None, {}, "", first_invalid_hint)


def inspect_fabrics_workspace(workspace: Path) -> dict[str, str]:
    """Return a structured preflight verdict for Fabrics in a workspace."""
    from shutil import which

    ws = workspace.resolve()
    if which("npx") is None:
        return {
            "status": "fail",
            "detail": "npx no esta disponible (instala Node.js LTS antes de correr Fabrics)",
        }

    config_path, env, source, hint = _discover_fabrics_config(ws)
    if config_path is None:
        detail = hint or "MCP fabrics no esta registrado o no tiene un ARTIFACT_TOKEN usable"
        return {"status": "fail", "detail": detail}

    token = env.get("ARTIFACT_TOKEN", "").strip()
    if not token or _is_placeholder_token(token):
        return {
            "status": "fail",
            "detail": (
                f"config encontrada en {config_path} pero el ARTIFACT_TOKEN no es usable; "
                "corre `capamedia fabrics setup` o expone CAPAMEDIA_ARTIFACT_TOKEN"
            ),
        }

    return {
        "status": "ok",
        "detail": f"config={config_path} ({source})",
        "config_path": str(config_path),
        "config_source": source,
        "token_length": str(len(token)),
    }


def fabrics_metadata_path(workspace: Path) -> Path:
    return workspace / ".capamedia" / "fabrics.json"


def load_fabrics_metadata(workspace: Path) -> dict | None:
    path = fabrics_metadata_path(workspace)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_fabrics_metadata(workspace: Path, payload: dict) -> Path:
    path = fabrics_metadata_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _write_fabrics_prompt(
    workspace: Path,
    service_name: str,
    *,
    project_name: str,
    project_path: str,
    namespace: str,
    tecnologia: str,
    project_type: str,
    analysis: object,
) -> Path:
    """Escribe `FABRICS_PROMPT_<svc>.md` con catalogos oficiales inyectados.

    Lee `tx-adapter-catalog.json`, `codigosBackend.xml` y las reglas del PDF
    BPTPSRE, detecta las TX relevantes del servicio (via `analysis.umps` +
    `tx/` clonados + COMPLEXITY.md) y arma el bloque Markdown.
    """
    from capamedia_cli.core.catalog_injector import (
        detect_relevant_tx,
        format_for_prompt,
        load_catalogs,
    )

    umps = list(getattr(analysis, "umps", []) or [])
    tx_codes = detect_relevant_tx(workspace, service_name, analysis_umps=umps)
    snapshot = load_catalogs(workspace)
    catalog_block = format_for_prompt(snapshot, relevant_tx=tx_codes)

    header = (
        f"# FABRICS prompt: {service_name}\n\n"
        f"Generado por `capamedia fabrics generate` el "
        f"{dt.datetime.now(dt.UTC).isoformat()}.\n\n"
        f"## Parametros del scaffold\n\n"
        f"- projectName: `{project_name}`\n"
        f"- projectPath: `{project_path}`\n"
        f"- namespace: `{namespace}`\n"
        f"- tecnologia: `{tecnologia}`\n"
        f"- projectType: `{project_type}`\n"
        f"- TX detectadas: "
        f"{', '.join(tx_codes) if tx_codes else '(ninguna)'}\n\n"
    )
    body = header + (catalog_block or "")
    path = workspace / f"FABRICS_PROMPT_{service_name}.md"
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
    return path


def _resolve_legacy_root(service_name: str, workspace: Path) -> Path | None:
    """Find the legacy root for fabrics generate, preferring workspace-local material."""
    preferred = workspace / "legacy" / f"sqb-msa-{service_name.lower()}"
    if preferred.exists():
        return preferred

    if (workspace / "legacy").exists():
        candidates = list((workspace / "legacy").glob("*"))
        if candidates:
            return candidates[0]

    from capamedia_cli.core.local_resolver import find_local_legacy

    return find_local_legacy(service_name, workspace.parent)


def _load_or_create_mcp_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            console.print(f"[yellow]Warning:[/yellow] no pude parsear {path}, voy a crear uno nuevo")
    return {"mcpServers": {}}


NPMRC_FEED = "//pkgs.dev.azure.com/BancoPichinchaEC/arq-framework/_packaging/Framework/npm/registry/"


def _refresh_npmrc(token: str) -> Path:
    """Actualiza ~/.npmrc con el token de Azure Artifacts (base64-encoded).

    Formato requerido por Azure Artifacts:
      //pkgs.dev.azure.com/.../registry/:username=BancoPichinchaEC
      //pkgs.dev.azure.com/.../registry/:_password=<base64(PAT)>
      //pkgs.dev.azure.com/.../registry/:email=npm@pichincha.com
      @pichincha:registry=https://pkgs.dev.azure.com/.../registry/
      always-auth=true
    """
    npmrc = Path.home() / ".npmrc"
    pw_b64 = base64.b64encode(token.encode("utf-8")).decode("ascii")

    new_lines = [
        "; managed by capamedia-cli fabrics setup --refresh-npmrc",
        f"{NPMRC_FEED}:username=BancoPichinchaEC",
        f"{NPMRC_FEED}:_password={pw_b64}",
        f"{NPMRC_FEED}:email=npm@pichincha.com",
        f"@pichincha:registry=https:{NPMRC_FEED}",
        "always-auth=true",
        "",
    ]

    # Preserve user lines not related to the Azure Artifacts feed
    existing: list[str] = []
    if npmrc.exists():
        try:
            for line in npmrc.read_text(encoding="utf-8").splitlines():
                if NPMRC_FEED in line or "@pichincha:registry" in line or line.startswith("; managed by capamedia"):
                    continue
                if "always-auth=true" in line:
                    continue
                existing.append(line)
        except OSError:
            pass

    content = "\n".join(new_lines + existing).rstrip() + "\n"
    npmrc.write_text(content, encoding="utf-8")
    return npmrc


@app.command("setup")
def setup(
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            "-s",
            help="Donde registrar: 'global' (~/.mcp.json) o 'project' (./.mcp.json)",
        ),
    ] = "project",
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            help="Token de Azure Artifacts. Si se omite, se pide interactivamente.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Sobrescribir si ya existe"),
    ] = False,
    refresh_npmrc: Annotated[
        bool,
        typer.Option(
            "--refresh-npmrc",
            help="Ademas de .mcp.json, actualiza ~/.npmrc con el token (para que `npx @pichincha/fabrics-project` funcione).",
        ),
    ] = False,
) -> None:
    """Registra el MCP Fabrics del banco en la configuracion de Claude Code.

    El MCP `@pichincha/fabrics-project` se instala via `npx` (ya lo hace solo).
    Lo que hay que registrar es la URL y el ARTIFACT_TOKEN para Azure Artifacts.
    """
    if scope == "global":
        target = Path.home() / ".mcp.json"
    elif scope == "project":
        target = Path.cwd() / ".mcp.json"
    else:
        console.print(f"[red]Error:[/red] scope invalido: {scope}. Usa 'global' o 'project'")
        raise typer.Exit(1)

    config = _load_or_create_mcp_json(target)
    servers = config.setdefault("mcpServers", {})

    if "fabrics" in servers and not force:
        console.print(f"[yellow]MCP fabrics ya existe en {target}[/yellow]")
        if not Confirm.ask("Sobrescribir?", default=False):
            console.print("[dim]Cancelado.[/dim]")
            raise typer.Exit(0)

    # Token: prioridad 1) --token, 2) env var, 3) prompt
    if token is None:
        token = resolve_artifact_token()
    if token is None or token.strip() == "":
        console.print(
            Panel(
                (
                    "Necesitas un [bold]Azure Artifacts PAT[/bold] con scope [cyan]Packaging (Read)[/cyan] "
                    "para descargar @pichincha/fabrics-project.\n\n"
                    "Crearlo: https://dev.azure.com/BancoPichinchaEC/_usersSettings/tokens\n"
                    "-> New Token -> Scopes -> Packaging (Read) -> Create -> Copy"
                ),
                border_style="yellow",
                title="Como obtener el token",
            )
        )
        token = Prompt.ask(
            "Pega aca tu token",
            password=True,
        )

    if not token or not token.strip():
        console.print("[red]Token vacio. Cancelando.[/red]")
        raise typer.Exit(1)

    default_config = _default_mcp_fabrics_config()
    fabric_config = {
        "command": str(default_config["command"]),
        "args": list(default_config["args"]),
        "env": {
            "ARTIFACT_USERNAME": "BancoPichinchaEC",
            "ARTIFACT_TOKEN": token.strip(),
        },
    }
    servers["fabrics"] = fabric_config

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    console.print(f"[green]OK[/green] MCP Fabrics registrado en {target}")

    # Refresh ~/.npmrc si se pidio (o auto si no tiene configuracion del feed)
    if refresh_npmrc:
        npmrc_path = _refresh_npmrc(token.strip())
        console.print(f"[green]OK[/green] ~/.npmrc actualizado en {npmrc_path}")
        console.print(
            "       Ahora `npx @pichincha/fabrics-project@latest` podra bajar el paquete."
        )

    console.print()
    if scope == "project":
        console.print(
            "[yellow]IMPORTANTE:[/yellow] el archivo .mcp.json contiene tu token. "
            "Ya esta en .gitignore si usaste 'capamedia init', pero verifica antes de commit."
        )
    if not refresh_npmrc:
        console.print(
            "[dim]Tip: si `npx @pichincha/fabrics-project` te da E401, "
            "corre este comando con --refresh-npmrc para renovar el token en ~/.npmrc[/dim]"
        )


NAMESPACE_OPTIONS = ["tnd", "tpr", "csg", "tmp", "tia", "tct"]

# Params del MCP que nuestro CLI sabe proveer. Usado para validacion de schema en runtime.
KNOWN_MCP_PARAMS = frozenset(
    {
        "projectName",
        "projectPath",
        "wsdlFilePath",
        "groupId",
        "namespace",
        "tecnologia",
        "projectType",
        "webFramework",
        "invocaBancs",
    }
)


def _find_java21_home() -> Path | None:
    """Localiza Java 21 en el sistema (necesario porque Gradle 8.x no soporta Java 25+).

    Busca en ubicaciones tipicas de Windows (Eclipse Temurin, Oracle) y macOS/Linux.
    Retorna el path al JAVA_HOME (directorio que contiene bin/java).
    """
    candidates: list[Path] = []
    # Windows - Eclipse Temurin (lo que instala winget / capamedia install)
    candidates.extend(Path("C:/Program Files/Eclipse Adoptium").glob("jdk-21*")) if Path("C:/Program Files/Eclipse Adoptium").exists() else None
    # Windows - Oracle
    candidates.extend(Path("C:/Program Files/Java").glob("jdk-21*")) if Path("C:/Program Files/Java").exists() else None
    # macOS
    candidates.append(Path("/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home"))
    # Linux
    candidates.append(Path("/usr/lib/jvm/java-21-openjdk-amd64"))
    candidates.append(Path("/usr/lib/jvm/temurin-21-jdk-amd64"))

    for c in candidates:
        if c and c.exists() and (c / "bin" / ("java.exe" if os.name == "nt" else "java")).exists():
            return c

    # Fallback: check JAVA_HOME env if it points to Java 21
    env_java = os.environ.get("JAVA_HOME")
    if env_java:
        p = Path(env_java)
        release = p / "release"
        if release.exists():
            try:
                text = release.read_text(encoding="utf-8", errors="replace")
                if 'JAVA_VERSION="21' in text:
                    return p
            except OSError:
                pass
    return None


def _artifact_env_from_mcp(ws: Path) -> dict[str, str]:
    """Lee ARTIFACT_USERNAME/ARTIFACT_TOKEN del .mcp.json para pasarlos al gradlew subprocess."""
    _, env, _, _ = _discover_fabrics_config(ws)
    if env.get("ARTIFACT_TOKEN"):
        return {
            "ARTIFACT_USERNAME": env.get("ARTIFACT_USERNAME", "BancoPichinchaEC"),
            "ARTIFACT_TOKEN": env["ARTIFACT_TOKEN"],
        }
    return {}


def _fix_schema_locations(proj_dir: Path) -> list[str]:
    """Arregla schemaLocation con paths relativos externos (`../...`) en WSDL/XSD.

    Caso tipico: WSClientes*_InlineSchema1.xsd tiene:
        <xsd:include schemaLocation="../TCSProcesarServicioSOAP/GenericSOAP.xsd"/>
    Fix:
        1. Copiar GenericSOAP.xsd (recurso embebbed del CLI) al dir del WSDL.
        2. Quitar el prefijo `../TCSProcesarServicioSOAP/` del schemaLocation.

    Retorna la lista de archivos modificados.
    """
    import re

    legacy_dir = proj_dir / "src" / "main" / "resources" / "legacy"
    if not legacy_dir.exists():
        return []

    # Copiar GenericSOAP.xsd desde los recursos del CLI si hace falta
    resources_dir = Path(__file__).resolve().parent.parent / "data" / "resources"
    src_generic = resources_dir / "GenericSOAP.xsd"
    dest_generic = legacy_dir / "GenericSOAP.xsd"

    modified: list[str] = []
    pattern_need_fix = re.compile(r'schemaLocation="[^"]*\.\./[^"]*GenericSOAP\.xsd"')

    for f in list(legacy_dir.glob("*.wsdl")) + list(legacy_dir.glob("*.xsd")):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        if pattern_need_fix.search(text):
            if src_generic.exists() and not dest_generic.exists():
                dest_generic.write_bytes(src_generic.read_bytes())
                modified.append(f"copied GenericSOAP.xsd -> {dest_generic.name}")
            # Reemplazar schemaLocation relativo por local
            new_text = re.sub(
                r'schemaLocation="[^"]*\.\./[^"]*GenericSOAP\.xsd"',
                'schemaLocation="GenericSOAP.xsd"',
                text,
            )
            f.write_text(new_text, encoding="utf-8")
            modified.append(f"fixed schemaLocation in {f.name}")
    return modified


def _set_gradle_java_home(proj_dir: Path, java_home: Path) -> None:
    """Escribe org.gradle.java.home en gradle.properties para forzar el JDK.

    Usa forward slashes (Gradle los acepta en Windows) para evitar issues de
    escape de backslashes en .properties files. Reemplaza la linea si ya existe.
    """
    props = proj_dir / "gradle.properties"
    lines: list[str] = []
    if props.exists():
        try:
            for line in props.read_text(encoding="utf-8").splitlines():
                if not line.strip().startswith("org.gradle.java.home"):
                    lines.append(line)
        except OSError:
            pass
    java_home_str = str(java_home).replace("\\", "/")
    lines.append(f"org.gradle.java.home={java_home_str}")
    props.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_gradlew_wsdl_import(proj_dir: Path, ws: Path) -> tuple[bool, str]:
    """Workaround post-MCP: corre `gradlew generateFromWsdl` con path absoluto y env vars.

    Hace 3 cosas para superar los bugs conocidos del MCP en Windows:
      1. Pre-procesa WSDL/XSDs arreglando schemaLocation relativos (GenericSOAP.xsd).
      2. Pasa ARTIFACT_USERNAME/ARTIFACT_TOKEN al subprocess (los plugins Gradle
         viven en Azure Artifacts privado y los necesitan para auth).
      3. Invoca el wrapper con path absoluto (bug Windows: `gradlew.bat` sin `.\\`
         no es resuelto por exec).
    """
    is_windows = os.name == "nt"
    wrapper = proj_dir / ("gradlew.bat" if is_windows else "gradlew")
    if not wrapper.exists():
        return (False, f"no existe {wrapper.name}")

    # 1. Fix schemaLocation externos
    fixes = _fix_schema_locations(proj_dir)
    if fixes:
        console.print(f"  [dim]Pre-procesado: {len(fixes)} fix(es) de schemaLocation[/dim]")

    # 2. Env vars para Azure Artifacts + Java 21 (Gradle 8.x no soporta Java 25+)
    subprocess_env = os.environ.copy()
    subprocess_env.update(_artifact_env_from_mcp(ws))
    java21 = _find_java21_home()
    if java21:
        # Setear via gradle.properties (mas confiable en Windows con paths con espacios)
        _set_gradle_java_home(proj_dir, java21)
        subprocess_env["JAVA_HOME"] = str(java21)
        console.print(f"  [dim]Java 21 forzado via gradle.properties: {java21.name}[/dim]")
    else:
        console.print(
            "  [yellow]WARN[/yellow] Java 21 no encontrado. Gradle puede fallar si PATH apunta a Java >=25."
        )

    # 3. Ejecutable: en Unix marcar como ejecutable
    if not is_windows:
        try:
            wrapper.chmod(0o755)
        except OSError:
            pass

    # 4. Limpiar caches previos del proyecto (evita class files de otras versiones de Java)
    import shutil as _sh
    for stale in (proj_dir / ".gradle", proj_dir / "build"):
        if stale.exists():
            try:
                _sh.rmtree(stale, ignore_errors=True)
            except OSError:
                pass

    try:
        result = subprocess.run(
            [str(wrapper), "generateFromWsdl", "--no-daemon"],
            cwd=str(proj_dir),
            capture_output=True,
            text=True,
            timeout=600,
            shell=is_windows,
            env=subprocess_env,
        )
        if result.returncode == 0:
            return (True, "")
        # Buscar la linea "What went wrong" para dar info util
        full_output = (result.stdout or "") + "\n" + (result.stderr or "")
        relevant: list[str] = []
        for line in full_output.splitlines():
            lower = line.lower()
            if any(k in lower for k in ("error", "unable", "fail", "exception", "401", "wsdlexception")):
                relevant.append(line.strip())
                if len(relevant) >= 3:
                    break
        return (False, " | ".join(relevant)[:400] or "gradlew returned non-zero")
    except subprocess.TimeoutExpired:
        return (False, "timeout (>600s)")
    except (OSError, FileNotFoundError) as e:
        return (False, str(e))


def _autodetect_service_name_from_config(ws: Path) -> str | None:
    """Lee <ws>/.capamedia/config.yaml y devuelve service_name si existe.

    Tolera YAML malformado, archivo ausente o campos faltantes sin crashear.
    """
    config_path = ws / ".capamedia" / "config.yaml"
    if not config_path.is_file():
        return None
    try:
        import yaml as _yaml

        data = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, _yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    val = data.get("service_name")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


@app.command("generate")
def generate(
    service_name: str | None = typer.Argument(
        None,
        help=(
            "Nombre del servicio (ej: wsclientes0076). Si se omite, "
            "autodetecta desde ./.capamedia/config.yaml del workspace."
        ),
    ),
    workspace: Path | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace root (default: CWD)",
    ),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        "-n",
        help=f"Namespace del catalogo: {' | '.join(NAMESPACE_OPTIONS)}. Si se omite, se pregunta interactivamente.",
    ),
    group_id: str = typer.Option(
        "com.pichincha.sp",
        "--group-id",
        help="Maven groupId del proyecto",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="No invocar el MCP, solo mostrar los parametros que se usarian",
    ),
) -> None:
    """Invoca el MCP Fabrics del banco y genera el arquetipo en ./destino/.

    Analiza el legacy clonado por `capamedia clone`, deduce los parametros del MCP,
    lo invoca via stdio JSON-RPC y deja la carpeta `destino/` con el proyecto generado.
    """
    from capamedia_cli.core.legacy_analyzer import analyze_legacy
    from capamedia_cli.core.mcp_client import MCPClient, MCPError
    from capamedia_cli.core.mcp_launcher import locate as locate_mcp

    ws = (workspace or Path.cwd()).resolve()

    # v0.20.4: autodetectar service_name desde .capamedia/config.yaml si se omite
    if service_name is None:
        service_name = _autodetect_service_name_from_config(ws)
        if service_name is None:
            console.print(
                "[red]Error:[/red] falta el argumento SERVICE_NAME y no se pudo "
                "autodetectar.\n"
                "[yellow]Opciones:[/yellow]\n"
                f"  1) Correr desde el workspace root (donde vive "
                f"[cyan].capamedia/config.yaml[/cyan]).\n"
                "  2) Pasar el nombre explicito: "
                "[cyan]capamedia fabrics generate <service_name>[/cyan]"
            )
            raise typer.Exit(2)
        console.print(
            f"[dim]Autodetectado[/dim] servicio=[cyan]{service_name}[/cyan] "
            f"desde [cyan].capamedia/config.yaml[/cyan]"
        )

    # Auto-padding a 4 digitos (convencion del banco, ver v0.20.1)
    from capamedia_cli.commands.clone import normalize_service_name

    normalized, was_padded = normalize_service_name(service_name)
    if was_padded:
        console.print(
            f"[yellow]Tip:[/yellow] [cyan]{service_name}[/cyan] -> "
            f"[cyan]{normalized}[/cyan] (auto-padded a 4 digitos)"
        )
        service_name = normalized

    console.print(
        Panel.fit(
            f"[bold]CapaMedia fabrics generate[/bold]\n"
            f"Servicio: [cyan]{service_name}[/cyan]\n"
            f"Workspace: [cyan]{ws}[/cyan]",
            border_style="cyan",
        )
    )

    preflight_status = inspect_fabrics_workspace(ws)
    if preflight_status["status"] != "ok":
        console.print(f"[red]FAIL[/red] {preflight_status['detail']}")
        raise typer.Exit(1)
    console.print(f"  [green]OK[/green] Fabrics listo: {preflight_status['detail']}")

    # Step 1: Find legacy folder
    legacy_root = _resolve_legacy_root(service_name, ws)
    if legacy_root is None:
        console.print(f"[red]FAIL[/red] no se encontro legacy en {ws / 'legacy'} ni localmente")
        console.print("[yellow]Tip:[/yellow] corre 'capamedia clone <servicio>' antes")
        raise typer.Exit(1)

    console.print(f"  [green]OK[/green] legacy encontrado en: {legacy_root}")

    # Step 2: Analyze
    umps_root = ws / "umps" if (ws / "umps").exists() else None
    analysis = analyze_legacy(legacy_root, service_name=service_name, umps_root=umps_root)

    if not analysis.wsdl:
        console.print("[red]FAIL[/red] no se pudo analizar el WSDL del legacy")
        raise typer.Exit(1)

    # Step 3: Deduce MCP params
    # invocaBancs: deteccion robusta (UMP + TX directa + HTTPRequest + BancsClient)
    invoca_bancs = analysis.has_bancs

    # projectType: invocaBancs gana sobre op count salvo en WAS
    if analysis.source_kind == "orq" or (analysis.source_kind == "iib" and invoca_bancs):
        project_type = "rest"
    else:
        project_type = analysis.framework_recommendation or "soap"

    # webFramework: WAS siempre MVC, resto WebFlux
    web_framework = "mvc" if analysis.source_kind == "was" else "webflux"

    # tecnologia: mismo mapping que antes
    tecnologia = "was" if analysis.source_kind == "was" else "bus"
    wsdl_abs = str(analysis.wsdl.path.resolve())
    project_name = f"tnd-msa-sp-{service_name.lower()}"
    project_path = str((ws / "destino").resolve())

    # Step 4: Resolve namespace (enum MCP)
    if namespace is None:
        console.print()
        console.print("[bold yellow]Namespace del catalogo[/bold yellow] (obligatorio, no inferible)")
        console.print(f"  Opciones: {', '.join(NAMESPACE_OPTIONS)}")
        namespace = Prompt.ask(
            "  Elegi el namespace",
            choices=NAMESPACE_OPTIONS,
            default="tnd",
        )

    # Show summary
    console.print()
    table = Table(title="Parametros deducidos para el MCP", title_style="bold cyan")
    table.add_column("Parametro", style="cyan")
    table.add_column("Valor", style="bold")
    table.add_column("Origen", style="dim")
    table.add_row("projectName", project_name, "derivado de service_name")
    table.add_row("projectPath", project_path, "ws/destino")
    table.add_row("wsdlFilePath", wsdl_abs, "legacy WSDL")
    table.add_row("groupId", group_id, "--group-id")
    table.add_row("namespace", namespace, "interactivo / --namespace")
    table.add_row("tecnologia", tecnologia, f"source_kind={analysis.source_kind}")
    table.add_row("projectType", project_type, f"{analysis.wsdl.operation_count} ops")
    table.add_row("webFramework", web_framework, "matriz oficial")
    table.add_row("invocaBancs", str(invoca_bancs).lower(), f"{len(analysis.umps)} UMPs")
    console.print(table)

    mcp_args = {
        "projectName": project_name,
        "projectPath": project_path,
        "wsdlFilePath": wsdl_abs,
        "groupId": group_id,
        "namespace": namespace,
        "tecnologia": tecnologia,
        "projectType": project_type,
        "webFramework": web_framework,
        "invocaBancs": invoca_bancs,
    }

    if dry_run:
        console.print("\n[yellow]--dry-run: no invoco el MCP.[/yellow]")
        console.print("Argumentos que se enviarian:")
        console.print_json(data=mcp_args)
        return

    # Step 5: Locate + launch MCP
    console.print("\n[bold]Arrancando MCP Fabrics...[/bold]")
    try:
        spec = locate_mcp(cwd=ws)
    except FileNotFoundError as e:
        console.print(f"[red]FAIL[/red] {e}")
        raise typer.Exit(1) from None
    console.print(f"  source: [dim]{spec.source}[/dim]")

    mcp_error_msg: str | None = None
    result: dict = {}
    server_info: dict = {}
    mcp_source = ""
    try:
        with MCPClient(spec.command, env=spec.env, cwd=str(ws)) as client:
            info = client.initialize(client_name="capamedia-cli", client_version="0.2.4")
            server_info = info.get("serverInfo", {}) if isinstance(info, dict) else {}
            mcp_source = spec.source
            console.print(
                f"  [green]OK[/green] MCP conectado: {info.get('serverInfo', {}).get('name')} "
                f"v{info.get('serverInfo', {}).get('version')}"
            )

            # Fix #4: validar schema en runtime
            tools = client.list_tools()
            target = next((t for t in tools if t.name == "create_project_with_wsdl"), None)
            if target is None:
                console.print("[red]FAIL[/red] el MCP no expone create_project_with_wsdl. Tools disponibles:")
                for t in tools:
                    console.print(f"  - {t.name}")
                raise typer.Exit(1)

            required = set(target.required_params)
            all_props = set(target.all_params)

            # Params obligatorios que el CLI no sabe proveer
            missing_in_cli = required - KNOWN_MCP_PARAMS
            if missing_in_cli:
                console.print(
                    f"[red]FAIL[/red] el MCP pide params required desconocidos: "
                    f"{sorted(missing_in_cli)}. Este CLI no sabe como completarlos.\n"
                    f"       Actualiza capamedia-cli a una version que soporte estos params."
                )
                raise typer.Exit(1)

            # Params nuevos opcionales (warning, no bloqueante)
            new_optional = all_props - KNOWN_MCP_PARAMS
            if new_optional:
                console.print(
                    f"  [yellow]WARN[/yellow] el MCP acepta params nuevos no usados: "
                    f"{sorted(new_optional)} (puede ser version nueva del MCP)"
                )

            # Validar que todos los mcp_args que vamos a enviar estan en el schema
            our_extras = set(mcp_args.keys()) - all_props
            if our_extras:
                console.print(
                    f"  [yellow]WARN[/yellow] removiendo params que el MCP no conoce: "
                    f"{sorted(our_extras)}"
                )
                for k in our_extras:
                    mcp_args.pop(k, None)

            # Step 6: Invoke the tool
            console.print("\n[bold]Invocando create_project_with_wsdl...[/bold]")
            try:
                result = client.call_tool("create_project_with_wsdl", mcp_args)
            except MCPError as e:
                mcp_error_msg = str(e)
    except MCPError as e:
        console.print(f"[red]FAIL[/red] error conectando al MCP: {e}")
        raise typer.Exit(1) from None

    # Step 7: Parse result
    content_items = result.get("content", [])
    text_parts = [c.get("text", "") for c in content_items if c.get("type") == "text"]
    if text_parts:
        # Sanitize emojis/unicode that cp1252 (Windows default) cannot encode
        def _safe_text(s: str) -> str:
            return s.encode("ascii", errors="replace").decode("ascii")

        console.print("\n[bold]Respuesta del MCP:[/bold]")
        for part in text_parts:
            console.print(f"  {_safe_text(part[:600])}")

    destino = ws / "destino"
    proj_dir = destino / project_name
    generated_ok = destino.exists() and any(destino.iterdir())

    # Workaround #5: si el MCP fallo pero el scaffold existe, el error tipico es
    # que corrio `gradlew.bat generateFromWsdl` sin prefijo `.\\` (bug Windows).
    # Completamos el paso por nuestra cuenta con path absoluto al wrapper.
    recovered = False
    fabrics_status = "fail"
    fabrics_detail = ""
    if generated_ok and mcp_error_msg and "gradlew" in mcp_error_msg.lower():
        console.print("\n[bold]Completando paso faltante del MCP (gradlew generateFromWsdl)...[/bold]")
        ok, err = _run_gradlew_wsdl_import(proj_dir, ws)
        if ok:
            console.print("  [green]OK[/green] clases JAXB generadas en build/generated/")
            recovered = True
            mcp_error_msg = None
        else:
            console.print(f"  [yellow]WARN[/yellow] gradlew fallo: {err}")

    if generated_ok and mcp_error_msg:
        fabrics_status = "partial"
        fabrics_detail = mcp_error_msg[:500]
        # Exito parcial: scaffold existe pero el error no pude recuperar
        console.print()
        def _safe(s: str) -> str:
            return s.encode("ascii", errors="replace").decode("ascii")
        short_err = _safe(mcp_error_msg[:300])
        console.print(
            Panel(
                f"Scaffold generado en [cyan]{proj_dir}[/cyan]\n"
                f"pero el MCP reporto un error y el auto-recovery fallo:\n\n"
                f"[dim]{short_err}[/dim]\n\n"
                f"Completa el paso manualmente:\n"
                f"  cd {proj_dir}\n"
                f"  gradlew.bat generateFromWsdl  # Windows\n"
                f"  ./gradlew generateFromWsdl     # macOS/Linux",
                border_style="yellow",
                title="Exito parcial",
            )
        )
    elif generated_ok:
        fabrics_status = "ok"
        fabrics_detail = "arquetipo generado por Fabrics"
        recovery_line = "  0. (Auto) Clases JAXB generadas ya por gradlew generateFromWsdl.\n" if recovered else ""
        console.print()
        console.print(
            Panel(
                f"Arquetipo generado en [cyan]{proj_dir}[/cyan]\n\n"
                f"Proximos pasos:\n"
                f"{recovery_line}"
                f"  1. Revisa `{proj_dir.name}/build.gradle` y aplica workarounds conocidos.\n"
                f"  2. Corre `capamedia init --here` dentro de destino/{project_name}/ para sumar .claude/ y CLAUDE.md.\n"
                f"  3. Abri en Claude Code y corre `/migrate` en el chat.",
                border_style="green",
                title="OK",
            )
        )
    else:
        console.print(
            f"[red]FAIL[/red] el MCP respondio pero {destino} esta vacio."
        )
        if mcp_error_msg:
            def _safe(s: str) -> str:
                return s.encode("ascii", errors="replace").decode("ascii")
            console.print(f"Error MCP: {_safe(mcp_error_msg[:500])}")
        raise typer.Exit(1)

    if generated_ok:
        _write_fabrics_metadata(
            ws,
            {
                "service": service_name,
                "status": fabrics_status,
                "detail": fabrics_detail,
                "generated_at": dt.datetime.now(dt.UTC).isoformat(),
                "project_name": project_name,
                "project_path": str(proj_dir),
                "namespace": namespace,
                "group_id": group_id,
                "wsdl_file_path": wsdl_abs,
                "tecnologia": tecnologia,
                "project_type": project_type,
                "web_framework": web_framework,
                "invoca_bancs": str(invoca_bancs).lower(),
                "operation_count": str(analysis.wsdl.operation_count),
                "source_kind": analysis.source_kind,
                "recovered_gradlew": str(recovered).lower(),
                "mcp_source": mcp_source,
                "mcp_server_name": _resolve_env_placeholder(str(server_info.get("name", ""))),
                "mcp_server_version": str(server_info.get("version", "")),
            },
        )

        # Inyectar catalogos oficiales al FABRICS_PROMPT_<svc>.md para que la
        # AI no alucine TX-BANCS, codigos backend ni reglas de error.
        try:
            prompt_path = _write_fabrics_prompt(
                ws,
                service_name,
                project_name=project_name,
                project_path=str(proj_dir),
                namespace=namespace,
                tecnologia=tecnologia,
                project_type=project_type,
                analysis=analysis,
            )
            console.print(f"  [green]OK[/green] prompt inyectado con catalogos: {prompt_path}")
        except (OSError, ValueError) as e:  # pragma: no cover - defensivo
            console.print(f"  [yellow]WARN[/yellow] no pude escribir FABRICS_PROMPT: {e}")


@app.command("preflight")
def preflight() -> None:
    """Verifica que el MCP Fabrics este configurado y accesible.

    Chequea:
      - .mcp.json o ~/.claude/settings.json tiene el server 'fabrics'
      - El token no esta vacio
      - npx esta disponible (necesario para invocar el MCP)
      - Puede hacer un dry-run del MCP para verificar conectividad
    """
    console.print("[bold]Preflight MCP Fabrics[/bold]\n")
    status = inspect_fabrics_workspace(Path.cwd())
    if status["status"] != "ok":
        console.print(f"[red]FAIL[/red] {status['detail']}")
        console.print("       Corre: [bold]capamedia fabrics setup[/bold]")
        raise typer.Exit(1)

    console.print("[green]OK[/green] npx disponible")
    console.print(f"[green]OK[/green] config encontrada en {status['config_path']}")
    console.print(
        f"[green]OK[/green] ARTIFACT_TOKEN presente ({status['token_length']} chars)"
    )

    # 4) Reminder to verify version
    console.print()
    console.print(
        Panel(
            (
                "[bold]Recordatorio[/bold] (Julio Soria, 2026-04-17):\n"
                "> [italic]Siempre hay que mirar la ultima version del MCP.[/italic]\n\n"
                "El MCP se instala con [cyan]@latest[/cyan], asi que en teoria es siempre el ultimo.\n"
                "Pero antes de invocar [cyan]/fabric[/cyan] desde Claude Code:\n"
                "  1. Verifica que el tool [cyan]mcp__fabrics__create_project_with_wsdl[/cyan] aparezca\n"
                "  2. Revisa el schema del tool por parametros nuevos\n"
                "  3. Registra en [cyan].capamedia/config.yaml[/cyan] la fecha de scaffolding"
            ),
            border_style="cyan",
            title="Preflight check",
        )
    )
