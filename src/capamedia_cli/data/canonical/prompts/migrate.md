---
name: migrate
title: Migrar la logica del legacy al arquetipo destino
description: Lanza el agente migrador con el prompt correcto (REST o SOAP) segun el analisis previo. Implementa todo el codigo hexagonal y corre build hasta que pase.
type: prompt
scope: project
stage: migration
source_kind: any
framework: any
complexity: high
preferred_model:
  anthropic: claude-opus-4-7
fallback_model: opus
allowed_tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Task
---

# migrate

Migra toda la lógica del servicio legacy al arquetipo destino generado por Fabrics.

## Prerequisitos

1. Haber corrido `capamedia clone <servicio>` - deja `legacy/`, `umps/`, `tx/`, `gold-ref/`, `COMPLEXITY_*.md`.
2. Haber corrido `capamedia fabrics generate` - deja `destino/<namespace>-msa-sp-<servicio>/` con el scaffold base.
3. Ejecutar desde la raiz del workspace; no desde `destino/`.

## Paso 1 — Detectar modo

Leer `bank-mcp-matrix.md`, `COMPLEXITY_<servicio>.md` y
`migration-context.json` en `destino/`. La matriz BPTPSRE manda sobre cualquier
heuristica local:

```mermaid
flowchart TD
  A["Leer tecnologia_origen / source_type"] --> B{source_type}
  B -->|was| C["MVC. 1 op=REST, 2+ ops=SOAP. BANCS prohibido"]
  B -->|orq| D["WebFlux REST + lib-event-logs. BANCS directo prohibido"]
  B -->|bus/iib| E{invocaBancs?}
  E -->|true| F["WebFlux REST. BANCS obligatorio permitido"]
  E -->|false| G{"ops"}
  G -->|1| H["WebFlux REST. BANCS prohibido"]
  G -->|2+| I["MVC SOAP. BANCS prohibido"]
```

- Si `projectType=rest` + `webFramework=mvc` + `sourceKind=was` -> cargar
  `migrate-rest-full.md` en modo WAS REST/MVC.
- Si `projectType=rest` + `webFramework=webflux` -> cargar
  `migrate-rest-full.md` en modo BUS/ORQ REST/WebFlux.
- Si `projectType=soap` -> cargar `migrate-soap-full.md` en modo SOAP/MVC.
- Si `migration-context.json` contradice `bank-mcp-matrix.md` -> detenerse y
  pedir confirmacion; no cambiar el arquetipo por cuenta propia.

## Paso 2 — Lanzar agente migrador

Usar el sub-agente `migrador` (definido en `.claude/agents/migrador.md` del proyecto) con este contexto:

- `legacy/` — fuente original (ESQL, WSDL, XSDs, msgflows)
- `umps/` — UMPs asociados con sus ESQL (para extraer TX reales)
- `gold-ref/` — proyecto gold (0024 para REST, 0015 para SOAP) como referencia de patrones
- `destino/tnd-msa-sp-<servicio>/` — destino donde se implementa
- `COMPLEXITY_<servicio>.md` — análisis previo
- `bank-mcp-matrix.md` — fuente unica para decidir REST/WebFlux, REST/MVC o SOAP/MVC

El agente ejecuta los 7 bloques del prompt de migración:

1. **Block 1: Scaffolding** — verificar el scaffold del MCP, ajustar si falta algo
2. **Block 2: Domain layer** — records, exceptions, sin imports de framework
3. **Block 3: Application layer** — interface ports + services
4. **Block 4: Infrastructure layer** — controllers, DTOs, mappers, adapters BANCS, error resolvers, application.yml
5. **Block 5: Helm + Docker** — values-{dev,test,prod}.yaml con probes
6. **Block 6: Tests** — unit + integration con JUnit 5, Mockito, StepVerifier
7. **Block 7: Core Adapter beans** — `@BancsService` config por TX

## Paso 3 — Loop de autocorrección por GATE

Cada bloque tiene un GATE de verificación (grep por imports prohibidos, build gradle, tests pasando). Si falla:
1. Identificar qué falló
2. Analizar causa
3. Corregir
4. Re-verificar
5. Max 3 intentos antes de escalar al usuario

## Paso 4 — Loop de build

Después del Block 7, correr en loop:

```bash
cd destino/tnd-msa-sp-<servicio>/
./gradlew generateFromWsdl && ./gradlew clean build
```

Si falla:
- Parsear el error
- Aplicar fix
- Re-intentar (max 5 ciclos)

## Paso 4.5 - Gate peer review del banco

El build de Azure ejecuta `gradle build -x test`, pero `architectureReview`
sigue corriendo y analiza arquitectura + tests. Despues de compilar, ejecutar o
leer la salida de:

```bash
./gradlew architectureReview
```

Reglas:
- No cerrar con `build_status=green` si `architectureReview` queda con score < 7,
  `BLOQUEAR PR: SI`, u observaciones generales/test sin resolver.
- Objetivo operativo: score >= 9 y sin observaciones accionables.
- Si aparece `Paquetes: 3 / 4`, mover ports a
  `application/input/port` y `application/output/port`.
- Si aparecen observaciones de tests, agregar `application-test.yml`, H2 si hay
  DB, y al menos un test `@SpringBootTest` con MockMvc/WebTestClient/
  MockWebServiceClient y asserts 200/404/500 donde aplique.

## Paso 5 — Generar reporte

Escribir `destino/tnd-msa-sp-<servicio>/MIGRATION_REPORT.md` con:
- Bloques ejecutados y sus GATEs
- Archivos creados / modificados
- Workarounds aplicados (gaps del MCP, feedbacks del equipo)
- Cobertura de tests (del jacocoTestReport)
- GenAI section — qué modelo ejecutó cada bloque

## Paso 6 — Responder conversacionalmente

```markdown
## Migración completada: <servicio>

- **Modo:** REST + WebFlux / REST + Spring MVC / SOAP + Spring MVC
- **Archivos creados:** N
- **Build:** verde (./gradlew build)
- **Tests:** X/Y pasando, cobertura Z%

### Siguiente paso

Corré `/check` para validar contra la checklist BPTPSRE y cruzar con el legacy.
```

## Reglas importantes

1. **No sobrescribir `build.gradle` del MCP.** Sólo agregar dependencias faltantes; nunca reemplazar el archivo.
2. **Puertos son interfaces, nunca abstract classes.**
3. **Domain sin imports de Spring/JPA/WebFlux.**
4. **HTTP 200 para errores de negocio** (compatibilidad con IIB caller).
5. **Secrets vía `${CCC_*}` env vars.**
6. **Código en inglés**, documentación en inglés.
7. **DB no cambia REST/SOAP.** WAS REST/MVC con DB usa HikariCP+JPA+Oracle. Si un caso BUS/ORQ WebFlux trae DB propia, escalar o aislar el bloqueo con R2DBC/`Schedulers.boundedElastic()`; nunca meter HikariCP+JPA en el request path de WebFlux.
8. **Higiene de `.gitignore` antes de cerrar:** el `.gitignore` del proyecto migrado debe ignorar `.capamedia/`, `.codex/`, `.claude/`, `.cursor/`, `.windsurf/`, `.opencode/`, `.github/prompts/`, `.vscode/`, `.idea/`, `.mcp.json`, `FABRICS_PROMPT_*.md`, `QA_STATUS.md` y `TRAMAS.txt`. No ignorar `.sonarlint/connectedMode.json`.
9. **BANCS no se infiere por nombre ni por template.** Solo BUS/IIB con `invocaBancs=true` puede agregar `lib-bnc-api-client`, `BancsService`, `BancsClientHelper`, `bancs.webclients`, `CCC_BANCS_*` o `dependsOn: lib-bnc-api-client`. En WAS, ORQ y BUS sin BANCS, esos artefactos son error de migracion y deben removerse.
