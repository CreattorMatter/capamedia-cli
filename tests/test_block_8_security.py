"""Tests for Block 8 security baseline (Spring Boot 3.5.14).

Cubre los cambios de seguridad CVE-driven decididos por el equipo
(Slack: kevin armas / Jean Pierre Garcia / Alexis Padilla, 2026-05):

- Check 8.1 severity subido de MEDIUM a HIGH (CVE-equivalente).
- Check 8.7 nuevo: pins manuales de io.netty:* en dependencyManagement -> HIGH.
- Autofix fix_spring_boot_plugin_version ahora actualiza tambien
  migration-context.json (consistencia build.gradle <-> contexto).
- Autofix fix_remove_netty_pin nuevo: elimina pins io.netty:*:VERSION del
  build.gradle.

Justificacion:
- Spring Boot 3.5.14 es el baseline aprobado para los servicios OLA.
- Pins manuales (Jackson o Netty) son anti-patron: se quedan atras al
  proximo CVE — exactamente lo que paso con netty-codec-http:4.1.132.Final
  que se metio para parchar un CVE y se transformo en el bug nuevo.
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.bank_autofix import fix_remove_netty_pin
from capamedia_cli.core.checklist_rules import CheckContext, run_block_8
from capamedia_cli.core.version_policy import SPRING_BOOT_BASELINE_VERSION


def _make_minimal_project(tmp_path: Path) -> Path:
    root = tmp_path / "migrated"
    (root / "src" / "main" / "java").mkdir(parents=True)
    return root


def _write_gradle(root: Path, content: str) -> Path:
    f = root / "build.gradle"
    f.write_text(content, encoding="utf-8")
    return f


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


# ---------------------------------------------------------------------------
# Baseline version
# ---------------------------------------------------------------------------


def test_baseline_is_3_5_14() -> None:
    """El baseline declarado en version_policy.py debe ser 3.5.14."""
    assert SPRING_BOOT_BASELINE_VERSION == "3.5.14"


# ---------------------------------------------------------------------------
# Check 8.1 — severity HIGH
# ---------------------------------------------------------------------------


def test_8_1_severity_is_high_for_old_version(tmp_path: Path) -> None:
    """Spring Boot < 3.5.14 -> HIGH."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, "plugins { id 'org.springframework.boot' version '3.5.13' }\n")

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.1")

    assert check.status == "fail"
    assert check.severity == "high"
    assert "3.5.14" in check.detail


def test_8_1_severity_high_when_version_missing(tmp_path: Path) -> None:
    """Cuando no se detecta version literal -> HIGH tambien."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        "plugins { id 'org.springframework.boot' }\n",  # sin version
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.1")

    assert check.status == "fail"
    assert check.severity == "high"


def test_8_1_passes_for_3_5_14(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, "plugins { id 'org.springframework.boot' version '3.5.14' }\n")

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.1")

    assert check.status == "pass"


def test_8_1_passes_for_3_5_15_newer(tmp_path: Path) -> None:
    """Versiones mas nuevas que el baseline tambien pasan."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, "plugins { id 'org.springframework.boot' version '3.5.15' }\n")

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.1")

    assert check.status == "pass"


# ---------------------------------------------------------------------------
# Check 8.7 — io.netty:* pin manual
# ---------------------------------------------------------------------------


def test_8_7_detects_netty_codec_http_pin(tmp_path: Path) -> None:
    """El pin viejo `netty-codec-http:4.1.132.Final` que se metio para parchar
    el CVE anterior y se transformo en el nuevo bug -> HIGH."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencyManagement {
    dependencies {
        // Patch CVE: Netty HTTP Request Smuggling
        dependency 'io.netty:netty-codec-http:4.1.132.Final'
        dependency 'io.netty:netty-codec-http2:4.1.132.Final'
    }
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.7")

    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"
    assert "io.netty" in check.detail


def test_8_7_detects_any_netty_pin(tmp_path: Path) -> None:
    """Cualquier `io.netty:*:VERSION` en dependencyManagement -> HIGH."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencyManagement {
    dependencies {
        dependency 'io.netty:netty-resolver-dns:4.1.999.Final'
    }
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.7")

    assert check.status == "fail"
    assert check.severity == "high"


def test_8_7_passes_without_netty_pin(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencyManagement {
    imports {
        mavenBom "org.springframework.cloud:spring-cloud-dependencies:2025.0.0"
    }
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.7")

    assert check.status == "pass"


def test_8_7_ignores_netty_in_comments(tmp_path: Path) -> None:
    """Una mencion de io.netty: dentro de un comentario NO es bug."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencyManagement {
    // NEVER: dependency 'io.netty:netty-codec-http:4.1.132.Final'
    // This pin would re-introduce the Snyk CVE.
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.7")

    assert check.status == "pass"


def test_8_7_ignores_netty_dependencies_outside_dependency_management(tmp_path: Path) -> None:
    """El check solo aplica a pins dentro de dependencyManagement, no a
    `implementation 'io.netty:netty-handler:4.x'` directas (que serian deps
    transitivas legítimas si alguien las necesita)."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencies {
    implementation 'io.netty:netty-handler:4.1.132.Final'
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.7")

    assert check.status == "pass"


# ---------------------------------------------------------------------------
# Autofix fix_remove_netty_pin
# ---------------------------------------------------------------------------


def test_autofix_removes_netty_codec_http_pin(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    f = _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencyManagement {
    dependencies {
        // Patch CVE: Netty HTTP Request Smuggling
        dependency 'io.netty:netty-codec-http:4.1.132.Final'
        dependency 'io.netty:netty-codec-http2:4.1.132.Final'
    }
}
""",
    )

    result = fix_remove_netty_pin(root)
    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    assert "io.netty:netty-codec-http:" not in text
    assert "io.netty:netty-codec-http2:" not in text
    # El comentario "Patch CVE" se queda — lo limpia el dev manualmente o
    # el linter de Gradle al re-formatear. El autofix solo saca las lineas
    # de pin para no romper la estructura del bloque.


def test_autofix_idempotent(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }
dependencyManagement { imports { mavenBom 'foo:bar:1.0' } }
""",
    )

    first = fix_remove_netty_pin(root)
    second = fix_remove_netty_pin(root)

    assert first.applied is False
    assert second.applied is False


def test_autofix_no_build_gradle(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    result = fix_remove_netty_pin(root)
    assert result.applied is False


def test_autofix_preserves_other_dependencies(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    f = _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-webflux'
    implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0'
}

dependencyManagement {
    imports {
        mavenBom 'org.springframework.cloud:spring-cloud-dependencies:2025.0.0'
    }
    dependencies {
        dependency 'io.netty:netty-codec-http:4.1.132.Final'
    }
}
""",
    )

    result = fix_remove_netty_pin(root)
    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    # Netty pin removido
    assert "io.netty:netty-codec-http:" not in text
    # Resto del build.gradle intacto
    assert "spring-boot-starter-webflux" in text
    assert "lib-bnc-api-client:1.1.0" in text
    assert "spring-cloud-dependencies:2025.0.0" in text


def test_autofix_preserves_direct_netty_dependency_outside_dependency_management(tmp_path: Path) -> None:
    """El autofix debe seguir el mismo alcance del checker: solo dependencyManagement."""
    root = _make_minimal_project(tmp_path)
    f = _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencies {
    implementation 'io.netty:netty-handler:4.1.132.Final'
}

dependencyManagement {
    imports {
        mavenBom 'org.springframework.cloud:spring-cloud-dependencies:2025.0.0'
    }
}
""",
    )

    result = fix_remove_netty_pin(root)

    text = f.read_text(encoding="utf-8")
    assert result.applied is False
    assert "io.netty:netty-handler:4.1.132.Final" in text
