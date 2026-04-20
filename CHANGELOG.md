# Changelog

Todos los cambios notables en `capamedia-cli` estan documentados aqui.
Formato basado en [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning [SemVer](https://semver.org/lang/es/).

## [0.2.4] - 2026-04-20

### Fixed - 4 mitigaciones de descubrimientos del día anterior

Todas las mitigaciones se integraron al flujo de `fabrics generate`. Ahora el
comando **termina el proyecto end-to-end** con clases JAXB generadas.

**Fix #5 — Workaround para bug del MCP en Windows** (el MCP corre `gradlew.bat`
sin prefijo `.\\` y falla). Mi CLI ahora detecta el error y corre el paso por
su cuenta con:
- Path absoluto al wrapper (no depende del exec resolution)
- `shell=True` en Windows, `chmod 0o755` en Unix
- `--no-daemon` para evitar cache sucio de daemon previo
- Clean previo de `.gradle/` y `build/` del proyecto

**Fix adicional descubierto mientras probaba el #5:**
- **schemaLocation externos** (`../TCSProcesarServicioSOAP/GenericSOAP.xsd`)
  pre-procesados automaticamente: mi CLI trae un `GenericSOAP.xsd` embebbed
  (`data/resources/GenericSOAP.xsd`) y lo copia al destino + arregla el
  schemaLocation para apuntar local.
- **Auth Azure Artifacts al gradlew**: inyecto `ARTIFACT_USERNAME`/
  `ARTIFACT_TOKEN` desde `.mcp.json` al env del subprocess (gradlew necesita
  bajar plugins del feed privado del banco).
- **Java 21 forzado** en `gradle.properties` (`org.gradle.java.home=...` con
  forward slashes). Gradle 8.x no soporta Java 25+, pero si el PATH tiene Java
  25 por default, hay que sobrescribir.

**Fix #4 — Validacion de schema MCP en runtime.** Antes de invocar el tool:
- Llamamos `tools/list` y buscamos `create_project_with_wsdl`
- Comparamos `required` del schema contra `KNOWN_MCP_PARAMS` del CLI
- Si hay params required desconocidos, abortamos con guia al user
- Si hay params opcionales nuevos, warning (no bloqueante)
- Removemos del payload params que el MCP no conoce (tolerancia)

**Fix #3 — `capamedia fabrics setup --refresh-npmrc`**. Actualiza `~/.npmrc`
con el token base64-encoded para que `npx @pichincha/fabrics-project` pueda
bajar el paquete. Preserva lineas no-relacionadas con el feed. `capamedia
install` ahora tambien reporta si el MCP esta cacheado.

**Fix #1 — Doc de inconsistencia de naming**. Nota en `mcp_launcher.py`:
npm package = `@pichincha/fabrics-project`; MCP server interno =
`azure-project-manager`; tool = `create_project_with_wsdl`. Los tres son el
mismo componente.

### Added
- `GenericSOAP.xsd` embebbed como recurso del CLI en `data/resources/`
- Funcion `_find_java21_home()` para localizar Java 21 en Windows/macOS/Linux
- Funcion `_set_gradle_java_home()` que escribe `org.gradle.java.home` con
  forward slashes (evita issues de escape de backslashes en `.properties`)
- Funcion `_artifact_env_from_mcp()` que lee `ARTIFACT_TOKEN` del `.mcp.json`
  y lo inyecta al subprocess env
- Funcion `_fix_schema_locations()` que pre-procesa WSDL/XSDs con paths
  relativos externos
- Constante `KNOWN_MCP_PARAMS` con los 9 params que el CLI sabe proveer

### Testing end-to-end sobre `wsclientes0007`

Probado con workspace limpio `007b-test/`:
- `capamedia fabrics generate wsclientes0007 --namespace tnd`
- **MCP conectado** desde cache npx (sin depender de `.npmrc` fresco)
- **Scaffold creado** por el MCP (build.gradle, Dockerfile, Helm, etc.)
- **2 fixes de schemaLocation** aplicados automaticamente
- **Java 21 forzado** via gradle.properties (evita bug de Java 25 + Gradle 8)
- **`gradlew generateFromWsdl`** corre y termina OK
- **19 clases JAXB** generadas en `build/generated/sources/wsdl/`
- **BUILD SUCCESSFUL in 8s**

Flujo completo: del legacy clonado al scaffold con clases Java generadas, en
un solo comando, sin intervencion manual.

---

## [0.2.3] - 2026-04-20

### Added - `fabrics generate` ahora invoca el MCP y genera la carpeta destino

Antes generaba un prompt-texto para pegar en Claude Code. Ahora **invoca el MCP
Fabrics directamente** via JSON-RPC stdio y deja la carpeta `destino/` lista.

- **`core/mcp_client.py`** - cliente JSON-RPC 2.0 sobre stdio con context manager.
  Implementa `initialize`, `tools/list`, `tools/call` del protocolo MCP 2024-11-05.
  Maneja UTF-8 en ambas direcciones y drain de stderr en thread aparte.

- **`core/mcp_launcher.py`** - localiza el MCP Fabrics con dos estrategias:
  1. Cache npx local (`~/AppData/Local/npm-cache/_npx/<hash>/.../fabrics-project/dist/index.js`)
     - preferido, no requiere `.npmrc` fresco
  2. Fallback a `.mcp.json` con `cmd /c npx @pichincha/fabrics-project@latest`
  Inyecta `ARTIFACT_USERNAME` y `ARTIFACT_TOKEN` desde `.mcp.json` al env.

- **`fabrics generate`** refactorizado completo:
  - Analiza legacy clonado
  - Deduce 9 parametros del MCP (`projectName`, `projectPath`, `wsdlFilePath`,
    `groupId`, `namespace`, `tecnologia`, `projectType`, `webFramework`, `invocaBancs`)
  - Pregunta interactivamente `namespace` del catalogo (enum `tnd/tpr/csg/tmp/tia/tct`)
    o se puede pasar via `--namespace`
  - Muestra tabla con los parametros antes de invocar
  - Invoca `create_project_with_wsdl` via MCPClient
  - Maneja "exito parcial" cuando el MCP genera el scaffold pero falla en el ultimo
    paso (tipicamente `gradlew generateFromWsdl`)
  - Nuevo flag `--dry-run` para ver los parametros sin invocar
  - Nuevo flag `--group-id` (default `com.pichincha.sp`)

### Fixed

- **UTF-8 forzado en stdout/stderr** desde el arranque del CLI. Antes el output
  del MCP con emojis explotaba en Windows (cp1252). Fix en `cli.py`.
- Schema real del MCP descubierto: nombres de params corregidos
  (`wsdlFilePath` no `wsdlPath`, `projectName` no `serviceName`,
  `projectPath` no `outputDir`).
- `namespace` y `tecnologia` son params obligatorios nuevos (antes no se pasaban).

### Testing end-to-end sobre `wsclientes0007`

Probado contra MCP real (`azure-project-manager v1.0.0`):
- MCP conectado via cache npx sin dependencia de `.npmrc` fresco
- Parametros deducidos correctos (projectType=rest, webFramework=webflux,
  tecnologia=bus, invocaBancs=true)
- Arquetipo generado en `destino/tnd-msa-sp-wsclientes0007/` con: build.gradle,
  settings.gradle, gradle wrapper, Dockerfile, Helm values, Azure Pipelines,
  src/main/java/ con Application, ErrorResolver, GlobalErrorException, etc.
- Error del MCP en paso final (`gradlew generateFromWsdl`) manejado como
  "exito parcial" con guia al usuario para completarlo manual.

---

## [0.2.2] - 2026-04-20

### Changed - Scope de `clone` simplificado

Filosofia de diseño: el CLI debe saber migrar bien por si mismo, sin necesidad
de copiar cada vez desde un servicio-ejemplo. El conocimiento destilado del
0024 (REST gold) y 0015 (SOAP gold) ya vive en los prompts canonicos
(`migrate-rest-full.md`, `migrate-soap-full.md`, `checklist-rules.md`).

`capamedia clone` ahora solo trae lo especifico del servicio:

```
workspace/
  legacy/sqb-msa-<svc>/
  umps/sqb-msa-umpclientes<NNNN>/
  tx/sqb-cfg-<NNNNNN>-TX/
  COMPLEXITY_<svc>.md
```

### Removed

- `catalogs/` — se quitaron los clones de `sqb-cfg-codigosBackend-config` y
  `sqb-cfg-errores-errors`. Son catalogos globales que no cambian entre
  servicios; clonarlos 40 veces era desperdicio. Si en algun servicio hace
  falta validar un TX code contra el catalogo, el dev puede clonarlo manual.
- `gold-ref/` — se quito el clone de `tnd-msa-sp-wsclientes0024` y
  `tnd-msa-sp-wsclientes0015`. Los patrones del gold ya viven dentro del CLI.
- Flags `--skip-catalogs` y `--skip-gold` eliminadas (no aplican).
- Referencias a proyecto `tpl-middleware` (solo se usaba para gold).

### Testing

Probado sobre `wsclientes0007`: workspace queda con **solo 3 carpetas**
(legacy, umps, tx) + COMPLEXITY report. Todos los clones exitosos.
30/30 tests passed.

---

## [0.2.1] - 2026-04-19

### Added - TX repos + multi-project support

- **Clone de repos de TX individuales.** Para cada TX code detectado en los ESQL de los UMPs clonados, `capamedia clone` ahora clona el repo `sqb-cfg-<TX>-TX` (contiene el XML con el contrato request/response del TX BANCS). Ejemplo: TX `060480` -> clona `sqb-cfg-060480-TX` en `./tx/`.
- **Separacion `catalogs/` vs `tx/`.** Los catalogos comunes (`sqb-cfg-codigosBackend-config`, `sqb-cfg-errores-errors`) se clonan ahora en `./catalogs/` — antes iban mezclados en `./tx/`. El `./tx/` queda para los repos de TX especificos del servicio.
- **Multi-project support en `_git_clone`.** Parametro `project_key` permite elegir el proyecto Azure DevOps correcto segun el tipo de repo:
  - `bus` -> `tpl-bus-omnicanal` (legacy + UMPs)
  - `config` -> `tpl-integrationbus-config` (TX repos + catalogos)
  - `middleware` -> `tpl-middleware` (gold references `tnd-msa-sp-*`)
- **Reporte de complejidad enriquecido.** `COMPLEXITY_<svc>.md` ahora tiene:
  - Columna `Extraido` (SI/NO) por UMP indicando si se pudo sacar el TX de ESQL
  - Columna `Fuente` (ESQL / config externa / catalogo) para cada UMP
  - Columna `Nota` con pista de donde mirar si el TX no se pudo extraer
  - Nueva seccion "TX repos clonados" con status por cada TX (clonado / no existe / error)
- **Nueva flag `--skip-tx`** para saltear el clone de repos TX individuales.

### Fixed

- Los catalogos y el gold reference antes fallaban con `repository not found` porque estaban en proyectos Azure DevOps equivocados. Ahora cada tipo apunta al proyecto correcto.

### Testing end-to-end

Probado sobre `wsclientes0007` real:
- 5 UMPs detectados y clonados (0002, 0003, 0005, 0020, 0028)
- 3 TX codes unicos extraidos (060480, 067050, 067186)
- 4/5 UMPs con TX desde ESQL; 1 UMP (0028) marcado como "no extraido" con nota para investigacion manual (TX vive en `Environment.cache.*Config`, no hardcoded)
- 3/3 TX repos clonados OK
- 2/2 catalogos clonados OK
- Gold reference (tnd-msa-sp-wsclientes0024) clonado OK

---

## [0.2.0] - 2026-04-19

### Added - Shell parity

Tres comandos shell que antes solo existian como slash commands del IDE:

- **`capamedia clone <servicio>`** — clonado determinista sin AI.
  - Clona el repo legacy (`sqb-msa-<servicio>`) en `./legacy/`
  - Detecta UMPs referenciados en ESQL/msgflow, los clona en `./umps/`
  - Extrae TX codes de los ESQL de los UMPs clonados
  - Clona catalogos (`sqb-cfg-codigosBackend-config`, `sqb-cfg-errores-errors`) en `./tx/`
  - Cuenta operaciones del WSDL y clona el gold reference correcto
    (REST `tnd-msa-sp-wsclientes0024` o SOAP `tnd-msa-sp-wsclientes0015`) en `./gold-ref/`
  - Genera `COMPLEXITY_<servicio>.md` con tipo de fuente (IIB/WAS/ORQ),
    framework recomendado, UMPs + TX, evidencia de BD, complejidad LOW/MEDIUM/HIGH.
  - Flags: `--shallow`, `--skip-catalogs`, `--skip-gold`, `--workspace`

- **`capamedia check [<path>] [--legacy <path>]`** — checklist BPTPSRE deterministico.
  - Corre los BLOQUES 0-14 sin AI (grep, awk, regex).
  - **BLOQUE 0** incluye cross-check legacy vs migrado: count ops, operation names, targetNamespace, XSDs referenciados.
  - Salida: tabla colorida en stdout + `CHECKLIST_<servicio>.md` con detalle por bloque.
  - Veredicto final: `READY_TO_MERGE` / `READY_WITH_FOLLOW_UP` / `BLOCKED_BY_HIGH`.
  - Exit code 1 si hay fails HIGH (o si `--fail-on-medium` y hay MEDIUM).
  - Ideal para CI/CD como gate pre-merge.

- **`capamedia fabrics generate <servicio>`** — arma el prompt para pegar en el IDE.
  - Analiza el legacy clonado, deduce `projectType` (rest/soap), `webFramework` (webflux/mvc), `wsdlPath` absoluto.
  - Escribe `FABRICS_PROMPT_<servicio>.md` con el prompt completo (parametros + workarounds de gaps conocidos + pasos).
  - Copia al clipboard automaticamente (via `pyperclip`). Flag `--no-clipboard` para solo archivo.

### Added - Infraestructura compartida

- **`core/legacy_analyzer.py`** — utilidades deterministas reusables:
  - `analyze_wsdl(path)` — count ops en `<portType>` sin duplicar por `<binding>`
  - `detect_ump_references(root)` — regex sobre ESQL/msgflow/subflow
  - `extract_tx_codes(ump_repo)` — TX codes 6 digitos con filtro de falsos positivos (fechas)
  - `detect_source_kind(root, name)` — IIB / WAS / ORQ / unknown
  - `detect_database_usage(root)` — persistence.xml, @Entity, JdbcTemplate, etc.
  - `score_complexity(ops, umps, has_db)` — LOW / MEDIUM / HIGH
  - `analyze_legacy(root, name, umps_root)` — orquesta todo

- **`core/checklist_rules.py`** — 15 bloques con ~25 checks implementados como funciones:
  - Block 0 (pre-check + cross legacy/migrado), 1 (hexagonal), 2 (logging), 5 (error handling), 7 (config externa), 13 (WAS+DB/HikariCP), 14 (SonarLint binding)

### Fixed

- `CLAUDE.md` / `AGENTS.md` ahora tienen header con `{{ service_name }}` y el flujo esperado — antes eran genéricos.
- `capamedia init --ai all` verificado con los 6 adapters — genera **89 archivos** correctamente (`.claude/` 17, `.cursor/` 14, `.windsurf/` 13, `.github/` 14, `.codex/` 10, `.opencode/` 16).

### Tests

- 30 tests totales, todos PASS (era 17 en v0.1.0).
- Nuevos: `test_legacy_analyzer.py` (6 tests), `test_checklist_rules.py` (7 tests).

---

## [0.1.0] - 2026-04-19

### Added - MVP inicial

- CLI multi-harness con 6 adapters: Claude Code, Cursor, Windsurf, GitHub Copilot, OpenAI Codex, opencode
- 4 slash commands canonicos: `/clone`, `/fabric`, `/migrate`, `/check`
- 5 prompts detallados portados desde PromptCapaMedia: `analisis-servicio`, `analisis-orq`, `migrate-rest-full`, `migrate-soap-full`, `checklist-rules`
- 4 agents, 3 skills, 5 context files
- Comandos shell: `install` (winget), `check-install`, `init` (interactivo), `fabrics setup/preflight`, `doctor`, `upgrade`
- Templates Jinja2: `mcp.json`, `sonarlint-connectedMode.json`, `CLAUDE.md`
- 17 tests PASS
