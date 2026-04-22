---
name: checklist-rules
title: Reglas completas del checklist BPTPSRE (15 bloques)
description: Checklist oficial pass/fail con severidad HIGH/MEDIUM/LOW. Incluye BLOQUE
  0 con dialogo cruzado legacy vs migrado.
type: prompt
scope: project
stage: post-migration
source_kind: any
framework: any
complexity: high
preferred_model:
  anthropic: claude-opus-4-7
fallback_model: opus
allowed_tools:
- Read
- Glob
- Grep
- Bash
- Write
---

# 03 — Checklist Post-Migración (AI-ejecutable)

## ROL

Sos un auditor de código que revisa un microservicio Java Spring Boot ya migrado (IIB → Java, arquitectura hexagonal OLA1) contra las reglas vivas del equipo **BPTPSRE** de Banco Pichincha. Tu salida es un **reporte estructurado** con pass/fail por bloque, severidad, y acción sugerida por cada violación.

**NO modificas código.** Solo auditás y reportás. Los fixes se hacen en un flujo aparte.

## CUÁNDO SE USA

Después de correr el prompt de migración (`migracion/REST/02-REST-migrar-servicio.md` o `migracion/SOAP/02-SOAP-migrar-servicio.md` según el proyecto) y antes de abrir PR. También sirve para auditar servicios que ya están en `develop` antes de pasar a `release`.

## INPUT

Dos argumentos (el segundo es opcional pero recomendado):

1. **`<MIGRATED_PATH>`** — path absoluto al **proyecto migrado** (ej: `C:\Dev\Banco Pichincha\CapaMedia\0007\destino`). OBLIGATORIO.
2. **`<LEGACY_PATH>`** — path absoluto al **servicio legacy original** (ej: `C:\Dev\Banco Pichincha\CapaMedia\0007\legacy\sqb-msa-wsclientes0007`). OPCIONAL pero recomendado: habilita el análisis cruzado del BLOQUE 0 (WSDL legacy vs migrado, conteo de operaciones, nombres, namespaces).

Si no se pasa el segundo argumento, el BLOQUE 0 degrada a "solo cuenta en el WSDL copiado al proyecto migrado" y los Checks 0.3 y 0.4 se saltan con severidad **MEDIUM** (no se pudo cruzar con la fuente).

## FUENTES DE LAS REGLAS

Cada bloque referencia su origen para que el lector sepa de dónde viene:

- **[PDF-OFICIAL]** — PDFs del área BPTPSRE bajo `prompts/documentacion/` (documentos oficiales)
- **[FB-JG]** — Feedback del tech lead del equipo BPTPSRE (canal Slack interno)
- **[FB-JA]** — Feedback de desarrolladores del equipo BPTPSRE (canal Slack interno)
- **[COMMIT-XXXXX]** — Commit específico del repo de referencia
- **[MCP]** — Confluence del MCP fabrics (versiones de librerías)

---

## BLOQUE 0 — Pre-check: identificar tipo de proyecto y gold standard

Antes de auditar, detectar qué tipo de servicio es y qué gold standard le corresponde.

### Check 0.1 — Tipo de proyecto (SOAP vs REST)

```bash
# SOAP: existe @Endpoint o WebServiceConfig
grep -rl "@Endpoint\|WebServiceConfig" <PATH>/src/main/java

# REST: existe @RestController y NO @Endpoint
grep -rl "@RestController" <PATH>/src/main/java
```

**Decisión:**
- Hay `@Endpoint` → **SOAP** (gold standard: `tnd-msa-sp-wsclientes0015`, pero SOLO válido para WAS 2+ ops)
- Hay `@RestController` y no `@Endpoint` → **REST** (gold standard: `tnd-msa-sp-wsclientes0024`)
- Ambos o ninguno → **FAIL HIGH** (proyecto malformado)

> **ADVERTENCIA sobre wsclientes0015:** Fue originalmente un servicio BUS (IIB) migrado como SOAP. Bajo la matriz MCP actual, BUS+invocaBancs SIEMPRE va REST+WebFlux. El 0015 es gold standard SOLO para WAS con 2+ operaciones. Si el proyecto auditado es BUS y tiene patrones SOAP del 0015 (@Endpoint, WebServiceConfig, NamespacePrefixInterceptor, BancsClientHelper, .block()), es **mal-clasificado**.

### Check 0.2 — Clasificacion MCP: source type + parametro clave ↔ framework

**Principio del banco:** la matriz oficial es MCP-driven, basada en el tipo de origen legacy y el parametro MCP clave:

| Origen Legacy | Condicion | Parametro MCP clave | Framework correcto | Prompt |
|---|---|---|---|---|
| **BUS (IIB)** | invocaBancs=true | `invocaBancs: true` (override) | REST + WebFlux + `@RestController` | REST |
| **WAS** | 1 op WSDL | params estandar | REST + Spring MVC + `@RestController` | REST |
| **WAS** | 2+ ops WSDL | params estandar | SOAP + Spring MVC + `@Endpoint` | SOAP |
| **ORQ** | siempre | `deploymentType: orquestador` | REST + WebFlux + `@RestController` | REST |

- **BUS + invocaBancs:** el MCP ignora `projectType` y `webFramework` — siempre REST+WebFlux (1 o N ops)
- **WAS:** el conteo de operaciones decide REST MVC (1 op) vs SOAP MVC (2+ ops). BD presente es ortogonal
- **ORQ:** siempre WebFlux via `deploymentType: orquestador`

#### Paso 1 — Contar operaciones en el WSDL **migrado**

```bash
MIGRATED_WSDL=$(ls <MIGRATED_PATH>/src/main/resources/legacy/*.wsdl 2>/dev/null | head -1)

OPS_MIGRATED=$(awk '/<wsdl:portType/,/<\/wsdl:portType>/' "$MIGRATED_WSDL" \
  | grep -c "<wsdl:operation")

echo "Migrado tiene $OPS_MIGRATED operación(es) en el portType"
```

Si no se encuentra WSDL en `src/main/resources/legacy/` → **HIGH** (scaffold incompleto: el WSDL debe estar copiado ahí para que `generateFromWsdl` funcione).

#### Paso 2 — Contar operaciones en el WSDL **legacy original** (si `<LEGACY_PATH>` fue provisto)

```bash
if [ -n "<LEGACY_PATH>" ]; then
  LEGACY_WSDL=$(find <LEGACY_PATH> -name "*.wsdl" 2>/dev/null | head -1)
  OPS_LEGACY=$(awk '/<wsdl:portType/,/<\/wsdl:portType>/' "$LEGACY_WSDL" \
    | grep -c "<wsdl:operation")
  echo "Legacy tiene $OPS_LEGACY operación(es) en el portType"
else
  echo "Legacy NO fue provisto -> se salta cruce, se usa solo OPS_MIGRATED"
  OPS_LEGACY="$OPS_MIGRATED"
fi
```

#### Paso 3 — ¿Coinciden los conteos?

- `OPS_LEGACY == OPS_MIGRATED` → ✅ OK, el WSDL se copió fiel al legacy
- `OPS_LEGACY != OPS_MIGRATED` → **HIGH** "¡Che! El WSDL del proyecto tiene N operaciones pero el legacy tenía M. Revisá si se perdió o duplicó alguna operación al copiar."
- `<LEGACY_PATH>` no provisto → **MEDIUM** "No se pudo cruzar con el legacy; tomando el conteo del proyecto como fuente única."

#### Paso 4 — Detectar tipo de origen legacy

```bash
# Determinar si es BUS (IIB), WAS, o ORQ
# BUS: tiene *.esql
# WAS: tiene *.java + web.xml, no tiene *.esql
# ORQ: tiene *.esql + patron IniciarOrquestacionSOAP o nombre ORQ*
if [ -n "<LEGACY_PATH>" ]; then
  HAS_ESQL=$(find <LEGACY_PATH> -name "*.esql" 2>/dev/null | head -1)
  HAS_JAVA=$(find <LEGACY_PATH> -name "*.java" -path "*/src/*" 2>/dev/null | head -1)
  HAS_WEBXML=$(find <LEGACY_PATH> -name "web.xml" 2>/dev/null | head -1)

  if [ -n "$HAS_ESQL" ]; then
    SOURCE_TYPE="BUS"  # podria ser ORQ, verificar nombre
  elif [ -n "$HAS_JAVA" ] && [ -n "$HAS_WEBXML" ]; then
    SOURCE_TYPE="WAS"
  else
    SOURCE_TYPE="UNKNOWN"
  fi
else
  # Sin legacy path, inferir del migration-context.json
  SOURCE_TYPE=$(grep -o '"tecnologia_origen":\s*"[^"]*"' <MIGRATED_PATH>/migration-context.json 2>/dev/null \
    | sed 's/.*: *"\([^"]*\)"/\1/' | tr '[:lower:]' '[:upper:]')
fi
echo "Tipo de origen: $SOURCE_TYPE"
```

#### Paso 5 — Veredicto conversacional (diálogo explícito)

El reporte debe rendir este diálogo literal, con los valores reemplazados:

```
¿Cuál es el tipo de origen legacy? → $SOURCE_TYPE (BUS | WAS | ORQ)
¿Cuántas operaciones tiene el WSDL? → $OPS_LEGACY
¿Conecta con BANCS (invocaBancs)? → <SÍ | NO>
¿Qué framework corresponde según la matriz MCP? → <ver tabla abajo>
¿Qué framework se usó en la migración? → <projectType de Check 0.1>
¿Coincide lo usado con lo que la matriz pide? → <SÍ ✅ | NO ❌>
Veredicto final: <PASS | HIGH mal-clasificado | etc.>
```

#### Paso 6 — Reglas de severidad (matriz MCP-driven)

**BUS (IIB) + invocaBancs:**
- BUS + tipo REST (WebFlux) → ✅ **PASS** (cualquier cantidad de ops). Diálogo: *"Es BUS con invocaBancs, va REST+WebFlux. ¿Está OK? Sí, está OK."*
- BUS + tipo SOAP → **HIGH** (mal-clasificado). Diálogo: *"Es BUS con invocaBancs → debió ir REST+WebFlux. El MCP con invocaBancs=true ignora projectType/webFramework. Se migró como SOAP → está mal-clasificado."*

**WAS:**
- WAS + 1 op + tipo REST → ✅ **PASS**. Diálogo: *"Es WAS con 1 op, va REST+MVC. ¿Está OK? Sí, está OK."*
- WAS + 2+ ops + tipo SOAP → ✅ **PASS**. Diálogo: *"Es WAS con N ops, va SOAP+MVC. ¿Está OK? Sí, está OK."*
- WAS + 1 op + tipo SOAP → **HIGH** (mal-clasificado). Diálogo: *"Es WAS con 1 op → debió ir REST+MVC. Se migró como SOAP → está mal-clasificado."*
- WAS + 2+ ops + tipo REST → **HIGH** (mal-clasificado). Diálogo: *"Es WAS con N ops → REST no soporta dispatching multi-operation para WAS, necesita Spring WS sobre MVC."*
- WAS + tipo REST + `DB_USAGE: YES` → ✅ **PASS**. Diálogo: *"Es WAS con 1 op y BD → queda en REST+MVC con HikariCP+JPA. Correcto."*

**ORQ:**
- ORQ + tipo REST (WebFlux) → ✅ **PASS** (cualquier cantidad de ops). Diálogo: *"Es ORQ, va REST+WebFlux via deploymentType:orquestador. ¿Está OK? Sí, está OK."*
- ORQ + tipo SOAP → **HIGH** (mal-clasificado). Diálogo: *"Es ORQ → siempre va WebFlux. Se migró como SOAP → está mal-clasificado."*

**Hallazgo documentado:** wsclientes0007 es BUS (IIB) con 1 op y está migrado como SOAP. Bajo la nueva matriz MCP, esto es **mal-clasificado** (BUS+invocaBancs siempre va REST+WebFlux). Es un caso legacy que NO se reclasifica ahora por costo vs beneficio (ya está funcionando, pasa checklist, build verde). Los futuros servicios BUS deben usar REST+WebFlux (via `invocaBancs: true`).

**Guardar en el contexto del reporte:** `sourceType`, `invocaBancs`, `projectType`, `goldStandard`, `opsLegacy`, `opsMigrated`, `opsMatch`, `expectedFramework`, `actualFramework`, `frameworkMatch`.

---

### Check 0.3 — Nombres de operaciones: legacy = migrado

Requiere `<LEGACY_PATH>` provisto. Si no, **MEDIUM** (skip).

```bash
# Extraer nombres de operaciones del portType de cada WSDL
LEGACY_OPS=$(awk '/<wsdl:portType/,/<\/wsdl:portType>/' "$LEGACY_WSDL" \
  | grep -oE '<wsdl:operation name="[^"]+"' \
  | sed 's/.*name="\([^"]*\)".*/\1/' | sort)

MIGRATED_OPS=$(awk '/<wsdl:portType/,/<\/wsdl:portType>/' "$MIGRATED_WSDL" \
  | grep -oE '<wsdl:operation name="[^"]+"' \
  | sed 's/.*name="\([^"]*\)".*/\1/' | sort)

diff <(echo "$LEGACY_OPS") <(echo "$MIGRATED_OPS")
```

**Veredicto:**
- `diff` vacío → ✅ **PASS**. Todas las operaciones están en ambos WSDLs con el mismo nombre.
- Hay diferencias → **HIGH**. Reportar exactamente cuáles operaciones faltan o sobran, con el diff crudo. Diálogo: *"En el legacy está `<op1>` pero en el migrado no aparece. Se perdió en la migración."*

### Check 0.4 — `targetNamespace` del WSDL: legacy = migrado

Requiere `<LEGACY_PATH>` provisto. Si no, **MEDIUM** (skip).

```bash
LEGACY_NS=$(grep -oE 'targetNamespace="[^"]+"' "$LEGACY_WSDL" | head -1 | sed 's/.*="\([^"]*\)".*/\1/')
MIGRATED_NS=$(grep -oE 'targetNamespace="[^"]+"' "$MIGRATED_WSDL" | head -1 | sed 's/.*="\([^"]*\)".*/\1/')

[ "$LEGACY_NS" = "$MIGRATED_NS" ] && echo "OK" || echo "MISMATCH: legacy=$LEGACY_NS migrado=$MIGRATED_NS"
```

**Veredicto:**
- Coinciden → ✅ **PASS**
- Difieren → **HIGH**. Los consumidores existentes apuntan al namespace legacy; si el migrado lo cambió, rompe integración. Diálogo: *"El namespace legacy era `<X>`, el migrado es `<Y>`. Los callers antiguos no van a encontrar este endpoint. Hay que restaurar el namespace original o hacer una migración coordinada."*

### Check 0.5 — XSDs referenciados desde el WSDL están presentes

Requiere `<LEGACY_PATH>` provisto (opcional en migrado, pero útil).

```bash
# Listar imports de XSD desde el WSDL del proyecto migrado
grep -oE 'schemaLocation="[^"]+"' "$MIGRATED_WSDL" \
  | sed 's/.*="\([^"]*\)".*/\1/' \
  | while read SCHEMA; do
      BASENAME=$(basename "$SCHEMA")
      find <MIGRATED_PATH>/src/main/resources/ -name "$BASENAME" 2>/dev/null | head -1 \
        || echo "MISSING: $SCHEMA"
    done
```

**Veredicto:**
- Todos los XSDs referenciados existen → ✅ **PASS**
- Alguno falta → **HIGH** (el build `generateFromWsdl` va a fallar). Diálogo: *"El WSDL importa `<schema>.xsd` pero no está copiado en `src/main/resources/`. Copialo del legacy o arregla el `schemaLocation`."*

---

---

## BLOQUE 1 — Arquitectura hexagonal

**Origen:** [PDF-OFICIAL] (sección Arquitectura) + [FB-JG] (UN solo output port Bancs)

### Check 1.1 — Capas presentes

```bash
ls <PATH>/src/main/java/com/pichincha/sp/
# Debe contener: application/ domain/ infrastructure/
```

**Severidad si falta alguna:** HIGH.

### Check 1.2 — Domain SIN imports de framework

```bash
grep -rE "import (org\.springframework|jakarta\.persistence|org\.springframework\.web|org\.springframework\.http|javax\.ws)" <PATH>/src/main/java/com/pichincha/sp/domain/
```

Esperado: **0 matches**. Cualquier hit es **HIGH**.

### Check 1.3 — Puertos son interfaces

```bash
grep -l "public abstract class.*Port\|public abstract class.*InputPort\|public abstract class.*OutputPort" <PATH>/src/main/java/com/pichincha/sp/application/
```

Esperado: **0 archivos**. Abstract classes para puertos es desviación (caso wsclientes0007 original). **HIGH**.

### Check 1.4 — UN SOLO output port Bancs [FB-JG]

```bash
ls <PATH>/src/main/java/com/pichincha/sp/application/*/port/output/ | grep -iE "bancs|Bancs"
```

- 0 ports Bancs → ⚠ MEDIUM (puede ser intencional si el servicio no llama a Bancs)
- 1 port Bancs → ✓ PASS
- 2+ ports Bancs → **HIGH**. Unificar en un solo port con múltiples métodos.

**Acción sugerida:** consolidar métodos en un único `BancsCustomerOutputPort` (o nombre equivalente al dominio del servicio). La pluralidad de adapters/helpers a nivel infrastructure sigue siendo válida; lo que se unifica es el puerto visible desde application.

**Referencia:** wsclientes0015 tiene 3 ports Bancs (`CustomerAddressBancsPort`, `GeoLocationBancsPort`, `CorrespondenceBancsPort`) — **NO replicar**. wsclientes0024 y wsclientes0007 cumplen.

### Check 1.5 — Adaptadores implementan puertos (no abstract class)

```bash
grep -l "extends.*Port\s" <PATH>/src/main/java/com/pichincha/sp/infrastructure/
```

Esperado: **0 archivos** (deben usar `implements` sobre interfaces). **MEDIUM**.

### Check 1.6 — Service Purity: CERO métodos privados en services [FB-JG]

Los services (`application/service/`) deben contener **SOLO** las implementaciones de los métodos de la interfaz del input port. Son orquestadores puros — delegan a output ports y a utilities de `application/util/`. **CERO métodos privados** (validaciones, normalizaciones, formateos, builders) dentro de la clase service.

```bash
# Buscar métodos privados en services (excluyendo campos private final)
grep -rnE "^\s+private\s+(?!final)" <PATH>/src/main/java/com/pichincha/sp/application/service/*.java
```

Cualquier match → **HIGH**. Acción: extraer cada método privado a una clase helper en `application/util/`:
- `private void validateRequest(...)` → `application/util/<Domain>ValidationHelper.java`
- `private <Type> normalize*(...)` → `application/util/<Domain>NormalizationHelper.java`
- `private <Type> format*(...)` → `application/util/<Domain>FormatHelper.java`
- `private <Type> build*(...)` → `application/util/<Domain>BuilderHelper.java`

```bash
# Verificar que existen helpers en application/util/ si el servicio tiene lógica de negocio
find <PATH>/src/main/java/com/pichincha/sp/application/util/ -name "*Helper.java" -o -name "*Util.java" | wc -l
```

- 0 archivos y el servicio tiene validaciones/normalizaciones → **HIGH** (la lógica está enterrada en el service).
- ≥ 1 archivo → ✅ PASS (la lógica está correctamente extraída).

**Justificación:** services con métodos privados se convierten en clases gordas que violan SRP, son difíciles de testear unitariamente en aislamiento, y generan conflictos de merge cuando múltiples desarrolladores tocan el mismo archivo. Extraer a `application/util/` hace cada concern independientemente testeable y reutilizable entre services.

**Referencia:** regla incorporada para evitar la acumulación de lógica auxiliar en services observada en migraciones anteriores.

---

## BLOQUE 2 — Logging y tracing

**Origen:** [PDF-OFICIAL] (sección Log) + [FB-JG] (@BpLogger en TODOS los services)

### Check 2.1 — `@BpTraceable` en Controllers

```bash
grep -L "@BpTraceable" <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/*/impl/*Controller.java
```

Cualquier archivo listado (sin la anotación) es **HIGH**.

### Check 2.2 — `@BpLogger` en TODOS los métodos públicos de @Service [FB-JG]

```bash
# Para cada Service bean, contar métodos públicos vs @BpLogger
for f in <PATH>/src/main/java/com/pichincha/sp/application/service/*.java; do
  pub=$(grep -cE "^\s+public\s+\w+\s+\w+\(" "$f")
  bpl=$(grep -c "@BpLogger" "$f")
  [ "$pub" -gt "$bpl" ] && echo "FAIL: $f (public=$pub, @BpLogger=$bpl)"
done
```

Si `public > @BpLogger` en cualquier service → **HIGH**. Cada método público debe tener `@BpLogger`.

**Referencia:** wsclientes0015 viola esto (2 de 3 services sin la anotación) — **NO replicar**.

### Check 2.3 — `@BpLogger` en Adapters de infrastructure

```bash
grep -L "@BpLogger" <PATH>/src/main/java/com/pichincha/sp/infrastructure/output/adapter/**/*Adapter.java
```

Archivos listados → **MEDIUM** (ideal que lo tengan; no bloqueante si el método es trivial).

### Check 2.4 — Logs con GUID y niveles adecuados

```bash
# Buscar logs sin GUID
grep -rnE "log\.(info|warn|error)\(\"[^{]*\"\)" <PATH>/src/main/java/com/pichincha/sp/application/
```

**MEDIUM** si hay logs que no incluyen `guid` ni contexto. Los logs deben tener formato `[guid: {}] <mensaje>` donde aplique.

### Check 2.5 — Sin imports de `org.slf4j` [FB-JG]

```bash
grep -rnE "import org\.slf4j\." <PATH>/src/main/java/
```

Cualquier match → **HIGH**. El proyecto debe usar exclusivamente la librería de logging del banco (`ServiceLogHelper`, `@BpLogger`, `@BpTraceable`). Los imports directos de `org.slf4j.Logger`, `org.slf4j.LoggerFactory` o la anotación Lombok `@Slf4j` están prohibidos porque duplican el logging y no se integran con la trazabilidad corporativa.

**Patrón incorrecto (detectado en wsclientes0007):**
```java
import org.slf4j.Logger;           // ← PROHIBIDO
import org.slf4j.LoggerFactory;    // ← PROHIBIDO

private static final Logger LOGGER =
    LoggerFactory.getLogger(MyController.class);  // ← PROHIBIDO

LOGGER.warn("algo");  // duplica el log de ServiceLogHelper
log.warn("algo");     // este es el correcto (ServiceLogHelper)
```

**Acción:** eliminar imports `org.slf4j.*`, campos `Logger`/`LoggerFactory`, y todas las llamadas `LOGGER.xxx(...)`. Quedarse solo con `ServiceLogHelper log` inyectado.

### Check 2.6 — `log.info` reservado para eventos de contrato [FB-JA] [Rule 9e.1]

`log.info` debe usarse solo para eventos operativos reales (inicio/fin de operación de negocio, éxito de TX Bancs con efecto colateral). Logs de diagnóstico intermedio (*"Basic info retrieved for CIF: X"*) van en `log.debug`.

```bash
# Heurística — logs con verbos típicos de diagnóstico en info
grep -rnE "log\.info\(\"(Basic|Retrieved|Starting|Processing|Got|Found|Mapping|Normalizing)" \
    <PATH>/src/main/java/com/pichincha/sp/application/
```

Cualquier match → **MEDIUM**. Revisar si son eventos de contrato o diagnóstico. Si es diagnóstico → pasar a `log.debug` (ServiceLogHelper ya lo soporta).

**Referencia:** feedback del equipo [FB-JA] sobre wsclientes0007 (`log.info("Basic info retrieved for CIF: {}", ...)` bajado a debug en post-fix).

### Check 2.7 — No abuso de log.info

```bash
grep -rc "log\.info\|logLevelHandler.log(CustomLogLevel.INFO" <PATH>/src/main/java/ | awk -F: '$2 > 5 {print}'
```

Archivos con más de 5 log.info → **LOW** (revisar si son necesarios o son "logs de navegación").

---

## BLOQUE 3 — Naming de métodos y convenciones

**Origen:** [FB-JG] (queryX → getX) + [COMMIT-bf913b9] (PascalCase localPart)

### Check 3.1 — Output ports usan `get*` para lecturas [FB-JG]

```bash
grep -rnE "^\s*\w+\s+query\w+\(" <PATH>/src/main/java/com/pichincha/sp/application/*/port/output/
```

Cualquier método `query*` en puertos de lectura → **HIGH**.

**Regla:**
- Lecturas → `get*` (ej: `getCustomerInfo`, `getTransactionalContact`)
- Mutaciones → `create*` / `update*` / `delete*`
- `query*` **PROHIBIDO** para lecturas.

### Check 3.2 — `@PayloadRoot.localPart` = PascalCase [COMMIT-bf913b9] (solo SOAP)

```bash
grep -nE "localPart\s*=\s*\"[a-z]" <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/soap/impl/*Controller.java
```

Cualquier `localPart` que empiece en minúscula → **HIGH**. Debe matchear EXACTO el nombre del elemento raíz del XSD (PascalCase en servicios IIB legacy).

**Ejemplo correcto:**
```java
@PayloadRoot(namespace = NAMESPACE_URI,
    localPart = "ConsultarContactoTransaccional01")  // PascalCase
public ConsultarContactoTransaccional01Response
    consultarContactoTransaccional01(...) { ... }     // método Java: camelCase
```

### Check 3.3 — Java method name = camelCase

```bash
grep -nE "public\s+[A-Z]\w+Response\s+[A-Z]\w+\(" <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/*/impl/*Controller.java
```

Método en PascalCase → **MEDIUM** (rompe convención Java).

### Check 3.5 — Naming profesional: sin nombres genéricos en clases, variables ni campos [FB-JG]

Clases, variables inyectadas, y campos deben ser **específicos al dominio de negocio**. Nombres genéricos como `service`, `adapter`, `port`, `request`, `response`, `data`, `result`, `dto`, `entity`, `mapper` **sin prefijo de dominio** dificultan la lectura, generan ambigüedad cuando el proyecto crece, y no pasan peer review.

#### 3.5.1 — Clases con nombres genéricos

```bash
# Buscar clases sin dominio — solo nombre genérico
find <PATH>/src/main/java/com/pichincha/sp -name "*.java" | xargs grep -l "^public class \|^public interface \|^public record " | while read f; do
  BASENAME=$(basename "$f" .java)
  echo "$BASENAME" | grep -qxE "(Service|ServiceImpl|Adapter|Port|InputPort|OutputPort|Controller|Mapper|Helper|Request|Response|Dto|Config|Constants|Exception)" \
    && echo "GENERIC CLASS: $BASENAME in $f"
done
```

Cualquier match → **HIGH**. Ejemplos de violación y corrección:

| Incorrecto (genérico) | Correcto (dominio explícito) | Por qué |
|---|---|---|
| `ServiceImpl.java` | `CustomerServiceImpl.java` | No dice QUÉ servicio |
| `Adapter.java` | `CustomerAdapterBancs.java` | No dice QUÉ adapta ni HACIA dónde |
| `InputPort.java` | `ConsultarClienteInputPort.java` | No dice QUÉ operación expone |
| `OutputPort.java` | `BancsCustomerOutputPort.java` | No dice QUÉ downstream ni dominio |
| `Request.java` | `CustomerRequest.java` | No dice QUÉ request |
| `Response.java` | `ConsultarContactoResponse.java` | No dice de QUÉ operación |
| `Mapper.java` | `BancsCustomerMapper.java` | No dice QUÉ mapea ni entre qué capas |
| `Helper.java` | `SoapResponseHelper.java` | No dice QUÉ ayuda |
| `Controller.java` | `WSClientes0024Controller.java` | No dice QUÉ servicio |
| `Config.java` | `WebClientProperties.java` | No dice QUÉ configura |

#### 3.5.2 — Variables inyectadas con nombres genéricos

```bash
# Buscar campos inyectados con nombre genérico (private final <Type> service/port/adapter/mapper/helper)
grep -rnE "private final \w+ (service|port|adapter|mapper|helper|client|repository|config)\s*;" \
    <PATH>/src/main/java/com/pichincha/sp/
```

Cualquier match → **MEDIUM**. El nombre del campo debe reflejar el dominio:

| Incorrecto | Correcto | Contexto |
|---|---|---|
| `private final CustomerServicePort service;` | `private final CustomerServicePort customerService;` | En el Controller |
| `private final BancsCustomerPort port;` | `private final BancsCustomerPort bancsCustomerPort;` | En el Service |
| `private final BancsClient client;` | `private final BancsClient bancsClient;` | En el Adapter |
| `private final SoapCustomerMapper mapper;` | `private final SoapCustomerMapper soapCustomerMapper;` | En el Controller |
| `private final BancsCustomerMapper mapper;` | `private final BancsCustomerMapper bancsCustomerMapper;` | En el Adapter |

**Excepción aceptada:** `private final CustomLogLevelHandler customLogLevelHandler;` y `private final ServiceLogHelper log;` — son nombres canónicos del banco.

#### 3.5.3 — Variables locales y parámetros genéricos

```bash
# Buscar variables locales con nombres genéricos en métodos de negocio
grep -rnE "\b(var|String|Object|Mono|List)\s+(data|result|response|request|value|item|obj|temp|tmp|res|req|ret)\s*[=;]" \
    <PATH>/src/main/java/com/pichincha/sp/application/service/
```

Cualquier match en `application/service/` → **MEDIUM**. En la capa de negocio, las variables deben contar la historia del dominio:

| Incorrecto | Correcto | Contexto |
|---|---|---|
| `var result = bancsPort.getCustomerInfo(...)` | `var customerInfo = bancsPort.getCustomerInfo(...)` | Describe QUÉ contiene |
| `var response = bancsClient.call(...)` | `var bancsResponse = bancsClient.call(...)` | Clarifica el ORIGEN |
| `var data = mapper.toCustomer(...)` | `var customer = mapper.toCustomer(...)` | Nombra la ENTIDAD |
| `var request = CustomerRequest.builder()...` | `var customerRequest = CustomerRequest.builder()...` | Evita colisión con parámetro |
| `var item : collection` | `var address : customerAddresses` | Nombra la COSA que itera |

**Excepción aceptada:** variables en lambdas de una línea (`ex -> ...`, `e -> ...`, `t -> ...`) y parámetros de MapStruct `@Mapping` — el contexto es suficiente.

#### 3.5.4 — Constantes genéricas

```bash
# Buscar constantes con nombres que no identifican su propósito
grep -rnE "static final String (ERROR|MESSAGE|CODE|VALUE|NAME|TYPE|STATUS|DEFAULT|PARAM)\s*=" \
    <PATH>/src/main/java/com/pichincha/sp/
```

Cualquier match → **MEDIUM**. Las constantes deben autodocumentarse:

| Incorrecto | Correcto |
|---|---|
| `static final String ERROR = "999";` | `static final String ERROR_CODE_SERVICE = "9999";` (del catálogo `errores.xml`) |
| `static final String MESSAGE = "OK";` | `static final String SUCCESS_MESSAGE_BANCS = "OK";` |
| `static final String CODE = "0";` | `static final String SUCCESS_CODE = "0";` |
| `static final String NAME = "WSClientes0024";` | `static final String WS_COMPONENTE = "WSClientes0024";` |

**Referencia:** `CatalogExceptionConstants` debe usar el patrón `CONTEXT_NOUN` con códigos del catálogo oficial `sqb-cfg-errores-errors/errores.xml`: `WS_RECURSO`, `SUCCESS_CODE`, `ERROR_CODE_SERVICE` (9999), `ERROR_CODE_BANCS_INVOKE` (9929), `ERROR_CODE_BANCS_PARSE` (9922), `ERROR_CODE_HEADER` (9927).

### Check 3.4 — `postProcessWsdl.groovy` sin decapitalize activo [COMMIT-bf913b9] (solo SOAP)

Solo detecta **invocaciones activas** de `decapitalize` (no la mera declaración de la función).

```bash
# Invocaciones activas (call-site): variable.decapitalize(...) o = decapitalize(...)
grep -nE "\.decapitalize\(|= decapitalize\(" <PATH>/gradle/postProcessWsdl.groovy
```

Cualquier match → **HIGH**. Revertido en commit `bf913b9` del 0007 (ver Historial).

**Nota:** las funciones `injectXmlRootElement()` y `updatePackageInfo()` son **necesarias** en el patrón del banco (generan `@XmlRootElement` y `package-info.java`), NO son problemáticas. Solo `decapitalize` invocada activamente rompería el PascalCase de los elementos raíz.

---

## BLOQUE 4 — Validaciones

**Origen:** [FB-JG] (validaciones de header en infrastructure)

### Check 4.1 — `HeaderRequestValidator` existe en infrastructure [FB-JG]

```bash
find <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/*/util/ -name "HeaderRequestValidator.java"
```

- 0 archivos → **HIGH**. Falta el validador de header.
- 1 archivo en la ubicación correcta → ✓ PASS
- Existe en `domain/` o `application/` → **HIGH** (ubicación incorrecta)

### Check 4.2 — HeaderRequestValidator NO está en domain/application

```bash
find <PATH>/src/main/java/com/pichincha/sp/domain/ <PATH>/src/main/java/com/pichincha/sp/application/ -name "HeaderRequestValidator.java" -o -name "*HeaderValidator*.java"
```

Cualquier archivo encontrado → **HIGH**.

### Check 4.3 — Controller invoca al validator

```bash
# El Controller debe inyectar HeaderRequestValidator (Rule 9e.2) y llamar a
# validator.validate(...) — NO llamada estática HeaderRequestValidator.validate(...)
grep -rnE "headerValidator\.validate\(|HeaderRequestValidator\s+headerValidator" \
    <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/*/impl/*Controller.java
```

- 0 matches → **MEDIUM** (el validator existe pero no se usa, o sigue siendo estático).
- Si se encuentra `HeaderRequestValidator\.validate\(` (con punto, llamada estática sobre la clase) → **HIGH** (viola Rule 9e.2).

### Check 4.4 — Validaciones de body/business siguen en domain/application

Body validations (ej: CIF vacío, identificación inválida) **SÍ van en application/service** con `BusinessValidationException`. Este check es informativo — no es violación.

### Check 4.5 — HeaderRequestValidator rechaza header null y bloque `<bancs>` faltante [Rule 9b]

```bash
grep -A6 "Optional<String> validate" \
    <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/soap/util/HeaderRequestValidator.java \
  | grep -cE "header == null|getBancs\(\) == null"
```

- 0 matches → **HIGH**. El servicio permite header null o sin `<bancs>`, lo que provoca `NullPointerException` en el Core Adapter o headers corporativas vacías hacia Bancs.
- 1 match (solo `header == null`) → **HIGH**. Falta validar `getBancs() == null`.
- 2 matches ✓ PASS.

**Mensaje requerido (canónico del catálogo `sqb-cfg-errores-errors`, error 9927):**
```
"Datos de la cabecera de la transaccion no se han asignado"
```

```bash
grep -c "Datos de la cabecera de la transaccion no se han asignado" \
    <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/soap/util/HeaderRequestValidator.java
```
- 0 matches → **MEDIUM** (mensaje custom en vez del canónico).
- ≥ 1 match ✓ PASS (puede ser 1 constante reusada o 2 literales).

**Referencia:** wsclientes0007 post-fix (commit `bbcc62a`).

### Check 4.6 — Patterns de validación del header externalizados [FB-JA] [Rule 9e.2]

Los patterns regex del `HeaderRequestValidator` deben venir de `@ConfigurationProperties` — NO hardcoded como `private static final Pattern` — para permitir override vía ConfigMap de OpenShift sin redeploy del artefacto.

```bash
# No debe haber Pattern.compile hardcoded en el validator
grep -cE "private static final Pattern|Pattern\.compile\(\"\^" \
    <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/soap/util/HeaderRequestValidator.java
```

\> 0 matches → **HIGH**. Los patterns deben salir de una clase `@ConfigurationProperties` inyectada por constructor.

```bash
# Debe existir HeaderValidationProperties con prefix correcto
find <PATH>/src/main/java/com/pichincha/sp/infrastructure/config -name "HeaderValidationProperties.java" | wc -l
grep "prefix = \"header-validation.patterns\"" \
    <PATH>/src/main/java/com/pichincha/sp/infrastructure/config/HeaderValidationProperties.java 2>/dev/null | wc -l
```

Alguno 0 → **HIGH**.

```bash
# El validator es @Component (no final class estática)
grep -cE "^@Component|public class HeaderRequestValidator" \
    <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/soap/util/HeaderRequestValidator.java
```

< 2 matches → **HIGH** (el validator debe ser `@Component` con inyección de props, no `final class` con métodos estáticos).

**Referencia:** feedback del equipo [FB-JA] sobre wsclientes0007; refactor aplicado en post-fix.

---

## BLOQUE 5 — Error handling y propagación de errores Bancs

**Origen:** [FB-JG] (error propagation) + [FB-JG] (localPart casing ya en bloque 3)

### Check 5.1 — `BancsClientHelper.execute()` atrapa RuntimeException [FB-JG]

```bash
grep -A5 "public <T> T execute" <PATH>/src/main/java/com/pichincha/sp/infrastructure/output/adapter/bancs/helper/BancsClientHelper.java | grep -c "catch\s*(\s*RuntimeException"
```

0 matches → **HIGH**. Sin este catch, `WebClientResponseException` burbujea como RuntimeException y el Controller devuelve "9999 Error al procesar el servicio" genérico en vez del error real de Bancs.

**Patrón requerido (códigos del catálogo `sqb-cfg-errores-errors/errores.xml`):**
```java
try {
  response = doCall(txCode, ctx, body, responseType);
} catch (BancsOperationException e) {
  throw e;
} catch (RuntimeException e) {
  throw new BancsOperationException(
    CatalogExceptionConstants.ERROR_CODE_BANCS_INVOKE,  // "9929" from errores.xml
    e.getMessage() != null ? e.getMessage() : "Error al invocar transaccion Bancs",
    txCode);
}
```

**Referencia:** wsclientes0015 NO lo tiene (hueco del gold standard). wsclientes0007 lo cubrió post-feedback del tech lead [FB-JG].

### Check 5.2 — Controller/Service atrapa BancsOperationException

```bash
grep -rn "catch\s*(\s*BancsOperationException" <PATH>/src/main/java/com/pichincha/sp/
```

0 matches → **HIGH**. Sin catch, el error nunca llega al cliente SOAP/REST con código estructurado.

**Ubicación válida:** Controller (patrón 0007) o Service (patrón 0015). Uno u otro, no ambos.

### Check 5.3 — No hay SOAP Faults — todo es HTTP 200 con `<error>` (solo SOAP)

```bash
grep -rn "SoapFaultException\|MessageFaultException\|throw.*SoapFault" <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/soap/
```

Cualquier match → **HIGH**. Errores se devuelven como response válido con `tipo='ERROR'`, nunca como SOAP fault (compatibilidad IIB).

### Check 5.4 — `error.backend` viene del catálogo oficial, no hardcodeado [FB-JG]

```bash
# Buscar constantes hardcodeadas que setean error.backend
grep -rnE "BACKEND_CODE\s*=\s*\"00000\"|setBackend\(\"[^\"]+\"\)" <PATH>/src/main/java/
# Buscar que exista la configuración
grep -E "error-codes:|iib:|bancs-app:" <PATH>/src/main/resources/application*.yml
```

**Origen:** UMP legacy leía `Environment.cache.codigosBackend.iib` y `.bancs_app` del cache del IIB (poblado por el repo oficial `sqb-cfg-codigosBackend-config/codigosBackend.xml`).

**Catálogo oficial del banco:**
- `iib` = `"00638"` — Middleware Integracion (IIB), usado en success y BusinessValidationException
- `bancs_app` = `"00045"` — Core Bancario (BANCS), usado en BancsOperationException

**Violaciones:**
- `BACKEND_CODE = "00000"` hardcodeado en un `*Constants.java` → **HIGH**. `"00000"` no corresponde a ningún backend real del banco.
- `setBackend("")` o `setBackend("00000")` literal en el helper/controller → **HIGH**.
- No existe sección `bancs.error-codes` en `application.yml` → **HIGH**.
- Existe sección pero sin variable ENV (`${CCC_...}`) que permita override por entorno → **MEDIUM**.

**Patrón correcto (ver 0007 post-fix):**
```java
// application.yml
bancs:
  error-codes:
    iib: ${CCC_BANCS_ERROR_CODE_IIB:00638}
    bancs-app: ${CCC_BANCS_ERROR_CODE_BANCS_APP:00045}

// BancsErrorCodesProperties.java
@ConfigurationProperties(prefix = "bancs.error-codes")
public record BancsErrorCodesProperties(String iib, String bancsApp) {}

// SoapResponseHelper.java — constructor inyecta props
// buildSuccessResponse → backendCodes.iib()
// buildErrorResponse   → backendCodes.iib()  (BusinessValidationException)
// buildBancsErrorResponse → backendCodes.bancsApp()  (BancsOperationException)
```

**Referencia:** wsclientes0024/0013/0006 (golds) todos tienen el bug `"00000"` — **no replicar**. wsclientes0007 lo corrigió en post-auditoría (ver Historial).

### Check 5.5 — BusinessValidationException en domain

```bash
grep -l "BusinessValidationException" <PATH>/src/main/java/com/pichincha/sp/domain/exception/
```

0 matches → **HIGH**. Debe existir en `domain/exception/`.

### Check 5.6 — `error.tipo` sigue la clasificación INFO/ERROR/FATAL [Rule 9d]

**Reglas del legacy IIB (ver `reference_error_types.md` en memoria):**

| Tipo | Cuándo | Ejemplo |
|---|---|---|
| `INFO` | Success o resultado esperado sin datos | flujo OK |
| `ERROR` | Validación de negocio recuperable por caller | `BusinessValidationException` (CIF vacío, identificación inválida) |
| `FATAL` | Falla técnica/infra no recuperable | header faltante, `BancsOperationException`, Exception genérica |

**Check 5.6.1 — Constante `ERROR_TYPE_FATAL` existe**

```bash
grep -E 'ERROR_TYPE_FATAL\s*=\s*"FATAL"' \
    <PATH>/src/main/java/com/pichincha/sp/infrastructure/exception/CatalogExceptionConstants.java
```

0 matches → **HIGH**. Sin la constante no puede cumplirse el mapeo completo.

**Check 5.6.2 — El Helper expone los 3 builders diferenciados**

```bash
grep -cE "public .* buildSuccessResponse|public .* buildErrorResponse|public .* buildFatalResponse|public .* buildBancsErrorResponse" \
    <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/soap/helper/SoapResponseHelper.java
```

< 4 matches → **HIGH**. Faltan builders; ver patrón en sección 4.5 del prompt SOAP.

**Check 5.6.3 — El Controller mapea cada rama al builder correcto**

```bash
# BancsOperationException debe ir a buildBancsErrorResponse, NO a buildErrorResponse
grep -B2 "buildErrorResponse" <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/soap/impl/*Controller.java \
  | grep -E "BancsOperationException|catch \(Exception"
```

Cualquier match → **HIGH**. Indica que `BancsOperationException` o `catch (Exception)` están siendo ruteados al builder `ERROR` en vez de `FATAL`/`buildBancsErrorResponse`.

```bash
# El validador de header debe usar buildFatalResponse (no buildErrorResponse).
# Usar -A8 porque el return queda ~5 líneas debajo del isPresent()
# (comentario + log.warn con continuación de línea + return multilínea).
grep -A8 "validationError.isPresent" <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/soap/impl/*Controller.java \
  | grep -cE "buildFatalResponse"
```

0 matches → **HIGH**. Header-faltante debe ser tipo=FATAL (es falla técnica, caller no puede corregirlo sin enviar el bloque bancs).

**Check 5.6.4 — Tests asertan `tipo` explícitamente**

```bash
grep -cE 'assertEquals\("(INFO|ERROR|FATAL)",.*getTipo' \
    <PATH>/src/test/java/com/pichincha/sp/infrastructure/input/adapter/soap/**/*.java
```

< 4 matches → **MEDIUM**. Cada rama del Controller debe tener al menos un test que asierte el `tipo` (success=INFO, business=ERROR, bancs=FATAL, unexpected=FATAL).

**Referencia:** wsclientes0007 post-fix (tipo FATAL para header-missing + Bancs + Exception genérica). Los golds 0024/0013/0006 NO aplican esta clasificación — **no replicar**.

---

## BLOQUE 6 — Mappers y tipos

**Origen:** [FB-JG] (usar mappers, evitar genéricos)

### Check 6.1 — Mappers dedicados existen

```bash
find <PATH>/src/main/java -type d -name "mapper"
```

Debe haber al menos:
- `infrastructure/input/adapter/*/mapper/` (request SOAP/REST → domain)
- `infrastructure/output/adapter/bancs/mapper/` (Bancs DTO → domain)

0 o 1 carpeta → **MEDIUM**.

### Check 6.2 — MapStruct en mappers

```bash
# Total mappers
find <PATH>/src/main/java -name "*Mapper.java" -path "*/mapper/*" | wc -l
# Cuántos usan @Mapper
grep -rl "@Mapper" <PATH>/src/main/java/**/mapper/ | wc -l
```

**Reglas:**
- 0 mappers con `@Mapper` → **MEDIUM**. Ideal usar MapStruct.
- ≥ 1 mapper con `@Mapper` y el resto manuales → **PASS** si los manuales tienen Javadoc que justifica por qué (ej: transformación uniforme `nullSafeValue` de N campos String→String). **MEDIUM** si no documentan.
- 100% manuales → **MEDIUM** — aunque sean simples, conviene al menos tener MapStruct en el mapper BANCS→domain (response mapping).

**Regla de oro:** MapStruct aporta valor cuando hay mapping con **nombres distintos** o **tipos distintos** o **lógica de transformación no trivial**. Cuando es 1-a-1 con una sola función uniforme (ej: `nullSafe`), MapStruct oscurece más de lo que ayuda — documentar la decisión en el Javadoc del mapper.

**Verificación documentación:**
```bash
# Cada mapper manual debe tener Javadoc que mencione "MapStruct" o "@Mapper"
for f in $(find <PATH>/src/main/java -name "*Mapper.java" -path "*/mapper/*"); do
  if ! grep -q "@Mapper" "$f"; then
    grep -l "MapStruct\|@Mapper" "$f" || echo "UNDOCUMENTED: $f"
  fi
done
```

### Check 6.3 — Sin `new Record(>=8 args)` inline en services [FB-JG]

```bash
grep -rnE "new \w+\([^;]{200,}" <PATH>/src/main/java/com/pichincha/sp/application/service/*.java
```

Cualquier match → **MEDIUM**. Si un service construye un record con muchos argumentos, extraer a factory estático en el record (ej: `Result.success(...)`, `Result.failure(...)`) como hace wsclientes0015 con `ConsultAddressesResult`.

### Check 6.4 — Sin `Object`/`Map<String, Object>` en contratos de puertos [FB-JG]

```bash
grep -rnE "\b(Object|Map<String,\s*Object>|\?\s*>)\b" <PATH>/src/main/java/com/pichincha/sp/application/*/port/
```

Cualquier match → **HIGH**. Excepciones justificadas (deben documentarse):
- Helpers de infra con binding genérico `<T>` (ej: `BancsClientHelper.execute(..., Object body, Class<T>)`)
- Logging varargs (`Object... data`)

Si el match es en un puerto de application → siempre **HIGH**.

---

## BLOQUE 7 — Configuración externa

**Origen:** [PDF-OFICIAL] (Application.yml, Azure pipeline, Helm) + [FB-JG] (catalog-info.yaml detallado)

### Check 7.1 — `catalog-info.yaml` completo [FB-JG]

Verificar:
- `spec.owner: jgarcia@pichincha.com` (NO `<owner>`)
- `spec.lifecycle: test` (NO `<lifecycle>`)
- `spec.system: ""` (vacío)
- `spec.domain: ""` (vacío)
- `spec.definition:` **ELIMINADO** (no debe existir el bloque)
- `links[]` NO incluye URL de SwaggerHub
- `annotations.dynatrace.com/dynatrace-entity-id: ""` (vacío)
- `annotations.sonarcloud.io/project-key` con el ID real del proyecto Sonar
- `spec.dependsOn` lista librerías del banco (ej: `lib-bnc-api-client`), NO `frm-spa-optimus-core`
- `tags` BIAN pendientes de confirmación (comentadas o placeholder explícito)

```bash
# Quick scan:
grep -E "<owner>|<lifecycle>|<domain>|<system>|swaggerhub\.com|definition:" <PATH>/catalog-info.yaml
```

Cualquier match → **HIGH** (placeholders sin completar).

### Check 7.2 — `azure-pipelines.yml` alineado [PDF-OFICIAL]

```bash
grep -E "KUBERNETES_NAMESPACE|CMDB_APPLICATION_ID" <PATH>/azure-pipelines.yml
```

Verificar:
- `KUBERNETES_NAMESPACE` = namespace correcto del microservicio (ej: `tnd-middleware`)
- `CMDB_APPLICATION_ID` = `"Red Hat OpenShift Container Platform"` (NO `CAPA_COMUN`)

Mismatch → **HIGH**.

### Check 7.3 — `application.yml` usa variables ENV del Helm [PDF-OFICIAL]

```bash
grep -nE "^\s*(password|secret|url|host|user):\s*[^$]" <PATH>/src/main/resources/application*.yml
```

Cualquier valor hardcoded para secrets/urls → **HIGH**. Deben ser `${VAR_NAME:default}`.

### Check 7.4 — Validar configuraciones de Bancs, WebClient, Circuit Breaker [PDF-OFICIAL]

```bash
grep -E "bancs:|resilience4j:|circuitbreaker:" <PATH>/src/main/resources/application*.yml
```

Secciones esperadas: `bancs:` y `resilience4j:`. Faltante → **MEDIUM**.

**NOTA (patrón del banco):** el webclient connector no va en una sección `webclient:` top-level — vive **dentro** de cada `bancs.webclients.<ws-txNNNNNN>.connector.*`. Verificar que cada webclient tiene `connect-timeout`, `read-timeout`, `max-connections`, `max-idle-time`, `pending-acquire-*` dentro de su nodo. Si NO tiene el `connector:` anidado → **MEDIUM**.

### Check 7.5 — Helm con valores por entorno [PDF-OFICIAL]

```bash
ls <PATH>/helm/dev.yml <PATH>/helm/test.yml <PATH>/helm/prod.yml 2>/dev/null
```

**NOTA (patrón del banco):** el naming oficial es `dev.yml`, `test.yml`, `prod.yml` (NO el convention genérico `values-<env>.yaml` de Helm upstream). Debe existir uno por cada entorno soportado.

Falta algún entorno → **MEDIUM**.

### Check 7.6 — `@ConfigurationPropertiesScan` en Application.java

```bash
grep "@ConfigurationPropertiesScan" <PATH>/src/main/java/com/pichincha/sp/Application.java
```

0 matches → **HIGH** (los beans `@ConfigurationProperties` no se registran sin esto).

### Check 7.7 — Todas las variables legacy en application.yml [MANDATORIO]

**Regla:** TODA variable de configuración identificada en el ANALYSIS (Section 15) — tanto del servicio como de sus UMPs/dependencias (`.properties`, `Constantes.java`, `Propiedad.get()`, `Environment.cache.*`, `GestionarRecursoConfigurable`, `CatalogoAplicaciones.properties`) — DEBE tener su entrada en `application.yml`.

**Procedimiento:**
1. Leer la Section 15 del `ANALISIS_<ServiceName>.md`
2. Para cada variable listada, verificar que existe en `application.yml` (como literal, como `${CCC_*}`, o como comentario `# valor no disponible`)
3. Para cada `${CCC_*}` en `application.yml`, verificar que tiene entrada en los 3 helms

```bash
# Listar todas las ${CCC_*} del application.yml
grep -oP '\$\{CCC_\w+' <PATH>/src/main/resources/application.yml | sort -u

# Para cada una, verificar presencia en los 3 helms
for var in $(grep -oP 'CCC_\w+' <PATH>/src/main/resources/application.yml | sort -u); do
  for env in dev test prod; do
    grep -q "$var" <PATH>/helm/$env.yml || echo "MISSING in $env.yml: $var"
  done
done
```

**Veredictos:**
- Variable del ANALYSIS ausente en `application.yml` → **HIGH**
- `${CCC_*}` en `application.yml` sin entrada en algún helm → **HIGH**
- Variable en helm que no se usa en `application.yml` (huérfana) → **MEDIUM**
- Valor inventado (no extraído del código legacy ni de archivos config) → **HIGH**

### Check 7.8 — Sin valores inventados en application.yml

```bash
# Buscar valores sospechosos que podrían ser inventados
# (números redondos genéricos que no vienen del legacy)
grep -nE ":\s+(100|1000|5000|10000|30000|60000)\s*$" <PATH>/src/main/resources/application.yml
```

Cualquier valor numérico debe ser trazable al legacy (Section 15 del ANALYSIS) o ser un default documentado del framework. Si el ANALYSIS dice `<pendiente_validar>` para una variable y el `application.yml` tiene un valor concreto → **HIGH** (valor inventado). Si el ANALYSIS tiene el valor real y el `application.yml` lo refleja → **PASS**.

---

## BLOQUE 8 — Versiones y dependencias

**Origen:** [PDF-OFICIAL] (Snyk) + [MCP] (versiones)

### Check 8.1 — Versiones actualizadas

```bash
grep -E "springframework.boot.*version|jackson-core:|logstash-logback-encoder|lib-bnc-api-client|peer-review" <PATH>/build.gradle
```

Baseline esperado (a 2026-04):
- Spring Boot: `3.5.13`
- jackson-core / jackson-dataformat-xml: `2.21.2`
- logstash-logback-encoder: `9.0` (solo si aplica)
- lib-bnc-api-client: **verificar en Confluence MCP antes de auditar** — si el valor local es más viejo que el publicado, **MEDIUM**
- Peer Review plugin: `1.1.0`

Cualquier versión menor al baseline → **MEDIUM**.

### Check 8.2 — Snyk sin vulnerabilidades HIGH [PDF-OFICIAL]

Ejecutar (si está disponible):
```bash
cd <PATH> && snyk test --severity-threshold=high
```

Cualquier HIGH → **HIGH** bloqueante. MEDIUM/LOW son informativos.

### Check 8.3 — Peer Review score ≥ 7

```bash
find <PATH>/build/reports -name "peer-review*" -type f
# Leer el reporte y extraer score
```

Score < 7 → **HIGH**. Score 7-8 → MEDIUM (aceptable pero mejorar). Score ≥ 9 → PASS.

### Check 8.4 — Lombok minimal

```bash
grep -rE "@Data|@AllArgsConstructor|@NoArgsConstructor|@Builder|@ToString" <PATH>/src/main/java/
```

Lombok permitido: `@Getter`, `@RequiredArgsConstructor`, `@Setter` (solo en `@ConfigurationProperties`). `@Slf4j` **PROHIBIDO** (genera `org.slf4j.Logger`; usar `ServiceLogHelper` del banco — ver Check 2.5).

Uso de `@Data`/`@AllArgsConstructor`/`@NoArgsConstructor` → **MEDIUM**. Usar records de dominio en vez de clases con Lombok.

### Check 8.5 — `spring-boot-starter-webflux` presente en servicios BUS [MCP gap]

Compensación obligatoria del **gap conocido del MCP fabrics** (§1.0.3 del prompt SOAP): el MCP no incluye `webflux` en el scaffold aunque se le pase `webFramework: webflux`. Como `lib-bnc-api-client` usa `WebClient` internamente, sin este starter las llamadas a BANCS no funcionan.

```bash
# BUS mode debe tener webflux starter
grep -c "spring-boot-starter-webflux" <PATH>/build.gradle
# NO debe tener spring-boot-starter-web (el de MVC)
grep -c "spring-boot-starter-web'\|spring-boot-starter-web\"" <PATH>/build.gradle
```

**Reglas (para proyectos con `tecnologia: bus` en `migration-context.json`):**
- webflux=0 → **HIGH**. El MCP no lo incluyó y no se agregó post-scaffold. `lib-bnc-api-client` no va a funcionar.
- webflux=1 y web=0 → ✅ PASS.
- webflux=1 y web=1 → **MEDIUM**. Ambos starters presentes; Spring MVC va a tomar prioridad sobre WebFlux. Solo dejar uno (webflux).

**Validación adicional — container real en runtime:**
```bash
# Buscar en logs de tests qué factory levanta Spring
grep -r "UndertowServletWebServerFactory\|UndertowReactiveWebServerFactory" \
    <PATH>/build/test-results/ 2>/dev/null | head -1
```

Si aparece `UndertowServletWebServerFactory` en un proyecto SOAP + BUS → **esperado** (Spring WS requiere servlet); el `webflux` starter se usa solo para el `WebClient` outbound. Este híbrido es el **patrón BUS oficial** del banco.

**Referencia:** bug del MCP observado en wsclientes0007 scaffold inicial (commit `3fa03db` sin webflux) y corregido manualmente en `e1bff14`.

### Check 8.6 — `jaxws-rt` presente en servicios SOAP [MCP gap]

```bash
grep -E "jaxws-rt:" <PATH>/build.gradle
```

0 matches → **HIGH**. El MCP no lo incluye; agregar con las exclusiones de `jaxb-core`/`jaxb-impl` (ver §1.0.3 del prompt SOAP).

---

## BLOQUE 9 — Tests y calidad

**Origen:** [PDF-OFICIAL] (Cobertura 75%, SonarLint, Sonar Test)

### Check 9.1 — JaCoCo ≥ 75% [PDF-OFICIAL]

```bash
cat <PATH>/build/reports/jacoco/test/jacocoTestReport.xml | \
  grep -oE 'counter type="INSTRUCTION" missed="[0-9]+" covered="[0-9]+"' | head -1
# Calcular covered / (covered + missed) * 100
```

- < 75% → **HIGH** (bloqueante del banco)
- 75-80% → MEDIUM
- ≥ 80% → PASS

### Check 9.2 — Build verde

```bash
cd <PATH> && ./gradlew build --no-daemon
```

BUILD FAILED → **HIGH**. Bloqueante.

### Check 9.3 — Tests unitarios presentes por capa

```bash
find <PATH>/src/test/java -name "*Test.java" | wc -l
```

Esperado mínimo:
- 1 test por service de application
- 1 test por adapter de infrastructure
- 1 test de Controller (integration)
- Tests de strategies (si aplica — ver Bloque 11)

< 5 archivos de test → **HIGH**. 5-10 → MEDIUM.

### Check 9.4 — @Nested con @SuppressWarnings("java:S2187")

```bash
grep -rlE "@Nested" <PATH>/src/test/java | while read f; do
  # Si el archivo tiene @Nested pero no @SuppressWarnings("java:S2187")
  grep -L "@SuppressWarnings(\"java:S2187\")" "$f"
done
```

Archivos listados → **LOW** (regla Sonar, no bloqueante).

### Check 9.5 — SonarLint local sin issues BLOCKER/CRITICAL [PDF-OFICIAL]

```bash
# Si hay reporte de SonarLint
find <PATH> -name "sonar-*.xml" -o -name ".sonarlint" | head -5
```

Ejecución manual: dev corre SonarLint en IDE. No se puede automatizar desde CLI sin Sonar Server. **INFORMATIVO**.

---

## BLOQUE 10 — SOAP specifics (solo si `projectType = SOAP`)

**Origen:** [COMMIT-bf913b9] + análisis 0015

Si `projectType != SOAP`, saltar este bloque.

### Check 10.1 — Tests de integración usan PascalCase en XML

```bash
# Detecta elementos XML con nombre en minúscula (ej: <consultarAlgo01>) excluyendo
# prefijos namespace legítimos (<ns:..., <ns1:..., <ns2:..., <soap:..., <xsi:...).
grep -rnE "<[a-z]+[A-Z][a-zA-Z]*[0-9]{2}\b" <PATH>/src/test/java/ \
  | grep -v -E "<[a-z]+[0-9]*:|local-name=" \
  | grep -iE "consultar|crear|eliminar|actualizar|modificar"
```

XML requests/responses con elemento raíz en minúscula → **HIGH**.

**Falso positivo a filtrar:** `<ns:ConsultarX01>` es **válido** (el PascalCase está después del prefijo). El grep con `-v "<[a-z]+[0-9]*:"` filtra cualquier elemento con prefijo namespace.

### Check 10.2 — `@PayloadRoot.localPart` = PascalCase (ya en Bloque 3.2)

Cross-reference. No re-auditar.

### Check 10.3 — `BancsClientHelper` abstract + 1 subclase por TX

```bash
grep -l "abstract class BancsClientHelper" <PATH>/src/main/java/com/pichincha/sp/infrastructure/output/adapter/bancs/helper/
ls <PATH>/src/main/java/com/pichincha/sp/infrastructure/output/adapter/bancs/helper/Tx*BancsClientHelper.java
```

- 0 subclases `Tx{CODE}BancsClientHelper` → **HIGH** (patrón no aplicado)
- Helper concreto `@Component` sin ser subclase → **HIGH**

### Check 10.4 — `WebServiceConfig` + `NamespacePrefixInterceptor`

```bash
find <PATH>/src/main/java -name "WebServiceConfig.java" -o -name "NamespacePrefixInterceptor.java"
```

Faltante → **HIGH**.

---

## BLOQUE 11 — REST strategies (solo si aplica)

**Origen:** wsclientes0024 (gold standard REST, referencia estable)

Si `projectType != REST`, saltar.

### Check 11.1 — ¿El servicio tiene failover Bancs↔OCP?

Decidir si aplica por presencia de:
```bash
ls <PATH>/src/main/java/com/pichincha/sp/infrastructure/output/adapter/stratio/ 2>/dev/null
ls <PATH>/src/main/java/com/pichincha/sp/infrastructure/output/adapter/strategy/ 2>/dev/null
```

Si NO hay `stratio/` ni `strategy/` → servicio REST mono-fuente, **saltar Bloque 11**.

### Check 11.2 — 4 strategies presentes

```bash
ls <PATH>/src/main/java/com/pichincha/sp/infrastructure/output/adapter/strategy/
```

Debe listar: `BancsOnlyStrategy.java`, `BancsWithOcpFailoverStrategy.java`, `OcpOnlyStrategy.java`, `OcpWithBancsFailoverStrategy.java`.

Menos de 4 → **HIGH**.

### Check 11.3 — `CustomerQueryStrategyPort` como interfaz con `withDataSource()` estático

```bash
grep -A3 "interface CustomerQueryStrategyPort" <PATH>/src/main/java/com/pichincha/sp/application/*/port/output/CustomerQueryStrategyPort.java
```

Debe ser `public interface` con método `static Customer withDataSource(...)`. Si no → **MEDIUM**.

### Check 11.4 — `CustomerStrategyConfig` bean factory

```bash
grep -l "CustomerStrategyConfig" <PATH>/src/main/java/com/pichincha/sp/infrastructure/config/
```

Faltante → **HIGH**.

### Check 11.5 — `application.yml` tiene `customer.datasource` y `customer.failover.enabled`

```bash
grep -E "^  datasource:|^    enabled:" <PATH>/src/main/resources/application.yml
```

Faltante → **HIGH**.

### Check 11.6 — Tests de cada strategy

```bash
ls <PATH>/src/test/java/com/pichincha/sp/infrastructure/output/adapter/strategy/
```

4 archivos `*StrategyTest.java`. Menos → **MEDIUM**.

---

## BLOQUE 12 — REST specifics (solo si `projectType = REST`)

**Origen:** wsclientes0024 (gold standard REST) + prompt `REST/02-REST-migrar-servicio.md`

Si `projectType != REST`, saltar este bloque.

### Check 12.1 — `ErrorResolverHandler` existe e implementa `ErrorWebExceptionHandler`

```bash
grep -rl "implements ErrorWebExceptionHandler" <PATH>/src/main/java/
```

Faltante → **HIGH**. Sin esto, errores inesperados devuelven JSON Spring default en vez de SOAP Fault XML.

### Check 12.2 — Error Resolver chain completa (sealed hierarchy)

```bash
# Debe existir ErrorResolver (abstract sealed), y los 3 resolvers concretos
grep -rl "sealed class ErrorResolver\|abstract sealed class ErrorResolver" <PATH>/src/main/java/
grep -rl "final class GlobalErrorExceptionResolver" <PATH>/src/main/java/
grep -rl "final class ResponseStatusExceptionResolver" <PATH>/src/main/java/
grep -rl "final class UnexpectedErrorResolver" <PATH>/src/main/java/
```

Menos de 4 archivos → **HIGH**.

### Check 12.3 — SoapFault DTOs existen

```bash
find <PATH>/src/main/java -name "SoapFaultDto.java" -o -name "SoapFaultBodyDto.java" -o -name "SoapFaultEnvelopeDto.java"
```

Menos de 3 archivos → **HIGH**. El `ErrorResolverHandler` necesita estos DTOs para serializar SOAP Faults.

### Check 12.4 — `package-info.java` con `@XmlSchema` para prefijos NS1/NS2

```bash
find <PATH>/src/main/java -path "*/adapter/rest/dto/package-info.java"
grep "@XmlSchema" <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/rest/dto/package-info.java 2>/dev/null
```

Faltante → **MEDIUM**. Sin `@XmlSchema`, JAXB genera prefijos `ns2:`/`ns3:` que rompen clientes legacy IIB.

### Check 12.5 — `ReactiveContextWebConfig` (WebFilter)

```bash
grep -rl "ReactiveContextWebConfig" <PATH>/src/main/java/
grep -rl "implements WebFilter" <PATH>/src/main/java/com/pichincha/sp/infrastructure/config/
```

Faltante → **MEDIUM**. Sin esto, headers `x-guid`/`x-app` no se propagan downstream en cadenas reactivas.

### Check 12.6 — NO existe `BancsClientHelper` en proyecto REST

```bash
find <PATH>/src/main/java -name "BancsClientHelper.java" -o -name "*BancsClientHelper.java"
```

Si existe → **HIGH**. En REST se usa adapter directo con `@BancsService("ws-txNNNNNN")`, no BancsClientHelper.

### Check 12.7 — NO existe `WebServiceConfig` ni `NamespacePrefixInterceptor` en proyecto REST

```bash
find <PATH>/src/main/java -name "WebServiceConfig.java" -o -name "NamespacePrefixInterceptor.java"
```

Si existe → **HIGH**. Estos son artefactos SOAP (Spring WS) que no aplican a REST (WebFlux).

### Check 12.8 — SOAP Envelope DTOs existen (REST los necesita manualmente)

```bash
find <PATH>/src/main/java -name "SoapEnvelopeRequestDto.java" -o -name "SoapEnvelopeResponseDto.java" -o -name "SoapBodyRequestDto.java" -o -name "SoapBodyResponseDto.java"
```

Menos de 4 archivos → **HIGH**. En REST, Spring no maneja envelopes SOAP automáticamente — se requieren DTOs manuales con JAXB annotations.

### Check 12.9 — Controller es `@RestController` (no `@Endpoint`)

```bash
grep -rn "@RestController" <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/rest/impl/
grep -rn "@Endpoint" <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/
```

Si hay `@Endpoint` en REST → **HIGH**. Si no hay `@RestController` → **HIGH**.

### Check 12.10 — Adapter BANCS usa `@BancsService` directamente

```bash
grep -rn "@BancsService" <PATH>/src/main/java/com/pichincha/sp/infrastructure/output/adapter/bancs/
```

0 matches → **HIGH**. El adapter BANCS debe inyectar `BancsClient` con `@BancsService("ws-txNNNNNN")`.

---

## BLOQUE 13 — Persistence layer (solo si el proyecto tiene JPA)

Aplica únicamente cuando `build.gradle` incluye `spring-boot-starter-data-jpa` (tipicamente proyectos con `DB_USAGE: YES` en el ANALISIS, independiente de si la fuente legacy era IIB o WAS). Si no hay JPA starter, saltar todo el bloque.

Nota sobre la matriz: la elección REST vs SOAP se decide por cantidad de operaciones del WSDL, no por presencia de BD. Este bloque audita los detalles de la capa de persistencia **dentro** del prompt que se haya usado (usualmente SOAP+MVC, que es donde JPA vive natural; si aparece en REST+WebFlux hay que chequear el flag `ATTENTION_NEEDED_REST_WITH_DB`).

### Check 13.1 — JPA + WebFlux NO conviven

```bash
# Si hay starter-data-jpa, NO debe haber starter-webflux
grep -E "spring-boot-starter-(webflux|data-jpa)" <PATH>/build.gradle
```

Si aparecen ambos -> **HIGH**. Regla 4 violada (NEVER mix JPA with WebFlux). Acción: remover `spring-boot-starter-webflux` y migrar adapters reactivos a blocking.

### Check 13.2 — HikariCP configurado (no defaults)

```bash
grep -A20 "hikari:" <PATH>/src/main/resources/application.yml
```

Debe contener al menos: `maximum-pool-size`, `connection-timeout`, `idle-timeout`. Si solo está la sección vacía o falta -> **MEDIUM**. Acción: completar config Hikari con env vars `${CCC_DB_*}` (ver SOAP prompt Rule 4.1 para template).

### Check 13.3 — `pool-name` definido

```bash
grep "pool-name:" <PATH>/src/main/resources/application.yml
```

0 matches -> **LOW**. Acción: agregar `pool-name: ${spring.application.name}-pool` para que las métricas de Micrometer/Prometheus separen pools por servicio.

### Check 13.4 — `ddl-auto: validate` (NUNCA create / update / create-drop)

```bash
grep "ddl-auto:" <PATH>/src/main/resources/application.yml
```

Si es `create`, `create-drop`, o `update` en cualquier env -> **HIGH**. Acción: forzar `validate` (las migraciones de schema van por DBA / Liquibase / Flyway, NUNCA por Hibernate).

### Check 13.5 — `open-in-view: false`

```bash
grep "open-in-view:" <PATH>/src/main/resources/application.yml
```

Si es `true` o no está -> **MEDIUM** (Spring Boot default es `true`, hay que negarlo explícitamente). Acción: agregar `open-in-view: false` bajo `spring.jpa`.

### Check 13.6 — `@Transactional` en application/service, NO en adapters ni repositories

```bash
# Debe haber @Transactional en application/service/
grep -rn "@Transactional" <PATH>/src/main/java/com/pichincha/sp/application/service/

# NO debe haber en adapters ni repositories
grep -rn "@Transactional" <PATH>/src/main/java/com/pichincha/sp/infrastructure/output/adapter/persistence/
```

Si aparece en `infrastructure/output/adapter/persistence/` -> **MEDIUM**. Las transacciones se gestionan en el boundary del use-case (application service), no en el adapter ni en el repo.

### Check 13.7 — Output port de persistencia es framework-agnóstico

```bash
# El port no debe importar JPA/Spring Data
grep -E "import (jakarta\.persistence|org\.springframework\.data)" <PATH>/src/main/java/com/pichincha/sp/application/output/port/
```

Si hay match -> **HIGH**. El port vive en application/, no puede conocer JPA. Mover los imports al adapter.

### Check 13.8 — Entity y Domain separados

```bash
# Entities en infrastructure/persistence/entity/
ls <PATH>/src/main/java/com/pichincha/sp/infrastructure/persistence/entity/ 2>/dev/null

# Domain models NO deben tener @Entity
grep -rn "@Entity" <PATH>/src/main/java/com/pichincha/sp/domain/
```

`@Entity` en `domain/` -> **HIGH**. Domain debe ser puro (records / POJOs sin anotaciones de framework). El mapeo va en `infrastructure/persistence/mapper/`.

### Check 13.9 — Driver Oracle declarado y versionado

```bash
grep -E "ojdbc|oracle.*jdbc" <PATH>/build.gradle
```

0 matches -> **HIGH**. Acción: agregar `runtimeOnly 'com.oracle.database.jdbc:ojdbc11:<version>'` (versión según MCP fabrics / Confluence).

### Check 13.10 — Secrets de BD vía env vars (no hardcoded)

```bash
# url, user, password deben usar ${CCC_*}
grep -E "url:|username:|password:" <PATH>/src/main/resources/application.yml
```

Si alguno es literal (no `${...}`) -> **HIGH**. Los secrets NUNCA se commitean — se referencian como `${CCC_DB_URL}`, `${CCC_DB_USER}`, `${CCC_DB_PASSWORD}` y los provee el banco antes del deploy.

---

## BLOQUE 14 — SonarLint binding (Connected Mode)

Verifica que el proyecto migrado tiene el binding versionado a SonarCloud organizacional. Esto permite que cualquier dev del equipo arranque con feedback en tiempo real sin re-hacer el setup. Origen: PDF oficial `CDSRL-Guía de configuración SonarQube for ide (SonarLint)`.

### Check 14.1 — Existe `.sonarlint/connectedMode.json`

```bash
test -f <PATH>/.sonarlint/connectedMode.json && echo "EXISTS" || echo "MISSING"
```

`MISSING` -> **HIGH**. Acción: bindar el proyecto en VS Code/IntelliJ con SonarQube for IDE → Share configuration. Ver guía en `prompts/configuracion-claude-code/sonarlint/README.md`.

### Check 14.2 — `sonarCloudOrganization` = `bancopichinchaec`

```bash
grep -E '"sonarCloudOrganization":\s*"bancopichinchaec"' <PATH>/.sonarlint/connectedMode.json
```

0 matches -> **HIGH**. La organización debe ser literal `bancopichinchaec`. Si dice otra cosa, se está apuntando a un Sonar incorrecto.

### Check 14.3 — `projectKey` no es placeholder

```bash
grep -E '"projectKey":\s*"<PROJECT_KEY' <PATH>/.sonarlint/connectedMode.json
```

Si matchea (placeholder `<PROJECT_KEY_FROM_SONARCLOUD>` aún presente) -> **HIGH**. Acción: reemplazar por el `projectKey` real obtenido desde la URL del proyecto en SonarCloud (`https://sonarcloud.io/project/overview?id=<UUID>`).

### Check 14.4 — `.sonarlint/` está versionado, no ignorado

```bash
git -C <PATH> check-ignore .sonarlint/connectedMode.json
```

Si NO retorna vacío (es decir, está siendo ignorado) -> **MEDIUM**. Acción: revisar `.gitignore` raíz del proyecto y NO ignorar `.sonarlint/connectedMode.json` (sí ignorar `~/.sonarlint/` global, pero ese no vive en el repo).

### Check 14.5 — Sin tokens commiteados

```bash
grep -rEn "(token|password|secret).*=.*['\"][A-Za-z0-9_-]{20,}" <PATH>/.sonarlint/ 2>/dev/null
```

Si hay match -> **HIGH** (CRITICAL). Acción: rotar el token en SonarCloud inmediatamente y purgar del historial git. SonarLint guarda tokens cifrados en el secret store del IDE — NUNCA en el repo.

---

## BLOQUE 15 — Estructura de error oficial y librerías opcionales

**Origen:** [PDF-OFICIAL] `BPTPSRE-Estructura de error`, `BPTPSRE-Archivos de configuración`, `BPTPSRE-Servicios Configurables`, `BPTPSRE-Librería Audit Log Reactive`, `BPTPSRE-Librería Stratio Connector`.

Este bloque NO es redundante con el BLOQUE 5 (que cubre propagación de errores Bancs). Cubre la **forma** de los 8 campos del `<error>` según el PDF oficial + la presencia correcta de las 2 librerías internas opcionales.

### Check 15.1 — `error.recurso` respeta el formato `<SERVICIO>/<MÉTODO>`

```bash
# Buscar asignaciones / setters de recurso y ver que contengan "/"
grep -rnE "setRecurso\(|RECURSO\s*=" <PATH>/src/main/java/ \
  | grep -vE "//|\\*" \
  | head -20
```

**Veredicto:** para cada match, el string literal debe contener `/` y empezar con el `spring.application.name` del servicio (ej: `tnd-msa-sp-wsclientes0024/getDatosBasicos`). Si hay un `setRecurso(...)` con string sin `/`, o que no empieza con el artifactId → **HIGH**.

### Check 15.2 — `error.componente` sigue estructura oficial

El formato depende del tipo de legacy (IIB vs WAS). Consultar `ANALISIS_<ServiceName>.md` para saber cuál aplica.

**Casos IIB (mayoría):**

```bash
# Listar todos los valores literal que se asignan a componente
grep -rnE "setComponente\(\"[^\"]+\"|COMPONENTE\s*=\s*\"[^\"]+" <PATH>/src/main/java/
```

Cada valor debe matchear uno de:
- El `spring.application.name` (ej: `tnd-msa-sp-wsclientes0024`) — caso servicio interno / respuesta exitosa
- `ApiClient` (o nombre de librería exacto) — caso error propagado desde librería
- `TX\d{6}` (prefijo `TX` + 6 dígitos) — caso error de negocio desde ApiClient

Cualquier otro literal → **MEDIUM** (revisar caso a caso).

**Casos WAS (menos común):** valor debe matchear el nombre del método legacy, el `<NOMBRE_SERVICIO>`, o un valor literal de un `.properties` legacy. Si el origen no es rastreable → **MEDIUM**.

### Check 15.3 — `error.mensajeNegocio` NUNCA se setea con valor real

DataPower gestiona este campo en frente del microservicio. El servicio debe pasarlo como `null` o `""`.

```bash
# Buscar setters con string literal no vacío
grep -rnE "setMensajeNegocio\(\"[^\"]+\"\)" <PATH>/src/main/java/
```

0 matches esperado → ✅ **PASS**. Cualquier match con contenido real → **HIGH** (DataPower va a sobreescribir pero mejor no enviar ruido). Excepción aceptada: `setMensajeNegocio(null)` o `setMensajeNegocio("")` son válidos (pasan el pipe builder por simetría).

### Check 15.4 — `error.mensaje` sin prefijo `<NODO>-`

```bash
# Buscar mensajes con patrón "NODO-..." al principio
grep -rnE "setMensaje\(\"[A-Z][A-Z_0-9]+-" <PATH>/src/main/java/
```

Si hay match (ej: `setMensaje("IIB-algo...")`, `setMensaje("WS0024-...")`) → **MEDIUM**. Acción: strippear el prefijo, dejar solo la descripción. QA valida solo descripción, no nodo.

### Check 15.5 — `error.backend` no es `"00000"` literal

Ya cubierto por **Check 5.4**. Aquí solo referencia cruzada: no duplicar el check, pero si 5.4 falla este bloque lo hereda como pendiente.

### Check 15.6 — Audit Log Reactive: si está, está completa

```bash
# ¿La librería está declarada?
grep -E "mdw-dm-lib-audit-log-reactive" <PATH>/build.gradle
```

Si **no** está → saltar 15.6 (servicio no la usa — OK).

Si **sí** está:

```bash
# Controllers deben tener @LogAudit
grep -L "@LogAudit" <PATH>/src/main/java/com/pichincha/sp/infrastructure/input/adapter/rest/*Controller.java

# Services/adapters deben tener @LogAuditStep (no @LogAudit)
grep -rL "@LogAuditStep" <PATH>/src/main/java/com/pichincha/sp/application/service/
grep -rn "@LogAudit\b" <PATH>/src/main/java/com/pichincha/sp/application/service/

# Kafka credentials via env vars, no literales
grep -A2 "jaas:" <PATH>/src/main/resources/application.yml | grep -E "username=\"[^\$]"
```

**Veredicto:**
- Controller sin `@LogAudit` → **HIGH**
- Service/adapter con `@LogAudit` (debía ser `@LogAuditStep`) → **HIGH**
- Service/adapter sin `@LogAuditStep` → **MEDIUM**
- Kafka `username`/`password` literales en yml → **HIGH** (deben ser `${CCC_*}`)

### Check 15.7 — Stratio Connector: si está, está completa

```bash
grep -E "mdw-dm-lib-stratio-connector" <PATH>/build.gradle
```

Si **no** está → saltar 15.7.

Si **sí** está:

```bash
# Los adapters deben inyectar StratioQueryExecutor, no hand-rolled clients
grep -rn "StratioQueryExecutor" <PATH>/src/main/java/com/pichincha/sp/infrastructure/output/adapter/

# OAuth2 client-name debe ser unique (typically = spring.application.name)
grep -A1 "client-name:" <PATH>/src/main/resources/application.yml

# URL de Stratio y OAuth2 via env var
grep -E "stratio:\s*$|token-uri:|base-url:" <PATH>/src/main/resources/application.yml
```

**Veredicto:**
- Adapter Stratio sin inyectar `StratioQueryExecutor` (hand-rolled WebClient) → **HIGH**
- `client-name` hardcodeado distinto del artifactId del servicio → **MEDIUM**
- `stratio.base-url` o `token-uri` literales (no `${CCC_*}`) → **HIGH**
- Si `spring.data.redis.enabled=true` pero falta `host`/`port` → **HIGH**

### Check 15.8 — XMLs de configuración IIB: si aplica, inyectados como `@ConfigurationProperties`

Si el ANALISIS reportó uso de `GestionarRecursoXML` en legacy:

```bash
# Buscar @ConfigurationProperties que mapee el XML (no debe leer XML en runtime)
grep -rn "@ConfigurationProperties" <PATH>/src/main/java/com/pichincha/sp/infrastructure/config/
```

**Veredicto:**
- Si el servicio migrado sigue leyendo `.xml` de disco con `XmlMapper`/`DocumentBuilder` en runtime → **HIGH**. Acción: migrar el contenido del XML a `application.yml` o ConfigMap, binding vía `@ConfigurationProperties`.
- Si no hay trace de XML loading en el migrado → ✅ **PASS** (probablemente ya se migró a properties).

### Check 15.9 — Configurables IIB desde CSV local: si aplica, resueltos en `application.yml` / Helm

Si el ANALISIS reportó uso de `GestionarRecursoConfigurable` en legacy:

```bash
# Buscar placeholders pendientes o trazas del legacy en config
grep -rnE "TBD|pendiente_validar|Environment\\.cache|GestionarRecursoConfigurable" <PATH>/src/main/resources/application.yml <PATH>/helm/ 2>/dev/null
```

**Veredicto:**
- Cada campo usado del configurable debe trazarse al archivo local `prompts/ConfigurablesBusOmniTest_Transfor(ConfigurablesBusOmniTest_Transf).csv` o a una `${CCC_*}` con presencia en Helm si es secreto o depende del ambiente.
- Si queda `TBD` aunque el valor exista en el CSV local → **HIGH**.
- Si el servicio deja nombres genéricos o env vars sin mapear los campos detectados en `ANALISIS_<ServiceName>.md` → **MEDIUM**.
- Si todos los campos quedan resueltos con literal o `${CCC_*}` justificado → ✅ **PASS**.

---

## FORMATO DEL REPORTE

Generás el reporte en este formato, en el orden de los bloques. Para cada check: emoji de estado + descripción corta + detalles si FAIL.

```markdown
# Post-Migration Checklist Report
**Project:** <path>
**Type:** SOAP | REST
**Gold standard:** wsclientes0015 | wsclientes0024
**Date:** YYYY-MM-DD

---

## Summary
| Block | Pass | HIGH | MEDIUM | LOW |
|---|---|---|---|---|
| 1 Hexagonal | 4/5 | 1 | 0 | 0 |
| 2 Logging | ... | ... | ... | ... |
| ... | | | | |
| **TOTAL** | **X/Y** | **N** | **N** | **N** |

**Verdict:** READY_TO_MERGE | BLOCKED_BY_HIGH | READY_WITH_FOLLOW_UP

---

## Block 1 — Arquitectura hexagonal

### 1.1 Capas presentes — ✅ PASS
Encontradas: `application/`, `domain/`, `infrastructure/`

### 1.2 Domain sin imports framework — ✅ PASS
0 matches.

### 1.4 UN solo output port Bancs — ❌ HIGH
**Hallado:** 3 ports Bancs en `application/output/port/`:
  - `CustomerAddressBancsPort.java`
  - `GeoLocationBancsPort.java`
  - `CorrespondenceBancsPort.java`
**Acción:** consolidar en un único `CustomerAddressBancsPort` con los métodos de los otros dos.
**Ref:** [FB-JG]

...
```

**Orden de severidad en la salida:**
1. HIGH primero (bloqueante)
2. MEDIUM segundo (merge con ticket de follow-up)
3. LOW tercero (nice-to-have)
4. PASS agrupado al final como conteo (no listar uno por uno)

**Verdict:**
- `READY_TO_MERGE` si 0 HIGH
- `READY_WITH_FOLLOW_UP` si 0 HIGH y ≤ 3 MEDIUM
- `BLOCKED_BY_HIGH` si ≥ 1 HIGH

---

## CÓMO EJECUTARLO

Desde Claude Code, invocar el skill `/post-migracion` con el path al proyecto migrado (y opcionalmente el path al legacy original para habilitar el análisis cruzado del BLOQUE 0):

```
/post-migracion <MIGRATED_PATH> [<LEGACY_PATH>]
```

Ejemplos:

```
/post-migracion /ruta/absoluta/al/servicio-migrado
/post-migracion /ruta/absoluta/al/servicio-migrado /ruta/absoluta/al/legacy-original
```

También puede ejecutarse como instrucción libre apuntando a este archivo:

> "Aplicá el checklist post-migración de `prompts/post-migracion/03-checklist.md` sobre `<MIGRATED_PATH>`. Devolveme solo HIGH y MEDIUM, skip PASS."

El agente debe:
1. Detectar tipo de proyecto (Bloque 0)
2. Correr cada check del bloque relevante
3. Agrupar resultados por severidad
4. Emitir el reporte en el formato especificado
5. Cerrar con Verdict

NO auto-corrige. NO modifica archivos. Solo lee y reporta.

---

## Historial de decisiones (contexto de las reglas)

Este historial documenta las decisiones clave que motivan los checks de este archivo. Sirve para entender **por qué** cada regla existe. Los detalles del servicio-ancla `wsclientes0007` aparecen porque fue el primero en aplicar cada corrección antes de que se consolidaran como regla.

| Fecha | Servicio / commit | Decisión que originó una regla |
|---|---|---|
| 2026-04-14 | Checklist v1 — inicial | Primera versión del checklist. Base: gold standards `wsclientes0024` (REST) y `wsclientes0015` (SOAP). |
| 2026-04-14 | `bf913b9` (wsclientes0007) | **`postProcessWsdl.groovy` sin `decapitalize`** — revertida la lógica que decapitalizaba el root element del WSDL. La fuente de verdad es el XSD en PascalCase. → Check 3.4. |
| 2026-04-16 | `bbcc62a` (wsclientes0007) | **`error.tipo = FATAL`** para header-missing + Bancs + Exception genérica. Antes solo INFO/ERROR. También mensaje canónico `"Datos de la cabecera de la transaccion no se han asignado"` (error 9927 del catálogo `errores.xml`). → Checks 4.5 y 5.6. |
| 2026-04-16 | wsclientes0007 post-audit | **`error.backend` desde el catálogo oficial** `sqb-cfg-codigosBackend-config/codigosBackend.xml`, NO hardcodeado como `"00000"`. Los golds 0024/0013/0006 tienen el bug `"00000"` — no replicar. → Check 5.4. |
| 2026-04-17 | wsclientes0007 post-fix | **`log.info` reservado para eventos de contrato; diagnóstico a `log.debug`.** Origen: feedback del equipo [FB-JA]. → Checks 2.6 y 2.7. |
| 2026-04-17 | wsclientes0007 post-fix | **Patrones del `HeaderRequestValidator` externalizados** a `HeaderValidationProperties` (`@ConfigurationProperties`, ConfigMap de OpenShift). Validator convertido en `@Component` inyectable, no `final class` estática. Origen: feedback del equipo [FB-JA]. → Check 4.6. |
| 2026-04-18 | Matriz oficial formalizada | **1 op → REST + WebFlux, 2+ ops → SOAP + Spring MVC** (sin excepciones, igual para IIB / WAS / ORQ). La presencia de BD se trata como tecnología agregada dentro del prompt elegido, no como criterio para saltar a otro. wsclientes0007 queda como caso mal-clasificado histórico. → BLOQUE 0. |
| 2026-04-20 | BPTPSRE PDFs incorporados | **Estructura de error oficial** con 8 campos (`mensajeNegocio` lo gestiona DataPower — NUNCA el servicio). **Patrones IIB** de config: `GestionarRecursoXML` (archivos XML) y `GestionarRecursoConfigurable` (cache), usando `ConfigurablesBusOmniTest_Transfor(ConfigurablesBusOmniTest_Transf).csv` como fuente operativa para poblar `application.yml` / Helm cuando haya configurables. **Patrones WAS** de config: `.properties` en `/apps/proy/OMNICANALIDAD_SERVICIOS/conf/` + clases `Propiedad.java`, `ErrorTipo.java`, `ServicioExcepcion`. **Librerías WebFlux opcionales**: `mdw-dm-lib-audit-log-reactive` (`@LogAudit`/`@LogAuditStep`) y `mdw-dm-lib-stratio-connector` (`StratioQueryExecutor`). → BLOQUE 15. |

**Servicios-referencia citados en el checklist (`wsclientes0007/0013/0015/0024`):** son proyectos reales del banco usados como fuente de patrones o como ejemplos de anti-patrones. No se tocan desde este repo — son referencias de solo lectura. Los huecos conocidos de cada uno (`0024/0013/0006` con `"00000"` hardcodeado; `0015` con 3 ports Bancs y `log.info` excesivo; etc.) están documentados inline en cada Check correspondiente.
