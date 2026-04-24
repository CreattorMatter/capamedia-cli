# Capa Media OLA1 - Banco Pichincha

## Proyecto
Migracion de servicios legacy a Java 21 + Spring Boot + arquitectura hexagonal OLA1.

**Fuentes legacy soportadas:**
- **IIB** (IBM Integration Bus) — ESQL + SOAP/WSDL + msgflow + MQ
- **WAS** (WebSphere Application Server) — Java/JAX-WS + típicamente Oracle
- **ORQ** (Orquestadores) — IIB orchestrators que delegan a otros servicios; análisis liviano

**Matriz MCP oficial (mandatoria, sin excepciones):**

> **Fuente única**: canonical [`bank-mcp-matrix.md`](bank-mcp-matrix.md) — 5 parámetros + 3 reglas de override + 8 casos canónicos. Espejo directo del PDF `BPTPSRE-Modos de uso`. Si hay discrepancia con otro archivo, prevalece el canonical.

**Resumen operativo (detalle en el canonical)**:
- **Regla 1**: `invocaBancs=true` → REST + WebFlux (override total).
- **Regla 2**: `deploymentType=orquestador` → REST + WebFlux + `lib-event-logs`.
- **Regla 3**: `projectType=soap` + microservicio → SOAP + Spring MVC + `spring-web-service`.
- **Caso base WAS 1 op**: REST + Spring MVC (sin regla especial).

**Scaffold inicial:** lo genera el **Fabrics MCP del Banco Pichincha** vía cuestionario. La migración parte desde ese scaffold; no se reconstruye desde cero.

**Secrets:** NUNCA buscar/inventar. Referenciar como `${CCC_*}` env vars en `application.yml` y `helm/*.yml`. El banco provee valores reales ~1 semana antes del deploy productivo.

**SonarLint local:** todo proyecto migrado debe tener `.sonarlint/connectedMode.json` versionado apuntando a la organización `bancopichinchaec` en SonarCloud. Setup detallado en `configuracion-claude-code/sonarlint/README.md`. Validado por la checklist post-migración (BLOQUE 14).

**Estructura de error oficial (PDF BPTPSRE):** el bloque `<error>` tiene 8 campos. `mensajeNegocio` lo setea DataPower (NUNCA el servicio — pasar null). `recurso` = `<artifactId>/<método>`. `componente` tiene reglas diferentes para IIB (`<SERVICIO>` / `ApiClient` / `TX\d{6}`) vs WAS (`<SERVICIO>` / `<MÉTODO>` / `<VALOR_ARCHIVO_CONFIG>`). Validado por checklist BLOQUE 15.

**Librerías internas opcionales (solo WebFlux/REST):**
- `mdw-dm-lib-audit-log-reactive` — auditoría vía Kafka; anotaciones `@LogAudit` (controller) y `@LogAuditStep` (service/adapter).
- `mdw-dm-lib-stratio-connector` — cliente reactivo contra RDM (Stratio); `StratioQueryExecutor.retrieveMono/Flux`; OAuth2 Cas Operacional + opcional Redis para cache de token.
- Ambas requieren Spring Boot 3.4.2+ y están descritas en detalle en el prompt REST.

**Patrones legacy IIB de configuración:**
- `GestionarRecursoXML('carpeta', 'archivo', ...)` → archivos XML en repos `sqb-cfg-<archivo>-<carpeta>` (ej: `sqb-cfg-codigosBackend-config`, `sqb-cfg-errores-errors`) — ya commiteados en este repo.
- `GestionarRecursoConfigurable('OmniServiceConfig', ...)` → servicios configurables cacheados en `Environment.cache.<Name>`; origen histórico: XLSX en SharePoint. **Fuente operativa en este repo:** `prompts/ConfigurablesBusOmniTest_Transfor(ConfigurablesBusOmniTest_Transf).csv`. Resolver allí los campos usados y poblar `application.yml` / Helm. Solo dejar `TBD` si el configurable o el campo no existe en el CSV local.

**Patrones legacy WAS de configuración:**
- Properties: `/apps/proy/OMNICANALIDAD_SERVICIOS/conf/{<servicio>,generalServices,CatalogoAplicaciones}.properties`
- Clases Java a inspeccionar: `Propiedad.java` (reader), `ErrorTipo.java` (enum tipo), `ServicioExcepcion` (origen de componente)

## Build & Test
```bash
# bloque_estricto_a_copiar
./gradlew generateFromWsdl      # Generar clases JAXB desde WSDL
./gradlew clean build            # Build completo con tests
./gradlew test                   # Solo tests
./gradlew jacocoTestReport       # Reporte de cobertura
./gradlew bootJar                # Generar JAR para Docker
```

## Arquitectura: Hexagonal OLA1
```
application/
  port/input/    <- interfaces (NUNCA abstract classes)
  port/output/   <- interfaces (NUNCA abstract classes)
  service/       <- SOLO @Override de interfaces (CERO metodos privados)
  util/          <- Helpers extraidos: validaciones, normalizaciones, formateos
domain/
  model/         <- Records puros, CERO imports de Spring
  exception/     <- Excepciones tipadas
infrastructure/
  input/adapter/ <- SOAP controller, DTOs envelope
  output/adapter/<- BANCS adapters via Core Adapter REST
  config/        <- @Configuration, @ConfigurationProperties
  mapper/        <- MapStruct o @Component mappers
  exception/     <- ErrorResolverHandler
```

## Reglas criticas (NUNCA violar)
- **Variables de configuracion (MANDATORIO):** TODA variable leida por el servicio legacy o sus UMPs/dependencias (`.properties`, `Constantes.java`, `Propiedad.get()`, `Environment.cache.*`, `GestionarRecursoConfigurable`, `GestionarRecursoXML`) DEBE tener su entrada en `application.yml`. Valores funcionales van como literal o con default inline. Secrets van como `${CCC_*}` con entrada en los 3 helms. NUNCA inventar valores — solo del codigo legacy o archivos config disponibles. Si el archivo no esta disponible, documentar la clave en comentario YAML: `# valor no disponible — obtener de <fuente>`. Solo poner en Helm las `${CCC_*}` que se usen en `application.yml`.
- Ports son INTERFACES, nunca abstract classes
- domain/ no importa Spring, SOAP, JPA, WebFlux
- application/ no importa infrastructure/
- CERO @Autowired — solo @RequiredArgsConstructor
- Metodos max 20 lineas, lineas max 100 columnas
- @Slf4j en todas las clases con comportamiento
- HTTP 200 para errores de negocio (compatibilidad IIB)
- HTTP 500 solo para SOAP Faults inesperados
- Todo el codigo en INGLES
- Config via ${CCC_*} env vars, NUNCA hardcodear
- livenessProbe + readinessProbe en TODOS los Helm values
- Produccion: replicaCount >= 2, hpa.enabled: true
- **Service Purity:** services SOLO contienen @Override de la interfaz del input port. CERO metodos privados (validaciones, normalizaciones, formateos). Extraer a `application/util/<Domain>*Helper.java`

## Referencia de patrones
Las reglas canonicas del banco viven en este mismo contexto (hexagonal, bancs,
bank-official-rules, code-style, etc.). NO copiar de un servicio-ejemplo;
aplicar las reglas como estan definidas aqui. Los patrones del banco evolucionan
y un servicio migrado el mes pasado puede tener gaps que ya se resolvieron.

## Flujo de trabajo
1. `/pre-migracion <ruta>` — Detecta tipo (IIB / WAS / ORQ) y genera ANALISIS_*.md
   - IIB o WAS -> usa `pre-migracion/01-analisis-servicio.md`
   - ORQ (orquestador) -> usa `pre-migracion/01-analisis-orq.md` (análisis liviano)
2. `/migrar` — Ejecuta migracion con autocorreccion segun matriz MCP:
   - BUS (IIB) + invocaBancs -> usa `migracion/REST/02-REST-migrar-servicio.md` (WebFlux, 1 o N ops)
   - WAS con 1 operacion -> usa `migracion/REST/02-REST-migrar-servicio.md` (MVC)
   - WAS con 2+ operaciones -> usa `migracion/SOAP/02-SOAP-migrar-servicio.md` (MVC)
   - ORQ (orquestador) -> usa `migracion/REST/02-REST-migrar-servicio.md` (WebFlux)
3. `/post-migracion` — Audita el proyecto migrado contra la checklist (`post-migracion/03-checklist.md`), genera reporte pass/fail por bloque (incluye BLOQUE 13 si hay JPA/HikariCP)

## Commits
Conventional Commits: `feat|fix|refactor|test|docs|chore|ci|iac: descripcion`

@prompts/pre-migracion/01-analisis-servicio.md
@prompts/pre-migracion/01-analisis-orq.md
@prompts/migracion/REST/02-REST-migrar-servicio.md
@prompts/migracion/SOAP/02-SOAP-migrar-servicio.md
@prompts/post-migracion/03-checklist.md
