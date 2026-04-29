---
name: bank-mcp-matrix
kind: context
priority: 1
summary: Matriz oficial BPTPSRE-Modos de uso - 3 reglas de override MCP + 8 templates por caso de uso
---

# Matriz oficial MCP del banco (BPTPSRE-Modos de uso)

**Fuente**: PDF `BPTPSRE-Modos de uso-230426-214957` del equipo BPTPSRE
(Banco Pichincha). Este archivo es la **fuente de verdad** para decidir
que framework/archetype genera el MCP Fabrics segun los parametros ingresados.

## Los 4 parametros MCP

| Parametro | Valores | Descripcion |
|---|---|---|
| `tecnologia` | `bus` \| `was` | Tecnologia ORIGEN del legacy (IIB o WebSphere) |
| `projectType` | `rest` \| `soap` | Tipo de contrato del servicio migrado |
| `framework` | `mvc` \| `webflux` | Framework Spring (blocking o reactive) |
| `invocaBancs` | `true` \| `false` | Flag de override: si true, forza webflux+rest |
| `deploymentType` | `microservicio` \| `orquestador` | Tipo de despliegue; orquestador agrega `lib-event-logs` |

## Las 3 reglas de override (en orden de prioridad)

La matriz del PDF define 3 reglas. Se aplican **en orden** — la primera que
matchee gana, los demas parametros quedan ignorados.

### Regla 1 — `invocaBancs: true` (override total)

**Si el usuario pasa `invocaBancs: true`**, el MCP genera `webflux + rest`
**siempre**, ignorando cualquier combinacion de `projectType` / `framework`
que el usuario haya pasado.

```yaml
# Parametros ingresados
invocaBancs: true
deploymentType: microservicio    # o orquestador
framework: mvc                    # IGNORADO
projectType: soap                 # IGNORADO

# Arquetipo generado
framework: webflux                # override
projectType: rest                 # override
```

**Por que**: cualquier servicio que hable con BANCS tiene que ser reactive
(WebFlux) para manejar las connections del pool sin bloquear.

### Regla 2 — `deploymentType: orquestador` + `invocaBancs: false`

**Si el usuario pasa `deploymentType: orquestador`** (y no invocaBancs=true
que ya matcheo la Regla 1), el MCP genera `webflux + rest` + **incluye
`lib-event-logs`**.

```yaml
# Parametros ingresados
deploymentType: orquestador
invocaBancs: false                # NO invoca BANCS directo
framework: mvc/webflux            # IGNORADO
projectType: rest/soap            # IGNORADO

# Arquetipo generado
framework: webflux
projectType: rest
# + dependencia lib-event-logs (log transaccional)
```

**Por que**: los orquestadores coordinan multiples servicios externos y el
banco requiere log transaccional obligatorio para auditoria (PDF BPTPSRE
Log Transaccional). Los servicios downstream migrados son los que hablan
con BANCS, el ORQ solo coordina.

### Regla 3 — `projectType: soap` + `deploymentType: microservicio` + `invocaBancs: false`

**Si el usuario pasa `projectType: soap`** (y `microservicio`, sin BANCS),
el MCP genera `mvc + soap` + **incluye `spring-web-service`**.

```yaml
# Parametros ingresados
projectType: soap
deploymentType: microservicio
invocaBancs: false
framework: mvc/webflux            # se fuerza a mvc

# Arquetipo generado
framework: mvc
projectType: soap
# + dependencia spring-web-service (Spring WS)
```

**Por que**: SOAP en Spring requiere el dispatcher `MessageDispatcherServlet`
de Spring WS, que solo funciona sobre Spring MVC (no WebFlux).

## Matriz completa — 8 casos canonicos

Combinando las 3 reglas con los casos reales del banco:

| # | Servicio tipico | tecnologia | projectType | framework | invocaBancs | deploymentType | Regla aplicada |
|---|---|---|---|---|---|---|---|
| 1 | WAS base de datos, **1 metodo** | `was` | `rest` | `mvc` | `false` | `microservicio` | — (caso base) |
| 2 | WAS base de datos, **2+ metodos** | `was` | `soap` | `mvc` | `false` | `microservicio` | **Regla 3** → mvc+soap + spring-web-service |
| 3 | WAS procesamiento interno, **1 metodo** | `was` | `rest` | `mvc` | `false` | `microservicio` | — (caso base) |
| 4 | WAS procesamiento interno, **2+ metodos** | `was` | `soap` | `mvc` | `false` | `microservicio` | **Regla 3** → mvc+soap + spring-web-service |
| 5 | **BUS con BANCS** (1 o varios metodos) | `bus` | `rest` | `webflux` | **`true`** | `microservicio` | **Regla 1** → webflux+rest (override total) |
| 6 | BUS Apis sin BANCS, **1 metodo** | `bus` | `rest` | `webflux` | `false` | `microservicio` | — (caso base) |
| 7 | BUS sin BANCS, **2+ metodos** | `bus` | `soap` | `mvc` | `false` | `microservicio` | **Regla 3** → mvc+soap + spring-web-service |
| 8 | **ORQ (Orquestador)** | `bus` | `rest` | `webflux` | **`false`** | **`orquestador`** | **Regla 2** → webflux+rest + **lib-event-logs** |

### Detalles importantes

- **WAS siempre es `framework: mvc`**, nunca WebFlux. Aunque sea 1 op REST,
  el banco usa MVC con un `@RestController` sobre Tomcat (no Netty reactive).
- **BANCS solo aplica a BUS/IIB con `invocaBancs: true`**. En WAS, ORQ y
  BUS/IIB sin BANCS esta prohibido agregar o mantener `lib-bnc-api-client`,
  `BancsService`, `BancsClientHelper`, `bancs.webclients`, `CCC_BANCS_*` o
  `dependsOn: lib-bnc-api-client`.
- **ORQ no invoca BANCS directamente**. Los servicios downstream migrados
  (`<ns>-msa-sp-<svc>` en `tpl-middleware`) son los que hablan con BANCS.
  Por eso `invocaBancs: false` para ORQ.
- **Lo que define un ORQ es `deploymentType: orquestador`**, no `invocaBancs`.
- **BUS con 2+ ops sin BANCS** cae en Regla 3 → mvc+soap (caso raro pero
  valido segun PDF).
- **`spring.header.channel: digital` + `spring.header.medium: web`** son
  literales mandatorios siempre (ver Regla 9f de `bank-official-rules.md`).

## Como el CLI lo aplica

### Deteccion del source_type del legacy

```python
# capamedia_cli/core/legacy_analyzer.py
def detect_source_kind(legacy_root: Path, service_name: str) -> str:
    if service_name.lower().startswith("orq"):
        return "orq"   # -> tecnologia=bus, deploymentType=orquestador, invocaBancs=false
    if ".esql" in legacy_root.rglob("*"):
        return "iib"   # -> tecnologia=bus
    if "web.xml" in legacy_root.rglob("*"):
        return "was"   # -> tecnologia=was
    return "unknown"
```

### Mapeo a parametros MCP (fabrics generate)

| `source_type` detectado | tecnologia | deploymentType | Otros |
|---|---|---|---|
| `was` | `was` | `microservicio` | projectType/framework segun ops (1=mvc+rest, 2+=mvc+soap) |
| `iib` + has_bancs | `bus` | `microservicio` | Regla 1: invocaBancs=true → webflux+rest |
| `iib` sin bancs + 1 op | `bus` | `microservicio` | framework=webflux, projectType=rest |
| `iib` sin bancs + 2+ ops | `bus` | `microservicio` | Regla 3: projectType=soap → mvc |
| `orq` | `bus` | **`orquestador`** | Regla 2: deploymentType=orquestador → webflux+rest + lib-event-logs |

### Block 0 del checklist (run_block_0)

El Check 0.2c compara el framework **esperado** (segun matriz MCP) con el
framework **actual** (detectado en el codigo migrado). Si no coinciden:

- `FAIL HIGH` con mensaje "MAL-CLASIFICADO — segun Regla N MCP deberia ir {X}"
- `suggested_fix` dice exactamente que cambiar

Implementado en `_expected_framework()` de `checklist_rules.py`.

## Regla para el agente migrador

Al correr `/migrate`:

1. **Leer el source_type** del workspace (`legacy/` o `.capamedia/config.yaml`).
2. **Mapear a parametros MCP** usando la tabla de arriba.
3. **Validar que el codigo migrado cumple la Regla aplicable**:
   - Si es ORQ → `build.gradle` debe tener `lib-event-logs` (Regla 2)
   - Si es SOAP + microservicio → `build.gradle` debe tener `spring-boot-starter-web-services` (Regla 3)
   - Si es invocaBancs → framework DEBE ser WebFlux (`reactor-core` en deps) (Regla 1)
4. **NUNCA** generar codigo `@Endpoint` + Spring WS en un servicio con
   `invocaBancs: true` — contradice la Regla 1 y no compila bien con BANCS.
5. **NUNCA** omitir `lib-event-logs` en un ORQ — viola la Regla 2 del banco.
