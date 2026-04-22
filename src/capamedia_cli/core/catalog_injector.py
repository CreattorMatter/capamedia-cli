"""Inyeccion de catalogos oficiales del banco al prompt del FABRICS/MIGRATE.

Objetivo: evitar que la AI alucine TX-BANCS, codigos backend o reglas de
estructura de error. Cargamos los 3 catalogos canonicos y los renderizamos
como bloque Markdown listo para inyectar al prompt.

Fuentes (orden de preferencia):
  1. `<workspace>/.capamedia/catalogs/` (snapshot local, util en batch clone)
  2. `<capamedia_root>/prompts/tx-adapter-catalog.json`
     + `<capamedia_root>/prompts/sqb-cfg-codigosBackend-config/codigosBackend.xml`
     + `<capamedia_root>/prompts/Transacciones catalogadas Dominio_v1*.xlsx`

Si no hay fuentes, devolvemos snapshot vacio + warning. Nunca tiramos.

Reglas duras:
  - TX que aparezca en el servicio y este en catalogo => se inyecta literal.
  - TX que NO este en catalogo => bullet `NEEDS_HUMAN_CATALOG_MAPPING`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Reglas canonicas del PDF BPTPSRE (documentadas en
# `prompts/documentacion/BPTPSRE-Estructura de error-*.pdf`).
# Orden de precedencia: PDF > checklist > reviewers > golds vigentes.
_ERROR_STRUCTURE_RULES: tuple[str, ...] = (
    "codigo: exactamente igual al legacy (mirar ESQL et_bancs/et_soap o properties).",
    "mensaje: para migrados, solo la descripcion. Si legacy decia `NODO-OK`, queda `OK`.",
    "mensajeNegocio: vacio (\"\" o null). Lo gestiona DataPower, NO el microservicio.",
    "tipo: exactamente igual al legacy: INFO=success, ERROR=negocio recoverable, "
    "FATAL=headers/bancs/unexpected.",
    "recurso: `<NOMBRE_SERVICIO>/<metodoCamelCase>` (ej: `tnd-msa-sp-wsclientes0024/getDatosBasicos`). "
    "QA valida estructura, no valor exacto.",
    "componente: success o error interno -> `<NOMBRE_SERVICIO>`; error de libreria -> `ApiClient`; "
    "error de negocio desde ApiClient -> `TX<codigo>`.",
    "backend: exactamente igual al legacy. Tomarlo de codigosBackend.xml. "
    "IIB=`00638`, BANCS_APP=`00045`. NO inventar \"00000\".",
)

# Nombres de archivos que buscamos dentro de un `prompts/` valido.
_TX_CATALOG_FILENAME = "tx-adapter-catalog.json"
_BACKEND_CODES_DIR = "sqb-cfg-codigosBackend-config"
_BACKEND_CODES_FILE = "codigosBackend.xml"
_XLSX_GLOB = "Transacciones catalogadas Dominio_v1*.xlsx"


@dataclass
class CatalogSnapshot:
    """Snapshot inmutable de los catalogos oficiales cargados en memoria.

    `tx_mappings` mapea una TX code (string de 6 digitos) a su fila del
    catalogo (bancs real si difiere, dominio, data class/adapter, etc.).
    `backend_codes` mapea `aplicacion` -> `id` (ej: "iib" -> "00638").
    `error_structure_rules` es una lista de reglas canonicas del PDF BPTPSRE.
    `source_paths` lista los archivos efectivamente cargados (audit trail).
    """

    tx_mappings: dict[str, dict[str, str]] = field(default_factory=dict)
    backend_codes: dict[str, str] = field(default_factory=dict)
    error_structure_rules: list[str] = field(default_factory=list)
    source_paths: list[Path] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.tx_mappings and not self.backend_codes and not self.error_structure_rules


# -- discovery ---------------------------------------------------------------


def _default_capamedia_roots(workspace: Path) -> list[Path]:
    """Orden de busqueda para el `prompts/` global cuando no se especifica.

    El CLI vive en `.../capamedia-cli/`, los prompts oficiales en
    `.../CapaMedia/prompts/`. Buscamos hacia arriba a partir del workspace
    y del propio CLI.
    """
    candidates: list[Path] = []
    for start in (workspace.resolve(), Path(__file__).resolve().parent):
        current = start
        seen: set[Path] = set()
        for _ in range(6):
            if current in seen:
                break
            seen.add(current)
            candidates.append(current)
            candidates.append(current / "CapaMedia")
            if current.parent == current:
                break
            current = current.parent
    return candidates


def _find_prompts_dir(workspace: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        explicit = explicit.resolve()
        if (explicit / "prompts").is_dir():
            return explicit / "prompts"
        if explicit.name == "prompts" and explicit.is_dir():
            return explicit
        return None
    for root in _default_capamedia_roots(workspace):
        cand = root / "prompts"
        if cand.is_dir() and (cand / _TX_CATALOG_FILENAME).is_file():
            return cand
    return None


def _workspace_cache_dir(workspace: Path) -> Path:
    return workspace / ".capamedia" / "catalogs"


# -- parsing -----------------------------------------------------------------


def _parse_tx_catalog(path: Path) -> dict[str, dict[str, str]]:
    """Lee tx-adapter-catalog.json y devuelve {tx_code: {campos}}.

    Preserva todos los campos del JSON pero los normaliza a strings.
    Acepta el formato esperado: lista de objetos con `tx`, `tipo`, `dominio`,
    `capacidad`, `tribu`, `adaptador`. Valores null se convierten a "".
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("no pude parsear %s: %s", path, e)
        return {}

    if not isinstance(data, list):
        logger.warning("formato inesperado en %s (no es lista)", path)
        return {}

    mappings: dict[str, dict[str, str]] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        tx = str(entry.get("tx", "")).strip()
        if not tx:
            continue
        mappings[tx] = {
            "tx": tx,
            "tipo": str(entry.get("tipo") or "").strip(),
            "dominio": str(entry.get("dominio") or "").strip(),
            "capacidad": str(entry.get("capacidad") or "").strip(),
            "tribu": str(entry.get("tribu") or "").strip(),
            "adaptador": str(entry.get("adaptador") or "").strip(),
        }
    return mappings


def _parse_backend_codes(path: Path) -> dict[str, str]:
    """Extrae `aplicacion -> id` de codigosBackend.xml con regex liviana.

    El XML tiene la forma: `<backcode id="00638" aplicacion="iib" ... />`.
    Preferimos regex sobre un parser XML completo para tolerar el encoding
    (el archivo mezcla latin-1 en descripciones pero los atributos son ASCII).
    """
    import re

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.warning("no pude leer %s: %s", path, e)
        return {}

    pattern = re.compile(
        r'<backcode\s+id="(?P<id>[^"]+)"\s+aplicacion="(?P<app>[^"]+)"',
        re.IGNORECASE,
    )
    codes: dict[str, str] = {}
    for m in pattern.finditer(text):
        app = m.group("app").strip()
        code = m.group("id").strip()
        if app and code:
            codes[app] = code
    return codes


def _parse_xlsx_mappings(path: Path) -> dict[str, dict[str, str]]:
    """Fallback: si no hay tx-adapter-catalog.json, leer el xlsx oficial.

    Columnas esperadas (del header de la hoja `Hoja1`):
      TRANSACCIONES | DESCRIPCION | (aux) | TIPO | DOMINIO | CAPACIDAD |
      TRIBU | NOMBRE DEL ADAPTADOR | YA CREADAS | Independientes | TOP 15

    El codigo TX viene prefijado con `TX` en la primera columna (ej:
    `TX067050`). Lo strippeamos antes de guardar.
    """
    try:
        import openpyxl
    except ImportError:
        logger.warning("openpyxl no disponible, ignorando %s", path)
        return {}

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (OSError, ValueError) as e:
        logger.warning("no pude leer xlsx %s: %s", path, e)
        return {}

    mappings: dict[str, dict[str, str]] = {}
    try:
        ws = wb.active
        if ws is None:
            return {}
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return {}
        header = [str(c or "").strip().upper() for c in rows[0]]

        def idx(name: str) -> int:
            try:
                return header.index(name)
            except ValueError:
                return -1

        tx_col = idx("TRANSACCIONES")
        tipo_col = idx("TIPO")
        dom_col = idx("DOMINIO MAPA CAPACIDADES V3")
        if dom_col < 0:
            dom_col = idx("DOMINIO")
        cap_col = idx("CAPACIDAD")
        tribu_col = idx("TRIBU")
        adapter_col = idx("NOMBRE DEL ADAPTADOR")

        for row in rows[1:]:
            if tx_col < 0 or len(row) <= tx_col:
                continue
            raw_tx = str(row[tx_col] or "").strip()
            if not raw_tx:
                continue
            tx = raw_tx.upper().removeprefix("TX").strip()
            if not tx:
                continue
            mappings[tx] = {
                "tx": tx,
                "tipo": str(row[tipo_col] or "").strip() if tipo_col >= 0 and len(row) > tipo_col else "",
                "dominio": str(row[dom_col] or "").strip() if dom_col >= 0 and len(row) > dom_col else "",
                "capacidad": str(row[cap_col] or "").strip() if cap_col >= 0 and len(row) > cap_col else "",
                "tribu": str(row[tribu_col] or "").strip() if tribu_col >= 0 and len(row) > tribu_col else "",
                "adaptador": str(row[adapter_col] or "").strip() if adapter_col >= 0 and len(row) > adapter_col else "",
            }
    finally:
        wb.close()
    return mappings


# -- public API --------------------------------------------------------------


def load_catalogs(
    workspace: Path,
    *,
    capamedia_root: Path | None = None,
) -> CatalogSnapshot:
    """Carga los catalogos oficiales con fallback graceful.

    Orden:
      1. `<workspace>/.capamedia/catalogs/` si contiene alguno de los archivos.
         Util cuando `batch clone` ya inyecto snapshot local.
      2. `<capamedia_root>/prompts/` (si se paso explicito) o el primer
         `prompts/` descubierto mirando cwd/capamedia-cli parents.

    Si no hay NINGUNA fuente, devuelve snapshot vacio (`is_empty() == True`)
    y loggea warning. El llamador decide si es bloqueante o no.
    """
    snapshot = CatalogSnapshot()
    snapshot.error_structure_rules = list(_ERROR_STRUCTURE_RULES)

    # Workspace-local cache tiene prioridad.
    cache_dir = _workspace_cache_dir(workspace)
    if cache_dir.is_dir():
        tx_path = cache_dir / _TX_CATALOG_FILENAME
        if tx_path.is_file():
            snapshot.tx_mappings.update(_parse_tx_catalog(tx_path))
            snapshot.source_paths.append(tx_path)
        backend_path = cache_dir / _BACKEND_CODES_FILE
        if backend_path.is_file():
            snapshot.backend_codes.update(_parse_backend_codes(backend_path))
            snapshot.source_paths.append(backend_path)

    # Completar con el prompts/ global.
    prompts_dir = _find_prompts_dir(workspace, capamedia_root)
    if prompts_dir is not None:
        if not snapshot.tx_mappings:
            tx_path = prompts_dir / _TX_CATALOG_FILENAME
            if tx_path.is_file():
                snapshot.tx_mappings.update(_parse_tx_catalog(tx_path))
                snapshot.source_paths.append(tx_path)
        if not snapshot.backend_codes:
            backend_path = prompts_dir / _BACKEND_CODES_DIR / _BACKEND_CODES_FILE
            if backend_path.is_file():
                snapshot.backend_codes.update(_parse_backend_codes(backend_path))
                snapshot.source_paths.append(backend_path)
        # Fallback xlsx solo si tx_mappings sigue vacio.
        if not snapshot.tx_mappings:
            xlsx_candidates = sorted(prompts_dir.glob(_XLSX_GLOB))
            if xlsx_candidates:
                xlsx_path = xlsx_candidates[0]
                snapshot.tx_mappings.update(_parse_xlsx_mappings(xlsx_path))
                snapshot.source_paths.append(xlsx_path)

    if snapshot.is_empty() or (not snapshot.tx_mappings and not snapshot.backend_codes):
        logger.warning(
            "catalogos oficiales no encontrados (workspace=%s, capamedia_root=%s). "
            "La AI puede alucinar valores de TX/backend.",
            workspace,
            capamedia_root,
        )
    return snapshot


def format_for_prompt(
    snapshot: CatalogSnapshot,
    *,
    relevant_tx: list[str] | None = None,
) -> str:
    """Renderiza un snapshot como bloque Markdown listo para inyectar.

    Si `relevant_tx` se provee:
      - Filtra `tx_mappings` a esas TX.
      - Para TX no catalogadas, emite bullet `NEEDS_HUMAN_CATALOG_MAPPING`.
      - Si la lista esta vacia tras filtrar, omite la tabla.

    El bloque empieza con `## Catalogos oficiales ...` para que sea detectable
    al deduplicar (ver `contains_catalog_block`).
    """
    if snapshot.is_empty():
        return ""

    lines: list[str] = []
    lines.append("## Catalogos oficiales (cargados automaticamente - NO alucinar estos valores)")
    lines.append("")
    if snapshot.source_paths:
        lines.append("**Fuentes cargadas:**")
        for p in snapshot.source_paths:
            lines.append(f"- `{p}`")
        lines.append("")

    # TX mappings
    requested = [t.strip() for t in (relevant_tx or []) if t and t.strip()]
    requested_norm = [t.upper().removeprefix("TX").strip() for t in requested]

    if snapshot.tx_mappings:
        lines.append("### TX mappings IIB -> BANCS (reales, via tx-adapter-catalog / xlsx)")
        lines.append("")
        lines.append("| TX | Tipo | Dominio | Tribu | Adaptador BANCS |")
        lines.append("|---|---|---|---|---|")
        if requested_norm:
            known = [tx for tx in requested_norm if tx in snapshot.tx_mappings]
            for tx in known:
                m = snapshot.tx_mappings[tx]
                lines.append(
                    f"| `{m.get('tx', tx)}` | {m.get('tipo') or '-'} | {m.get('dominio') or '-'} | "
                    f"{m.get('tribu') or '-'} | `{m.get('adaptador') or '-'}` |"
                )
        else:
            # Full catalog (truncate to keep prompt bounded)
            for tx in sorted(snapshot.tx_mappings):
                m = snapshot.tx_mappings[tx]
                lines.append(
                    f"| `{m.get('tx', tx)}` | {m.get('tipo') or '-'} | {m.get('dominio') or '-'} | "
                    f"{m.get('tribu') or '-'} | `{m.get('adaptador') or '-'}` |"
                )
        lines.append("")

        if requested_norm:
            missing = [tx for tx in requested_norm if tx not in snapshot.tx_mappings]
            if missing:
                lines.append("**TX detectadas en el servicio pero NO catalogadas:**")
                for tx in missing:
                    lines.append(
                        f"- WARN TX {tx}: NO esta en catalogo. "
                        "La AI debe reportar `NEEDS_HUMAN_CATALOG_MAPPING`."
                    )
                lines.append("")

    # Backend codes
    if snapshot.backend_codes:
        lines.append("### Codigos de backend (PDF BPTPSRE, via codigosBackend.xml)")
        lines.append("")
        priority = ("iib", "bancs_app", "was", "wso2", "datapower")
        shown: set[str] = set()
        for key in priority:
            if key in snapshot.backend_codes:
                lines.append(f"- `{key}` -> **{snapshot.backend_codes[key]}**")
                shown.add(key)
        # Resto en orden alfabetico
        remaining = sorted(k for k in snapshot.backend_codes if k not in shown)
        for key in remaining:
            lines.append(f"- `{key}` -> `{snapshot.backend_codes[key]}`")
        lines.append("")

    # Error structure rules
    if snapshot.error_structure_rules:
        lines.append("### Estructura de error (reglas PDF BPTPSRE - prevalecen sobre gold 0015)")
        lines.append("")
        for rule in snapshot.error_structure_rules:
            lines.append(f"- {rule}")
        lines.append("")

    lines.append("> Estas tablas vienen del banco. Si un valor contradice lo que esperabas, confia en esta tabla.")
    return "\n".join(lines).rstrip() + "\n"


# -- helpers para integracion ------------------------------------------------

_CATALOG_MARKER = "## Catalogos oficiales (cargados automaticamente"


def contains_catalog_block(text: str) -> bool:
    """True si el texto ya tiene un bloque de catalogos inyectado.

    Usado por `batch._build_batch_migrate_prompt` para no duplicar cuando el
    `FABRICS_PROMPT_<svc>.md` ya lo trae pegado.
    """
    return _CATALOG_MARKER in (text or "")


def detect_relevant_tx(
    workspace: Path,
    service: str,
    *,
    analysis_umps: list[object] | None = None,
) -> list[str]:
    """Deduce las TX codes relevantes para el servicio.

    Fuentes (union):
      1. `analysis.umps[*].tx_codes` del LegacyAnalysis (si se pasa).
      2. `<workspace>/tx/sqb-cfg-<NNNNNN>-TX/` (clonados por `capamedia clone`).
      3. `COMPLEXITY_<service>.md` - extrae TX con regex de la tabla.

    Devuelve lista sin duplicados, normalizadas a 6 digitos.
    """
    import re

    found: set[str] = set()

    if analysis_umps:
        for ump in analysis_umps:
            tx_codes = getattr(ump, "tx_codes", None) or []
            for tx in tx_codes:
                tx_norm = str(tx).strip().upper().removeprefix("TX")
                if tx_norm.isdigit():
                    found.add(tx_norm)

    tx_dir = workspace / "tx"
    if tx_dir.is_dir():
        pattern = re.compile(r"sqb-cfg-(\d{5,6})-TX", re.IGNORECASE)
        for child in tx_dir.iterdir():
            m = pattern.match(child.name)
            if m:
                found.add(m.group(1))

    complexity_md = workspace / f"COMPLEXITY_{service}.md"
    if complexity_md.is_file():
        try:
            text = complexity_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for m in re.finditer(r"\b(\d{6})\b", text):
            found.add(m.group(1))

    return sorted(found)
