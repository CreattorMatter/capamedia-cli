---
name: clone
title: Clonar el servicio legacy + UMPs + TX catalogs
description: Detecta el repo legacy en Azure DevOps, lo clona, identifica UMPs/TX asociados y los clona tambien. Reporta un resumen de complejidad del servicio.
type: prompt
scope: project
stage: pre-migration
source_kind: any
framework: any
complexity: medium
preferred_model:
  anthropic: claude-sonnet-4-6
fallback_model: sonnet
allowed_tools:
  - Bash
  - Read
  - Glob
  - Grep
  - Write
harness_overrides:
  cursor:
    globs: []
    alwaysApply: false
---

# /clone &lt;nombre-del-servicio&gt;

Cloná el servicio legacy y todo su árbol de dependencias en el workspace actual.

## Input

Un único argumento: nombre del servicio legacy (sin prefijo).

Ejemplos:
- `/clone wsclientes0008`
- `/clone umpclientes0005`
- `/clone orqtransferencias0003`

## Qué hacer (en orden)

### Paso 1 — Clonar el repo legacy

Resolvé el nombre del repo según el patrón:

| Prefijo del servicio | Patrón de repo |
|---|---|
| `wsclientes*` / `wscuentas*` / `ws*` | `sqb-msa-<servicio>` |
| `umpclientes*` / `umpcuentas*` / `ump*` | `sqb-msa-<servicio>` |
| `orq*` | `sqb-msa-<servicio>` |

Cloná en una subcarpeta `./legacy/` del CWD:

```bash
mkdir -p legacy
git clone https://dev.azure.com/BancoPichinchaEC/tpl-bus-omnicanal/_git/sqb-msa-<servicio> legacy/sqb-msa-<servicio>
```

Si el clone falla por auth, avisá al usuario que corra `git clone` manual primero para cachear el PAT via GCM (ver guía en `CLAUDE.md`).

### Paso 2 — Detectar UMPs referenciados

Buscá referencias a UMPs en los archivos ESQL/msgflow del legacy clonado:

```bash
grep -rhoE "UMPClientes[0-9]+|UMPCuentas[0-9]+|UMP[A-Z][a-z]+[0-9]+" legacy/sqb-msa-<servicio>/src/ 2>/dev/null | sort -u
```

Para cada UMP encontrado, cloná su repo en `./umps/`:

```bash
mkdir -p umps
for UMP in <lista>; do
  UMP_LOWER=$(echo "$UMP" | tr '[:upper:]' '[:lower:]')
  git clone https://dev.azure.com/BancoPichinchaEC/tpl-bus-omnicanal/_git/sqb-msa-${UMP_LOWER} umps/sqb-msa-${UMP_LOWER}
done
```

### Paso 3 — Extraer TX codes de los UMPs

Para cada UMP clonado, escaneá su ESQL buscando TX codes (códigos BANCS de 6 dígitos):

```bash
for UMP_DIR in umps/*/; do
  grep -rhoE "'[0-9]{6}'" "$UMP_DIR/src/" 2>/dev/null | tr -d "'" | sort -u
done
```

Registrá el mapping `UMP -> TX code` en una tabla del reporte.

### Paso 4 — Clonar catálogos de referencia

Cloná los catálogos del banco (son comunes a todos los servicios):

```bash
mkdir -p tx
git clone https://dev.azure.com/BancoPichinchaEC/tpl-bus-omnicanal/_git/sqb-cfg-codigosBackend-config tx/sqb-cfg-codigosBackend-config
git clone https://dev.azure.com/BancoPichinchaEC/tpl-bus-omnicanal/_git/sqb-cfg-errores-errors tx/sqb-cfg-errores-errors
```

### Paso 5 — Contar operaciones del WSDL legacy

Contá las operaciones del `<portType>` en el WSDL del legacy (insumo para
decidir framework via matriz MCP en `/fabric`):

```bash
WSDL=$(find legacy -name "*.wsdl" -not -path "*/node_modules/*" | head -1)
OPS=$(awk '/<wsdl:portType/,/<\/wsdl:portType>/' "$WSDL" | grep -c "<wsdl:operation")
```

El framework se decide segun `bank-mcp-matrix.md`: BUS+invocaBancs siempre
REST+WebFlux, ORQ siempre REST+WebFlux, WAS 1 op REST+MVC, WAS 2+ ops SOAP+MVC,
BUS sin BANCS 1 op REST+WebFlux y BUS sin BANCS 2+ ops SOAP+MVC. Las reglas
canonicas viven en los contextos del CLI (`bank-mcp-matrix.md`,
`bank-official-rules.md`, `hexagonal.md`, `bancs.md`) — no hace falta clonar un
"servicio gold" de referencia.

### Paso 6 — Detectar tipo de fuente (IIB / WAS / ORQ)

- Si hay `*.esql` **y** el nombre empieza con `ORQ` → tipo **ORQ** (análisis liviano)
- Si hay `*.esql` **y** nombre empieza con `WS/UMP` → tipo **IIB**
- Si hay `*.java` + `web.xml` y no hay `*.esql` → tipo **WAS**
- Si hay ambiguedad → flaggear y preguntar al usuario

### Paso 7 — Responder conversacionalmente

Al final, respondé en el chat con un resumen estructurado:

```markdown
## Clone completado: <servicio>

- **Tipo de fuente:** IIB / WAS / ORQ
- **Operaciones WSDL:** <N>
- **Framework recomendado:** segun `bank-mcp-matrix.md` (REST+WebFlux, REST+Spring MVC o SOAP+Spring MVC)
- **UMPs detectados:** <lista con TX codes>
- **BD detectada:** SI / NO (solo relevante para WAS)
- **Complejidad estimada:** LOW / MEDIUM / HIGH

### UMPs y TX codes

| UMP | TX code |
|---|---|
| UMPClientes0002 | 060480 |
| UMPClientes0020 | 061404 |

### Archivos clave encontrados en legacy/
- WSDL: `legacy/<repo>/src/main/resources/wsdl/<service>.wsdl`
- XSDs: `legacy/<repo>/src/main/resources/xsd/*.xsd`
- ESQL: `legacy/<repo>/src/main/resources/esql/*.esql` (N archivos)

### Proximo paso

Si todo se ve bien, corré `/fabric` para generar el arquetipo en `./destino/`.
Si ves algo raro (UMPs faltantes, WSDL no estandar, etc.), avisame antes.
```

## Reglas importantes

1. **No fabricar datos.** Si un UMP no se pudo clonar (auth, no existe), marcalo explícitamente y seguí.
2. **Respetar `.gitignore`.** Las carpetas `legacy/`, `umps/`, `tx/`, `gold-ref/` ya están en `.gitignore` (agregadas por `capamedia init`). Nunca las agregues al commit.
3. **Si el PAT falla**, pará y pedile al usuario que corra `git clone` interactivo una vez para cachear el token via GCM. Ver la guía en `CLAUDE.md`.
4. **Escribí un archivo `COMPLEXITY_<servicio>.md`** con el reporte anterior para que `/fabric` y `/migrate` lo lean después.
