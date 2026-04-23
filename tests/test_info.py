"""Tests para `capamedia info` + `/info` slash command (v0.23.12)."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from capamedia_cli.cli import app


runner = CliRunner()


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


def test_info_is_registered() -> None:
    """`capamedia info --help` debe funcionar."""
    result = runner.invoke(app, ["info", "--help"])
    assert result.exit_code == 0
    assert "dashboard" in result.output.lower() or "pendientes" in result.output.lower()


def test_info_runs_on_empty_workspace(tmp_path: Path) -> None:
    """Sin reports, info no crashea — muestra placeholders."""
    (tmp_path / ".capamedia").mkdir()
    (tmp_path / ".capamedia" / "config.yaml").write_text(
        "service_name: wsfoo0001\n", encoding="utf-8",
    )
    result = runner.invoke(app, ["info", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "wsfoo0001" in result.output
    # Secciones principales presentes
    assert "Properties" in result.output
    assert "Downstream" in result.output


def test_info_shows_pending_properties(tmp_path: Path) -> None:
    """Report con PENDING_FROM_BANK se muestra en la seccion."""
    (tmp_path / ".capamedia").mkdir()
    (tmp_path / ".capamedia" / "config.yaml").write_text(
        "service_name: wsclientes0076\n", encoding="utf-8",
    )
    report = {
        "service_specific_properties": [
            {
                "file": "umpclientes0025.properties",
                "status": "PENDING_FROM_BANK",
                "source": "ump:umpclientes0025",
                "keys_used": ["GRUPO_CENTRALIZADA", "RECURSO_01"],
            },
        ],
        "shared_catalog_keys_used": {
            "generalServices.properties": ["OMNI_COD_SERVICIO_OK"],
        },
    }
    (tmp_path / ".capamedia" / "properties-report.yaml").write_text(
        yaml.safe_dump(report), encoding="utf-8",
    )

    result = runner.invoke(app, ["info", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "umpclientes0025.properties" in result.output
    assert "GRUPO_CENTRALIZADA" in result.output
    assert "generalServices.properties" in result.output
    # Mensaje de accion
    assert ".capamedia/inputs" in result.output or "raiz del workspace" in result.output


def test_info_shows_secrets_for_was_with_db(tmp_path: Path) -> None:
    """Secretos KV se muestran si has_database=true."""
    (tmp_path / ".capamedia").mkdir()
    (tmp_path / ".capamedia" / "config.yaml").write_text(
        "service_name: wsclientes0045\n", encoding="utf-8",
    )
    secrets_report = {
        "service_kind": "was",
        "has_database": True,
        "secrets_required": [
            {
                "base_de_datos": "TPOMN",
                "jndi": "jndi.tecnicos.cataloga",
                "user_secret": "CCC-ORACLE-OMNI-CATALOGA-USER",
                "password_secret": "CCC-ORACLE-OMNI-CATALOGA-PASSWORD",
            },
        ],
        "jndi_references_unknown": [],
    }
    (tmp_path / ".capamedia" / "secrets-report.yaml").write_text(
        yaml.safe_dump(secrets_report), encoding="utf-8",
    )

    result = runner.invoke(app, ["info", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "CCC-ORACLE-OMNI-CATALOGA-USER" in result.output
    assert "jndi.tecnicos.cataloga" in result.output


def test_info_skips_secrets_for_non_was(tmp_path: Path) -> None:
    """Para BUS/ORQ sin reporte de secretos, muestra mensaje claro."""
    (tmp_path / ".capamedia").mkdir()
    (tmp_path / ".capamedia" / "config.yaml").write_text(
        "service_name: orq0027\n", encoding="utf-8",
    )

    result = runner.invoke(app, ["info", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    # Debe mencionar que no aplica (o similar)
    assert "no aplica" in result.output.lower() or "solo WAS" in result.output


def test_info_detects_sonarlint_placeholder(tmp_path: Path) -> None:
    """Si connectedMode.json tiene <PROJECT_KEY_FROM_SONARCLOUD>, lo marca como handoff."""
    (tmp_path / ".capamedia").mkdir()
    (tmp_path / ".capamedia" / "config.yaml").write_text(
        "service_name: wsx0001\n", encoding="utf-8",
    )
    sonar = tmp_path / ".sonarlint"
    sonar.mkdir()
    (sonar / "connectedMode.json").write_text(
        '{"sonarCloudOrganization": "bancopichinchaec", '
        '"projectKey": "<PROJECT_KEY_FROM_SONARCLOUD>"}',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["info", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert ".sonarlint/connectedMode.json" in result.output
    assert "project_key" in result.output.lower() or "placeholder" in result.output.lower()


def test_info_next_step_when_properties_pending(tmp_path: Path) -> None:
    """Si hay PENDING, el siguiente paso sugiere pedir al owner + checklist."""
    (tmp_path / ".capamedia").mkdir()
    (tmp_path / ".capamedia" / "config.yaml").write_text(
        "service_name: wsfoo0001\n", encoding="utf-8",
    )
    (tmp_path / ".capamedia" / "properties-report.yaml").write_text(
        yaml.safe_dump({
            "service_specific_properties": [
                {"file": "x.properties", "status": "PENDING_FROM_BANK",
                 "source": "service", "keys_used": ["K1"]},
            ],
        }),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["info", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    # Siguiente paso especifico cuando hay pending
    assert "Pedir" in result.output or "pending" in result.output.lower()
    assert "checklist" in result.output.lower() or "doublecheck" in result.output.lower()


def test_info_counts_umps_from_legacy(tmp_path: Path) -> None:
    """Seccion Downstream cuenta UMPs clonadas."""
    (tmp_path / ".capamedia").mkdir()
    (tmp_path / ".capamedia" / "config.yaml").write_text(
        "service_name: wsclientes0076\n", encoding="utf-8",
    )
    # Simular 2 UMPs clonados
    (tmp_path / "umps" / "ump-umpclientes0025-was").mkdir(parents=True)
    (tmp_path / "umps" / "ump-umpotro0099-was").mkdir(parents=True)

    result = runner.invoke(app, ["info", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "UMPs" in result.output
    # El conteo "2" debe aparecer
    assert "2" in result.output


# ---------------------------------------------------------------------------
# Slash command integration
# ---------------------------------------------------------------------------


def test_info_slash_command_canonical_loaded() -> None:
    """v0.23.12: /info disponible como prompt canonical."""
    from capamedia_cli.core.canonical import load_canonical_assets

    assets = load_canonical_assets()
    names = {a.name for a in assets["prompt"]}
    assert "info" in names, "/info debe estar como prompt canonical"


def test_info_slash_invokes_capamedia_info() -> None:
    """El prompt /info debe indicar que corra `capamedia info`."""
    from capamedia_cli.core.canonical import CANONICAL_ROOT

    content = (CANONICAL_ROOT / "prompts" / "info.md").read_text(encoding="utf-8")
    assert "capamedia info" in content
    # Menciona los 3 tipos de servicio
    assert "WAS" in content
    assert "BUS" in content or "IIB" in content
    assert "ORQ" in content


def test_init_scaffolds_info_slash_in_claude_commands(tmp_path: Path, monkeypatch) -> None:
    """Despues de init --ai claude, .claude/commands/info.md existe."""
    from capamedia_cli.commands.init import scaffold_project

    monkeypatch.chdir(tmp_path)
    scaffold_project(
        target_dir=tmp_path,
        service_name="wsfooXXXX",
        harnesses=["claude"],
    )
    info_file = tmp_path / ".claude" / "commands" / "info.md"
    assert info_file.exists(), "/info debe ser un slash command disponible en Claude Code"
