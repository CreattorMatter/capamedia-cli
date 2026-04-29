---
name: bank-error-structure
kind: context
priority: 1
summary: Estructura oficial del bloque <error> de Banco Pichincha - 7 campos canonicos, mensajeNegocio gestionado por DataPower, variantes BUS/WAS
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

**MUST**: el servicio **NUNCA** setea un valor real de negocio en
`mensajeNegocio`. Ese campo lo completa **DataPower** en su capa de
transformacion, consultando reglas de negocio especificas del banco.

**NEVER**:
- Poblar `mensajeNegocio` con texto desde el codigo del microservicio migrado.
- Copiar el valor desde otro campo (ej. asignarle el `mensajeCliente`).

**OK**:
- `setMensajeNegocio(null)` o no llamar al setter cuando el contrato permite
  omitir el elemento.
- `setMensajeNegocio("")` solo cuando la respuesta SOAP debe conservar el tag
  vacio (`<mensajeNegocio/>`) para que DataPower tenga el slot que completa.

```java
// ✘ NO — el servicio NUNCA setea mensajeNegocio
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
| Header inválido o faltante | **`FATAL`** | `"Datos de la cabecera de la transaccion no se han asignado"` |
| Fallo al invocar BANCS (red, timeout, 5xx) | **`FATAL`** | `BancsClientException` |
| Parse error de respuesta BANCS | **`FATAL`** | `"No se ha podido interpretar la respuesta de Bancs"` |
| Exception genérica no catch-eada | **`FATAL`** | Catch-all de `Exception` |

**NEVER**: marcar una falla de BANCS como `ERROR` — es **`FATAL`**. Regla
reforzada en commits post-2026-04-16 tras feedback del equipo.

## Variantes por contexto legacy

### BUS (IIB) migrado — response SOAP

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

### WAS migrado — response REST (JSON equivalente)

```json
{
  "cabecera": { ... },
  "data": { ... },
  "error": {
    "codigo": "0",
    "tipo": "INFO",
    "mensajeCliente": "OK",
    "mensajeNegocio": null,
    "mensajeAplicacion": null,
    "backend": "00045",
    "momentoError": "2026-04-23T21:10:16.123Z"
  }
}
```

### Error path — ejemplo `BancsClientException`

```json
{
  "error": {
    "codigo": "9929",
    "tipo": "FATAL",
    "mensajeCliente": "Error al invocar transaccion Bancs",
    "mensajeNegocio": null,
    "mensajeAplicacion": "Timeout after 30000ms calling ws-tx067010",
    "backend": "00045",
    "momentoError": "2026-04-23T21:10:16.123Z"
  }
}
```

## Gap conocido — `<bancs>` no se replica en HeaderOut

Documentado en `feedback_bancs_header_out_no_echo.md` (memoria del equipo):

> La response **NUNCA** devuelve `<bancs>` aunque venga en el request.

El validador del banco lo considera gap conocido en servicios antiguos
(`wsclientes0015`, `wsclientes0020`). En servicios nuevos: no replicar el bloque
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
