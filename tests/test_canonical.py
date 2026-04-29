"""Tests for the canonical asset loader."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.canonical import CANONICAL_ROOT, load_canonical_assets
from capamedia_cli.core.frontmatter import parse_frontmatter, serialize_frontmatter


def test_load_canonical_assets_returns_all_types() -> None:
    assets = load_canonical_assets()
    assert "prompt" in assets
    assert "agent" in assets
    assert "skill" in assets
    assert "context" in assets


def test_slash_commands_are_loaded() -> None:
    """The 4 main slash commands must be present."""
    assets = load_canonical_assets()
    names = {a.name for a in assets["prompt"]}
    assert "clone" in names
    assert "fabric" in names
    assert "migrate" in names
    assert "check" in names


def test_doublecheck_slash_command_exists(tmp_path: Path) -> None:
    """v0.23.0: /doublecheck (alias de capamedia checklist) debe estar
    disponible como slash command en Claude Code.
    """
    assets = load_canonical_assets()
    names = {a.name for a in assets["prompt"]}
    assert "doublecheck" in names, (
        "/doublecheck debe existir como prompt canonical para que se genere "
        ".claude/commands/doublecheck.md al correr `capamedia init`"
    )

    # El prompt debe tener los campos mínimos para ser un slash command valido
    dc = next(a for a in assets["prompt"] if a.name == "doublecheck")
    assert dc.description, "doublecheck debe tener description"
    assert dc.frontmatter.get("type") == "prompt"


def test_edge_cases_slash_command_exists() -> None:
    """`/edge-cases` debe existir como prompt canonical para Claude Code."""
    assets = load_canonical_assets()
    names = {a.name for a in assets["prompt"]}
    assert "edge-cases" in names, (
        "/edge-cases debe existir como prompt canonical para que se genere "
        ".claude/commands/edge-cases.md al correr `capamedia init`"
    )

    edge_cases = next(a for a in assets["prompt"] if a.name == "edge-cases")
    assert edge_cases.description
    assert edge_cases.frontmatter.get("type") == "prompt"
    assert ".capamedia/discovery" in edge_cases.body
    assert "capamedia checklist ./destino/<namespace>-msa-sp-<servicio>" in edge_cases.body


def test_init_scaffolds_doublecheck_in_claude_commands(tmp_path: Path, monkeypatch) -> None:
    """v0.23.0: `capamedia init --ai claude` escribe
    `.claude/commands/doublecheck.md` al workspace para que `/doublecheck`
    este disponible en Claude Code.
    """
    from capamedia_cli.commands.init import scaffold_project

    monkeypatch.chdir(tmp_path)
    scaffold_project(
        target_dir=tmp_path,
        service_name="wsfooXXXX",
        harnesses=["claude"],
    )
    dc_file = tmp_path / ".claude" / "commands" / "doublecheck.md"
    assert dc_file.exists(), (
        "Despues de init, .claude/commands/doublecheck.md debe existir para "
        "que /doublecheck sea un slash command visible en Claude Code"
    )
    content = dc_file.read_text(encoding="utf-8")
    assert "doublecheck" in content.lower() or "doble check" in content.lower()


def test_init_scaffolds_edge_cases_in_claude_commands(tmp_path: Path, monkeypatch) -> None:
    """`capamedia init --ai claude` escribe `.claude/commands/edge-cases.md`."""
    from capamedia_cli.commands.init import scaffold_project

    monkeypatch.chdir(tmp_path)
    scaffold_project(
        target_dir=tmp_path,
        service_name="wsfooXXXX",
        harnesses=["claude"],
    )

    edge_file = tmp_path / ".claude" / "commands" / "edge-cases.md"
    assert edge_file.exists(), (
        "Despues de init, .claude/commands/edge-cases.md debe existir para "
        "que /edge-cases sea un slash command visible en Claude Code"
    )
    content = edge_file.read_text(encoding="utf-8")
    assert "DISCOVERY_EDGE_CASES" in content
    assert ".capamedia/discovery" in content
    assert "Block 22" in content


def test_full_prompts_are_loaded() -> None:
    """The 5 detailed prompts ported from PromptCapaMedia must be present."""
    assets = load_canonical_assets()
    names = {a.name for a in assets["prompt"]}
    assert "analisis-servicio" in names
    assert "analisis-orq" in names
    assert "migrate-rest-full" in names
    assert "migrate-soap-full" in names
    assert "checklist-rules" in names


def test_agents_are_loaded() -> None:
    assets = load_canonical_assets()
    names = {a.name for a in assets["agent"]}
    assert "analista-legacy" in names
    assert "migrador" in names
    assert "qa-generator" in names
    assert "validador-hex" in names


def test_skills_are_loaded() -> None:
    assets = load_canonical_assets()
    names = {a.name for a in assets["skill"]}
    assert "pre-migracion" in names
    assert "migrar" in names
    assert "post-migracion" in names


def test_context_are_loaded() -> None:
    assets = load_canonical_assets()
    names = {a.name for a in assets["context"]}
    assert "hexagonal" in names
    assert "bancs" in names
    assert "security" in names
    assert "code-style" in names
    assert "sonarlint" in names
    assert "peer-review" in names


def test_bank_shared_properties_context_loaded() -> None:
    """v0.18.0: catalogo de properties compartidas del banco debe estar cargado."""
    assets = load_canonical_assets()
    names = {a.name for a in assets["context"]}
    assert "bank-shared-properties" in names, (
        "bank-shared-properties.md debe existir para que el agente migrador "
        "conozca los valores literales de generalservices.properties y "
        "catalogoaplicaciones.properties"
    )


def test_bank_shared_properties_has_key_values() -> None:
    """El catalogo debe contener las claves criticas que el agente necesita."""
    path = CANONICAL_ROOT / "context" / "bank-shared-properties.md"
    content = path.read_text(encoding="utf-8")

    # generalservices.properties - claves criticas
    assert "OMNI_COD_SERVICIO_OK=0" in content
    assert "OMNI_MSJ_SERVICIO_OK=OK" in content
    assert "OMNI_COD_FATAL=9999" in content
    assert "OMNI_COD_NO_EXISTE_DATOS=1" in content

    # catalogoaplicaciones.properties - codigos de backend criticos
    assert "MIDDLEWARE_INTEGRACION_TECNICO_WAS=00633" in content
    assert "MIDDLEWARE_INTEGRACION=00638" in content
    assert "BANCS=00045" in content
    assert "BASE_DE_DATOS_OMNICANAL=00634" in content


def test_bank_official_rules_references_shared_properties() -> None:
    """bank-official-rules.md debe incluir la Regla 10 con la referencia."""
    path = CANONICAL_ROOT / "context" / "bank-official-rules.md"
    content = path.read_text(encoding="utf-8")
    assert "Regla 10" in content
    assert "bank-shared-properties" in content


def test_frontmatter_roundtrip() -> None:
    fm = {"name": "test", "description": "hello", "allowed_tools": ["Read", "Write"]}
    body = "# Title\n\nBody content.\n"
    serialized = serialize_frontmatter(fm, body)
    parsed_fm, parsed_body = parse_frontmatter(serialized)
    assert parsed_fm["name"] == "test"
    assert parsed_fm["description"] == "hello"
    assert parsed_fm["allowed_tools"] == ["Read", "Write"]
    assert parsed_body == body


def test_frontmatter_missing_returns_empty_dict() -> None:
    content = "# Just a title\n\nNo frontmatter here.\n"
    fm, body = parse_frontmatter(content)
    assert fm == {}
    assert body == content


def test_canonical_migration_assets_align_ports_with_interfaces() -> None:
    targets = [
        CANONICAL_ROOT / "prompts" / "migrate.md",
        CANONICAL_ROOT / "context" / "hexagonal.md",
        CANONICAL_ROOT / "context" / "code-style.md",
        CANONICAL_ROOT / "agents" / "migrador.md",
        CANONICAL_ROOT / "skills" / "migrar" / "SKILL.md",
    ]

    forbidden = [
        "Puertos son abstract classes, nunca interfaces.",
        "Ports son ABSTRACT CLASSES, nunca interfaces",
        "Crear abstract class ports + service impl",
    ]

    for path in targets:
        content = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in content, f"{Path(path).name} still contains outdated rule: {phrase}"
