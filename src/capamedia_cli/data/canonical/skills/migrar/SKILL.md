---
name: migrar
description: Ejecuta la migracion completa de un servicio legacy a Java Spring Boot hexagonal OLA1 con loop de autocorreccion
allowed-tools: Read Glob Grep Bash Edit Write Agent
---

# /migrate

Ejecuta la migracion completa usando el ANALISIS_*.md previamente generado. Si el
harness invoca este skill como `/migrar`, tratarlo como alias legacy de `/migrate`.

## Prerequisitos
- ANALISIS_<ServiceName>.md debe existir en el directorio actual o en docs/
- El servicio legacy debe estar accesible para referencia

## Pasos

1. **Leer el analisis** — Extraer: nombre, tribu, framework (webflux/mvc), operaciones, UMPs

1.5. **Rutear al prompt correcto segun `bank-mcp-matrix.md`** (fuente unica BPTPSRE):
   - Leer `sourceKind` / `tecnologia_origen`, `invocaBancs`, `deploymentType`, `projectType`, `webFramework` y operaciones del `<wsdl:portType>`.
   - **BUS/IIB + `invocaBancs=true`** -> REST + WebFlux + `@RestController` con cualquier cantidad de operaciones.
   - **ORQ / `deploymentType=orquestador`** -> REST + WebFlux + `@RestController` con cualquier cantidad de operaciones y `lib-event-logs`.
   - **WAS + 1 operacion** -> REST + Spring MVC + `@RestController`.
   - **WAS + 2+ operaciones** -> SOAP + Spring MVC + `@Endpoint`.
   - **BUS/IIB sin BANCS** -> 1 op REST + WebFlux; 2+ ops SOAP + Spring MVC.
   - La presencia de BD NO cambia la decision REST/SOAP. En WAS/MVC se agrega HikariCP+JPA; en WebFlux se debe escalar/flaggear antes de meter blocking JPA.
   - Documentar la decision con parametro decisivo, source type y cantidad de operaciones.

2. **Bloque 1: Scaffolding**
   - Crear proyecto Gradle copiando patrones del proyecto referencia
   - Versiones: baseline Spring Boot `4.1.1` (MCP `v20260827161016`). **Nunca bajar** lo que emitio el MCP; si el scaffold vino en 3.5.x (MCP viejo), subir a `4.1.1` + `lib-trace-logger-sb4:1.2.0` (+ `lib-event-logs-webflux:2.0.0` en ORQ, `lib-bnc-api-client:3.0.0` solo BANCS). Un proyecto SB3 ya construido se conserva en `3.5.15+`.
   - Copiar WSDL/XSD, fix schemaLocation
   - GATE: verificar estructura y `grep "org.springframework.boot' version" build.gradle` (>= 4.1.1 o la version mayor del MCP)

3. **Bloque 2: Domain**
   - Crear records, exceptions
   - GATE: grep domain/ por imports de Spring (debe ser vacio)

4. **Bloque 3: Application**
   - Crear interface ports + service impl
   - GATE: grep ports por "public interface" (debe ser >0), grep application/ por imports de infrastructure/ (debe ser vacio)

5. **Bloque 4: Infrastructure**
   - Input adapter correcto segun matriz (REST `@RestController` o SOAP `@Endpoint`), DTOs, mappers, BANCS adapters (stubs si TX desconocida), config, error resolvers, application.yml
   - `infrastructure/config/TraceLoggerManagementPathConfig.java` (BeanPostProcessor; variante WebFlux `ReactiveRequestInformationExtractor` o MVC `ServletRequestInformationExtractor` segun stack) + su test (>= 6 casos given_when_then). ORQ: `logging.event.excluded-paths: /actuator/**,/health,/metrics,/prometheus`. Logs INFO solo con correlador; diagnosticos a DEBUG.
   - GATE: grep @Autowired (debe ser 0), verificar adapters implementan ports, `find . -name TraceLoggerManagementPathConfig.java` (1 archivo)

6. **Bloque 5: Helm + Docker**
   - helm/dev.yml, test.yml, prod.yml con probes a `/actuator/health/liveness` (liveness) y `/actuator/health/readiness` (readiness), nunca el agregado `/actuator/health`; `CCC_ACTUATOR_HEALTH_PROBES_ENABLED: "true"` en los 3
   - GATE: grep liveness/readiness en todos los Helm

7. **Bloque 6: Tests**
   - Unit tests JUnit 5 + Mockito + StepVerifier
   - GATE: intentar ./gradlew test (documentar si falla por credenciales)

8. **Loop de autocorreccion** en cada GATE:
   - Si falla: identificar → analizar → corregir → re-verificar
   - Max 3 intentos antes de escalar al usuario

9. **Generar MIGRATION_REPORT.md** con seccion GenAI, y **README.md con un cURL por operacion del WSDL** (envelope, `Content-Type: text/xml;charset=utf-8`, respuesta OK y al menos un error de negocio) — gate previo a asignar al TO

10. **Generar NO_VERIFICABLE_LOCAL.md** con lo que no se pudo probar

## Ejemplo de uso
```
/migrate
```
(alias legacy: `/migrar`; ejecutar desde la raiz del proyecto destino, con ANALISIS_*.md presente)
