"""Tests para helpers de gradle.properties."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.gradle_properties import remove_committed_gradle_java_home


def test_remove_committed_gradle_java_home_removes_only_local_jdk_property(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    props = project / "gradle.properties"
    props.write_text(
        "org.gradle.jvmargs=-Xmx1g\n"
        "org.gradle.java.home=C:/Program Files/Eclipse Adoptium/jdk-21\n"
        "# org.gradle.java.home=/documented/example\n"
        "systemProp.file.encoding=UTF-8\n",
        encoding="utf-8",
    )

    result = remove_committed_gradle_java_home(project)

    assert result.existed is True
    assert result.removed == 1
    text = props.read_text(encoding="utf-8")
    assert "org.gradle.java.home=C:" not in text
    assert "# org.gradle.java.home=/documented/example" in text
    assert "org.gradle.jvmargs=-Xmx1g" in text
    assert text.endswith("\n")


def test_remove_committed_gradle_java_home_handles_missing_file(tmp_path: Path) -> None:
    result = remove_committed_gradle_java_home(tmp_path)

    assert result.existed is False
    assert result.removed == 0
    assert result.path == tmp_path / "gradle.properties"
