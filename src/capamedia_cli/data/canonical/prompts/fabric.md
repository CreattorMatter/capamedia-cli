---
name: fabric
title: Generar arquetipo con el MCP Fabrics del banco
description: Deduce los parametros del MCP desde el analisis previo y lo invoca para generar el scaffold oficial en ./destino/. Aplica workarounds conocidos del MCP.
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
  - Read
  - Glob
  - Grep
  - Bash
  - Write
  - Edit
  - mcp__fabrics__create_project_with_wsdl
---

# /fabric

Genera el arquetipo oficial del Banco Pichincha usando el MCP Fabrics, con todos los parámetros deducidos del análisis previo.

## Prerequisitos

1. Haber corrido `/clone <servicio>` antes (deja `legacy/`, `COMPLEXITY_*.md`, etc.).
2. El MCP Fabrics debe estar conectado. Si el tool `mcp__fabrics__create_project_with_wsdl` no aparece, parar y correr `capamedia fabrics preflight` en shell.

## Paso 1 — Preflight del MCP

Antes de invocar, verificar:

1. **El tool existe** — `mcp__fabrics__create_project_with_wsdl` debe estar disponible en esta sesión. Si no, avisar al usuario y detenerse.

2. **Versión reciente** — preguntar al usuario: *"¿Actualizaste el MCP esta semana? (`npm view @pichincha/fabrics-project version`)"*. Registrar la respuesta.

3. **Schema actualizado** — leer el schema del tool. Si hay parámetros nuevos o renombrados respecto a los conocidos, preguntar antes de invocar.

## Paso 2 — Leer el contexto

Leer en este orden:
- `COMPLEXITY_<servicio>.md` (si existe) — preferido, ya tiene tipo y # ops
- `legacy/*/src/main/resources/wsdl/*.wsdl` — para contar ops si falta COMPLEXITY
- `.capamedia/config.yaml` — metadata del proyecto

## Paso 3 — Deducir parámetros del MCP

| Parámetro | Cómo se deduce |
|---|---|
| `wsdlPath` | Ruta absoluta al `*.wsdl` del legacy clonado |
| `projectType` | `rest` si WSDL tiene 1 op, `soap` si tiene 2+ ops |
| `webFramework` | `webflux` si no hay BD, `mvc` si hay BD (solo aplica a SOAP) |
| `serviceName` | Nombre del servicio (del argumento de `/clone`) |
| `groupId` | `com.pichincha.sp` (standard del banco) |
| `artifactId` | `tnd-msa-sp-<servicio>` |
| `javaVersion` | `21` |
| `springBootVersion` | la última compatible (verificar via MCP schema o preguntar) |

## Paso 4 — Invocar el MCP

```
mcp__fabrics__create_project_with_wsdl(
    wsdlPath="<ruta absoluta>",
    projectType="rest" o "soap",
    webFramework="webflux" o "mvc",
    serviceName="<servicio>",
    outputDir="./destino",
    ...
)
```

Si el MCP crea una subcarpeta `./destino/tnd-msa-sp-<servicio>/`, está OK — dejarla ahí.

## Paso 5 — Aplicar workarounds conocidos (MCP ≤ 2026-04-10)

Verificar cada gap y aplicar el workaround si corresponde. Si el MCP nuevo ya lo fixeó, registrar en `.capamedia/config.yaml` bajo `scaffolding.gaps_fixed_by_mcp`.

### Gap 1 — `spring-boot-starter-webflux` faltante en scaffold SOAP

Si `projectType=soap` y el `build.gradle` generado **no** incluye `spring-boot-starter-webflux`, agregarlo manualmente:

```groovy
implementation 'org.springframework.boot:spring-boot-starter-webflux'
```

(Necesario porque `lib-bnc-api-client` usa `WebClient` internamente).

### Gap 2 — `jaxws-rt` faltante

Si falta, agregar al `build.gradle`:

```groovy
implementation('com.sun.xml.ws:jaxws-rt:4.0.3') {
    exclude group: 'com.sun.xml.bind', module: 'jaxb-core'
    exclude group: 'com.sun.xml.bind', module: 'jaxb-impl'
}
```

### Gap 3 — Versiones desactualizadas

Verificar y actualizar (si aplica) las versiones de Spring Boot, Jackson y Peer Review en `build.gradle` comparando con la matriz canónica del CLI y con lo que genere el schema actual del MCP.

## Paso 6 — Completar con artefactos CapaMedia

Después del scaffold del MCP, copiar al destino:

```bash
# Copiar los assets del harness generado por capamedia init al destino
cp -r .codex destino/tnd-msa-sp-<servicio>/ 2>/dev/null || true
cp -r .agents destino/tnd-msa-sp-<servicio>/ 2>/dev/null || true
cp AGENTS.md destino/tnd-msa-sp-<servicio>/ 2>/dev/null || true
cp -r .claude destino/tnd-msa-sp-<servicio>/ 2>/dev/null || true
cp CLAUDE.md destino/tnd-msa-sp-<servicio>/ 2>/dev/null || true
cp .sonarlint/connectedMode.json destino/tnd-msa-sp-<servicio>/.sonarlint/ 2>/dev/null || true
cp .mcp.json destino/tnd-msa-sp-<servicio>/  # (el .gitignore lo ignora)
```

## Paso 7 — Registrar contexto

Escribir `destino/tnd-msa-sp-<servicio>/migration-context.json`:

```json
{
  "service": "<servicio>",
  "sourceKind": "iib|was|orq",
  "projectType": "rest|soap",
  "webFramework": "webflux|mvc",
  "dbUsage": false,
  "operationsCount": 1,
  "umps": [{"name": "UMPClientes0002", "tx": "060480"}],
  "scaffolding": {
    "mcp_version": "<versión reportada>",
    "scaffold_date": "<ISO8601>",
    "gaps_fixed_by_mcp": ["gap1", "gap2"],
    "workarounds_applied": []
  }
}
```

## Paso 8 — Responder conversacionalmente

```markdown
## Arquetipo generado: <servicio>

**Parámetros pasados al MCP:**
- projectType: rest
- webFramework: webflux
- wsdlPath: .../legacy/.../consultarCliente.wsdl

**Workarounds aplicados:**
- Gap 1 (webflux starter) — AGREGADO
- Gap 2 (jaxws-rt) — NO aplica (projectType=rest)
- Gap 3 (versiones) — sincronizado con la matriz canónica del CLI

**Destino generado:** `./destino/tnd-msa-sp-<servicio>/`

Revisá:
1. `build.gradle` — que las dependencias sean las esperadas
2. `src/main/resources/wsdl/` — que el WSDL esté copiado
3. Artefactos del harness (`.codex/` + `.agents/` + `AGENTS.md`, o `.claude/` + `CLAUDE.md`) — que estén adentro

Si está todo bien, abrí esa carpeta en el IDE y corré `/migrate`.
```

## Reglas importantes

1. **No rebuild desde cero.** Si el MCP falla, hacer self-correction loop (reintentar con distintos params). Sólo fallback a scaffold manual si el MCP genuinamente no está disponible.
2. **Respetar el build.gradle del MCP.** Solo aplicar workarounds de gaps conocidos y documentar cada cambio.
3. **No commitear secrets.** El `.mcp.json` copiado al destino no debe terminar en git (ya está en `.gitignore`).
