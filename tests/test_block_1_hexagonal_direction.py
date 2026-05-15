"""Tests for Block 1 hexagonal dependency direction checks.

Cubre:
- Check 1.3c ampliado: detecta tambien output ports implementados por archivos
  en `infrastructure/config/**` (caso TransactionMetadataPort en wstecnicos0008).
- Check 1.7: clases bajo `infrastructure/input/**` no deben inyectar output ports.

Origen: peer-review wstecnicos0008 branch feature/dev-BTHCCC-5954 (2026-05).
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import CheckContext, run_block_1


def _make_minimal_project(tmp_path: Path) -> Path:
    """Layout hexagonal canonico minimo para tests."""
    root = tmp_path / "migrated"
    base = root / "src" / "main" / "java" / "com" / "pichincha" / "sp"
    for sub in (
        "application/input/port",
        "application/output/port",
        "application/service",
        "domain/model",
        "infrastructure/input/adapter/soap/helper",
        "infrastructure/input/adapter/soap/impl",
        "infrastructure/output/adapter/bancs",
        "infrastructure/config",
    ):
        (base / sub).mkdir(parents=True)
    return root


def _write_java(root: Path, relative: str, body: str) -> Path:
    f = root / "src" / "main" / "java" / "com" / "pichincha" / "sp" / relative
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    return f


def _find(results, check_id):
    return next((r for r in results if r.id == check_id), None)


# ---------------------------------------------------------------------------
# Check 1.7 — output ports inyectados en infrastructure/input/
# ---------------------------------------------------------------------------


def test_1_7_helper_inyecta_output_port_is_high(tmp_path: Path) -> None:
    """Caso exacto wstecnicos0008: SoapResponseHelper inyecta TransactionMetadataPort."""
    root = _make_minimal_project(tmp_path)
    _write_java(
        root,
        "application/output/port/TransactionMetadataPort.java",
        "package com.pichincha.sp.application.output.port;\npublic interface TransactionMetadataPort {}\n",
    )
    _write_java(
        root,
        "infrastructure/input/adapter/soap/helper/SoapResponseHelper.java",
        """\
package com.pichincha.sp.infrastructure.input.adapter.soap.helper;
import com.pichincha.sp.application.output.port.TransactionMetadataPort;
import org.springframework.stereotype.Component;
@Component
public class SoapResponseHelper {
  private final TransactionMetadataPort transactionMetadata;
  public SoapResponseHelper(TransactionMetadataPort transactionMetadata) {
    this.transactionMetadata = transactionMetadata;
  }
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = _find(results, "1.7")

    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"
    assert "TransactionMetadataPort" in check.detail


def test_1_7_controller_inyecta_input_port_passes(tmp_path: Path) -> None:
    """Controller inyectando InputPort -> OK (es el flujo correcto)."""
    root = _make_minimal_project(tmp_path)
    _write_java(
        root,
        "application/input/port/CustomerServicePort.java",
        "package com.pichincha.sp.application.input.port;\npublic interface CustomerServicePort {}\n",
    )
    _write_java(
        root,
        "infrastructure/input/adapter/soap/impl/CustomerController.java",
        """\
package com.pichincha.sp.infrastructure.input.adapter.soap.impl;
import com.pichincha.sp.application.input.port.CustomerServicePort;
public class CustomerController {
  private final CustomerServicePort customerService;
  public CustomerController(CustomerServicePort customerService) {
    this.customerService = customerService;
  }
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = _find(results, "1.7")

    assert check.status == "pass"


def test_1_7_output_adapter_implements_port_passes(tmp_path: Path) -> None:
    """Output adapter implementando output port -> OK (es su rol)."""
    root = _make_minimal_project(tmp_path)
    _write_java(
        root,
        "application/output/port/CustomerBancsPort.java",
        "package com.pichincha.sp.application.output.port;\npublic interface CustomerBancsPort {}\n",
    )
    _write_java(
        root,
        "infrastructure/output/adapter/bancs/CustomerBancsAdapter.java",
        """\
package com.pichincha.sp.infrastructure.output.adapter.bancs;
import com.pichincha.sp.application.output.port.CustomerBancsPort;
public class CustomerBancsAdapter implements CustomerBancsPort {}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = _find(results, "1.7")

    assert check.status == "pass"


def test_1_7_only_import_no_field_passes(tmp_path: Path) -> None:
    """Si el archivo solo IMPORTA un output port pero no lo inyecta -> OK.
    (Caso: el archivo solo usa el port como tipo en un metodo helper estatico
    que recibe el valor como parametro, no como campo inyectado.)"""
    root = _make_minimal_project(tmp_path)
    _write_java(
        root,
        "application/output/port/SomePort.java",
        "package com.pichincha.sp.application.output.port;\npublic interface SomePort {}\n",
    )
    _write_java(
        root,
        "infrastructure/input/adapter/soap/util/SomeMapper.java",
        """\
package com.pichincha.sp.infrastructure.input.adapter.soap.util;
// import declarado pero el port no se inyecta — solo se referencia como tipo
// en algun method param que el caller pasa.
public class SomeMapper {
  public static void mapNothing() {}
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = _find(results, "1.7")
    assert check.status == "pass"


def test_1_7_no_output_ports_in_project_passes(tmp_path: Path) -> None:
    """Sin output ports en application/, el check pasa vacuously."""
    root = _make_minimal_project(tmp_path)
    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = _find(results, "1.7")
    assert check is not None
    assert check.status == "pass"


# ---------------------------------------------------------------------------
# Check 1.3c — ampliacion: port implementado por archivo en infra/config/
# ---------------------------------------------------------------------------


def test_1_3c_port_implemented_in_infra_config_is_high(tmp_path: Path) -> None:
    """Caso exacto wstecnicos0008: TransactionMetadataProperties (en
    infrastructure/config/) implementa TransactionMetadataPort.
    El sufijo NO es 'ConfigOutputPort' — la heuristica vieja no lo atraparia.
    """
    root = _make_minimal_project(tmp_path)
    _write_java(
        root,
        "application/output/port/TransactionMetadataPort.java",
        "package com.pichincha.sp.application.output.port;\npublic interface TransactionMetadataPort {}\n",
    )
    _write_java(
        root,
        "infrastructure/config/TransactionMetadataProperties.java",
        """\
package com.pichincha.sp.infrastructure.config;
import com.pichincha.sp.application.output.port.TransactionMetadataPort;
import org.springframework.boot.context.properties.ConfigurationProperties;
@ConfigurationProperties(prefix = "transaction")
public class TransactionMetadataProperties implements TransactionMetadataPort {}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = _find(results, "1.3c")

    assert check is not None
    assert check.status == "fail"
    assert check.severity == "high"
    assert "TransactionMetadataProperties" in check.detail


def test_1_3c_legacy_ConfigOutputPort_still_detected(tmp_path: Path) -> None:
    """La heuristica vieja (por nombre *ConfigOutputPort) sigue funcionando."""
    root = _make_minimal_project(tmp_path)
    _write_java(
        root,
        "application/output/port/AppConfigOutputPort.java",
        "package com.pichincha.sp.application.output.port;\npublic interface AppConfigOutputPort {}\n",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = _find(results, "1.3c")

    assert check.status == "fail"
    assert check.severity == "high"


def test_1_3c_normal_config_class_in_infra_config_passes(tmp_path: Path) -> None:
    """Una clase normal en infrastructure/config/ que NO implementa ningun port
    -> OK. La heuristica solo flaggea si hay implements *Port."""
    root = _make_minimal_project(tmp_path)
    _write_java(
        root,
        "infrastructure/config/BancsErrorCodesProperties.java",
        """\
package com.pichincha.sp.infrastructure.config;
import org.springframework.boot.context.properties.ConfigurationProperties;
@ConfigurationProperties(prefix = "bancs.error-codes")
public class BancsErrorCodesProperties {
  private String iib;
  public String getIib() { return iib; }
  public void setIib(String iib) { this.iib = iib; }
}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = _find(results, "1.3c")
    assert check.status == "pass"


def test_1_3c_output_adapter_implements_port_passes(tmp_path: Path) -> None:
    """Un adapter en infrastructure/output/adapter/ implementa un port -> OK
    (es su rol). El check 1.3c solo flaggea infra/config/."""
    root = _make_minimal_project(tmp_path)
    _write_java(
        root,
        "application/output/port/CustomerPort.java",
        "package com.pichincha.sp.application.output.port;\npublic interface CustomerPort {}\n",
    )
    _write_java(
        root,
        "infrastructure/output/adapter/bancs/CustomerAdapter.java",
        """\
package com.pichincha.sp.infrastructure.output.adapter.bancs;
import com.pichincha.sp.application.output.port.CustomerPort;
public class CustomerAdapter implements CustomerPort {}
""",
    )

    ctx = CheckContext(migrated_path=root, legacy_path=None)
    results = run_block_1(ctx)
    check = _find(results, "1.3c")
    assert check.status == "pass"
