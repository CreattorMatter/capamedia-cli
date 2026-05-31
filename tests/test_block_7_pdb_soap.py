"""Tests del check 7.5h (Regla 9h): SOAP requiere pdb.minAvailable=1 en values-dev.yml.

Aplica SOLO si ctx.project_type == 'soap'. REST (WebFlux y MVC) no necesitan
pdb explicito porque el scaffold MCP lo maneja cuando aplica. Origen: commit
9b670da del PromptCapaMedia (banco), 2026-04-23.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capamedia_cli.core.checklist_rules import CheckContext, run_block_7


def _mig_with_helm(tmp_path: Path, values_dev_body: str | None = None) -> Path:
    """Estructura minima con helm/values-dev.yml opcional."""
    root = tmp_path / "migrated"
    (root / "src" / "main" / "java").mkdir(parents=True)
    (root / "src" / "main" / "resources").mkdir(parents=True)
    # application.yml minimo (Block 7 lo lee para otros checks)
    (root / "src" / "main" / "resources" / "application.yml").write_text(
        "spring:\n"
        "  application:\n"
        "    name: tnd-msa-sp-test\n"
        "  header:\n"
        "    channel: digital\n"
        "    medium: web\n",
        encoding="utf-8",
    )
    helm = root / "helm"
    helm.mkdir()
    if values_dev_body is not None:
        (helm / "values-dev.yml").write_text(values_dev_body, encoding="utf-8")
    return root


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


# ---------------------------------------------------------------------------
# Caso PASS: SOAP + values-dev.yml con pdb.minAvailable=1
# ---------------------------------------------------------------------------


def test_check_75h_pass_when_soap_has_pdb_min_available_1(tmp_path: Path) -> None:
    root = _mig_with_helm(tmp_path,
        "container:\n"
        "  image: x\n"
        "pdb:\n"
        "  minAvailable: 1\n"
        "hpa:\n"
        "  minReplicas: 1\n"
        "  maxReplicas: 1\n"
        "  metrics:\n"
        "    - type: Resource\n"
        "      resource:\n"
        "        name: cpu\n"
        "        target:\n"
        "          type: AverageValue\n"
        "          averageValue: 100m\n"
        "resources:\n"
        "  requests:\n"
        "    cpu: 50m\n"
        "    memory: 100Mi\n"
        "  limits:\n"
        "    cpu: 200m\n"
        "    memory: 400Mi\n"
        "env:\n"
        "  - name: JAVA_OPTIONS\n"
        "    value: \"-XX:InitialRAMPercentage=70.0 -XX:MaxRAMPercentage=70.0 -XX:+UseStringDeduplication -XX:+UseG1GC\"\n",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None,
                       source_type="was", project_type="soap")
    r = _find(run_block_7(ctx), "7.5h")
    assert r is not None
    assert r.status == "pass"


# ---------------------------------------------------------------------------
# Caso HIGH: SOAP + values-dev.yml SIN bloque pdb
# ---------------------------------------------------------------------------


def test_check_75h_high_when_soap_missing_pdb(tmp_path: Path) -> None:
    root = _mig_with_helm(tmp_path,
        "container:\n"
        "  image: x\n"
        "hpa:\n"
        "  minReplicas: 1\n"
        "  maxReplicas: 1\n",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None,
                       source_type="was", project_type="soap")
    r = _find(run_block_7(ctx), "7.5h")
    assert r is not None
    assert r.status == "fail"
    assert r.severity == "high"
    assert "pdb" in r.detail.lower()


# ---------------------------------------------------------------------------
# Caso HIGH: SOAP + values-dev.yml con pdb.minAvailable distinto a 1
# ---------------------------------------------------------------------------


def test_check_75h_high_when_pdb_value_wrong(tmp_path: Path) -> None:
    root = _mig_with_helm(tmp_path,
        "pdb:\n"
        "  minAvailable: 2\n",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None,
                       source_type="was", project_type="soap")
    r = _find(run_block_7(ctx), "7.5h")
    assert r.status == "fail" and r.severity == "high"
    assert "minAvailable=2" in r.detail


# ---------------------------------------------------------------------------
# Caso HIGH: SOAP + sin values-dev.yml (solo values-prod.yml)
# ---------------------------------------------------------------------------


def test_check_75h_high_when_soap_lacks_values_dev_file(tmp_path: Path) -> None:
    root = _mig_with_helm(tmp_path, values_dev_body=None)  # sin values-dev.yml
    # Crear solo values-prod.yml
    (root / "helm" / "values-prod.yml").write_text(
        "pdb:\n  minAvailable: 1\n", encoding="utf-8",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None,
                       source_type="was", project_type="soap")
    r = _find(run_block_7(ctx), "7.5h")
    assert r.status == "fail" and r.severity == "high"
    assert "values-dev.yml" in r.detail


# ---------------------------------------------------------------------------
# Caso SKIP: REST (WebFlux o MVC) — el check 7.5h NO debe generarse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("project_type", ["rest", ""])
def test_check_75h_skip_for_rest(tmp_path: Path, project_type: str) -> None:
    """Para REST (WebFlux o MVC), el check 7.5h NO aplica — no se emite."""
    root = _mig_with_helm(tmp_path,
        "hpa:\n  minReplicas: 1\n  maxReplicas: 1\n",
    )
    ctx = CheckContext(migrated_path=root, legacy_path=None,
                       source_type="bus", project_type=project_type)
    r = _find(run_block_7(ctx), "7.5h")
    # 7.5h no debe estar en los resultados (skip silencioso por guard)
    assert r is None, f"7.5h NO debe generarse para project_type={project_type!r}, obtuvo: {r}"


# ---------------------------------------------------------------------------
# Smoke E2E: real sobre WSClientes0010 (WAS-SOAP)
# ---------------------------------------------------------------------------


def test_check_75h_real_was_0010_soap() -> None:
    """Smoke real sobre WSClientes0010 (WAS + spring-boot-starter-web-services).
    Debe detectar si tiene o no el bloque pdb."""
    real = Path("/Users/juliocesarsoriadiaz/Documentos/SmartSolutions/Banco Pichincha/Capa Media/lote-20260421/WSClientes0010/destino/tnd-msa-sp-wsclientes0010")
    if not real.is_dir():
        pytest.skip("0010 real no disponible")
    ctx = CheckContext(migrated_path=real, legacy_path=None,
                       source_type="was", project_type="soap")
    r = _find(run_block_7(ctx), "7.5h")
    # No imponemos pass/fail (depende del estado real del repo del banco) —
    # solo verificamos que el check se GENERA cuando aplica.
    assert r is not None, "7.5h debe generarse para WAS-SOAP real"
    assert r.id == "7.5h"
    # Reportar el estado real (informativo, no aserta valor concreto)
    print(f"\nEstado real 0010: {r.status} ({r.severity or 'pass'}) — {r.detail}")
