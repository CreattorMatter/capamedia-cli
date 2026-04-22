"""Tests para el Block 16: SonarCloud custom rule - test class annotations.

Regla: cada `*Test.java` / `*Tests.java` bajo `src/test/java/` debe tener
al menos una anotacion de test class reconocida (@SpringBootTest,
@WebMvcTest, @ExtendWith, @RunWith, etc.). SonarCloud del banco lo
reporta como violation en Quality Gate.
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.autofix import fix_add_test_annotation
from capamedia_cli.core.checklist_rules import CheckContext, run_block_16

# ---------------------------------------------------------------------------
# Check 16.1 — detection
# ---------------------------------------------------------------------------


def _make_test_class(
    tmp_path: Path,
    name: str = "FooTest",
    annotations: list[str] | None = None,
    body: str = 'public void test() {}',
) -> Path:
    test_dir = tmp_path / "src" / "test" / "java" / "com" / "pichincha"
    test_dir.mkdir(parents=True, exist_ok=True)
    f = test_dir / f"{name}.java"
    ann_block = "\n".join(annotations or []) + "\n" if annotations else ""
    f.write_text(
        f"package com.pichincha;\n\n"
        f"{ann_block}"
        f"public class {name} {{\n"
        f"    {body}\n"
        f"}}\n",
        encoding="utf-8",
    )
    return f


def test_block_16_passes_when_test_has_springboottest(tmp_path: Path) -> None:
    _make_test_class(tmp_path, "FooTest", annotations=["@SpringBootTest"])
    results = run_block_16(CheckContext(migrated_path=tmp_path, legacy_path=None))
    assert len(results) == 1
    assert results[0].status == "pass"
    assert results[0].id == "16.1"


def test_block_16_passes_with_extendwith(tmp_path: Path) -> None:
    _make_test_class(
        tmp_path,
        "UnitTest",
        annotations=["@ExtendWith(MockitoExtension.class)"],
    )
    results = run_block_16(CheckContext(migrated_path=tmp_path, legacy_path=None))
    assert results[0].status == "pass"


def test_block_16_passes_with_webfluxtest(tmp_path: Path) -> None:
    _make_test_class(tmp_path, "CtrlTest", annotations=["@WebFluxTest"])
    assert run_block_16(CheckContext(migrated_path=tmp_path, legacy_path=None))[0].status == "pass"


def test_block_16_fails_when_test_has_no_annotation(tmp_path: Path) -> None:
    _make_test_class(tmp_path, "PlainTest", annotations=[])
    results = run_block_16(CheckContext(migrated_path=tmp_path, legacy_path=None))
    assert results[0].status == "fail"
    assert results[0].severity == "medium"
    assert results[0].id == "16.1"
    assert "PlainTest.java" in results[0].detail


def test_block_16_reports_missing_count(tmp_path: Path) -> None:
    # 2 tests: 1 con anotacion, 1 sin
    _make_test_class(tmp_path, "OkTest", annotations=["@SpringBootTest"])
    _make_test_class(tmp_path, "BadTest", annotations=[])
    results = run_block_16(CheckContext(migrated_path=tmp_path, legacy_path=None))
    assert results[0].status == "fail"
    assert "1/2" in results[0].detail


def test_block_16_passes_when_no_test_dir(tmp_path: Path) -> None:
    results = run_block_16(CheckContext(migrated_path=tmp_path, legacy_path=None))
    assert results[0].status == "pass"
    assert "sin src/test" in results[0].detail


def test_block_16_ignores_non_test_files(tmp_path: Path) -> None:
    # Archivo en src/test que no se llame *Test.java (ej. helper)
    test_dir = tmp_path / "src" / "test" / "java"
    test_dir.mkdir(parents=True)
    (test_dir / "TestHelper.java").write_text(
        "package com.p;\npublic class TestHelper {}\n", encoding="utf-8"
    )
    results = run_block_16(CheckContext(migrated_path=tmp_path, legacy_path=None))
    # TestHelper.java no termina en Test.java/Tests.java -> ignorado
    assert results[0].status == "pass"


# ---------------------------------------------------------------------------
# Autofix fix_add_test_annotation
# ---------------------------------------------------------------------------


from capamedia_cli.core.autofix import (  # noqa: E402
    Violation,
)


def _violation() -> Violation:
    return Violation(
        check_id="16.1",
        severity="medium",
        file=Path("."),
        line=0,
        message="Falta anotacion test",
        evidence="",
    )


def test_autofix_adds_springboottest_when_spring_context(tmp_path: Path) -> None:
    """Si el test usa @Autowired/@MockBean, debe agregar @SpringBootTest."""
    test_dir = tmp_path / "src" / "test" / "java" / "com" / "p"
    test_dir.mkdir(parents=True)
    f = test_dir / "IntegrationTest.java"
    f.write_text(
        "package com.p;\n\n"
        "import org.springframework.beans.factory.annotation.Autowired;\n"
        "import org.junit.jupiter.api.Test;\n\n"
        "public class IntegrationTest {\n"
        "    @Autowired private Object svc;\n"
        "    @Test public void a() {}\n"
        "}\n",
        encoding="utf-8",
    )
    result = fix_add_test_annotation(tmp_path, _violation())
    assert result.applied
    updated = f.read_text(encoding="utf-8")
    assert "@SpringBootTest" in updated
    assert "import org.springframework.boot.test.context.SpringBootTest;" in updated


def test_autofix_uses_extendwith_for_unit_tests(tmp_path: Path) -> None:
    """Tests sin hints de Spring context deben usar @ExtendWith(MockitoExtension.class)."""
    test_dir = tmp_path / "src" / "test" / "java" / "com" / "p"
    test_dir.mkdir(parents=True)
    f = test_dir / "UnitTest.java"
    f.write_text(
        "package com.p;\n\n"
        "import org.junit.jupiter.api.Test;\n\n"
        "public class UnitTest {\n"
        "    @Test public void a() { int x = 1 + 1; }\n"
        "}\n",
        encoding="utf-8",
    )
    result = fix_add_test_annotation(tmp_path, _violation())
    assert result.applied
    updated = f.read_text(encoding="utf-8")
    assert "@ExtendWith(MockitoExtension.class)" in updated
    assert "import org.junit.jupiter.api.extension.ExtendWith;" in updated
    assert "import org.mockito.junit.jupiter.MockitoExtension;" in updated


def test_autofix_skips_if_already_annotated(tmp_path: Path) -> None:
    test_dir = tmp_path / "src" / "test" / "java" / "com" / "p"
    test_dir.mkdir(parents=True)
    f = test_dir / "OkTest.java"
    f.write_text(
        "package com.p;\n"
        "import org.springframework.boot.test.context.SpringBootTest;\n"
        "@SpringBootTest\n"
        "public class OkTest {\n}\n",
        encoding="utf-8",
    )
    result = fix_add_test_annotation(tmp_path, _violation())
    assert not result.applied


def test_autofix_no_test_dir_no_error(tmp_path: Path) -> None:
    result = fix_add_test_annotation(tmp_path, _violation())
    assert not result.applied
