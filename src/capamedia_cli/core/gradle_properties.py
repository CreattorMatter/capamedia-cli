"""Helpers para propiedades Gradle que no deben quedar versionadas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

GRADLE_JAVA_HOME_PROPERTY = "org.gradle.java.home"


@dataclass(frozen=True)
class GradleJavaHomeSanitizeResult:
    path: Path
    existed: bool
    removed: int


def remove_committed_gradle_java_home(project_dir: Path) -> GradleJavaHomeSanitizeResult:
    """Quita org.gradle.java.home del gradle.properties del proyecto.

    Esa propiedad apunta a un JDK absoluto de la maquina local. Si queda
    versionada, rompe los pipelines Linux/Windows que no tienen la misma ruta.
    """
    props = project_dir / "gradle.properties"
    if not props.exists():
        return GradleJavaHomeSanitizeResult(path=props, existed=False, removed=0)

    text = props.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    kept = [line for line in lines if not line.strip().startswith(GRADLE_JAVA_HOME_PROPERTY)]
    removed = len(lines) - len(kept)
    if removed:
        props.write_text(("\n".join(kept).rstrip() + "\n") if kept else "", encoding="utf-8")

    return GradleJavaHomeSanitizeResult(path=props, existed=True, removed=removed)
