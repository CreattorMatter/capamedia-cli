---
name: qacases
title: QA Cases - desarrolla los casos de uso como tests Karate ejecutables
description: Paso 3 del pipeline QA. Consume los specs que /qa + qe-migration dejan en docs/qa/migration/<ws>/ (test-cases, karate-spec, payloads) y desarrolla los casos de uso como tests Karate .feature ejecutables dentro del microservicio migrado, ademas de preparar el proyecto (dependencia Karate, runner JUnit5, recursos de test) para correrlos con Gradle.
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
  - Edit
  - Write
  - Bash
---

# /qacases — desarrolla los casos de uso ejecutables en el microservicio

Paso 3 del pipeline QA. `/qa` produce el analisis y el diseno; **`/qacases`
convierte ese diseno en tests Karate corribles y prepara el microservicio
para soportarlos**.

Pipeline completo:

1. `/qa` Paso 1 — analisis comparativo legacy vs migrado (go/no-go).
2. `/qa` Paso 2 (`qe-migration`) — disena los casos de uso y los deja como
   specs en `docs/qa/migration/<ws>/` (test-cases, karate-spec, payloads).
3. **`/qacases`** (este comando) — desarrolla esos casos como `.feature` de
   Karate ejecutables dentro del microservicio y deja el proyecto listo para
   `gradle test`.

## Entrada

`/qacases` trabaja sobre el microservicio migrado y **consume lo que
`qe-migration` ya produjo** — NO vuelve a escribir el documento de casos de
uso, ese ya existe:

- `docs/qa/migration/<ws>/test-cases/<op>-test-cases.md` — el detalle de cada
  `TC-<WS>-<OP>-<NNN>` (Gherkin, datos de entrada, resultado esperado).
- `docs/qa/migration/<ws>/karate-spec/<op>.spec.yaml` — el spec
  machine-readable, pensado justo para este paso.
- `docs/qa/migration/<ws>/payloads/<op>-payloads.json` — los payloads baseline.
- `docs/qa/migration/<ws>/operaciones/<op>.md` — los criterios de aceptacion.

**Si esos artefactos no existen**, parar y pedir correr `/qa` primero (Paso 1
+ Paso 2). El diseno de los casos es responsabilidad de `qe-migration`;
`/qacases` solo los implementa. No inventes casos.

## Que hace

### 1. Prepara el microservicio para soportar los casos de uso

- **`build.gradle`**: agregar `testImplementation 'com.intuit.karate:karate-junit5'`
  en la version estable vigente (o la que defina el baseline del banco si lo
  define). No pinear versiones de transitivas.
- **Runner JUnit5**: una clase bajo `src/test/java/<pkg>/karate/` con
  `@Karate.Test` (o `Karate.run()`) que descubre y corre los `.feature`.
- **`src/test/resources/karate-config.js`**: `baseUrl` parametrizable por
  propiedad/env (`karate.properties['baseUrl']` o `KARATE_BASEURL`), con un
  default a `http://localhost:8080`.
- **`application-test.yml`** y/o `logback-test.xml` si el microservicio los
  necesita para levantar en modo test (perfil `test`, H2 si hay BD, etc.).
- Tocar SOLO `build.gradle` y `src/test/`. Nunca `src/main/` (codigo de
  produccion).

### 2. Desarrolla los casos de uso como `.feature` de Karate

Por cada operacion del `karate-spec`:

- Un `src/test/resources/karate/<op>/<op>.feature` con un `Scenario` por cada
  `TC-<WS>-<OP>-<NNN>` del `test-cases/<op>-test-cases.md`: happy path,
  validaciones, errores de negocio, faults SOAP, edge cases (valores limite).
- Los payloads (request / response esperada) bajo
  `src/test/resources/karate/<op>/payloads/`, tomados de
  `payloads/<op>-payloads.json`, referenciados desde el `.feature` con `read()`.
- Cada `Scenario` traza al `TC-*` y al `CA-*` que cubre (tag o comentario).
- La cantidad de `Scenario` debe coincidir con la cantidad de `TC-*` del spec.
  Si una operacion anuncia N casos, los N quedan implementados.

### 3. Verifica

- Correr `./gradlew test` (o `gradlew.bat test`). Confirmar que los `.feature`
  compilan y la suite corre.
- Si el endpoint no esta levantado, dejar los tests listos y avisar como
  correrlos (`gradle bootRun` + pasar `baseUrl`). No declarar OK inventando
  resultados.

## Reglas de Karate (obligatorias)

- URL **parametrizable**: nunca hardcodear el host. Usar `karate-config.js` +
  `karate.properties['baseUrl']`.
- SOAP: assertions con XPath — `karate.xmlPath(response, '//error/codigo')`.
- **NUNCA** usar `#(variable)` dentro de un XML/JSON leido con `read()`. El
  archivo de payload es un template fijo; parametrizar desde el `.feature`, no
  dentro del archivo leido.
- Tags semanticos por escenario (`@HappyPath`, `@ValidacionCedulaVacia`,
  `@FaultSoap`, ...) + traza al requerimiento Jira si esta disponible.
- Un `Scenario` = una intencion verificable. Sin escenarios "combo".
- Datos repetibles: mismo input -> mismo resultado, sin dependencia de orden.

## Reglas estrictas

- NO re-generar el documento de casos de uso — `qe-migration` ya lo produjo;
  `/qacases` lo consume.
- NO inventar casos que no esten en `test-cases/*.md`. Si falta cobertura,
  reportarlo como gap, no rellenar.
- NO tocar `src/main/` (codigo de produccion). Solo `build.gradle` y `src/test/`.
- Los `.feature` deben reflejar EXACTAMENTE los `expected` de los specs, sin
  suavizar diferencias funcionales.
- NO declarar OK si `gradle test` no se corrio o fallo por algo distinto al
  endpoint caido.

## Salida

- `.feature` + payloads + runner JUnit5 + `karate-config.js` bajo `src/test/`
  del microservicio migrado.
- `build.gradle` con la dependencia de Karate.
- Resumen en el chat: operaciones cubiertas, # de escenarios por tipo
  (positivo/negativo/borde/fault), resultado de `gradle test`, gaps detectados.
