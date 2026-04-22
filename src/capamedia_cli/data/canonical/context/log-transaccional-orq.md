---
name: log-transaccional-orq
kind: context
priority: 2
summary: Log transaccional (lib-event-logs) — EXCLUSIVO de orquestadores (ORQ). WAS/BUS no lo usan.
---

# Log transaccional (lib-event-logs) — EXCLUSIVO de orquestadores

**Fuentes**:
- `prompts/documentacion/BPTPSRE-Estructura Log Transaccional-220426-215404.pdf` (estructura, flujo, mapeo)
- `prompts/documentacion/BPTPSRE-Librería Log Transaccional-220426-202920.pdf` (librería, dependencias, config)

**Característica oficial de la librería** (PDF 2, sección "Características"):
- Agnóstica a **Spring Boot 3.5.12** (no la hereda — convive con cualquier versión compatible).
- Compilada en **Java 21**.
- Existen dos variantes de artefacto (`-webflux` y `-mvc`), pero en el marco
  de esta migración **solo aplica la variante `-webflux`** porque por regla del
  banco los ORQs van siempre en WebFlux.

## Ámbito de aplicación — SOLO ORQ

**Cita literal del PDF 1** (sección "Eventos"):
> _"Los eventos se generan **únicamente en los orquestadores**."_

**Implicación dura**:
- ✅ **ORQ**: OBLIGATORIO. Todas las reglas LT-1..LT-7 de este canonical aplican.
- ❌ **WAS** (microservicios REST/MVC terminales): **NO** lleva `lib-event-logs`,
  **NO** lleva `@EventAudit`, **NO** lleva `spring.kafka` ni `logging.event` en
  el yml. Nada de esto. Si en revisión aparece en un WAS, es un error de copy-
  paste de un ORQ y debe removerse.
- ❌ **BUS** (servicios SOAP IIB migrados a Java): **NO** lleva log
  transaccional. El BUS audita vía IIB legacy / Core Adapter / sus propios
  mecanismos de trace. No usa esta librería.
- ❌ **UMPs** (stores/jpa embebidos en WAS): tampoco aplica — son componentes
  internos del WAS, no microservicios con operaciones auditables.

**Reglas operativas**:
- El Block 17 del `capamedia check` está gated por `_looks_like_orq(ctx)`. Si
  el proyecto no es ORQ (nombre de la carpeta / catalog-info), el bloque se
  omite por completo — no emite ni PASS ni FAIL.
- En un ORQ al que le falten estos componentes, el Block 17 emite FAIL severity
  `high`. En un WAS que accidentalmente los tenga, debe haber otra regla
  (futura) que los marque como "remove — WAS no usa log transaccional".

---

## Flujo de auditoría end-to-end (PDF 1)

```
 ┌───────────────────┐         ┌────────────┐        ┌────────────────────┐         ┌──────────────────────┐
 │ ORQClientes0003   │         │            │        │ WSTecnicos0038     │         │                      │
 │ (orquestador)     │  pub    │ CE_EVENTOS │  sub   │ (servicio técnico  │  pub    │ CE_TRANSACCIONAL     │
 │ @EventAudit →     │ ──────▶ │  (Kafka)   │ ─────▶ │  compartido del    │ ──────▶ │  (Kafka — lo consume │
 │ lib-event-logs    │         │            │        │  banco)            │         │  Elastic/Observabili-│
 │ serializa evento  │         │            │        │  aplica plantillas │         │  dad)                │
 └───────────────────┘         └────────────┘        │  XML→JSON lotElastico       └──────────────────────┘
                                                     └────────────────────┘
```

**Puntos clave del flujo**:

1. El **adapter del ORQ** (nuestro código) decora el método downstream con
   `@EventAudit`. La librería **intercepta** el request/response y construye el
   XML `<NS1:evento tipoEvento="T">` con headerIn + bodyIn + datos + bodyOut +
   error.
2. La librería **publica ese XML** en la cola `CE_EVENTOS` (Kafka). Nuestro ORQ
   termina ahí su responsabilidad.
3. `WSTecnicos0038` es un **servicio técnico compartido del banco** (no lo
   implementa cada equipo). Lee `CE_EVENTOS`, y por cada evento aplica las
   plantillas XML (`<PLANTILLA>`, `<TX>`, `<RX>`) para **mapear el XML del
   evento al JSON final** con estructura `logs.detalleOrquestador` /
   `logs.detalleMicroServicio` / `logs.lotElastico`.
4. Publica el JSON resultante en `CE_TRANSACCIONAL`, que es lo que finalmente
   consume Elastic/SIEM/Observabilidad.

**Implicación para nosotros**: nuestro código **NO** necesita construir el JSON
final ni conocer `WSTecnicos0038`. Solo necesita:
- La dependencia `lib-event-logs-*` correcta.
- `application.yml` con `spring.kafka` + `logging.event`.
- `@EventAudit` en cada adapter.
- Plantillas XML provistas por env (helm/ConfigMap).

---

## Regla LT-1 — Dependencia `lib-event-logs-webflux`

**MUST**: el `build.gradle` del ORQ declara la variante **webflux** (en este
programa de migración no hay ORQs MVC — todos van WebFlux por regla del banco):

```gradle
implementation 'com.pichincha.common:lib-event-logs-webflux:1.0.0'
```

**Prerrequisitos del proyecto** (PDF 2, sección "Prerequisitos"):
- Spring Boot 3.5.12 o superior compatible (la lib es agnóstica pero se probó
  contra esa versión).
- Java 21.

**Nota sobre la variante MVC**: el PDF 2 documenta también
`lib-event-logs-mvc:1.0.0`. No la usamos porque:
- Los ORQs son siempre WebFlux (regla del banco).
- Los WAS MVC **NO** llevan log transaccional (cita PDF 1: "los eventos se
  generan únicamente en los orquestadores").
- Por lo tanto `lib-event-logs-mvc` no debería aparecer en ningún proyecto de
  esta migración. Si aparece, es error de copy-paste y debe removerse.

**NEVER**:
- Agregar la dependencia en un WAS — NO aplica (es solo ORQ).
- Declarar la variante `mvc` — en nuestro marco no tiene uso legítimo.
- Usar una versión distinta de `1.0.0` sin actualizar este canonical primero.

## Regla LT-2 — Bloque `spring.kafka` + `logging.event` en `application.yml`

**MUST**: el yml tiene los 3 bloques en este orden, con env vars sin default
(respetando **Regla 7 oficial del banco**: nunca hardcodear valores de infra):

```yaml
spring:
  kafka:
    security:
      protocol: PLAINTEXT               # literal OK (no es secreto; en prod Helm lo sobrescribe a SASL_SSL)
    properties:
      sasl:
        mechanism: PLAIN                # literal OK
        jaas:
          config: ""                    # literal vacio (prod inyecta via secret)
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
        kafka: OFF                      # OBLIGATORIO: apaga logs de kafka en el pod (Cita PDF 2)
  event:
    mode: 'EXTERNAL'                    # literal — modo externo (publica a kafka, no logs locales)
    kafka:
      topic:
        name: ${KAFKA_TOPIC_AUDITOR}    # env var sin default — apunta a CE_EVENTOS
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
      "201000101": ${XML_TRANSACCION_0001}   # id de tipoTransaccion -> template XML completo via env
      # una entrada por cada tipoTransaccion que el ORQ invoca downstream
```

**Defaults documentados** (PDF 2, tabla de Atributos — todos REQUERIDOS=SI):

| Campo | Default | Nota |
|-------|---------|------|
| `spring.kafka.properties.sasl.mechanism` | `PLAIN` | |
| `spring.kafka.properties.security.protocol` | `SASL_SSL` | En dev usamos `PLAINTEXT` |
| `spring.kafka.properties.session.timeout.ms` | `45000` | |
| `spring.kafka.properties.request.timeout.ms` | `2000` | |
| `spring.kafka.producer.key-serializer` | `org.apache.kafka.common.serialization.StringSerializer` | |
| `spring.kafka.producer.value-serializer` | `org.apache.kafka.common.serialization.StringSerializer` | |
| `logging.event.mode` | `EXTERNAL` | |
| `logging.event.kafka.topic.name` | `${KAFKA_TOPIC_AUDITOR}` | |
| `logging.event.executor.isDefault` | `false` | |
| `logging.event.excluded-paths` | `${EXCLUDE_PATH}` | |

**NEVER**:
- Omitir `logging.level.org.apache.kafka: OFF` (el pod se llena de logs Kafka
  internos — cita textual del PDF 2).
- Hardcodear `KAFKA_SERVER`, `KAFKA_TOPIC_AUDITOR`, `XML_TRANSACCION_*` o los
  tamaños de threadpool.
- Usar `spring.kafka.*` sin `logging.event.*` — van juntos, el uno sin el otro
  no enciende la librería.
- Omitir el bloque `xml.template.templates` si el ORQ invoca downstream (sin
  templates, el mensaje final queda sin `lotElastico`).

## Regla LT-3 — Anotación `@EventAudit` en adapters (solo ORQ)

**MUST**: en un ORQ, cada adapter outbound (`@Component implements XxxPort`)
lleva `@EventAudit` en el método que invoca el downstream (WebClient). La
librería intercepta el request/response y publica el evento a `CE_EVENTOS`.

**Cliente HTTP en ORQ**: siempre `WebClient` (WebFlux). `RestTemplate` está
deprecado en Spring Boot 3.x. El PDF 2 muestra también un ejemplo `RestClient`
para la variante MVC, pero **NO aplica a nuestros ORQs** — se omite del
canonical para evitar confusión.

```java
// ORQ — adapter outbound con @EventAudit (unico caso valido en este programa)
@Component
@RequiredArgsConstructor
public class WSClientes0001Adapter implements Clientes0001Port {
    private final WebClient wsclientes0001WebClient;
    private static final String ERROR_MESSAGE = "Error consultando cuentas";
    private static final String ERROR_CODE_OK = "0";

    @Override
    @EventAudit(
        service = "WSClientes0001",
        method = "ConsultarCuentasActivas01",
        type = AuditType.T
    )
    public Mono<ConsultarCuentasActivas01ResponseDto> consultarCuentasActivas01(
            ConsultarCuentasActivas01RequestDto requestDto) {
        log.info("Invocando WSClientes0001 - ConsultarCuentasActivas01");
        return executeRequest(requestDto)
                .doOnNext(r -> log.info("Respuesta recibida de WSClientes0001: {}", r))
                .onErrorMap(this::mapError)
                .flatMap(this::validateResponse);
    }
}
```

**WAS: NO lleva `@EventAudit`** — si aparece en un adapter de un proyecto
`wstecnicos/wsclientes`, es error de copy-paste y debe removerse. Los WAS no
tienen adapters outbound a otros WS en el sentido que audita esta librería;
sus "downstream" son BANCS (vía Core Adapter) o UMPs (embebidos), ninguno
auditado por `lib-event-logs`.

**Parámetros obligatorios de `@EventAudit`** (PDF 2, tabla "Detalle de
componentes"):
- `service`: nombre literal del servicio downstream (ej `"WSClientes0001"`).
- `method`: nombre de la operación invocada (ej `"ConsultarCuentasActivas01"`).
- `type`: **`AuditType.T`** (transaccional) — es la única auditoría soportada
  por este tópico. Si aparecen otros tipos en el futuro (`AuditType.S`,
  `AuditType.N`), documentar en este canonical.

**NEVER**:
- Dejar `@EventAudit` sin `service`, `method`, o `type` — es inválido.
- Poner `@EventAudit` en services (`@Service`): va **solo en adapters
  outbound** (`@Component` que implementa un `Port`).
- Mezclar múltiples `@EventAudit` en un mismo método (uno por método público).
- Aparecer en un WAS — solo ORQ. Si aparece, removerlo.

## Regla LT-4 — Templates XML de transformación

**MUST**: cada tipoTransaccion usado por el ORQ tiene una entrada en
`xml.template.templates` del yml. El valor viene de env var
(`XML_TRANSACCION_<NNNN>`) que en Helm se setea con el string XML completo
desde el ConfigMap o desde el repo shared `Plantillas xml-shared`.

Formato del template XML (PDF 2, sección "Plantillas"):

```xml
<PLANTILLA servicio="WSClientes0001" metodo="ConsultarCuentasActivas01">
    <TX cargaFuente="*" />
    <RX cargaFuente="cuentas">
        <coleccion nombrePadre="corrientes" nombreHijo="corriente" fuentePadre="...">
            <campo nombre="numeroCuenta" fuente="/" nomenclatura="numeroCuenta" />
            <campo nombre="tipo" fuente="/" nomenclatura="tipo" />
        </coleccion>
        <coleccion nombrePadre="ahorros" nombreHijo="ahorro" fuentePadre="...">
            <campo nombre="numeroCuenta" fuente="/" nomenclatura="numeroCuenta" />
            <campo nombre="tipo" fuente="/" nomenclatura="tipo" />
        </coleccion>
        <coleccion nombrePadre="inversiones" nombreHijo="inversion" fuentePadre="...">
            <campo nombre="numeroOperacion" fuente="/" nomenclatura="numeroOperacion" />
            <campo nombre="tipo" fuente="/" nomenclatura="tipo" />
        </coleccion>
    </RX>
</PLANTILLA>
```

**Elementos del template**:
- `<TX cargaFuente="*" />`: regla de captura del **request** (bodyIn). `*`
  captura todo el payload de entrada.
- `<RX cargaFuente="cuentas">`: regla de captura del **response** (bodyOut).
  `cuentas` indica el nodo raíz de la respuesta.
- `<coleccion>`: mapea arrays del XML a arrays del JSON — cada uno con
  `nombrePadre` (nodo JSON), `nombreHijo` (elemento), y la lista de `<campo>`
  internos.
- `<campo nombre="X" fuente="/" nomenclatura="Y">`: mapea `X` del XML source
  al campo `Y` del JSON destino.

**NEVER**:
- Hardcodear el XML en el yml. El template entero va por env var para que cada
  ambiente (dev/test/prod) pueda tener variantes sin rebuild.
- Poner plantillas en `src/main/resources/` — **deben vivir en Helm/ConfigMap**
  (cita textual PDF 2: _"Estas plantillas deben ser colocados en el helm como
  variables de entorno"_).
- Omitir la plantilla de algún `tipoTransaccion` que el ORQ realmente invoca
  (`WSTecnicos0038` no podrá construir `lotElastico` y el registro Elastic
  queda parcial).

## Regla LT-5 — Estructura del mensaje final en `CE_TRANSACCIONAL`

**Referencia informativa**: nuestro código no construye este JSON (lo construye
`WSTecnicos0038`), pero tenemos que **saber qué campos va a extraer** para
garantizar que el headerIn/bodyIn/bodyOut que pasan por el adapter tengan todo
lo que la plantilla espera.

**Estructura final del mensaje en `CE_TRANSACCIONAL`** (PDF 1 + PDF 2):

```json
{
  "logs": {
    "empresa":        "0010",                        // headerIn.empresa
    "canal":          "03",                          // headerIn.canal
    "medio":          "030006",                      // headerIn.medio
    "aplicacion":     "00663",                       // headerIn.aplicacion
    "agencia":        "",                            // headerIn.agencia
    "idioma":         "es-EC",                       // headerIn.idioma
    "usuario":        "USINTERT",                    // headerIn.usuario
    "serverConsumer": "10.161.24.40",                // flujo.ip (IP del pod que procesa)
    "sesion":         "dca89eb2-0d8b-4e39-...",      // headerIn.sesion
    "unicidad":       "",                            // headerIn.unicidad
    "guid":           "1ba986fd1e114...",            // headerIn.guid
    "fechaHora":      "202601061415420752",          // headerIn.fechaHora

    "detalleCliente": {
      "ip":             "186.69.61.150",             // headerIn.ip (del cliente real)
      "dispositivo":    "IOS-801A058E-...",          // headerIn.dispositivo
      "geolocalizacion":"-1.66,-78.65",              // headerIn.geolocalizacion
      "idCliente":      "1722768924",                // headerIn.idCliente
      "tipoIdCliente":  "0001"                       // headerIn.tipoIdCliente
    },

    "detalleOrquestador": {
      "nombreServicio":   "ORQClientes0003",         // datos.servicioORQ
      "metodoServicio":   "ConsultarProductosActivos01", // datos.metodoORQ
      "tipoTransaccion":  "301000301"                // datos.tipoTransaccionORQ
    },

    "detalleMicroServicio": {
      "nombreServicio":   "WSClientes0002",          // @EventAudit.service
      "metodoServicio":   "consultarPrestamosActivos01", // @EventAudit.method
      "tipoTransaccion":  "201000201",               // datos.tipoTransaccionWS (del yml template key)
      "fechaHoraInicio":  "202601061415431148",      // timestamp antes de invocar
      "fechaHoraFin":     "202601061415431372",      // timestamp despues de invocar
      "lotElastico": {
        "documento": {},                              // vacio para consultas; poblado en transacciones
        "bodyIn":  { /* payload request mapeado segun <TX> */ },
        "bodyOut": { /* payload response mapeado segun <RX> */ }
      }
    },

    "error": {
      "codigo":         "0",                         // "0" = OK, otros = codigo backend
      "mensaje":        "OK",                        // mensaje tecnico backend
      "mensajeNegocio": "Transaccion procesada exitosamente",  // mensaje para UX
      "tipo":           "INFO"                       // INFO / ERROR / FATAL (ver reference_error_types.md)
    }
  }
}
```

**Implicaciones para nuestro código**:

- El `headerIn` que recorre el flujo ORQ debe tener **todos los campos** que el
  JSON final espera (especialmente `geolocalizacion`, `dispositivo`, `idCliente`,
  `tipoIdCliente` — no son opcionales aunque puedan venir vacíos).
- El adapter **no** necesita medir `fechaHoraInicio` / `fechaHoraFin`. La
  librería lo hace automáticamente al interceptar el método con `@EventAudit`.
- `error.mensajeNegocio` viene de la `BusinessException`/mapping de errores del
  adapter. `error.tipo` = `INFO`/`ERROR`/`FATAL` según `reference_error_types.md`.
- El `lotElastico.bodyIn` / `bodyOut` se rellena según la **plantilla XML** del
  yml — por eso LT-4 es obligatoria.

## Regla LT-6 — Formato del `<error>` en el evento XML intermedio

**MUST**: el adapter propaga el error del downstream con esta estructura dentro
del evento (PDF 1, ejemplo de `<NS1:evento>`):

```xml
<error>
    <codigo>0</codigo>             <!-- "0" = OK; != 0 = codigo de backend -->
    <mensaje>OK</mensaje>          <!-- mensaje tecnico -->
    <tipo>INFO</tipo>              <!-- INFO (success), ERROR (business), FATAL (infra) -->
    <backend>00638</backend>       <!-- codigo backend que respondio: 00638=IIB, 00045=BANCS, 00000=infra... -->
</error>
```

**Mapeo de `backend`** (cruzar con `reference_codigos_backend.md`):

| Backend value | Significado                                       |
|---------------|---------------------------------------------------|
| `00638`       | IIB (broker integración)                          |
| `00045`       | BANCS aplicación                                  |
| `00000`       | Usado por golds legacy — **NO es oficial**, evitar|
| otros         | Consultar catálogo oficial del banco              |

**Mapeo de `tipo`** (cruzar con `reference_error_types.md`):

| Tipo    | Cuándo                                                |
|---------|-------------------------------------------------------|
| `INFO`  | Respuesta exitosa (`codigo=0`)                        |
| `ERROR` | Excepción de negocio (validación, reglas, HTTP 4xx)   |
| `FATAL` | Header missing / Exception genérica / BANCS error / HTTP 5xx |

**NEVER**:
- Usar `tipo="WARN"` o `"DEBUG"` — no son valores válidos en este esquema.
- Omitir `backend` — algunos golds lo tienen pero es incorrecto; siempre
  debe estar.
- Hardcodear `codigo=0` cuando el response tuvo error — debe reflejar el
  código real devuelto por downstream.

## Regla LT-7 — Mapeo obligatorio headerIn → evento

**MUST**: todo campo del `<headerIn>` del request entrante al ORQ **se copia
tal cual** en el `<headerIn>` del evento (incluido `<bancs>` si existe — ver
gap conocido en `feedback_bancs_header_out_no_echo.md`).

Campos obligatorios que debe contener `headerIn` del evento (PDF 1):

```
dispositivo, empresa, canal, medio, aplicacion, agencia,
tipoTransaccion, geolocalizacion, usuario, unicidad, guid,
fechaHora, filler, idioma, sesion, ip, idCliente, tipoIdCliente
```

Y el sub-bloque `<bancs>` cuando aplica:

```
teller, terminal, institucion, agencia, estacion, aplicacion, canal
```

**NEVER**:
- Enriquecer el headerIn con campos nuevos solo para el evento — viaja tal
  cual entra.
- Strippear campos "irrelevantes" — `filler` por ejemplo queda vacío pero
  presente.
- Transformar valores (ej: trim, upper-case, timezone convert) — lo que llega
  es lo que va al evento.

---

## Automatización en el CLI

- `capamedia check` incluye el **Block 17 — Log transaccional (ORQ)** que
  valida:
  - `17.1`: dependencia `lib-event-logs-*` correcta según framework (fail si
    falta).
  - `17.2`: bloques `spring.kafka` + `logging.event` en el yml.
  - `17.3`: `logging.level.org.apache.kafka: OFF` presente.
  - `17.4`: al menos 1 `@EventAudit` en los adapters del proyecto.
  - Solo se activan si `source_kind == "orq"`. Para BUS/WAS no corre
    (evitar falsos positivos en servicios atómicos sin downstream).

- `capamedia check --auto-fix --bank-fix` agrega las dependencias faltantes
  automáticamente en ORQs.

- Mensaje de salida del bloque 17 incluye links a los dos PDFs fuente:
  - `prompts/documentacion/BPTPSRE-Estructura Log Transaccional-220426-215404.pdf`
  - `prompts/documentacion/BPTPSRE-Librería Log Transaccional-220426-202920.pdf`
