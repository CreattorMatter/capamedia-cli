# Changelog

Todos los cambios notables en `capamedia-cli` estan documentados aqui.
Formato basado en [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning [SemVer](https://semver.org/lang/es/).

## [0.5.0] - 2026-04-22

### Added - Sprint 2 del plan "cero trabajo humano"

Cinco features grandes orientadas a **cero alucinaciones** + **sync automatico
del canonical** + **self-correction con error especifico**.

**Punto 2a — `capamedia canonical sync` (nuevo comando):**

- Subcomandos `canonical sync`, `canonical diff`, `canonical audit`.
- Sync lee prompts vivos de Julian (`C:/Dev/.../CapaMedia/prompts/`) y los
  compara contra el canonical del CLI (`data/canonical/`). Diff unificado por
  archivo, tabla rich, confirm, apply.
- Mapping explicito por convencion de nombres (`01-analisis-servicio.md`,
  `02-REST-migrar-servicio.md`, etc.) + fallback por nombre en `prompts/` y
  `context/`. Status: `UPDATED | NEW | ORPHAN | SKIPPED | IDENTICAL`.
- Preserva frontmatter del canonical cuando el source no lo tiene.
- Orphans NUNCA se borran (solo reportan).
- Log `.capamedia/canonical-sync/<timestamp>.log` con cada diff aplicado.
- Flags: `--dry-run`, `--yes`/`-y`, `--include "**/*.md"`.

**Punto 2b — `capamedia clone --deep-scan`:**

- Nuevo modulo `core/azure_search.py`: wrapper minimo del Azure DevOps Code
  Search API (`POST /_apis/search/codesearchresults`). Auth Basic base64.
  Detecta errores HTTP, red, timeout, JSON invalido.
- Nuevo modulo `core/dossier.py`: ejecuta queries por servicio (nombre,
  WSDL namespace, TX codes, UMPs), recolecta hits, extrae variables
  `CE_*`/`CCC_*` automaticamente del contenido de los matches.
- `DOSSIER_<svc>.md` en el workspace con tabla por seccion + resumen.
- `.capamedia/dossier-appendix.md` para inyectar al FABRICS_PROMPT y al
  prompt de batch migrate — la AI ve los valores reales y no los inventa.
- **Regla dura**: si la AI detecta referencia a ConfigMap/variable que NO
  esta en el dossier, debe reportar `NEEDS_HUMAN_CONFIG` (no inventar).
- Usa PAT de `CAPAMEDIA_AZDO_PAT` / `AZURE_DEVOPS_EXT_PAT` ya configurado.

**Punto 7a — `capamedia canonical audit`:**

- Audita cada archivo operativo del canonical (`prompts/migrate-*`,
  `context/*`, `agents/*`).
- Para cada seccion que parece regla (Rule/Regla/bullets `- **`), verifica:
  1. Tiene imperativo (`MUST`/`NEVER`/`SIEMPRE`/`NUNCA`/`PROHIBIDO`)?
  2. Tiene ejemplo negativo (`// NO`/`// BAD`/`// WRONG`)?
- Tabla rich con gaps por archivo + flag `--verbose` para titulos sin
  imperativo/ejemplo. Reduce alucinaciones: lo que no tiene MUST/NEVER
  explicito es un vector de ambiguedad para la AI.
- **Baseline actual**: 7 reglas sin imperativo, 23 sin ejemplo NO.

**Punto 7b — inyeccion de catalogos en FABRICS_PROMPT:**

- Nuevo modulo `core/catalog_injector.py`: carga `tx-adapter-catalog.json`,
  `sqb-cfg-codigosBackend-config`, `Transacciones catalogadas Dominio.xlsx`.
- `CatalogSnapshot` con mapeos TX-IIB -> TX-BANCS reales, codigos backend
  (iib=00638, bancs_app=00045), reglas de estructura de error del PDF BPTPSRE.
- `format_for_prompt(snapshot, relevant_tx=...)` renderiza bloque markdown
  para inyectar. `commands/fabrics.py::generate()` y `commands/batch.py::
  _build_batch_migrate_prompt()` lo consumen automatico.
- Si servicio usa TX no catalogada: bullet `NEEDS_HUMAN_CATALOG_MAPPING`.
- Evita duplicacion si el FABRICS_PROMPT previo ya inyecto el bloque.

**Punto 7e — self-correction con error especifico:**

- Nuevo modulo `core/self_correction.py`: `extract_failure_context()` lee
  logs del engine previo + CHECKLIST.md + state.json, arma `FailureContext`
  con `build_errors`, `checklist_violations`, `stdout_tail`, `stderr_tail`.
- `build_correction_appendix(ctx, base_prompt)` adjunta al prompt del
  retry un bloque "INTENTO N (correccion automatica)" con:
  1. Categoria del fallo (`build | checklist | timeout | rate_limit`).
  2. Cada violation con `check_id`, `evidence`, `hint` del registry autofix.
  3. Tail del stdout/stderr (~50 lineas).
  4. Instrucciones: "corregi ESPECIFICAMENTE estos fallos, no re-migrar".
- `_run_service_with_retries` inyecta el context en iteraciones > 0.

### Testing

- **239/239 tests PASS** (vs 164 baseline v0.4.0). Nuevos:
  - `test_canonical_sync.py` (13): IDENTICAL, UPDATED, NEW, ORPHAN, fm preserv,
    dry-run, unmapped skip, context mapping.
  - `test_azure_search.py` (10): auth header, endpoint, HTTP error, network,
    JSON parse, SearchHit extraction.
  - `test_dossier.py` (9): build happy path, CE/CCC extract, error graceful,
    cap TX/UMP, render md, render appendix, write file.
  - `test_canonical_audit.py` (6): split sections, imperative detection,
    gaps, non-rule skip, bullet rules.
  - `test_catalog_injector.py`: load con todas las fuentes, graceful fallback,
    filter por relevant_tx, integracion con prompts.
  - `test_self_correction.py`: extract context, correction appendix, retry
    loop integration.
- `ruff check` limpio en todos los archivos nuevos (engine, scheduler,
  azure_search, dossier, canonical.py, los del sprint 1).

### Pendiente para v0.6.0 y mas alla

- Regla explicita en canonical: "Service > 200 LOC o > 4 responsabilidades
  debe extraer utils a `util/<Concern>NormalizationUtil.java`" (SRP como
  MUST/NEVER con ejemplo negativo). Hoy el patron sale por estilo del
  prompt, no por regla explicita.
- Auto-fix de refactor SRP (semantico, no regex). Proximo sprint: integrar
  LSP/JavaParser para detectar Service gordo y proponer extraccion.
- Metricas historicas agregadas (tokens por servicio, tasa de convergencia).

---

## [0.4.0] - 2026-04-22

### Added - Engine abstraction + rate limit defensivo + autofix + dashboard

**Sprint 1 del plan "cero trabajo humano" (Julian 2026-04-22).**

**`core/engine.py` — Claude + Codex + auto-detect (punto 1):**

- Nueva abstraccion `Engine` con dos implementaciones:
  - **`ClaudeEngine`** via `claude -p` (Claude Code CLI, suscripcion Max)
  - **`CodexEngine`** via `codex exec` (ChatGPT Plus/Pro, preserva comportamiento v0.3.8)
- Ambos consumen de la **suscripcion del usuario**, NO de tokens API pagos.
- Auto-detect con prioridad Claude > Codex. Flag `--engine claude|codex|auto`
  en `batch migrate` y `batch pipeline`. Env var `CAPAMEDIA_ENGINE`.
- `EngineResult` uniforme con `rate_limited: bool` y `retry_after_seconds`.
- Deteccion de rate limit por regex sobre stderr/stdout (`429`, `rate_limit`,
  `quota exceeded`, `retry-after: N`, etc.).
- Nuevo comando **`capamedia batch engines`** lista los engines disponibles.

**`core/scheduler.py` — BatchScheduler (puntos 6a + 6c):**

- Throttle proactivo con `--max-services-per-window N` (0=off) y
  `--window-hours H` (default 5h, coincide con Claude Max).
- Pausa reactiva global cuando el engine reporta `rate_limited=True`.
  Respeta `retry-after` si lo parsea, sino usa `default_rate_limit_pause`.
- Thread-safe con `threading.Condition`. Sin configurar, es passthrough.

**`core/autofix.py` — registry HIGH+MEDIUM (punto 3):**

- 8 fixes deterministicos (regex + edit, sin AI) para los checks BPTPSRE
  autofixeables: `1.3`, `2.2`, `5.1`, `15.1`, `15.2`, `15.3`, `15.4`.
- Flag `--auto-fix` en `capamedia check`: loop hasta 3 rondas o 0 HIGH/MEDIUM
  autofixeables. Lo que no converja se marca `NEEDS_HUMAN`.
- Escribe `.capamedia/autofix/<timestamp>.log` con before/after.

**`core/dashboard.py` — barras rich (punto 5):**

- `capamedia batch watch --rich` (default en TTY) con `rich.live.Live`.
- Barra por servicio (fase → %), agregada con total + ETA + success rate.
- Fallback ASCII automatico en Windows consolas legacy (cp1252).
- Footer con engine usado, iter avg, success rate.

**Canonical clean-up (punto 4):**

- `context/code-style.md`: `*Port.java (abstract class)` → `(interface)`.
  El resto del canonical ya estaba correcto en v0.3.1.

**Backward compatibility:**

- `--codex-bin` sigue funcionando (ahora como binario del CodexEngine).
- `--unsafe` existe en ambos engines (bypass de approvals/sandbox).
- Prompts + scaffolds de MCP Fabrics no cambian.

### Testing

- **164/164 tests PASS** (vs 81 baseline de v0.3.8):
  - `test_engine.py` (nuevo, 23 tests): rate limit detection, JSON extraction,
    select_engine con auto-detect, is_available con binarios reales y mocks.
  - `test_scheduler.py` (nuevo, 8 tests): throttle, pausa reactiva,
    thread-safety bajo contencion.
  - `test_autofix.py` (nuevo, 19 tests): cada fix individual + e2e.
  - `test_dashboard.py` (nuevo, 22 tests): snapshot, aggregate, render.
  - `test_batch.py` (17 actualizados): fake engine en vez de monkeypatch
    de `subprocess.run`.
- `ruff check` limpio en todos los archivos nuevos.

### Pendiente para v0.5.0 (Sprint 2 del plan)

- Punto 2a: `capamedia canonical sync` con prompts de CapaMedia.
- Punto 2b: `clone --deep-scan` con Azure DevOps Code Search API.
- Punto 7a: auditoria MUST/NEVER del canonical completo.
- Punto 7b: inyeccion de catalogos (tx-adapter-catalog.json, xlsx) al FABRICS_PROMPT.
- Punto 7e: self-correction con error especifico en retry (no solo "retry").

---

## [0.3.8] - 2026-04-21

### Added - Bootstrap unattended + cierre cross-platform para batch

**`capamedia auth bootstrap`** nuevo comando para preparar una maquina de corrida:

- Registra Fabrics en `~/.mcp.json` o `./.mcp.json` sin prompts (`--scope global|project`)
- Puede refrescar `~/.npmrc` automaticamente para Azure Artifacts
- Autentica Codex CLI por API key usando `codex login --with-api-key`
- Opcionalmente escribe un `auth.env` con `CAPAMEDIA_ARTIFACT_TOKEN`, `CAPAMEDIA_AZDO_PAT`, `OPENAI_API_KEY`

Esto deja una Mac o runner lista para `batch pipeline` sin depender de pasos interactivos
salvo el binding de Sonar.

**Azure DevOps unattended auth** en `clone.py`:

- `capamedia clone` y todos los batch que lo reutilizan ahora aceptan PAT por env:
  - `CAPAMEDIA_AZDO_PAT`
  - `AZURE_DEVOPS_EXT_PAT`
- El clone inyecta `http.extraHeader=Authorization: Basic ...` via `GIT_CONFIG_*`
  para no exponer el PAT en la linea de comando y evitar prompts (`GIT_TERMINAL_PROMPT=0`)

**Fabrics cross-platform:**

- `fabrics setup` y el template `.mcp.json` pasan a registrar Fabrics con:
  - `command: "npx"`
  - `args: ["-y", "@pichincha/fabrics-project@latest"]`
- `core/mcp_launcher.py` ya no asume solo `~/AppData/Local/npm-cache`; ahora busca
  tambien en `~/.npm/_npx` y respeta `npm_config_cache` / `NPM_CONFIG_CACHE`

**Toolchain / check-install:**

- `capamedia install` ahora instala **Codex CLI** via `npm install -g @openai/codex`
- `capamedia check-install` valida:
  - `codex --version`
  - `codex login status`
  - Azure DevOps auth por env o Git Credential Manager
  - Fabrics con el mismo preflight real que usa `batch pipeline`

**Release automation:**

- Nuevo workflow `ci.yml` corriendo tests en Windows, macOS y Linux
- Nuevo workflow `release.yml` que construye `sdist/wheel`, crea GitHub Release en tags `v*`
  y publica en PyPI si `PYPI_API_TOKEN` esta configurado

### Testing

- Nuevos tests:
  - `test_auth.py` - bootstrap + env file + auth helpers
  - `test_clone.py` - clone unattended con PAT por env
  - `test_pipeline_support.py` - `.mcp.json` cross-platform + cache npm Unix
- Suite local: `81 -> 90` tests pasando
- Validado tambien:
  - `py -m capamedia_cli.cli auth bootstrap --help`
  - `py -m capamedia_cli.cli check-install --help`

## [0.3.3] - 2026-04-20

### Added - Multi-project Azure fallback + estrategia `_repo/ directo`

**Multi-project Azure DevOps con multi-pattern de naming:**

Antes el CLI solo conocia `tpl-bus-omnicanal`. Investigando en Azure se descubrieron 4 proyectos con patrones distintos:

| Project key | Proyecto Azure | Patrones de repo |
|---|---|---|
| `bus` | `tpl-bus-omnicanal` | `sqb-msa-<svc>` (IIB + UMPs + ORQs) |
| `was` | `tpl-integration-services-was` | `ws-<svc>-was`, `ms-<svc>-was` (WAS legacy) |
| `config` | `tpl-integrationbus-config` | `sqb-cfg-<TX>-TX`, `sqb-cfg-*-config` |
| `middleware` | `tpl-middleware` | `tnd-msa-sp-*`, `tia-msa-sp-*`, `tpr-msa-sp-*`, `csg-msa-sp-*` (gold/migrados) |

Nueva funcion `_resolve_azure_repo(service, dest, shallow)` en `clone.py` que itera sobre `AZURE_FALLBACK_PATTERNS`:

```python
AZURE_FALLBACK_PATTERNS = [
    ("bus", "sqb-msa-{svc}"),
    ("was", "ws-{svc}-was"),
    ("was", "ms-{svc}-was"),
    ("middleware", "tnd-msa-sp-{svc}"),
    ("middleware", "tia-msa-sp-{svc}"),
    ("middleware", "tpr-msa-sp-{svc}"),
    ("middleware", "csg-msa-sp-{svc}"),
]
```

Prueba cada combinacion hasta encontrar una que funcione. Reporta cual proyecto/patron se uso (ej. `azure: was/ws-wsclientes0091-was`).

**Estrategia 2b (NUEVA) en `local_resolver.py`: `_repo/` directo:**

Antes el resolver solo manejaba:
1. `_repo/<svc>-aplicacion` + `-infraestructura` (WAS)
2. `_repo/<svc>` (single subcarpeta)
3. `_variants/`
4. `sqb-msa-<svc>`

Ahora tambien detecta:

**2b. `_repo/` con archivos directos** (caso WSReglas0010): si `_repo/` tiene WSDL/ESQL/pom.xml/com/IBMdefined/msgflow directos sin subcarpeta, lo retorna.

**Flag `prefer_original=True` (default):** los `_variants/` (versiones migradas) ya NO se retornan por defecto — el caller espera el legacy original. Esto fuerza a clonar de Azure si solo hay variant local. Util para que `batch complexity` no tome un variant migrado como fuente de analisis.

### Testing - 26 servicios reales

Re-corrida del batch sobre los 26 servicios:
- **12 ORQ OK** (Azure tpl-bus-omnicanal)
- **11 WAS OK** (local con `-aplicacion`/`-infraestructura`)
- **2 IIB OK** (WSReglas0010 ahora detectado via _repo/ directo + WSTecnicos0006 desde Azure)
- **1 caso edge** (WSClientes0091): clonado correctamente desde `tpl-integration-services-was/ws-wsclientes0091-was` pero el repo Azure esta vacio (sin codigo, solo `.git/`). Reportado correctamente como UNKNOWN.

**Resultado:** 25/26 con tipo correcto + 1 caso edge legitimo. Cobertura efectiva ~100%.

**Tests:** 63/63 PASS (+2 nuevos en `test_local_resolver.py` para estrategia 2b).

---

## [0.3.2] - 2026-04-20

### Added - Local resolver + Domain mapping multi-adapter

**`core/local_resolver.py` — Local first, Azure fallback:**

`capamedia clone` y `capamedia batch complexity` ahora buscan el legacy del servicio
**localmente en `<CapaMedia>/<NNNN>-<SUF>/legacy/_repo/...` antes de clonar de Azure**.

Estrategias de busqueda local (en orden):
1. `<NNNN>-<SUF>/legacy/_repo/<svc>-aplicacion` + `-infraestructura` (WAS clasico) -> retorna el `_repo/` padre
2. `<NNNN>-<SUF>/legacy/_repo/<svc>` (single repo)
3. `<NNNN>-<SUF>/legacy/_variants/*<svc>*` (variant migrado)
4. `<NNNN>-<SUF>/legacy/sqb-msa-<svc>` (clone CLI standar)
5. `<NNNN>-<SUF>/legacy/` (legacy directo, sin subdir)

Mapeo de prefijo de servicio -> sufijo de carpeta:
- WSClientes -> WSC, WSCuentas -> WSCU, WSReglas -> WSR, WSTecnicos -> WST,
  WSTarjetas -> WSTa, WSProductos -> WSP, ORQ* -> ORQ.

**`core/domain_mapping.py` — Adapters por dominio de UMP:**

**Cambio conceptual importante:** los adapters NO se nombran segun el WS del legacy,
sino segun el **dominio de los UMPs invocados**. Un mismo servicio puede invocar UMPs
de varios dominios y necesita 1 adapter por cada uno.

Mapeos:
- `UMPClientes*` -> `Customer` (CustomerOutputPort, CustomerBancsAdapter)
- `UMPCuentas*` -> `Account`
- `UMPSeguridad*` -> `Security`
- `UMPReglas*` -> `Rules`
- `UMPTecnicos*` -> `Technical`
- `UMPTarjetas*` -> `Card`
- `UMPProductos*` -> `Product`
- `UMPTransferencias*` -> `Transfer`
- `UMPPagos*` -> `Payment`
- `UMPAutorizaciones*` -> `Authorization`
- `UMPNotificaciones*` -> `Notification`
- (otros) -> `Generic`

API publica:
- `get_domain(service)` -> Domain del WS/ORQ
- `get_ump_domain(ump_name)` -> Domain del UMP
- `domains_for_umps(umps_list)` -> lista de Domains distintos requeridos
- `umps_grouped_by_domain(umps_list)` -> dict {Domain: [UMPs del dominio]}

**Check 1.4 del checklist actualizado:**

Antes: "1 solo output port Bancs". Ahora: **"1 output port por dominio de UMP invocado"**.
Si `CheckContext.ump_domains` esta poblado, valida que la cantidad y nombre de los
output ports coincida con los dominios esperados.

**Reporte de batch complexity enriquecido:**

Nueva columna `dominios` en la tabla: muestra los dominios distintos del servicio
en formato `Customer+Security+Account` (concatenados con `+`).

**Prompts de migracion actualizados:**

`migrate-rest-full.md` y `migrate-soap-full.md` ahora documentan al inicio la tabla
de mapeo prefijo UMP -> dominio, con ejemplos concretos.

### Testing

- **61/61 tests PASS** (+17 nuevos en `test_domain_mapping.py` y `test_local_resolver.py`)
- Probado batch complexity sobre los 26 servicios reales del usuario:
  - 12 ORQs OK desde Azure (`tpl-bus-omnicanal`)
  - 11 WS detectados localmente (estructura WAS con `-aplicacion`/`-infraestructura`)
  - 2 WS clonados desde Azure (los que SI estan ahi)
  - 1 WS no encontrado en ningun lado (heuristica de busqueda incorrecta)

### Pending - WS legacy en Azure

Los WS-WAS legacy (WSClientes0010, etc.) NO estan en `tpl-bus-omnicanal`. Necesitamos
que el usuario confirme cual proyecto Azure los aloja para agregar fallback ahi.

---

## [0.3.1] - 2026-04-20

### Changed - Regla canonica: ports son **interfaces** (no abstract classes)

Confirmado por usuario: la regla oficial es ports como **interface**. Cambios:

- **Check 1.3 del checklist invertido**: ahora FAIL si encuentra `public abstract class .*Port` (antes era al reves).
- **`prompts/migrate-soap-full.md`**: ejemplo de `CustomerOutputPort` cambiado a `interface` + adapter `implements` en vez de `extends`.
- **`agents/migrador.md` + `agents/validador-hex.md`**: actualizados para reflejar la regla.
- **`prompts/check.md`**: descripcion del BLOQUE 1 actualizada.
- **wsclientes0007 migrado** (007-test/destino): ports y service/adapter convertidos a interface/implements.

### Added - SQL Server soportado en HikariCP/JPA

`prompts/migrate-soap-full.md` Rule 4.1 ahora documenta los **dos engines de DB** soportados por el banco:
- **Oracle**: driver `com.oracle.database.jdbc:ojdbc11`, dialect `OracleDialect`
- **SQL Server**: driver `com.microsoft.sqlserver:mssql-jdbc`, dialect `SQLServerDialect`

Aclaracion: HikariCP aplica solo cuando legacy es **WAS** con DB. IIB/BUS no usan DB.

### Added - Caveats honestos en COMPLEXITY_*.md

Nuevo modulo `core/caveats.py` que detecta situaciones que requieren intervencion manual:

- **`ump_not_cloned`** — UMP referenciado en ESQL pero el repo no esta en `tpl-bus-omnicanal`
- **`tx_not_extracted`** — UMP clonado pero el TX vive en config externa (no `'XXXXXX'` literal)
- **`non_bancs_call`** — invocaciones SOAP non-BANCS detectadas (label `et_soap`)
- **`external_endpoint`** — URLs HTTP externas al banco (Equifax, SRI, providers)
- **`orq_dep_missing`** — para ORQ: servicios delegados que aun no estan migrados

Cada caveat tiene `kind`, `target`, `detail`, `suggested_action`, `evidence`.

`COMPLEXITY_<svc>.md` ahora incluye:
- Seccion **"Caveats detectados"** con summary por tipo + tabla detallada
- Seccion **"Dependencias ORQ"** (solo si el servicio es orquestador) listando los servicios delegados

### Added - Soporte `.xlsx` y `.csv` en `batch --from`

`capamedia batch <cmd> --from services.xlsx --sheet "Servicios"` ahora funciona ademas
de `.txt` y `.csv`. Detecta header automatico ("servicio", "service", "name", "nombre").

Dependencia nueva: `openpyxl>=3.1.0`.

### Testing

- **44/44 tests PASS** (+9 nuevos en `test_caveats.py`)
- wsclientes0007 reverificado: ports convertidos a interface, build verde, `READY_WITH_FOLLOW_UP`
- caveats funcional sobre wsclientes0007: detecta el `tx_not_extracted` de UMPClientes0028

---

## [0.3.0] - 2026-04-20

### Added - Batch mode + BLOQUE 15 del checklist

**Batch mode (procesar N servicios en paralelo):**

- **`capamedia batch complexity --from services.txt --workers 4 [--shallow] [--csv]`**
  - Clone superficial del legacy de cada servicio + analisis determinista
  - ThreadPool con N workers (default 4)
  - Output: tabla stdout + `batch-complexity-<timestamp>.md` (y opcional `.csv`)
  - Columnas: tipo, ops, framework, umps, bd, complejidad

- **`capamedia batch clone --from services.txt --workers 4 [--shallow]`**
  - Clone completo (legacy + UMPs + TX) de N servicios en paralelo
  - Cada servicio queda en `<root>/<service>/`

- **`capamedia batch check <root> --glob "*/destino/*" --workers 4`**
  - Audita todos los proyectos Spring Boot migrados bajo un path
  - Auto-descubre el legacy hermano (`../legacy/`)
  - Tabla agregada: servicio, verdict, pass, HIGH, MEDIUM, LOW
  - Ideal para dashboard del frente ("como estan los 40 servicios hoy")

- **`capamedia batch init --from services.txt --ai claude`**
  - Crea N workspaces con `.claude/` + `CLAUDE.md` + `.mcp.json` + `.sonarlint/`
  - Secuencial (no-threadsafe por CWD/prompts)

Helpers comunes:
- `_read_services_file(path)` parsea txt con soporte de comentarios `#`
- `_write_markdown_report(cmd, rows, ...)` genera reporte estructurado
- `_write_csv_report(cmd, rows, ...)` genera CSV para importar a Excel
- `_render_table()` con rich.Table coloreada

**BLOQUE 15 al checklist — Estructura de error (PDF BPTPSRE oficial):**

4 checks nuevos basados en el PDF `BPTPSRE-Estructura de error-200426-212629.pdf`:

- **Check 15.1** — `mensajeNegocio` NO debe setearse desde el codigo (lo setea DataPower). HIGH si hay `setMensajeNegocio("...")`.
- **Check 15.2** — `recurso` con formato `<NOMBRE_SERVICIO>/<METODO>`. MEDIUM si falta el `/`.
- **Check 15.3** — `componente` con valor reconocido:
  - Para IIB: `<nombre-servicio>` / `ApiClient` / `TX<6-digitos>`
  - Para WAS: `<nombre-servicio>`, `<metodo>`, `<valor-archivo-config>`
- **Check 15.4** — `backend` codes del catalogo oficial, no hardcoded arbitrario (`00045`, `00638`, `00640`...). HIGH si detecta `00000` o `999`.

### Testing

- **35/35 tests PASS** (+5 tests nuevos en `test_batch.py`)
- `batch complexity --from services.txt` probado end-to-end con 2 servicios reales
  (wsclientes0007 + wsclientes0030) — ambos analizados en paralelo
- `batch check` probado sobre el proyecto migrado en `007-test/destino/`
- `wsclientes0007` pasa de 18/18 (v0.2.4) a 20/22 PASS (v0.3.0) con 2 MEDIUM del BLOQUE 15 —
  son los esperados: mapper del controller no setea `recurso`/`componente` con los formatos oficiales

### Other

- Read en detalle los 3 PDFs nuevos del banco:
  - `BPTPSRE-Archivos de configuracion` → ya cubierto por `capamedia clone` (TX repos)
  - `BPTPSRE-Estructura de error` → integrado al BLOQUE 15 del checklist
  - `BPTPSRE-Servicios Configurables` → ya marcado TBD (fuente en SharePoint XLSX inaccesible)

---

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
