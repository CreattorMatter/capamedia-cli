---
name: bank-configurables
kind: context
priority: 1
summary: Configuracion externa del banco - GestionarRecursoConfigurable (IIB), GestionarRecursoXML (BUS), CSV operativo y mapeo a application.yml
---

# Configuración externa del banco — reglas unificadas

**Fuentes autoritativas**:
- `prompts/documentacion/BPTPSRE-Servicios Configurables-200426-212822.pdf`
- `prompts/documentacion/BPTPSRE-Archivos de configuración-200426-212744.pdf`
- CSV operativo: `PromptCapaMedia/ConfigurablesBusOmni*.csv` — **ISO-8859-1**,
  delimitador `;`, columnas `Configurable;Variable;Valor`, 7868 filas, 533
  configurables distintos. **Consultarlo SIEMPRE con `capamedia configurables
  <Nombre>`**, nunca con `grep` (ver Regla 11 de `bank-official-rules.md`: en
  locale UTF-8 `grep` sale con codigo 1 y sin salida, indistinguible de "no
  encontrado", y eso produjo un falso negativo real en WSSeguridad0069).
- Commit `b55a794` del PromptCapaMedia (2026-04-21)

Este canonical centraliza las reglas para **configurables** (IIB/WAS) y su
migración a `application.yml`. Reemplaza las piezas dispersas que antes
vivían en `checklist-rules.md` Regla 11, `migrate-rest-full.md` y
`migrate-soap-full.md`.

## Patrones legacy a detectar

### 1. IIB — `GestionarRecursoConfigurable`

Nodo ESQL del IIB que lee configurables de un repositorio operativo del banco.

**Patrón típico**:

```esql
CALL GestionarRecursoConfigurable(
    'UMPSeguridad0087Config',  -- nombre del configurable (columna `Configurable` del CSV)
    'url',                     -- clave           (columna `Variable` del CSV)
    OutputRoot.XMLNSC.valor    -- OUT             (columna `Valor` del CSV)
);
```

El primer argumento es lo que se le pasa a `capamedia configurables <Nombre>`.

**Cómo migrarlo**:
1. El CSV `ConfigurablesBusOmni*.csv` (en el repo local `PromptCapaMedia/`)
   contiene los valores de producción.
2. El agente migrador corre `capamedia configurables <Nombre>` con el nombre
   que aparece en el ESQL. **No hace `grep`**: el archivo es ISO-8859-1 y un
   grep en locale UTF-8 devuelve un falso "no encontrado". Exit code `1` =
   leído y ausente (definitivo); exit code `2` = no se pudo leer (sin
   respuesta, nunca concluir ausencia).
3. Mapea las filas devueltas a `application.yml` (ejemplo real de
   WSSeguridad0069, cuyo UMP lee `Environment.cache.UMPSeguridad0087Config`):

```yaml
# capamedia configurables UMPSeguridad0087Config --yaml
UMPSeguridad0087Config:
  enableAUD: "true"
  ns: "http://soap.easysol.net/detect/detectService"
  url: "https://detectidtest.uio.bpichincha.com/detect/services/WSClientService"
```

`url` es env-dependent -> `${CCC_*}` + Helm; flags y `ns` son literales.

### 2. IIB — `GestionarRecursoXML`

Nodo ESQL que lee un XML operativo (`sqb-cfg-<name>-<folder>`). Valores
constantes que el BUS inyecta en la respuesta.

**Patrón típico**:

```esql
CALL GestionarRecursoXML('sqb-cfg-mensajes-omni', 'MSJ_OK', ...);
```

**Cómo migrarlo**: los valores de los XML operativos son **literales** en
`application.yml` — no requieren env var ni Helm:

```yaml
mensajes:
  MSJ_OK: "Transaccion exitosa"
  MSJ_ERROR_GENERICO: "Error al procesar el servicio"
```

### 3. WAS — `Propiedad.get(...)` + `.properties`

Los WAS legacy leen properties del sistema de archivos:

```java
// legacy/ws-xxx-was/.../Propiedad.java
private static final String REG_MAX =
    Propiedad.get("wsclientes0006.properties", "REG_MAX");
```

**Ubicación**: `/apps/proy/OMNICANALIDAD_SERVICIOS/conf/<service>.properties`.

**Cómo migrarlo**:
1. Leer el `.properties` legacy del workspace.
2. Mapear cada entrada a `application.yml`.
3. Si es un valor **constante del banco** (ej. `OMNI_COD_SERVICIO_OK=0`),
   vive en `bank-shared-properties.md` — usar literal **sin** env var.
4. Si es un valor **del servicio específico**, decidir según Regla 9g (ver
   `bank-official-rules.md`):
   - Constante conocida → **literal**.
   - Secret / env-dependent → `${CCC_*}` + declaración en Helm (3 ambientes).

## Regla maestra de commit (Regla 9g, reafirmada acá)

**MUST**: toda variable legacy referenciada por el servicio **o sus UMPs**
debe tener entrada en `application.yml`.

**NEVER inline defaults**: `${CCC_VAR:value}` está prohibido sin excepción.
Los `${CCC_*}` resuelven **sólo** vía Helm.

```yaml
# ✘ NO
error-messages:
  backend: ${CCC_BANCS_ERROR_CODE:00633}

# ✔ OK — constante del catálogo, literal
error-messages:
  backend: "00633"

# ✔ OK — env-dependent, sin default
datasource:
  url: ${CCC_DATASOURCE_URL}
```

## Flujo de detección del CLI (Block 19)

El CLI ejecuta este flujo automáticamente en `capamedia clone` /
`_auto_generate_reports_from_local_legacy`:

1. **Escanear** `legacy/` + `umps/` buscando:
   - `*.properties` files
   - `Constantes.java` / `Propiedad.get(...)`
   - `Environment.cache.*`
   - Calls ESQL a `GestionarRecursoConfigurable` y `GestionarRecursoXML`
   - Referencias a `CatalogoAplicaciones.properties`
2. **Emitir** `.capamedia/properties-report.yaml` con todas las claves
   encontradas y sus fuentes (archivo + línea).
3. **Block 19** del checklist (`run_block_19` de `checklist_rules.py`):
   cruza `properties-report.yaml` contra `application.yml` del destino.
   Cada clave sin mapear → **FAIL HIGH**.

## Decisión: literal vs env var

| Señal | Commit a `application.yml` |
|---|---|
| Aparece en `bank-shared-properties.md` | **Literal** (catálogo global del banco) |
| Valor fijo conocido del legacy (resource name, code, prefix, longitud) | **Literal** |
| `capamedia configurables <N>` devuelve la fila (exit 0) | **Literal** (valor del CSV) |
| Contiene URL / host / puerto / password / token | **`${CCC_*}`** + Helm (3 envs) |
| Cambia entre dev/test/prod | **`${CCC_*}`** + Helm (3 envs) |
| JNDI de BD | Ver `bank-secrets.md` — `${CCC-XXX-USER/PASSWORD}` (con guiones) |

## Anti-patrones prohibidos

- **NEVER** dejar una clave legacy sin mapear en `application.yml` si
  `properties-report.yaml` la listó.
- **NEVER** inventar un valor si el CSV / legacy / catálogo global no lo
  tiene. En ese caso usar `${CCC_*}` + comentario
  `# TODO: valor no disponible — solicitar al SRE`. "No lo tiene" significa
  `capamedia configurables` con **exit code 1**, no un `grep` vacío.
- **NEVER** enmascarar el resultado de una búsqueda con `|| echo "NO
  ENCONTRADO"` ni concluir ausencia desde una lista truncada con `head`: ambos
  convierten un fallo de herramienta en un falso negativo (WSSeguridad0069).
- **NEVER** declarar `${CCC_*}` huérfanos en Helm sin uso en `application.yml`.
- **NEVER** duplicar una clave del catálogo global (`bank-shared-properties.md`)
  como env var — es literal.

## Ámbito de aplicación

- ✅ **BUS (IIB)**: aplica `GestionarRecursoConfigurable`, `GestionarRecursoXML`,
  `CatalogoAplicaciones.properties`.
- ✅ **WAS**: aplica `.properties` files + `Propiedad.get(...)`.
- ✅ **ORQ**: aplica mismo tratamiento que BUS (también usa los nodos ESQL).
- ✅ **UMPs**: cuando el servicio las importa, sus properties cuentan como
  configurables del servicio final.

## Regla para el agente migrador

1. **Consumir** `properties-report.yaml` generado por `clone`.
2. **Para cada clave**: aplicar la tabla de decisión `literal vs env var`.
3. **Si es literal**: copiar valor exacto del CSV / `bank-shared-properties`
   / catálogo. Nunca inventar.
4. **Si es env var**: declarar `${CCC_*}` sin default + entrada en
   `helm/values-dev.yml`, `values-test.yml`, `values-prod.yml`.
5. **Ejecutar Block 19** del checklist antes de entregar. Si hay gaps,
   auto-corregir con `fix_yml_remove_defaults` o completar manualmente.
