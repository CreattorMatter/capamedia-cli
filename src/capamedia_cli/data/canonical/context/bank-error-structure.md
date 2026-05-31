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

> **Sobre LITERAL vs CONSTANTE en `recurso`/`componente`**: historicamente el
> ejemplo del 0077 usa string LITERAL porque el check 15.2/15.3 original solo
> hacia grep de literal. **Actualizado v0.29**: el check ahora resuelve
> CONST_CLASS y CONST_LOCAL via `_resolve_const`, asi que AMBOS patrones son
> validos (ver §"recurso y componente — formato detallado" mas abajo para el
> patron completo con ambos estilos). El analisis estatico del banco sigue
> prefiriendo literal porque es mas grep-friendly fuera del CLI; el CLI no
> distingue.

## Tipos canónicos (`error.tipo`)

Referencia cruzada con `bank-error-structure.md` (memoria del equipo):

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

## recurso y componente — formato detallado (origen BTHCCC-6826)

**Origen**: PDF `BPTPSRE-Estructura de error` + QA del banco (ticket BTHCCC-6826,
hallazgo de 2026-05 sobre `WSClientes0011`).

**Aplica a**: WAS, BUS/IIB y ORQ — **los tres tipos**. El estandar de error es
unico, no varia por source type.

### Formato canonico (tabla OK vs HIGH)

| Campo | Formato | Ejemplo OK | Ejemplo HIGH (rechazado por QA) |
|---|---|---|---|
| `recurso` | `<spring.application.name>/<metodo>` | `csg-msa-sp-wsclientes0011/ConsultarDatosIdentificacion` | `WSClientes0011/ConsultarDatosIdentificacion` |
| `componente` | uno de los 3 valores canonicos (ver abajo) | `csg-msa-sp-wsclientes0011`, `ApiClient`, o `TX060480` | `WSClientes0011` |

### Tres valores canonicos para `componente`

1. **`<namespace>-msa-sp-<svc>`** (= `spring.application.name`): error interno
   del servicio migrado o respuesta exitosa.
2. **`ApiClient`** (o nombre exacto de libreria): error propagado desde
   `lib-bnc-api-client` u otra libreria interna.
3. **`TX<NNNNNN>`** (prefijo `TX` + 6 digitos): error de negocio propagado
   desde el Core Adapter.

> **Caso downstream**: si el error se propaga desde un servicio downstream
> migrado (ej. ORQ que invoca a WSClientes0046), el `componente` debe ser
> `ApiClient`, `TX<NNNNNN>` o el nombre migrado del downstream
> (`<ns>-msa-sp-<downstream-svc>`), **NUNCA** el nombre legacy
> (`WSClientes0046`). El autofix 9j conservadoramente NO reescribe nombres
> de downstream (necesitaria conocer el migrado del otro servicio); el
> agente migrador debe elegir entre las 3 opciones.

### Patron Java (ambos validos, el check resuelve constantes)

El check 15.2/15.3 (`run_block_15`) detecta el valor en los 4 patrones reales
del banco: LITERAL directo en setter, CONST_CLASS, CONST_LOCAL en builder
ingles, CONST_CLASS en builder espanol. Usa `_resolve_const` para leer la
definicion de la constante. Por lo tanto, **ambos patrones son aceptados**:

```java
// ✔ OK — LITERAL directo (caso WSClientes0077, mas grep-friendly):
error.setRecurso("csg-msa-sp-wsclientes0011/ConsultarDatosIdentificacion");
error.setComponente("csg-msa-sp-wsclientes0011");

// ✔ OK — CONSTANTE centralizada (caso WSClientes0013, mas mantenible):
@UtilityClass
public class CatalogExceptionConstants {
    public static final String WS_COMPONENTE = "csg-msa-sp-wsclientes0011";
    public static final String WS_RECURSO_PREFIX = WS_COMPONENTE + "/";
}
// En el helper que construye el <error>:
error.setRecurso(CatalogExceptionConstants.WS_RECURSO_PREFIX + operationName);
error.setComponente(CatalogExceptionConstants.WS_COMPONENTE);
```

**Eleccion**: literal es mas explicito y mas facil de auditar visualmente;
constante es mas mantenible si cambia el namespace. Para servicios nuevos,
preferir constante centralizada con el literal alineado a `spring.application.name`.

### Justificacion (CMDB / Backstage)

El nombre legacy IIB/WAS/ORQ es referencia interna (logs, trazabilidad), no
contrato externo. Lo que el banco audita en produccion es el `recurso` y
`componente` del response — esos identifican univocamente al microservicio
MIGRADO en el catalogo Backstage y en CMDB. Un response con
`<componente>WSClientes0011</componente>` no aparece registrado en CMDB y QA
lo reporta como bug bloqueante (BTHCCC-6826).

### Validacion en el CLI

- **Check 15.2** (`recurso`) y **Check 15.3** (`componente`) en
  `core/checklist_rules.py::run_block_15`. Detectan nombre legacy con
  severity HIGH; diferencian legacy del PROPIO servicio (autofixeable)
  vs DOWNSTREAM (decision semantica).
- **Autofix 9j** en `core/bank_autofix.py::fix_legacy_name_in_error_payload`:
  Pass 1 (regex setter+literal directo) + Pass 2 (`_find_field_usages` con
  resolucion de constantes; cubre los 4 patrones reales del banco).
- Test: `tests/test_block_15_legacy_name.py` (21 casos).

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

> La response **NUNCA** devuelve `<bancs>` aunque venga en el request (gap conocido del equipo).

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
   `bank-error-codes.md`: `bancs_app=00045`, `iib=00638`).
5. **`recurso`** = `<SERVICIO>/<MÉTODO>` y **`componente`** = método o componente
   backend (ej. `TXNNNNNN`) — ambos del recurso donde ocurre el fallo.
6. Si el PR reviewer señala el formato, **citar este canonical** — no
   reformular la tabla.
