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

## Regla 2 - WSDL determina framework

**MUST**: si WSDL tiene **1 operacion** → REST + Spring WebFlux. Si tiene **2+ operaciones** → SOAP + Spring MVC.

**NEVER**: mezclar. Un proyecto con `@Endpoint` (SOAP) y `@RestController` (REST) falla. Un `build.gradle` con `spring-boot-starter-webflux` **y** `spring-boot-starter-web` falla.

```gradle
// WSDL con 1 op: SOLO webflux
implementation 'org.springframework.boot:spring-boot-starter-webflux'   // ✔ OK

// WSDL con 2+ ops: SOLO mvc
implementation 'org.springframework.boot:spring-boot-starter-web'       // ✔ OK

// NUNCA ambos
implementation 'org.springframework.boot:spring-boot-starter-web'       // ✘ NO
implementation 'org.springframework.boot:spring-boot-starter-webflux'   // ✘ NO
```

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

## Regla 6 - Services sin logica utilitaria

**MUST**: clases `@Service` contienen SOLO logica de orquestacion y decisiones de negocio. Metodos utilitarios (normalizar, parsear, formatear, limpiar, convertir) viven en clases dedicadas bajo `infrastructure/util/` o `domain/util/`.

**NEVER**:
- metodo `static` dentro de un `@Service`
- metodo que solo manipula `String`/numeros (`.trim()`, `.substring()`, `String.format()`, `Long.parseLong()`)
- metodo con nombre que empieza en `normalize*`, `pad*`, `strip*`, `format*`, `parse*`, `convert*`, `sanitize*`, `encode*`, `clean*`
- metodo cuya firma no usa ningun tipo del dominio propio (solo `String`, `Integer`, `List`, etc)
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

**Bloque completo de referencia** (extraido del gold tnd-msa-sp-wsclientes0024):

```yaml
spring:
  application:
    name: tnd-msa-sp-wsclientes0024
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
    dev.azure.com/project-repo: tpl-middleware/tnd-msa-sp-wsclientes0024   # ✔ matches links[0]
    sonarcloud.io/project-key: 46ce6caa-d7d5-49b5-9c8a-0958a64589c5        # ✔ UUID
  links:
    - url: https://dev.azure.com/BancoPichinchaEC/tpl-middleware/_git/tnd-msa-sp-wsclientes0024
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
