---
name: check
title: Ejecutar la checklist BPTPSRE post-migracion
description: Corre los 14 bloques del checklist oficial contra el destino migrado, cruzando con el legacy. Produce CHECKLIST_*.md con diálogo conversacional, severidad y veredicto.
type: prompt
scope: project
stage: post-migration
source_kind: any
framework: any
complexity: medium
preferred_model:
  anthropic: claude-opus-4-7
fallback_model: opus
allowed_tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Write
---

# /check (alias: /post-migrate)

Audita el proyecto migrado contra el checklist oficial del equipo **BPTPSRE** de Banco Pichincha. Produce un reporte estructurado con pass/fail por bloque, severidad (HIGH/MEDIUM/LOW) y acción sugerida.

**NO modifica código.** Solo audita y reporta. Los fixes se hacen en un flujo aparte (opcionalmente puede ofrecer aplicarlos al final si el usuario lo pide).

## Input

- `<MIGRATED_PATH>` (default: CWD si detecta `build.gradle` + `src/`) — el proyecto migrado
- `<LEGACY_PATH>` (opcional, default: `../legacy/sqb-msa-<servicio>`) — para análisis cruzado de BLOQUE 0

## Paso 1 — Cargar contexto

Leer:
- `migration-context.json` del destino — tipo, operaciones, UMPs
- `COMPLEXITY_<servicio>.md` si existe
- `MIGRATION_REPORT.md` del destino

## Paso 2 — Ejecutar BLOQUE 0 con diálogo cruzado legacy ↔ migrado

### Check 0.1 — Tipo de proyecto
- `grep @RestController` y `grep @Endpoint` en `src/main/java`
- Determinar REST vs SOAP

### Check 0.2 — Conteo de operaciones con diálogo conversacional

Contar operaciones en:
- WSDL del migrado (`src/main/resources/legacy/*.wsdl`)
- WSDL del legacy original (si path provisto)

Producir literal este diálogo:

```
¿Cuántas operaciones tiene el WSDL? → N
¿Qué framework corresponde según la matriz? → REST si 1, SOAP si 2+
¿Qué framework se usó en la migración? → <actual>
¿Coincide lo usado con lo que la matriz pide? → SÍ ✅ / NO ❌
Veredicto: PASS / HIGH mal-clasificado
```

Diálogos por caso:
- 1 op + REST → *"Es 1 op, va REST. ¿Está OK? Sí, está OK."*
- 2+ ops + SOAP → *"Son N ops, va SOAP. ¿Está OK? Sí, está OK."*
- 1 op + SOAP → HIGH *"Es 1 op → debió ir REST+WebFlux. Mal-clasificado."*
- 2+ ops + REST → HIGH *"Son N ops → REST+WebFlux no soporta dispatching multi-op."*
- 1 op + REST + DB → PASS con flag `ATTENTION_NEEDED_REST_WITH_DB`

### Check 0.3 — Nombres de operaciones coinciden (legacy vs migrado)

Extraer `<wsdl:operation name="...">` de cada WSDL, diff. Si hay diferencias → HIGH.

### Check 0.4 — `targetNamespace` coincide

Si difiere → HIGH (rompe consumidores existentes).

### Check 0.5 — XSDs referenciados presentes

Todo `schemaLocation` del WSDL debe existir en `src/main/resources/`. Si falta → HIGH.

## Paso 3 — Ejecutar BLOQUES 1 a 14

Los bloques están documentados en el prompt canónico `prompts.checklist-rules` (espejo del `post-migracion/03-checklist.md`):

- **BLOQUE 1** — Arquitectura hexagonal (capas, domain sin framework, puertos abstract class, único port Bancs)
- **BLOQUE 2** — Logging y tracing (`@BpTraceable`, `@BpLogger`, sin `org.slf4j`, log levels correctos)
- **BLOQUE 3** — Naming (camelCase methods, PascalCase `@PayloadRoot.localPart`)
- **BLOQUE 4** — Validaciones (HeaderRequestValidator, patterns externalizados via `@ConfigurationProperties`)
- **BLOQUE 5** — Error handling (BancsClientHelper wrapea RuntimeException, HTTP 200 para errores, backend codes del catálogo)
- **BLOQUE 6** — Mappers (MapStruct o manuales con Javadoc)
- **BLOQUE 7** — Config externa (application.yml, `${CCC_*}` env vars, Helm probes)
- **BLOQUE 8** — Versiones y dependencias (Spring Boot, Jackson, starter-webflux, jaxws-rt)
- **BLOQUE 9** — Tests y calidad (cobertura Jacoco, SonarLint)
- **BLOQUE 10** — SOAP specifics (si aplica)
- **BLOQUE 11-12** — REST specifics (si aplica)
- **BLOQUE 13** — WAS+DB (HikariCP config, ddl-auto validate, open-in-view false, @Transactional en service boundary)
- **BLOQUE 14** — SonarLint binding (.sonarlint/connectedMode.json, org=bancopichinchaec, projectKey no placeholder)

## Paso 4 — Generar reporte

Escribir `CHECKLIST_<servicio>.md` con esta estructura:

```markdown
# Post-Migration Checklist Report
**Project:** <path>
**Service:** <name>
**Type:** SOAP | REST
**Gold standard:** wsclientes0015 | wsclientes0024
**Date:** YYYY-MM-DD

## Summary
| Block | Pass | HIGH | MEDIUM | LOW |
|---|---|---|---|---|
| 0 Pre-check + cross | 4/5 | 1 | 0 | 0 |
| 1 Hexagonal | 5/5 | 0 | 0 | 0 |
| ... | | | | |
| **TOTAL** | **X/Y** | **N** | **N** | **N** |

**Verdict:** READY_TO_MERGE | BLOCKED_BY_HIGH | READY_WITH_FOLLOW_UP

## Block 0 — Pre-check + cross-check

### 0.2 Operation count — ✅ PASS
¿Cuántas operaciones tiene el WSDL? → 1
¿Qué framework corresponde? → REST + WebFlux
¿Qué framework se usó? → REST + WebFlux
¿Coincide? → SÍ ✅
Veredicto: **PASS** — *"Es 1 op, va REST. ¿Está OK? Sí, está OK."*

### 0.3 Operation names — ✅ PASS
(...)

## Block 1 — Arquitectura hexagonal
(...)
```

## Paso 5 — Responder conversacionalmente

```markdown
## Checklist ejecutado: <servicio>

**Resultado:** X/Y PASS · N HIGH · M MEDIUM

### Veredicto final: READY_TO_MERGE / BLOCKED / READY_WITH_FOLLOW_UP

### Issues HIGH (si hay)
1. **Check 1.4 — 2 output ports Bancs**
   Fix: consolidar en un único `BancsCustomerOutputPort`.
   Ref: feedback Jean Pierre García.

### Pregunta
¿Querés que aplique los fixes de severidad MEDIUM/LOW automáticamente?
Los HIGH siempre los revisás vos primero.
```

## Reglas importantes

1. **No modificar código.** Solo auditar.
2. **Severidad clara.** Cada fail tiene HIGH/MEDIUM/LOW + acción concreta.
3. **Cross-check obligatorio.** Si hay `<LEGACY_PATH>`, correr Checks 0.3/0.4. Si no, degradar a MEDIUM.
4. **Veredicto final explícito.** No dejar ambigüedad al lector del reporte.
