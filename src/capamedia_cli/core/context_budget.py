"""Presupuesto de contexto para los harnesses AI (v0.41.0).

Problema que resuelve (WSSeguridad0069, 2026-09-03): `capamedia init` concatenaba
los 22 canonicals de `context/` dentro de UN solo `CLAUDE.md` (~200 KB, ~50k
tokens) que Claude Code carga en cada sesion Y en cada subagente. Encima,
`/migrate` cargaba `migrate-rest-full.md` entero (153 KB). El subagente
`migrador` (Opus) moria con "Prompt is too long" antes de leer un archivo del
legacy.

Solucion en dos partes, ambas transparentes para el contenido (nada se
pierde, solo cambia DONDE vive):

1. **Contexto en dos niveles.** El archivo auto-cargado (`CLAUDE.md`,
   `AGENTS.md`, `.windsurfrules`, `copilot-instructions.md`, la regla
   `alwaysApply` de Cursor) solo lleva los canonicals nucleo
   (`ALWAYS_INLINE_CONTEXT`) y los muy chicos; el resto se escribe UNO por
   archivo en `.capamedia/context/<name>.md` y el archivo auto-cargado trae un
   indice (nombre, resumen, tamano, path) con la regla "leer bajo demanda".
2. **Prompts grandes partidos.** Un prompt cuyo cuerpo supera
   `PROMPT_SPLIT_THRESHOLD_BYTES` se renderiza como indice + partes en
   `.capamedia/prompts/<name>/NN-<slug>.md`, cortadas por encabezados (`##`,
   luego `###`, luego `####`) y agrupadas hasta `PROMPT_PART_TARGET_BYTES`.
   El agente lee cada parte al llegar a ese bloque.

Los presupuestos estan calibrados para Opus (modelo objetivo del CLI, ver
`model_policy.py`), no para modelos con ventana mayor. El comportamiento
anterior sigue disponible con `capamedia init --inline-context`
(`inline_context=True` en `scaffold_project`).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from capamedia_cli.core.canonical import CanonicalAsset

# Tamano maximo deseado del archivo que el harness carga solo en cada sesion y
# subagente. ~6k tokens: deja el grueso de la ventana de Opus para legacy +
# codigo generado.
INLINE_CONTEXT_BUDGET_BYTES = 24_000

# Canonicals de contexto que SIEMPRE van inline (identidad del proyecto y reglas
# de arquitectura/estilo que aplican a cada archivo que se escribe). El resto
# se lee bajo demanda.
ALWAYS_INLINE_CONTEXT: tuple[str, ...] = ("CLAUDE", "hexagonal", "code-style", "security")

# Un canonical chico viaja inline aunque no este en la allowlist (no vale la
# pena un Read extra por 1-2 KB), salvo que el presupuesto ya este agotado.
INLINE_ASSET_MAX_BYTES = 2_000

# Prompts (slash commands) por encima de este tamano se parten en partes.
PROMPT_SPLIT_THRESHOLD_BYTES = 48_000
# Tamano objetivo de cada parte (~6k tokens).
PROMPT_PART_TARGET_BYTES = 24_000

# Carpetas compartidas por todos los harnesses (ya estan en el .gitignore del
# workspace: `.capamedia/` es artefacto local, no va a Azure DevOps).
SHARED_CONTEXT_DIR = Path(".capamedia") / "context"
SHARED_PROMPT_PARTS_DIR = Path(".capamedia") / "prompts"

_HEADING_LEVELS = ("## ", "### ", "#### ")


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _kb(n_bytes: int) -> str:
    return f"{max(1, round(n_bytes / 1024))} KB"


def slugify(text: str, max_len: int = 48) -> str:
    """`### BLOCK 4: Infrastructure Layer (infrastructure/)` -> `block-4-infrastructure-layer`."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"^#+\s*", "", ascii_text).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return (slug[:max_len].rstrip("-")) or "parte"


# --------------------------------------------------------------------------
# Contexto en dos niveles
# --------------------------------------------------------------------------


def asset_summary(asset: CanonicalAsset, max_len: int = 140) -> str:
    """Resumen de una linea para el indice: frontmatter `summary` > `description`
    > primera linea de prosa del cuerpo."""
    for key in ("summary", "description"):
        value = asset.frontmatter.get(key)
        if isinstance(value, str) and value.strip():
            text = " ".join(value.split())
            return text if len(text) <= max_len else text[: max_len - 3].rstrip() + "..."
    for line in asset.body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "-", "|", "```", "<", "*")):
            text = " ".join(stripped.split())
            return text if len(text) <= max_len else text[: max_len - 3].rstrip() + "..."
    return ""


def partition_context(
    assets: list[CanonicalAsset],
) -> tuple[list[CanonicalAsset], list[CanonicalAsset]]:
    """Separa (inline, on_demand) respetando el orden canonico.

    Inline: `ALWAYS_INLINE_CONTEXT` siempre; los demas solo si son chicos
    (`INLINE_ASSET_MAX_BYTES`) y todavia hay presupuesto.
    """
    inline: list[CanonicalAsset] = []
    on_demand: list[CanonicalAsset] = []
    used = 0
    for asset in assets:
        if asset.name in ALWAYS_INLINE_CONTEXT:
            inline.append(asset)
            used += _size(asset.body)
    for asset in assets:
        if asset.name in ALWAYS_INLINE_CONTEXT:
            continue
        body_size = _size(asset.body)
        if body_size <= INLINE_ASSET_MAX_BYTES and used + body_size <= INLINE_CONTEXT_BUDGET_BYTES:
            inline.append(asset)
            used += body_size
        else:
            on_demand.append(asset)
    # Conservar el orden canonico dentro del bloque inline.
    order = {id(a): i for i, a in enumerate(assets)}
    inline.sort(key=lambda a: order[id(a)])
    return inline, on_demand


def on_demand_context_path(asset: CanonicalAsset) -> Path:
    return SHARED_CONTEXT_DIR / f"{asset.name}.md"


def write_on_demand_context(assets: list[CanonicalAsset], target_dir: Path) -> list[Path]:
    """Escribe cada canonical bajo demanda como archivo propio (con un H1 y el
    resumen) en `<target>/.capamedia/context/`. Idempotente."""
    written: list[Path] = []
    if not assets:
        return written
    out_dir = target_dir / SHARED_CONTEXT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        dest = target_dir / on_demand_context_path(asset)
        summary = asset_summary(asset)
        header = f"# {asset.title}\n\n"
        if summary:
            header += f"> {summary}\n\n"
        dest.write_text(header + asset.body.strip() + "\n", encoding="utf-8")
        written.append(dest)
    return written


def render_context_index(
    inline: list[CanonicalAsset],
    on_demand: list[CanonicalAsset],
    *,
    heading: str = "# Contexto del proyecto",
) -> str:
    """Cuerpo del archivo auto-cargado: canonicals inline + indice bajo demanda."""
    parts = [heading + "\n"]
    for asset in inline:
        parts.append(f"\n## {asset.title}\n\n{asset.body.strip()}\n")
    if on_demand:
        parts.append(
            "\n## Contexto bajo demanda (NO cargado automaticamente)\n\n"
            "Los canonicals de esta tabla viven en `"
            + SHARED_CONTEXT_DIR.as_posix()
            + "/`. Este archivo se carga en cada sesion y en cada subagente, y el "
            "presupuesto de contexto del modelo es finito: **lee cada canonical con "
            "`Read` solo cuando la tarea lo requiera** (ej. `bank-official-rules` al "
            "tocar `build.gradle` o error handling; `log-transaccional-orq` solo en "
            "ORQ; `bank-secrets` solo al declarar secrets). Nunca los cargues todos al "
            "inicio ni los pegues en el prompt de un subagente: pasale el path.\n\n"
            "| Canonical | Cuando leerlo | Tamano | Archivo |\n|---|---|---|---|\n"
        )
        for asset in on_demand:
            summary = asset_summary(asset).replace("|", "\\|")
            parts.append(
                f"| `{asset.name}` | {summary} | {_kb(_size(asset.body))} | "
                f"`{on_demand_context_path(asset).as_posix()}` |\n"
            )
    return "".join(parts)


def render_legacy_context(assets: list[CanonicalAsset], heading: str = "# Contexto del proyecto") -> str:
    """Concatenacion completa (comportamiento previo a v0.41.0, `--inline-context`)."""
    parts = [heading + "\n"]
    for a in assets:
        parts.append(f"\n## {a.title}\n\n{a.body}")
    return "\n".join(parts)


def context_document(
    assets: list[CanonicalAsset],
    target_dir: Path,
    *,
    heading: str = "# Contexto del proyecto",
    inline_context: bool = False,
) -> tuple[str, list[Path]]:
    """(texto del archivo auto-cargado, archivos bajo demanda escritos)."""
    if inline_context:
        return render_legacy_context(assets, heading), []
    inline, on_demand = partition_context(assets)
    written = write_on_demand_context(on_demand, target_dir)
    return render_context_index(inline, on_demand, heading=heading), written


# --------------------------------------------------------------------------
# Prompts grandes -> indice + partes
# --------------------------------------------------------------------------


@dataclass
class PromptPart:
    index: int
    heading: str
    kind: str  # "inicio" | "bloque" | "cierre"
    content: str
    filename: str

    @property
    def size(self) -> int:
        return _size(self.content)


def _split_at(text: str, marker: str) -> tuple[str, list[tuple[str, str]]]:
    """Corta `text` en (preambulo, [(heading, seccion_con_heading)]) por lineas
    que empiezan con `marker`, ignorando lineas dentro de fences ```."""
    lines = text.splitlines(keepends=True)
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith(marker):
            sections.append((line.rstrip("\n"), [line]))
            continue
        if sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)
    return "".join(preamble), [(h, "".join(body)) for h, body in sections]


def _clean_heading(head: str) -> str:
    return re.sub(r"^#+\s*", "", head).strip()


def _group(pieces: list[tuple[str, str]], target: int) -> list[tuple[str, str]]:
    """Agrupa piezas consecutivas hasta `target` bytes. Un grupo con varias
    piezas se nombra `primera ... ultima` para que el indice diga que contiene."""
    grouped: list[tuple[str, str]] = []
    heads: list[str] = []
    cur_body = ""

    def flush() -> None:
        if not cur_body:
            return
        label = heads[0] if len(heads) == 1 else f"{heads[0]} ... {heads[-1]}"
        grouped.append((label, cur_body))

    for head, body in pieces:
        if cur_body and _size(cur_body) + _size(body) > target:
            flush()
            heads, cur_body = [_clean_heading(head)], body
        else:
            heads.append(_clean_heading(head))
            cur_body += body
    flush()
    return grouped


def _explode(head: str, body: str, level: int, target: int) -> list[tuple[str, str, bool]]:
    """Devuelve piezas (heading, texto, es_subseccion) de tamano <= target cuando
    se puede, bajando de nivel de encabezado (## -> ### -> ####)."""
    # level 1 = seccion `##` entera (parte "inicio"/"cierre"); level >= 2 = pieza
    # nacida de partir por `###`/`####` (parte "bloque").
    is_sub = level >= 2
    if _size(body) <= target or level >= len(_HEADING_LEVELS):
        return [(head, body, is_sub)]
    marker = _HEADING_LEVELS[level]
    pre, subs = _split_at(body, marker)
    if not subs:
        return [(head, body, is_sub)]
    pieces: list[tuple[str, str]] = []
    if pre.strip():
        pieces.append((head, pre))
    for sub_head, sub_body in subs:
        for h, b, _ in _explode(sub_head, sub_body, level + 1, target):
            pieces.append((h, b))
    return [(h, b, True) for h, b in _group(pieces, target)]


def split_prompt_body(body: str, target: int = PROMPT_PART_TARGET_BYTES) -> tuple[str, list[PromptPart]]:
    """(preambulo, partes). El preambulo es el texto antes del primer `## `."""
    preamble, sections = _split_at(body, _HEADING_LEVELS[0])
    parts: list[PromptPart] = []
    seen_block = False
    for head, sec_body in sections:
        exploded = _explode(head, sec_body, 1, target)
        multi = len(exploded) > 1
        for i, (h, text, is_sub) in enumerate(exploded, start=1):
            kind = "bloque" if is_sub else ("cierre" if seen_block else "inicio")
            if is_sub:
                seen_block = True
            heading = re.sub(r"^#+\s*", "", h).strip()
            if multi and not is_sub:
                heading = f"{heading} (p{i})"
            parts.append(PromptPart(0, heading, kind, text, ""))
    # Dedupe headings that repeat (grouped #### under the same ###) and number.
    counts: dict[str, int] = {}
    for n, part in enumerate(parts, start=1):
        part.index = n
        base = slugify(part.heading)
        counts[base] = counts.get(base, 0) + 1
        suffix = f"-p{counts[base]}" if counts[base] > 1 else ""
        part.filename = f"{n:02d}-{base}{suffix}.md"
    return preamble, parts


def prompt_parts_dir(asset_name: str) -> Path:
    return SHARED_PROMPT_PARTS_DIR / asset_name


def render_prompt_index(asset_name: str, preamble: str, parts: list[PromptPart]) -> str:
    rel_dir = prompt_parts_dir(asset_name).as_posix()
    lines = [preamble.rstrip("\n"), ""]
    lines.append(
        "> **Prompt dividido en partes por presupuesto de contexto.** Este archivo es "
        f"solo el indice; el contenido completo vive en `{rel_dir}/`. NO leas todas las "
        "partes de una vez: el modelo objetivo (Opus) agota su ventana y los subagentes "
        "mueren con `Prompt is too long`.\n>\n"
        "> Orden de lectura:\n"
        "> 1. Lee las partes `inicio` antes de empezar (rol, input, reglas, estilo).\n"
        "> 2. Lee cada parte `bloque` recien cuando llegues a ese bloque; ejecuta su GATE y "
        "pasa a la siguiente. Si delegas un bloque a un subagente, pasale el PATH de la "
        "parte, no su contenido.\n"
        "> 3. Termina con las partes `cierre` (build final, autocorreccion).\n"
    )
    lines.append("")
    lines.append("| # | Parte | Tipo | Tamano | Archivo |")
    lines.append("|---|---|---|---|---|")
    for part in parts:
        heading = part.heading.replace("|", "\\|")
        lines.append(
            f"| {part.index:02d} | {heading} | {part.kind} | {_kb(part.size)} | "
            f"`{rel_dir}/{part.filename}` |"
        )
    lines.append("")
    return "\n".join(lines)


def prompt_body_for_harness(
    asset: CanonicalAsset,
    target_dir: Path,
    *,
    inline_context: bool = False,
    threshold: int = PROMPT_SPLIT_THRESHOLD_BYTES,
) -> tuple[str, list[Path]]:
    """Cuerpo a renderizar para un prompt y los archivos de partes escritos.

    Prompts chicos (o modo `inline_context`) vuelven intactos. Los grandes se
    escriben como partes en `.capamedia/prompts/<name>/` y se devuelve el indice.
    """
    if inline_context or _size(asset.body) <= threshold:
        return asset.body, []
    preamble, parts = split_prompt_body(asset.body)
    if len(parts) < 2:
        return asset.body, []
    out_dir = target_dir / prompt_parts_dir(asset.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for part in parts:
        dest = out_dir / part.filename
        dest.write_text(
            f"<!-- {asset.name} - parte {part.index:02d}/{len(parts)} ({part.kind}) -->\n"
            + part.content.rstrip("\n")
            + "\n",
            encoding="utf-8",
        )
        written.append(dest)
    return render_prompt_index(asset.name, preamble, parts), written


# --------------------------------------------------------------------------
# Reporte
# --------------------------------------------------------------------------

# Archivos que cada harness carga solo al arrancar una sesion.
AUTOLOADED_FILES: dict[str, str] = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "opencode": "AGENTS.md",
    "cursor": ".cursor/rules/apim-context.mdc",
    "windsurf": ".windsurfrules",
    "copilot": ".github/copilot-instructions.md",
}


@dataclass
class ContextBudgetReport:
    autoloaded: dict[str, int]  # path relativo -> bytes
    on_demand_context: int
    split_prompts: int

    @property
    def over_budget(self) -> list[str]:
        return [p for p, n in self.autoloaded.items() if n > INLINE_CONTEXT_BUDGET_BYTES]

    def lines(self) -> list[str]:
        out = []
        for rel, n in self.autoloaded.items():
            flag = " (SUPERA el presupuesto)" if n > INLINE_CONTEXT_BUDGET_BYTES else ""
            out.append(f"{rel}: {_kb(n)} auto-cargado{flag}")
        out.append(
            f"{self.on_demand_context} canonical(es) bajo demanda en "
            f"{SHARED_CONTEXT_DIR.as_posix()}/, {self.split_prompts} prompt(s) partido(s) en "
            f"{SHARED_PROMPT_PARTS_DIR.as_posix()}/"
        )
        return out


def context_budget_report(target_dir: Path, harnesses: list[str]) -> ContextBudgetReport:
    autoloaded: dict[str, int] = {}
    for harness in harnesses:
        rel = AUTOLOADED_FILES.get(harness)
        if not rel:
            continue
        path = target_dir / rel
        if path.exists():
            autoloaded[rel] = path.stat().st_size
    ctx_dir = target_dir / SHARED_CONTEXT_DIR
    prompts_dir = target_dir / SHARED_PROMPT_PARTS_DIR
    return ContextBudgetReport(
        autoloaded=autoloaded,
        on_demand_context=len(list(ctx_dir.glob("*.md"))) if ctx_dir.exists() else 0,
        split_prompts=len([d for d in prompts_dir.iterdir() if d.is_dir()]) if prompts_dir.exists() else 0,
    )
