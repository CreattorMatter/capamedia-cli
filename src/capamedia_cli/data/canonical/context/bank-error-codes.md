---
name: bank-error-codes
kind: context
priority: 1
summary: Catalogo oficial de error codes del banco (errores.xml) - NUNCA inventar "999" o similares
---

# Catalogo oficial de error codes

Fuente: `sqb-cfg-errores-errors/errores.xml` del banco — Feedback jgarcia
(commit 3dbf23f del `PromptCapaMedia`, 2026-04-21).

## Regla

**MUST**: usar los codes del catalogo oficial del banco.

**NEVER**: inventar codigos como `"999"`, `"404"`, `"500"` como fallback
generico. Cada tipo de error tiene un codigo especifico asignado por el banco.

## Catalogo de codes (fragmento principal)

| Code | Mensaje canonico | Cuando usar |
|---|---|---|
| `"0"` | `"OK"` | Success generico |
| `"1"` | `"No existen datos de la consulta para mostrar"` | Query vacia / sin datos |
| `"9922"` | `"No se ha podido interpretar la respuesta de Bancs"` | Parse error del body de Bancs |
| `"9927"` | `"Datos de la cabecera de la transaccion no se han asignado"` | Header validator fails (FATAL) |
| `"9929"` | `"Error al invocar transaccion Bancs"` | BancsClientException / fallo red Bancs |
| `"9991"` | `"Tiempo de respuesta del servicio expirado"` | Timeout generico |
| `"9996"` | `"Error en la validacion de datos de entrada, no pueden ser nulos o vacios"` | BusinessValidationException (generico) |
| `"9997"` | `"No existe informacion para realizar la actualizacion"` | Update target no existe |
| `"9998"` | `"Ya existe registros con la informacion solicitada"` | Insert duplicado |
| `"9999"` | `"Error al procesar el servicio"` | Catch-all generico (Exception) |

(ampliar con mas codes del errores.xml segun se encuentren)

## Patron canonico en Java

```java
public class CatalogExceptionConstants {

    // Success / OK
    public static final String SUCCESS_CODE = "0";
    public static final String SUCCESS_MESSAGE_BANCS = "OK";
    public static final String SUCCESS_MENSAJE_NEGOCIO =
        "Transaccion OK";

    // Backend (DEBE venir del catalogo codigosBackend.xml, NUNCA hardcoded "00000")
    // Ver bank-official-rules.md Regla 5.4
    public static final String BACKEND_CODE = "00045";   // BANCS (ejemplo)

    // ---- Codes de errores.xml (NEVER fabricate) ----

    /** Error al procesar el servicio (catch-all, catch Exception). */
    public static final String ERROR_CODE_SERVICE = "9999";

    /** Error al invocar transaccion Bancs (BancsClientException / red). */
    public static final String ERROR_CODE_BANCS_INVOKE = "9929";

    /** No se ha podido interpretar la respuesta de Bancs (parse / null body). */
    public static final String ERROR_CODE_BANCS_PARSE = "9922";

    /** Datos de la cabecera no se han asignado (HeaderValidator fails). */
    public static final String ERROR_CODE_HEADER = "9927";

    /** Tiempo de respuesta del servicio expirado (timeout). */
    public static final String ERROR_CODE_TIMEOUT = "9991";
}
```

## Uso en el codigo (reemplazar `"999"` hardcoded)

### Antes (incorrecto)

```java
static final String ERROR = "999";

if (Objects.isNull(bancsResponse.body())) {
    return Mono.error(new GlobalErrorException("999",
        "Respuesta de Adaptador Bancs sin body para: " + request.identificacion(),
        ERROR_TX_COMPONENT));
}
```

### Despues (correcto)

```java
if (Objects.isNull(bancsResponse.body())) {
    return Mono.error(new GlobalErrorException(
        CatalogExceptionConstants.ERROR_CODE_BANCS_PARSE,
        "No se ha podido interpretar la respuesta de Bancs para: "
            + request.identificacion(),
        ERROR_TX_COMPONENT));
}
```

## Mapping exception -> code

| Exception type | Code |
|---|---|
| `HeaderValidator.validate(...).isPresent()` | `ERROR_CODE_HEADER` (`9927`) → tipo FATAL |
| `BusinessValidationException` | `9996` → tipo ERROR |
| `BancsOperationException` | `ERROR_CODE_BANCS_INVOKE` (`9929`) → tipo FATAL |
| `BancsClientException` (null body, parse) | `ERROR_CODE_BANCS_PARSE` (`9922`) → tipo FATAL |
| `TimeoutException` | `ERROR_CODE_TIMEOUT` (`9991`) → tipo FATAL |
| `Exception` (catch-all) | `ERROR_CODE_SERVICE` (`9999`) → tipo FATAL |

## Reglas para el agente migrador

1. **NUNCA** usar `"999"`, `"404"`, `"500"` u otros codes fabricados.
2. Declarar constantes en `CatalogExceptionConstants` con **comentario**
   indicando el code y el mensaje canonico del `errores.xml`.
3. Si el caso no matchea ningun code del catalogo, **documentar en el
   MIGRATION_REPORT** la necesidad de pedir un code nuevo al banco — NO
   inventar uno.
4. En tests, los asserts deben usar las constantes, no string literales:
   ```java
   // CORRECTO
   assertThat(e.getCode()).isEqualTo(CatalogExceptionConstants.ERROR_CODE_BANCS_PARSE);

   // INCORRECTO
   assertThat(e.getCode()).isEqualTo("9922");  // no hardcodear
   ```
