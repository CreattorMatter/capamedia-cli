---
name: migrate-soap-full
title: Migracion SOAP/MVC completa segun bank-mcp-matrix
description: Implementa servicios SOAP/MVC para WAS 2+ operaciones o BUS 2+ operaciones sin BANCS. No agrega BANCS.
type: prompt
scope: project
stage: migration
source_kind: was_or_bus_without_bancs
framework: mvc
complexity: high
---

# SOAP/MVC Migration Prompt

This prompt applies only when `bank-mcp-matrix.md` selects **SOAP + Spring MVC**:

- WAS with 2+ WSDL operations.
- BUS/IIB with 2+ operations and `invocaBancs=false`.

Do not use this prompt for:

- WAS with 1 operation: use REST + MVC.
- BUS/IIB with `invocaBancs=true`: use REST + WebFlux.
- ORQ: use REST + WebFlux + `lib-event-logs`.

`bank-mcp-matrix.md` is the source of truth. If local evidence contradicts it,
stop and report a blocker instead of changing the archetype.

## Non-Negotiable Rules

1. **SOAP/MVC only.** Use Spring WS `@Endpoint`, servlet/Tomcat stack, generated
   JAXB classes, and Spring MVC infrastructure. Do not add WebFlux.
2. **BANCS is prohibited here.** Do not add `lib-bnc-api-client`,
   `BancsService`, `BancsClientHelper`, `bancs.webclients`, `CCC_BANCS_*`,
   or `dependsOn: lib-bnc-api-client`. Create/confirm `.capamedia/fabrics.json`
   with `invoca_bancs: false` (PR-gate source of truth). A `UMP*` reference does
   NOT reclassify the service as BANCS (e.g. `UMPSeguridad*` wraps Cyxtera SOAP).
3. **WAS endpoints are not BUS endpoints.** WAS SOAP keeps the legacy/MCP path,
   normally `/<ServiceName>/soap/*` and `/<ServiceName>/soap/<ServiceName>Request`.
   Never rewrite WAS to `/IntegrationBus/soap/...` unless legacy WAS evidence
   explicitly proves that exact contract.
4. **Ports stay interfaces.** Use `application/input/port` and
   `application/output/port`. Ports are not abstract classes.
5. **Domain is clean.** No Spring, SOAP, JAXB, JPA, WebFlux, logger, or adapter
   imports in `domain/`.
6. **Config is not an output port.** Env/YAML/properties values are read through
   `@ConfigurationProperties` or config beans, never through `*ConfigOutputPort`.
7. **No historical reference projects.** Work only from the service workspace:
   `legacy/`, `umps/`, `tx/`, `destino/`, `.capamedia/fabrics.json`, and the
   canonical prompts/context.
8. **No comment noise.** Do NOT add trivial/redundant comments (version, `fix:`,
   `removed ...`, cosmetic `TODO`, or anything that restates the code). Do NOT
   generate JavaDoc and strip legacy JavaDoc. Keep only comments that document a
   NON-obvious decision (bank catalog literal + source, workaround reason). When
   in doubt, do not add it. Source code and comments in English.
9. **Commit messages.** Short Conventional Commit
   (`feat|fix|refactor|chore: <brief summary>`), no long detail. NEVER mention
   Claude or Anthropic: no `Co-Authored-By`, no "Generated with", no equivalent.

## Expected Structure

```text
src/main/java/com/pichincha/sp/
  application/
    input/port/
    output/port/
    service/
    model/
  domain/
    model/
    exception/
  infrastructure/
    input/adapter/soap/
      config/
      endpoint/
      mapper/
      model/
      util/
    output/adapter/
    config/
src/main/resources/
  application.yml
  legacy/
```

## Implementation Steps

1. Read `bank-mcp-matrix.md`, `.capamedia/fabrics.json`,
   `migration-context.json`, `COMPLEXITY_<service>.md`, and legacy WSDL/XSD.
2. Verify operation count and operation names. Migrated WSDL must preserve every
   legacy operation.
3. Keep MCP scaffold files; do not replace `build.gradle`, `settings.gradle`,
   Dockerfile, Helm, Gradle wrapper, `catalog-info.yaml`, or pipeline wholesale.
4. Implement domain models and exceptions without framework imports.
5. Implement input ports and services in `application/`.
6. Implement SOAP endpoint, SOAP request/response mapping, and `WebServiceConfig`
   under `infrastructure/input/adapter/soap/`.
7. Implement output adapters only for downstreams proven by legacy evidence.
   Do not infer BANCS from TX names or from old examples.
8. Preserve official error structure: `codigo`, `mensaje`, `mensajeNegocio`,
   `tipo`, `recurso`, `componente`, `backend`. See "Error structure" below for
   the strict rules on `recurso` and `componente` (migrated component name,
   never the legacy IIB/WAS/ORQ short name).
9. Add focused unit/integration tests for each WSDL operation and each mapped
   error path.
10. Add `infrastructure/config/TraceLoggerManagementPathConfig.java` (servlet
    variant, below) and its test so Kubernetes probes never reach the
    `lib-trace-logger` extractor (Regla 9e.3, Checks 2.10 / 2.11).
11. Keep INFO logs to transaction-identifying events only; `"Request received
    for operation"`, `"Input validation passed"` and similar diagnostics go to
    `log.debug` (Regla 9e.1, Check 2.6).
12. Before handing the card to the TO, `README.md` (or `docs/`) carries one cURL
    per WSDL operation: sample envelope, `Content-Type: text/xml;charset=utf-8`,
    SOAPAction, success response (`error.codigo=0`, `tipo=INFO`) and at least
    one business error (`tipo=ERROR`). Check 0.6.

## TraceLoggerManagementPathConfig (MVC — mandatory, Regla 9e.3)

`ServletRequestInformationExtractor` of `lib-trace-logger` dumps every request into
a **singleton** `RequestInformationContextHolder`; liveness/readiness/prometheus
probes overwrite the business request context (TO finding 2026-08-25 §1.2). Wrap the
bean with a `BeanPostProcessor` — an extra filter cannot stop the library's filter.
Same code compiles on `lib-trace-logger:1.4.0` (SB3) and `lib-trace-logger-sb4:1.2.0`
(SB4). Location `infrastructure/config/` (Rule: 3 layers), name `*Config`.

```java
package com.pichincha.sp.infrastructure.config;

import com.pichincha.common.trace.logger.extractor.request.information.servlet.ServletRequestInformationExtractor;
import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.context.EnvironmentAware;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

@Component
public class TraceLoggerManagementPathConfig implements BeanPostProcessor, EnvironmentAware {

  private static final String BASE_PATH_PROPERTY = "management.endpoints.web.base-path";
  private static final String DEFAULT_BASE_PATH = "/actuator";

  private String managementBasePath = DEFAULT_BASE_PATH;

  @Override
  public void setEnvironment(Environment environment) {
    String basePath = environment.getProperty(BASE_PATH_PROPERTY, DEFAULT_BASE_PATH);
    this.managementBasePath = basePath.isBlank() ? DEFAULT_BASE_PATH : basePath;
  }

  @Override
  public Object postProcessAfterInitialization(Object bean, String beanName) {
    if (bean instanceof ServletRequestInformationExtractor delegate) {
      return new ManagementPathAwareExtractor(delegate, managementBasePath);
    }
    return bean;
  }

  // El extractor de lib-trace-logger vuelca cada request en un RequestInformationContextHolder
  // singleton: las sondas de liveness/readiness/prometheus pisan el contexto del request de
  // negocio y ademas cachean su body en memoria. Se las deja pasar sin capturar.
  private record ManagementPathAwareExtractor(Filter delegate, String managementBasePath)
      implements Filter {

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
        throws IOException, ServletException {
      if (request instanceof HttpServletRequest httpRequest && isManagementPath(httpRequest)) {
        chain.doFilter(request, response);
        return;
      }
      delegate.doFilter(request, response, chain);
    }

    private boolean isManagementPath(HttpServletRequest request) {
      return pathWithinApplication(request).startsWith(managementBasePath);
    }

    private String pathWithinApplication(HttpServletRequest request) {
      String uri = request.getRequestURI();
      String contextPath = request.getContextPath();
      if (contextPath == null || contextPath.isEmpty() || !uri.startsWith(contextPath)) {
        return uri;
      }
      return uri.substring(contextPath.length());
    }
  }
}
```

Test `TraceLoggerManagementPathConfigTest` (JUnit 5 + Mockito + AssertJ,
`given_when_then`, no `@DisplayName`/JavaDoc, **>= 6 cases**, Check 2.11):
`/actuator/prometheus`, `/actuator/health/liveness`, `/actuator/health/readiness`
→ `chain.doFilter` called, delegate never; `/<ServiceName>/soap/...` → delegate
called, chain never; custom base-path `/management`; blank base-path falls back to
`/actuator`; unrelated `mock(Filter.class)` → `isSameAs`; context path `/svc` +
`/svc/actuator/health` skipped. Use `MockHttpServletRequest` + `mock(FilterChain)`.
`capamedia ai doublecheck` can generate both files.

## Error Structure (mandatory — applies to WAS, BUS without BANCS, and any SOAP target)

Every `<error>` block returned by the migrated service MUST carry the
**migrated component name**, never the legacy IIB/WAS/ORQ short name. QA del
banco (ticket BTHCCC-6826, 2026-05) reporta como HIGH cualquier response con el
nombre legacy en estos campos. Checklist Block 15.2 y 15.3 lo bloquean en CI.

| Field | Rule |
|---|---|
| `recurso` | `<spring.application.name>/<MÉTODO>` — e.g. `csg-msa-sp-wsclientes0011/ConsultarDatosIdentificacion`. **NEVER** `WSClientes0011/...`, `ORQTransferencias0003/...`, or any legacy short name. |
| `componente` | One of: (a) `spring.application.name` (= `<namespace>-msa-sp-<svc>`) for errors internal to the migrated service and successful responses; (b) `ApiClient` (or the literal library name) when the error was propagated from an internal library; (c) `TX<NNNNNN>` (6 digits, prefix `TX`) for business errors propagated from the Core Adapter. **NEVER** `catalog-info.yaml` `metadata.name` (`tpl-middleware`) or the legacy short name. |
| `mensajeNegocio` | `null` or empty string. DataPower populates this. |
| `backend` | 5-digit code from `sqb-cfg-codigosBackend-config/codigosBackend.xml`. Never hardcode `"00000"`. |

**Canonical `CatalogExceptionConstants` for SOAP/MVC:**

```java
package com.pichincha.sp.infrastructure.exception;

import lombok.experimental.UtilityClass;

@UtilityClass
public class CatalogExceptionConstants {

    // ⚠️ MANDATORY — recurso/componente del response usan el nombre del
    // componente MIGRADO (spring.application.name), NUNCA metadata.name
    // (tpl-middleware) ni el legacy IIB/WAS/ORQ. Preferentemente inyectar dinamicamente via
    // @Value("${spring.application.name}") en lugar de literal.
    public static final String WS_RECURSO =
        "<namespace>-msa-sp-<svc>/<Operacion>";   // e.g. "csg-msa-sp-wsclientes0011/ConsultarDatosIdentificacion"
    public static final String WS_COMPONENTE =
        "<namespace>-msa-sp-<svc>";               // e.g. "csg-msa-sp-wsclientes0011"

    // Codes from sqb-cfg-errores-errors/errores.xml — NEVER fabricate
    public static final String ERROR_CODE_SERVICE = "9999";       // catch-all
    public static final String ERROR_CODE_BANCS_INVOKE = "9929";  // BANCS REST/SOAP only
    public static final String ERROR_CODE_BANCS_PARSE = "9922";   // BANCS REST/SOAP only
    public static final String ERROR_CODE_HEADER = "9927";        // header missing/invalid
    public static final String ERROR_CODE_TIMEOUT = "9991";       // downstream timeout

    public static final String SUCCESS_CODE = "0";
    public static final String ERROR_TYPE_INFO = "INFO";
    public static final String ERROR_TYPE_ERROR = "ERROR";
    public static final String ERROR_TYPE_FATAL = "FATAL";
}
```

## Database / Hikari / JPA

This block applies ONLY when `ANALISIS_<ServiceName>.md` reports `DB_USAGE: YES`
or legacy WAS code proves database access.

- WAS + DB uses HikariCP + JPA/JDBC + Oracle under Spring MVC.
- BUS/IIB SOAP without BANCS may use DB only if legacy evidence proves it.
- Do not add JPA/Hikari because of template inertia.
- `spring.jpa.hibernate.ddl-auto` must be `validate` or omitted. Never
  `create`, `create-drop`, or `update`.

**Hikari value source:** every pool value comes from env/config without inline
  default. Example:

```yaml
spring:
  datasource:
    url: ${CCC_DB_URL}
    username: ${CCC_DB_USER}
    password: ${CCC_DB_PASSWORD}
    driver-class-name: oracle.jdbc.OracleDriver
    hikari:
      maximum-pool-size: ${CCC_DB_POOL_MAX}
      minimum-idle: ${CCC_DB_POOL_MIN}
      connection-timeout: ${CCC_DB_CONN_TIMEOUT}
      connection-test-query: ${CCC_DB_CONNECTION_TEST_QUERY}
  jpa:
    database-platform: org.hibernate.dialect.OracleDialect
    hibernate:
      ddl-auto: validate
    open-in-view: false
```

For Oracle use `SELECT 1 from dual`. For SQL Server use `SELECT 1`.

If a reviewer asks why JPA/Hikari is present, point to the exact legacy class,
query, DAO/repository, or config file that proves DB usage.

## Build And Dependencies

Use Java 21 and Spring Boot **`4.1.1`** (baseline for every new project — BPTPSRE
2026-08; MCP `v20260827161016` emits it). **Never downgrade** a version the MCP
generated: if the scaffold is `>= 4.1.1` keep it as-is. If an older MCP build
scaffolded `3.5.x`, raise the plugin to `4.1.1` before development and switch to the
SB4 artifact set below. Only an EXISTING project already built on `3.5.15+` stays on
the SB3 line (Check 8.1 reports MEDIUM; the upgrade goes in a libraries PR with
`lib-trace-logger:1.4.0` → `lib-trace-logger-sb4:1.2.0`). Netty pins are SB3-only
(Check 8.7): never add `io.netty:*:4.1.x` on SB4.

Allowed common dependencies:

- `spring-boot-starter-web`
- `spring-boot-starter-web-services`
- `spring-boot-starter-actuator`
- `wsdl4j`
- JAXB/WSDL generation dependencies produced by MCP
- `lib-trace-logger`
- JPA/Hikari/Oracle only when DB usage is proven

**MANDATORY (Prometheus metrics for KEDA — Regla 9h.3 / Check 8.11):** add these
3 dependencies so the `servicemonitor` can expose `/actuator/prometheus` and KEDA
can scale by `http_server_requests_seconds_count`:

```gradle
// Prometheus metrics for KEDA autoscaling
implementation 'io.micrometer:micrometer-registry-prometheus'
implementation 'io.prometheus:simpleclient_hotspot:0.16.0'
implementation 'io.prometheus:simpleclient_common:0.16.0'
```

**MANDATORY (trace-logger + payload — Checks 7.7 / 7.8):** default observability for
EVERY migrated service (orchestrator AND microservice — NOT ORQ-only). Declare the
dependency:

```gradle
// Spring Boot 4 (baseline): NEW artifactId with -sb4 suffix — Check 8.13
implementation 'com.pichincha.common:lib-trace-logger-sb4:1.2.0'
// Existing Spring Boot 3.5.x projects only:
// implementation 'com.pichincha.common:lib-trace-logger:1.4.0'
```

Forbidden dependencies:

- `spring-boot-starter-webflux`
- `spring-boot-starter-undertow`
- `io.undertow:*`
- `lib-bnc-api-client`
- `frm-lib-ad-bnc-core-adapter`

## Catalog, Pipeline, Helm

- `metadata.name` is fixed: `tpl-middleware`.
- `metadata.namespace` derives from the migrated component name
  (`spring.application.name` / repo folder): `tnd-...` -> `tnd-middleware`,
  `csg-...` -> `csg-middleware`, etc.
- `KUBERNETES_NAMESPACE` in `azure-pipelines.yml` must equal
  `metadata.namespace`.
- Helm env var `name:` / `value:` lines must not contain inline comments.
- Helm probes (Spring Boot 4, Checks 7.10 / 7.11): `livenessProbe` curls
  `/actuator/health/liveness` and `readinessProbe` curls
  `/actuator/health/readiness` in `helm/dev.yml`, `test.yml`, `prod.yml`
  (canonical `if ! curl -s <url> | grep -q '"status":"UP"'; then exit 1; fi`; the
  MCP `cut` form is accepted; never the aggregate `/actuator/health`). Keep the
  chart timings. `application.yml` declares
  `management.endpoint.health.probes.enabled: ${CCC_ACTUATOR_HEALTH_PROBES_ENABLED}`
  and the 3 Helm files set `CCC_ACTUATOR_HEALTH_PROBES_ENABLED: "true"`.
- No unresolved placeholders: `<pendiente_validar>`, `TODO`, `TBD`,
  `VALIDAR`, `REVISAR`, or `not_probed`.
- Helm capacity + KEDA baseline (Banco Pichincha official; capacity ajuste 2026-07): every `helm/dev.yml`, `helm/test.yml`, `helm/prod.yml` must carry the canonical `resources` baseline plus **KEDA** autoscaling — `hpa:` is **deprecated**. Values are **referential** to let pods start; refined after performance/load tests. See `bank-official-rules.md` Regla 9h.1 for the source. Required: `resources.requests` (cpu=`50m`, memory=`100Mi`), `resources.limits` (cpu=`200m`, memory=`400Mi`); `keda.enabled=true` with `minReplicaCount=1`/`maxReplicaCount=1` and a prometheus trigger on `http_server_requests_seconds_count`; `servicemonitor.enabled=true` with `path='/actuator/prometheus'`; **no `hpa:` block**. Validated by checklist 7.4/7.5d/7.5e/7.5g (HIGH).
- Helm env `JAVA_OPTIONS` baseline (Banco Pichincha official; capacity ajuste 2026-07): every helm must declare `env: - name: "JAVA_OPTIONS"` with value `"-XX:MaxRAMPercentage=60.0 -XX:+UseStringDeduplication -XX:+UseG1GC"`. Use ASCII only and separate flags with normal space `U+0020`; never paste `U+00A0` or invisible separators. The 2026-07 adjustment lowered `MaxRAMPercentage` 70→60 and dropped `InitialRAMPercentage`. See `bank-official-rules.md` Regla 9h.2. Validated by checklist Block 7.5f (HIGH on deviation).
- trace-logger + payload by default (orchestrator AND microservice — NOT ORQ-only). `application.yml` declares the `trace-logger` block with `enabled: ${CCC_TRACE_LOGGER_ENABLED}`, `custom-level` (enabled/infoEnabled/debugEnabled/warnEnabled/errorEnabled via `${CCC_CUSTOM_LEVEL_*}`) and `payload.mode: ${CCC_PAYLOAD_MODE}` — no inline defaults (Rule 7). `application-test.yml` uses literals with `enabled: false` and `payload.mode: NONE`. The 7 env vars go in all 3 `helm/*.yml`: `CCC_TRACE_LOGGER_ENABLED`, `CCC_CUSTOM_LEVEL_ENABLED/INFO/DEBUG/WARN/ERROR_ENABLED`, `CCC_PAYLOAD_MODE`. Per-environment rule: `CCC_CUSTOM_LEVEL_DEBUG_ENABLED = true` only in `dev` (test/prod = `false`); `CCC_PAYLOAD_MODE = NONE` in the 3 (never log payload/PII, mandatory in prod). The transactional-log block (`lib-event-logs`, `spring.kafka`, `logging.event`, `xml.template`) stays ORQ-only — do NOT add it to microservices. Validated by checklist 7.7 (application.yml) and 7.8 (helm), both HIGH.

## Peer Review Gate

Before closing, run the build and `architectureReview` when available.

The peer review must not report:

- `BLOQUEAR PR: SI`
- misplaced ports outside `application/input/port` or `application/output/port`
- WebFlux in SOAP/MVC
- BANCS artifacts in WAS/BUS-without-BANCS SOAP
- missing operation tests

## Final Verification

Run, when available:

```bash
./gradlew clean build
./gradlew architectureReview
capamedia review --dry-run
```

If any command cannot run because of credentials or corporate network access,
record the exact blocker and do not mark the migration as complete.
