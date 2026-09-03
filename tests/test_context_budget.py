"""Presupuesto de contexto (v0.41.0): CLAUDE.md slim + prompts partidos.

Motivacion: el subagente `migrador` moria con `Prompt is too long` porque
`capamedia init` concatenaba ~200 KB de canonicals en CLAUDE.md (heredado por
cada subagente) y `/migrate` cargaba `migrate-rest-full.md` (153 KB) entero.
El modelo objetivo del CLI es Opus: los presupuestos son conservadores.
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.adapters import ALL_HARNESSES, get_adapter
from capamedia_cli.commands.init import scaffold_project
from capamedia_cli.core.canonical import load_canonical_assets
from capamedia_cli.core.context_budget import (
    ALWAYS_INLINE_CONTEXT,
    AUTOLOADED_FILES,
    INLINE_CONTEXT_BUDGET_BYTES,
    PROMPT_PART_TARGET_BYTES,
    PROMPT_SPLIT_THRESHOLD_BYTES,
    SHARED_CONTEXT_DIR,
    SHARED_PROMPT_PARTS_DIR,
    context_budget_report,
    partition_context,
    render_legacy_context,
    split_prompt_body,
)

ASSETS = load_canonical_assets()
REST_PROMPT = next(a for a in ASSETS["prompt"] if a.name == "migrate-rest-full")
SOAP_PROMPT = next(a for a in ASSETS["prompt"] if a.name == "migrate-soap-full")


def _strip_marker_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("<!-- migrate-rest-full - parte"))


# ---------------------------------------------------------------------------
# Particion del contexto
# ---------------------------------------------------------------------------


def test_partition_keeps_core_inline_and_moves_heavy_canonicals_on_demand() -> None:
    inline, on_demand = partition_context(ASSETS["context"])
    inline_names = {a.name for a in inline}
    on_demand_names = {a.name for a in on_demand}

    assert set(ALWAYS_INLINE_CONTEXT) <= inline_names
    # Los pesados (62 KB, 29 KB, 18 KB) nunca viajan inline.
    assert {"bank-official-rules", "log-transaccional-orq", "bank-secrets"} <= on_demand_names
    assert not (inline_names & on_demand_names)
    assert len(inline) + len(on_demand) == len(ASSETS["context"])
    assert sum(len(a.body.encode()) for a in inline) <= INLINE_CONTEXT_BUDGET_BYTES


def test_claude_md_is_within_budget_and_indexes_on_demand_context(tmp_path: Path) -> None:
    get_adapter("claude").render_all(ASSETS, tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    text = claude_md.read_text(encoding="utf-8")

    assert claude_md.stat().st_size <= INLINE_CONTEXT_BUDGET_BYTES
    assert "## Contexto bajo demanda" in text
    for name in ("bank-official-rules", "log-transaccional-orq", "bank-mcp-matrix"):
        assert f"`{SHARED_CONTEXT_DIR.as_posix()}/{name}.md`" in text
        on_demand_file = tmp_path / SHARED_CONTEXT_DIR / f"{name}.md"
        assert on_demand_file.exists()
    # El contenido no se pierde: el canonical pesado esta completo en su archivo.
    rules = (tmp_path / SHARED_CONTEXT_DIR / "bank-official-rules.md").read_text(encoding="utf-8")
    assert "Regla 8.5" in rules and "Regla 9e.3" in rules


def test_every_harness_autoloaded_file_is_within_budget(tmp_path: Path) -> None:
    for harness in ALL_HARNESSES:
        target = tmp_path / harness
        written, _ = get_adapter(harness).render_all(ASSETS, target)
        autoloaded = target / AUTOLOADED_FILES[harness]
        assert autoloaded.exists(), harness
        assert autoloaded.stat().st_size <= INLINE_CONTEXT_BUDGET_BYTES, harness
        # Los canonicals bajo demanda forman parte de lo escrito (auditables).
        assert any(SHARED_CONTEXT_DIR.as_posix() in p.as_posix() for p in written), harness


def test_inline_context_flag_reproduces_legacy_render(tmp_path: Path) -> None:
    get_adapter("claude").render_all(ASSETS, tmp_path, inline_context=True)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")

    assert text == render_legacy_context(ASSETS["context"])
    assert "Contexto bajo demanda" not in text
    assert not (tmp_path / SHARED_CONTEXT_DIR).exists()
    # Prompt REST entero, sin partir.
    rest = (tmp_path / ".claude" / "commands" / "migrate-rest-full.md").read_text(encoding="utf-8")
    assert "### BLOCK 4: Infrastructure Layer" in rest
    assert not (tmp_path / SHARED_PROMPT_PARTS_DIR).exists()


# ---------------------------------------------------------------------------
# Prompts partidos
# ---------------------------------------------------------------------------


def test_split_prompt_roundtrip_and_part_sizes() -> None:
    preamble, parts = split_prompt_body(REST_PROMPT.body)

    assert len(parts) >= 10
    assert preamble + "".join(p.content for p in parts) == REST_PROMPT.body
    # Cada parte cabe en el presupuesto salvo una seccion indivisible sin sub-encabezados.
    oversized = [p for p in parts if p.size > PROMPT_PART_TARGET_BYTES * 1.05]
    assert not oversized, [(p.heading, p.size) for p in oversized]
    kinds = [p.kind for p in parts]
    assert kinds[0] == "inicio"
    assert "bloque" in kinds
    assert kinds[-1] == "cierre"
    # Las reglas y el estilo van antes de los bloques de ejecucion.
    first_block = kinds.index("bloque")
    assert all(k == "inicio" for k in kinds[:first_block])
    assert all(k == "cierre" for k in kinds[kinds.index("cierre") :])
    assert len({p.filename for p in parts}) == len(parts)


def test_small_prompts_are_not_split(tmp_path: Path) -> None:
    assert len(SOAP_PROMPT.body.encode()) <= PROMPT_SPLIT_THRESHOLD_BYTES
    get_adapter("claude").render_all(ASSETS, tmp_path)
    soap = (tmp_path / ".claude" / "commands" / "migrate-soap-full.md").read_text(encoding="utf-8")
    assert "## Build And Dependencies" in soap
    assert not (tmp_path / SHARED_PROMPT_PARTS_DIR / "migrate-soap-full").exists()


def test_rest_prompt_renders_as_index_plus_parts(tmp_path: Path) -> None:
    written, _ = get_adapter("claude").render_all(ASSETS, tmp_path)
    index = (tmp_path / ".claude" / "commands" / "migrate-rest-full.md").read_text(encoding="utf-8")
    parts_dir = tmp_path / SHARED_PROMPT_PARTS_DIR / "migrate-rest-full"
    part_files = sorted(parts_dir.glob("*.md"))

    assert len(index.encode()) < 10_000
    assert "Prompt dividido en partes" in index
    assert "| # | Parte | Tipo | Tamano | Archivo |" in index
    assert part_files and all(p in written for p in part_files)
    for part in part_files:
        assert f"`{SHARED_PROMPT_PARTS_DIR.as_posix()}/migrate-rest-full/{part.name}`" in index
    # Nada se pierde: la union de las partes contiene el cuerpo completo.
    joined = _strip_marker_lines("\n".join(p.read_text(encoding="utf-8") for p in part_files))
    for anchor in ("### BLOCK 1: Project Scaffolding", "#### 4.11b TraceLoggerManagementPathConfig", "## SELF-CORRECTION LOOP"):
        assert anchor in joined, anchor


def test_parts_are_shared_across_harnesses(tmp_path: Path) -> None:
    for harness in ("claude", "codex", "cursor"):
        get_adapter(harness).render_all(ASSETS, tmp_path)
    parts_dir = tmp_path / SHARED_PROMPT_PARTS_DIR / "migrate-rest-full"
    assert len(list(parts_dir.glob("*.md"))) >= 10
    # Cursor referencia las mismas partes desde su regla.
    rule = (tmp_path / ".cursor" / "rules" / "migrate-rest-full.mdc").read_text(encoding="utf-8")
    assert SHARED_PROMPT_PARTS_DIR.as_posix() in rule


# ---------------------------------------------------------------------------
# init / reporte
# ---------------------------------------------------------------------------


def test_scaffold_project_default_is_slim_and_reports_budget(tmp_path: Path) -> None:
    scaffold_project(tmp_path, "wsseguridad0069", ["claude", "codex"])
    report = context_budget_report(tmp_path, ["claude", "codex"])

    assert set(report.autoloaded) == {"CLAUDE.md", "AGENTS.md"}
    assert not report.over_budget
    assert report.on_demand_context >= 10
    assert report.split_prompts == 1
    assert any("bajo demanda" in line for line in report.lines())
    # El header por servicio de init sigue al principio de CLAUDE.md.
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8").startswith(
        "# wsseguridad0069 - Migracion CapaMedia OLA1"
    )


def test_scaffold_project_inline_context_is_over_budget_and_flagged(tmp_path: Path) -> None:
    scaffold_project(tmp_path, "wsseguridad0069", ["claude"], inline_context=True)
    report = context_budget_report(tmp_path, ["claude"])

    assert report.over_budget == ["CLAUDE.md"]
    assert report.on_demand_context == 0 and report.split_prompts == 0
    assert any("SUPERA" in line for line in report.lines())


def test_router_and_migrador_teach_on_demand_reading() -> None:
    router = REST_PROMPT.source.parent.joinpath("migrate.md").read_text(encoding="utf-8")
    migrador = REST_PROMPT.source.parents[1].joinpath("agents", "migrador.md").read_text(encoding="utf-8")
    for text in (router, migrador):
        assert ".capamedia/context/" in text
        assert ".capamedia/prompts/" in text
    assert "Prompt is too long" in router
