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

# /migrate

Migra toda la lógica del servicio legacy al arquetipo destino generado por Fabrics.

## Prerequisitos

1. Haber corrido `/clone <servicio>` — deja `legacy/`, `umps/`, `tx/`, `gold-ref/`, `COMPLEXITY_*.md`.
2. Haber corrido `/fabric` — deja `destino/tnd-msa-sp-<servicio>/` con el scaffold base.
3. Estar **dentro** de `destino/tnd-msa-sp-<servicio>/` o en la raíz del workspace (el comando detecta ambos).

## Paso 1 — Detectar modo

Leer `COMPLEXITY_<servicio>.md` y `migration-context.json` en `destino/`:

- Si `projectType=rest` → cargar el prompt interno `prompts.migrate-rest` (análogo a `migracion/REST/02-REST-migrar-servicio.md` del repo de referencia)
- Si `projectType=soap` → cargar `prompts.migrate-soap`
- Si hay ambigüedad → preguntar al usuario.

## Paso 2 — Lanzar agente migrador

Usar el sub-agente `migrador` (definido en `.claude/agents/migrador.md` del proyecto) con este contexto:

- `legacy/` — fuente original (ESQL, WSDL, XSDs, msgflows)
- `umps/` — UMPs asociados con sus ESQL (para extraer TX reales)
- `gold-ref/` — proyecto gold (0024 para REST, 0015 para SOAP) como referencia de patrones
- `destino/tnd-msa-sp-<servicio>/` — destino donde se implementa
- `COMPLEXITY_<servicio>.md` — análisis previo

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

- **Modo:** REST + WebFlux / SOAP + Spring MVC
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
7. **Si el ANALISIS dice `ATTENTION_NEEDED_REST_WITH_DB`** (1 op + DB), usar R2DBC o blocking boundary con `Schedulers.boundedElastic()` — NUNCA HikariCP+JPA en el request path de WebFlux.
