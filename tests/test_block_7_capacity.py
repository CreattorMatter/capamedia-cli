"""Tests for Block 7 Helm capacity + KEDA baseline (Banco Pichincha).

Cubre los checks de capacity/autoscaling en run_block_7:
- 7.4:  bloque `hpa:` presente (derogado 2026-07) -> HIGH
- 7.5d: `keda:` habilitado (enabled/minReplicaCount/maxReplicaCount/triggers) -> HIGH
- 7.5e: resources.requests/limits con valores exactos del baseline -> HIGH
- 7.5g: `servicemonitor:` con enabled:true y path /actuator/prometheus -> HIGH

Tambien cubre el autofix fix_helm_capacity_baseline (reescribe resources y
elimina el bloque hpa derogado; NO inyecta keda/servicemonitor).

Fuente del baseline: capacity Banco Pichincha. Ajuste 2026-07: HPA derogado, el
autoscaling pasa a KEDA + ServiceMonitor Prometheus.
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
    """Baseline 2026-07: resources + KEDA + servicemonitor, sin hpa."""
    return """\
resources:
  requests:
    cpu: 50m
    memory: 100Mi
  limits:
    cpu: 200m
    memory: 400Mi

keda:
  enabled: true
  minReplicaCount: 1
  maxReplicaCount: 1
  triggers:
    - authenticationRef:
        kind: ClusterTriggerAuthentication
        name: keda-trigger-auth-prometheus
      metadata:
        authModes: bearer
        metricName: http_server_requests_seconds_count
        namespace: tnd-middleware
        query: 'sum(rate(http_server_requests_seconds_count{job="service-tnd-msa-sp-wsclientes0011"}[1m]))'
        serverAddress: 'https://thanos-querier.openshift-monitoring.svc.cluster.local:9092'
        threshold: '5'
      type: prometheus
  fallback:
    failureThreshold: 3
    replicas: 1
servicemonitor:
  enabled: true
  path: '/actuator/prometheus'
"""


def _hpa_helm() -> str:
    """Helm legacy con hpa (derogado) — debe fallar 7.4 y 7.5d/7.5g."""
    return """\
resources:
  requests:
    cpu: 50m
    memory: 100Mi
  limits:
    cpu: 200m
    memory: 400Mi

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
# Check 7.4 — HPA derogado (KEDA)
# ---------------------------------------------------------------------------


def test_7_4_no_hpa_passes(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    for env in ("dev", "test", "prod"):
        _write_helm(root, env, _baseline_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.4")
    assert check is not None
    assert check.status == "pass"


def test_7_4_hpa_present_is_high(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_helm(root, "dev", _baseline_helm())
    _write_helm(root, "test", _baseline_helm())
    _write_helm(root, "prod", _hpa_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.4")
    assert check.status == "fail"
    assert check.severity == "high"
    assert "hpa" in check.detail.lower()
    assert "prod" in check.detail


# ---------------------------------------------------------------------------
# Check 7.5d — KEDA habilitado
# ---------------------------------------------------------------------------


def test_7_5d_keda_baseline_passes(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    for env in ("dev", "test", "prod"):
        _write_helm(root, env, _baseline_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5d")
    assert check is not None
    assert check.status == "pass"


def test_7_5d_keda_missing_is_high(tmp_path: Path) -> None:
    """Un helm sin bloque keda: -> HIGH."""
    root = _make_minimal_project(tmp_path)
    _write_helm(root, "dev", _baseline_helm())
    _write_helm(root, "test", _baseline_helm())
    _write_helm(root, "prod", _hpa_helm())  # sin keda

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5d")
    assert check.status == "fail"
    assert check.severity == "high"
    assert "keda" in check.detail.lower()
    assert "prod" in check.detail


def test_7_5d_keda_not_enabled_is_high(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    bad = _baseline_helm().replace("enabled: true\n  minReplicaCount", "enabled: false\n  minReplicaCount")
    _write_helm(root, "dev", bad)
    _write_helm(root, "test", _baseline_helm())
    _write_helm(root, "prod", _baseline_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5d")
    assert check.status == "fail"
    assert "enabled" in check.detail.lower()


def test_7_5d_keda_missing_max_replica_is_high(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    bad = _baseline_helm().replace("  maxReplicaCount: 1\n", "")
    _write_helm(root, "dev", bad)
    _write_helm(root, "test", _baseline_helm())
    _write_helm(root, "prod", _baseline_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5d")
    assert check.status == "fail"
    assert "maxReplicaCount" in check.detail


# ---------------------------------------------------------------------------
# Check 7.5g — ServiceMonitor Prometheus
# ---------------------------------------------------------------------------


def test_7_5g_servicemonitor_baseline_passes(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    for env in ("dev", "test", "prod"):
        _write_helm(root, env, _baseline_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5g")
    assert check is not None
    assert check.status == "pass"


def test_7_5g_servicemonitor_missing_is_high(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_helm(root, "dev", _baseline_helm())
    _write_helm(root, "test", _baseline_helm())
    _write_helm(root, "prod", _hpa_helm())  # sin servicemonitor

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5g")
    assert check.status == "fail"
    assert check.severity == "high"
    assert "servicemonitor" in check.detail.lower()


def test_7_5g_wrong_path_is_high(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    bad = _baseline_helm().replace("/actuator/prometheus", "/metrics")
    _write_helm(root, "dev", bad)
    _write_helm(root, "test", _baseline_helm())
    _write_helm(root, "prod", _baseline_helm())

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5g")
    assert check.status == "fail"
    assert "path" in check.detail.lower()


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
    bad = _baseline_helm().replace("memory: 400Mi", "memory: 1Gi")
    _write_helm(root, "prod", bad)

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_7(ctx)
    check = _find(results, "7.5e")
    assert check.status == "fail"
    assert "limits.memory" in check.detail


def test_7_5e_no_resources_block_skips_silently(tmp_path: Path) -> None:
    """Si el helm no declara resources:, skip (puede declararse en values base)."""
    root = _make_minimal_project(tmp_path)
    minimal = (
        "keda:\n  enabled: true\n  minReplicaCount: 1\n  maxReplicaCount: 1\n"
        "  triggers:\n    - type: prometheus\n"
        "servicemonitor:\n  enabled: true\n  path: '/actuator/prometheus'\n"
    )
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


def test_autofix_removes_hpa_block(tmp_path: Path) -> None:
    """El bloque hpa: derogado se elimina; resources/keda intactos."""
    root = _make_minimal_project(tmp_path)
    # baseline con keda + un hpa legacy pegado abajo
    body = _baseline_helm() + "\nhpa:\n  minReplicas: 1\n  maxReplicas: 2\n"
    f = _write_helm(root, "prod", body)

    result = fix_helm_capacity_baseline(root)
    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    assert "hpa:" not in text
    assert "minReplicas" not in text
    # keda y resources se conservan
    assert "keda:" in text
    assert "cpu: 50m" in text


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
        root, "prod", _baseline_helm().replace("memory: 400Mi", "memory: 1Gi")
    )

    result = fix_helm_capacity_baseline(root)
    assert result.applied is True
    text = f.read_text(encoding="utf-8")
    assert "memory: 400Mi" in text
    assert "memory: 1Gi" not in text
    # El memory del request debe quedar en 100Mi
    assert "memory: 100Mi" in text


def test_autofix_idempotent(tmp_path: Path) -> None:
    root = _make_minimal_project(tmp_path)
    _write_helm(root, "dev", _baseline_helm())
    _write_helm(root, "test", _baseline_helm())
    _write_helm(root, "prod", _baseline_helm())

    first = fix_helm_capacity_baseline(root)
    second = fix_helm_capacity_baseline(root)

    assert first.applied is False  # Ya estaba alineado (sin hpa, resources ok)
    assert second.applied is False


def test_autofix_no_helm_dir(tmp_path: Path) -> None:
    root = tmp_path / "no-helm"
    root.mkdir()
    result = fix_helm_capacity_baseline(root)
    assert result.applied is False
    assert "no existe" in result.notes
