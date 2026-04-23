"""Tests para los 4 gaps nuevos sincronizados del PromptCapaMedia (v0.23.6)."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.canonical import CANONICAL_ROOT, load_canonical_assets


# ---------------------------------------------------------------------------
# Gap 1: QA prompts (commit 368a5c9)
# ---------------------------------------------------------------------------


def test_qa_review_prompt_is_loaded() -> None:
    """v0.23.6: /qa-review slash command disponible via canonical prompt."""
    assets = load_canonical_assets()
    names = {a.name for a in assets["prompt"]}
    assert "qa-review" in names, "/qa-review debe estar como prompt canonical"


def test_qa_review_prompt_mentions_acceptance_criteria() -> None:
    path = CANONICAL_ROOT / "prompts" / "qa-review.md"
    content = path.read_text(encoding="utf-8")
    # Todos los 14 criterios deben estar mencionados
    for ac in ("AC-01", "AC-02", "AC-03", "AC-04", "AC-05",
               "AC-06", "AC-07", "AC-08", "AC-09", "AC-10",
               "AC-11", "AC-12", "AC-13", "AC-14"):
        assert ac in content, f"qa-review debe mencionar {ac}"
    # Archivo de evidencia path
    assert "/docs/acceptance-criteria/" in content


def test_unit_test_guidelines_context_loaded() -> None:
    """v0.23.6: unit-test-guidelines como context canonical."""
    assets = load_canonical_assets()
    names = {a.name for a in assets["context"]}
    assert "unit-test-guidelines" in names


def test_unit_test_guidelines_has_key_rules() -> None:
    path = CANONICAL_ROOT / "context" / "unit-test-guidelines.md"
    content = path.read_text(encoding="utf-8")
    # Patron given_when_then obligatorio
    assert "given[Context]_when[Action]_then[ExpectedResult]" in content
    # Coverage threshold 85%
    assert "85%" in content
    # NO @DisplayName
    assert "@DisplayName" in content
    # Duplication 0%
    assert "0%" in content
    # Idioma ingles obligatorio
    assert "ingles" in content.lower() or "english" in content.lower()


# ---------------------------------------------------------------------------
# Gap 2: Bank error codes catalog (commit 3dbf23f)
# ---------------------------------------------------------------------------


def test_bank_error_codes_context_loaded() -> None:
    assets = load_canonical_assets()
    names = {a.name for a in assets["context"]}
    assert "bank-error-codes" in names


def test_bank_error_codes_includes_all_key_codes() -> None:
    """El catalogo debe listar los 5 codes criticos del errores.xml."""
    path = CANONICAL_ROOT / "context" / "bank-error-codes.md"
    content = path.read_text(encoding="utf-8")
    # Los 5 codes documentados por jgarcia
    assert "9999" in content
    assert "9929" in content
    assert "9922" in content
    assert "9927" in content
    assert "9991" in content
    # Regla explicita "NEVER inventar 999"
    assert "999" in content
    assert "NEVER" in content or "NUNCA" in content


def test_bank_error_codes_has_exception_mapping_table() -> None:
    """El catalogo tiene tabla que mapea exception types a error codes."""
    path = CANONICAL_ROOT / "context" / "bank-error-codes.md"
    content = path.read_text(encoding="utf-8")
    assert "BancsClientException" in content
    assert "HeaderValidator" in content or "HeaderRequestValidator" in content
    assert "BusinessValidationException" in content


# ---------------------------------------------------------------------------
# Gap 3: Service Purity fortalecida (commit 56d2771)
# ---------------------------------------------------------------------------


def test_bank_official_rules_has_stricter_service_purity() -> None:
    """Regla 6 fortalecida: CERO metodos privados, todo a application/util/."""
    path = CANONICAL_ROOT / "context" / "bank-official-rules.md"
    content = path.read_text(encoding="utf-8")
    # Service Purity mencionada en regla 6
    assert "Service Purity" in content
    # Helpers van a application/util/
    assert "application/util/" in content
    # Ejemplos de helpers específicos
    assert "ValidationHelper" in content or "NormalizationHelper" in content


# ---------------------------------------------------------------------------
# Gap 4: Preserve MCP scaffold + Regla 9g all-vars-in-yml
# ---------------------------------------------------------------------------


def test_bank_official_rules_has_preserve_scaffold_rule() -> None:
    """Regla 9f: preservar application.yml del scaffold MCP (merge, no replace)."""
    path = CANONICAL_ROOT / "context" / "bank-official-rules.md"
    content = path.read_text(encoding="utf-8")
    assert "Regla 9f" in content or "Preservar" in content
    # Mencion explicita de spring.main.lazy-initialization
    assert "lazy-initialization" in content
    # Mencion de NO replace, merge
    assert "merge" in content.lower() or "preservar" in content.lower()


def test_bank_official_rules_has_rule_9g_all_legacy_vars() -> None:
    """Regla 9g: toda variable legacy en application.yml."""
    path = CANONICAL_ROOT / "context" / "bank-official-rules.md"
    content = path.read_text(encoding="utf-8")
    assert "Regla 9g" in content or "configurables legacy" in content.lower()
    # Fuentes de configuracion listadas
    assert "GestionarRecursoConfigurable" in content
    assert "CatalogoAplicaciones" in content


# ---------------------------------------------------------------------------
# Integracion scaffold
# ---------------------------------------------------------------------------


def test_bank_official_rules_has_helm_pdb_rule() -> None:
    """v0.23.7: Regla 9h - helm dev SOAP requiere pdb: minAvailable: 1."""
    path = CANONICAL_ROOT / "context" / "bank-official-rules.md"
    content = path.read_text(encoding="utf-8")
    assert "Regla 9h" in content or "pdb" in content.lower()
    assert "minAvailable: 1" in content
    # Menciona que es para SOAP
    assert "SOAP" in content


def test_bank_official_rules_prohibits_inline_defaults_v0_23_9() -> None:
    """v0.23.9: Regla 9g actualizada - NEVER inline defaults `${CCC_VAR:value}`."""
    path = CANONICAL_ROOT / "context" / "bank-official-rules.md"
    content = path.read_text(encoding="utf-8")
    # La prohibicion explicita debe estar
    assert "NEVER inline defaults" in content or "inline defaults" in content.lower()
    # Debe explicar el motivo (helm como unica fuente)
    assert "exclusivamente desde Helm" in content or "Helm" in content


def test_bank_official_rules_mandatory_spring_header_v0_23_9() -> None:
    """v0.23.9: spring.header.channel/medium deben ser mandatorios always."""
    path = CANONICAL_ROOT / "context" / "bank-official-rules.md"
    content = path.read_text(encoding="utf-8")
    # Check explicitos que son MANDATORIO
    assert "channel: digital" in content
    assert "medium: web" in content
    # Como literal, no env var
    # (el texto debe enfatizar "literal, nunca env var")
    assert "MANDATORIO" in content or "MUST" in content


def test_bank_official_rules_has_configurables_csv_reference() -> None:
    """v0.23.7: Regla 11 - referencia al CSV ConfigurablesBusOmniTest."""
    path = CANONICAL_ROOT / "context" / "bank-official-rules.md"
    content = path.read_text(encoding="utf-8")
    assert "ConfigurablesBusOmniTest" in content
    assert "GestionarRecursoConfigurable" in content
    # Debe aclarar por que no esta embebido
    assert "grande" in content.lower() or "no esta embebido" in content.lower()


def test_init_scaffolds_qa_review_as_slash_command(tmp_path: Path, monkeypatch) -> None:
    """init con --ai claude debe generar .claude/commands/qa-review.md."""
    from capamedia_cli.commands.init import scaffold_project

    monkeypatch.chdir(tmp_path)
    scaffold_project(
        target_dir=tmp_path,
        service_name="wsfooXXXX",
        harnesses=["claude"],
    )

    qa_review = tmp_path / ".claude" / "commands" / "qa-review.md"
    assert qa_review.exists(), "qa-review.md debe existir en .claude/commands/"

    # Debe contener el header del prompt
    content = qa_review.read_text(encoding="utf-8")
    assert "Acceptance Criteria" in content or "acceptance-criteria" in content
