"""Lector del CSV operativo de configurables del banco (v0.42.0).

Problema que resuelve (migracion WSSeguridad0069, 2026-09-03): el agente
concluyo "esta configurable no existe en el CSV" cuando si existia. No fue un
error de razonamiento, fue el archivo:

- El CSV esta en **ISO-8859-1**, no UTF-8. Un `grep` en locale UTF-8 lo trata
  como binario: sale con codigo 1 y sin salida, **indistinguible de "no
  encontrado"**. `sort` directamente muere con `Illegal byte sequence`.
- El delimitador es `;`, no `,` (un `cut -d','` devuelve la fila entera).
- Las columnas reales son `Configurable;Variable;Valor` y los valores vienen
  con triple-quote CSV (`\"\"\"X\"\"\"` -> `X`).
- Son 7868 filas de datos pero solo **533 configurables distintos**, asi que
  cualquier `head -N` sobre la lista ordenada corta antes de la mayoria.
  (Contar con `cut | sort -u | wc -l` da 535 porque suma el encabezado y el
  campo vacio de las filas de relleno; el canonical decia 7879 porque contaba
  lineas, no filas de datos.)

Dato que hace confiable el lookup: las columnas `Configurable` y `Variable` son
**ASCII puro** en las 7868 filas. El encoding solo afecta a 24 valores de
descripcion, asi que buscar por nombre siempre es exacto.

Encima, el patron `grep ... || echo "NO ENCONTRADO"` convierte un fallo de
herramienta en un falso negativo silencioso.

Este modulo hace la lectura correcta una sola vez y el comando
`capamedia configurables` la expone, de modo que el agente migrador no vuelva
a hacer grep a mano. La distincion clave que ofrece es entre **"no esta en el
CSV"** (respuesta definitiva) y **"no pude leer el CSV"** (no hay respuesta):
son dos exit codes distintos, justamente lo que el `|| echo` borraba.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Encoding real del archivo (`file` reporta "ISO-8859 text"). Leerlo como UTF-8
# tira UnicodeDecodeError en las descripciones con acentos.
CSV_ENCODING = "iso-8859-1"
# El banco exporta desde Excel es-EC: separador punto y coma.
CSV_DELIMITER = ";"
# El nombre real trae parentesis: `ConfigurablesBusOmniTest_Transfor(...)csv`.
CSV_GLOB = "ConfigurablesBusOmni*.csv"
# Encabezado esperado (las columnas que el canonical llamaba `ConfigName`).
EXPECTED_HEADER = ("Configurable", "Variable", "Valor")


class ConfigurablesCsvError(RuntimeError):
    """No se pudo localizar o leer el CSV. NO significa "la clave no existe"."""


@dataclass(frozen=True)
class ConfigurableRow:
    """Una fila del CSV, ya normalizada (sin padding ni triple-quote)."""

    configurable: str
    variable: str
    valor: str

    @property
    def key(self) -> str:
        return f"{self.configurable}.{self.variable}"


def _clean(field: str) -> str:
    """Quita padding y las comillas sobrantes del export de Excel.

    El `csv` module ya resuelve el `\"\"\"X\"\"\"` a `\"X\"`; aca sacamos ese par
    externo que queda.
    """
    value = (field or "").strip()
    while len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1].strip()
    return value


def rows_with_encoding_artifacts(rows: list[ConfigurableRow]) -> list[ConfigurableRow]:
    """Filas cuyo `Valor` trae un acento mal codificado en el CSV de origen.

    Son 24 en el CSV vigente: el banco exporto `Notificacion`/`Certificacion`
    con un byte `0xE2` donde iba `o` con tilde, asi que latin-1 las lee como
    `Notificaci` + `a` con circunflejo. No es un bug de lectura: el archivo
    llega asi. Importa porque copiar ese literal a `application.yml` deja un
    texto corrupto que QA del banco reporta; el valor exacto se pide al SRE.
    """
    return [row for row in rows if not row.valor.isascii()]


def candidate_csv_paths(workspace: Path | None = None) -> list[Path]:
    """Rutas donde buscar el CSV, en orden de preferencia.

    Reusa la misma busqueda de `prompts/` que los catalogos oficiales
    (`catalog_injector.candidate_capamedia_roots`) para no tener dos
    convenciones de descubrimiento divergentes.
    """
    from capamedia_cli.core.catalog_injector import candidate_capamedia_roots

    ws = (workspace or Path.cwd()).resolve()
    found: list[Path] = []
    seen: set[Path] = set()
    # 1. Snapshot local del workspace (util en batch, igual que los catalogos).
    for base in (ws / ".capamedia" / "catalogs", *[r / "prompts" for r in candidate_capamedia_roots(ws)]):
        if not base.is_dir():
            continue
        for match in sorted(base.glob(CSV_GLOB)):
            resolved = match.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
    return found


def find_configurables_csv(
    workspace: Path | None = None, explicit: Path | None = None
) -> Path | None:
    """Path al CSV, o None si no esta disponible localmente."""
    if explicit is not None:
        explicit = explicit.expanduser().resolve()
        if explicit.is_file():
            return explicit
        if explicit.is_dir():
            matches = sorted(explicit.glob(CSV_GLOB))
            return matches[0].resolve() if matches else None
        return None
    paths = candidate_csv_paths(workspace)
    return paths[0] if paths else None


def load_rows(path: Path) -> list[ConfigurableRow]:
    """Lee el CSV completo con el encoding y delimitador correctos.

    Salta el encabezado y las filas vacias (el export trae `;;;;;;` de relleno).
    Levanta `ConfigurablesCsvError` si el archivo no se puede leer.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigurablesCsvError(f"no pude leer {path}: {exc}") from exc

    text = raw.decode(CSV_ENCODING, errors="replace")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=CSV_DELIMITER)
    rows: list[ConfigurableRow] = []
    for index, fields in enumerate(reader):
        if len(fields) < 2:
            continue
        configurable = _clean(fields[0])
        variable = _clean(fields[1])
        valor = _clean(fields[2]) if len(fields) > 2 else ""
        if not configurable and not variable:
            continue
        # Encabezado (primera fila util).
        if index == 0 and configurable.lower() == EXPECTED_HEADER[0].lower():
            continue
        rows.append(ConfigurableRow(configurable, variable, valor))
    if not rows:
        raise ConfigurablesCsvError(
            f"{path} no tiene filas de datos (revisa encoding/delimitador)"
        )
    return rows


def distinct_configurables(rows: list[ConfigurableRow]) -> list[str]:
    """Nombres de configurable distintos, ordenados (533 en el CSV vigente)."""
    return sorted({row.configurable for row in rows if row.configurable}, key=str.lower)


def lookup(
    rows: list[ConfigurableRow],
    name: str,
    *,
    variable: str | None = None,
    exact: bool = False,
) -> list[ConfigurableRow]:
    """Filas cuyo `Configurable` matchea `name` (y opcionalmente `Variable`).

    Por defecto el match es case-insensitive y por substring, porque el legacy
    escribe el nombre con variantes (`CMRCTEATRConfig`, `CMRCTEATR`). `exact`
    fuerza igualdad case-insensitive.
    """
    needle = name.strip().lower()
    var_needle = (variable or "").strip().lower()

    def matches(row: ConfigurableRow) -> bool:
        target = row.configurable.lower()
        if exact:
            if target != needle:
                return False
        elif needle not in target:
            return False
        return not (var_needle and var_needle not in row.variable.lower())

    return [row for row in rows if matches(row)]


def as_yaml_block(rows: list[ConfigurableRow], indent: str = "  ") -> str:
    """Bloque `application.yml` listo para pegar (agrupado por configurable).

    Los valores del CSV son literales del catalogo operativo: van como literal
    en `application.yml`, no como `${CCC_*}` (ver `bank-configurables.md`).
    """
    by_name: dict[str, list[ConfigurableRow]] = {}
    for row in rows:
        by_name.setdefault(row.configurable, []).append(row)
    lines: list[str] = []
    for name in sorted(by_name, key=str.lower):
        lines.append(f"{name}:")
        for row in sorted(by_name[name], key=lambda r: r.variable.lower()):
            value = row.valor.replace('"', '\\"')
            lines.append(f'{indent}{row.variable}: "{value}"')
    return "\n".join(lines)
