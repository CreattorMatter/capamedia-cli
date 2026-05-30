---
name: bank-error-structure
kind: context
priority: 1
summary: Estructura oficial del bloque <error> de Banco Pichincha - 7 campos canonicos, mensajeNegocio gestionado por DataPower, formato segun contrato WSDL/XSD
---

# Estructura oficial del bloque `<error>` — Banco Pichincha

**Fuente autoritativa**: el contrato `GenericError` del XSD generado en los
servicios migrados — verificado **idéntico** en WSClientes0077 y WSClientes0013
(`src/main/resources/legacy/GenericSOAP.xsd`). Referencia histórica del banco:
`prompts/documentacion/BPTPSRE-Estructura de error-200426-212629.pdf` (PDF no
versionado en este repo; el contrato XSD es la verdad ejecutable y prevalece).

Este canonical es la **única fuente de verdad** para el formato del bloque
`<error>` en las respuestas SOAP/REST del banco. Cualquier prompt, check o
reviewer que hable de error structure debe referenciar este archivo — **no
copiar ni reformular la tabla** en otro lado.

## Los 7 campos canónicos del `<error>`

Orden y nombres **EXACTOS** del contrato XSD `GenericError` (todos `minOccurs=1`,
obligatorios). Verificado contra el código desplegado de WSClientes0077 y 0013:

| # | Campo | Tipo | Origen del valor | Quién lo setea |
|---|---|---|---|---|
| 1 | `codigo` | String numérico | Catálogo `errores.xml`; `"0"` en éxito | **Servicio** (ver `bank-error-codes.md`) |
| 2 | `mensaje` | Texto user-facing | Mensaje del catálogo; `"OK"` en éxito (ej. `"CUENTA NO EXISTE"`) | **Servicio** |
| 3 | `mensajeNegocio` | String (slot vacío) | **Gestionado por DataPower** — el servicio emite `""`/null/ausencia | **DataPower** (NUNCA un valor real del servicio) |
| 4 | `tipo` | `INFO` \| `ERROR` \| `FATAL` | `ErrorType` enum, por severidad de la falla | **Servicio** |
| 5 | `recurso` | String `<servicio-migrado>/<método>` | Nombre MIGRADO **+ `/método`** (ej. `tnd-msa-sp-wsclientes0077/ConsultarDatoBasicoCliente01`). El check 15.2 exige el `/` y RECHAZA el nombre legacy `WSClientes0077` | **Servicio** |
| 6 | `componente` | String (sin `/`) | Nombre MIGRADO del servicio (`tnd-msa-sp-wsclientes0077`) o, en error propagado de backend, `TX<NNNNNN>` / `ApiClient`. El check 15.3 RECHAZA el nombre legacy | **Servicio** |
| 7 | `backend` | String (long. 5) | Catálogo `sqb-cfg-codigosBackend-config/codigosBackend.xml`; ej. `00045` (Bancs) | **Servicio** |

> **Campos que NO pertenecen al bloque `<error>`**: `mensajeCliente`,
> `mensajeAplicacion`, `momentoError` y `severidad` **no existen** en el contrato
> XSD del banco (aparecen en 0 archivos Java de los servicios reales). Versiones
> previas de este canonical los listaban por error — **NO usarlos**. El campo
> user-facing es `mensaje` (no `mensajeCliente`); la severidad se expresa vía
> `tipo` (no un campo aparte).
>
> **Conteo histórico**: algunos checklists viejos mencionaban "8 campos"
> separando `codigoBackend` de `backend`. Son **7** — `codigoBackend` está
> fusionado dentro de `backend` (ej. `"00045"`). No agregar un 8º campo ad-hoc.

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

// ✔ OK — patrón real (infrastructure/soap/helper/SoapResponseHelper.java de
//        WSClientes0077): mensajeNegocio vacío; DataPower lo completa si aplica.
GenericError error = new GenericError();
error.setCodigo(codigo);                                              // "0" en éxito
error.setMensaje(mensaje);                                            // "OK" en éxito
error.setMensajeNegocio(EMPTY_MENSAJE_NEGOCIO);                       // constante = "" — DataPower lo gestiona
error.setTipo(tipo);                                                  // ERROR_TYPE_INFO/ERROR/FATAL
error.setRecurso("tnd-msa-sp-wsclientes0077/ConsultarDatoBasicoCliente01"); // LITERAL <servicio-migrado>/<método>
error.setComponente("tnd-msa-sp-wsclientes0077");                     // LITERAL nombre MIGRADO (en error BANCS: TX067050 / ApiClient)
error.setBackend(backend);                                           // catálogo codigosBackend.xml (00045 BANCS / 00638 IIB)
```

> **Por qué `recurso`/`componente` van como string LITERAL** (no constante ni
> variable): el análisis estático del banco (checklist 15.2/15.3) los detecta con
> grep sobre el fuente. Si se pasan vía constante/variable, el check no los ve.
> El código real del 0077 los inlinea por esta razón.

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
  <mensaje>OK</mensaje>
  <mensajeNegocio/>                       <!-- tag vacio permitido; valor real NUNCA -->
  <tipo>INFO</tipo>
  <recurso>tnd-msa-sp-wsclientes0077/ConsultarDatoBasicoCliente01</recurso>
  <componente>tnd-msa-sp-wsclientes0077</componente>
  <backend>00045</backend>
</error>
```

### Error path — ejemplo `BancsClientException`

```xml
<error>
  <codigo>9929</codigo>
  <mensaje>Error al invocar transaccion Bancs</mensaje>
  <mensajeNegocio/>
  <tipo>ERROR</tipo>
  <recurso>tnd-msa-sp-wsclientes0077/ConsultarDatoBasicoCliente01</recurso>
  <componente>ApiClient</componente>
  <backend>00045</backend>
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
2. **Poblar `GenericError`** con los 7 campos en el orden del contrato XSD
   (`codigo, mensaje, mensajeNegocio, tipo, recurso, componente, backend`) —
   nunca mezclar orden ni inventar campos.
3. **`mensajeNegocio` siempre sin valor real**: `null`/ausente o `""` cuando el contrato SOAP exige tag vacio.
4. **`backend`** resuelto desde el catálogo `codigosBackend.xml` (ver
   `reference_codigos_backend.md`: `bancs_app=00045`, `iib=00638`).
5. **`recurso`** = `<SERVICIO>/<MÉTODO>` y **`componente`** = método o componente
   backend (ej. `TXNNNNNN`) — ambos del recurso donde ocurre el fallo.
6. Si el PR reviewer señala el formato, **citar este canonical** — no
   reformular la tabla.
