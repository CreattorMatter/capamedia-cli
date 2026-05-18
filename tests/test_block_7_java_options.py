"""Tests for Block 7 Helm env JAVA_OPTIONS baseline (Banco Pichincha, 2026-05).

Cubre el check nuevo 7.5f en run_block_7:
- env var JAVA_OPTIONS no declarada -> HIGH
- value: difiere del baseline (cualquier flag faltante / extra / cambiado) -> HIGH
- 3 helms con baseline exacto -> PASS

Tambien cubre el autofix fix_helm_java_options.

Fuente: mail Alexis Padilla (Kyndryl) / capacity Banco Pichincha 2026-05.
Valor exacto:
  -XX:InitialRAMPercentage=70.0 -XX:MaxRAMPercentage=70.0
  -XX:+UseStringDeduplication -XX:+UseG1GC
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.bank_autofix import fix_helm_java_options
from capamedia_cli.core.checklist_rules import (
    HELM_JAVA_OPTIONS_BASELINE,
    CheckContext,
    run_block_7,
)


def _make_minimal_project(tmp_path: Path) -> Path:
    root = tmp_path / "migrated"
    res = root / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "spring:\n  application:\n    name: tnd-msa-sp-wsclientes0011\n",
        encoding="utf-8",
    )
    (root / "helm").mkdir()
    return root


def _baseline_helm_with_java_opts() -> str:
    return f"""\
resources:
  requests: {{ cpu: 50m, memory: 350Mi }}
  limits: {{ cpu: 200m, memory: 500Mi }}

hpa:
  minReplicas: 1
  maxReplicas: 1

env:
  - name: "JAVA_OPTIONS"
    value: "{HELM_JAVA_OPTIONS_BASELINE}"
"""


def _write_helm(root: Path, env: str, body: str) -> Path:
    f = root / "helm" / f"{env}.yml"
    f.write_text(body, encoding="utf-8")
    return f


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


# ---------------------------------------------------------------------------
# Check 7.5f
# ---------------------------------------------------------------------------


def test_7_5f_baseline_in_3_helms_passes(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    for env in ("dev", "test", "prod"):
        _write_helm(root, env, _baseline_helm_with_java_opts())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5f")
    assert check is not None
    assert check.status == "pass"


def test_7_5f_missing_java_options_is_high(tmp_path: Path) -> None:
    """Si algun helm no declara JAVA_OPTIONS -> HIGH."""
    root = _make_minimal_project(tmp_path)
    _write_helm(root, "dev", _baseline_helm_with_java_opts())
    _write_helm(root, "test", _baseline_helm_with_java_opts())
    # prod sin JAVA_OPTIONS
    _write_helm(
        root,
        "prod",
        """\
resources:
  requests: { cpu: 50m, memory: 350Mi }
  limits: { cpu: 200m, memory: 500Mi }
hpa:
  minReplicas: 1
  maxReplicas: 1
env:
  - name: "OTHER_VAR"
    value: "x"
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5f")
    assert check.status == "fail"
    assert check.severity == "high"
    assert "no declarada" in check.detail
    assert "prod" in check.detail


def test_7_5f_wrong_value_is_high(tmp_path: Path) -> None:
    """JAVA_OPTIONS con un flag distinto al baseline -> HIGH."""
    root = _make_minimal_project(tmp_path)
    bad = _baseline_helm_with_java_opts().replace(
        "-XX:MaxRAMPercentage=70.0", "-XX:MaxRAMPercentage=80.0"
    )
    _write_helm(root, "dev", bad)
    _write_helm(root, "test", _baseline_helm_with_java_opts())
    _write_helm(root, "prod", _baseline_helm_with_java_opts())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5f")
    assert check.status == "fail"
    assert check.severity == "high"
    assert "value" in check.detail.lower()


def test_7_5f_missing_flag_is_high(tmp_path: Path) -> None:
    """JAVA_OPTIONS sin uno de los flags del baseline -> HIGH."""
    root = _make_minimal_project(tmp_path)
    bad = _baseline_helm_with_java_opts().replace(
        " -XX:+UseStringDeduplication", ""
    )
    _write_helm(root, "dev", _baseline_helm_with_java_opts())
    _write_helm(root, "test", bad)
    _write_helm(root, "prod", _baseline_helm_with_java_opts())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5f")
    assert check.status == "fail"


def test_7_5f_flag_order_does_not_matter(tmp_path: Path) -> None:
    """Si los 4 flags estan presentes pero en otro orden -> PASS (es un set)."""
    root = _make_minimal_project(tmp_path)
    reordered_body = """\
env:
  - name: "JAVA_OPTIONS"
    value: "-XX:+UseG1GC -XX:+UseStringDeduplication -XX:MaxRAMPercentage=70.0 -XX:InitialRAMPercentage=70.0"
"""
    for env in ("dev", "test", "prod"):
        _write_helm(root, env, reordered_body)

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5f")
    assert check.status == "pass"


def test_7_5f_non_breaking_space_is_high(tmp_path: Path) -> None:
    """U+00A0 parece espacio, pero OpenShift/Java no lo separa como flag."""
    root = _make_minimal_project(tmp_path)
    bad_value = HELM_JAVA_OPTIONS_BASELINE.replace(
        " -XX:MaxRAMPercentage", "\u00a0-XX:MaxRAMPercentage"
    )
    body = f"""\
env:
  - name: "JAVA_OPTIONS"
    value: "{bad_value}"
"""
    _write_helm(root, "dev", body)
    _write_helm(root, "test", _baseline_helm_with_java_opts())
    _write_helm(root, "prod", _baseline_helm_with_java_opts())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5f")
    assert check.status == "fail"
    assert check.severity == "high"
    assert "U+00A0" in check.detail


def test_7_5f_skips_when_no_helm_dir(tmp_path: Path) -> None:
    """Si no hay helm/, el check no se emite."""
    root = _make_minimal_project(tmp_path)
    # Borrar helm/ vacio
    (root / "helm").rmdir()
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    assert _find(results, "7.5f") is None


# ---------------------------------------------------------------------------
# Autofix fix_helm_java_options
# ---------------------------------------------------------------------------


def test_autofix_replaces_wrong_value(tmp_path: Path) -> None:
    """Si JAVA_OPTIONS existe con valor distinto -> autofix lo reemplaza."""
    root = _make_minimal_project(tmp_path)
    f = _write_helm(
        root,
        "dev",
        _baseline_helm_with_java_opts().replace(
            "-XX:MaxRAMPercentage=70.0", "-XX:MaxRAMPercentage=80.0"
        ),
    )

    result = fix_helm_java_options(root)
    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    assert HELM_JAVA_OPTIONS_BASELINE in text
    assert "-XX:MaxRAMPercentage=80.0" not in text


def test_autofix_replaces_missing_flag(tmp_path: Path) -> None:
    """Si JAVA_OPTIONS existe pero falta un flag -> autofix lo restablece."""
    root = _make_minimal_project(tmp_path)
    f = _write_helm(
        root,
        "prod",
        _baseline_helm_with_java_opts().replace(
            " -XX:+UseStringDeduplication", ""
        ),
    )

    result = fix_helm_java_options(root)
    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    assert "-XX:+UseStringDeduplication" in text


def test_autofix_replaces_non_breaking_space(tmp_path: Path) -> None:
    """Si JAVA_OPTIONS tiene U+00A0, el autofix reescribe con espacios ASCII."""
    root = _make_minimal_project(tmp_path)
    bad_value = HELM_JAVA_OPTIONS_BASELINE.replace(
        " -XX:MaxRAMPercentage", "\u00a0-XX:MaxRAMPercentage"
    )
    f = _write_helm(
        root,
        "dev",
        f"""\
env:
  - name: "JAVA_OPTIONS"
    value: "{bad_value}"
""",
    )

    result = fix_helm_java_options(root)
    text = f.read_text(encoding="utf-8")
    assert result.applied is True
    assert "\u00a0" not in text
    assert HELM_JAVA_OPTIONS_BASELINE in text


def test_autofix_does_NOT_inject_when_missing(tmp_path: Path) -> None:
    """Si JAVA_OPTIONS no esta declarada -> autofix NO la inyecta (handoff manual)."""
    root = _make_minimal_project(tmp_path)
    body = """\
env:
  - name: "OTHER_VAR"
    value: "x"
"""
    f = _write_helm(root, "dev", body)
    original = f.read_text(encoding="utf-8")

    result = fix_helm_java_options(root)
    assert result.applied is False
    assert f.read_text(encoding="utf-8") == original


def test_autofix_idempotent(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_helm(root, "dev", _baseline_helm_with_java_opts())
    _write_helm(root, "test", _baseline_helm_with_java_opts())
    _write_helm(root, "prod", _baseline_helm_with_java_opts())

    first = fix_helm_java_options(root)
    second = fix_helm_java_options(root)

    assert first.applied is False  # Ya estaba alineado
    assert second.applied is False


def test_autofix_no_helm_dir(tmp_path: Path) -> None:
    root = tmp_path / "no-helm"
    root.mkdir()
    result = fix_helm_java_options(root)
    assert result.applied is False


def test_autofix_preserves_other_env_vars(tmp_path: Path) -> None:
    """El autofix solo toca el value de JAVA_OPTIONS — otras env vars intactas."""
    root = _make_minimal_project(tmp_path)
    body = (
        'env:\n'
        '  - name: "CCC_BANCS_BASE_URL"\n'
        '    value: "https://bancs.example.com"\n'
        '  - name: "JAVA_OPTIONS"\n'
        '    value: "-XX:MaxRAMPercentage=80.0"\n'
        '  - name: "CCC_OTHER"\n'
        '    value: "z"\n'
    )
    f = _write_helm(root, "dev", body)

    result = fix_helm_java_options(root)
    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    # JAVA_OPTIONS alineado
    assert HELM_JAVA_OPTIONS_BASELINE in text
    # Otras env vars intactas
    assert 'CCC_BANCS_BASE_URL' in text
    assert 'https://bancs.example.com' in text
    assert 'CCC_OTHER' in text
    assert '"z"' in text
