---
name: bank-official-rules
kind: context
priority: 1
summary: Reglas oficiales del banco - las 9 validaciones de validate_hexagonal.py deben pasar todas
---

# Reglas oficiales del banco - gate de PR (`validate_hexagonal.py`)

**Fuente**: script oficial que los reviewers corren en cada PR. Si alguna de estas 9 reglas falla, el PR se rechaza.

**MUST**: cumplir las 9. **NEVER**: dejar pasar una con placeholder, default o anotacion faltante.

El conocimiento de como resolver cada una vive aqui. No se copia de un servicio de referencia: se aplica la regla.

---

## Regla 1 - Capas hexagonales puras

**MUST**: proyecto tiene SOLO 3 dirs bajo `src/main/java/com/pichincha/sp/`:
- `application/`
- `domain/`
- `infrastructure/`

**NEVER**: agregar `service/`, `util/`, `helper/`, `config/`, `exception/` como directorios hermanos de las 3 capas. Si son utiles, van **dentro** de la capa correspondiente (`infrastructure/util/`, `application/service/`, etc).

```
src/main/java/com/pichincha/sp/
├── application/              ✔ OK
├── domain/                   ✔ OK
├── infrastructure/           ✔ OK
└── util/                     ✘ NO - ilegal sibling
```

---

## Regla 2 - Matriz MCP oficial (5 parámetros + 3 reglas de override)

**Fuente única**: [`bank-mcp-matrix.md`](bank-mcp-matrix.md) — espejo del PDF
`BPTPSRE-Modos de uso`. Esta regla **no redefine** la matriz; la **aplica**.

**Resumen operativo** (detalle, tabla de 8 casos y explicación en el canonical):

| # | Trigger | Framework generado |
|---|---|---|
| **1** | `invocaBancs: true` | `webflux + rest` (override total) |
| **2** | `deploymentType: orquestador` + `invocaBancs: false` | `webflux + rest` + `lib-event-logs` |
| **3** | `projectType: soap` + `microservicio` + `invocaBancs: false` | `mvc + soap` + `spring-web-service` |

**MUST**: antes de migrar, resolver la regla aplicable leyendo el canonical.
**NEVER**: mezclar starters — `spring-boot-starter-webflux` **y**
`spring-boot-starter-web` en el mismo `build.gradle` = proyecto inválido.

```gradle
// Regla 1/2: SOLO webflux
implementation 'org.springframework.boot:spring-boot-starter-webflux'

// Regla 3 (SOAP): MVC + spring-web-services (nunca webflux)
implementation 'org.springframework.boot:spring-boot-starter-web'
implementation 'org.springframework.boot:spring-boot-starter-web-services'

// WAS 1 op: SOLO web (MVC)
implementation 'org.springframework.boot:spring-boot-starter-web'
```

**Validación CLI (Block 0.2c)**: `run_block_0` compara `actualFramework` vs
`expectedFramework` calculado por `_expected_framework()` (espejo directo del
canonical). Discrepancia → **FAIL HIGH** con mensaje `"Regla N MCP: <detalle>"`.

---

## Regla 3 - `@BpTraceable` en controllers

**MUST**: cada metodo publico de un controller (clase con `@RestController` o `@Controller`) lleva `@BpTraceable`. Excluye controllers de test.

**NEVER**: dejar un `@PostMapping` o `@GetMapping` sin `@BpTraceable`.

```java
import com.pichincha.common.trace.BpTraceable;   // OBLIGATORIO

@RestController
@RequestMapping("/customer")
public class CustomerController {

  @PostMapping("/consultar")
  @BpTraceable                                    // ✔ OK
  public Mono<Response> consultar(...) { ... }

  @GetMapping("/health")
  // falta @BpTraceable                           // ✘ NO
  public String health() { ... }
}
```

---

## Regla 4 - `@BpLogger` en services

**MUST**: cada metodo publico de una clase `@Service` (o `@Service` + `@RequiredArgsConstructor`) lleva `@BpLogger`. Al menos un metodo con la anotacion satisface el check, pero la convencion del banco es anotarlos todos.

**NEVER**: olvidar la anotacion en metodos publicos de `@Service`. No es suficiente con `@BpTraceable` en el controller.

```java
import com.pichincha.common.trace.logger.annotation.BpLogger;   // OBLIGATORIO
import org.springframework.stereotype.Service;
import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class CustomerServiceImpl implements CustomerServicePort {

  private final CustomerQueryStrategyPort customerQueryStrategy;

  @Override
  @BpLogger                                      // ✔ OK
  public Mono<Customer> getCustomerByIdentification(
      CustomerRequest request,
      SoapRequestContext requestContext
  ) {
    return customerQueryStrategy.query(request, requestContext);
  }
}
```

Import EXACTO: `com.pichincha.common.trace.logger.annotation.BpLogger`. No confundir con `@BpTraceable` de controllers (son dos anotaciones distintas del mismo framework).

---

## Regla 5 - Sin navegacion cruzada entre capas

**MUST**:
- `domain/` NO importa `application.*` ni `infrastructure.*`
- `application/` NO importa `infrastructure.*`
- `infrastructure/` PUEDE importar `domain.*` y `application.*` (hacia adentro siempre OK)

**NEVER**: un `import com.pichincha.sp.infrastructure.adapter.CustomerBancsAdapter` dentro de `application/`. Lo correcto es importar el `OutputPort` (interface) y que Spring inyecte el adapter concreto.

```java
// application/service/CustomerServiceImpl.java
import com.pichincha.sp.application.output.port.CustomerQueryStrategyPort; // ✔ OK (misma capa)
import com.pichincha.sp.domain.customer.Customer;                          // ✔ OK (capa interior)
import com.pichincha.sp.infrastructure.adapter.CustomerBancsAdapter;       // ✘ NO
```

---

## Regla 6 - Service Purity (CERO metodos privados en @Service)

**v0.23.6 — fortalecida desde commit 56d2771 del PromptCapaMedia:**

**MUST**: clases `@Service` contienen **UNICAMENTE** los metodos `@Override`
de la interfaz del input port. **CERO metodos privados**. El service es un
**orquestador puro** que delega a output ports y a utilities externas.

### Lo que DEBE estar en el service

- `@Override` de los metodos del input port.
- Dependencias inyectadas por constructor (`private final` fields).
- Class annotations (`@Service`, `@RequiredArgsConstructor`, `@BpLogger`).

### Lo que NO DEBE estar en el service (mover a `application/util/`)

- `private void validateRequest(...)` → `application/util/<Domain>ValidationHelper.java`
- `private <Type> normalize*(...)` → `application/util/<Domain>NormalizationHelper.java`
- `private <Type> format*(...)` → `application/util/<Domain>FormatHelper.java`
- `private <Type> build*(...)` → `application/util/<Domain>BuilderHelper.java`
- Cualquier `private` con logica de negocio → extraer a util dedicado.

### Patron correcto

```java
// ✔ Service puro — solo orquesta
@Service
@RequiredArgsConstructor
public class CustomerServiceImpl implements ConsultarClientePort {

    private final BancsCustomerPort bancsPort;

    @Override
    @BpLogger
    public Mono<Customer> getCustomerByIdentification(
            CustomerRequest request, SoapRequestContext ctx) {
        return Mono.fromCallable(() -> {
            CustomerValidationHelper.validateRequest(request);
            return CustomerNormalizationHelper.normalizeIdentification(request);
        }).flatMap(bancsPort::getCustomerInfo);
    }
}

// ✘ Service con helpers privados — NO
@Service
public class CustomerServiceImpl implements ConsultarClientePort {

    @Override
    public Mono<Customer> getCustomerByIdentification(...) { ... }

    private void validateRequest(CustomerRequest request) { ... }   // ✘
    private CustomerRequest normalizeIdentification(...) { ... }    // ✘
}
```

### Por que

Services que acumulan helpers privados se vuelven fat classes que violan SRP,
son dificiles de testear en aislacion, y generan merge conflicts cuando
varios devs tocan el mismo archivo. Extraer a `application/util/` hace cada
helper **independientemente testeable** y reusable entre services.

### Otros NEVER (se mantienen de la version original)

- metodo `static` dentro de un `@Service`
- `record` o `class` definidos **dentro** del `@Service`
- llamadas a `StringUtils.*` o import de `org.apache.commons.*`

### Patron concreto 1 — StringUtils.* → Java nativo

Java 11+ tiene `String.isBlank()` nativo. No necesita Apache Commons. **MUST**:

```java
// ✘ NO
import org.apache.commons.lang3.StringUtils;
if (StringUtils.isBlank(id)) { ... }
if (StringUtils.isNotBlank(email)) { ... }

// ✔ OK (Java nativo, sin import extra)
if (id == null || id.isBlank()) { ... }
if (email != null && !email.isBlank()) { ... }
```

**Mapeo exacto**:

| Apache Commons | Java nativo |
|---|---|
| `StringUtils.isBlank(x)` | `(x == null \|\| x.isBlank())` |
| `StringUtils.isEmpty(x)` | `(x == null \|\| x.isEmpty())` |
| `StringUtils.isNotBlank(x)` | `(x != null && !x.isBlank())` |
| `StringUtils.isNotEmpty(x)` | `(x != null && !x.isEmpty())` |

Tras el reemplazo, **MUST** remover `import org.apache.commons.lang3.StringUtils;` si queda sin uso. **NEVER** dejar el import como cosmetica si todo el codigo ya usa Java nativo.

### Patron concreto 2 — records internos → application/model/

DTOs intermedios del flujo del `@Service` **NO** viven dentro de la clase del Service. Viven en `application/model/<Name>.java` como record publico:

```java
// ✘ NO — record embebido en el Service
@Service
public class ContactService {
  public void run() { ... }
  private record FallbackData(String email, String phone) {}  // inner
}

// ✔ OK — record en archivo propio
// application/model/FallbackData.java
package com.pichincha.sp.application.model;
public record FallbackData(String email, String phone) {}

// application/service/ContactService.java
import com.pichincha.sp.application.model.FallbackData;

@Service
public class ContactService {
  public void run() { ... }  // el Service queda limpio
}
```

**Heuristica para elegir capa**:
- DTO intermedio del flujo → `application/model/`
- Entidad de negocio con invariantes → `domain/<concept>/`

**NEVER**: mezclar records de contrato externo (request/response SOAP o REST) con records internos. Esos van en `infrastructure/input/adapter/*/dto/`.

```java
// ✘ NO - utilidad en el Service
@Service
public class CustomerServiceImpl {
  private String normalizeIdentification(String id) {           // prefijo "normalize" → utilidad
    return id.trim().substring(0, 10);                          // manipulacion raw
  }
  private static boolean isBlank(String s) {                    // static en @Service
    return s == null || s.trim().isEmpty();
  }
  private record NormalizedPhone(String number, String prefix) { }  // record inner
}

// ✔ OK - extraer a util dedicado
// application/service/CustomerServiceImpl.java
@Service
public class CustomerServiceImpl {
  public Mono<Customer> consultar(CustomerRequest request) {
    CustomerRequest normalized = IdentificationNormalizer.normalize(request);
    return customerQueryStrategy.query(normalized);
  }
}

// infrastructure/util/IdentificationNormalizer.java
public final class IdentificationNormalizer {
  private IdentificationNormalizer() {}
  public static CustomerRequest normalize(CustomerRequest r) { ... }
}
```

**Patron**: el Service orquesta, el Util transforma. Si necesitas `${VAR}` del config, el Util recibe los valores primitivos por parametro, no inyecta `@ConfigurationProperties` directo.

---

## Regla 6.5 — Header estandar en `application.yml`

**MUST**: todo `application.yml` del microservicio incluye el bloque
`spring.header.*` con valores literales (NO env vars). Son metadata del
proyecto leidas por los interceptors de Optimus:

```yaml
spring:
  application:
    name: tnd-msa-sp-<service>        # literal, matchea metadata.name del catalog
  header:
    channel: digital                  # literal, siempre "digital"
    medium: web                       # literal, siempre "web"
```

**NEVER**: eliminar estos campos. El auto-fix de Regla 7 (`${VAR:default}` →
`${VAR}`) solo aplica a variables de entorno — NO debe tocar `channel: digital`
ni `medium: web` que son literales validos. Nuestro `fix_yml_remove_defaults`
tiene guard explicito para este caso (usa el patron `${VAR:default}`, no
matchea valores literales).

**Bloque completo de referencia** (patron canonico del banco):

```yaml
spring:
  application:
    name: <namespace>-msa-sp-<svc>     # ej. tnd-msa-sp-wsclientes0007
  header:
    channel: digital
    medium: web

TPL_LOG_INFO: INFO
TPL_LOG_DEBUG: DEBUG
```

---

## Regla 7 - `application.yml` sin valores por defecto

**MUST**: toda variable de entorno va como `${VAR_NAME}` sin default. La configuracion real vive en ConfigMap OpenShift + Azure DevOps Variable Groups, no en el yml.

**NEVER**: `${VAR:default}` con valor hardcoded. Rompe el principio de separar config de codigo y esconde bugs cuando el ConfigMap no setea la variable (toma el default silencioso en lugar de fallar).

**Excepcion**: prefijo `optimus.web.*` puede tener valores literales (default OK ahi).

```yaml
# ✔ OK
customer:
  datasource: ${CCC_CUSTOMER_DATASOURCE}
  failover:
    enabled: ${CCC_CUSTOMER_FAILOVER_ENABLED}

bancs:
  webclients:
    ws-tx060480:
      base-url: ${CCC_BANCS_BASE_URL}
      max-in-memory-size: ${CCC_BANCS_MAX_IN_MEMORY_SIZE}

# ✘ NO - tienen default hardcoded
customer:
  datasource: ${CCC_CUSTOMER_DATASOURCE:default-ds}
  timeout: ${CCC_BANCS_READ_TIMEOUT:30000}

# ✔ OK (excepcion: optimus.web)
optimus:
  web:
    filter:
      excluded-path-patterns:
        defaults: "/actuator"
    headers:
      enabled: true
```

**Convencion de naming de env vars**: `CCC_*` para variables del servicio (ConfigMap). `ARTIFACT_*` para secrets del build. Nunca `SPRING_*` salvo overrides legitimos de Spring.

---

## Regla 8 - `lib-bnc-api-client:1.1.0` obligatoria

**MUST**: el `build.gradle` DEBE declarar la libreria BANCS API client del banco en la **version estable** `1.1.0`:

```gradle
implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0'
```

**Ahora que la version estable `1.1.0` esta liberada** (Apr 2026), los
proyectos migrados van con `1.1.0` limpio. Antes estaba disponible solo
en variante pre-release (`1.1.0-alpha.20260409115137`), que tambien pasaba
el regex del validador oficial porque contenia el substring `1.1.0`. Esa
version queda **deprecada** para proyectos nuevos.

**NEVER**:
- omitirla (implementar BANCS client a mano desde cero)
- usar version `1.0.x` o menor
- mantener `1.1.0-alpha.*`, `1.1.0-SNAPSHOT`, `1.1.0.RELEASE`, `1.1.0-rc*`,
  `1.1.0-beta*` en proyectos migrados nuevos. La estable ya salio; ir a ella.
- usar version sin prefijo `1.1.0` (el check oficial busca substring match)

### Autofix

`capamedia validate-hexagonal auto-fix --rules 8` aplica dos pasos:

1. **Normaliza** cualquier variante pre-release de `1.1.0` (`-alpha.*`,
   `-SNAPSHOT`, `-rc*`, `-beta*`, `.RELEASE`, `.M*`) a `1.1.0` estable.
2. Si la libreria no esta declarada, la inserta en el bloque
   `dependencies { }` del `build.gradle` (o crea el bloque si no existe).

Esta libreria provee: `BancsClient`, `BancsClientHelper`, anotaciones `@BancsService`, mapeos de errores canonicos del banco. Sin ella el codigo se duplica.

```gradle
// ✔ OK
dependencies {
  implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0'
  // ... resto
}

// ✘ NO - version vieja
implementation 'com.pichincha.bnc:lib-bnc-api-client:1.0.5'

// ✘ NO - falta
// (dependency block sin la libreria)
```

---

## Regla 9 - `catalog-info.yaml` completo

**MUST**: archivo `catalog-info.yaml` en la raiz del proyecto con:

- `metadata.namespace: tnd-middleware` (literal)
- `metadata.name: tpl-middleware` (literal)
- `metadata.description`: texto real del servicio (NO `"comming soon"`)
- `metadata.annotations`:
  - `dev.azure.com/project-repo: <proyecto-azure>/<nombre-repo>` (matchea links[0])
  - `sonarcloud.io/project-key: <UUID>` (formato `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)
- `spec.owner`: email con sufijo `@pichincha.com`
- `spec.lifecycle: test` (literal)
- `spec.dependsOn`: lista que incluye cada `lib-bnc-*` usada en Gradle
- `spec.links[0].url`: URL Azure DevOps formato `https://dev.azure.com/BancoPichinchaEC/tpl-middleware/_git/<repo>`
- `spec.links[2].url`: URL Confluence formato `https://pichincha.atlassian.net/wiki/spaces/...`

**NEVER**: dejar placeholders literales `<project-name>`, `<owner>`, `<lifecycle>`, `<sonarcloud-project-key>`, `comming soon`. El archivo se llena al crear el servicio.

```yaml
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  namespace: tnd-middleware                           # ✔ literal obligatorio
  name: tpl-middleware                                # ✔ literal obligatorio
  description: Consulta de contacto transaccional BANCS   # ✔ real (no "comming soon")
  annotations:
    dev.azure.com/project-repo: tpl-middleware/<namespace>-msa-sp-<svc>    # ✔ matches links[0]
    sonarcloud.io/project-key: <uuid-de-sonarcloud>                         # ✔ UUID
  links:
    - url: https://dev.azure.com/BancoPichinchaEC/tpl-middleware/_git/<namespace>-msa-sp-<svc>
      title: Repositorio
    - url: https://app.swaggerhub.com/apis/BancoPichincha/customer-contact/1.0.0
      title: OpenAPI
    - url: https://pichincha.atlassian.net/wiki/spaces/CDSRL/pages/2808054060/Documentacion
      title: Documentacion tecnica
spec:
  type: service
  owner: jsoria@pichincha.com                         # ✔ @pichincha.com
  lifecycle: test                                      # ✔ literal
  dependsOn:
    - component:lib-bnc-api-client                     # ✔ por cada lib-bnc-* del gradle
    - component:lib-trace-logger
```

---

## Regla 10.5 - ORQ llama al servicio MIGRADO, no al legacy

**MUST**: un orquestador (ORQ) invoca al servicio target en su version
**migrada** (proyecto Java Spring Boot hexagonal en `tpl-middleware`), NO
al servicio legacy (`sqb-msa-<svc>` o `ws-<svc>-was`).

**NEVER**: buscar el proyecto target como "legacy" en el workspace del ORQ.
El unico legacy del workspace ORQ es el **del propio orquestador**.

### Como se identifica esto

- En el workspace del ORQ, `legacy/` contiene el codigo del orquestador
  legacy (ej. `sqb-msa-orqclientes0027`).
- Los servicios invocados (ej. `wsclientes0023`, `wsclientes0076`) se
  resuelven desde el catalogo de `tpl-middleware` en su version migrada:
  `<namespace>-msa-sp-<svc>`.
- Si el ORQ migrado tiene un `WebClient` apuntando a `sqb-msa-wsclientes*`
  o `ws-wsclientes*-was`, es **mal-clasificado** — debe apuntar al
  servicio migrado.

### Ejemplo del contrato correcto

```yaml
# application.yml del ORQ migrado
services:
  wsclientes0076:
    url: ${CCC_WSCLIENTES0076_URL}  # apunta al <ns>-msa-sp-wsclientes0076 desplegado
```

```java
// Adapter del ORQ que invoca al target
@Component
public class Wsclientes0076OutputAdapter implements ConsultarClienteOutputPort {
    private final WebClient webClient;  // configurado con la URL del servicio MIGRADO
    ...
}
```

### Blocker del check

- Si `capamedia check` detecta en un proyecto `source_kind=orq` una
  referencia a `sqb-msa-<target>` o `ws-<target>-was` como path/URL en
  configuracion, **FAIL HIGH** con hint de cambiar al endpoint del
  servicio migrado.

---

## Regla 9f - Preservar el `application.yml` del MCP scaffold (merge, no replace)

**Commits 898d25f + 104addb del PromptCapaMedia (2026-04-22/23)**.

**MUST**: el MCP Fabrics genera un `application.yml` con propiedades que la
infraestructura del banco espera (`spring.header.channel`, `spring.header.medium`,
`spring.application.name`, `optimus.*`, `web-filter.*`, etc). El agente migrador
DEBE **preservar TODAS las propiedades del scaffold**. Al migrar se **AGREGAN**
las propiedades especificas de la migracion (`bancs.webclients`, `error-codes`,
service config, `trace-logger`, etc) **junto a** las existentes.

### MANDATORIO (v0.23.9): `spring.header.channel` + `spring.header.medium`

Estas DOS propiedades **DEBEN** estar siempre presentes como **literales**
en el `application.yml` final, aplica para REST y SOAP por igual:

```yaml
spring:
  header:
    channel: digital    # MANDATORIO - literal, nunca ${CCC_*}
    medium: web         # MANDATORIO - literal, nunca ${CCC_*}
```

Motivo: la infraestructura del banco lee estas dos keys para el tracing y
routing global. Son literales fijos que no cambian por ambiente.

**NEVER**:
- Reemplazar el `application.yml` entero.
- Quitar propiedades del scaffold pensando que "no se usan".
- Borrar `spring.header.channel` o `spring.header.medium`.
- Convertirlas en `${CCC_*}` (son literales, no env vars).

**UNICA propiedad a REMOVER** del scaffold: `spring.main.lazy-initialization`.
Causa problemas con WebFlux (contexto reactivo) y con Spring WS (dispatcher
multi-operation). Se remueve con un comentario `# removido por incompatibilidad`.

```yaml
# Esta propiedad del scaffold MCP se remueve:
# spring:
#   main:
#     lazy-initialization: true    # ← removido por incompatibilidad WebFlux/SpringWS

# El resto del scaffold se PRESERVA:
spring:
  application:
    name: <namespace>-msa-sp-<svc>    # ← preservar del scaffold
  header:                             # ← preservar del scaffold
    channel: digital
    medium: web

# Y se AGREGAN las propiedades de la migracion:
error-messages:
  success-code: "0"
  fatal-code: "9999"
bancs:
  webclients:
    ...
```

---

## Regla 9g - Todos los configurables legacy en `application.yml`

**Commits a91bda8 + 104addb del PromptCapaMedia (2026-04-22/23)**.

**MUST**: TODA variable de configuracion identificada en el ANALYSIS
(Section 15 "Service Configuration") — del servicio Y de sus UMPs — DEBE
tener su entrada en `application.yml`. Incluye variables de:

- `.properties` files (servicio + UMPs)
- `Constantes.java` (`Propiedad.get(...)`)
- `Environment.cache.*`
- `GestionarRecursoConfigurable` (IIB)
- `GestionarRecursoXML` (IIB)
- `CatalogoAplicaciones.properties`

### Regla de commit (actualizada en v0.23.9)

- **Valores fijos conocidos del legacy** (ej. resource names, component names,
  lengths, prefixes, codigos de backend del catalogo): commit como **literal**
  directo en `application.yml`.

  ```yaml
  transaction-attributes:
    resource-01: "XYZ_RECURSO"            # literal
    component-01: "XYZ_COMPONENTE"        # literal
  error-messages:
    backend: "00633"                      # literal (del catalogo)
  ```

- **Secrets + env-dependent** (DB URLs, passwords, tokens, URLs que cambian
  por ambiente): usar `${CCC_*}` **SIN** defaults inline. Cada `${CCC_*}`
  DEBE tener entrada en los **3 helms** (`helm/dev.yml`, `helm/test.yml`,
  `helm/prod.yml`).

  ```yaml
  datasource:
    url: ${CCC_DATASOURCE_URL}            # sin default, viene de Helm
    username: ${CCC-ORACLE-OMNI-CATALOGA-USER}
  ```

- **NEVER inline defaults `${CCC_VAR:value}`**. TODO `${CCC_*}` obtiene su
  valor **exclusivamente desde Helm**. Sin excepciones — ni siquiera para
  codigos del catalogo oficial del banco.

  **Por que**: permite que el Helm sea la unica fuente de verdad. Inline
  defaults ocultan valores operativos y dificultan cambios sin redeploy.

  ```yaml
  # ✘ NO — inline default
  error-messages:
    backend: ${CCC_BANCS_ERROR_CODE:00633}

  # ✔ OK — si es constante del catalogo, literal
  error-messages:
    backend: "00633"

  # ✔ OK — si puede cambiar por ambiente, sin default (helm lo resuelve)
  error-messages:
    backend: ${CCC_BANCS_ERROR_CODE}
  ```

- **NEVER** inventar valores. Si no esta disponible en el legacy, usar
  `${CCC_*}` + comentario `# valor no disponible — obtener de <fuente>`.
- **NEVER** dejar una variable sin documentar. Si el ANALYSIS la lista,
  DEBE aparecer en `application.yml`.
- **Solo** declarar en Helm las `${CCC_*}` que realmente se referencian en
  `application.yml`. No variables huerfanas.

### Autofix ejecutable

La Regla 7 del banco (autofix `fix_yml_remove_defaults`) aplica exactamente
esto: remueve todo `${CCC_VAR:default}` dejando solo `${CCC_VAR}`. Se
dispara con `capamedia checklist` o `/doublecheck`.

**Unica excepcion del autofix**: valores literales como `channel: digital`
y `medium: web` NO tienen pattern `${VAR:default}`, no se tocan.

### Check ejecutable: Block 19 del checklist

El CLI valida esto en `run_block_19` de `checklist_rules.py`, cruzando el
`.capamedia/properties-report.yaml` (generado por `clone` o por
`_auto_generate_reports_from_local_legacy`) con las keys presentes en
`application.yml` del destino.

---

## Regla 9h - Helm values-dev SOAP requiere `pdb: minAvailable: 1`

**Commit 9b670da del PromptCapaMedia (2026-04-23)**.

**MUST**: para servicios **SOAP**, el archivo `helm/values-dev.yml` debe
tener el bloque `pdb` con `minAvailable: 1`:

```yaml
container:
  extraVolumeMounts:
    - name: init-volume
      mountPath: /opt/build/init.sh
      subPath: init.sh

pdb:
  minAvailable: 1    # ← MANDATORIO para SOAP dev

hpa:
  minReplicas: 1
  maxReplicas: 1
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: AverageValue
          averageValue: 100m
```

**NEVER**: omitir el `pdb:` block en `values-dev.yml` para SOAP. Es
requerido por la infra del banco para PodDisruptionBudget.

**NO aplica a REST WebFlux** (el scaffold del MCP ya lo incluye cuando
aplica).

### Nota operativa

Si el scaffold del MCP Fabrics no lo genera automaticamente, agregarlo
manualmente al `helm/values-dev.yml`. Es parte del checklist oficial del
banco (Block 16 — Helm & Kubernetes).

---

## Regla 9h.1 - Helm HPA `averageValue` oficial = `100m`

**MUST**: en `helm/dev.yml`, `helm/test.yml` y `helm/prod.yml`, todo target
CPU de HPA con `averageValue` debe ser exactamente `100m`:

```yaml
hpa:
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: AverageValue
          averageValue: 100m
```

**NEVER**: dejar `averageValue: 400m` generado por el scaffold/MCP. El
checklist oficial del CLI lo bloquea como HIGH en el Block 7 con el detalle:
`helm/<env>.yml - averageValue: '400m' -> debe ser '100m'`.

---

## Regla 9i - WAS + JPA/Hikari requiere `connection-test-query: SELECT 1`

**MUST**: si el origen legacy es **WAS** y el migrado tiene
`spring-boot-starter-data-jpa`, `application.yml` debe declarar:

```yaml
spring:
  datasource:
    hikari:
      connection-test-query: SELECT 1
```

Esta regla es exclusiva para WAS con BD/JPA. BUS/ORQ WebFlux sin JPA no deben
agregarla.

---

## Regla 11 - CSV `ConfigurablesBusOmniTest_Transfor` para IIB

**Commit b55a794 del PromptCapaMedia (2026-04-21)**.

**Contexto**: servicios IIB (BUS) que usan `GestionarRecursoConfigurable`
leen sus configurables de un CSV operativo del banco:

```
PromptCapaMedia/prompts/ConfigurablesBusOmniTest_Transfor(ConfigurablesBusOmniTest_Transf).csv
```

Tiene ~7879 filas con las configurables oficiales de produccion (CMRCTEATR,
CMRDATRFN, etc. mapeadas a valores por ambiente).

### Por que no esta embebido en el CLI

El CSV es **demasiado grande** (~500 KB, 7879 filas) para distribuir en el
paquete Python. Ademas se actualiza con regularidad desde operaciones.

### Como consumirlo

**Cuando el ANALYSIS detecta `GestionarRecursoConfigurable`**, el agente
migrador DEBE:

1. Abrir el CSV desde el repo local `PromptCapaMedia` (path arriba).
2. Buscar las rows cuyo campo `ConfigName` matchee las configurables
   usadas por el servicio legacy.
3. Mapear cada row a una entrada en `application.yml`:

```yaml
# Ejemplo: legacy usa Environment.cache.CMRCTEATR.REG_MAX
cache:
  CMRCTEATR:
    REG_MAX: "10"                     # valor del CSV (row CMRCTEATR.REG_MAX)
    CODIGO_VACIO: "0001"              # valor del CSV
    # ... demas campos del CSV para este ConfigName
```

4. **NUNCA** dejar como `TBD` si el CSV tiene el valor. **NUNCA** inventar
   si el CSV no tiene el row — documentar como pendiente del SRE.

### Cross-check con Block 19

El Block 19 del checklist (via `properties-report.yaml`) tambien cubre
configurables `.properties`. Los de `GestionarRecursoConfigurable` (CSV) son
un mecanismo paralelo; la regla es la misma: **todo configurable legacy
referenciado tiene su entrada en `application.yml`**.

---

## Regla 10 - Properties compartidas del banco

**MUST**: `generalservices.properties` y `catalogoaplicaciones.properties` son
**catalogo global del banco** — los valores son constantes y estan embebidos
en `bank-shared-properties.md`. El agente DEBE:

1. Buscar la clave en el catalogo antes de marcarla como blocker.
2. Si la clave esta en el catalogo → usar el **valor literal** en
   `application.yml` (NO placeholder, NO `${CCC_*}`).
3. Solo diferir a env var las claves que vienen del `<ump>.properties` o
   `<servicio>.properties` especifico (inputs del owner).

**NEVER**:
- Marcar `OMNI_COD_SERVICIO_OK`, `OMNI_MSJ_SERVICIO_OK`, `MIDDLEWARE_INTEGRACION_TECNICO_WAS`,
  `BANCS`, etc. como "env var faltante" en `MIGRATION_REPORT.md`.
- Usar placeholder para estos valores — son literales del catalogo.

Ver [bank-shared-properties.md](bank-shared-properties.md) para la tabla
completa.

---

## Automatizacion en el CLI

- `capamedia validate-hexagonal summary <path>` — corre las 9 reglas oficiales
- `capamedia check <path> --auto-fix` — corrige automaticamente las que son deterministas:
  - Regla 4 `@BpLogger`: agrega anotacion a metodos publicos de `@Service`
  - Regla 7 `${VAR:default}`: reemplaza `${VAR:default}` por `${VAR}` (preserva `optimus.web.*`)
  - Regla 8 `lib-bnc-api-client`: agrega la dependency si falta
  - Regla 9 `catalog-info.yaml`: genera esqueleto con `namespace`/`name`/`lifecycle` correctos + placeholders marcados para review manual (owner, URLs, UUID sonar)
- Reglas 1, 2, 3, 5: validadas en `capamedia check` (bloques 0 y 1)
- Regla 6: autofix parcial deterministico:
  - `fix_stringutils_to_native`: reemplaza `StringUtils.*` por Java nativo + remueve import
  - `fix_extract_inner_records_to_model`: mueve records privados/internos del `@Service` a `application/model/<Name>.java`
  - Lo que quede (metodos `static`, `normalize*`, etc.) queda como alerta HIGH con hint al AI via `core/self_correction.py`.
