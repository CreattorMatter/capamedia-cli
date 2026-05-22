---
name: qa
title: QA - compuerta pre-QA (analisis comparativo + artefactos QA)
description: Compuerta de calidad pre-QA en dos pasos. Paso 1 - analisis comparativo legacy vs migrado que detecta toda diferencia que haria fallar QA, con veredicto go/no-go, casos de prueba y config Diffy. Paso 2 - handoff al agente qe-migration para generar los artefactos QA (criterios de aceptacion, BDD Gherkin, payloads, riesgos) bajo docs/qa/**.
type: prompt
scope: project
stage: qa
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
---

# /qa — compuerta de calidad pre-QA

Compuerta de calidad **antes de pasar a QA**, en dos pasos (flujo de fabrica
oficial del banco):

1. **Analisis comparativo pre-QA** — compara el legacy contra el migrado y
   encuentra TODA diferencia que pueda hacer que QA falle. Entrega veredicto
   go/no-go, tabla de hallazgos, casos de prueba y configuracion de Diffy.
2. **Generacion de artefactos QA** — handoff al agente `qe-migration`, que hace
   ingenieria inversa del legacy y genera criterios de aceptacion, casos BDD
   Gherkin, payloads de linea base y matriz de riesgos bajo `docs/qa/**`.

## Como invocarlo

El agente trabaja sobre el **legacy** y el **migrado** del workspace:

- Si el workspace ya tiene `legacy/` y `destino/` (por ej. tras
  `capamedia qa pack <servicio>`), usalos directamente.
- Si no, pedir una sola vez las rutas/repos del legacy y del migrado.
- Dependencias externas (subflows GenericSOAP, UMPs, JARs internos) son
  opcionales: si estan disponibles, leerlas mejora el analisis; si no, marcar
  "requiere confirmacion".

---

## Paso 1 — Analisis comparativo pre-QA

Actua como un arquitecto senior Java/integracion bancaria y QA tecnico. Tu
trabajo es encontrar TODO lo que pueda hacer que el nuevo servicio falle en QA
por responder distinto al legacy.

La salida alimenta a QA, Karate/Diffy, y la decision go/no-go.

### Descubrimiento automatico

Lee COMPLETAMENTE ambos repositorios y determina:

a) **TIPO DE LEGACY:**
   - Archivos .esql, .msgflow, .subflow → ESQL (usa guia ESQL abajo)
   - Archivos .java con @WebService, servlets, EJBs → Java antiguo (usa guia Java abajo)

b) **OPERACIONES:** Busca en WSDL (wsdl:operation), .msgflow (SOAPInput urlSelector),
   @WebService, @RequestMapping, @PayloadRoot, web.xml. Lista todas.

c) **DEPENDENCIAS EXTERNAS:** Busca en pom.xml (ZIP/iib-bar), xsd:include/import que
   apunten fuera del repo, PROPAGATE TO LABEL a subflows externos.
   Si proporcionaron repos de dependencias, leelos. Si no, marca "requiere confirmacion".

d) **SERVICIOS DOWNSTREAM:** Busca TX BANCS, URLs, DataSources, colas JMS/MQ.
   - ESQL: Environment.UMPSubflow, InvocarBancs
   - Java antiguo: RestTemplate, HttpClient, JdbcTemplate, JmsTemplate, SOAPConnection
   - Java nuevo: BancsClient, @BancsService, WebClient, JpaRepository

e) **PATRON SOAP DEL NUEVO:** ¿Como maneja SOAP?
   - @RestController + text/xml con DTOs manuales
   - @Endpoint + @PayloadRoot + MessageDispatcherServlet (Spring-WS)

f) **INTEGRACION DOWNSTREAM DEL NUEVO:**
   - BancsClient HTTP, WebClient a OCP/Stratio, JPA directo a BD Oracle, crypto adapter

Reporta hallazgos al inicio de la salida.

### Contexto del proyecto

Banco Pichincha migra ~800 servicios middleware desde IIB/ACE y Java WAS hacia
Java 21 + Spring Boot en OpenShift. Principio: migracion 1:1 funcional.
- Endpoints y contratos SOAP/REST NO cambian.
- DataPower redirige trafico del legacy al nuevo una vez validado.
- Los canales deben ver "el mismo servicio".

Stack legacy ESQL:
  IIB/ACE, ESQL, WSDL+XSD (namespace http://bpichincha.com/servicios),
  GenericSOAP.xsd (GenericHeaderIn/Out, GenericError), message flows,
  subflows empaquetados como ZIPs Maven (TCS*, UMP*).

Stack legacy Java:
  WAR/EAR en WebSphere, JAX-WS (@WebService), EJBs, JNDI,
  JARs internos del banco, properties en filesystem del servidor.

Stack nuevo:
  Java 21, Spring Boot 3.x, JAXB 4 (tipos generados desde WSDL, no en source),
  arquitectura hexagonal (application/domain/infrastructure),
  Helm charts, CCC_* env vars, Resilience4j, Karate/K6/Diffy.

### Guia de lectura — legacy ESQL

(Aplicar cuando detectes .esql, .msgflow, .subflow.)

Patrones clave:

1. CREATE COMPUTE MODULE NombreOperacion_Procesar → Main() → ValidarEntrada() → OrquestarTX()
2. Validacion: IF LENGTH(TRIM(bodyIn.campo)) <= 0 THEN → error.codigo='N', PROPAGATE TO LABEL 'et_fin'
3. Orquestacion: Environment.UMPSubflow.ump='UMPClientes00XX', PROPAGATE TO LABEL 'et_ump'
4. Exito: error.codigo='0', error.mensaje='OK'
5. Subflows externos (TCSProcesarServicioSOAP) manejan headerIn/headerOut echo y envelope SOAP

CUIDADO:
- Todo es STRING en ESQL; Java parsea a Long/BigDecimal → NumberFormatException posible
- ESQL copia campos no declarados en el XSD; Java/JAXB los ignora
- Whitespace quirks en mensajes de error (consumidores comparan strings exactos)
- Una funcion ESQL = 50-130 lineas; no omitir ramas condicionales

### Guia de lectura — legacy Java antiguo

(Aplicar cuando detectes .java con @WebService, servlets, EJBs.)

Buscar en este orden:
1. Entry point: @WebService, HttpServlet, web.xml servlet-mapping
2. Wiring: Spring XML, EJB (ejb-jar.xml, @Stateless), web.xml
3. Validaciones: if/else null/isEmpty, javax.validation, try/catch de parseos
4. Transformaciones: mappers, XSLT, BeanUtils, copia manual
5. Downstream: DAO, JdbcTemplate, RestTemplate, SOAPConnection, JMS
6. Errores: catch blocks, @ExceptionHandler, constantes, properties files, try/catch generico
7. Config: *.properties, JNDI, @Value, web.xml init-params

CUIDADO:
- Logica dispersa en clases, interceptors, filters, aspects (no como ESQL en un archivo)
- try/catch generico que traga excepciones y retorna default silencioso
- @Singleton con estado mutable (ej: cache de catalogos con refresh por timer)
- @XmlType(propOrder) define orden de serializacion; JAXB 4 sin propOrder puede cambiar orden
- JARs internos del banco con utilidades compartidas que el nuevo puede no replicar

### Checklist de trampas

Trampas descubiertas en analisis reales. Revisalas ACTIVAMENTE.

**CONTRATO:**
- T01. minOccurs/maxOccurs cambiado entre WSDL legacy y nuevo
- T02. soapAction string distinto
- T03. elementFormDefault cambiado (qualified vs unqualified)
- T04. Path del endpoint cambiado
- T05. Estructura de error con campos adicionales (mensajeNegocio, tipo, recurso, componente, backend)

**COMPORTAMIENTO:**
- T06. HTTP status distinto para errores de negocio (legacy SIEMPRE retorna 200)
- T07. headerOut no echado en rutas de error
- T08. Validaciones nuevas que el legacy NO tenia (requests antes validos ahora rechazados) — ej. longitud o patron derivado de la PROSA de `<xsd:documentation>` ("Longitud: 4") en vez de un facet formal del XSD
- T09. Parseos que tragan errores (stringToBigDecimal catch NFE → return 0)
- T10. Echo de campo del request vs downstream en la respuesta
  (legacy echa bodyIn.identificacion original; nuevo echa valor normalizado o del downstream)

**CONFIG/INFRA:**
- T11. Circuit breaker que bloquea pruebas tras pocos errores en QA
- T12. Timeouts mucho mas cortos que el legacy
- T13. ConfigMaps referenciados que no existen en cluster QA
- T14. JAXB_FRAGMENT=true omite declaracion XML

**ESQL → JAVA:**
- T15. ESQL string vs Java Long/BigDecimal → NumberFormatException
- T16. ESQL copia campos no declarados en XSD; Java/JAXB los ignora
- T17. Whitespace quirks en mensajes de error ESQL

**JAVA WAS → SPRING BOOT:**
- T18. Cache singleton vs JPA sin cache (cada request = N queries de catalogo)
- T19. Dual-schema Oracle (CONCLIENT vs CATALOGA): entidad sin @Table(schema=...) + hibernate.default_schema
- T20. Codigo de error compartido entre header y body (QA no distingue causa)
- T21. xs:dateTime canonico vs SimpleDateFormat custom (ej: yyyyMMddHHmmssSSSS)
- T22. Crypto stub passthrough/strict: datos sin cifrar en test, todo falla en prod con strict
- T23. Recurso/componente copy-paste del legacy (ops 36/37 con recurso_35)

**STACK NUEVO:**
- T24. bancs block obligatorio en validator pero opcional en XSD (canales digitales fallan)
- T25. @Table sin schema + default_schema insuficiente para multi-schema
- T26. Mapper del nuevo prefiere valor downstream sobre request original
- T27. headerOut.documento vacio pero XSD tiene hijos con minOccurs=1
- T28. Spring-WS (@Endpoint) vs @RestController: diferencias en namespace prefixes, SOAP Faults, WSDL publishing

### Areas de analisis (obligatorias)

Para cada hallazgo indica archivo:linea en ambos repos.

- **4.1 CONTRATOS** — WSDL/XSD campo por campo: minOccurs, maxOccurs, soapAction,
  endpoint path, elementFormDefault, namespaces
- **4.2 VALIDACIONES** — paridad de reglas: mismo campo, mismo codigo, mismo
  mensaje, mismo orden
- **4.3 TRANSFORMACIONES** — mapeos campo por campo: tipos (string vs Long),
  nulls (null vs "" vs "0"), limpieza de datos, formato de numeros
- **4.4 ERRORES** — codigos, mensajes, estructura, HTTP status, headerOut en errores
- **4.5 DOWNSTREAM** — TX ID, campos, tipos de dato, headers propagados, manejo
  de null/error/empty
- **4.6 HEADERS** — headerIn→headerOut echo, propagacion de guid/canal/usuario a downstream
- **4.7 CONFIGURACION** — timeouts, circuit breakers, URLs, ConfigMaps, CCC_* en Helm
- **4.8 SEGURIDAD** — NPE potenciales, parseos inseguros, logs con datos sensibles
- **4.9 PRUEBAS** — cobertura del nuevo vs escenarios del legacy
- **4.10 DEPENDENCIAS** — subflows/JARs externos, logica internalizada vs original

### Formato de salida

**5.1 RESUMEN EJECUTIVO**

DESCUBRIMIENTO:
- Tipo de legacy: ESQL / Java / Ambos
- Operaciones encontradas
- Dependencias externas (cuales leiste, cuales no)
- Servicios downstream detectados

EVALUACION:
- Riesgo general: Bajo / Medio / Alto / Critico
- Recomendacion: GO / GO con observaciones / NO-GO
- Top 5 riesgos para QA
- ¿Funcionalmente equivalente? Si / No / Parcial
- Que validar primero en QA

**5.2 TABLA DE HALLAZGOS**

| # | Severidad | Categoria | Hallazgo | Legacy (archivo:linea) | Nuevo (archivo:linea) | Impacto | Recomendacion |
|---|-----------|-----------|----------|------------------------|-----------------------|---------|---------------|

Severidades: Critico / Alto / Medio / Bajo

**5.3 LISTAS DETALLADAS**

1. Bugs evidentes (archivo:linea, descripcion)
2. Diferencias funcionales
3. Diferencias de contrato (campo por campo)
4. Diferencias de errores (codigo por codigo)
5. Riesgos de configuracion QA

**5.4 CASOS DE PRUEBA**

| # | Caso | Condicion | Resultado esperado | ¿Diferencia? |
|---|------|-----------|--------------------|--------------|

Incluir: happy path, cada validacion, cada error, timeout downstream, request sin header,
campos extra no declarados, listas con mas elementos que maxOccurs.

**5.5 CONFIGURACION DIFFY**

Campos a comparar estrictamente, ignorar (timestamps, guids), verificar presencia.

**5.6 CHECKLIST QA**

- [ ] URLs downstream correctas
- [ ] Timeouts alineados con legacy
- [ ] Circuit breaker revisado
- [ ] ConfigMaps existen
- [ ] Variables CCC_* configuradas
- [ ] Schemas de BD accesibles

**5.7 PREGUNTAS ABIERTAS**

Lo que NO pudiste confirmar y el equipo debe verificar.

### Quick check (5 minutos, para servicios simples)

1. ¿Path del endpoint identico?
2. ¿soapAction identico?
3. ¿headerIn/bodyIn mantienen minOccurs="1"?
4. ¿Cada validacion del legacy esta en el nuevo con mismo codigo y mensaje?
5. ¿Errores de negocio retornan HTTP 200?
6. ¿headerOut se echa siempre, incluso en errores?
7. ¿Timeouts >= al legacy?

Todo SI → GO. Algun NO → analisis completo.

### Reglas estrictas

- NO reportes diferencias cosmeticas sin impacto funcional.
- Se ESPECIFICO: archivo, clase, metodo, linea.
- Si no tenes certeza, marca "requiere confirmacion".
- Lee el legacy COMPLETO antes de comparar.
- Tipos JAXB generados (*.generated.*): infiere su estructura del WSDL.
- Prioriza PARIDAD FUNCIONAL sobre calidad de codigo.
- Si algo del legacy NO esta en el nuevo, marcalo CRITICO.
- Los consumidores NO deberian notar ninguna diferencia.

---

## Paso 2 — Handoff al agente qe-migration

Cerrado el analisis comparativo del Paso 1, invoca el agente **`qe-migration`**
para generar la bateria QA reutilizable a partir del legacy:

- Criterios de aceptacion (formato dual: simple + Gherkin), `CA-<WS>-<OP>-<NNN>`.
- Casos de prueba BDD con tecnicas ISTQB, `TC-<WS>-<OP>-<NNN>`.
- Payloads de linea base (request/response) por escenario.
- Matriz de riesgos (negocio / financiero / regulatorio / operativo).

Todo se escribe **exclusivamente** bajo `docs/qa/**`. El agente barre TODAS las
operaciones del WSDL del legacy.

Notas:
- Si el Paso 1 dio **NO-GO**, primero resolver los hallazgos criticos. Igual
  conviene generar la bateria QA para tenerla lista cuando se corrijan.
- Los hallazgos del Paso 1 (trampas T01-T28, diferencias de contrato/errores)
  son input directo para priorizar los casos de prueba del Paso 2.
