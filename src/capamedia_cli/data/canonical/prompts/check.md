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

## Paso 3 — Ejecutar los bloques activos (`ALL_BLOCKS`)

**Fuente unica:** la lista oficial vive en `ALL_BLOCKS` dentro de
`capamedia_cli/core/checklist_rules.py`. **17 bloques activos** con IDs no
contiguos (faltan 4, 6, 9, 10, 11, 12 numericamente; no son bugs, son IDs
reservados/refactorizados). El prompt `checklist-rules.md` documenta el detalle
textual y debe ser espejo de `ALL_BLOCKS` — si discrepa, gana el codigo.

| ID | Titulo |
|---|---|
| 0  | Pre-check + cross-check WSDL legacy vs migrado + matriz MCP |
| 1  | Arquitectura hexagonal (capas, ports como interfaces, output port Bancs unico, service purity) |
| 2  | Logging y tracing (`@BpTraceable`, `@BpLogger`, sin `org.slf4j`/`@Slf4j`) |
| 3  | Naming profesional (sin nombres genericos, camelCase methods, PascalCase `@PayloadRoot.localPart`) |
| 5  | Error handling y propagacion Bancs (HTTP 200 para errores, backend codes del catalogo, FATAL/ERROR/INFO) |
| 7  | Config externa (`application.yml` sin defaults inline, `${CCC_*}` en 3 Helms, HPA `100m`, catalog/pipeline namespace) |
| 8  | Versiones y dependencias (Spring Boot baseline, Undertow prohibido, webflux/web-services segun stack, Peer Review score >= 7) |
| 13 | Persistence (HikariCP+JPA solo cuando hay DB; `connection-test-query` SQL Server=`SELECT 1` / Oracle=`SELECT 1 from dual`; ddl-auto validate; open-in-view false) |
| 14 | SonarLint binding (`.sonarlint/connectedMode.json` versionado, org=`bancopichinchaec`, projectKey real) + higiene `.gitignore` |
| 15 | Estructura de error oficial (8 campos del PDF BPTPSRE) + librerias opcionales (Audit Log Reactive, Stratio Connector) |
| 16 | SonarCloud custom rule: test classes con anotacion (`@SpringBootTest` / `@WebMvcTest` / `@ExtendWith`) |
| 17 | Log transaccional ORQ obligatorio (`lib-event-logs-webflux`, `spring.kafka`, `@EventAudit`) |
| 18 | Log transaccional indebido en no-ORQ (WAS/BUS/UMP no deben tener `lib-event-logs-*` ni `@EventAudit`) |
| 19 | Properties delivery audit (`.capamedia/inputs/<file>.properties` entregados por el owner) |
| 20 | ORQ apunta al servicio MIGRADO, no al legacy (`sqb-msa-<svc>` / `ws-<svc>-was` como endpoint es FAIL) |
| 21 | TX mapping Java vs `application.yml` (`transactionId` / `@BancsService` deben coincidir con `bancs.webclients.ws-txNNNNNN`) |
| 22 | Discovery edge cases (`LINK WSDL`, observaciones, integraciones; cada codigo con decision/archivo/test, sin pendientes) |

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
