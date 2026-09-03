"""CSV operativo de configurables (v0.42.0).

Motivacion: en la migracion de WSSeguridad0069 el agente concluyo que
`UMPSeguridad0087Config` no estaba en el CSV cuando tenia 12 filas (incluidas la
`url` y el `ns` de Cyxtera DetectID). Causa: el archivo es ISO-8859-1 con
delimitador `;`, y `grep` en locale UTF-8 sale con codigo 1 y sin salida,
indistinguible de "no encontrado"; el `|| echo "NO ENCONTRADO"` del agente
enmascaro el fallo y un `head -40` corto la lista.

Estos tests usan un CSV sintetico con las mismas trampas del real (encoding,
delimitador, triple-quote de Excel, filas de relleno, acento corrupto).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from capamedia_cli.cli import app
from capamedia_cli.commands.configurables import (
    EXIT_CSV_UNAVAILABLE,
    EXIT_FOUND,
    EXIT_NOT_IN_CSV,
)
from capamedia_cli.core.canonical import CANONICAL_ROOT
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

runner = CliRunner()

# Replica del formato real: header, padding, triple-quote, filas de relleno
# `;;;;`, y una descripcion con el byte 0xE2 (donde el banco quiso poner `o`
# con tilde). Se escribe en latin-1 a proposito.
CSV_TEXT = (
    "Configurable;Variable;Valor;;;;\n"
    'KriptoServiceConfig ; LLAVE0303000100663 ;"""XXXXXX""";;;;\n'
    'UMPSeguridad0087Config ; url ;"""https://detectidtest.uio.bpichincha.com/detect"""\n'
    'UMPSeguridad0087Config ; ns ;"""http://soap.easysol.net/detect/detectService"""\n'
    'UMPSeguridad0087Config ; enableTRA ;"""true"""\n'
    ";;;;;;\n"
    'ORQClientes0040Config ; asunto ;"""Notificaci\xe2n de Banco Pichincha"""\n'
)


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    path = tmp_path / "ConfigurablesBusOmniTest_Transfor(ConfigurablesBusOmniTest_Transf).csv"
    path.write_bytes(CSV_TEXT.encode(CSV_ENCODING))
    return path


# ---------------------------------------------------------------------------
# El encoding es el nucleo del bug
# ---------------------------------------------------------------------------


def test_csv_is_not_utf8_so_naive_reads_fail(csv_file: Path) -> None:
    """Prueba que la eleccion de latin-1 no es cosmetica: UTF-8 explota."""
    with pytest.raises(UnicodeDecodeError):
        csv_file.read_bytes().decode("utf-8")
    # latin-1 nunca falla, por eso es el encoding correcto para el lookup.
    assert csv_file.read_bytes().decode(CSV_ENCODING)


def test_load_rows_parses_delimiter_padding_and_triple_quotes(csv_file: Path) -> None:
    rows = load_rows(csv_file)

    # Header y filas de relleno `;;;;` quedan fuera.
    assert len(rows) == 5
    kripto = next(r for r in rows if r.configurable == "KriptoServiceConfig")
    assert kripto.variable == "LLAVE0303000100663"
    assert kripto.valor == "XXXXXX"  # sin el triple-quote de Excel
    assert kripto.key == "KriptoServiceConfig.LLAVE0303000100663"


def test_search_columns_are_ascii_even_when_values_are_not(csv_file: Path) -> None:
    """Lo que hace confiable el lookup: los nombres nunca traen bytes altos."""
    rows = load_rows(csv_file)
    assert all(r.configurable.isascii() and r.variable.isascii() for r in rows)
    assert [r.key for r in rows_with_encoding_artifacts(rows)] == [
        "ORQClientes0040Config.asunto"
    ]


def test_load_rows_raises_when_file_has_no_data(tmp_path: Path) -> None:
    empty = tmp_path / "ConfigurablesBusOmni-empty.csv"
    empty.write_text("Configurable;Variable;Valor\n;;;\n", encoding=CSV_ENCODING)
    with pytest.raises(ConfigurablesCsvError):
        load_rows(empty)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def test_lookup_finds_the_key_that_the_grep_missed(csv_file: Path) -> None:
    rows = load_rows(csv_file)
    hits = lookup(rows, "UMPSeguridad0087Config")

    assert len(hits) == 3
    values = {r.variable: r.valor for r in hits}
    assert values["ns"] == "http://soap.easysol.net/detect/detectService"
    assert values["url"].startswith("https://detectidtest.uio.bpichincha.com")


def test_lookup_substring_exact_and_variable_filter(csv_file: Path) -> None:
    rows = load_rows(csv_file)

    assert len(lookup(rows, "seguridad0087")) == 3  # case-insensitive substring
    assert len(lookup(rows, "seguridad0087", exact=True)) == 0
    assert len(lookup(rows, "UMPSeguridad0087Config", exact=True)) == 3
    assert len(lookup(rows, "UMPSeguridad0087Config", variable="url")) == 1
    assert lookup(rows, "CMRCTEATR") == []  # el ejemplo viejo del canonical


def test_distinct_configurables_and_yaml_block(csv_file: Path) -> None:
    rows = load_rows(csv_file)
    assert distinct_configurables(rows) == [
        "KriptoServiceConfig",
        "ORQClientes0040Config",
        "UMPSeguridad0087Config",
    ]

    block = as_yaml_block(lookup(rows, "UMPSeguridad0087Config"))
    assert block.splitlines()[0] == "UMPSeguridad0087Config:"
    assert '  ns: "http://soap.easysol.net/detect/detectService"' in block


def test_find_csv_by_file_dir_or_missing(csv_file: Path, tmp_path: Path) -> None:
    assert find_configurables_csv(explicit=csv_file) == csv_file
    assert find_configurables_csv(explicit=csv_file.parent) == csv_file
    assert find_configurables_csv(explicit=tmp_path / "nope.csv") is None


# ---------------------------------------------------------------------------
# Contrato de exit codes del comando
# ---------------------------------------------------------------------------


def test_command_exit_0_when_found(csv_file: Path) -> None:
    result = runner.invoke(app, ["configurables", "UMPSeguridad0087Config", "--csv", str(csv_file)])
    assert result.exit_code == EXIT_FOUND
    # La tabla Rich trunca los valores largos a 80 columnas, asi que verificamos
    # nombre y variables; los valores exactos se afirman via --json mas abajo.
    assert "UMPSeguridad0087Config" in result.stdout
    assert "enableTRA" in result.stdout


def test_command_exit_1_is_a_definitive_absence(csv_file: Path) -> None:
    result = runner.invoke(app, ["configurables", "CMRCTEATR", "--csv", str(csv_file)])
    assert result.exit_code == EXIT_NOT_IN_CSV
    assert "no esta en el CSV" in result.stdout
    assert "pendiente del SRE" in result.stdout


def test_command_exit_2_when_csv_unreadable_and_forbids_conclusion(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["configurables", "UMPSeguridad0087Config", "--csv", str(tmp_path / "nope.csv")]
    )
    assert result.exit_code == EXIT_CSV_UNAVAILABLE
    assert "NO concluyas" in result.stdout


def test_command_json_is_single_line_and_parseable(csv_file: Path) -> None:
    import json

    result = runner.invoke(
        app, ["configurables", "UMPSeguridad0087Config", "--csv", str(csv_file), "--json"]
    )
    assert result.exit_code == EXIT_FOUND
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["total"] == 3
    assert {r["variable"] for r in payload["rows"]} == {"url", "ns", "enableTRA"}

    missing = runner.invoke(app, ["configurables", "NoExiste", "--csv", str(csv_file), "--json"])
    assert json.loads(missing.stdout.strip())["status"] == "not_found"


def test_command_inventory_says_when_it_truncates(csv_file: Path) -> None:
    full = runner.invoke(app, ["configurables", "--csv", str(csv_file)])
    assert full.exit_code == EXIT_FOUND
    assert "3 configurables distintos" in full.stdout

    truncated = runner.invoke(app, ["configurables", "--csv", str(csv_file), "--limit", "1"])
    assert "Mostrando 1 de 3" in truncated.stdout
    assert "no concluyas ausencia" in truncated.stdout


def test_command_warns_about_source_encoding_artifacts(csv_file: Path) -> None:
    result = runner.invoke(app, ["configurables", "ORQClientes0040Config", "--csv", str(csv_file)])
    assert result.exit_code == EXIT_FOUND
    assert "acento mal codificado" in result.stdout


def test_command_yaml_output(csv_file: Path) -> None:
    result = runner.invoke(
        app, ["configurables", "UMPSeguridad0087Config", "--csv", str(csv_file), "--yaml"]
    )
    assert result.exit_code == EXIT_FOUND
    assert "UMPSeguridad0087Config:" in result.stdout


# ---------------------------------------------------------------------------
# Canonicals: la guia que causo el falso negativo quedo corregida
# ---------------------------------------------------------------------------


def test_canonicals_no_longer_teach_the_broken_recipe() -> None:
    targets = [
        CANONICAL_ROOT / "context" / "bank-official-rules.md",
        CANONICAL_ROOT / "context" / "bank-configurables.md",
        CANONICAL_ROOT / "context" / "CLAUDE.md",
        CANONICAL_ROOT / "prompts" / "analisis-servicio.md",
        CANONICAL_ROOT / "prompts" / "migrate-rest-full.md",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert "capamedia configurables" in text, path.name
        # `ConfigName` no debe presentarse como el nombre de la COLUMNA del CSV
        # (el header real es `Configurable`). Sigue siendo valido como nombre del
        # argumento del ESQL o en el token `Environment.cache.<ConfigName>`.
        assert "campo `ConfigName`" not in text, path.name

    rules = (CANONICAL_ROOT / "context" / "bank-official-rules.md").read_text(encoding="utf-8")
    assert "ISO-8859-1" in rules
    assert "533" in rules and "7868" in rules
    assert "CMRCTEATR" not in rules  # el ejemplo inexistente
    assert 'NO ENCONTRADO' in rules  # documenta el anti-patron del `|| echo`
