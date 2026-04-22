---
name: log-transaccional-orq
kind: context
priority: 2
summary: Log transaccional (lib-event-logs) — OBLIGATORIO en orquestadores, OPCIONAL en BUS/WAS terminales
---

# Log transaccional (lib-event-logs) — reglas para orquestadores

**Fuente**: `BPTPSRE-Librería Log Transaccional-220426-202920.pdf`. La librería
`com.pichincha.common:lib-event-logs-*` publica el request/response al tópico
Kafka de auditoría cuando el microservicio invoca a otros via `WebClient` o
`RestClient`.

**Aplica OBLIGATORIO a orquestadores** (ORQ). En BUS/WAS terminales aplica
solo si el servicio tiene downstream calls auditables; si es un servicio
atómico que termina en BANCS vía Core Adapter, NO aplica.

---

## Regla LT-1 — Dependencia `lib-event-logs-*`

**MUST**: `build.gradle` de un ORQ declara la variante que coincide con el
framework del proyecto:

- **WebFlux** (ORQs por regla + BUS con `invocaBancs=true`):
  ```gradle
  implementation 'com.pichincha.common:lib-event-logs-webflux:1.0.0'
  ```
- **MVC** (WAS):
  ```gradle
  implementation 'com.pichincha.common:lib-event-logs-mvc:1.0.0'
  ```

**NEVER**: declarar la variante equivocada (`webflux` en un WAS o `mvc` en un
ORQ). Rompe en runtime al cargar el autoconfig.

## Regla LT-2 — Bloque `spring.kafka` + `logging.event` en `application.yml`

**MUST**: el yml tiene los 2 bloques en este orden exacto, con env vars sin
default (respetando Regla 7 oficial del banco):

```yaml
spring:
  kafka:
    security:
      protocol: PLAINTEXT               # literal OK (no es secreto)
    properties:
      sasl:
        mechanism: PLAIN                # literal OK
        jaas:
          config: ""                    # literal vacio
      bootstrap:
        servers: ${KAFKA_SERVER}        # env var sin default
      session:
        timeout:
          ms: 45000                     # literal OK (constante del framework)
      request:
        timeout:
          ms: 2000
    producer:
      key-serializer: org.apache.kafka.common.serialization.StringSerializer
      value-serializer: org.apache.kafka.common.serialization.StringSerializer

logging:
  level:
    org:
      apache:
        kafka: OFF                      # OBLIGATORIO: apaga logs de kafka en el pod
  event:
    mode: 'EXTERNAL'                    # literal
    kafka:
      topic:
        name: ${KAFKA_TOPIC_AUDITOR}    # env var sin default
    excluded-paths: /actuator/**,/health,/metrics,/prometheus
    executor:
      isDefault: false
      corePoolSize: ${THREAD_CORE_POOL_SIZE}
      maxPoolSize: ${THREAD_MAX_POOL_SIZE}
      keepAliveTime: ${THREAD_KEEP_ALIVE_TIME}
      queueSize: ${THREAD_QUEUE_SIZE}

xml:
  template:
    templates:
      "201000101": ${XML_TRANSACCION_0001}   # id de tipoTransaccion → template XML via env
```

**NEVER**:
- Omitir `logging.level.org.apache.kafka: OFF` (el pod se llena de logs Kafka)
- Hardcodear `KAFKA_SERVER`, `KAFKA_TOPIC_AUDITOR`, `XML_TRANSACCION_*`
- Usar `spring.kafka.*` sin `logging.event.*` — va junto, el uno sin el otro no sirve

## Regla LT-3 — Anotación `@EventAudit` en adapters

**MUST**: cada adapter outbound (`@Component implements XxxPort`) lleva
`@EventAudit` en el método que invoca el downstream:

```java
// WebFlux (ORQ)
@Component
@RequiredArgsConstructor
public class WSClientes0001Adapter implements Clientes0001Port {
    private final WebClient wsclientes0001WebClient;

    @Override
    @EventAudit(
        service = "WSClientes0001",
        method = "ConsultarCuentasActivas01",
        type = AuditType.T
    )
    public Mono<ConsultarCuentasActivas01ResponseDto> consultarCuentasActivas01(...) {
        // ...
    }
}

// MVC (WAS)
@Component
@RequiredArgsConstructor
public class WSClientes0001RestAdapter implements Clientes0001Port {
    protected final RestClientFactory restClientFactory;
    protected RestClient restClient;

    @Override
    @EventAudit(
        service = "WSClientes0001",
        method = "ConsultarCuentasActivas01",
        type = AuditType.T
    )
    public ConsultarCuentasActivas01ResponseDto consultarCuentasActivas01(...) {
        // ...
    }
}
```

**Parámetros obligatorios**:
- `service`: nombre literal del servicio downstream (ej `"WSClientes0001"`)
- `method`: nombre de la operación invocada (ej `"ConsultarCuentasActivas01"`)
- `type`: `AuditType.T` (transaccional) siempre en este caso

**NEVER**:
- Dejar `@EventAudit` sin `service`, `method`, o `type` — es invalido
- Poner `@EventAudit` en services (`@Service`): va **solo en adapters** (`@Component`)
- Mezclar múltiples `@EventAudit` en un mismo método (uno por método público de adapter)

## Regla LT-4 — Templates XML de transformación

**MUST**: cada tipo de transacción usado por el ORQ tiene una entrada en
`xml.template.templates` del yml. El valor viene de env var
(`XML_TRANSACCION_<NNNN>`) que en Helm se setea con el string XML completo
desde el ConfigMap o un valor shared del banco.

Formato del template XML (referencia del PDF):

```xml
<PLANTILLA servicio="WSClientes0001" metodo="ConsultarCuentasActivas01">
    <TX cargaFuente="*" />
    <RX cargaFuente="cuentas">
        <coleccion nombrePadre="corrientes" nombreHijo="corriente" fuentePadre="...">
            <campo nombre="numeroCuenta" fuente="/" nomenclatura="numeroCuenta" />
            <campo nombre="tipo" fuente="/" nomenclatura="tipo" />
        </coleccion>
    </RX>
</PLANTILLA>
```

**NEVER**: hardcodear el XML en el yml. El template entero va por env var para
que cada ambiente (dev/test/prod) pueda tener variantes sin rebuild.

---

## Automatización en el CLI

- `capamedia check` incluye el nuevo bloque **Block 17 — Log transaccional
  (ORQ)** que valida:
  - `17.1`: dependencia `lib-event-logs-*` correcta según framework
  - `17.2`: bloques `spring.kafka` + `logging.event` en el yml
  - `17.3`: `logging.level.org.apache.kafka: OFF` presente
  - `17.4`: al menos 1 `@EventAudit` en los adapters del proyecto
  - Solo se activan si `source_kind == "orq"`. Para BUS/WAS no corre
    (evitar falsos positivos).

- `capamedia check --auto-fix --bank-fix` agrega las dependencias faltantes
  automático en ORQs.

- Mensaje de salida del bloque 17 incluye link al PDF:
  `prompts/documentacion/BPTPSRE-Librería Log Transaccional-220426-202920.pdf`.
