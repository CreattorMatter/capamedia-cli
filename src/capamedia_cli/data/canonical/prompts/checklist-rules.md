---
name: checklist-rules
title: Reglas completas del checklist BPTPSRE (15 bloques)
description: Checklist oficial pass/fail con severidad HIGH/MEDIUM/LOW. Incluye BLOQUE 0 con dialogo cruzado legacy vs migrado.
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

Después de correr el prompt de migración (`02-migrar-servicio.md`) y antes de abrir PR. También sirve para auditar servicios que ya están en `develop` antes de pasar a `release`.

## INPUT

Dos argumentos (el segundo es opcional pero recomendado):

1. **`<MIGRATED_PATH>`** — path absoluto al **proyecto migrado** (ej: `C:\Dev\Banco Pichincha\CapaMedia\0007\destino`). OBLIGATORIO.
2. **`<LEGACY_PATH>`** — path absoluto al **servicio legacy original** (ej: `C:\Dev\Banco Pichincha\CapaMedia\0007\legacy\sqb-msa-wsclientes0007`). OPCIONAL pero recomendado: habilita el análisis cruzado del BLOQUE 0 (WSDL legacy vs migrado, conteo de operaciones, nombres, namespaces).

Si no se pasa el segundo argumento, el BLOQUE 0 degrada a "solo cuenta en el WSDL copiado al proyecto migrado" y los Checks 0.3 y 0.4 se saltan con severidad **MEDIUM** (no se pudo cruzar con la fuente).

## FUENTES DE LAS REGLAS

Cada bloque referencia su origen para que el lector sepa de dónde viene:

- **[PDF-OFICIAL]** — `prompts/documentacion/BPTPSRE-CheckList Desarrollo-140426-212740.pdf` (documento oficial del área)
- **[FB-JG]** — Feedback de Jean Pierre García (Slack, múltiples fechas)
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
- Hay `@Endpoint` → **SOAP** (gold standard: `tnd-msa-sp-wsclientes0015`)
- Hay `@RestController` y no `@Endpoint` → **REST** (gold standard: `tnd-msa-sp-wsclientes0024`, FROZEN 2026-04-14)
- Ambos o ninguno → **FAIL HIGH** (proyecto malformado)

### Check 0.2 — Conteo de operaciones: legacy ↔ migrado ↔ framework

**Principio del banco:** la matriz oficial es estricta por `<portType>` del WSDL legacy:

| Operaciones WSDL | Framework correcto | Prompt usado |
|---|---|---|
| **1** | Spring WebFlux + `@RestController` (Netty reactive, sin `.block()`) | REST |
| **2 o más** | Spring MVC + `@Endpoint` (Spring WS dispatching sobre MVC + Undertow) | SOAP |

Aplica igual para IIB, WAS y ORQ. BD presente es ortogonal (suma HikariCP+JPA o R2DBC según el caso, NO cambia la decisión REST/SOAP).

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

#### Paso 4 — Veredicto conversacional (diálogo explícito)

El reporte debe rendir este diálogo literal, con los valores reemplazados:

```
¿Cuántas operaciones tiene el WSDL? → $OPS_LEGACY
¿Qué framework corresponde según la matriz? → <REST si OPS=1 | SOAP si OPS>=2>
¿Qué framework se usó en la migración? → <projectType de Check 0.1>
¿Coincide lo usado con lo que la matriz pide? → <SÍ ✅ | NO ❌>
Veredicto final: <PASS | HIGH mal-clasificado | etc.>
```

#### Paso 5 — Reglas de severidad

- 1 op legacy + tipo REST → ✅ **PASS**. Diálogo: *"Es 1 op, va REST. ¿Está OK? Sí, está OK."*
- 2+ ops legacy + tipo SOAP → ✅ **PASS**. Diálogo: *"Son N ops, va SOAP. ¿Está OK? Sí, está OK."*
- 1 op legacy + tipo SOAP → **HIGH** (mal-clasificado). Diálogo: *"Es 1 op → debió ir REST + WebFlux. Se migró como SOAP → está mal-clasificado."*
- 2+ ops legacy + tipo REST → **HIGH** (mal-clasificado). Diálogo: *"Son N ops → REST+WebFlux no soporta dispatching multi-operation, necesita Spring WS sobre MVC."*
- 1 op + tipo REST + `DB_USAGE: YES` → ✅ **PASS con flag** `ATTENTION_NEEDED_REST_WITH_DB`. Diálogo: *"Es 1 op con BD → queda en REST. ¿Usaste R2DBC o blocking boundary? Confirmá el approach con el equipo."*

**Hallazgo documentado:** wsclientes0007 tiene 1 op y está migrado como SOAP (ver [memoria mis-classification](../../.claude/projects/C--Dev-Banco-Pichincha-CapaMedia/memory/reference_mcp_fabrics_gaps.md)). Es **caso mal-clasificado que NO se reclasifica ahora** por costo vs beneficio (ya está funcionando, pasa checklist, build verde). Los futuros servicios con 1 op deben usar el prompt REST (sin importar si tienen BD — la matriz es estricta por cantidad de operaciones).

**Guardar en el contexto del reporte:** `projectType`, `goldStandard`, `opsLegacy`, `opsMigrated`, `opsMatch`, `expectedFramework`, `actualFramework`, `frameworkMatch`.

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

**Referencia:** feedback Jonathan Arana / Alexis 2026-04-17 sobre wsclientes0007 (`log.info("Basic info retrieved for CIF: {}", ...)` bajado a debug en commit post-fix).

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

### Check 3.4 — `postProcessWsdl.groovy` sin decapitalize activo [COMMIT-bf913b9] (solo SOAP)

Solo detecta **invocaciones activas** de `decapitalize` (no la mera declaración de la función).

```bash
# Invocaciones activas (call-site): variable.decapitalize(...) o = decapitalize(...)
grep -nE "\.decapitalize\(|= decapitalize\(" <PATH>/gradle/postProcessWsdl.groovy
```

Cualquier match → **HIGH**. Revertido en commit `bf913b9` del 0007 (2026-04-14).

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

**Referencia:** wsclientes0007 post-fix 2026-04-16 (commit `bbcc62a` de Kevin Armas).

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

**Referencia:** feedback Jonathan Arana / Alexis 2026-04-17 sobre wsclientes0007; refactor aplicado en post-fix del mismo día.

---

## BLOQUE 5 — Error handling y propagación de errores Bancs

**Origen:** [FB-JG] (error propagation) + [FB-JG] (localPart casing ya en bloque 3)

### Check 5.1 — `BancsClientHelper.execute()` atrapa RuntimeException [FB-JG]

```bash
grep -A5 "public <T> T execute" <PATH>/src/main/java/com/pichincha/sp/infrastructure/output/adapter/bancs/helper/BancsClientHelper.java | grep -c "catch\s*(\s*RuntimeException"
```

0 matches → **HIGH**. Sin este catch, `WebClientResponseException` burbujea como RuntimeException y el Controller devuelve "999 Error interno" en vez del error real de Bancs.

**Patrón requerido:**
```java
try {
  response = doCall(txCode, ctx, body, responseType);
} catch (BancsOperationException e) {
  throw e;
} catch (RuntimeException e) {
  throw new BancsOperationException("999",
    e.getMessage() != null ? e.getMessage() : "Bancs integration exception",
    txCode);
}
```

**Referencia:** wsclientes0015 NO lo tiene (hueco del gold standard). wsclientes0007 lo cubrió post-feedback de Jean Pierre.

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

**Referencia:** wsclientes0024/0013/0006 (golds) todos tienen el bug `"00000"` — **no replicar**. wsclientes0007 lo corrigió post-auditoría 2026-04-16.

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

**Referencia:** wsclientes0007 post-fix 2026-04-16 (tipo FATAL para header-missing + Bancs + Exception genérica). Los golds 0024/0013/0006 NO aplican esta clasificación — **no replicar**.

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

**Origen:** wsclientes0024 (gold standard REST, FROZEN 2026-04-14)

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

---

## Changelog del checklist
- 2026-04-14: versión inicial
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

## EJEMPLO DE OUTPUT (preview sobre wsclientes0007)

Aplicado a `C:\Dev\Banco Pichincha\CapaMedia\0007\destino` a fecha 2026-04-14:

```markdown
# Post-Migration Checklist Report
**Project:** C:\Dev\Banco Pichincha\CapaMedia\0007\destino
**Type:** SOAP
**Gold standard:** wsclientes0015
**Date:** 2026-04-14

## Summary
| Block | Pass | HIGH | MEDIUM | LOW |
|---|---|---|---|---|
| 0 Pre-check | 2/2 | 0 | 0 | 0 |
| 1 Hexagonal | 5/5 | 0 | 0 | 0 |
| 2 Logging | 4/5 | 0 | 0 | 1 |
| 3 Naming | 3/4 | 1 | 0 | 0 |
| 4 Validaciones | 2/4 | 1 | 1 | 0 |
| 5 Error handling | 4/4 | 0 | 0 | 0 |
| 6 Mappers/tipos | 3/4 | 0 | 1 | 0 |
| 7 Config externa | 2/6 | 2 | 2 | 0 |
| 8 Versiones | 3/4 | 0 | 1 | 0 |
| 9 Tests | 3/5 | 0 | 2 | 0 |
| 10 SOAP specifics | 4/4 | 0 | 0 | 0 |
| 11 REST strategies | N/A | — | — | — |
| 12 REST specifics | N/A | — | — | — |
| **TOTAL** | **35/47** | **4** | **7** | **1** |

**Verdict:** BLOCKED_BY_HIGH

---

## Block 3 — Naming de métodos

### 3.1 Output ports usan `get*` — ❌ HIGH
**Hallado:** 2 métodos `query*` en puerto de lectura:
  - `BancsCustomerOutputPort.queryTransactionalContact`
  - `BancsCustomerOutputPort.queryCustomerInfoField`
**Acción:** renombrar a `getTransactionalContact` y `getCustomerInfoField` (+ usos en service y tests).
**Ref:** [FB-JG]

### 3.2 `@PayloadRoot.localPart` PascalCase — ✅ PASS
`"ConsultarContactoTransaccional01"` correcto.

### 3.3 Java method camelCase — ✅ PASS
### 3.4 postProcessWsdl sin decapitalize — ✅ PASS
Commit bf913b9 revirtió la lógica problemática.

---

## Block 4 — Validaciones

### 4.1 HeaderRequestValidator existe — ❌ HIGH
**Hallado:** 0 archivos en `infrastructure/input/adapter/soap/util/`.
**Acción:** crear `HeaderRequestValidator` siguiendo el patrón de `wsclientes0024/HeaderRequestValidator.java` adaptado al tipo JAXB `GenericHeaderIn` que llega vía Spring WS.
**Ref:** [FB-JG]

### 4.2 No está en domain/application — ✅ PASS
### 4.3 Controller invoca validator — ⚠ MEDIUM
**Nota:** consecuencia de 4.1. Se resolverá junto con 4.1.
### 4.4 Validaciones body en domain/app — ✅ PASS (informativo)

---

## Block 7 — Configuración externa

### 7.1 catalog-info.yaml completo — ❌ HIGH
**Hallado:** archivo con placeholders sin resolver:
  - `<owner>`, `<system>`, `<domain>`, `<lifecycle>`, `<dynatrace-entity-id>`, `<sonarcloud-project-key>`
  - Bloque `spec.definition:` presente (debe eliminarse)
  - Link de SwaggerHub presente (debe eliminarse)
**Acción:** reemplazar con template canónico (ver §7 del checklist).
**Ref:** [FB-JG]

### 7.2 azure-pipelines.yml — ✅ PASS
`CMDB_APPLICATION_ID: "Red Hat OpenShift Container Platform"` ✓
`KUBERNETES_NAMESPACE: tnd-middleware` ✓

### 7.3 application.yml usa ENV del Helm — ⚠ MEDIUM
**Hallado:** 2 URLs con valor por defecto hardcoded (aceptable), 0 secrets hardcoded.
**Acción:** verificar que todos los endpoints productivos usen `${VAR:default}`.

### 7.4 Validar Bancs/WebClient/CircuitBreaker — ⚠ MEDIUM
**Hallado:** `bancs:` ✓, `webclient:` ✓, `resilience4j:` falta sección explícita.

### 7.5 Helm por entorno — ❌ HIGH
**Hallado:** solo `values.yaml` genérico, faltan `values-dev.yaml`, `values-test.yaml`, `values-prod.yaml`.
**Ref:** [PDF-OFICIAL]

### 7.6 @ConfigurationPropertiesScan — ✅ PASS

---

## Block 2 — Logging

### 2.1 @BpTraceable en Controller — ✅ PASS
### 2.2 @BpLogger en todos los @Service — ✅ PASS (1/1 services, 1/1 métodos públicos cubiertos)
### 2.3 @BpLogger en Adapters — ✅ PASS (4 métodos en BancsCustomerAdapter)
### 2.4 Logs con GUID — ✅ PASS
### 2.5 Abuso de log.info — ℹ LOW
**Hallado:** `BancsCustomerAdapter.java` con 6 log.info. Revisar si son necesarios o parte del flujo normal.

---

## Block 6 — Mappers y tipos

### 6.1 Mappers dedicados — ✅ PASS
SOAP mapper + Bancs mapper + repository mapper presentes.
### 6.2 MapStruct — ✅ PASS
### 6.3 Sin new Record(>=8 args) inline — ⚠ MEDIUM
**Hallado:** `ConsultarContactoTransaccionalService.handleFallbackPath` y `.buildDirectResult` construyen `new CustomerContactResult(12 args)` inline.
**Acción:** agregar factory estático `CustomerContactResult.fromFallback(...)` / `.fromDirect(...)` en el record.
### 6.4 Sin Object/Map<String,Object> en puertos — ✅ PASS

---

## Block 9 — Tests y calidad

### 9.1 JaCoCo ≥ 75% — ✅ PASS (80.12%)
### 9.2 Build verde — ✅ PASS (61 tests OK)
### 9.3 Tests por capa — ⚠ MEDIUM
**Hallado:** 1 test de service, 1 de controller, 4 de adapter/helper = 6 archivos. Falta test específico de `PhoneNormalizationUtil`.
### 9.4 @Nested + S2187 — ✅ PASS (no usa @Nested)
### 9.5 SonarLint — ℹ INFO (ejecutar en IDE local)

---

## Changelog del checklist
- 2026-04-14: versión inicial
```

---

## CÓMO EJECUTARLO

Desde Claude Code:

```
/03-checklist-post-migracion.md path="C:/Dev/Banco Pichincha/CapaMedia/0007/destino"
```

O directamente en una instrucción:

> "Aplicá el checklist post-migración de `prompts/migracion/03-checklist-post-migracion.md` sobre `C:/Dev/Banco Pichincha/CapaMedia/0007/destino`. Devolveme solo HIGH y MEDIUM, skip PASS."

El agente debe:
1. Detectar tipo de proyecto (Bloque 0)
2. Correr cada check del bloque relevante
3. Agrupar resultados por severidad
4. Emitir el reporte en el formato especificado
5. Cerrar con Verdict

NO auto-corrige. NO modifica archivos. Solo lee y reporta.
