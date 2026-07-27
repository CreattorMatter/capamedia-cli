---
name: checklist-rules
title: Reglas completas del checklist BPTPSRE (17 bloques)
description: Checklist oficial pass/fail con severidad HIGH/MEDIUM/LOW en formato AI-Dense.
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
- Write
---

# BPTPSRE Checklist Auditor (AI-Dense Edition)

Este prompt consolida de forma compacta y declarativa el checklist ejecutable **BPTPSRE** del Banco Pichincha para auditar microservicios Java Spring Boot migrados a arquitectura hexagonal OLA1.

---

## MODO DE OPERACIÓN: AUDITOR
1. **Analizar** el código fuente del proyecto migrado (`<MIGRATED_PATH>`) y del legacy original (`<LEGACY_PATH>`) si se provee.
2. **Generar un reporte estructurado** pass/fail para cada Check.
3. **No modificar código.** Limitarse a diagnosticar.

---

## BLOQUE 0: Tipo de Proyecto y Clasificación
* **Check 0.1: SOAP vs REST.** Determinar framework:
  - `@Endpoint` o `WebServiceConfig` presente en `src/main/java` -> **SOAP** (requiere Spring MVC).
  - `@RestController` presente y NO `@Endpoint` -> **REST** (requiere WebFlux si `invocaBancs=true` o ORQ; Spring MVC si no).
  - Ambos o ninguno -> **FAIL HIGH** (proyecto malformado).
* **Check 0.2: Matriz MCP.** Comparar framework usado (`actual`) contra el esperado por matriz oficial:
  - `invocaBancs=true` -> **REST + WebFlux** (Regla 1).
  - `deploymentType=orquestador` -> **REST + WebFlux + lib-event-logs** (Regla 2).
  - `projectType=soap` + `deploymentType=microservicio` + `invocaBancs=false` -> **SOAP + Spring MVC** (Regla 3).
  - Divergencias -> **FAIL HIGH** (mal-clasificado).
* **Check 0.2f: WAS SOAP no publica en BUS/IIB.** Si es WAS SOAP, no debe usar `/IntegrationBus/soap` en endpoints (usar `/<ServiceName>/soap/*`). Si contiene match activo -> **FAIL HIGH**.
* **Check 0.3: Operaciones del WSDL.** WSDL migrado (`src/main/resources/legacy/`) debe tener idénticas operaciones a las del legacy. Si no coinciden -> **FAIL HIGH**.
* **Check 0.4: targetNamespace del WSDL.** targetNamespace en el WSDL migrado debe ser idéntico al legacy. Si difiere -> **FAIL HIGH**.
* **Check 0.5: XSDs presentes.** Todos los XSDs importados en el WSDL deben estar presentes en `src/main/resources/legacy/`. Faltantes -> **FAIL HIGH**.

---

## BLOQUE 1: Arquitectura Hexagonal y Service Purity
* **Check 1.1: Capas presentes.** Estructura obligatoria: `domain/`, `application/` (con `port/input/` y `port/output/`), `infrastructure/` (con `input/adapter/` y `output/adapter/` o `output/client/`). Falta de estructura -> **FAIL HIGH**.
* **Check 1.2: Domain Pure.** Cero imports de `spring`, `jakarta`, `javax`, `lombok` (excepto `@Getter`/`@Setter` básicos) en la capa domain. Cualquier import de framework -> **FAIL HIGH**.
* **Check 1.3: Puertos son interfaces.** Todo puerto en `port/input/` y `port/output/` debe declararse como `interface` (no `abstract class`). Si es abstract class -> **FAIL HIGH**.
* **Check 1.3c: Config no es output port.** Las clases de configuración o properties de negocio no deben guardarse en `port/output/`. Matches -> **FAIL HIGH**.
* **Check 1.4: Un solo output port Bancs.** Para invocar a BANCS, debe haber un único puerto consolidado en la capa de dominio/aplicación. Múltiples puertos de BANCS -> **FAIL HIGH**.
* **Check 1.5: Adapters implementan ports.** Los adapters en `infrastructure/` deben implementar sus puertos correspondientes mediante `implements` (no `extends`). Si usan abstract class o extends -> **FAIL HIGH**.
* **Check 1.7: Aislamiento de entrada.** Componentes en `infrastructure/input/` no deben consumir directamente ningún output port; deben interactuar únicamente a través de la capa de aplicación/servicios. Matches directos -> **FAIL HIGH**.
* **Check 1.6: Service Purity.** Todo componente marcado con `@Service` no debe contener métodos privados (debe delegar a helpers de infraestructura o utilitarios). Matches de métodos privados -> **FAIL HIGH**.

---

## BLOQUE 2: Trazabilidad, Logging y BpLogger
* **Check 2.1: BpTraceable en Controllers.** Todo controlador o endpoint REST/SOAP debe estar decorado con `@BpTraceable` y usar inyección de constructor (no `@Autowired`). Sin anotación -> **FAIL HIGH**.
* **Check 2.2: BpLogger en @Service.** Todo método público en componentes `@Service` debe usar `@BpLogger` o el trace helper del banco para asegurar el flujo transaccional. Métodos públicos sin traza -> **FAIL HIGH**.
* **Check 2.5: Sin imports directos de org.slf4j.** Prohibido importar `org.slf4j.*` o declarar `@Slf4j` de Lombok directamente. Debe usarse `ServiceLogHelper log` inyectado y anotación `@BpLogger`/`@BpTraceable`. Matches directos -> **FAIL HIGH**.
* **Check 2.8: Cobertura log INFO.** Componentes clave (Controllers, Helpers, Clients) deben tener al menos un log a nivel INFO (`log.info()`). Sin log INFO -> **FAIL INFO** (meramente recomendado, no bloqueante).
* **Check 2.9: Cobertura log DEBUG.** Componentes clave (Controllers, Helpers, Clients) deben tener al menos un log a nivel DEBUG (`log.debug()`). Sin log DEBUG -> **FAIL INFO** (meramente recomendado, no bloqueante).
* **Check 2.6: Log Info para eventos de contrato.** Los logs de nivel INFO deben estar estrictamente acotados a inicio, fin de transacciones o eventos de contrato de negocio.
* **Check 2.7: No abuso de log.info.** Evitar inyectar logs informativos redundantes o dentro de bucles interactivos intensivos.

---

## BLOQUE 3: Naming y Convenciones Profesionales
* **Check 3.1: Output ports usan get\* para lecturas.** Los métodos de consulta en puertos de salida deben empezar con el prefijo `get` (no `obtener`, `search`, etc.). Desviaciones -> **FAIL HIGH**.
* **Check 3.2: localPart PascalCase.** En endpoints SOAP, `@PayloadRoot.localPart` debe coincidir exactamente en PascalCase con el request WSDL. Divergencias -> **FAIL HIGH**.
* **Check 3.3: CamelCase en métodos Java.** Todo método Java debe usar strictly camelCase. Matches con PascalCase o snake_case -> **FAIL MEDIUM**.
* **Check 3.4: postProcessWsdl.groovy limpio.** (SOAP) El script groovy no debe contener la regla de decapitalize activa en los elementos generados. Desviaciones -> **FAIL HIGH**.
* **Check 3.5: Naming profesional.** Evitar nombres genéricos como `Data`, `Request`, `Response`, `Helper` a secas. Deben tener el prefijo semántico del microservicio. Uso de nombres crudos genéricos -> **FAIL MEDIUM**.

---

## BLOQUE 4: Validación de `<headerIn>` — Política vigente desde 2026-05-26

> **Cambio de política**: la clase `HeaderRequestValidator` con patrones regex
> + max length por campo **se elimina del proyecto**. La validación de tamaños
> y patrones del header queda delegada a DataPower (capa de borde). En el
> microservicio, la única validación permitida sobre `<headerIn>` es el
> null-check del bloque `<bancs>`, y solo para servicios que invocan BANCS
> Core Adapter. Reemplaza a los checks 4.1–4.6 anteriores. Ver §4.6 del
> prompt REST canónico para el detalle completo.

* **Check 4.1: NO existe `HeaderRequestValidator`.** No debe existir en el
  proyecto migrado el archivo
  `infrastructure/input/adapter/**/util/HeaderRequestValidator.java` ni su
  test asociado. Presencia -> **FAIL HIGH**.
* **Check 4.2: NO regex/maxLength sobre `<headerIn>`.** En el controller no
  debe haber `Pattern.compile(...)` ni comparaciones `.length() > N` aplicadas
  a campos de `GenericHeaderIn`/`GenericHeaderOut` (dispositivo, empresa,
  canal, medio, aplicación, agencia, tipoTransacción, geolocalización,
  usuario, unicidad, guid, fechaHora, filler, idioma, sesión, ip, idCliente,
  tipoIdCliente). Matches -> **FAIL HIGH**.
* **Check 4.3: Null-check del `<bancs>` solo cuando aplica.** En servicios
  con `invocaBancs=true` (BUS/IIB), el controller debe chequear
  `headerIn == null || headerIn.getBancs() == null` ANTES de invocar BANCS y
  devolver HTTP 200 con `codigo=9927`, `tipo=FATAL`, `backend=00638`,
  `mensaje="Datos de la cabecera de la transaccion no se han asignado"`.
  Sin null-check -> **FAIL HIGH**. En WAS, ORQ y BUS sin BANCS, el null-check
  del `<bancs>` **NO** debe existir — su presencia es residuo del template
  viejo.
* **Check 4.4: NO `HeaderValidationProperties` ni patterns externalizados.**
  No debe existir `@ConfigurationProperties` o bean que exponga regex/length
  de campos del header desde `application.yml`. Presencia -> **FAIL HIGH**.
* **Check 4.5: Códigos 9927/9996 solo para falta de `<bancs>`.** Si el
  proyecto devuelve `codigo=9927` o `codigo=9996` en cualquier otra ruta
  (longitud excedida, pattern mismatch, campo vacío que no sea `<bancs>`), es
  residuo del validator viejo. Matches -> **FAIL HIGH**.

---

## BLOQUE 5: Manejo de Errores e Integridad de Entrada
* **Check 5.1: BancsClientHelper execute wrapping (SOAP).** Las llamadas al cliente SOAP de BANCS deben envolver cualquier `RuntimeException` y lanzarla mapeada a una excepción controlada (como `BancsOperationException` / `BancsException`). Sin wrapping -> **FAIL HIGH**.
* **Check 5.2: Catch en Controller/Service.** Controlador o servicio debe atrapar controladamente la excepción de BANCS para construir el payload de error estándar del banco. Fuga de excepciones -> **FAIL HIGH**.
* **Check 5.3: Cero SOAP Faults (SOAP).** La respuesta HTTP debe ser siempre 200 OK, encapsulando las fallas dentro del bloque `<error>` del payload XML. SOAP Faults detectados -> **FAIL HIGH**.
* **Check 5.4: error.backend catalogado.** El valor del campo `backend` devuelto en el error debe coincidir con el código del backend oficial mapeado en `bank-shared-properties.md` (no hardcodear `"00000"` ni `"999"`). Hardcodeado -> **FAIL HIGH**.
* **Check 5.5: BusinessValidationException.** Lanzar excepciones de negocio específicas heredadas de una excepción base en `domain`, no lanzar `RuntimeException` genéricas.
* **Check 5.5b: Mensajes sin normalizar.** Los mensajes de error de cara al cliente deben mapearse directamente desde el catálogo del banco, sin alteración de texto literal inline.
* **Check 5.6: error.tipo.** El campo tipo de error debe clasificarse estrictamente en uno de los valores definidos: `INFO` (success), `ERROR` (BusinessValidationException y errores BANCS), `FATAL` (solo header missing `9927` y catch-all `9999`). Desviaciones -> **FAIL HIGH**.
* **Check 5.6.5: BusinessValidationException NO se mapea a FATAL.** El catch de `BusinessValidationException` no debe rutear a `buildFatalResponse`/`buildBancsErrorResponse` ni setear `tipo="FATAL"` ni `ERROR_TYPE_FATAL`. Es validación recuperable -> tipo `ERROR`. Matches -> **FAIL HIGH**.
* **Check 5.7b: BANCS / GlobalErrorException NO se mapean a FATAL.** Errores de BANCS (`BancsOperationException`, `BancsClientException`, `TimeoutException`, `GlobalErrorException`) son tipo `ERROR` — el caller puede reintentar. `FATAL` queda solo para header missing y catch-all. Aclaración oficial Kevin Armas / BPTPSRE 2026-05-27. Matches -> **FAIL HIGH**.
* **Check 5.8: Fechas nulas BANCS.** Para indicar campos de fecha vacíos o nulos enviados a BANCS, usar el valor oficial del banco `31129999`. Uso de otros valores por defecto -> **FAIL MEDIUM**.
* **Check 5.10: Validacion de entrada en Controllers.** Inyectar `jakarta.validation.Validator` y realizar validación programática (`validator.validate(dto)`) o decorar parámetros con `@Valid` en la firma de métodos del controlador. Sin validación -> **FAIL HIGH**.
* **Check 5.11: Validacion sintáctica en DTOs.** Aplicar restricciones sintácticas a los campos de DTOs usando anotaciones de Jakarta Bean Validation (ej: `@NotNull`, `@Pattern`, `@Size`, `@Min`, `@Max`). DTOs sin validación -> **FAIL MEDIUM**.
* **Check 5.12: Allowlist en campos de tipo/código.** Implementar obligatoriamente validación de allowlist mediante expresiones regulares ancladas con `^` y `$` en campos DTO opcionales o cerrados (ej: `@Pattern(regexp = "^[CRPOcrpo]$")` en tipoIdentificacion). Sin allowlist -> **FAIL MEDIUM**.
* **Check 5.13: Paridad de short-circuit en ORQ (ORQ-RETURN-PARITY).** Solo `source_kind=orq`. En IIB, `CALL Proc() INTO respuesta; IF NOT respuesta THEN RETURN FALSE;` parece mandatorio, pero si el `PROCEDURE` invocado NO tiene `RETURN FALSE` en su rama de error (cae al `RETURN TRUE` final) el downstream es **best-effort** (su falla no corta el flujo legacy). El CLI cruza el `Mono.zip` migrado contra el `RETURN FALSE` de los `PROCEDURE` del ESQL legacy por **conteo agregado** (cuenta invocaciones `.onError*` —en el `ServiceImpl` o en sus `util/*Helper.java`— y las contrasta con los PROCEDURE best-effort/mandatory), con detección **léxica conservadora**: NO se parsea el Java por rama (un mini-parser a mano resultó frágil con text blocks/generics/strings y se revirtió en v0.28.10). Veredictos: fan-out **homogéneo todos-mandatory** con algún `.onError*` -> **FAIL HIGH** (más permisivo, ignora errores que el legacy propaga); **homogéneo todos-best-effort** sin ningún `.onError*` -> **FAIL HIGH** (más estricto, rompe casos productivos, ej. cliente sin asesor → 500 en vez de 200); **mixto** (mandatory + best-effort) -> **FAIL LOW** (revisión manual — el conteo agregado no distingue por rama, nunca HIGH/MEDIUM automático en mixto); coherente -> **PASS**. Sin legacy -> **FAIL LOW**. Casos: ORQClientes0022 (OP21, best-effort), ORQClientes0023 (4 downstreams mandatory).

---

## BLOQUE 6: Mappers y DTOs
* **Check 6.1: Mappers dedicados.** El mapeo entre las entidades de dominio y DTOs de infraestructura debe residir en clases mapper independientes en lugar de realizarse inline dentro de los servicios.
* **Check 6.2: MapStruct.** Usar la librería `MapStruct` para la generación automática de mappers. Mapeo manual extensivo -> **FAIL MEDIUM**.
* **Check 6.3: Sin new Record con >=8 args.** Prohibido instanciar records Java de forma manual inline con 8 o más argumentos. Debe usarse un mapper o un builder adecuado. Instanciación inline -> **FAIL MEDIUM**.
* **Check 6.4: Sin tipos genéricos en firmas.** Las firmas de los métodos en interfaces de puertos no deben usar `Object` ni `Map<String, Object>` para pasar payloads de negocio. Uso de tipos genéricos -> **FAIL HIGH**.

---

## BLOQUE 7: Pipeline, Helm y Variables de Entorno
* **Check 7.1: catalog-info.yaml completo.** El archivo debe estar completamente parametrizado.
  - `spec.owner: jgarcia@pichincha.com` (NO `<owner>`).
  - `metadata.name` fijo `tpl-middleware`.
  - `metadata.namespace` debe derivar del componente migrado (`csg-middleware` o `tnd-middleware` etc).
  - Placeholders (`<...>`) -> **FAIL HIGH**.
* **Check 7.1c: metadata.name literal.** `metadata.name` en `catalog-info.yaml` debe ser literalmente `tpl-middleware` (no parametrizado ni otro valor). Desviaciones -> **FAIL HIGH**.
* **Check 7.2: azure-pipelines.yml.** Asegurar alineación con el template oficial del pipeline. Desviaciones -> **FAIL HIGH**.
* **Check 7.3: application.yml variable mapping.** Las propiedades dinámicas de `application.yml` deben leerse desde variables de entorno mapeadas en Helm (`helm/values.yaml` o `helm/dev.yml`).
* **Check 7.4: Configuración de Clientes.** Validar timeouts, configuración de reintentos y circuit breakers oficiales en la capa de integración de WebClient/SOAP.
* **Check 7.5: Helm values por entorno.** Helm de `dev.yml`, `test.yml` y `prod.yml` presentes con estructura coherente.
* **Check 7.4 / 7.5b: HPA derogado (KEDA).** HPA quedo derogado (capacity Banco Pichincha 2026-07). La presencia de un bloque `hpa:` en cualquier helm por-entorno es **FAIL HIGH**; el autoscaling se declara con `keda:` + `servicemonitor:`.
* **Check 7.5c: Helm variables sin placeholders.** Valores en `dev.yml`, `test.yml` y `prod.yml` no deben contener comentarios inline dentro del par name/value ni placeholders literales `<...>`. Matches -> **FAIL HIGH**.
* **Check 7.5d: Helm KEDA habilitado.** Cada helm por-entorno debe declarar `keda:` con `enabled: true`, `minReplicaCount`, `maxReplicaCount` y al menos un `triggers`. `minReplicaCount`/`maxReplicaCount` = `1` como baseline. Desviaciones -> **FAIL HIGH**.
* **Check 7.5e: Helm resources.** Los bloques `resources.requests` y `resources.limits` de CPU y Memoria deben coincidir exactamente con los valores baseline oficiales del banco. Desviaciones -> **FAIL HIGH**.
* **Check 7.5f: JAVA_OPTIONS baseline.** La variable `JAVA_OPTIONS` en el Helm debe tener exactamente el valor: `"-XX:MaxRAMPercentage=60.0 -XX:+UseStringDeduplication -XX:+UseG1GC"`. Desviaciones o caracteres corruptos (no-ASCII) -> **FAIL HIGH**.
* **Check 7.5g: ServiceMonitor Prometheus.** Cada helm por-entorno debe declarar `servicemonitor:` con `enabled: true` y `path: '/actuator/prometheus'` (fuente de metricas del trigger KEDA). Desviaciones -> **FAIL HIGH**.
* **Check 7.7: trace-logger + payload en application.yml.** Observabilidad por defecto en TODO servicio (orquestador Y microservicio, NO ORQ-only). `application.yml` debe declarar el bloque `trace-logger:` que referencia via `${...}` cada env var (`CCC_TRACE_LOGGER_ENABLED`, `CCC_CUSTOM_LEVEL_ENABLED/INFO/DEBUG/WARN/ERROR_ENABLED`) y el sub-bloque `payload:` con `mode: ${CCC_PAYLOAD_MODE}` — sin defaults inline (Regla 7). Ausente o parcial -> **FAIL HIGH** (autofix `fix_trace_logger_application`).
* **Check 7.8: Helm env vars trace-logger + payload.** Cada helm por-entorno (dev/test/prod) debe declarar las 7 env vars CCC_* del trace-logger con el valor esperado del ambiente: `CCC_CUSTOM_LEVEL_DEBUG_ENABLED = true` solo en `dev` (test/prod = `false`); `CCC_PAYLOAD_MODE = NONE` en los 3 (no loguear payload/PII); el resto igual en los 3. Faltantes o valor incorrecto -> **FAIL HIGH** (autofix `fix_trace_logger_helm` inyecta las ausentes). El log transaccional (`lib-event-logs`, `spring.kafka`) sigue siendo ORQ-only y NO se valida aca.
* **Check 8.11: Deps Prometheus/KEDA.** `build.gradle` debe declarar `io.micrometer:micrometer-registry-prometheus`, `io.prometheus:simpleclient_hotspot:0.16.0` y `io.prometheus:simpleclient_common:0.16.0`. Faltantes -> **FAIL HIGH** (autofix `fix_add_prometheus_deps`).
* **Check 8.12: Version del plugin peer-review del banco.** El bloque `plugins {}` de `build.gradle` debe declarar `id 'com.pichincha.frm-plugin-peer-review-gradle' version '1.1.2'` (version vigente 2026-07; los scaffolds viejos de Fabrics traen `1.1.0`). Version menor, o plugin ausente/sin version literal -> **FAIL HIGH**. Se acepta una version mayor (mismo criterio que 8.1). Autofix `fix_peer_review_plugin_version`: actualiza una declaracion existente pero **no inyecta el plugin si falta** — se resuelve desde el repo interno del banco (`settings.gradle`) y un `id` no resoluble rompe el build.

---

## BLOQUE 8: Seguridad y Parches de Vulnerabilidades
* **Check 8.1: Spring Boot Plugin Version.** La versión de Spring Boot en `build.gradle` debe estar alineada al baseline del banco (`3.4.5` o la oficial). Versión deprecada -> **FAIL HIGH**.
* **Check 8.2: Gradle sin Undertow activo.** Spring Boot debe usar Tomcat (Netty para WebFlux) como servidor embebido. Dependencias o exclusiones forzadas de Tomcat para usar Undertow -> **FAIL HIGH**.
* **Check 8.3: Peer Review score >= 7.** El reporte de revisión del par en `build/reports` debe reflejar una calificación mayor o igual a 7. Calificación baja -> **FAIL HIGH**.
* **Check 8.4: Lombok minimal.** Solo permitido `@Getter`, `@Setter` (en config) y `@RequiredArgsConstructor`. `@Slf4j` prohibido (ver 2.5). Uso de `@Data`/`@Builder`/`@AllArgsConstructor` -> **FAIL MEDIUM**.
* **Check 8.5: WebFlux starter presente en BUS.** Servicios clasificados con tecnología `bus` deben contar obligatoriamente con `spring-boot-starter-webflux` en `build.gradle`. Faltante -> **FAIL HIGH**.
* **Check 8.6: MVC starter ausente en WebFlux.** Si se usa WebFlux, no debe estar presente `spring-boot-starter-web`. Presencia de ambos -> **FAIL MEDIUM**.
* **Check 8.7: Sin pins de io.netty (con excepción WebFlux).** Evitar declarar pins manuales de dependencias transitivas de Netty (`io.netty:*`) en el `dependencyManagement` de `build.gradle`. Pins manuales -> **FAIL HIGH**. **Excepción oficial v0.27.0**: en proyectos WebFlux (`spring-boot-starter-webflux` presente) el pin `io.netty:*:4.1.136.Final` está permitido (CVE-fix Snyk 2026-07 aprobado; historial `4.1.133` → `4.1.135` → `4.1.136`). Cualquier otra versión sigue bloqueada (incluidas `4.1.135.Final` y 4.2.x, que rompe Reactor Netty: `StacklessClosedChannelException`). MVC/SOAP: no se permite pin manual de ninguna versión.
* **Check 8.8: Árbol Netty completo en WebFlux (13 módulos, doble pin).** Cuando un proyecto WebFlux ya pinea `io.netty:*:4.1.136.Final`, los **13 módulos core** del árbol (`netty-common`, `netty-buffer`, `netty-transport`, `netty-transport-native-unix-common`, `netty-resolver`, `netty-resolver-dns`, `netty-codec`, `netty-codec-dns`, `netty-codec-http`, `netty-codec-http2`, `netty-codec-socks`, `netty-handler`, `netty-handler-proxy`) deben estar pineados con **doble mecanismo**: `dependencyManagement { dependency '...' }` **y** `configurations.all { resolutionStrategy { force '...' } }`. El BOM de Spring Boot 3.5.x trae Netty en versión vulnerable (`4.1.121.Final`) y `dependencyManagement` no siempre gana sobre transitivas (lib-bnc, el propio BOM); el `force` lo garantiza. Pinear solo `netty-codec*` deja transitivos como `netty-handler-proxy` vulnerables (WSClientes0013: 9 CVEs). Faltantes -> **FAIL HIGH** (autofix `fix_netty_full_tree_pin`). Incluye `netty-transport-native-unix-common` (módulo Java puro); excluye solo binarios nativos por-SO (`netty-transport-native-epoll`/`kqueue`) y `netty-tcnative-*`. **NO bumpear a 4.2.x** (rompe Reactor Netty).
* **Check 8.10: Pins de seguridad WebFlux NO-Netty (Snyk 2026-06).** Mismo Snyk report y mismo gate que 8.8 (WebFlux con Netty ya pineado en la versión permitida). En `dependencyManagement` deben estar: `dependency 'io.micrometer:micrometer-core:1.15.12'`, `'io.projectreactor.netty:reactor-netty-http:1.2.18'`, `'org.springframework.retry:spring-retry:2.0.13'`, `'org.springframework.kafka:spring-kafka:3.3.16'` + `imports { mavenBom 'org.springframework:spring-framework-bom:6.2.19' }`. Faltante o versión distinta -> **FAIL HIGH** (autofix `fix_webflux_security_pins`). **Solo WebFlux** (BUS REST + ORQ): `reactor-netty-http`/`spring-kafka` no existen en MVC/SOAP. Fuente única de versiones: `WEBFLUX_SECURITY_DEPENDENCY_PINS` + `SPRING_FRAMEWORK_BOM_*` en `version_policy.py`.
* **Check 8.9: lib-bnc-api-client solo si BUS/IIB + invocaBancs.** La dependencia `com.pichincha.bnc:lib-bnc-api-client` debe estar declarada en `build.gradle` SOLO si el servicio es BUS/IIB **y** `invoca_bancs=true`. Fuente de verdad: `.capamedia/fabrics.json` (`tecnologia`/`source_kind` + `invoca_bancs`); fallback a la matriz MCP (`source_type` + `has_bancs`). Veredictos: lib + invocaBancs=true -> **PASS**; lib + invocaBancs=false (o sin `fabrics.json`) -> **FAIL HIGH** (el PR-gate oficial `validate_hexagonal.py` la rechaza; acción: remover la lib + las 3 `spring.autoconfigure.exclude` BANCS); sin lib + invocaBancs=false -> **PASS**; sin lib + invocaBancs=true -> **FAIL HIGH** (lib mandatoria). **Nota (falso positivo WSReglas0010, corregido v0.28.6):** el detector `detect_bancs_connection` ya NO marca BANCS por cualquier `UMP*` — solo UMPs de prefijo BANCS conocido (`UMPClientes`, `UMPCuentas`, `UMPTransacciones`, ...) o TX literal `0NNNNN`; las UMP no-BANCS (Cyxtera/`UMPSeguridad`, autorizadores, `UMPGenerico`) NO cuentan.

---

## BLOQUES 13, 14, 15, 16: Reglas Adicionales de Gradle y Testeo
* **Check 13.1: JPA + WebFlux.** No deben convivir en el mismo `build.gradle` starter JPA y WebFlux (usar Spring MVC si hay base de datos relacional). Matches -> **FAIL HIGH**.
* **Check 14.1: Spring Boot Starter Validation.** Debe estar presente `spring-boot-starter-validation` en dependencias de `build.gradle`. Faltante -> **FAIL HIGH**.
* **Check 15.1: Sin setter de mensajeNegocio.** En mappers de error de infraestructura, prohibido invocar `setMensajeNegocio("...")` con texto literal (ver 5.5b). Matches -> **FAIL HIGH**.
* **Check 15.2: Formato de Recurso.** El campo `recurso` en mappers de error debe llevar slash-prefix (ej: `/servicio/operacion`). Formato inválido -> **FAIL MEDIUM**.
* **Check 15.3: Nombre del componente.** `setComponente` en mappers de error debe ser exactamente el nombre canónico del microservicio del `catalog-info.yaml`. Desviaciones -> **FAIL MEDIUM**.
* **Check 15.4: Código backend.** `setBackend` en mappers de error debe ser el código del catálogo (ej: `00045`). Desviaciones -> **FAIL HIGH**.
* **Check 16.1: Anotación de tests.** Clases de pruebas unitarias deben tener anotación adecuada de contexto.

---

## BLOQUE 17: Log Transaccional en Orquestadores (ORQ)
* **Check 17.1: lib-event-logs presente.** (ORQ) Debe declarar la librería de log transaccional del banco en `build.gradle`. Faltante -> **FAIL HIGH**.
* **Check 17.2: Configuración en application.yml.** (ORQ) Bloque `logging.event.mode` configurado en `EXTERNAL` y propiedades de kafka activas. Faltante -> **FAIL HIGH**.
* **Check 17.3: Kafka bootstrap.** (ORQ) Servidores de kafka mapeados a variables de entorno oficiales. Faltante -> **FAIL HIGH**.
* **Check 17.4: EventAudit en Adapters.** (ORQ) Al menos un adaptador de infraestructura debe usar `@EventAudit`. Faltante -> **FAIL HIGH**.

---

## BLOQUE 18: Log Transaccional Prohibido en WAS/BUS
* **Check 18.1: Sin lib-event-logs.** En servicios WAS/BUS, no debe declararse `lib-event-logs` en `build.gradle`. Si existe -> **FAIL HIGH**.
* **Check 18.2: Sin config transaccional en yml.** En WAS/BUS, no deben existir configuraciones de `logging.event` ni kafka en `application.yml`. Si existen -> **FAIL HIGH**.
* **Check 18.3: Sin EventAudit en Java.** En WAS/BUS, no debe haber anotaciones `@EventAudit` en clases Java (traslado a modo informativo). Si existen -> **FAIL INFO** (no bloquea pipeline).

---

## BLOQUES 19, 20, 21, 22: Integración y Entorno
* **Check 19.1: Propiedades de entorno.** Propiedades en yml limpias de secretos.
* **Check 20.1: Sin referencias legacy en ORQ.** Un ORQ migrado no debe invocar o referenciar URLs del legacy `sqb-msa-<svc>` o `ws-<svc>-was` (debe usar endpoints migrados). Matches -> **FAIL HIGH**.
* **Check 21.1: Configuración de circuit breaker.** Circuit breaker configurado según lineamientos de capacidad.
* **Check 22.1: Puerto expuesto.** Puerto expuesto en properties y configurado en puerto dinámico para el contenedor de Kubernetes.
