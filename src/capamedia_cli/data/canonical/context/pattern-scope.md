---
name: pattern-scope
kind: context
priority: 2
summary: Matriz empirica patron x scope - cuales reglas aplican a BUS, WAS, ORQ basado en analisis de 42 servicios reales del banco
---

# Pattern Scope — matriz empirica reglas × patrones

> **Fuente**: analisis empirico de 42 servicios desplegados en disco del banco
> (BUS-WebFlux 0006-0030/0077-0122 + WAS 0010/0026/0090/WSTecnicos\* + ORQ
> 0002-0071) ejecutado el 2026-05-31 por el panel de subagentes del CLI.
>
> **Proposito**: documentar QUE reglas del canonical aplican a QUE patrones,
> con evidencia. Sirve como referencia humana y como guia para `source_type`
> guards en `core/checklist_rules.py`. NO duplica el contenido de las reglas
> — solo las clasifica.

## Los 3 patrones reales (verificados empiricamente)

| Patron | Servicios ejemplo | Stack | BANCS | Logger dominante | HeaderRequestValidator |
|---|---|---|---|---|---|
| **BUS-WebFlux + BANCS** | 0077, 0013, 0007, 0011, 0012, 0015, 0020, 0030, 0078, 0101, 0122 | `webflux` (o `web-services` en 0015) | sí (`lib-bnc-api-client`) | **`@BpLogger`** (12/13 OLA1 puro) | sí (11/13) |
| **WAS-SOAP-JPA** | 0010, 0026, 0090, WSTecnicos 0004/0006/0008/0036/0039/0076 | `web-services` + a veces `data-jpa` | no | **`@Slf4j`** (8/8 universal) | no |
| **ORQ-WebFlux-downstream** | 0022, 0002, 0005, 0016, 0023, 0027, 0028, 0029, 0037, 0059, 0062, 0071 | `webflux` puro | no (`invocaBancs=false`) | mezcla: 8 `@Slf4j` + 2 `@BpLogger` outliers | mezcla 5/12 |

> **Caso especial — batch viejo `lote-20260421`**: algunos BUS migrados antes
> (WSReglas0010, WSTecnicos0006) usan `@Slf4j` lombok. Conviven con el batch
> nuevo OLA1 que usa `@BpLogger`. **Es deuda real del banco**, no del canonical.

## Matriz reglas × patrones (resumen)

Notacion: `U` = universal · `B` = bus · `W` = was · `O` = orq · `B+BANCS` = bus con `invocaBancs=true`.

| Regla del monolito | BUS+BANCS | BUS sin BANCS | WAS | ORQ | Estado en CLI |
|---|:--:|:--:|:--:|:--:|---|
| 1 — Capas hexagonales puras | U | U | U | U | `run_block_1` UNIVERSAL ✅ |
| 2 — Matriz MCP (override) | U (entry) | U | U | U | `run_block_0` ya filtra ✅ |
| 3 — `@BpTraceable` en controllers | U | U | U? | U | check 2.1 UNIVERSAL — duda WAS-SOAP `@Endpoint` |
| **4 — `@BpLogger` en services** | **MUST** | preferido | **`@Slf4j` aceptado** | mezcla aceptada | **check 2.5 NECESITA GUARD** (ver abajo) |
| 5 — Sin navegacion cruzada | U | U | U | U | `run_block_1` UNIVERSAL ✅ |
| 6 — Service Purity | U | U | U | U | UNIVERSAL ✅ |
| 6.5 / 9f — `spring.header.*` | U | U | U | U | UNIVERSAL ✅ |
| 7 — yml sin defaults | U | U | U | U | UNIVERSAL ✅ |
| 8 — `lib-bnc-api-client` | **MUST** | NO | NO | NO | `run_block_0` 0.2d filtra ✅ |
| 8.5 baseline Spring Boot | U | U | U | U | `run_block_8` 8.1 UNIVERSAL ✅ |
| 8.5 Netty pin (excepcion WebFlux) | **MUST** | MUST (si webflux) | NO | MUST (si webflux) | `_project_uses_webflux` filtra ✅ |
| 9 — `catalog-info.yaml` | U | U | U | U | UNIVERSAL ✅ |
| 9g — Configurables legacy en yml | U | U | U | U | UNIVERSAL ✅ |
| 9h — `pdb: minAvailable: 1` Helm | NO | NO | **MUST (SOAP)** | NO | sin check automatico todavia |
| 9h.1/9h.2 — Capacity baseline | U | U | U | U | UNIVERSAL ✅ |
| 9i — Hikari connection-test-query | NO | NO | **MUST (si JPA)** | NO | `run_block_13` 13.11 filtra ✅ |
| 9j — recurso/componente migrado | U | U | U | U | UNIVERSAL ✅ |
| 10 / 11 — IIB-specific (CSV/properties) | bus/iib | bus/iib | NO | bus/iib (ORQ es IIB) | sin check automatico |
| 10.5 — ORQ apunta al migrado | NO | NO | NO | **MUST** | `run_block_20` filtra ✅ |
| Block 17 — Log transaccional | NO | NO | NO | **MUST** | `_looks_like_orq` filtra ✅ |
| Block 18 — Log transaccional indebido | **MUST** | MUST | MUST | NO | filtra negativo ✅ |

> Las reglas con ✅ ya estan correctamente filtradas en el CLI. La unica regla
> con problema empirico confirmado es **#4 (Check 2.5 — `@Slf4j` prohibido
> universal)**. Las dudas marcadas con `?` requieren confirmacion del banco
> antes de cambiar el CLI.

## Decisiones aplicadas en el CLI (consecuencia de esta matriz)

### Check 2.5 (`@Slf4j` prohibido) — guard por `source_type`

**Antes (commits previos al Lote D)**: la regla era universal — disparaba HIGH en
cualquier servicio que tuviera `import org.slf4j.` o `@Slf4j`. Esto generaba
falsos HIGH en WAS y ORQ que usan ese patron legitimamente.

**Despues (Lote D Etapa C)** — el check 2.5 aplica esta tabla:

| Patron detectado | Severidad si hay `@Slf4j` | Justificacion |
|---|---|---|
| BUS + `invocaBancs=true` (BANCS corporativo) | **HIGH** | El stack corporativo BANCS exige `@BpLogger` (12/13 servicios) |
| BUS sin BANCS | **MEDIUM** | preferido `@BpLogger`, pero hay batch viejo con `@Slf4j` |
| WAS | **MEDIUM** (no HIGH) | 8/8 WAS reales usan `@Slf4j` — es el patron de facto |
| ORQ | **MEDIUM** | mezcla observada (8/12 `@Slf4j`, 2/12 `@BpLogger`) |
| `unknown` / sin migration-context | **HIGH** (fallback conservador) | sin info de patron, asumir corporativo |

El degrade a MEDIUM (en vez de tolerar 100%) preserva la **señal** para que el
equipo sepa que hay una mezcla; pero no bloquea el merge en patrones donde
empiricamente el banco ya tiene `@Slf4j` desplegado en produccion.

## Casos especiales (auditoria del 2026-05-31)

- **WSClientes0006**: deuda mixta REAL — `@BpLogger` Y `@Slf4j` en el mismo
  archivo. Debe consolidarse en uno solo (el equipo de BUS-OLA1 prefiere
  `@BpLogger`).
- **WSClientes0024 / 0046 / 0154 (OLA1)**: destinos casi vacios. Migraciones
  no iniciadas o abortadas — no aplicar checks hasta que tengan codigo.
- **ORQClientes0029 / 0037**: outliers — son los unicos ORQ que usan
  `@BpLogger`. Si el banco define que ORQ debe usar `@BpLogger`, el resto
  (10/12 ORQ) tiene deuda; si define `@Slf4j`, estos 2 son outliers.
- **WSReglas0010 + WSTecnicos0006**: BUS migrados antes (lote viejo) con
  `@Slf4j`. Son la unica razon por la que BUS sin BANCS es MEDIUM y no HIGH.

## Decisiones pendientes (esperan confirmacion del banco)

1. **¿BUS sin BANCS debe usar `@BpLogger` o tolera `@Slf4j`?** El batch nuevo
   OLA1 dice `@BpLogger`; el batch viejo `lote-20260421` muestra `@Slf4j`.
2. **¿ORQ debe usar `@BpLogger` o `@Slf4j`?** La mezcla 8/2 sugiere que no
   hay consenso operativo.
3. **¿WSClientes0006 mezcla `@BpLogger`+`@Slf4j` es deuda o aceptable?**
4. **¿`@BpTraceable` aplica a `@Endpoint` de Spring WS (WAS-SOAP)?** El check
   2.1 hoy lo asume universal, pero el monolito habla solo de
   `@RestController`.

## Referencias

- Auditoria empirica: ver agente F del 2026-05-31 (output guardado en
  `/tmp/svc_results.json` en la maquina del owner).
- Servicios analizados (38/42 con codigo): listados en la matriz de arriba.
- Implementacion del guard 2.5: `core/checklist_rules.py::run_block_2` con
  acceso a `ctx.source_type` y `ctx.has_bancs`.
