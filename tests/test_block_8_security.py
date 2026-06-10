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

import json
from pathlib import Path

from capamedia_cli.core.bank_autofix import (
    fix_netty_full_tree_pin,
    fix_remove_netty_pin,
    fix_webflux_security_pins,
)
from capamedia_cli.core.checklist_rules import CheckContext, run_block_8
from capamedia_cli.core.version_policy import (
    NETTY_CORE_MODULES,
    NETTY_WEBFLUX_ALLOWED_VERSION,
    SPRING_BOOT_BASELINE_VERSION,
    SPRING_FRAMEWORK_BOM_COORD,
    SPRING_FRAMEWORK_BOM_VERSION,
    WEBFLUX_SECURITY_DEPENDENCY_PINS,
)


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


# ---------------------------------------------------------------------------
# v0.27.0 — WebFlux: pin 4.1.135.Final permitido (CVE-fix oficial 2026-05)
# ---------------------------------------------------------------------------


def test_8_7_allows_4_1_135_pin_in_webflux(tmp_path: Path) -> None:
    """WebFlux + pin oficial `io.netty:*:4.1.135.Final` -> pass."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-webflux'
}

dependencyManagement {
    dependencies {
        // CVE-fix oficial 2026-05
        dependency 'io.netty:netty-codec-http:4.1.135.Final'
        dependency 'io.netty:netty-codec-http2:4.1.135.Final'
    }
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.7")

    assert check.status == "pass"
    assert "4.1.135.Final" in check.detail


def test_8_7_rejects_non_135_pin_in_webflux(tmp_path: Path) -> None:
    """WebFlux + pin distinto de 4.1.135.Final -> FAIL HIGH."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-webflux'
}

dependencyManagement {
    dependencies {
        dependency 'io.netty:netty-codec-http:4.1.132.Final'
    }
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.7")

    assert check.status == "fail"
    assert check.severity == "high"


def test_8_7_rejects_4_1_135_pin_when_not_webflux(tmp_path: Path) -> None:
    """MVC/SOAP + pin 4.1.135.Final -> FAIL HIGH. La excepcion es solo WebFlux."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-web'
}

dependencyManagement {
    dependencies {
        dependency 'io.netty:netty-codec-http:4.1.135.Final'
    }
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_8(ctx)
    check = _find(results, "8.7")

    assert check.status == "fail"


def test_autofix_preserves_4_1_135_pin_in_webflux(tmp_path: Path) -> None:
    """En WebFlux el autofix preserva el pin oficial 4.1.135.Final."""
    root = _make_minimal_project(tmp_path)
    f = _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-webflux'
}

dependencyManagement {
    dependencies {
        dependency 'io.netty:netty-codec-http:4.1.135.Final'
    }
}
""",
    )

    result = fix_remove_netty_pin(root)
    text = f.read_text(encoding="utf-8")

    assert result.applied is False
    assert "io.netty:netty-codec-http:4.1.135.Final" in text


def test_autofix_removes_non_135_pin_in_webflux(tmp_path: Path) -> None:
    """En WebFlux el autofix sigue removiendo pins de otras versiones."""
    root = _make_minimal_project(tmp_path)
    f = _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-webflux'
}

dependencyManagement {
    dependencies {
        dependency 'io.netty:netty-codec-http:4.1.132.Final'
    }
}
""",
    )

    result = fix_remove_netty_pin(root)
    text = f.read_text(encoding="utf-8")

    assert result.applied is True
    assert "4.1.132.Final" not in text


def test_autofix_mixed_pins_in_webflux_only_removes_non_135(tmp_path: Path) -> None:
    """En WebFlux con varios pins, solo se removeria los NO 4.1.135.Final."""
    root = _make_minimal_project(tmp_path)
    f = _write_gradle(
        root,
        """\
plugins { id 'org.springframework.boot' version '3.5.14' }

dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-webflux'
}

dependencyManagement {
    dependencies {
        dependency 'io.netty:netty-codec-http:4.1.135.Final'
        dependency 'io.netty:netty-resolver-dns:4.1.132.Final'
    }
}
""",
    )

    result = fix_remove_netty_pin(root)
    text = f.read_text(encoding="utf-8")

    assert result.applied is True
    assert "io.netty:netty-codec-http:4.1.135.Final" in text
    assert "netty-resolver-dns" not in text


# ---------------------------------------------------------------------------
# Check 8.8 + autofix fix_netty_full_tree_pin — arbol Netty completo (NETTY_CORE_MODULES)
# en WebFlux con doble mecanismo (dependencyManagement + resolutionStrategy.force).
# WSClientes0013 (2026-05-29): pinear solo netty-codec* dejaba 9 CVEs vivos.
# ---------------------------------------------------------------------------

_CORE_4 = ("netty-codec", "netty-codec-dns", "netty-codec-http", "netty-codec-http2")
_VER = NETTY_WEBFLUX_ALLOWED_VERSION


def _webflux_gradle(dep_mods, force_mods=None, version=_VER) -> str:
    """build.gradle WebFlux con pins de Netty en dependencyManagement y,
    opcionalmente, un bloque resolutionStrategy.force."""
    dep_lines = "\n".join(
        f"        dependency 'io.netty:{m}:{version}'" for m in dep_mods
    )
    blocks = [
        "plugins { id 'org.springframework.boot' version '3.5.14' }",
        "",
        "dependencies {",
        "    implementation 'org.springframework.boot:spring-boot-starter-webflux'",
        "}",
        "",
        "dependencyManagement {",
        "    dependencies {",
        dep_lines,
        "    }",
        "}",
    ]
    if force_mods is not None:
        force_lines = "\n".join(
            f"        force 'io.netty:{m}:{version}'" for m in force_mods
        )
        blocks += [
            "",
            "configurations.all {",
            "    resolutionStrategy {",
            force_lines,
            "    }",
            "}",
        ]
    return "\n".join(blocks) + "\n"


def test_8_8_fail_when_tree_incomplete(tmp_path: Path) -> None:
    """WebFlux con solo 4 modulos pineados -> FAIL HIGH listando faltantes."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _webflux_gradle(_CORE_4, _CORE_4))

    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.8")

    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"
    assert "netty-handler-proxy" in check.detail  # faltante representativo


def test_8_8_pass_when_tree_complete(tmp_path: Path) -> None:
    """Todos los modulos core (NETTY_CORE_MODULES) en dependency + force -> PASS."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _webflux_gradle(NETTY_CORE_MODULES, NETTY_CORE_MODULES))

    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.8")

    assert check is not None
    assert check.status == "pass"


def test_8_8_fail_when_force_missing(tmp_path: Path) -> None:
    """12 en dependencyManagement pero 0 en force -> FAIL (falta el doble pin)."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _webflux_gradle(NETTY_CORE_MODULES))  # sin bloque force

    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.8")

    assert check is not None
    assert check.status == "fail"
    assert "force" in check.detail.lower()


def test_8_8_not_emitted_without_netty_pin(tmp_path: Path) -> None:
    """WebFlux sin ningun pin io.netty -> el 8.8 no aplica (no se emite)."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        "plugins { id 'org.springframework.boot' version '3.5.14' }\n"
        "dependencies {\n"
        "    implementation 'org.springframework.boot:spring-boot-starter-webflux'\n"
        "}\n",
    )

    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.8")

    assert check is None


def test_autofix_full_tree_completes_dependency_and_force(tmp_path: Path) -> None:
    """4 modulos en dependency + force -> autofix completa a 12 + 12."""
    root = _make_minimal_project(tmp_path)
    f = _write_gradle(root, _webflux_gradle(_CORE_4, _CORE_4))

    result = fix_netty_full_tree_pin(root)
    text = f.read_text(encoding="utf-8")

    assert result.applied is True
    dep = sum(1 for ln in text.splitlines() if ln.strip().startswith("dependency 'io.netty"))
    force = sum(1 for ln in text.splitlines() if ln.strip().startswith("force 'io.netty"))
    assert dep == len(NETTY_CORE_MODULES)
    assert force == len(NETTY_CORE_MODULES)
    for mod in NETTY_CORE_MODULES:
        assert f"dependency 'io.netty:{mod}:{_VER}'" in text
        assert f"force 'io.netty:{mod}:{_VER}'" in text


def test_autofix_full_tree_creates_force_block(tmp_path: Path) -> None:
    """4 modulos en dependency, SIN bloque force -> autofix crea el force block."""
    root = _make_minimal_project(tmp_path)
    f = _write_gradle(root, _webflux_gradle(_CORE_4))  # sin force

    result = fix_netty_full_tree_pin(root)
    text = f.read_text(encoding="utf-8")

    assert result.applied is True
    assert "configurations.all" in text
    assert "resolutionStrategy" in text
    force = sum(1 for ln in text.splitlines() if ln.strip().startswith("force 'io.netty"))
    assert force == len(NETTY_CORE_MODULES)
    # gradle balanceado tras crear el bloque
    assert text.count("{") == text.count("}")


def test_autofix_full_tree_idempotent(tmp_path: Path) -> None:
    """Segunda pasada no agrega duplicados ni reescribe el archivo."""
    root = _make_minimal_project(tmp_path)
    f = _write_gradle(root, _webflux_gradle(_CORE_4, _CORE_4))

    fix_netty_full_tree_pin(root)
    after_first = f.read_text(encoding="utf-8")
    second = fix_netty_full_tree_pin(root)
    after_second = f.read_text(encoding="utf-8")

    assert second.applied is False
    assert after_first == after_second


def test_autofix_full_tree_skips_non_webflux(tmp_path: Path) -> None:
    """MVC/SOAP: no se pinea el arbol Netty (no aplica)."""
    root = _make_minimal_project(tmp_path)
    gradle = _webflux_gradle(_CORE_4, _CORE_4).replace(
        "spring-boot-starter-webflux", "spring-boot-starter-web"
    )
    f = _write_gradle(root, gradle)

    result = fix_netty_full_tree_pin(root)

    assert result.applied is False
    assert f.read_text(encoding="utf-8") == gradle


def test_autofix_full_tree_skips_wrong_version(tmp_path: Path) -> None:
    """Si el pin base es 4.2.x (no permitida), el full-tree no completa
    (lo gobierna el Check/autofix 8.7)."""
    root = _make_minimal_project(tmp_path)
    gradle = _webflux_gradle(_CORE_4, _CORE_4, version="4.2.13.Final")
    f = _write_gradle(root, gradle)

    result = fix_netty_full_tree_pin(root)

    assert result.applied is False
    assert f.read_text(encoding="utf-8") == gradle


def test_autofix_full_tree_skips_without_base_pin(tmp_path: Path) -> None:
    """WebFlux sin ningun pin io.netty -> no forzamos pins (skip)."""
    root = _make_minimal_project(tmp_path)
    gradle = (
        "plugins { id 'org.springframework.boot' version '3.5.14' }\n"
        "dependencies {\n"
        "    implementation 'org.springframework.boot:spring-boot-starter-webflux'\n"
        "}\n"
    )
    f = _write_gradle(root, gradle)

    result = fix_netty_full_tree_pin(root)

    assert result.applied is False
    assert f.read_text(encoding="utf-8") == gradle


# ---------------------------------------------------------------------------
# Check 8.9 — lib-bnc-api-client solo si BUS/IIB + invocaBancs (falso positivo
# WSReglas0010: el CLI reagregaba la lib que el PR-gate luego rechaza).
# ---------------------------------------------------------------------------

_GRADLE_WITH_LIBBNC = (
    "plugins { id 'org.springframework.boot' version '3.5.14' }\n"
    "dependencies {\n"
    "    implementation 'org.springframework.boot:spring-boot-starter-webflux'\n"
    "    implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0'\n"
    "}\n"
)
_GRADLE_NO_LIBBNC = (
    "plugins { id 'org.springframework.boot' version '3.5.14' }\n"
    "dependencies {\n"
    "    implementation 'org.springframework.boot:spring-boot-starter-webflux'\n"
    "}\n"
)


def _write_fabrics(root: Path, *, tecnologia: str = "bus", invoca_bancs: bool) -> None:
    fj = root / ".capamedia" / "fabrics.json"
    fj.parent.mkdir(parents=True, exist_ok=True)
    fj.write_text(
        json.dumps({"tecnologia": tecnologia, "invoca_bancs": invoca_bancs}),
        encoding="utf-8",
    )


def test_8_9_lib_present_without_invoca_bancs_fails_high(tmp_path: Path) -> None:
    """Caso WSReglas0010: lib declarada + fabrics invoca_bancs=false -> FAIL HIGH."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _GRADLE_WITH_LIBBNC)
    _write_fabrics(root, invoca_bancs=False)
    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.9")
    assert check.status == "fail"
    assert check.severity == "high"


def test_8_9_lib_present_with_invoca_bancs_passes(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _GRADLE_WITH_LIBBNC)
    _write_fabrics(root, invoca_bancs=True)
    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.9")
    assert check.status == "pass"


def test_8_9_lib_absent_without_bancs_passes(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _GRADLE_NO_LIBBNC)
    _write_fabrics(root, invoca_bancs=False)
    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.9")
    assert check.status == "pass"


def test_8_9_lib_absent_with_bancs_fails_high(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _GRADLE_NO_LIBBNC)
    _write_fabrics(root, invoca_bancs=True)
    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.9")
    assert check.status == "fail"
    assert check.severity == "high"


def test_8_9_no_fabrics_falls_back_to_ctx(tmp_path: Path) -> None:
    """Sin fabrics.json, cae a la matriz (ctx): lib + ctx no-BANCS -> FAIL HIGH."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _GRADLE_WITH_LIBBNC)
    ctx = CheckContext(
        migrated_path=root, legacy_path=None, source_type="bus", has_bancs=False
    )
    check = _find(run_block_8(ctx), "8.9")
    assert check.status == "fail"
    assert check.severity == "high"


def _write_fabrics_raw(root: Path, payload: dict) -> None:
    fj = root / ".capamedia" / "fabrics.json"
    fj.parent.mkdir(parents=True, exist_ok=True)
    fj.write_text(json.dumps(payload), encoding="utf-8")


def test_8_9_reads_string_invoca_bancs_like_pr_gate(tmp_path: Path) -> None:
    """El fabrics.json REAL serializa invoca_bancs como STRING; el check debe leerlo."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _GRADLE_WITH_LIBBNC)
    _write_fabrics_raw(root, {"source_kind": "iib", "tecnologia": "bus", "invoca_bancs": "true"})
    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.9")
    assert check.status == "pass"


def test_8_9_camelcase_and_source_kind_match_gate(tmp_path: Path) -> None:
    """invocaBancs camelCase + source_kind=iib (tecnologia≠bus) -> requires (como el gate)."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _GRADLE_WITH_LIBBNC)
    _write_fabrics_raw(root, {"source_kind": "iib", "tecnologia": "rest", "invocaBancs": True})
    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.9")
    assert check.status == "pass"


def test_8_9_ignores_libbnc_in_comment(tmp_path: Path) -> None:
    """La lib mencionada SOLO en un comentario no cuenta como declarada."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(
        root,
        "plugins { id 'org.springframework.boot' version '3.5.14' }\n"
        "dependencies {\n"
        "    // NEVER add com.pichincha.bnc:lib-bnc-api-client here\n"
        "    implementation 'org.springframework.boot:spring-boot-starter-webflux'\n"
        "}\n",
    )
    _write_fabrics(root, invoca_bancs=False)
    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.9")
    assert check.status == "pass"


def test_8_9_parity_with_vendor_is_bus_bancs() -> None:
    """La replica _fabrics_requires_bancs coincide con el PR-gate _is_bus_bancs en
    los casos que el review marco como divergentes."""
    import importlib.util

    import capamedia_cli
    from capamedia_cli.core.checklist_rules import _fabrics_requires_bancs

    vendor = Path(capamedia_cli.__file__).parent / "data" / "vendor" / "validate_hexagonal.py"
    spec = importlib.util.spec_from_file_location("validate_hexagonal_paritytest", vendor)
    vh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vh)
    cases = [
        {"source_kind": "iib", "tecnologia": "bus", "invoca_bancs": "true"},
        {"source_kind": "bus", "invoca_bancs": "true"},
        {"source_kind": "bus", "invocaBancs": True},
        {"source_kind": "iib", "tecnologia": "rest", "invoca_bancs": True},
        {"tecnologia": "was", "invoca_bancs": "false"},
        {"tecnologia": "bus", "invoca_bancs": False},
        {},
    ]
    for meta in cases:
        assert _fabrics_requires_bancs(meta) == vh._is_bus_bancs(meta), meta


def test_8_9_libbnc_in_submodule_detected(tmp_path: Path) -> None:
    """La lib en un submodulo (no en el gradle raiz) se detecta (rglob, L4)."""
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, "plugins { id 'org.springframework.boot' version '3.5.14' }\n")
    sub = root / "modulo-app"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "build.gradle").write_text(
        "dependencies {\n    implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0'\n}\n",
        encoding="utf-8",
    )
    _write_fabrics(root, invoca_bancs=False)
    check = _find(run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.9")
    assert check.status == "fail"
    assert check.severity == "high"


# ---------------------------------------------------------------------------
# Check 8.10 + autofix fix_webflux_security_pins — pins NO-Netty del stack
# WebFlux (Snyk 2026-06): micrometer-core, reactor-netty-http, spring-retry,
# spring-kafka (dependency) + spring-framework-bom (mavenBom). Mismo gate que 8.8
# (WebFlux con Netty ya pineado en la version permitida). MVC/SOAP no aplican.
# ---------------------------------------------------------------------------


def test_8_10_autofix_adds_all_missing_webflux_pins(tmp_path: Path) -> None:
    """WebFlux con Netty pineado pero sin los pins NO-Netty -> autofix los agrega."""
    root = _make_minimal_project(tmp_path)
    f = _write_gradle(root, _webflux_gradle(_CORE_4))  # netty ok, faltan los 5

    result = fix_webflux_security_pins(root)
    text = f.read_text(encoding="utf-8")

    assert result.applied is True
    for coord, ver in WEBFLUX_SECURITY_DEPENDENCY_PINS.items():
        assert f"dependency '{coord}:{ver}'" in text
    assert (
        f"mavenBom '{SPRING_FRAMEWORK_BOM_COORD}:{SPRING_FRAMEWORK_BOM_VERSION}'"
        in text
    )
    assert text.count("{") == text.count("}")  # gradle balanceado


def test_8_10_autofix_skips_non_webflux(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    gradle = _webflux_gradle(_CORE_4).replace(
        "spring-boot-starter-webflux", "spring-boot-starter-web"
    )
    f = _write_gradle(root, gradle)

    result = fix_webflux_security_pins(root)

    assert result.applied is False
    assert f.read_text(encoding="utf-8") == gradle


def test_8_10_autofix_skips_when_netty_not_pinned(tmp_path: Path) -> None:
    """WebFlux pero sin pin base de Netty -> gate cierra (8.7/8.8 primero)."""
    root = _make_minimal_project(tmp_path)
    gradle = (
        "plugins { id 'org.springframework.boot' version '3.5.14' }\n"
        "dependencies {\n"
        "    implementation 'org.springframework.boot:spring-boot-starter-webflux'\n"
        "}\n"
    )
    f = _write_gradle(root, gradle)

    result = fix_webflux_security_pins(root)

    assert result.applied is False
    assert f.read_text(encoding="utf-8") == gradle


def test_8_10_autofix_idempotent(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    f = _write_gradle(root, _webflux_gradle(_CORE_4))

    fix_webflux_security_pins(root)
    after_first = f.read_text(encoding="utf-8")
    second = fix_webflux_security_pins(root)
    after_second = f.read_text(encoding="utf-8")

    assert second.applied is False
    assert after_first == after_second


def test_8_10_autofix_replaces_wrong_version(tmp_path: Path) -> None:
    """spring-kafka pineado en version vieja -> se corrige a la requerida."""
    root = _make_minimal_project(tmp_path)
    # Inyectar spring-kafka viejo dentro del bloque dependencyManagement.dependencies
    gradle = _webflux_gradle(_CORE_4).replace(
        "    }\n}\n",
        "        dependency 'org.springframework.kafka:spring-kafka:3.3.0'\n    }\n}\n",
        1,
    )
    f = _write_gradle(root, gradle)

    result = fix_webflux_security_pins(root)
    text = f.read_text(encoding="utf-8")

    assert result.applied is True
    assert "spring-kafka:3.3.16" in text
    assert "spring-kafka:3.3.0'" not in text


def test_8_10_check_fails_when_incomplete(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _webflux_gradle(_CORE_4))  # netty ok, faltan los 5

    check = _find(
        run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.10"
    )
    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"


def test_8_10_check_passes_when_complete(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_gradle(root, _webflux_gradle(_CORE_4))
    fix_webflux_security_pins(root)  # completa los pins

    check = _find(
        run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.10"
    )
    assert check is not None
    assert check.status == "pass"


def test_8_10_check_absent_for_non_webflux(tmp_path: Path) -> None:
    """MVC/SOAP no emite el check 8.10 (reactor-netty/spring-kafka no aplican)."""
    root = _make_minimal_project(tmp_path)
    gradle = _webflux_gradle(_CORE_4).replace(
        "spring-boot-starter-webflux", "spring-boot-starter-web"
    )
    _write_gradle(root, gradle)

    check = _find(
        run_block_8(CheckContext(migrated_path=root, legacy_path=None)), "8.10"
    )
    assert check is None
