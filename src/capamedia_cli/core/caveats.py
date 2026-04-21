"""Detector de caveats — situaciones que requieren intervencion manual.

Un caveat es algo que el CLI puede detectar pero NO resolver automaticamente:
- UMP que no se pudo clonar (404, archivado, otro proyecto Azure)
- TX no extraible del ESQL (vive en config externa)
- Invocaciones non-BANCS (DataPower, WSO2, externos)
- Endpoints externos al banco (Equifax, SRI, providers)
- Para ORQ: dependencias (servicios delegados) que no estan migradas todavia
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Patrones para detectar invocaciones non-BANCS y endpoints externos
RE_HTTP_REQUEST = re.compile(r"<(?:nc|node|wsdl|HTTPRequest)[^>]*HTTPRequest", re.IGNORECASE)
RE_EXTERNAL_URL = re.compile(r'https?://([^/"\s]+)', re.IGNORECASE)
RE_BANK_DOMAIN = re.compile(r"(bpichincha|pichincha\.com|bancsubsider)", re.IGNORECASE)
RE_ET_BANCS = re.compile(r"\bet_bancs\b")
RE_ET_SOAP = re.compile(r"\bet_soap\b")
RE_DELEGATION = re.compile(r"(IniciarOrquestacionSOAP|WSClientes\d+|WSCuentas\d+|ORQ\w+\d+)")


@dataclass
class Caveat:
    """Un hallazgo que requiere atencion manual."""

    kind: str  # "ump_not_cloned" | "tx_not_extracted" | "non_bancs_call" | "external_endpoint" | "orq_dep_missing"
    target: str  # nombre del UMP, URL, servicio, etc.
    detail: str
    suggested_action: str
    evidence: str = ""  # archivo + linea cuando aplique


def detect_ump_caveats(analysis) -> list[Caveat]:
    """Caveats derivados de UMPs no clonables o sin TX."""
    caveats: list[Caveat] = []
    for ump in analysis.umps:
        if ump.repo_path is None:
            caveats.append(
                Caveat(
                    kind="ump_not_cloned",
                    target=ump.name,
                    detail="Repo no encontrado en tpl-bus-omnicanal (404)",
                    suggested_action=(
                        f"Verificar si vive en otro proyecto Azure (tpl-middleware, "
                        f"tpl-integrationbus-config) o si fue archivado. Comando manual: "
                        f"git clone https://dev.azure.com/BancoPichinchaEC/<proyecto>/_git/sqb-msa-{ump.name.lower()}"
                    ),
                )
            )
        elif not ump.tx_codes:
            caveats.append(
                Caveat(
                    kind="tx_not_extracted",
                    target=ump.name,
                    detail="UMP clonado pero el ESQL no expone el TX literal",
                    suggested_action=(
                        f"Buscar en {ump.repo_path}/deploy-*-config.bat o pedir el TX al equipo. "
                        f"Tambien revisar Environment.cache.<UMP>Config en el ESQL — el TX puede estar"
                        f" en la URL de configuracion externa."
                    ),
                )
            )
    return caveats


def detect_non_bancs_caveats(legacy_root: Path) -> list[Caveat]:
    """Detecta invocaciones non-BANCS en ESQL/msgflow."""
    caveats: list[Caveat] = []
    for f in list(legacy_root.rglob("*.esql")) + list(legacy_root.rglob("*.msgflow")):
        if ".git" in f.parts:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if RE_ET_SOAP.search(line):
                caveats.append(
                    Caveat(
                        kind="non_bancs_call",
                        target="et_soap (SOAP externo)",
                        detail="Label et_soap detectado: invocacion SOAP a servicio NO BANCS",
                        suggested_action=(
                            "Revisar el target del SOAP (DataPower? WSO2? otro WAS?). "
                            "Generar adapter dedicado en infrastructure/output/adapter/<backend>/"
                        ),
                        evidence=f"{f.relative_to(legacy_root)}:{i}",
                    )
                )
                break  # Un caveat por archivo es suficiente
    return caveats


def detect_external_endpoints(legacy_root: Path) -> list[Caveat]:
    """Detecta URLs HTTP que NO son del banco."""
    caveats: list[Caveat] = []
    seen_domains: set[str] = set()
    for f in legacy_root.rglob("*.esql"):
        if ".git" in f.parts:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for url_match in RE_EXTERNAL_URL.finditer(text):
            domain = url_match.group(1)
            if RE_BANK_DOMAIN.search(domain):
                continue  # es del banco, no es externo
            if "localhost" in domain or domain.startswith("127.") or domain.startswith("10."):
                continue  # red interna, no es externo
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            caveats.append(
                Caveat(
                    kind="external_endpoint",
                    target=domain,
                    detail=f"URL externa al banco detectada: {domain}",
                    suggested_action=(
                        f"Es un proveedor de 3ros. Generar adapter HTTP dedicado en "
                        f"infrastructure/output/adapter/external/{domain.split('.')[0]}/. "
                        f"Backend code segun catalogo (00999 si no hay)."
                    ),
                    evidence=str(f.relative_to(legacy_root)),
                )
            )
    return caveats


def detect_orq_dependencies(legacy_root: Path, service_name: str) -> tuple[list[str], bool]:
    """Para servicios ORQ, detecta los servicios delegados.

    Returns: (lista_de_servicios_delegados, es_orq).
    """
    deps: set[str] = set()
    is_orq = service_name.lower().startswith("orq")
    for f in list(legacy_root.rglob("*.esql")) + list(legacy_root.rglob("*.msgflow")):
        if ".git" in f.parts:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "IniciarOrquestacionSOAP" in text:
            is_orq = True
        for m in RE_DELEGATION.finditer(text):
            target = m.group(1)
            if target == "IniciarOrquestacionSOAP":
                continue
            if target.lower() == service_name.lower():
                continue
            deps.add(target)
    return (sorted(deps), is_orq)


def detect_orq_dep_caveats(
    legacy_root: Path,
    service_name: str,
    migrated_services: set[str] | None = None,
) -> list[Caveat]:
    """Para ORQ: lista las deps faltantes (servicios delegados aun no migrados)."""
    caveats: list[Caveat] = []
    deps, is_orq = detect_orq_dependencies(legacy_root, service_name)
    if not is_orq or not deps:
        return caveats
    migrated = migrated_services or set()
    for dep in deps:
        if dep.lower() not in {m.lower() for m in migrated}:
            caveats.append(
                Caveat(
                    kind="orq_dep_missing",
                    target=dep,
                    detail=(
                        f"ORQ {service_name} delega a {dep} pero {dep} aun no esta migrado. "
                        f"El ORQ no puede ir a produccion sin que sus deps esten migradas."
                    ),
                    suggested_action=(
                        f"Migrar {dep} primero. Una vez migrado, el ORQ puede continuar. "
                        f"Si {dep} ya fue migrado pero no aparece en la lista, agregar al --migrated-list."
                    ),
                )
            )
    return caveats


def caveats_to_markdown_table(caveats: list[Caveat]) -> str:
    """Renderiza una lista de caveats como tabla markdown."""
    if not caveats:
        return "_(ninguno)_\n"
    lines = ["| # | Tipo | Target | Detalle | Accion sugerida | Evidencia |",
             "|---|---|---|---|---|---|"]
    for i, c in enumerate(caveats, 1):
        lines.append(
            f"| {i} | {c.kind} | {c.target} | {c.detail[:80]} | "
            f"{c.suggested_action[:120]} | {c.evidence or '-'} |"
        )
    return "\n".join(lines) + "\n"


def caveats_summary(caveats: list[Caveat]) -> dict[str, int]:
    """Cuenta caveats por tipo."""
    summary: dict[str, int] = {}
    for c in caveats:
        summary[c.kind] = summary.get(c.kind, 0) + 1
    return summary
