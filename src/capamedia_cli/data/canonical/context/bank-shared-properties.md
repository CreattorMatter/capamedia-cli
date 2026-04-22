---
name: bank-shared-properties
kind: context
priority: 1
summary: Catálogo embebido de `generalservices.properties` + `catalogoaplicaciones.properties` - constantes globales del banco, comunes a todos los servicios
---

# Catalogo de properties COMPARTIDOS del banco

**Estos dos archivos son constantes globales** de Banco Pichincha — no cambian
por servicio. Viven en `/apps/proy/OMNICANALIDAD_SERVICIOS/conf/` en los WAS
legacy (y en `/apps/proy/BANCA_ELECTRONICA_SERVICIOS/conf/` en los IIB).

**Regla fundamental:**

> Si el legacy referencia una clave de `generalservices.properties` o
> `catalogoaplicaciones.properties`, el agente migrador DEBE usar el **valor
> literal** de este catalogo — NUNCA pedir al usuario que lo pase, NUNCA
> marcarlo como "blocker pendiente", NUNCA usar placeholder.

Lo único que SI depende del servicio (y sí puede no estar disponible al
arranque) es el `<ump>.properties` o `<servicio>.properties` específico —
por ejemplo `umptecnicos0023.properties`, `consultaCliente.properties`, etc.

---

## 1. `generalservices.properties`

Contiene codigos de error base, tipos de evento, backends transversales y
configs de JNDI.

```properties
# Tipos de evento (para Service Log Helper / Event Audit)
OMNI_TIPO_ERROR=ERROR
OMNI_TIPO_FATAL=FATAL
OMNI_TIPO_INFO=INFO

# Codigos y mensajes estandar
OMNI_COD_FATAL=9999
OMNI_COD_NO_EXISTE_DATOS=1
OMNI_DESC_NO_EXISTE_DATOS=No existen datos de la consulta para mostrar
OMNI_COD_SERVICIO_OK=0
OMNI_MSJ_SERVICIO_OK=OK
OMNI_COD_INSERT_DATOS=9998
OMNI_DESC_INSERT_DATOS=Ya existe registros con la información solicitada
OMNI_COD_DATOS_UPDATE=9997
OMNI_DESC_DATOS_UPDATE=No existe información para realizar la actualización
OMNI_COD_VALIDAR_DATOS=9996
OMNI_DES_VALIDAR_DATOS=Error en la validacion de datos de entrada, no pueden ser nulos o vacios
OMN_MSJ_ERROR=Error al ejecutar la petición

# Backends transversales (codigos del catalogo oficial)
OMNI_BACKEND_VERIFER=00588
OMNI_COMPONENTE_VERIFER=VERIFIER
OMNI_COMPONENTE_BDD_OMNICANAL=Base de datos Omnicanal
OMNI_BACKEND_BDD_OMNICANAL=00634
OMNI_COMPONENTE_MOTOR_HOMOLOGACION=Motor de Homologacion
OMNI_BACKEND_MOTOR_HOMOLOGACION=00642
OMNI_COMPONENTE_BACKEND_SAR=Base de datos SAR
OMNI_BACKEND_SAR=00436
OMNI_COMPONENTE_BDD_ASESOR=AsesoresCOM
OMNI_BACKEND_ASESOR=00529
OMNI_COMPONENTE_S21=Base de datos Siglo21
OMNI_COMPONENTE_ASESORES=Base de Datos Asesores
OMNI_COMPONENTE_BDD_INTERNEXO=Base de datos Internexo
BACKEND_WAS=00633

# Paths de configuracion de providers (TCS)
OMNI_PROVIDER_CONF=/apps/proy/BANCA_ELECTRONICA_SERVICIOS/providers/providerconfiguration.config
OMNI_PROVIDER_APP=/apps/proy/BANCA_ELECTRONICA_SERVICIOS/providers/App.config

# JNDI
OMNI_INITIAL_CONTEXT_FACTORY=com.ibm.websphere.naming.WsnInitialContextFactory
OMN_JNDI_AUTORIZADORES=jndi.notifier.notificacion
OMN_JNDI_SEGURIDAD_INTERNEXO=jndi.internexo.cliente
JNDI_PRODUCTOS_CATALOGA=jndi.productos.cataloga
OMN_JNDI_PRODUCTOS_PRODUCTOS=jndi.productos.productos

# Limites
OMN_MAX_REG_DAO=2000
```

---

## 2. `catalogoaplicaciones.properties`

Mapping de **nombre de aplicacion** → **codigo de backend** oficial del banco.
Esto es lo que va en el campo `<backend>` del error/log transaccional.

```properties
NOTIFIER_OTP=00587
SIGLO_21=00429
SWITCH_TOTEM=00493
FEDERADOR_DE_IDENTIDADES_WSO2=00632
MIDDLEWARE_INTEGRACION_TECNICO_WAS=00633
BASE_DE_DATOS_OMNICANAL=00634
BASE_DE_DATOS_AUTORIZADORES=00644
MOTOR_DE_REGLAS_ODM=00635
NOTIFICADOR_MSG=00636
CXP_BANCA_ELECTRONICA_PERSONAS=00647
MIDDLEWARE_INTEGRACION=00638
GESTOR_DE_COLAS_MQ_GATEWAY=00639
FEDERADOR_DE_MIDDLEWARE_DATAPOWER=00640
MOTOR_DE_PAGOS_RECAUDACIONES=00641
MOTOR_DE_HOMOLOGACION=00642
BANCS=00045
INTERDIN=00646
VERIFIER=00588
PAGOS_PICHINCHA=00329
INTERNEXO_PERSONAS=00270
PICHINCHA_CELULAR=00335
BASE_DE_DATOS_ASESORES=00645
TCS_PROVIDERS=00517
BASE_DE_DATOS_INTERNEXO=00648
CARD_HOLDER_TARJETA_XPERTA=0019
BASE_DE_DATOS_SFI=00650
BASE_DE_DATOS_MOVILIDADMICRO=00650
BASE_DE_DATOS_AUTORIZADORES_PICHINCHA=00660
BASE_DE_DATOS_FILENET=00661
BASE_DATOS_SITAR=00651
BASE_DATOS_PDMP=00652
BASE_DATOS_SENTINEL=00653
BASE_DATOS_AS400=00654
BASE_DE_DATOS_CREDITO_TARJETA=00672
BASE_DE_DATOS_ASYNCRONO=00673
FIRMAS=00649
BASE_DE_DATOS_WORKFLOW=00046
```

---

## Cómo consumirlo en el servicio migrado

### Opción A — Hardcodear en `application.yml` (preferido para constantes inmutables)

Los codigos de backend y mensajes estandar no cambian entre ambientes
(dev/test/prod), asi que van **literales** en `application.yml`:

```yaml
error-messages:
  # Valores literales del catalogo del banco (generalservices.properties)
  success-code: "0"                     # OMNI_COD_SERVICIO_OK
  success-message: "OK"                 # OMNI_MSJ_SERVICIO_OK
  no-data-code: "1"                     # OMNI_COD_NO_EXISTE_DATOS
  no-data-message: "No existen datos de la consulta para mostrar"
  fatal-code: "9999"                    # OMNI_COD_FATAL

  # Backend del catalogoaplicaciones.properties
  backend: "00633"                      # MIDDLEWARE_INTEGRACION_TECNICO_WAS (WAS)
  # backend: "00638"                    # MIDDLEWARE_INTEGRACION (IIB)
  # backend: "00045"                    # BANCS
```

### Opción B — Expuestos via `${CCC_*}` env var (ops los puede cambiar sin redeploy)

Solo justificado si hay razon real para variar por ambiente. Para la gran
mayoria de estos, **NO** es el caso — van hardcoded y listo.

---

## Mapping legacy key → `application.yml` path sugerido

| Legacy key | `application.yml` path | Valor literal |
|---|---|---|
| `OMNI_COD_SERVICIO_OK` | `error-messages.success-code` | `"0"` |
| `OMNI_MSJ_SERVICIO_OK` | `error-messages.success-message` | `"OK"` |
| `OMNI_COD_NO_EXISTE_DATOS` | `error-messages.no-data-code` | `"1"` |
| `OMNI_DESC_NO_EXISTE_DATOS` | `error-messages.no-data-message` | literal del catalogo |
| `OMNI_COD_FATAL` | `error-messages.fatal-code` | `"9999"` |
| `OMNI_TIPO_INFO` | `error-messages.info-type` | `"INFO"` |
| `OMNI_TIPO_ERROR` | `error-messages.error-type` | `"ERROR"` |
| `OMNI_TIPO_FATAL` | `error-messages.fatal-type` | `"FATAL"` |
| `MIDDLEWARE_INTEGRACION_TECNICO_WAS` | `error-messages.backend` | `"00633"` (WAS) |
| `MIDDLEWARE_INTEGRACION` | `error-messages.backend` | `"00638"` (IIB) |
| `BANCS` | usado en adapters BANCS | `"00045"` |
| `BACKEND_WAS` | `error-messages.backend` | `"00633"` |
| `OMNI_BACKEND_BDD_OMNICANAL` | config DB adapter | `"00634"` |

---

## Qué SÍ pedirle al usuario

Las propiedades del **UMP específico** o del **servicio específico**. Ejemplos:

- `umptecnicos0023.properties`:
  - `URL_XML=/apps/proy/OMNICANALIDAD_SERVICIOS/conf/atributosTransaccion.xml`
  - `RECURSO`, `COMPONENTE`, `RECURSO2`, `COMPONENTE2`
- `consultaCliente.properties`, etc.

Esas NO estan en este catalogo. Si el usuario no las pasa al arranque, el
agente debe:
1. Listarlas explicitamente en `MIGRATION_REPORT.md` como "inputs pendientes"
2. Usar placeholder `${CCC_XXX}` en `application.yml`
3. Dejarlas como entrada del helm ConfigMap

---

## Regla para el agente migrador

1. **Antes** de marcar algo como blocker por falta de env var, buscar si la
   clave esta en este catalogo.
2. Si esta → usar el valor literal (hardcoded en `application.yml`).
3. Si no esta → pedirlo al usuario, pero primero confirmar que es
   servicio-especifico (viene de un `<ump>.properties` o similar).
4. En `MIGRATION_REPORT.md`, diferenciar claramente:
   - **"Valores resueltos desde catalogo del banco"** (NO son blockers)
   - **"Inputs pendientes del owner del servicio"** (SI son blockers de handoff)
