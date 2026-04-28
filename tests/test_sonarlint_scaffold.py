"""Tests para templates SonarLint (v0.22.0)."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.commands.init import scaffold_project
from capamedia_cli.core.gitignore_policy import DEPLOYMENT_GITIGNORE_ENTRIES


def test_init_scaffolds_sonarlint_example_and_readme(tmp_path: Path, monkeypatch) -> None:
    """v0.22.0: init debe generar connectedMode.example.json + README.md bajo .sonarlint/.

    Antes solo generaba connectedMode.json (template con placeholder). Ahora
    tambien escribe un example con UUID de ejemplo y un README con la guia
    de setup, para que el developer tenga contexto de como conectarlo a
    SonarCloud sin salir del workspace.
    """
    monkeypatch.chdir(tmp_path)
    scaffold_project(
        target_dir=tmp_path,
        service_name="wsclientesXXXX",
        harnesses=["claude"],
    )

    sonarlint = tmp_path / ".sonarlint"
    assert sonarlint.is_dir()

    # Template con placeholder (ya existia)
    template = sonarlint / "connectedMode.json"
    assert template.exists()
    assert "<PROJECT_KEY_FROM_SONARCLOUD>" in template.read_text(encoding="utf-8")

    # Example con UUID ejemplo (nuevo v0.22.0)
    example = sonarlint / "connectedMode.example.json"
    assert example.exists(), (
        "connectedMode.example.json deberia existir en .sonarlint/ - "
        "muestra al developer el formato del project_key real"
    )
    example_content = example.read_text(encoding="utf-8")
    assert "bancopichinchaec" in example_content
    # El example tiene un UUID de ejemplo, no un placeholder
    assert "<PROJECT_KEY_FROM_SONARCLOUD>" not in example_content

    # README con guia de setup (nuevo v0.22.0)
    readme = sonarlint / "README.md"
    assert readme.exists()
    readme_content = readme.read_text(encoding="utf-8")
    assert "SonarLint" in readme_content
    assert "SonarCloud" in readme_content
    # La guia menciona el service_name del workspace
    assert "wsclientesXXXX" in readme_content
    # Pasos principales
    assert "Connected Mode" in readme_content

    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".sonarlint/*" in gitignore
    assert "!.sonarlint/connectedMode.json" in gitignore
    assert "!.sonarlint/connectedMode.example.json" in gitignore
    assert "!.sonarlint/README.md" in gitignore
    for entry in DEPLOYMENT_GITIGNORE_ENTRIES:
        assert entry in gitignore
