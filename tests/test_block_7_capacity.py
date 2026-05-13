"""Tests for Block 7 Helm capacity baseline (Banco Pichincha, 2026-05).

Cubre los 2 checks nuevos en run_block_7:
- 7.5d: hpa.minReplicas y maxReplicas deben ser 1 en los 3 helms -> HIGH
- 7.5e: resources.requests/limits con valores exactos del baseline -> HIGH

Tambien cubre el autofix fix_helm_capacity_baseline.

Fuente del baseline: mail Dario Simbaña, area de capacity Banco Pichincha,
2026-05. Reglas viejas tipo "replicaCount >= 2" derogadas.
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.bank_autofix import fix_helm_capacity_baseline
from capamedia_cli.core.checklist_rules import CheckContext, run_block_7


def _make_minimal_project(tmp_path: Path) -> Path:
    """Layout minimo con application.yml correcto + helm/ vacio."""
    root = tmp_path / "migrated"
    res = root / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "spring:\n  application:\n    name: tnd-msa-sp-wsclientes0011\n",
        encoding="utf-8",
    )
    (root / "helm").mkdir()
    return root


def _write_helm(root: Path, env: str, body: str) -> Path:
    f = root / "helm" / f"{env}.yml"
    f.write_text(body, encoding="utf-8")
    return f


def _baseline_helm() -> str:
    return """\
resources:
  requests:
    cpu: 50m
    memory: 350Mi
  limits:
    cpu: 200m
    memory: 500Mi

hpa:
  minReplicas: 1
  maxReplicas: 1
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: AverageValue
          averageValue: 100m
"""


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


# ---------------------------------------------------------------------------
# Check 7.5d — hpa.minReplicas / maxReplicas = 1
# ---------------------------------------------------------------------------


def test_7_5d_baseline_passes(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    for env in ("dev", "test", "prod"):
        _write_helm(root, env, _baseline_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5d")
    assert check is not None
    assert check.status == "pass"


def test_7_5d_replicaCount_2_in_prod_is_high(tmp_path: Path) -> None:
    """Regla vieja: replicaCount >= 2 en prod. Bug del banco: ahora es 1."""
    root = _make_minimal_project(tmp_path)
    for env in ("dev", "test"):
        _write_helm(root, env, _baseline_helm())
    # prod con maxReplicas = 2 (viejo)
    bad = _baseline_helm().replace("maxReplicas: 1", "maxReplicas: 2")
    _write_helm(root, "prod", bad)

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5d")
    assert check.status == "fail"
    assert check.severity == "high"
    assert "maxReplicas" in check.detail
    assert "prod" in check.detail


def test_7_5d_minReplicas_3_is_high(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_helm(root, "dev", _baseline_helm())
    bad = _baseline_helm().replace("minReplicas: 1", "minReplicas: 3")
    _write_helm(root, "test", bad)
    _write_helm(root, "prod", _baseline_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5d")
    assert check.status == "fail"


def test_7_5d_hpa_block_missing_min_max_is_high(tmp_path: Path) -> None:
    """Si declara hpa: pero no tiene min/max declarados, es bug."""
    root = _make_minimal_project(tmp_path)
    body = """\
resources:
  requests: { cpu: 50m, memory: 350Mi }
  limits: { cpu: 200m, memory: 500Mi }

hpa:
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: AverageValue
          averageValue: 100m
"""
    _write_helm(root, "dev", body)
    _write_helm(root, "test", _baseline_helm())
    _write_helm(root, "prod", _baseline_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5d")
    assert check.status == "fail"
    assert check.severity == "high"
    assert "no declarado" in check.detail


# ---------------------------------------------------------------------------
# Check 7.5e — resources.requests/limits baseline
# ---------------------------------------------------------------------------


def test_7_5e_baseline_passes(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    for env in ("dev", "test", "prod"):
        _write_helm(root, env, _baseline_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5e")
    assert check is not None
    assert check.status == "pass"


def test_7_5e_cpu_request_wrong_is_high(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    # dev con cpu request = 100m en vez de 50m
    bad = _baseline_helm().replace("cpu: 50m", "cpu: 100m")
    _write_helm(root, "dev", bad)
    _write_helm(root, "test", _baseline_helm())
    _write_helm(root, "prod", _baseline_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5e")
    assert check.status == "fail"
    assert check.severity == "high"
    assert "requests.cpu" in check.detail
    assert "100m" in check.detail


def test_7_5e_memory_limit_wrong_is_high(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_helm(root, "dev", _baseline_helm())
    _write_helm(root, "test", _baseline_helm())
    bad = _baseline_helm().replace("memory: 500Mi", "memory: 1Gi")
    _write_helm(root, "prod", bad)

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5e")
    assert check.status == "fail"
    assert "limits.memory" in check.detail


def test_7_5e_no_resources_block_skips_silently(tmp_path: Path) -> None:
    """Si el helm no declara resources:, skip (puede declararse en values base)."""
    root = _make_minimal_project(tmp_path)
    minimal = "hpa:\n  minReplicas: 1\n  maxReplicas: 1\n"
    _write_helm(root, "dev", minimal)
    _write_helm(root, "test", minimal)
    _write_helm(root, "prod", minimal)

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5e")
    assert check is not None
    assert check.status == "pass"


# ---------------------------------------------------------------------------
# Autofix fix_helm_capacity_baseline
# ---------------------------------------------------------------------------


def test_autofix_replaces_maxReplicas_2_to_1(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    f = _write_helm(
        root, "prod", _baseline_helm().replace("maxReplicas: 1", "maxReplicas: 2")
    )

    result = fix_helm_capacity_baseline(root)
    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    assert "maxReplicas: 1" in text
    assert "maxReplicas: 2" not in text


def test_autofix_replaces_minReplicas_3_to_1(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    f = _write_helm(
        root, "test", _baseline_helm().replace("minReplicas: 1", "minReplicas: 3")
    )

    result = fix_helm_capacity_baseline(root)
    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    assert "minReplicas: 1" in text


def test_autofix_replaces_cpu_request(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    f = _write_helm(
        root, "dev", _baseline_helm().replace("cpu: 50m", "cpu: 100m")
    )

    result = fix_helm_capacity_baseline(root)
    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    # El cpu del request bajo `requests:` debe quedar en 50m
    assert "cpu: 50m" in text
    # El cpu del limit bajo `limits:` debe seguir en 200m
    assert "cpu: 200m" in text


def test_autofix_replaces_memory_limit(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    f = _write_helm(
        root, "prod", _baseline_helm().replace("memory: 500Mi", "memory: 1Gi")
    )

    result = fix_helm_capacity_baseline(root)
    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    assert "memory: 500Mi" in text
    assert "memory: 1Gi" not in text
    # El memory del request debe quedar en 350Mi
    assert "memory: 350Mi" in text


def test_autofix_idempotent(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_helm(root, "dev", _baseline_helm())
    _write_helm(root, "test", _baseline_helm())
    _write_helm(root, "prod", _baseline_helm())

    first = fix_helm_capacity_baseline(root)
    second = fix_helm_capacity_baseline(root)

    assert first.applied is False  # Ya estaba alineado
    assert second.applied is False


def test_autofix_no_helm_dir(tmp_path: Path) -> None:
    root = tmp_path / "no-helm"
    root.mkdir()
    result = fix_helm_capacity_baseline(root)
    assert result.applied is False
    assert "no existe" in result.notes


def test_autofix_does_not_inject_missing_min_max(tmp_path: Path) -> None:
    """Si helm declara hpa: pero NO tiene min/max, el autofix NO los inyecta.
    El bug se reporta como handoff manual (formato de bloque incompleto).
    """
    root = _make_minimal_project(tmp_path)
    body = "hpa:\n  metrics: []\n"
    f = _write_helm(root, "dev", body)
    original = f.read_text(encoding="utf-8")

    result = fix_helm_capacity_baseline(root)
    assert result.applied is False
    assert f.read_text(encoding="utf-8") == original
