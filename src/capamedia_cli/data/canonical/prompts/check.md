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
- `migration-context.json` del destino — tipo, operaciones, UMPs y parametros MCP
- `COMPLEXITY_<servicio>.md` si existe
- `MIGRATION_REPORT.md` del destino
- `bank-mcp-matrix.md` como fuente unica de la decision REST/WebFlux, REST/MVC o SOAP/MVC

## Paso 2 — Ejecutar BLOQUE 0 con diálogo cruzado legacy ↔ migrado

### Check 0.1 — Tipo de proyecto
- `grep @RestController` y `grep @Endpoint` en `src/main/java`
- Determinar REST vs SOAP

### Check 0.2 — Matriz BPTPSRE con diálogo conversacional

Contar operaciones en:
- WSDL del migrado (`src/main/resources/legacy/*.wsdl`)
- WSDL del legacy original (si path provisto)

Producir literal este diálogo:

```
¿Cuántas operaciones tiene el WSDL? → N
¿Qué fuente y overrides MCP aplican? → WAS/BUS/ORQ + invocaBancs/deploymentType
¿Qué stack corresponde según bank-mcp-matrix.md? → REST+WebFlux / REST+MVC / SOAP+MVC
¿Qué framework se usó en la migración? → <actual>
¿Coincide lo usado con lo que la matriz pide? → SÍ ✅ / NO ❌
Veredicto: PASS / HIGH mal-clasificado
```

Diálogos por caso:
- BUS/IIB + BANCS → *"Regla 1: BANCS fuerza REST+WebFlux, con 1 o N operaciones."*
- ORQ/orquestador → *"Regla 2: orquestador fuerza REST+WebFlux + lib-event-logs."*
- WAS + 1 op → *"Caso base WAS: 1 op va REST+Spring MVC."*
- WAS + 2+ ops → *"Regla 3: SOAP+Spring MVC."*
- BUS/IIB sin BANCS + 1 op → *"Caso base BUS sin BANCS: REST+WebFlux."*
- BUS/IIB sin BANCS + 2+ ops → *"Regla 3: SOAP+Spring MVC."*
- Cualquier mismatch → HIGH con la regla exacta incumplida; no sugerir otro stack sin citar `bank-mcp-matrix.md`.

### Check 0.3 — Nombres de operaciones coinciden (legacy vs migrado)

Extraer `<wsdl:operation name="...">` de cada WSDL, diff. Si hay diferencias → HIGH.

### Check 0.4 — `targetNamespace` coincide

Si difiere → HIGH (rompe consumidores existentes).

### Check 0.5 — XSDs referenciados presentes

Todo `schemaLocation` del WSDL debe existir en `src/main/resources/`. Si falta → HIGH.

## Paso 3 — Ejecutar BLOQUES 1 a 14

Los bloques están documentados en el prompt canónico `prompts.checklist-rules` (espejo del `post-migracion/03-checklist.md`):

- **BLOQUE 1** — Arquitectura hexagonal (capas, domain sin framework, puertos como **interfaces** —NUNCA abstract classes—, único port Bancs)
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
- **BLOQUE 14** — SonarLint binding (.sonarlint/connectedMode.json, org=bancopichinchaec, projectKey no placeholder) + higiene de `.gitignore` para artefactos locales CapaMedia/AI

## Paso 4 — Generar reporte

Escribir `CHECKLIST_<servicio>.md` con esta estructura:

```markdown
# Post-Migration Checklist Report
**Project:** <path>
**Service:** <name>
**Type:** SOAP | REST
**Framework matrix:** canonical rules (no servicio-gold reference)
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

### 0.2 BPTPSRE matrix — ✅ PASS
¿Cuántas operaciones tiene el WSDL? → 1
¿Qué fuente y overrides MCP aplican? → WAS, microservicio, sin BANCS
¿Qué framework corresponde? → REST + Spring MVC
¿Qué framework se usó? → REST + Spring MVC
¿Coincide? → SÍ ✅
Veredicto: **PASS** — *"Caso base WAS: 1 op va REST+Spring MVC."*

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
