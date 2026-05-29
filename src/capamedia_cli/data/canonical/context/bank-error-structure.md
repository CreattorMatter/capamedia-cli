---
name: bank-error-structure
kind: context
priority: 1
summary: Estructura oficial del bloque <error> de Banco Pichincha - 7 campos canonicos, mensajeNegocio gestionado por DataPower, formato segun contrato WSDL/XSD
---

# Estructura oficial del bloque `<error>` — Banco Pichincha

**Fuente autoritativa** (según indicación de Julian 2026-04-20):
`prompts/documentacion/BPTPSRE-Estructura de error-200426-212629.pdf`.

Este canonical es la **única fuente de verdad** para el formato del bloque
`<error>` en las respuestas SOAP/REST del banco. Cualquier prompt, check o
reviewer que hable de error structure debe referenciar este archivo — **no
copiar ni reformular la tabla** en otro lado.

## Los 7 campos canónicos del `<error>`

| # | Campo | Tipo | Origen del valor | Quién lo setea |
|---|---|---|---|---|
| 1 | `codigo` | String numérico | Catálogo `errores.xml` del banco | **Servicio** (ver `bank-error-codes.md`) |
| 2 | `tipo` | `INFO` \| `ERROR` \| `FATAL` | Clasificación por tipo de falla | **Servicio** |
| 3 | `mensajeCliente` | Texto corto, user-facing | Mensaje del catálogo `errores.xml` | **Servicio** |
| 4 | `mensajeNegocio` | Texto business | **Gestionado por DataPower** — el servicio solo emite `null`, tag vacio o ausencia segun contrato | **DataPower** (NUNCA un valor real del servicio) |
| 5 | `mensajeAplicacion` | Texto técnico / stacktrace resumido | Exception.getMessage() o detalle técnico | **Servicio** |
| 6 | `backend` | String | Catálogo oficial `sqb-cfg-codigosBackend-config/codigosBackend.xml` | **Servicio** |
| 7 | `momentoError` | ISO-8601 timestamp | `Instant.now().toString()` al momento del throw | **Servicio** |

> **Nota del PDF**: históricamente algunos checklists mencionan 8 campos
> separando `codigoBackend` de `backend`. En la estructura vigente de
> Banco Pichincha son **7 campos** — `codigoBackend` está fusionado dentro
> de `backend` (ej. `"00045"`). No agregar un 8º campo ad-hoc.

## Regla maestra — `mensajeNegocio`

**MUST**: el tag `mensajeNegocio` **siempre presente** y por defecto **vacio**
(`<mensajeNegocio/>` / `setMensajeNegocio("")`). El valor de negocio lo completa
**DataPower**. **El tag NUNCA se elimina** — debe quedar el slot vacio para que
DataPower lo complete.

**Excepcion — respetar el legacy**: si el **legacy del servicio** (BUS/WAS/ORQ)
ya poblaba `mensajeNegocio` con un valor real, la migracion **lo respeta**. El
Check 15.1 cross-chequea el legacy (`_legacy_populates_mensaje_negocio`): solo
marca **HIGH** cuando el migrado pone un valor que el legacy **no** tenia. Sin
legacy disponible para verificar → **LOW** (revisar manual).

**NEVER**:
- Inventar texto en `mensajeNegocio` desde el codigo migrado cuando el legacy no
  lo poblaba.
- **Eliminar** el tag o el setter — dejarlo vacio, no borrarlo (rompe el slot
  que DataPower completa).

**OK**:
- `setMensajeNegocio("")` / `null` para conservar el slot vacio
  (`<mensajeNegocio/>`) — **caso por defecto**.
- `setMensajeNegocio("<valor>")` **solo** si el legacy del servicio ya lo poblaba.

```java
// ✘ NO — no inventar valor si el legacy no lo poblaba (vaciar, NO borrar el tag)
error.setMensajeNegocio("Transacción exitosa");

// ✔ OK — null/ausente; DataPower lo completa si aplica
Error error = Error.builder()
    .codigo("0")
    .tipo("INFO")
    .mensajeCliente("OK")
    .mensajeNegocio(null)
    .mensajeAplicacion(null)
    .backend("00045")
    .momentoError(Instant.now().toString())
    .build();

// ✔ OK — SOAP/DataPower slot requerido por contrato
error.setMensajeNegocio("");
```

## Tipos canónicos (`error.tipo`)

Referencia cruzada con `reference_error_types.md` (memoria del equipo):

| Caso | Tipo | Ejemplo |
|---|---|---|
| Success (code `"0"`) | **`INFO`** | Transacción OK |
| Validación de negocio fallida (campo requerido nulo, formato inválido) | **`ERROR`** | `BusinessValidationException` |
| Fallo al invocar BANCS (red, timeout, 5xx) | **`ERROR`** | `BancsClientException` |
| Parse error de respuesta BANCS | **`ERROR`** | `"No se ha podido interpretar la respuesta de Bancs"` |
| Timeout de invocación BANCS | **`ERROR`** | `TimeoutException` envuelto en `GlobalErrorException` |
| Header inválido o faltante | **`FATAL`** | `"Datos de la cabecera de la transaccion no se han asignado"` |
| Exception genérica no catch-eada | **`FATAL`** | Catch-all de `Exception` |

**Aclaración oficial 2026-05-27 (Kevin Armas / BPTPSRE)**: los errores de
BANCS (fallo de red, timeout, parse error, 5xx) son **`ERROR`**, NO `FATAL`.
Esto invierte la regla anterior que reservaba `FATAL` para "infra incluyendo
BANCS". `FATAL` queda **únicamente** para:

1. **Header faltante** (`9927`) — la transacción no puede ni siquiera llegar
   a BANCS porque falta `<headerIn>.<bancs>` (precondición no satisfecha).
2. **Exception genérica catch-all** (`9999`) — situación desconocida que el
   código no contempló; requiere intervención técnica.

Para BANCS y timeouts de BANCS, el caller puede reintentar — es recuperable.
Por eso son `ERROR`, no `FATAL`.

**NEVER**: marcar una falla de BANCS como `FATAL` — es **`ERROR`**.
Anti-patrón inverso al que detectaba el check viejo. Validado por checklist
Block 5.7b (nuevo en v0.27.1).

**NEVER**: marcar `BusinessValidationException` como **`FATAL`** — es **`ERROR`**
(validación recuperable por el caller). Reforzado tras informe QA WSClientes0011
(2026-05): el migrado usaba `FATAL` para validaciones de negocio, perdiendo la
diferenciación que hace el legacy con `ERROR` / `INFO`. Validado por checklist
Block 5.6.5.

## Formato segun contrato expuesto

El bloque `<error>` conserva los mismos 7 campos canonicos. El formato de
transporte NO se infiere por la palabra "REST": se toma del contrato legacy
evidenciado en WSDL/XSD o documentacion. En las migraciones SOAP-over-HTTP del
programa, incluso cuando el arquetipo Spring usa `@RestController`, el payload
externo sigue siendo SOAP XML salvo evidencia explicita de JSON.

### Response SOAP/XML

```xml
<cabecera>...</cabecera>
<clientes>
  <cliente>...</cliente>
</clientes>
<error>
  <codigo>0</codigo>
  <tipo>INFO</tipo>
  <mensajeCliente>OK</mensajeCliente>
  <mensajeNegocio/>                       <!-- tag vacio permitido; valor real NUNCA -->
  <mensajeAplicacion xsi:nil="true"/>
  <backend>00045</backend>
  <momentoError>2026-04-23T21:10:16.123Z</momentoError>
</error>
```

### Error path — ejemplo `BancsClientException`

```xml
<error>
  <codigo>9929</codigo>
  <tipo>ERROR</tipo>
  <mensajeCliente>Error al invocar transaccion Bancs</mensajeCliente>
  <mensajeNegocio/>
  <mensajeAplicacion>Timeout after 30000ms calling ws-tx067010</mensajeAplicacion>
  <backend>00045</backend>
  <momentoError>2026-04-23T21:10:16.123Z</momentoError>
</error>
```

> `tipo=ERROR` (no FATAL) confirmado por Kevin Armas / BPTPSRE el 2026-05-27.
> El caller puede reintentar el llamado a BANCS — es recuperable.

## Gap conocido — `<bancs>` no se replica en HeaderOut

Documentado en `feedback_bancs_header_out_no_echo.md` (memoria del equipo):

> La response **NUNCA** devuelve `<bancs>` aunque venga en el request.

El validador del banco lo considera gap conocido en servicios antiguos.
En servicios nuevos: no replicar el bloque
`<bancs>` del request en la cabecera de salida.

## Relación con otros canonicals

- **`bank-error-codes.md`** → catálogo de codes (`"0"`, `"9922"`, `"9929"`, etc).
  Este canonical define **estructura** del `<error>`; `bank-error-codes.md`
  define **qué code usar** en cada caso.
- **`bank-official-rules.md` Regla 5.4** → `backend` desde catálogo, NUNCA
  hardcoded `"00000"`. Este canonical pone la regla en contexto del campo 6.
- **`checklist-rules.md` Checks 4.5, 5.4, 5.6** → auditan en el código migrado
  que los 7 campos estén poblados según las reglas definidas acá.

## Regla para el agente migrador

1. **Antes de generar código de error mapping**, leer este canonical y
   `bank-error-codes.md`.
2. **Usar un builder o record** con los 7 campos — nunca mezclar orden.
3. **`mensajeNegocio` siempre sin valor real**: `null`/ausente o `""` cuando el contrato SOAP exige tag vacio.
4. **`backend`** resuelto desde el catálogo `codigosBackend.xml` (ver
   `reference_codigos_backend.md`: `bancs_app=00045`, `iib=00638`).
5. **`momentoError`** generado al momento del throw con `Instant.now()`, no
   al momento del wrapping en el error handler.
6. Si el PR reviewer señala el formato, **citar este canonical** — no
   reformular la tabla.
