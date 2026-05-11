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
   or `dependsOn: lib-bnc-api-client`.
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
   `tipo`, `recurso`, `componente`, `backend`.
9. Add focused unit/integration tests for each WSDL operation and each mapped
   error path.

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

Use Java 21 and Spring Boot `3.5.14` or newer approved by the bank.

Allowed common dependencies:

- `spring-boot-starter-web`
- `spring-boot-starter-web-services`
- `wsdl4j`
- JAXB/WSDL generation dependencies produced by MCP
- `lib-trace-logger`
- JPA/Hikari/Oracle only when DB usage is proven

Forbidden dependencies:

- `spring-boot-starter-webflux`
- `spring-boot-starter-undertow`
- `io.undertow:*`
- `lib-bnc-api-client`
- `frm-lib-ad-bnc-core-adapter`

## Catalog, Pipeline, Helm

- `metadata.name` is the component name: `<namespace>-msa-sp-<service>`.
- `metadata.namespace` derives from `metadata.name`: `tnd-...` ->
  `tnd-middleware`, `csg-...` -> `csg-middleware`, etc.
- `KUBERNETES_NAMESPACE` in `azure-pipelines.yml` must equal
  `metadata.namespace`.
- Helm env var `name:` / `value:` lines must not contain inline comments.
- No unresolved placeholders: `<pendiente_validar>`, `TODO`, `TBD`,
  `VALIDAR`, `REVISAR`, or `not_probed`.
- HPA CPU `averageValue` must be `100m` in dev/test/prod.

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
