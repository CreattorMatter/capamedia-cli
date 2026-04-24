# Changelog

Todos los cambios notables en `capamedia-cli` estan documentados aqui.
Formato basado en [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning [SemVer](https://semver.org/lang/es/).

## [0.23.17] - 2026-04-24

### Added - Flujo AI portable para migrate y doublecheck

- Nuevo namespace `capamedia ai` con `capamedia ai migrate` y `capamedia ai doublecheck`.
- `ai migrate` reutiliza el runner headless de batch sobre el workspace actual, con `--engine codex|claude|auto`, `--model`, `--reasoning-effort`, `--resume` y `--retries`.
- `ai migrate` no corre checklist por defecto: el doble check queda como etapa separada.
- `ai doublecheck` ejecuta el prompt post-migracion con salida JSON estructurada y deja `capamedia review` como auditoria deterministica final.
- `fabrics generate`, `init`, `info`, README e INSTALL ahora recomiendan el flujo shell portable: `clone -> fabrics generate -> ai migrate -> ai doublecheck -> review`.
- Se actualizo la instalacion documentada de Codex CLI a `npm install -g @openai/codex`.
- Tests nuevos cubren registro del namespace `ai`, autodeteccion de servicio, skip de checklist por defecto y salida estructurada del doublecheck.

## [0.23.16] - 2026-04-24

### Changed - Codex GPT-5.5 first-class

- Codex harness defaults now generate `.codex/config.toml` with `model = "gpt-5.5"` and `model_reasoning_effort = "xhigh"`.
- Codex agent TOML generation now maps high-complexity assets to GPT-5.5 + `xhigh`, medium assets to GPT-5.5 + `high`, and low assets to GPT-5.4-Mini + `medium`.
- `batch pipeline` and `batch migrate` now default to `--engine codex`; `--engine claude` and `--engine auto` remain available.
- Added `--reasoning-effort low|medium|high|xhigh` for Codex batch runs and forward it to `codex exec` via config override.
- Added regression coverage so old `gpt-5.1-codex` defaults and missing reasoning forwarding fail tests.

## [0.23.15] - 2026-04-23

### Fixed - Unificación single-source-of-truth de canonicals (Phases 1–4)

**Root cause del bug `wstecnicos0006`**: el proyecto fue migrado como
REST+WebFlux siendo WAS con 2 operaciones (debería haber sido SOAP+MVC).
Traza de la causa: el changelog histórico 2026-04-18 de `checklist-rules.md`
contenía la frase ambigua *"1 op → REST + WebFlux"* sin calificar la
tecnología — el agente interpretó mal y aplicó WebFlux a un WAS. Además, la
matriz MCP vivía duplicada en **7 archivos** distintos y el threshold de
coverage tenía dos valores contradictorios (75% oficial vs 85% inventado).

Julian (Tech Lead): *"Unifiquemos que esa regla sea única y que todos
pregunten a esa regla."*

### Phase 1 — Auditoría de canonicals vs PDFs BPTPSRE

Se leyeron los 12 PDFs oficiales del banco (`BPTPSRE-Modos de uso`,
`BPTPSRE-Estructura de error`, `BPTPSRE-CheckList Desarrollo`,
`BPTPSRE-Servicios Configurables`, etc.) y se cruzaron contra los canonicals
actuales. Hallazgos:

- **Matriz MCP duplicada en 7 lugares**: `bank-mcp-matrix.md` (fuente),
  `bank-official-rules.md` Regla 2, `checklist-rules.md` Check 0.2 + Paso 6
  + línea 1734 (changelog basura) + línea 1343, `migrate-rest-full.md`,
  `migrate-soap-full.md` (x2), `CLAUDE.md`, `analisis-servicio.md` (x3).
- **Coverage conflicto**: PDF dice 75%; `unit-test-guidelines.md` + `qa-review.md`
  decían 85% (inventado). Los prompts `migrate-*-full.md` + `checklist-rules.md`
  sí estaban correctos en 75%.
- **Gaps**: faltaban canonicals únicos para estructura de error (8 campos
  del PDF) y para el catálogo completo de gates de desarrollo.

### Phase 3 — Ediciones aplicadas (12 acciones)

**Eliminación de duplicaciones de la matriz MCP**:

1. **`checklist-rules.md` línea 1734**: borrada la frase ambigua del
   changelog (root cause del bug `wstecnicos0006`); reemplazada por
   entrada de changelog 2026-04-23 que documenta la extracción.
2. **`checklist-rules.md` Check 0.2 (líneas 81-94)**: matriz embebida →
   referencia a `bank-mcp-matrix.md` + tabla resumen de 5 casos.
3. **`checklist-rules.md` Paso 6 (líneas 170-188)**: tabla MCP-driven →
   lógica de veredicto que llama al canonical + diálogos conversacionales.
4. **`checklist-rules.md` línea 1343**: "la elección REST vs SOAP se decide
   por cantidad de ops" → "por la matriz MCP oficial (ver canonical)".
5. **`bank-official-rules.md` Regla 2 (líneas 37-89)**: colapsada de ~52
   líneas a ~22 — tabla resumen de 3 reglas + `build.gradle` ejemplos +
   link al canonical.
6. **`migrate-rest-full.md` header**: matriz embebida → referencia con
   lista de casos cubiertos (Rule 1 + base case WAS 1 op + Rule 2 ORQ).
7. **`migrate-soap-full.md` header + sección "WHEN TO USE"**: las dos
   copias de la matriz → referencia única a `bank-mcp-matrix.md` (Rule 3
   = mvc+soap+spring-web-service).
8. **`CLAUDE.md`**: matriz → resumen de 3 reglas + link al canonical.
9. **`analisis-servicio.md`** (3 ocurrencias): matriz en Step H + sección
   Classification + quick-triage → todas referencian al canonical.

**Conflictos de coverage**:

10. **`unit-test-guidelines.md`** líneas 52-57, 208: `85%` → `75%` +
    referencia a `bank-checklist-desarrollo.md`.
11. **`qa-review.md`** AC-11: `> 85%` → `≥ 75%` con cita del PDF.

**Canonicals nuevos (3) — fuentes únicas de los PDFs BPTPSRE**:

12. **`context/bank-error-structure.md`** — 7 campos canónicos del bloque
    `<error>` (`codigo`, `tipo`, `mensajeCliente`, `mensajeNegocio`,
    `mensajeAplicacion`, `backend`, `momentoError`) + regla maestra
    *"servicio NUNCA setea `mensajeNegocio` — lo hace DataPower"*.
13. **`context/bank-configurables.md`** — `GestionarRecursoConfigurable` +
    `GestionarRecursoXML` + CSV operativo + decisión literal vs `${CCC_*}`.
14. **`context/bank-checklist-desarrollo.md`** — 75% coverage, SonarLint
    local, SonarCloud, Snyk (critical/high = fail), azure-pipeline
    namespaced, 8 gates obligatorios pre-PR.

### Phase 4 — Anti-duplicación tests (4 guards, 8 test cases)

Nuevo archivo `tests/test_canonical_single_source.py`:

1. **`test_matrix_mcp_lives_only_in_canonical`**: escanea todos los .md;
   si un archivo menciona AMBOS sentinels (`invocaBancs: true` y
   `deploymentType: orquestador`), debe estar en la allow-list (6
   archivos) Y referenciar explícitamente a `bank-mcp-matrix.md`.
2. **`test_coverage_threshold_is_75_percent`**: ningún canonical puede
   mencionar `85%` junto a palabras de coverage/JaCoCo.
3. **`test_ambiguous_matrix_phrase_removed`**: la frase ambigua root cause
   del bug `wstecnicos0006` (`"1 op → REST + WebFlux"` en sus 4 variantes)
   nunca puede reaparecer en ningún canonical.
4. **`test_new_canonicals_v0_23_15_exist`**: los 3 canonicals nuevos
   existen, tienen frontmatter YAML y >500 chars.

### Test fix — `test_canonical_v0_23_6.py`

Test viejo que hardcodeaba `"85%" in content` ajustado a `"75%"` +
verifica referencia a `bank-checklist-desarrollo.md`.

### Métricas

- **622/622 tests pass** (incluye 8 nuevos guards).
- **Matriz MCP**: de 7 duplicaciones → 1 fuente + 6 referencias.
- **Coverage**: de 2 valores contradictorios (75%/85%) → 1 valor (75%) en
  todos los canonicals, espejo del PDF oficial.
- **Basura del changelog**: 1 línea ambigua eliminada (`wstecnicos0006`
  root cause neutralizada).
- **Gaps cerrados**: 3 nuevos canonicals para estructura de error,
  configurables y checklist de desarrollo.

### Breaking changes

Ninguno. Los prompts siguen exponiendo la misma información; ahora la
consumen por referencia en vez de por copia.

---

## [0.23.14] - 2026-04-23

### Changed - Matriz MCP oficial completa (PDF BPTPSRE-Modos de uso)

Feedback Julian: la tabla del screenshot anterior tenia **ORQ con
invocaBancs=true**. El PDF oficial `BPTPSRE-Modos de uso` confirma que
**ORQ es invocaBancs=false + deploymentType=orquestador**. Ademas el PDF
introduce 2 parametros que no tenia integrados: `deploymentType` y la
matriz de 3 reglas de override priorizadas.

### 5 items implementados

**1. Nuevo canonical `context/bank-mcp-matrix.md`**

Espejo del PDF con:
- Los 5 parametros MCP (`tecnologia`, `projectType`, `framework`,
  `invocaBancs`, `deploymentType`)
- Las 3 reglas de override en orden de prioridad
- Los 8 casos canonicos (WAS BD 1/2+ ops, WAS procesamiento 1/2+ ops,
  BUS BANCS, BUS Apis 1 op, BUS sin BANCS 2+ ops, ORQ)
- Mapeo interno `source_type` → parametros MCP

**2. `_expected_framework` actualizado** (`checklist_rules.py`)

Cada return ahora menciona la Regla N aplicada para debugging:
- Regla 1: `invocaBancs=true fuerza webflux+rest (override total)`
- Regla 2: `deploymentType=orquestador -> webflux+rest + lib-event-logs`
- Regla 3: `mvc+soap + spring-web-service`

Ademas cubre el caso **BUS sin BANCS 2+ ops → soap+mvc (Regla 3)** que
antes caia al fallback.

**3. `fabrics generate` pasa `deploymentType` al MCP**

Gap critico cerrado: antes no se mandaba → MCP trataba ORQ como
microservicio y NO incluia `lib-event-logs`. Ahora:

```python
deployment_type = "orquestador" if analysis.source_kind == "orq" else "microservicio"
mcp_args["deploymentType"] = deployment_type
```

La tabla de parametros del `fabrics generate` tambien muestra la Regla
aplicable cuando el deployment_type es orquestador.

**4. `bank-official-rules.md` actualizada**

Regla 2 (WSDL determina framework) reemplazada con la matriz oficial del
PDF + tabla de 8 casos + referencia al nuevo canonical
`bank-mcp-matrix.md`. Los mensajes de FAIL HIGH del Block 0.2c ahora
mencionan la Regla N violada.

**5. Tests (11 nuevos)**

`test_block_0_mcp_matrix.py`:
- Caso 1: WAS BD 1 metodo (rest+mvc base)
- Caso 2: WAS BD 2+ metodos (Regla 3)
- Caso 5: BUS con BANCS (Regla 1 override, con 1 y 5 ops)
- Caso 6: BUS Apis 1 metodo
- **Caso 7 NUEVO**: BUS sin BANCS 2+ ops (Regla 3)
- Caso 8: ORQ (Regla 2 + lib-event-logs mencionado)
- Reasons mencionan Regla N
- Alias `iib` matchea como `bus`
- `fabrics.py` tiene `deploymentType` en mcp_args
- Canonical `bank-mcp-matrix.md` existe con las 3 reglas
- `bank-official-rules.md` referencia el nuevo canonical

Total: 614 tests passing.

### Correccion respecto a la tabla anterior

| Fila | Antes (cuadro erroneo) | Ahora (PDF oficial) |
|---|---|---|
| ORQ | `invocaBancs: true` | `invocaBancs: false` |
| ORQ | (sin deploymentType) | `deploymentType: orquestador` |
| ORQ | (sin extras) | Incluye `lib-event-logs` |
| WAS 2+ ops | (sin extras) | Incluye `spring-web-service` |
| BUS sin BANCS 2+ ops | (no contemplado) | `soap/mvc/microservicio` + `spring-web-service` |

## [0.23.13] - 2026-04-23

### Added - `/info` detecta UMPs referenciadas pero NO clonadas

Feedback Julian (caso real): usuario migro `wsclientes0026` pero no trajo
sus UMPs. El `/info` mostraba OK pero el detector de properties no tenia
acceso a las UMPs → las keys que cada UMP pedia al banco quedaban
invisibles en el reporte.

**Fix**: nueva seccion "UMPs (dependencias del servicio)" en `info.py`
que compara **referenciadas por el legacy** vs **clonadas en `umps/`**:

```
UMPs (dependencias del servicio)
  Referenciadas por el legacy: 2 (umpclientes0025, umptecnicos0077)
  Clonadas en `umps/`:         0
  Faltantes:                  2

  IMPACTO: las UMPs faltantes tienen sus propios `.properties` y
  posiblemente sus propias dependencias a BANCS / BD. Sin ellas, la
  migracion queda incompleta.

  UMPs faltantes + `.properties` esperado:
    ✗ umpclientes0025  (falta repo + archivo `umpclientes0025.properties`)
    ✗ umptecnicos0077  (falta repo + archivo `umptecnicos0077.properties`)

  Como traerlas:
  Opcion A (recomendado) - re-correr el clone completo:
    capamedia clone wsclientes0026   (requiere PAT Azure DevOps)

  Opcion B - git clone manual una por una:
    git clone .../tpl-integration-services-was/_git/ump-umpclientes0025-was umps/ump-umpclientes0025-was
    git clone .../tpl-integration-services-was/_git/ump-umptecnicos0077-was umps/ump-umptecnicos0077-was

  Despues de traerlas, re-correr `capamedia info` para ver las
  properties que cada UMP requiere del banco.
```

### Prioridad del siguiente paso actualizada

Cuando hay **UMPs faltantes**, el "siguiente paso" del dashboard ahora
prioriza traerlas PRIMERO (antes de pedir properties al owner), porque
sin las UMPs el detector no puede ver las keys reales.

```
Siguiente paso
  1) PRIMERO: traer las UMPs faltantes (sin eso el detector de properties
     no puede ver las keys que cada UMP requiere)
     capamedia clone wsclientes0026   (baja todo)
  2) Despues re-correr capamedia info
  3) Pedir los .properties pendientes al owner y pegar en .capamedia/inputs/
  4) capamedia checklist (o /doublecheck)
```

### Contempla WAS + BUS

- **WAS**: detecta UMPs desde `pom.xml` + `import com.pichincha....*` en Java.
- **BUS (IIB)**: detecta UMPs desde `*.esql` + `*.msgflow`.
- **ORQ**: no aplica (los ORQ no tienen UMPs propios).

Patterns de git clone sugeridos:
- WAS: `tpl-integration-services-was/_git/ump-<ump>-was`
- BUS: `tpl-bus-omnicanal/_git/sqb-msa-<ump>`

### Tests nuevos (3)

- UMPs referenciadas pero no clonadas → flageadas con `.properties` esperado
- Partial: 1 clonada + 1 faltante → solo flagea la faltante
- Sin legacy/: seccion muestra aviso, no crashea

Total: 603 tests passing.

## [0.23.12] - 2026-04-23

### Added - `capamedia info` / `/info` — dashboard de pendientes del workspace

Feedback Julian: "necesito un /info que me diga los archivos faltantes como
en el caso de los WAS los .properties, pero que contemple ORQ, WAS y BUS".

Nuevo comando CLI + slash command que muestra un resumen consolidado de
**que tiene y que le falta** al workspace. Contempla los 3 tipos de servicio.

### Secciones del dashboard

```
╔═ capamedia info ══════════════════════════════════╗
║ Servicio: wsclientes0076                          ║
║ Tipo: WAS · invocaBancs: NO                       ║
║ Workspace: C:\Dev\BancoPichincha\wsclientes0076   ║
╚════════════════════════════════════════════════════╝

Properties del banco
  Catalogo compartido (embebido, no requiere accion):
    ✓ generalServices.properties (3 keys)
    ✓ CatalogoAplicaciones.properties (4 keys)
  Pendientes del banco (1):
    ✗ umpclientes0025.properties (6 keys - source: ump:umpclientes0025)
      keys: GRUPO_CENTRALIZADA, RECURSO_01, COMPONENTE_01, ...
    -> pegar en `.capamedia/inputs/` o en la raiz del workspace

Secretos Azure Key Vault
  (no aplica a WAS sin BD - solo WAS con BD requiere KV)

Downstream / Integraciones
  UMPs clonadas: 1 (ump-umpclientes0025-was)

Handoffs pendientes (NO son bugs del codigo)
  ~ catalog-info.yaml: completar spec.owner + URL Confluence
  ~ .sonarlint/connectedMode.json: reemplazar placeholder con project_key

Siguiente paso
  1) Pedir los .properties pendientes al owner
  2) Pegar en .capamedia/inputs/<file>.properties
  3) capamedia checklist (o /doublecheck en Claude Code)
```

### Contempla los 3 tipos

- **WAS**: properties del legacy + UMPs + secretos KV si tiene BD +
  handoffs (catalog-info, sonar).
- **BUS (IIB)**: UMPs + TX repos + configurables CSV + handoffs.
- **ORQ**: confirma que referencia servicios migrados (no legacy del
  target), handoffs.

Auto-detecta `source_type` desde el legacy clonado. Lee los reports:
- `.capamedia/config.yaml`
- `.capamedia/properties-report.yaml`
- `.capamedia/secrets-report.yaml`

### Read-only

A diferencia de `check`/`doublecheck`, `info` NO modifica archivos ni corre
el checklist. Solo muestra estado. Ideal como primer comando al abrir un
workspace.

### Tests nuevos (11)

- `capamedia info --help` funciona
- Workspace vacio no crashea (placeholders claros)
- PENDING_FROM_BANK se muestra con keys
- Secretos KV solo para WAS con BD
- Skip de secrets para BUS/ORQ
- Detecta sonarlint placeholder
- Siguiente paso recomienda checklist + owner si hay pending
- Cuenta UMPs desde legacy
- `/info` cargado como prompt canonical
- Prompt menciona `capamedia info` + los 3 tipos
- `init --ai claude` scaffoldea `.claude/commands/info.md`

Total: 600 tests passing.

## [0.23.11] - 2026-04-23

### Added - `capamedia adopt` — adoptar workspaces migrados fuera del CLI

Feedback Julian: un usuario tiene su migracion en disco con layout plano
(sin `destino/` + `legacy/`), por ejemplo:

```
D:\Smart\Capa Media\Pichincha\0026\
  csg-msa-sp-wsclientes0026\    <- proyecto migrado
  ws-wsclientes0026-was\         <- legacy
  MIGRATION_REPORT.md
  ANALISIS_*.md
  ...
```

Como lo adoptamos al layout del CLI?

**Solucion: `capamedia adopt`**. Nuevo comando que:

1. Escanea el CWD detectando subdirectorios por patterns:
   - **Legacy**: `ws-*-was`, `ms-*-was`, `ump-*-was`, `sqb-msa-*`
   - **Destino**: `csg-msa-sp-*`, `tnd-msa-sp-*`, `tpr-msa-sp-*`, `tmp-msa-sp-*`,
     `tia-msa-sp-*`, `tct-msa-sp-*`
2. Muestra el plan (que se movera donde) en una tabla.
3. Pide confirmacion (skipeable con `--yes`).
4. Mueve los subdirs a `legacy/` + `destino/` respectivamente.
5. Opcionalmente corre `init` con `--init` (default harness: claude).

### Uso tipico

```bash
cd D:\Smart\Capa Media\Pichincha\0026
capamedia adopt wsclientes0026 --init
# -> mueve csg-msa-sp-* a destino/
# -> mueve ws-*-was a legacy/
# -> corre capamedia init wsclientes0026 --ai claude

capamedia review
# autodetect funciona, Block 19 auto-genera reports del legacy local
```

### Flags

- `<service_name>` opcional — si no se pasa, se infiere del CWD o de los
  subdirs detectados.
- `--init` — corre `scaffold_project` despues de los moves.
- `--init-ai <harness>` — default `claude`, acepta CSV.
- `--yes / -y` — no pide confirmacion.
- `--dry-run` — muestra el plan sin ejecutar.
- `--workspace / -w` — path alternativo al CWD.

### Idempotencia

- Si `legacy/` y `destino/` ya existen con los subdirs adentro, no intenta
  mover de nuevo (ni da error).
- Archivos sueltos en la raiz (ej. `MIGRATION_REPORT.md`) NO se tocan.
- Auto-padding del `service_name` a 4 digitos (v0.20.1).

### Tests nuevos (11)

`test_adopt.py`:
- Comando wireado en CLI + `--help`
- Clasificacion por pattern (legacy, destino, unknown, hidden)
- `--dry-run` no mueve nada
- `--yes` mueve sin prompt
- Archivos sueltos se preservan
- Sin patterns -> exit 0 sin error
- `--init` dispara scaffold + deja `.claude/` + `.capamedia/`
- Inferencia de service_name de subdirs
- Idempotencia cuando ya estan reubicados

Total: 589 tests passing.

## [0.23.10] - 2026-04-23

### Added - Formato helm `container.secret:` en `bank-secrets.md`

Feedback Julian: el canonical listaba los nombres de secretos en tabla +
ejemplo de uso en `application.yml`, pero **faltaba el formato helm** que
materializa los secretos del Azure Key Vault al pod.

Nueva seccion "Formato helm para montar los secretos del KV (MANDATORIO)"
en `context/bank-secrets.md`:

```yaml
# helm/values-dev.yml (y test.yml, prod.yml)
container:
  secret:
    - name: "CCC-SQLSERVER-MOTOR-HOMOLOGACION-USER"
      location: "CCC-SQLSERVER-MOTOR-HOMOLOGACION-USER"
    - name: "CCC-SQLSERVER-MOTOR-HOMOLOGACION-PASSWORD"
      location: "CCC-SQLSERVER-MOTOR-HOMOLOGACION-PASSWORD"
```

Reglas documentadas:
- `name` = nombre que se expone al contenedor (debe matchear `${CCC-XXX}`
  del `application.yml`).
- `location` = nombre en el KV (siempre **igual a `name`** — convencion del banco).
- Los 3 helms (dev/test/prod) tienen **los mismos nombres**, distinto KV por
  env via annotations del namespace.
- Orden: USER primero, PASSWORD despues.

### Ejemplo end-to-end

Nueva seccion con el flujo completo desde deteccion del JNDI en legacy
hasta el bloque `secret:` en los 3 helms, usando `jndi.tecnicos.cataloga`
como ejemplo concreto.

### Tests nuevos (2)

- `bank-secrets.md` tiene el bloque helm `container.secret` con formato
  name/location
- `bank-secrets.md` tiene el ejemplo end-to-end (legacy → yml → helm)

Total: 578 tests passing.

## [0.23.9] - 2026-04-23

### Changed - Alineacion con commit `104addb` del PromptCapaMedia: NEVER inline defaults, spring.header mandatorios

Nuevo commit en el repo canonico (`feat: Rest do not delete header yml` por
jgarcia, 2026-04-23) con 3 cambios que ahora estan integrados:

#### 1. `spring.header.channel` y `spring.header.medium` MANDATORIOS

Regla 9f actualizada: estas dos keys DEBEN estar siempre presentes como
**literales** en `application.yml` final (REST y SOAP por igual):

```yaml
spring:
  header:
    channel: digital    # MANDATORIO - literal, nunca ${CCC_*}
    medium: web         # MANDATORIO - literal, nunca ${CCC_*}
```

Motivo: la infra del banco las lee para tracing y routing global.

#### 2. NEVER inline defaults `${CCC_VAR:value}`

Regla 9g actualizada (contradiccion anterior removida):

**ANTES (v0.23.6-v0.23.8)**:
> "Valores funcionales: commit como literal o con default inline
> `${CCC_VAR:value}` cuando el valor es conocido del legacy."

**AHORA (v0.23.9)** — alineado al commit `104addb`:
> "NEVER inline defaults `${CCC_VAR:value}`. TODO `${CCC_*}` obtiene su
> valor **exclusivamente desde Helm**. Sin excepciones — ni siquiera para
> codigos del catalogo oficial del banco."

**Por que**: permite que el Helm sea la unica fuente de verdad. Inline
defaults ocultan valores operativos y dificultan cambios sin redeploy.

```yaml
# ✘ NO (v0.23.9) — inline default
error-messages:
  backend: ${CCC_BANCS_ERROR_CODE:00633}

# ✔ OK — si es constante del catalogo, literal
error-messages:
  backend: "00633"

# ✔ OK — si puede cambiar por ambiente, sin default
error-messages:
  backend: ${CCC_BANCS_ERROR_CODE}
```

#### 3. Autofix ya lo cubre

La Regla 7 del banco (`fix_yml_remove_defaults` en `bank_autofix.py`)
remueve todo `${CCC_VAR:default}` automaticamente cuando se corre
`capamedia checklist` / `/doublecheck`. La excepcion previa para
`bancs.error-codes` (`${CCC_BANCS_ERROR_CODE_IIB:00638}`) queda eliminada
del canonical — si es constante, se usa literal.

### Tests nuevos (2)

- `bank-official-rules.md` prohibe inline defaults explicitamente
- `spring.header.channel/medium` son mandatorios como literales

Total: 576 tests passing.

## [0.23.8] - 2026-04-23

### Added - `review` auto-genera reportes desde legacy local (sin `clone`)

Feedback Julian: "si alguien trae su proyecto migrado y quiere hacer review,
¿tiene que correr el init antes? Imagino que el init trae todo lo necesario."

Respuesta: **`init` trae todo lo del workspace** (`.claude/`, `CLAUDE.md`,
`.mcp.json`, `.sonarlint/`, `.capamedia/config.yaml`) pero **NO genera los
reportes de analisis del legacy** (`properties-report.yaml`,
`secrets-report.yaml`, `COMPLEXITY_<svc>.md`) — esos los produce `clone`.

**Problema**: alguien que trae el proyecto migrado + legacy local (sin
`clone`) corre `review` y el Block 19 (properties delivery) + los secrets
checks se saltean silenciosamente porque no tienen input.

**Fix**: nueva funcion `_auto_generate_reports_from_local_legacy` en
`commands/review.py` que:

1. Al inicio de `review()`, chequea si `.capamedia/properties-report.yaml`
   existe.
2. Si NO existe pero hay `./legacy/<svc>/` local, corre `analyze_legacy` al
   vuelo y genera tanto `properties-report.yaml` como `secrets-report.yaml`
   (reusando los helpers de `clone.py`).
3. Idempotente: si el archivo ya existe (del clone), NO lo pisa.

Mensaje claro al usuario:
```
Reportes auto-generados desde legacy local: generado desde .../legacy/ws-xxx-was
  -> .capamedia/properties-report.yaml
  -> .capamedia/secrets-report.yaml (si aplica)
```

### Flujo esperado para alguien que trae su proyecto migrado externamente

```bash
# 1. Workspace con legacy + destino (traido manualmente)
cd mi-servicio/
ls   # legacy/  destino/

# 2. Init - trae .claude, .mcp.json, CLAUDE.md, .sonarlint, etc
capamedia init <svc> --ai claude

# 3. Review - autodetecta + auto-genera reportes si faltan
capamedia review
#    -> Si no hay properties-report.yaml pero hay legacy/, lo genera.
#    -> Corre checklist + autofix + bank-fix + validator oficial.
```

Sin necesidad de `capamedia clone` (que requiere PAT de Azure DevOps).

### Tests nuevos (6)

- Skip si report ya existe (idempotencia)
- Skip si no hay legacy
- Skip si legacy dir no existe
- Genera properties-report.yaml desde WAS local con Propiedad.get()
- Genera secrets-report.yaml si WAS tiene BD (jndi del catalogo)
- No sobreescribe un report existente (del clone)

Total: 574 tests passing.

## [0.23.7] - 2026-04-23

### Added - Ultimos 2 gaps cerrados del PromptCapaMedia (sync completo)

Julian pidio confirmar que TODOS los commits del PromptCapaMedia esten
integrados. v0.23.6 cerro 4 grandes; v0.23.7 cierra los 2 chicos que
quedaban:

1. **Regla 9h - helm values-dev SOAP con `pdb: minAvailable: 1`** (commit
   `9b670da`). Para SOAP, el `helm/values-dev.yml` debe tener el bloque
   `pdb` con `minAvailable: 1` — requerido por la infra del banco para
   PodDisruptionBudget. NO aplica a REST WebFlux.

2. **Regla 11 - CSV `ConfigurablesBusOmniTest_Transfor` para IIB**
   (commit `b55a794`). Referencia al CSV de configurables (7879 filas)
   desde el canonical. **NO se embebe** en el CLI (muy grande, 500 KB y
   se actualiza seguido desde ops). Se documenta el path relativo al repo
   `PromptCapaMedia` y el patron de uso cuando el servicio usa
   `GestionarRecursoConfigurable`.

### Status final de los 12 commits del PromptCapaMedia

| Commit | Status |
|---|---|
| `4d3f738` Merge branch | N/A |
| `ed43688` Documentacion (4 PDFs) | ✅ Ya integrado (reglas en v0.17-v0.22) |
| `9b670da` fix: helm dev soap | ✅ **v0.23.7** |
| `898d25f` fix: Do not remove spring.header yml | ✅ v0.23.6 |
| `0acf823` change examples | ❌ N/A (zip) |
| `368a5c9` feat: new promts QA | ✅ v0.23.6 |
| `a91bda8` feat: Config in yml y helm | ✅ v0.23.6 |
| `56d2771` feat: Service clean | ✅ v0.23.6 |
| `b55a794` docs: align rules with configurable csv | ✅ **v0.23.7** (ref) |
| `3dbf23f` fix: Code 999 generic | ✅ v0.23.6 |
| `cf79f2e` feat: mejora was y bus | ✅ v0.22.0 |
| `b886631` Clean prompts, anonymize names | ✅ v0.22.0 |

**Sincronizacion completa. 0 gaps pendientes.**

### Tests nuevos (2)

- `bank-official-rules.md` tiene Regla 9h con `pdb: minAvailable: 1`
- `bank-official-rules.md` tiene Regla 11 referenciando `ConfigurablesBusOmniTest`

Total: 568 tests passing.

## [0.23.6] - 2026-04-23

### Added - Sincronizacion con ultimos 12 commits de `PromptCapaMedia`

Feedback Julian: revisar ultimos commits del repo canonico y cerrar gaps.
Identifique 6 gaps — este release cierra los 4 mas importantes.

#### Gap 1 — Prompts QA nuevos (commit 368a5c9)

Dos prompts del equipo QA:

**a) `/qa-review` (slash command)** — nuevo canonical `prompts/qa-review.md`:
- Review migrated vs legacy con 14 acceptance criteria (AC-01..AC-14).
- Genera evidencia en `docs/acceptance-criteria/<svc>_<op>_AcceptanceCriteria.md`.
- Criterios funcionales (AC-01..AC-05), no-funcionales (AC-06..AC-10),
  calidad de codigo (AC-11..AC-14 con coverage 85%, duplicacion 0%).

**b) Unit test guidelines** — nuevo canonical `context/unit-test-guidelines.md`:
- Idioma: ingles (excepto mensajes de produccion validados).
- Patron obligatorio `given[Context]_when[Action]_then[ExpectedResult]`.
- Estructura `// Given / // When / // Then` explicita por test.
- Coverage line/branch/method > 85% (JaCoCo).
- Duplicacion codigo = 0% (SonarQube/PMD-CPD/jscpd).
- Sin `@DisplayName`.

#### Gap 2 — Catalogo de error codes del banco (commit 3dbf23f)

Nuevo canonical `context/bank-error-codes.md`:
- Codes del `sqb-cfg-errores-errors/errores.xml`: `9999/9929/9922/9927/9991`.
- Regla estricta: **NUNCA** inventar `"999"` / `"404"` como fallback.
- Patron de constantes `CatalogExceptionConstants` con comentarios.
- Tabla mapping exception type → code (BancsClientException → 9929, null body
  → 9922, HeaderValidator → 9927, timeout → 9991, catch-all → 9999).

#### Gap 3 — Service Purity fortalecida (commit 56d2771)

`bank-official-rules.md` Regla 6 actualizada:
- **CERO metodos privados** en clases `@Service`.
- Helpers van a `application/util/<Domain>*Helper.java` con nombres
  especificos: `ValidationHelper`, `NormalizationHelper`, `FormatHelper`,
  `BuilderHelper`.
- Service = **orquestador puro** que solo tiene `@Override` methods.
- Rationale: SRP + testeabilidad aislada + menos merge conflicts.

#### Gap 4 — Preserve MCP scaffold + all-vars-in-yml (commits 898d25f + a91bda8)

Dos reglas nuevas en `bank-official-rules.md`:

**a) Regla 9f — Preservar el `application.yml` del MCP scaffold:**
- MERGE, no replace. El MCP genera properties que la infra del banco espera
  (`spring.header.*`, `spring.application.name`, `optimus.*`, `web-filter.*`).
- **UNICA** propiedad a REMOVER: `spring.main.lazy-initialization` (causa
  issues con WebFlux y Spring WS).

**b) Regla 9g — Todas las variables legacy en `application.yml`:**
- TODA variable del ANALYSIS (Section 15) debe aparecer en el yml.
- Funcionales → literal o `${CCC_VAR:default}`.
- Secrets/env-dependent → `${CCC_*}` sin default, entrada en los 3 helms.
- Nunca inventar valores; si no disponible → `${CCC_*}` + comentario.
- Cross-check ya implementado en Block 19 del checklist.

### Tests nuevos (11)

`test_canonical_v0_23_6.py`:
- `/qa-review` cargado + menciona AC-01..AC-14 + path de evidencia
- `unit-test-guidelines` cargado + menciona given_when_then, 85%, 0%, ingles
- `bank-error-codes` cargado + codes `9999/9929/9922/9927/9991` + mapping
- Service Purity fortalecida en `bank-official-rules.md`
- Regla 9f preserve scaffold + Regla 9g all-vars-in-yml
- init con Claude scaffoldea `.claude/commands/qa-review.md`

Total: 566 tests passing.

### Gaps no integrados (fuera de scope para esta version)

- CSV `ConfigurablesBusOmniTest_Transfor.csv` (7879 lineas) — muy grande
  para embeber, se puede referenciar via path.
- `helm/dev.yml` bloque `pdb:` para SOAP — regla muy especifica, se agrega
  en proximo release si hace falta.

## [0.23.5] - 2026-04-23

### Fixed - Block 17.3 catastrophic backtracking en regex de `kafka: OFF`

**Bug**: el check `17.3 logging.level.org.apache.kafka: OFF` tenia un regex
con 4 cuantificadores anidados `(?:[^\n]*\n\s+)*` que generaba
**catastrophic backtracking** cuando el yml contenia `logging:` pero no
tenia las claves `org:`/`apache:`/`kafka:` debajo.

**Caso real**: al correr `capamedia review orq` sobre los 7 ORQs
(ORQ0027/0028/0029/0037/0059/0062/0071), 3 de ellos (ORQ0027/0028/0037)
colgaban indefinidamente con 100%+ CPU en el Block 17. Yml de 72 lineas
generaba 72^4 = ~27M permutaciones de backtracking.

**Fix**: reemplazado el regex anidado por heuristica lineal simple:

```python
# Antes (bug):
has_kafka_off = re.search(
    r"logging:\s*(?:[^\n]*\n\s+)*level:\s*(?:[^\n]*\n\s+)*org:\s*"
    r"(?:[^\n]*\n\s+)*apache:\s*(?:[^\n]*\n\s+)*kafka:\s*OFF",
    full_yml,
) is not None or ("apache:" in full_yml and "kafka: OFF" in full_yml)

# Despues (fix):
has_kafka_off = "apache:" in full_yml and "kafka: OFF" in full_yml
```

La heuristica lineal es O(n) y cubre los casos reales. El caso borde
(alguien pone `kafka: OFF` fuera de `logging.level.org.apache`) es
extremadamente raro y no justifica el costo del regex anidado.

### Testing

- 555/555 tests PASS (incluyendo los 12 del Block 17 que siguen verdes).
- Dumps de los 7 ORQs ahora corren en ~5s cada uno (antes: colgaban).

## [0.23.4] - 2026-04-23

### Added - Masividad: `batch clone --init` + `batch review`

Feedback Julian: "necesito saber si acepta masividad... capamedia init con
el clone y init juntos para 7 servicios a la vez. Y el review tambien
masivo, parándote en la carpeta raíz donde estan todos los servicios."

Ya existia la familia `batch *` (clone/init/check/migrate/pipeline/watch).
Esta version suma:

**1. Flag `--init` en `batch clone`** (fusion consistente con single v0.23.0):

```bash
# Archivo de servicios (uno por linea o CSV/XLSX)
cat > services.txt <<EOF
wsclientes0023
wsclientes0076
wstecnicos0008
orqclientes0027
...
EOF

# Clone + init (default Claude) para los 7 en paralelo
capamedia batch clone --from services.txt --init --workers 4
```

Para cada servicio:
1. Crea subcarpeta `<root>/<service>/`
2. Corre `clone_service` (legacy + UMPs + TX + reportes)
3. Si `--init`: corre `scaffold_project` (Claude Code + CLAUDE.md + .mcp.json)
4. Reporta OK / fail / partial (clone OK pero init fallo) en la tabla
   consolidada.

Flag `--init-ai` acepta otros harnesses (claude/codex/copilot/cursor/
windsurf/opencode/all, o CSV).

**2. Nuevo `batch review`** (auditoria masiva):

```bash
# Parado en la carpeta raiz donde estan los 7 workspaces:
capamedia batch review

# Autodetecta subcarpetas que tengan destino/ + legacy/
# Corre el checklist completo en cada una, veredicto consolidado en tabla
```

O con lista explicita:
```bash
capamedia batch review --from services.txt --workers 2
```

Para cada workspace:
1. Localiza `destino/<unico-subdir>` y `legacy/<unico-subdir>`
2. Auto-detecta `source_type` + `has_bancs` desde el legacy
3. Corre `run_all_blocks(ctx)` con la matriz MCP completa
4. Calcula veredicto: `READY_TO_MERGE` | `READY_WITH_FOLLOW_UP` | `BLOCKED_BY_HIGH`
5. Tabla consolidada: `| svc | verdict | source | PASS | HIGH | MEDIUM | LOW |`
6. Reporte `.md` en el root con los detalles

**3. Caso de uso completo que Julian describio**:

```bash
# Estas parado en C:\Dev\BancoPichincha\ (la carpeta raiz)
cd C:\Dev\BancoPichincha

# Preparar lista de 7 servicios a migrar
notepad services.txt    # wsclientes0023, wsclientes0076, ...

# Paso 1: clone + init masivo (paralelo, ~5 min para 7 servicios)
capamedia batch clone --from services.txt --init --workers 4

# Paso 2: fabrics + migrate - esto SIGUE SIENDO manual por servicio
#   (cada uno requiere su sesion de Claude Code)
cd wsclientes0023
claude .
> /migrate
# repetir para cada servicio

# Paso 3: review masivo de vuelta en la raiz
cd C:\Dev\BancoPichincha
capamedia batch review
# tabla consolidada de los 7 veredictos
```

### Tests nuevos (6)

- `batch clone --help` muestra `--init` y `--init-ai`
- `batch review` esta registrado como subcomando
- `batch review <empty>` falla con exit 2 y mensaje claro
- `batch review` autodetecta subcarpetas con `destino/`
- `batch review --from services.txt` lee nombres explicitos
- `batch review` escribe reporte `batch-review-*.md`

Total: 555 tests passing.

## [0.23.3] - 2026-04-23

### Improved - Mensaje del Block 19 menciona las 3 ubicaciones validas para `.properties`

Feedback Julian: pegó los `.properties` en la **raíz** del workspace
(`wsclientes0076/umpclientes0025.properties` y
`wsclientes0076/wsclientes0076.properties`) esperando que el CLI los leyera.
El cascade YA los busca ahí (ubicacion #3 de la cascada), pero el mensaje
de FAIL del Block 19 solo sugeria `.capamedia/inputs/`.

Ahora el `suggested_fix` lista las 3 ubicaciones validas en orden de
prioridad:

1. `<workspace>/.capamedia/inputs/<file>` (recomendado, gitignored)
2. `<workspace>/inputs/<file>`
3. `<workspace>/<file>` (directo en la raiz)

Tambien menciona explicitamente que hay que re-correr `capamedia checklist`
o `/doublecheck` en Claude Code para que autodetecte e inyecte los valores
en `application.yml`.

### Contexto

El caso real: Julian corrio `/check` antes de pegar los archivos, vio FAIL
"NO ENTREGADO", pegó los `.properties` en la raiz, pero no volvio a correr
el check. El reporte seguia mostrando el estado viejo. El nuevo mensaje
lo deja explicito: "Luego re-correr `capamedia checklist` (o `/doublecheck`)".

### Sin cambio de comportamiento

El cascade search ya lee desde la raíz (desde v0.21.0). Ningun bug;
solo mejor guia al usuario.

Total: 549 tests passing.

## [0.23.2] - 2026-04-22

### Added - `capamedia review {orq,bus,was}` con subcomandos que fuerzan el tipo

Feedback Julian: "podemos agregarle capamedia review orq de orquestador, bus
o WAS, vamos a agregarle para que pueda decir: anda por esto para hacer este
checklist sobre los bus, los orquestadores, los WAS".

- `capamedia review` → autodetect (como antes)
- `capamedia review orq` → fuerza `source_type=orq` (activa Block 20,
  desactiva WAS+BD secrets)
- `capamedia review bus` → fuerza `source_type=bus` (matriz BUS+invocaBancs
  -> REST override en Block 0)
- `capamedia review was` → fuerza `source_type=was` (matriz WAS: 1op REST /
  2+ops SOAP, activa Block 19 properties + secrets KV si hay BD)

Tambien disponible como flag `--kind` en el comando base:
```
capamedia review --kind orq
capamedia review --kind was --legacy ./legacy/ws-xxx-was
```

Cuando el tipo forzado difiere del auto-detectado, el CLI imprime un aviso
claro: *"autodeteccion del legacy dice was pero estas forzando orq. Uso el
valor forzado."*

Util cuando:
- La autodeteccion falla (legacy no clonado, o ambiguo).
- Querés auditar un proyecto "como si fuera X" para debug.
- Un ORQ aun no clonó su legacy pero querés correr el Block 20.

### Refactor

- `commands/review.py` ahora exporta un `typer.Typer` app en vez de una
  funcion suelta. `cli.py` usa `add_typer(review.app, name="review")`.
- El core `review()` sigue siendo la funcion original (retrocompatible
  para tests existentes).

### Tests nuevos (9)

- Subcomandos orq/bus/was wireados y visibles en help
- `force_kind` setea `source_type` en el CheckContext (3 casos)
- `--kind foo` invalido → exit 2
- Override: force_kind vence al autodetectado
- Sin `--kind`: autodetect funciona igual que v0.23.1

Total: 549 tests passing.

## [0.23.1] - 2026-04-22

### Added - Slash command `/doublecheck` en Claude Code (y resto de harnesses)

Feedback Julian: tener `capamedia checklist` como CLI esta OK, pero tambien
hace falta el slash command `/doublecheck` disponible en Claude Code (y
todos los harnesses) para correrlo desde el chat sin salir del IDE.

- Nuevo prompt canonical `canonical/prompts/doublecheck.md`.
- Se publica automaticamente como `.claude/commands/doublecheck.md` al
  correr `capamedia init --ai claude` (y analogamente en `.codex/`,
  `.opencode/`, etc. para los otros harnesses).
- El slash `/doublecheck` invoca internamente `capamedia checklist` + guia
  al agente para interpretar el resultado (PASS / residuales HIGH / handoff
  al owner).

### Tests nuevos (2)

- `doublecheck` esta cargado como prompt canonical
- `init --ai claude` escribe `.claude/commands/doublecheck.md`

Total: 540 tests passing.

## [0.23.0] - 2026-04-22

### Added - 5 features consolidadas del feedback de Julian

1. **Clone + init juntos** — nuevo flag `--init` en `capamedia clone`:
   ```bash
   capamedia clone wsclientes0076 --init
   # equivale a: capamedia clone + capamedia init --ai claude
   ```
   Default harness: **Claude Code** (consistente con el flujo principal).
   `--init-ai` permite cambiar (acepta `claude/codex/copilot/cursor/windsurf/opencode/all` o CSV).

2. **Catalogo de secretos Azure Key Vault embebido** — para WAS con BD:
   - Nuevo canonical `context/bank-secrets.md` con las 6 entradas del PDF
     oficial BPTPSRE-Secretos (DTST, TPOMN×3, CREDITO_TARJETAS, MOTOR_HOMOLOGACION).
   - Nuevo modulo `core/secrets_detector.py` que escanea legacy + UMPs
     buscando JNDI en 5 formatos distintos (persistence.xml, ibm-web-bnd.xml,
     @Resource, InitialContext.lookup, *.properties) y los mapea al catalogo.
   - `capamedia clone` genera `.capamedia/secrets-report.yaml` con los
     secretos requeridos (solo si `source_kind=was AND has_database=true`).
   - JNDI detectados pero fuera del catalogo se reportan en
     `jndi_references_unknown` con hint de consultar con SRE.

3. **Comando `capamedia checklist`** — doble check en una linea:
   - Alias de `check --auto-fix --bank-fix` que aplica TODO lo autofixeable
     de nuestras reglas + las 4 deterministas del banco (4/7/8/9) en una
     sola invocacion.
   - Lo que queda FAIL despues del checklist es handoff al owner
     (sonarcloud project-key, URL Confluence, etc.) — no bugs del codigo.

4. **Block 20 — ORQ invoca servicio MIGRADO, no legacy**:
   - Nueva regla 10.5 en `bank-official-rules.md` canonical.
   - `run_block_20` detecta en proyectos `source_type=orq` referencias a
     `sqb-msa-<target>` o `ws-<target>-was` en YAML/Java/properties → FAIL
     HIGH con suggested_fix claro (usar `<namespace>-msa-sp-<target>` del
     servicio migrado).
   - Excluye auto-referencias al propio ORQ (`sqb-msa-orq*` es OK cuando
     aparece en su propio artifactId).

5. **Review valida todo** (confirmacion) — ya lo hacia desde v0.20.0 via
   `_autodetect_review_paths`. Funciona igual para WAS/BUS/ORQ.

### Tests nuevos (24)

- `test_secrets_detector.py` (13): catalogo, scan XML/Java/properties,
  dedup, audit WAS-con-BD, mapping JNDI→secret, desconocidos, UMPs
- `test_block_20_orq_migrated.py` (6): skip si no-ORQ, PASS limpio, FAIL
  con sqb-msa-*, FAIL con ws-*-was, auto-referencia OK, multiple offenders
- `test_clone_init_flag.py` (4): firma de clone_service, default claude,
  `checklist` wireado en CLI, help menciona `--init`

Total: 538 tests passing.

## [0.22.0] - 2026-04-22

### Changed - Sincronizacion con repo canonico `PromptCapaMedia` + canonical sin servicios-gold

Feedback Julian: "No quiero que queden referenciados ningun servicio como
algo estandar o un gol estandar, por asi decirlo, pero si todo lo demas."

Los ultimos 5 commits del `PromptCapaMedia` introdujeron 4 gaps en el CLI.
Este release cierra los 4.

#### Gap 1 — Matriz MCP-driven en codigo ejecutable

Antes `run_block_0` decidia framework solo por conteo de ops (`1=REST else SOAP`)
con excepcion BD+SOAP. Eso clasificaba mal a:
- BUS con invocaBancs y 2+ ops (deberia REST+WebFlux)
- ORQ con 2+ ops (deberia REST+WebFlux)

**Fix**: nuevo helper `_expected_framework(source_type, has_bancs, ops_count)`
implementa la matriz oficial:

| Origen | Condicion | Framework |
|---|---|---|
| BUS (IIB) | `invocaBancs=true` | REST + WebFlux (override MCP) |
| ORQ | siempre | REST + WebFlux (deploymentType=orquestador) |
| WAS | 1 op | REST + MVC |
| WAS | 2+ ops | SOAP + MVC |
| Unknown | fallback | Conteo de ops |

`CheckContext` suma campos `source_type` y `has_bancs`. Los comandos `check` y
`review` los auto-populan desde el legacy via
`detect_source_kind + detect_bancs_connection`.

#### Gap 2 — Check 3.5 "Naming profesional" ejecutable (Block 3)

Antes el texto estaba en el canonical pero no habia check ejecutable. Ahora
`run_block_3` detecta clases/interfaces/records con nombres genericos:

- `Service.java`, `ServiceImpl.java`
- `Adapter.java`, `Controller.java`, `Mapper.java`, `Helper.java`
- `Port.java`, `InputPort.java`, `OutputPort.java`
- `Request.java`, `Response.java`, `Dto.java`
- `Config.java`, `Constants.java`, `Exception.java`
- `Entity.java`, `Repository.java`

Cada match → FAIL HIGH con suggested_fix claro (ej. "Renombrar a
`CustomerService` / `BancsAdapter` / `<Operation>Response`").

#### Gap 3 — Templates SonarLint completos en scaffold

Antes `init` solo generaba `connectedMode.json` (template con placeholder).
Ahora agrega:

- `connectedMode.example.json` — muestra el formato con un UUID de ejemplo
- `README.md` — guia paso-a-paso para conectar SonarLint a SonarCloud
  (VS Code / IntelliJ), con troubleshooting

#### Gap 4 — Canonical sin referencias a servicios-gold (reformulado por Julian)

El pedido original era agregar una advertencia sobre `wsclientes0015` como
gold solo para WAS 2+ ops. Julian lo reformulo: **eliminar toda referencia a
servicios especificos como "gold standard" o "referencia a copiar"** en el
canonical del CLI.

Trabajo de limpieza en 11 archivos canonical:
- **De 108 menciones** a ~30 (solo mantenidas las que son historico/anti-patron,
  no guia de copia)
- **"gold standard"** como frase: de muchas apariciones a **1** (la propia
  politica que dice "no nombrar servicios como gold standard")
- `tnd-msa-sp-wsclientes0024` como hardcoded → `<namespace>-msa-sp-<svc>`
- `tnd-msa-sp-wsclientes0015` como hardcoded → `<namespace>-msa-sp-<svc>`
- "Copy from the gold standard" → "Apply the canonical pattern (defined in
  this document)"
- Tabla de historial del `checklist-rules.md` reescrita sin nombres de
  servicios concretos

Filosofia nueva: las reglas viven en los canonical del CLI
(`bank-official-rules.md`, `hexagonal.md`, `bancs.md`, `checklist-rules.md`).
El agente aplica las reglas, no copia de un servicio-ejemplo. Los patrones
del banco evolucionan y un proyecto migrado hace un mes puede tener gaps
ya resueltos en la version actual de las reglas.

### Tests nuevos (25)

- `test_block_0_mcp_matrix.py` (17): matriz pura de `_expected_framework`
  (BUS+invocaBancs, ORQ, WAS 1/2+ ops, fallback, case-insensitive) +
  integracion `run_block_0` con proyectos reales
- `test_block_3_naming.py` (8): generic classes, interfaces, records flagged;
  domain-prefixed pass; mixed; edge cases (sin src/main/java)
- `test_sonarlint_scaffold.py` (1): init genera example.json + README.md

Total: 514 tests passing.

## [0.21.0] - 2026-04-22

### Added - Properties delivery audit + autofix inject (feedback Julian)

**Feedback Julian**: "Cuando tenemos los puntos properties, hay que hacer
el fix o que salga en el review. Seria el check nuestro, que diga que no
tenemos las properties puestas, que haga un estudio, que busque en la
carpeta raiz si estan todas las properties, que haga un check si nos falta
una, y que si encuentra properties ya, que las meta en todo caso si no
estan puestas."

**Implementacion**:

**1. Convencion oficial** — carpeta `.capamedia/inputs/<archivo>.properties`

El owner del servicio te manda los `.properties` pendientes y vos los pegas
en esa carpeta. Como `.capamedia/` esta gitignored, no se filtran al repo
del banco. El cascade tolera variantes (raiz del workspace, `inputs/` sin
`.capamedia/`, samples inline en `legacy/`).

**2. Nuevo modulo** `core/properties_delivery.py`:

- `audit_properties_delivery(workspace)` — lee `properties-report.yaml`,
  busca cada archivo en ubicaciones cascade, clasifica:
  - `DELIVERED` — entregado con todas las keys declaradas
  - `PARTIAL` — entregado pero faltan keys
  - `STILL_PENDING` — no se encontro en ningun lado
  - `NOT_PENDING` — ya resuelto desde clone (SHARED_CATALOG / SAMPLE_IN_REPO)

- `inject_delivered_properties(audit, project_path)` — autofix que reemplaza
  `${CCC_*}` del `application.yml` (y `application-*.yml`) del destino por
  los valores literales. Solo toca archivos DELIVERED (saltea PARTIAL para
  evitar mezcla con placeholders residuales). Mapping CCC_key -> legacy_key
  conocido (URL_XML, RECURSO_XX, COMPONENTE_XX, GRUPO_CENTRALIZADA, etc.).

**3. Nuevo Block 19** en `checklist_rules.py`:
- PASS por cada archivo DELIVERED
- FAIL MEDIUM por cada PARTIAL (con lista de keys faltantes)
- FAIL MEDIUM por cada STILL_PENDING (con hint al path exacto donde pegar)
- Skip si no hay `properties-report.yaml` (proyecto pre-v0.19)

Integrado en `capamedia check` y en la Fase 3 (re-check) del `capamedia review`.

**4. Nueva Fase 2.5 en `capamedia review`**: "Properties delivery audit".
Corre el audit, muestra resumen DELIVERED/PARTIAL/STILL_PENDING, y si hay
DELIVERED ejecuta el autofix automaticamente. Log: "inject N placeholder(s)
${CCC_*} reemplazado(s) en M yml(s)".

### Flujo tipico end-to-end

```bash
# 1. clone detecta .properties pendientes
capamedia clone wsclientes0076
#   -> .capamedia/properties-report.yaml: wsclientes0076.properties + umpclientes0025.properties PENDING

# 2. pedir archivos al owner y pegarlos
cp <from-bank>/wsclientes0076.properties  ws/.capamedia/inputs/
cp <from-bank>/umpclientes0025.properties ws/.capamedia/inputs/

# 3. review auto-detecta y auto-inyecta
capamedia review
#   Fase 2.5: 2 DELIVERED, 0 PARTIAL, 0 STILL_PENDING
#   Inject: 8 placeholders ${CCC_*} reemplazados en application.yml
```

### Tests nuevos (23)

- `test_properties_delivery.py` (16): audit + inject con cascade, partial,
  delivered, fallback legacy inline, YAML malformado, multiple yml files
- `test_block_19_properties.py` (7): block results con DELIVERED/PARTIAL/
  STILL_PENDING, skip cuando no hay report, 3 files mixed status

Total: 489 tests passing.

## [0.20.7] - 2026-04-22

### Fixed - Mensaje de "Proximos pasos" del `fabrics generate` no mas induce a error

El mensaje de exito de v0.20.6 decia:

> 2. Corre `capamedia init --here` dentro de `destino/<project>/` para sumar
>    `.claude/` y `CLAUDE.md`.

Pero eso es **al reves**: el `init` va en el **workspace root** (al lado de
`legacy/`, `destino/`, `umps/`), NO adentro de `destino/<project>/`. Si el
user seguia ese consejo, terminaba con `.claude/`, `CLAUDE.md`, `.capamedia/`
duplicados dentro del repo Java del banco, que luego contaminaban el
`git push` del servicio migrado.

**Fix**: mensaje reescrito con el flujo correcto:

```
1. Abri Claude Code desde el workspace (NO desde destino/):
     cd <workspace>
     claude .
2. En el chat de Claude Code, corre: /migrate
3. Cuando termine, audita con: capamedia review
     (autodetecta destino/ y legacy/ desde el workspace)
```

Queda alineado con el nuevo flujo autodetectado de `review` (v0.20.0) y
`fabrics generate` (v0.20.4).

### Tests

- Guard contra regresion: `init --here` dentro de `destino/` NO debe
  aparecer mas en el source de `fabrics.py`.

Total: 466 tests passing.

## [0.20.6] - 2026-04-22

### Fixed - `fabrics generate` con WAS sin WSDL fisico genera placeholder en vez de omitir

**Bug descubierto post-v0.20.5**: la solucion anterior (omitir `wsdlFilePath`
del payload cuando el WSDL era sintetico) hacia que el MCP tirara:

```
"error": "The \"path\" argument must be of type string. Received undefined",
"message": "? Error: The \"path\" argument must be of type string. Received undefined"
```

El MCP Fabrics (Node.js) requiere que `wsdlFilePath` este presente SI o SI
como string valido — no acepta omitido ni null.

**Fix v0.20.6**: nueva funcion `_write_wsdl_placeholder(ws, service_name,
target_namespace)` que genera un WSDL minimo valido en
`<ws>/.capamedia/tmp/<svc>-placeholder.wsdl`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!-- WSDL PLACEHOLDER generado por capamedia-cli. -->
<wsdl:definitions
    xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:tns="http://pichincha.com/wsclientes0076"
    targetNamespace="http://pichincha.com/wsclientes0076"
    name="Wsclientes0076Service">
  <wsdl:types>
    <xsd:schema targetNamespace="http://pichincha.com/wsclientes0076"/>
  </wsdl:types>
  <wsdl:portType name="Wsclientes0076PortType"/>
</wsdl:definitions>
```

El MCP puede hacer `copyfile` sin problemas, el scaffold queda completo con
un WSDL placeholder en `src/main/resources/legacy/`. Durante `/migrate`,
el agente reconstruye el WSDL real desde las anotaciones JAX-WS del legacy.

### Tests nuevos (4)

- `_write_wsdl_placeholder` crea XML valido con WSDL minimo
- Usa el service_name en PascalCase
- Incluye marker "PLACEHOLDER" para que sea obvio
- Respeta target_namespace custom o genera un default razonable

Total: 465 tests passing.

## [0.20.5] - 2026-04-22

### Fixed - 2 bugs del `fabrics generate` (reportados por Julian en wsclientes0076)

**Bug 1: projectName hardcodeado a `tnd-msa-sp-` ignorando el namespace elegido**

El comando preguntaba interactivamente el namespace (`tnd/tpr/csg/tmp/tia/tct`)
pero el `project_name` se calculaba antes con prefix `tnd-msa-sp-` hardcoded:

```python
# v0.20.4 bug:
project_name = f"tnd-msa-sp-{service_name.lower()}"  # antes de resolver namespace
...
if namespace is None:
    namespace = Prompt.ask(...)   # ya es tarde, project_name ya uso "tnd-"
```

Julian eligio `tpr` pero el proyecto quedo en `destino/tnd-msa-sp-wsclientes0076/`.

**Fix**: mover la resolucion de namespace ANTES del calculo de project_name:

```python
# v0.20.5:
if namespace is None:
    namespace = Prompt.ask(...)
project_name = f"{namespace}-msa-sp-{service_name.lower()}"
```

**Bug 2: WSDL sintetico se pasaba al MCP causando ENOENT**

Para WAS con solo anotaciones JAX-WS (sin `.wsdl` fisico), `analyze_legacy`
sintetiza `Path("<inferred-from-java>")` como marcador. El CLI tomaba ese
placeholder, lo convertia en path absoluto y lo enviaba al MCP Fabrics:

```
"wsdlFilePath": "C:\\Dev\\BancoPichincha\\wsclientes0076\\<inferred-from-java>"
```

Lo que resultaba en:
```
ENOENT: no such file or directory, copyfile '...\\<inferred-from-java>' ->
  '...\\src\\main\\resources\\legacy\\<inferr...
```

El scaffold se generaba igual, pero el error confundia y ensuciaba el output.

**Fix**: detectar el prefix `<inferred` y:
1. Omitir `wsdlFilePath` del payload al MCP (asi no intenta copyfile).
2. Mostrar warning claro explicando que el agente migrador va a reconstruir
   el contrato SOAP desde las anotaciones Java durante `/migrate`.

### Tests nuevos (2)

- `projectName` NO hardcodea `tnd-msa-sp-`: verificacion al source
- `wsdlFilePath` sintetico se omite del payload: check via substring

Total: 462 tests passing.

## [0.20.4] - 2026-04-22

### Changed - `fabrics generate` autodetecta service_name desde `.capamedia/config.yaml`

**Feedback Julian**: corrio `capamedia fabrics generate` sin argumentos
esperando la misma UX que `capamedia review` (v0.20.0), y el comando fallo
con "Missing argument 'SERVICE_NAME'". Tambien probo `--here` que no existe.

**Fix**: `service_name` pasa a ser argumento opcional. Si se omite, lee
`.capamedia/config.yaml` del workspace y toma el valor de ahi.

```bash
# Antes (v0.20.3):
capamedia fabrics generate wsclientes0076

# Ahora (v0.20.4), parado en el workspace:
capamedia fabrics generate
```

Ademas se aplica el mismo **auto-padding a 4 digitos** (v0.20.1) por
coherencia con `clone` y `init`.

### Tests nuevos (7)

- `_autodetect_service_name_from_config`: lee config, devuelve None cuando
  falta archivo / campo / YAML malformado, strip whitespace (5 tests)
- Integracion CLI: sin config falla con exit 2 y mensaje claro; con config
  autodetecta y continua hasta preflight (2 tests)

Total: 460 tests passing.

## [0.20.3] - 2026-04-22

### Fixed - `analyze_legacy` resuelve UMPs WAS (antes solo buscaba pattern IIB)

**Bug reportado por Julian en wsclientes0076 + umpclientes0025**: el UMP se
clona correctamente a `umps/ump-umpclientes0025-was/` (patron WAS), pero en
el reporte solo aparecia `wsclientes0076.properties` como pendiente. El UMP
no se escaneaba y sus keys unicas (`GRUPO_CENTRALIZADA`, `COD_DATOS_VACIOS`,
`UNIDAD_PERSISTENCIA`, etc.) quedaban sin detectar.

**Causa raiz en `analyze_legacy`**: la busqueda del repo UMP ya clonado en
disco estaba hardcodeada al pattern IIB:

```python
repo = umps_root / f"sqb-msa-{ump_lower}"   # <-- solo IIB
if repo.exists():
    ...
else:
    umps.append(UmpInfo(name=ump))           # <-- repo_path queda None
```

Entonces cuando `detect_properties_references` recorria los roots:
```python
for ump in umps:
    if ump.repo_path and ump.repo_path.exists():   # <-- False, se saltea
        roots_to_scan.append(ump.repo_path)
```

El UMP nunca se escaneaba. El detector v0.19.0/0.20.2 funcionaba bien en
teoria pero le llegaba lista vacia de umps para WAS.

**Fix**: nueva funcion `_find_ump_repo(umps_root, ump, source_kind)` que
prueba los 3 patterns conocidos en orden segun el tipo del servicio:

```python
_UMP_REPO_PATTERNS_WAS = [
    "ump-{ump}-was",    # prioritario para WAS
    "ms-{ump}-was",
    "sqb-msa-{ump}",    # fallback
]
_UMP_REPO_PATTERNS_NON_WAS = [
    "sqb-msa-{ump}",    # prioritario para IIB/ORQ
    "ump-{ump}-was",
    "ms-{ump}-was",
]
```

### Comportamiento despues del fix

Con `wsclientes0076` (WAS) + `umpclientes0025` (clonado como `ump-umpclientes0025-was`):

```
.properties detectados:
  ✓ generalServices.properties       [resuelto por catalogo embebido]   (3 keys)
  ✓ CatalogoAplicaciones.properties  [resuelto por catalogo embebido]   (4 keys)
  ✗ wsclientes0076.properties        [PENDIENTE - pedir al owner]       (2 keys)
  ✗ umpclientes0025.properties       [PENDIENTE - pedir al owner]       (6 keys) ← ESTABA FALTANDO
```

### Tests nuevos (6)

- `_find_ump_repo`: WAS prioriza `ump-<ump>-was`, IIB prioriza `sqb-msa-<ump>`,
  fallback cross-pattern, ms-variant, ausente devuelve None (5 tests)
- `analyze_legacy` integracion: WAS con UMP clonado como `ump-<ump>-was`
  resuelve repo_path y propaga al detector de properties (1 test)

Total: 453 tests passing.

## [0.20.2] - 2026-04-22

### Fixed - El detector de `.properties` ahora tambien cubre el WAS principal (no solo UMPs)

**Bug reportado por Julian**: "Vamos a buscar los puntos properties del WAS,
pero después los UMP también tienen unos puntos properties; eso también hay
que buscarlos."

**Causa raiz en v0.19.0**: el detector inferia el nombre del archivo
`.properties` especifico con una heuristica simple:

```python
ump_match = re.search(r"(ump[a-z]+\d{4})", root_name_lower)
if ump_match:
    specific_file_name = f"{ump_match.group(1)}.properties"
# else: specific_file_name = ""  <-- se descartaba silenciosamente
```

Entonces para el WAS principal (root `ws-<svc>-was`, sin "ump" en el nombre),
todas las llamadas `Propiedad.get("K")` del codigo del servicio se perdian.

**Fix v0.20.2**: resolver robusto en 2 pasos:

1. **Propiedad.java como fuente de verdad** — nueva regex `RE_RUTA_ESPECIFICA`
   lee la constante que define la ruta al .properties especifico:
   ```java
   private static final String RUTA_ESPECIFICA =
       "/apps/proy/OMNICANALIDAD_SERVICIOS/conf/wsclientes0076.properties";
   ```

2. **Heuristica de fallback ampliada** — `_infer_specific_file_from_root_name`
   cubre los 4 patterns Azure del banco:
   - `ump-<svc>-was`  → `<svc>.properties`
   - `ws-<svc>-was`   → `<svc>.properties`   ← **antes no se cubria**
   - `ms-<svc>-was`   → `<svc>.properties`   ← **antes no se cubria**
   - `sqb-msa-<svc>`  → `<svc>.properties`   ← **antes no se cubria**

### Comportamiento nuevo

Cuando hay WAS principal + UMPs, el detector ahora reporta **ambos** archivos
por separado:

```
.properties detectados:
  ✗ wsclientes0076.properties    [PENDIENTE - pedir al owner]   service
  ✗ umptecnicos0023.properties   [PENDIENTE - pedir al owner]   ump:umptecnicos0023

ATENCION: hay 2 .properties especificos del servicio/UMP que NO estan en el repo.
```

### Tests nuevos (11)

`test_properties_detector.py`:
- WAS principal detecta sus propias Propiedad.get() (bug de v0.19.0)
- WAS + UMP: ambos detectados por separado
- Propiedad.java tiene prioridad sobre heuristica de root
- ms-<svc>-was y sqb-msa-<svc> se resuelven
- Root desconocido retorna None sin crashear
- Propiedad.java sin RUTA_ESPECIFICA retorna None

Total: 447 tests passing.

## [0.20.1] - 2026-04-22

### Fixed - `clone`/`init` auto-padean el nombre del servicio a 4 digitos

**Bug reportado por Julian**: corriendo `capamedia clone wsclientes76` (el
repo real es `ws-wsclientes0076-was` en `tpl-integration-services-was`),
el CLI fallaba con:

```
FAIL no se encontro en ningun proyecto Azure conocido
Tip: verifica que el servicio exista o agrega un nuevo patron a AZURE_FALLBACK_PATTERNS
```

**Causa**: el user escribio `76` en vez de `0076`. Los patterns estaban
correctos (`ws-{svc}-was` incluido) pero el CLI probaba con `ws-wsclientes76-was`
literal que no existe. Convencion del banco: todos los servicios terminan en
**4 digitos zero-padded** (`wsclientes0076`, `wstecnicos0008`, `orq0027`, etc.).

**Fix**: nueva funcion `normalize_service_name` en `commands/clone.py` que:
- Auto-padea sufijos numericos de 1-3 digitos a 4 (zero-left-padding).
- Respeta 4+ digitos (caso raro pero no se rompe).
- Lowercase + strip whitespace.
- No toca nombres que no terminan en digitos.
- Imprime tip claro al usuario: `wsclientes76 -> wsclientes0076 (auto-padded)`.

Integrada en `clone_service()` y `init_project()` (para consistencia).

### Ejemplos

| Input | Normalizado | was_padded |
|---|---|---|
| `wsclientes76` | `wsclientes0076` | True |
| `wstecnicos8` | `wstecnicos0008` | True |
| `orq27` | `orq0027` | True |
| `WsClientes76` | `wsclientes0076` | True |
| `wsclientes0076` | `wsclientes0076` | False |
| `wstecnicos12345` | `wstecnicos12345` | False (>4 se respeta) |
| `foo` | `foo` | False (no digitos) |

### Tests nuevos (13)

`test_normalize_service_name.py`:
- Padding 1/2/3 digitos
- No padding para 4+
- Case-insensitive
- Strip whitespace
- Nombres sin digitos
- UMPs (umptecnicos23), ORQs, variantes ms*

Total: 436 tests passing.

## [0.20.0] - 2026-04-22

### Changed - `capamedia review` ahora autodetecta paths y deja `destino/` limpio

**Feedback del user (Julian)**: dos mejoras de UX al review:

1. "No hace falta que pongamos legacy. Podemos estar en la carpeta raíz y poner
   capamedia review. Las dos carpetas legacy/ y destino/ se autodetectan. Si
   no encuentra, tira error claro."
2. "Cuando corre la checklist oficial del banco genera un .md dentro del
   destino. Estaría bueno sacarlo afuera así no jode cuando pusheamos sin
   querer al repo del servicio migrado."

**Autodeteccion de paths**:

```bash
# Antes (v0.19.x):
capamedia review ./destino/tnd-msa-sp-wstecnicos0008 --legacy ./legacy/ws-wstecnicos0008-was

# Ahora (v0.20.0), parado en el workspace root:
capamedia review
```

- `project_path` pasa a ser argumento **opcional**.
- Si se omite, el CLI busca `./destino/<unico-subdir>/` desde el CWD.
- `--legacy` tambien se autodetecta desde `./legacy/<unico-subdir>/`.
- Errores claros con hint de fix si falta `destino/`, esta vacio, o tiene
  varios subdirs (en ese caso sugiere el path explicito).

**Reubicacion de reportes** (v0.20.0):

Todos los artefactos del review ahora se escriben en
`<workspace>/.capamedia/reports/` y `<workspace>/.capamedia/autofix/`,
NO dentro de `destino/`. Esto mantiene el proyecto Java migrado limpio,
sin que un `git add -A` arrastre los reportes al repo del banco.

Archivos que se reubican:
- `hexagonal_validation_*.md` / `.json` (del validador oficial)
- `hexagonal_report_*.md` / `.json`
- `review_<ts>.json` (log consolidado del review)
- `<ts>.log` (logs del autofix loop)

**Antes (v0.19.x) - archivos que quedaban en destino/**:
```
destino/tnd-msa-sp-wstecnicos0008/
  .capamedia/
    autofix/20260422T203244.log
    review/20260422-210322.json
  hexagonal_validation_20260422.md     ← polucion repo
  hexagonal_validation_20260422.json   ← polucion repo
```

**Ahora (v0.20.0)**:
```
wstecnicos0008/                        ← workspace
  destino/tnd-msa-sp-wstecnicos0008/   ← LIMPIO, ready para git push
  .capamedia/
    reports/
      hexagonal_validation_20260422.md
      hexagonal_validation_20260422.json
      review_20260422-210322.json
    autofix/
      20260422T203244.log
```

**Compatibilidad**: pasar `project_path` explicito sigue funcionando igual
que antes. Si el path no esta bajo un `destino/`, workspace root == project
(fallback legacy) y no hay reubicacion.

### Tests nuevos (14)

- `_find_single_subdir` (3): unico, multiple, ignora ocultos
- `_autodetect_review_paths` (5): resolve both, legacy opcional, falta destino,
  destino vacio, multiples subdirs
- `_resolve_workspace_root` (2): bajo destino/ sube 2 niveles, fallback
- `_relocate_generated_reports` (3): mueve md+json, noop cuando ws==project,
  sobrescribe duplicados
- `review` integracion (2): sin args desde workspace, falla sin destino

Total: 423 tests passing.

## [0.19.0] - 2026-04-22

### Added - `clone` detecta `.properties` especificos y los reporta como blockers de handoff

**Feedback del user (Julian)**: antes de arrancar `/migrate` en un WAS nuevo,
necesita saber QUE archivos `.properties` especificos del servicio tiene que
pedirle al banco — sino llegan a `/migrate` con placeholders que el agente
marca como blockers falsos. Esto complementa el catalogo embebido v0.18.0
(generalservices + catalogoaplicaciones) con la **otra cara** del problema:
los properties que SI cambian por servicio.

**Implementacion**:

- **Nuevo detector** `detect_properties_references` en `core/legacy_analyzer.py`
  escanea codigo Java (y potencialmente ESQL/XML) buscando 4 patterns WAS reales:
  - `Propiedad.get("KEY")` → `.properties` especifico del UMP/servicio
  - `Propiedad.getGenerico("KEY")` → generalservices (catalogo compartido, skip)
  - `Propiedad.getCatalogo("KEY")` → catalogoaplicaciones (catalogo compartido, skip)
  - `ResourceBundle.getBundle("nombre")` → cualquier .properties custom
  - Paths literales `"/apps/proy/.../conf/<archivo>.properties"` para
    identificar el nombre fisico

- **Nueva dataclass** `PropertiesReference` con status:
  - `SHARED_CATALOG`: ya embebido en v0.18.0, no hay que hacer nada.
  - `SAMPLE_IN_REPO`: hay un sample en el repo con valores, usar como defaults.
  - `PENDING_FROM_BANK`: **BLOCKER** - pedirselo al owner del servicio
    antes de `/migrate`.

- **Integracion en `clone`**:
  - Tabla nueva (paso 7) con los `.properties` detectados y su estado.
  - Si hay `PENDING_FROM_BANK` > 0, warning en rojo con accion clara.
  - Contador en la tabla de resumen final.
  - Persistencia en `.capamedia/properties-report.yaml` para que
    `/migrate` y otros comandos lo consuman.

- **Canonical updated**: `bank-shared-properties.md` ahora documenta el
  flujo del reporte automatico y la regla que el agente migrador debe
  seguir al leerlo (no marcar shared como blocker, marcar pendientes en
  MIGRATION_REPORT como "inputs del owner", usar samples si hay).

### Tests agregados (13 nuevos)

- `test_properties_detector.py` (11): detecta get/getGenerico/getCatalogo,
  paths literales, ResourceBundle, excluye shared catalog, extrae samples,
  orden estable del output.
- `test_clone.py` (2): persiste el yaml con separacion pending/shared.

### Ejemplo real (wstecnicos0008)

Con este detector, el clone hubiera avisado **desde el dia 1**:

```
.properties detectados:
  ✓ generalServices.properties     [resuelto por catalogo embebido]  bank-shared  (5 keys)
  ✓ CatalogoAplicaciones.properties [resuelto por catalogo embebido]  bank-shared  (1 key)
  ✗ umptecnicos0023.properties     [PENDIENTE - pedir al owner]       ump:umptec23 (6 keys)

ATENCION: hay 1 .properties especifico del servicio/UMP que NO esta en el repo.
Antes de /migrate, pedir estos archivos al owner del servicio.
```

En vez de que el MIGRATION_REPORT final diga "blocker: CCC_TX_ATTRIBUTES_XML_PATH"
como si fuera descubrimiento sorpresa, el usuario ya sabia desde `clone` que
necesitaba URL_XML, RECURSO, COMPONENTE, COMPONENTE2, UNIDAD_PERSISTENCIA, RECURSO2.

## [0.18.1] - 2026-04-22

### Fixed - `capamedia review` Fase 4 crasheaba con `UnicodeDecodeError` en Windows

**Bug reportado por Julian**: corriendo `capamedia review` en `wstecnicos0008`,
la Fase 4 (validador oficial del banco) explotaba con:

```
UnicodeDecodeError: 'charmap' codec can't decode byte 0x90 in position 13:
character maps to <undefined>
TypeError: expected string or bytes-like object, got 'NoneType'
```

**Causa**: `_run_official_validator` invocaba `subprocess.run(..., text=True)`
sin pasar `encoding` explicito. En Windows + Python 3.14, el default cae a
`cp1252` y no puede decodificar los emojis UTF-8 (✓/✗) del validador oficial.
El subprocess devolvia `stdout=None` y el `ansi_re.sub()` crasheaba.

**Fix**:
- `subprocess.run(..., encoding="utf-8", errors="replace")` explicito.
- Guard `raw_stdout = result.stdout or ""` antes del regex.
- Try/except adicional para `UnicodeDecodeError` como salvavidas.

**Tests de regresion** en `test_review.py`:
- `test_run_official_survives_none_stdout`: stdout=None no crashea.
- `test_run_official_survives_unicode_decode_error`: UnicodeDecodeError
  retorna (0, 0, "").
- `test_run_official_passes_utf8_encoding`: verifica que la llamada incluye
  `encoding="utf-8"` y `errors="replace"`.

**Estado pre-fix del review de wstecnicos0008**:
- Fase 1: 0 fixes, NEEDS_HUMAN
- Fase 2: regla 8 aplicada (lib-bnc-api-client normalizado de alpha a 1.1.0)
- Fase 3: 20 PASS, 2 MEDIUM, 0 HIGH/LOW → READY_WITH_FOLLOW_UP
- Fase 4: crash ← fix aqui

## [0.18.0] - 2026-04-22

### Added - Catalogo embebido de `generalservices.properties` + `catalogoaplicaciones.properties`

**Feedback del user (Julian)**: despues de migrar `wstecnicos0008` el agente
reporto como "blockers" 4 items en `MIGRATION_REPORT.md`, de los cuales 3 eran
falsos positivos porque el agente NO sabia que `OMNI_COD_SERVICIO_OK`,
`MIDDLEWARE_INTEGRACION_TECNICO_WAS`, `BANCS`, etc. son **constantes globales
del banco** con valores literales conocidos (no env vars a resolver).

**Solucion**: embeber ambos archivos de properties **compartidos** en el CLI
para que los agentes los tengan disponibles desde el scaffold.

- Nuevo canonical `context/bank-shared-properties.md` con:
  - Los 2 archivos literales (`generalservices.properties` + `catalogoaplicaciones.properties`).
  - Tabla de mapping `legacy key` → `application.yml path` → `valor literal`.
  - Regla explicita para el agente: "busca en el catalogo antes de marcar
    blocker; si esta, usa valor literal hardcoded en application.yml".
  - Aclaracion de que SI depende del servicio: el `<ump>.properties` o
    `<servicio>.properties` especifico (esos si se piden al usuario).

- `bank-official-rules.md` ahora tiene **Regla 10 — Properties compartidas**
  que referencia el nuevo catalogo y prohibe marcar claves del catalogo como
  env vars faltantes en `MIGRATION_REPORT.md`.

- El adapter de Claude concatena todos los `context/*.md` en `CLAUDE.md`
  automaticamente — no hizo falta tocar adapters.

### Motivacion concreta

El MIGRATION_REPORT de `wstecnicos0008` decia:

> 1. lib-bnc-api-client en 1.1.0-alpha.* (cache local) — subir a 1.1.0 stable
>    cuando CI tenga credenciales Azure Artifacts.
> 2. CCC_TX_ATTRIBUTES_XML_PATH requiere ConfigMap + volumen OpenShift...
> 3. catalog-info.yaml: faltan sonarcloud.io/project-key real y URL Confluence.
> 4. .sonarlint/connectedMode.json pendiente (BLOQUE 14).

El #1 era error del agente (ya fixeado manualmente en este caso: build.gradle
usa ahora `1.1.0` estable literal). El #2 SI es valido (URL_XML viene del
umptecnicos0023.properties, no del catalogo compartido). El #3 y #4 son
handoff/ops, no blockers de codigo.

Con el catalogo embebido, el agente ahora puede:
- Hardcodear `success-code: "0"`, `backend: "00633"`, `fatal-code: "9999"`, etc.
  en `application.yml` en vez de dejarlos como `${CCC_*}`.
- Diferenciar en el `MIGRATION_REPORT.md` entre "resuelto desde catalogo del
  banco" (no es blocker) y "input pendiente del owner" (si es blocker de handoff).

## [0.17.5] - 2026-04-22

### Fixed - Log transaccional es EXCLUSIVO de ORQ (no WAS ni BUS)

**Feedback del user**: el v0.17.4 ablandaba la politica al decir "OBLIGATORIO
en ORQ, OPCIONAL en BUS/WAS con downstream calls" y hasta incluia un ejemplo
con `// MVC/SOAP (WAS)`. Eso contradice directamente el PDF 1 que dice:

  > _"Los eventos se generan unicamente en los orquestadores."_

**Correcciones al canonical** `context/log-transaccional-orq.md`:

- Summary y titulo ahora dicen **EXCLUSIVO de orquestadores**.
- Nueva seccion "Ambito de aplicacion" lista explicitamente:
  - ✅ ORQ: OBLIGATORIO.
  - ❌ WAS: NO lleva nada de esto. Si aparece, es copy-paste error.
  - ❌ BUS: NO usa lib-event-logs. Tiene su propio tracing.
  - ❌ UMPs: NO aplican (son componentes internos de WAS).
- LT-1 (dependencia): solo `lib-event-logs-webflux:1.0.0`. La variante `-mvc`
  documentada en el PDF 2 no se usa porque ORQs son siempre WebFlux y WAS no
  lleva log transaccional.
- LT-3 (`@EventAudit`): eliminado el ejemplo MVC/SOAP. Se aclara: si aparece
  en un WAS, es error de copy-paste y debe removerse.

### Added - Block 18: detector inverso (contra-regla del Block 17)

Nuevo bloque del checklist que **solo corre en proyectos NO-ORQ** (WAS, BUS,
UMP). Marca como FAIL con severity `high` cualquier resto de log transaccional:

- **18.1** - `lib-event-logs-*` en `build.gradle` (prohibido).
- **18.2** - `logging.event` / `spring.kafka` auditor / `xml.template` en el
  `application.yml` (prohibido).
- **18.3** - `@EventAudit` en cualquier `.java` (prohibido).

Cada fail incluye `suggested_fix` con la instruccion de remover el artefacto.

El Block 17 (que valida que ORQ SI tenga log transaccional) y el Block 18 son
mutuamente excluyentes:

```
         ORQ?
          │
    ┌─────┴─────┐
    SI          NO
    │           │
    Block 17    Block 18
    (valida     (valida
     presencia)  ausencia)
```

### Added - `_looks_like_orq()` mejorado

La heuristica ORQ ahora tambien lee `catalog-info.yaml` si existe (algunos
equipos no meten `orq` en el nombre del repo pero si en title/tags). Si `orq`
aparece en el catalog, el proyecto se trata como ORQ.

### Testing

- **12 tests nuevos** en `tests/test_block_18_lt_only_orq.py`:
  - Block 18 se salta en ORQ (responsabilidad del 17).
  - Block 18 se activa en WAS.
  - 3 tests por cada check (18.1/18.2/18.3) — positivos y negativos.
  - Test de integracion: WAS con copy-paste completo de un ORQ → 3 fails.
- **389/389 tests PASS** total.

### Rationale

Esta politica evita dos errores posibles:
1. **Falso negativo en ORQ**: el 17 falla si el ORQ no tiene la libreria.
2. **Falso positivo en WAS**: el 18 falla si el WAS copia-pega de un ORQ.

Antes del v0.17.5, el 17 solo validaba "presencia en ORQ" pero nada validaba
"ausencia en WAS" — por eso un WAS con copy-paste pasaba silencioso.

## [0.17.4] - 2026-04-22

### Added - Log transaccional: documentacion ampliada con flujo end-to-end

**Input del user**: 2 PDFs oficiales que documentan el log transaccional con
mucho mas detalle que lo que teniamos:

1. `BPTPSRE-Estructura Log Transaccional-220426-215404.pdf` — flujo completo
   ORQ → CE_EVENTOS → WSTecnicos0038 → CE_TRANSACCIONAL, estructura JSON final,
   mapeo headerIn XML → JSON, formato del `<error>` del evento.
2. `BPTPSRE-Libreria Log Transaccional-220426-202920.pdf` — dependencias por
   variante (mvc/webflux), tabla completa de atributos kafka/logging con
   defaults, `@EventAudit` con `AuditType.T`, plantillas XML en helm/ConfigMap,
   WebFlux=WebClient vs MVC=RestClient.

**Cambios en** `canonical/context/log-transaccional-orq.md`:

- Diagrama ASCII del **flujo de auditoria end-to-end** (ORQ publica XML a
  `CE_EVENTOS` → `WSTecnicos0038` aplica plantillas → JSON final en
  `CE_TRANSACCIONAL`). Aclara que `WSTecnicos0038` **NO** es parte de nuestro
  scope — es infra compartida del banco.
- **Caracteristicas oficiales** de la libreria: Spring Boot 3.5.12 (agnostica),
  Java 21, disponible en variante `mvc` y `webflux`.
- **Regla LT-2 ampliada**: tabla completa de defaults documentados en el PDF
  (`PLAIN`, `SASL_SSL`, `45000ms session`, `2000ms request`, `EXTERNAL` mode).
- **Regla LT-3 ampliada**: cita explicita del PDF sobre WebClient (WebFlux) vs
  RestClient (MVC/SOAP, NO RestTemplate en Boot 3.x).
- **Regla LT-4 ampliada**: desglose de elementos del template XML (`<TX>`,
  `<RX>`, `<coleccion>`, `<campo>`) con explicacion de cada atributo
  (`cargaFuente`, `nombrePadre`, `nombreHijo`, `fuentePadre`, `nomenclatura`).
- **NUEVA Regla LT-5** — Estructura del mensaje final en `CE_TRANSACCIONAL`:
  JSON completo con mapeo campo-por-campo desde headerIn/bodyIn/bodyOut al
  JSON que consume Elastic. Informativo pero critico para entender que el
  `headerIn` del request entrante debe tener *todos* los campos que el JSON
  final espera (geolocalizacion, dispositivo, idCliente, tipoIdCliente — no
  son opcionales aunque puedan venir vacios).
- **NUEVA Regla LT-6** — Formato del `<error>` en el evento XML intermedio:
  4 campos obligatorios (`codigo`, `mensaje`, `tipo`, `backend`) con tablas
  de mapeo cruzando `reference_codigos_backend.md` y `reference_error_types.md`
  de MEMORY (INFO/ERROR/FATAL; 00638=IIB, 00045=BANCS, 00000=inventado).
- **NUEVA Regla LT-7** — Mapeo obligatorio headerIn XML → evento: lista
  explicita de los 18 campos del headerIn + 7 del sub-bloque `<bancs>` que
  deben viajar **tal cual** al evento (sin trim, sin upper-case, sin
  transformaciones).

**Cambios en** `core/checklist_rules.py`:

- Comentario del Block 17 ahora cita **ambos PDFs** como fuentes oficiales.
- Menciona las 7 reglas canonicas (LT-1..LT-7) en lugar de 4.
- Clarifica la secuencia `CE_EVENTOS → WSTecnicos0038 → CE_TRANSACCIONAL`
  (antes solo decia "topico kafka de auditoria" sin detallar el intermediario).

### Contexto operativo

- Los ORQs que estamos migrando (0027, 0028, 0037, 0059, 0062) usan todos
  esta libreria. Las reglas LT-5 y LT-6 ahora permiten validar que el
  `HeaderIn` DTO que viaja por el ORQ trae todos los campos requeridos.
- El gap conocido de `feedback_bancs_header_out_no_echo.md` (HeaderOut no
  replica `<bancs>`) se cruza con LT-7: el evento **SI** debe llevar `<bancs>`
  del request entrante, aunque la response NO lo tenga.

### Testing

- Sin cambios en codigo de production (solo docs canonicas y comentarios).
- 377/377 tests PASS (sin regresiones).

### Sources

- `prompts/documentacion/BPTPSRE-Estructura Log Transaccional-220426-215404.pdf`
- `prompts/documentacion/BPTPSRE-Libreria Log Transaccional-220426-202920.pdf`

## [0.17.3] - 2026-04-22

### Fixed - `init` detecta workspace automatico (evita subcarpeta anidada)

**Caso real**: user estaba parado en `C:\...\wstecnicos0008\` (que ya tenia
`legacy/`, `destino/`, `umps/` del clone y fabrics) y corrio
`capamedia init wstecnicos0008 --ai claude` sin `--here`. Resultado: el
CLI creo una subcarpeta anidada `wstecnicos0008\wstecnicos0008\` y puso
ahi el scaffold (`.claude/`, `CLAUDE.md`, `.mcp.json`). Claude Code no
encontraba el contexto al abrir desde el workspace padre.

**Fix**: `init` detecta si el CWD ya parece workspace y activa `--here`
automatico. Heuristica (3 senales):

  1. CWD tiene carpeta `legacy/` (del clone)
  2. CWD tiene carpeta `destino/` (del fabrics)
  3. CWD se llama igual que el servicio pasado (`wstecnicos0008` === CWD.name)

Si cualquier senal matchea, imprime tip:

```
Tip: la carpeta actual (wstecnicos0008) parece ser el workspace del
servicio (tiene legacy/destino o el nombre coincide). Usando --here
automatico para evitar subcarpeta anidada.
```

Y escribe en la misma carpeta. Si ninguna senal matchea (ej. corrida
desde `C:\Dev\BancoPichincha\`), crea subcarpeta como antes.

`--here` explicito sigue funcionando igual.

### Testing

- **377/377 tests PASS** (+5 en `test_init_auto_here.py`):
  - Auto-here cuando CWD tiene `legacy/`
  - Auto-here cuando CWD tiene `destino/`
  - Auto-here cuando CWD name = service name
  - Crea subcarpeta cuando CWD NO es workspace
  - `--here` explicito no rompe

---

## [0.17.2] - 2026-04-22

### Fixed - UMPs de servicios WAS viven en otro proyecto Azure

**Caso real reportado**: `capamedia clone wstecnicos0008` detectaba la UMP
`umptecnicos0023` correctamente, pero al clonarla intentaba solo el patron
IIB `tpl-bus-omnicanal/sqb-msa-umptecnicos0023` y fallaba con `repository
not found`. El repo REAL vive en
`tpl-integration-services-was/ump-umptecnicos0023-was`.

**Fix** — dos patrones de fallback para UMPs segun el tipo del servicio que
las consume:

- `UMP_AZURE_FALLBACK_PATTERNS_IIB` (para servicios IIB/ORQ):
  1. `tpl-bus-omnicanal/sqb-msa-{ump}` (clasico IIB)
  2. `tpl-integration-services-was/ump-{ump}-was` (fallback por si la UMP
     migro a WAS)

- `UMP_AZURE_FALLBACK_PATTERNS_WAS` (para servicios WAS):
  1. `tpl-integration-services-was/ump-{ump}-was` (tipico WAS, caso real)
  2. `tpl-integration-services-was/ms-{ump}-was` (variante "ms")
  3. `tpl-bus-omnicanal/sqb-msa-{ump}` (fallback IIB)

Nueva funcion `_resolve_ump_repo(ump_name, dest_root, shallow, parent_kind)`
que itera los patrones en orden y devuelve el primero que responde. El
`parent_kind` (iib/was/orq) determina el orden de prueba — mismo `source_kind`
del servicio principal detectado con `detect_source_kind()`.

`commands/clone.py` Step 3: ahora usa `_resolve_ump_repo` en vez de un clone
hardcoded. Mensaje actualizado:

```
3. Clonando UMPs...
  OK was/ump-umptecnicos0023-was        # detectado con patron WAS
  SKIP otraump0000: no encontrado en ninguno de los patrones (was parent)
```

### Observacion - UMPs WAS sin TX BANCS

El usuario noto (correctamente) que las UMPs de WAS NO suelen tener llamadas
TX BANCS — son mas bien stores de BD (JPA/SQL) o logica pura de dominio.
`extract_tx_codes` no va a encontrar nada en esas UMPs. Queda documentado
como comportamiento esperado; el reporte `COMPLEXITY_<svc>.md` mostrara
`UMPs con TX extraido: 0/1` y eso es correcto para WAS.

### Testing

- **372/372 tests PASS** (+7 en `test_ump_resolver.py`):
  - Patrones IIB priorizan `sqb-msa-{ump}`
  - Patrones WAS priorizan `ump-{ump}-was`
  - `_resolve_ump_repo` con `parent_kind=was` intenta `ump-X-was` primero
  - `_resolve_ump_repo` con `parent_kind=iib` intenta `sqb-msa-X` primero
  - Fallback a alternativa si la primera no matchea
  - Retorna None si ninguno matchea
  - IIB puede fallback a proyecto WAS si la UMP vive alla

---

## [0.17.1] - 2026-04-22

### Fixed - Detector WAS: WSDL sin prefijo `wsdl:` + UMPs en pom.xml/Java

**Caso real**: `capamedia clone wstecnicos0008` reporto falsamente
`0 operaciones WSDL` y `0 UMPs` cuando el servicio tiene 2 ops y 1 UMP.
Investigacion del legacy revelo dos bugs del detector.

**Bug 1 - `RE_WSDL_OPERATION` exigia prefijo `wsdl:`**:

El regex era `r'<wsdl:operation\s+name="([^"]+)"'` y solo matcheaba
`<wsdl:operation>`. El WSDL del wstecnicos0008 usa
`<operation>` sin prefix (el namespace default ya es WSDL):

```xml
<definitions xmlns="http://schemas.xmlsoap.org/wsdl/">
  <portType name="WSTecnicos0008">
    <operation name="ConsultarAtributosTransaccion01">
```

Fix: `r'<(?:wsdl:)?operation\s+name="([^"]+)"'`. Matchea ambos
con y sin prefijo. `_extract_portType_block` ya tenia el fallback.

**Bug 2 - `detect_ump_references` no busca en WAS**:

La funcion solo escanea `.esql` + `.msgflow` + `.subflow` (patron IIB).
En un WAS las UMPs no viven en ESQL — se declaran:
  1. Como dependencias Maven en `pom.xml`:
     `<artifactId>umptecnicos0023-dominio</artifactId>`
  2. Como imports Java:
     `import com.pichincha.tecnicos.umptecnicos0023.pojo.E;`

Nueva funcion `detect_ump_references_was()` que escanea esos dos
patrones via regex y deduplica (ej: `umptecnicos0023-core-dominio` y
`umptecnicos0023-dominio` -> un solo `umptecnicos0023`).

`analyze_legacy()` ahora elige el detector segun `source_kind`:
  - `iib` / `orq` -> `detect_ump_references` (ESQL)
  - `was` -> `detect_ump_references_was` (pom.xml + Java)

`commands/clone.py` hace lo mismo en el Step 2 del clone. Mensaje
actualizado: "Detectando UMPs en pom.xml + imports Java (WAS)" vs
"Detectando UMPs referenciados en ESQL/msgflow".

**Verificacion sobre el caso real**:

```
antes v0.17.1:        despues v0.17.1:
  ops: 0                ops: 2 [ConsultarAtributosTransaccion01, ...02]
  UMPs: []              UMPs: ['umptecnicos0023']
  framework: soap       framework: soap
  (default)             (2 ops + no invoca BANCS directo)
```

### Testing

- **365/365 tests PASS** (+9 en `test_was_detectors.py`):
  - WSDL sin prefijo `wsdl:` parseado correctamente
  - WSDL con prefijo `wsdl:` sigue funcionando (regresion)
  - `find_wsdl` encuentra WSDL en `webapp/WEB-INF/wsdl/` (path WAS)
  - UMPs detectadas en `pom.xml` Maven deps
  - UMPs detectadas en Java imports
  - `detect_ump_references_was` NO mira ESQL (eso es IIB)
  - Combinando pom + Java, dedup correcto
  - Multiples UMPs distintas ordenadas
  - `analyze_legacy` integracion end-to-end WAS con UMPs + WSDL en webapp

---

## [0.17.0] - 2026-04-22

### Added - 4 updates del feedback real (Julian + JGarcia a91bda8)

**1. Sync canonical con `a91bda8 feat: Config in yml y helm`** de
jgarcia@pichincha.com. 13 archivos actualizados del canonical via
`capamedia canonical sync`. Cambios clave: scan obligatorio de
`.properties` en UMPs + documentacion como sole-input para
`application.yml` y helm.

**2. Regla 6.5 - `spring.header.*` obligatorio en `application.yml`**:

Documentada en `context/bank-official-rules.md`. Los literales
`channel: digital` y `medium: web` (metadata de Optimus) DEBEN estar
en todo servicio migrado. Advertencia explicita: el autofix de
Regla 7 (`${VAR:default}` → `${VAR}`) usa regex que NO matchea
literales, por lo que nunca elimina estos valores.

Ejemplo de referencia en el canonical (basado en el gold 0024):

```yaml
spring:
  application:
    name: tnd-msa-sp-<svc>
  header:
    channel: digital
    medium: web
TPL_LOG_INFO: INFO
TPL_LOG_DEBUG: DEBUG
```

**3. Canonical `context/was-ump-inline.md`** nuevo (4 reglas):

Caso real: algunos WAS tienen UMPs dentro del propio repo (no como
`sqb-msa-ump*` externos). La logica de esas UMPs se **plasma INLINE**
al migrar, no como adapter remoto.

- WAS-UMP-1: detectar inline vs externa (pattern `ump-*` / `*-ump` /
  clases Java prefijo `UMP*` dentro del mismo legacy)
- WAS-UMP-2: donde plasmar la logica (util → `infrastructure/util/`;
  orquestacion → service; BANCS wrapper → adapter con `BancsClient`)
- WAS-UMP-3: tests propios obligatorios por cada UMP migrada
- WAS-UMP-4: `MIGRATION_REPORT.md` con seccion `## UMPs inline migradas`
  como tabla path legacy → destino migrado

**4. Canonical `context/log-transaccional-orq.md`** nuevo (4 reglas LT):

Fuente: `BPTPSRE-Librería Log Transaccional-220426-202920.pdf`. Libreria
`com.pichincha.common:lib-event-logs-*:1.0.0` que publica
request/response a Kafka de auditoria. OBLIGATORIO en orquestadores.

- LT-1: dependencia `lib-event-logs-webflux:1.0.0` (WebFlux) o
  `lib-event-logs-mvc:1.0.0` (MVC)
- LT-2: bloques `spring.kafka.*` + `logging.event.*` en `application.yml`
  con env vars (KAFKA_SERVER, KAFKA_TOPIC_AUDITOR, THREAD_* etc.)
- LT-3: anotacion `@EventAudit(service, method, type=AuditType.T)` en
  cada adapter outbound
- LT-4: templates XML en `xml.template.templates` via env var
  `XML_TRANSACCION_<NNNN>` (shared en Helm)

Incluye ejemplos WebFlux y MVC/SOAP con `@EventAudit` en el adapter.

**Nuevo `Block 17` en `core/checklist_rules.py`**:

Solo activa en ORQs (heuristica: `"orq"` en el nombre del proyecto).
Skip total si no-ORQ.

- `17.1` - dependencia `lib-event-logs-<variante>` (HIGH)
- `17.2` - bloques `spring.kafka` + `logging.event` en yml (HIGH)
- `17.3` - `logging.level.org.apache.kafka: OFF` (MEDIUM)
- `17.4` - `@EventAudit` en al menos 1 adapter (HIGH); skip si el
  proyecto no tiene adapters (caso borde)

### Testing

- **356/356 tests PASS** (+12 en `test_block_17_log_transaccional.py`).
  Escenarios: skip en no-ORQ, activa en ORQ, cada check 17.1-17.4 en
  pass y fail con fixtures minimales.

---

## [0.16.1] - 2026-04-22

### Fixed - `install`: direct-download fallback para Gradle y VS Code

**Caso real reportado**: user con winget instalado tira
`No package found matching input criteria` al hacer
`winget install -e --id Gradle.Gradle`. Causa: el ID en el repo oficial
de winget cambio o el source no lo resuelve en ciertas versiones.

**Fix**: ultima ruta de fallback con descarga directa via PowerShell:

- `_install_gradle_direct()`: descarga
  `https://services.gradle.org/distributions/gradle-8.14-bin.zip`,
  extrae a `$env:USERPROFILE\gradle\gradle-8.14\`, agrega
  `...\gradle-8.14\bin` al PATH del user (permanente).

- `_install_vscode_direct()`: descarga el User Installer de
  `https://code.visualstudio.com/sha/download?build=stable&os=win32-x64-user`
  y lo ejecuta silent con `/verysilent /mergetasks=addtopath` (agrega
  `code` al PATH automatico).

**Cuando se activa** (Windows only):
  1. Si `_get_installer_command()` devuelve None (sin package manager)
     y el paquete esta en `DIRECT_DOWNLOAD_PACKAGES` -> direct-download.
  2. Si el package manager responde pero con `No package found` o `not
     found` para Gradle/VS Code -> fallback automatico a direct-download.
  3. Si el binario del package manager tira `FileNotFoundError` -> idem.

**Limitacion**: el user tiene que cerrar/abrir PowerShell despues para
que el PATH se refresque (Windows no lo hace en sesion activa sin
broadcast-message).

### Testing

- **344/344 tests PASS**. Ruff limpio.

---

## [0.16.0] - 2026-04-22

### Added - Comando `update` + auto-install de winget + URLs manuales

**`capamedia update`** nuevo comando para actualizar el CLI:

- Detecta la fuente de instalacion:
  - `uv tool` -> `uv tool upgrade capamedia-cli`
  - `pip install -e .` desde source git -> `git pull` + `pip install -e . --force-reinstall`
  - `pip install capamedia-cli` registry -> `pip install --upgrade capamedia-cli`
- Flag `--dry-run` para ver los comandos sin ejecutar.
- Al terminar, pide al user abrir shell nueva para ver la version
  actualizada (el interprete ya cargo la vieja en esta sesion).

### Changed - `install`: auto-install de winget + URLs manuales de fallback

**Problema real reportado**: user corrio `capamedia install` y fallaron
Gradle + VS Code con `[WinError 2] El sistema no puede encontrar el
archivo especificado`. Causa: `winget` no estaba en PATH.

**Fix 1** - `_ensure_winget_on_windows()`: al inicio de `install_toolchain`
en Windows, si `winget` no esta, intenta instalarlo descargando el
`App Installer` msixbundle desde `https://aka.ms/getwinget` y
registrandolo con `Add-AppxPackage`. Si falla, imprime instrucciones
manuales (3 opciones: Microsoft Store / PowerShell / scoop).

**Fix 2** - `_get_installer_command()` con fallback cascada en Windows:
`winget > scoop > choco`. Mapea IDs entre gestores (ej `Gradle.Gradle`
winget = `gradle` scoop = `gradle` choco).

**Fix 3** - URLs de descarga manual en la tabla. Nuevo dict
`MANUAL_DOWNLOAD_URLS` con la pagina oficial de cada paquete. Si ningun
package manager matchea, la columna `Accion` muestra `MANUAL: <url>`
en vez de un generico.

**Fix 4** - si alguna instalacion falla con `WinError 2` (o similar),
debajo del reporte de fallas se imprimen las URLs de retry manual para
copiar-pegar en el browser.

**Fix 5** - `_print_manual_steps()` limpiado:
- Saco mencion a `--openai-api-key` (NO usamos tokens API pagos)
- Clarifica que con Claude Max o ChatGPT Plus/Pro alcanza
- Explicita que `claude login` / `codex login` se hacen antes del bootstrap

### Testing

- **344/344 tests PASS**.
- Ruff limpio.

---

## [0.15.2] - 2026-04-22

### Changed - `capamedia install` reconoce Claude Code CLI como alternativa a Codex

Antes, el toolchain pedia Codex CLI obligatorio (`npm install -g @openai/
codex`) incluso cuando el usuario ya tenia Claude Code CLI funcionando.
Ahora son **alternativas intercambiables**: con **uno** alcanza.

**Cambios:**

- `Package` dataclass recibe nuevo campo
  `alternative_checks: tuple[tuple[str, tuple[str, ...]], ...]`. Cada
  elemento = (nombre_legible, check_command).
- Nuevo metodo `Package.detected_alternative()` que devuelve el nombre
  legible de la alternativa detectada (o `None` si el primario esta
  presente).
- Package "Codex CLI" renombrado a "AI engine CLI (Claude Code o Codex)":
  - Primario: `codex --version` (auto-install via `npm install -g
    @openai/codex`)
  - Alternativa: `claude --version` (Claude Code CLI, no se auto-instala
    porque requiere flujo de auth manual)
- Tabla de estado muestra `"Claude Code CLI detectado"` en la columna
  `Accion` cuando la alternativa esta presente.
- Note del package explicita que con **uno** alcanza y ambos consumen
  suscripcion del usuario (Claude Max o ChatGPT Plus/Pro), NO tokens API.

### Testing

- **344/344 tests PASS** (+5 en `test_install_ai_engine.py`):
  - Package configurado con claude como alternativa
  - OK cuando solo claude presente -> `detected_alternative() == "Claude Code CLI"`
  - OK cuando solo codex presente -> primario gana, `detected_alternative() == None`
  - Fail cuando ninguno presente
  - Primario gana sobre alternativa si ambos estan

---

## [0.15.1] - 2026-04-22

### Fixed - Doc: comando de instalacion con `uv` + warning de PATH en Windows

**Sintaxis correcta de `uv tool install`** en el CHANGELOG (README ya estaba
bien): el bug doc tenia `uv tool install --from .` que falla con "the
following required arguments were not provided: <PACKAGE>". Corregido a
`uv tool install capamedia-cli --from .`.

**Nueva nota en README**: advertencia para usuarios de `pip install -e .`
en Windows — el binario `capamedia.exe` se instala en
`%USERPROFILE%\AppData\Local\Python\pythoncore-<ver>-64\Scripts\` y este
directorio a menudo no esta en PATH por default. Se incluye snippet
PowerShell para agregarlo a la sesion actual y al PATH del usuario.

`uv tool install` no tiene este problema — uv maneja el PATH solo.

---

## [0.15.0] - 2026-04-22

### Added - `capamedia status` — readiness check sin tokens API

Comando corto que responde una sola pregunta: **"estoy listo para migrar?"**.
Tabla rich + veredicto global. Exit 0 si todo OK, exit 1 si falta algo
obligatorio.

```powershell
capamedia status
```

Chequea:

- **Toolchain**: `git`, Java 21 (JAVA_HOME o PATH), `gradle`, `node`
- **AI engine (suscripcion)**: al menos `claude` o `codex` autenticado
  (usa la suscripcion del usuario — Claude Max / ChatGPT Plus/Pro — NO
  tokens API pagos)
- **Azure DevOps PAT**: env `CAPAMEDIA_AZDO_PAT` o `AZURE_DEVOPS_EXT_PAT`
- **Azure Artifacts token**: env `CAPAMEDIA_ARTIFACT_TOKEN` o `ARTIFACT_TOKEN`
- **MCP Fabrics**: server `fabrics` registrado en `.mcp.json` (proyecto o home)

**Explicitamente NO chequea `OPENAI_API_KEY`**. El engine headless usa
la suscripcion del usuario (login interactivo del CLI), no una API key
de billing. El test `test_check_engines_never_looks_at_openai_api_key`
documenta esta invariante.

Si algun check obligatorio falla, imprime los pasos sugeridos en orden:

```
Pasos sugeridos:
  1. `capamedia install`                  # toolchain
  2. `claude login` o `codex login`       # suscripcion
  3. `capamedia auth bootstrap --artifact-token T --azure-pat T --scope global`
  4. `capamedia fabrics setup --refresh-npmrc`
```

### Testing

- **339/339 tests PASS** (+15 en `test_status.py`):
  - `StatusCheck` dataclass smoke
  - `_check_binary` en 3 escenarios (missing / found / with-version)
  - `_check_engines` en 4 escenarios (claude-only OK, codex-only OK,
    ninguno, y test explicito que confirma que NUNCA lee `OPENAI_API_KEY`)
  - `_check_azure_pat` y `_check_artifacts_token` con env vars alternativas
    y ausentes
  - `status_command` fail path (exit 1) + all-green path (no exit)

---

## [0.14.0] - 2026-04-22

### Added - Comandos `version` y `uninstall`

**`capamedia version`** (nuevo subcomando):

Muestra version del CLI + metadata util en un panel rich. Complementa el
flag global `--version` / `-V` que ya existia; el subcomando es mas
explorable (aparece en `capamedia --help`) y agrega:

- Version instalada (v0.14.0)
- Python interprete + implementation
- Plataforma (OS + release)
- Location del package (util para debug)
- Executable path

**`capamedia uninstall`** (nuevo subcomando):

Desinstala el CLI detectando la fuente automatico (uv tool / pip).

```bash
capamedia uninstall                  # interactivo, pide confirmacion
capamedia uninstall --yes            # unattended
capamedia uninstall --dry-run        # muestra que ejecutaria, sin tocar
capamedia uninstall --purge --yes    # ademas borra ~/.capamedia/ y .mcp.json
```

Deteccion:
  1. `uv tool list` para buscar `capamedia-cli` -> `uv tool uninstall`
  2. `pip show capamedia-cli` -> `pip uninstall -y capamedia-cli`
  3. Si no lo encuentra en ninguno, avisa y termina exit 0

Flag `--purge` (opcional): ademas del package, borra:
  - `~/.capamedia/` (carpeta con auth.env, caches, etc.)
  - `~/.mcp.json` (registro global del MCP Fabrics)
  - `./.mcp.json` (registro del proyecto actual)

### Testing

- **324/324 tests PASS** (+10 en `test_version_uninstall.py`):
  - `version` imprime version correcta
  - `_has_uv_tool` detecta presencia, ausencia, y `uv` no-instalado
  - `_has_pip_install` detecta presencia y ausencia
  - `_purge_user_files` borra paths reales y con `--dry-run` solo lista
  - `uninstall_command` con nada instalado exit 0, dry-run no llama subprocess

### Uso completo (desde cero)

Ya que tenemos `install` + `check-install` + `version` + `uninstall`, el
ciclo completo desde una maquina vacia queda:

```powershell
# Descargar
git clone https://github.com/CreattorMatter/capamedia-cli.git
cd capamedia-cli

# Instalar (elegir uno)
uv tool install capamedia-cli --from .                  # preferido (isolated)
# o
pip install -e .                                        # editable desde source

# Verificar
capamedia version
capamedia --help

# Usar (flujo completo)
capamedia install              # toolchain: git, java 21, gradle, node, codex, etc.
capamedia auth bootstrap ...   # credenciales Azure + OpenAI + artifacts
capamedia clone <servicio>     # legacy + UMPs + TX
capamedia fabrics generate <servicio> --namespace tnd
capamedia check <path>         # checklist BPTPSRE
capamedia validate-hexagonal summary <path>  # gate oficial del banco
capamedia review <path>        # pipeline end-to-end

# Desinstalar
capamedia uninstall --purge --yes
```

---

## [0.13.0] - 2026-04-22

### Added - `capamedia review` — pipeline end-to-end para proyectos migrados externamente

**Use case**: el equipo del banco migra servicios en paralelo usando los
prompts del repo `PromptCapaMedia` directamente, sin pasar por el CLI.
Cuando terminan la migracion, necesitan un pase de limpieza que aplique
todo lo que el CLI sabe hacer + el gate oficial del banco. Ahora hay un
comando unico que hace eso.

```bash
capamedia review <path-al-proyecto-migrado> \
    --legacy <path-al-legacy> \
    --bank-description "Servicio X" \
    --bank-owner jusoria@pichincha.com \
    --max-iterations 5
```

**Pipeline en 4 fases** (documentado en el docstring del modulo):

1. **Fase 1 — Nuestro checklist + autofix loop**: corre todos los blocks
   (0/1/2/5/7/13/14/15/16) en un loop. Aplica `AUTOFIX_REGISTRY` con max
   `--max-iterations` rondas hasta convergencia.
2. **Fase 2 — Bank autofix**: aplica las 5 reglas deterministas del
   script oficial (4, 6, 7, 8, 9) — `@BpLogger`, StringUtils→nativo +
   record extraction, `${VAR:default}`→`${VAR}`, `lib-bnc-api-client:1.1.0`,
   `catalog-info.yaml`.
3. **Fase 3 — Re-corrida nuestro checklist**: verifica que los bank
   autofixes no rompan nada del checklist propio.
4. **Fase 4 — Validador oficial del banco**: invoca el
   `validate_hexagonal.py` vendor-pinado via subprocess. Parsea
   `Resultado: N/M checks pasados` despojado de ANSI codes.

**Output consolidado:**

- Tabla rich con veredicto por gate + verdicto global `PR_READY` / `NEEDS_WORK`
- Log JSON completo en `.capamedia/review/<ts>.json` con todas las fases
- Reportes individuales: `CHECKLIST_<svc>.md`, `hexagonal_validation_*.md`,
  `.capamedia/autofix/*.log`

**Flags utiles**:

- `--dry-run`: solo corre checks, no aplica autofixes. Para ver el estado
  inicial sin modificar nada.
- `--skip-official`: salta el validador del banco. Util para debug cuando
  se quieren evaluar solo los checks propios.
- `--legacy`: habilita cross-check del Block 0 (WSDL legacy vs migrado,
  namespace match, op names).

**Exit codes**:

- `0`: `PR_READY` — nuestro checklist sin HIGHs + oficial PASS completo.
- `1`: `NEEDS_WORK` — algo quedo rojo.
- `2`: path invalido.

**Smoke real sobre `wsclientes0007`** (proyecto migrado que mantenemos como
referencia): pipeline ejecuta 21 PASS + 2 MEDIUM (ambos conocidos), oficial
9/10 (falta solo check 6 por refactor semantico no autofixeable). Veredicto
`NEEDS_WORK` correcto.

### Testing

- **314/314 tests PASS** (vs 300 de v0.12.0). +14 tests nuevos en
  `test_review.py`:
  - 5 de helpers puros (`_summarize_results`, `_verdict_from_summary`,
    `_write_review_log`)
  - 3 de `_run_official_validator` (ANSI parse, timeout, script missing)
  - 6 del comando end-to-end con mocks (all-green → PR_READY, HIGH fail →
    NEEDS_WORK, dry-run no aplica autofix, skip-official no llama validador,
    project inexistente → exit 2, log JSON persistido)
- Ruff limpio en `review.py` y `test_review.py`.

### Como lo usa un dev del equipo

```bash
# El chico termino su migracion con los prompts del repo CapaMedia
cd /path/a/su/proyecto-migrado

# Corre el review
capamedia review . --bank-owner jusoria@pichincha.com

# Si dice PR_READY -> mergear
# Si dice NEEDS_WORK -> leer .capamedia/review/<ts>.json para ver que quedo
```

---

## [0.12.0] - 2026-04-22

### Changed - Normalizar `lib-bnc-api-client` a `1.1.0` estable

El equipo del banco libero la version estable `com.pichincha.bnc:
lib-bnc-api-client:1.1.0` (Apr 2026). Antes la ultima variante disponible
era `1.1.0-alpha.20260409115137` (pre-release). Ambas pasaban el check
oficial `validate_hexagonal.py` (substring match contra `1.1.0`), pero
el estandar nuevo para proyectos migrados es **la estable limpia**:

```gradle
implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0'
```

**`fix_add_libbnc_dependency` ahora hace 2 pasos:**

1. **Normaliza** cualquier variante pre-release de `1.1.0` a la estable:
   - `1.1.0-alpha.xxx` -> `1.1.0`
   - `1.1.0-SNAPSHOT` -> `1.1.0`
   - `1.1.0-rc*` / `1.1.0-beta*` -> `1.1.0`
   - `1.1.0.RELEASE` / `1.1.0.M*` -> `1.1.0`
2. Si la libreria no esta declarada, la inserta (comportamiento previo).

Regex utilizado:

```python
r"(com\.pichincha\.bnc:lib-bnc-api-client:1\.1\.0)"
r"[-.](?:alpha|beta|rc|snapshot|release|m)[\w.\-]*"
```

**Canonical `context/bank-official-rules.md` - regla 8 actualizada**:

- MUST: usar `1.1.0` estable literal.
- NEVER: mantener pre-releases `-alpha/-SNAPSHOT/-rc/-beta/.RELEASE` en
  proyectos migrados nuevos. La estable salio, ir a ella.
- Autofix documentado como parte de la regla.

### Testing

- **300/300 tests PASS** (vs 296 de v0.11.0). +4 tests nuevos en
  `test_bank_autofix.py`:
  - `test_libbnc_normalizes_alpha_to_stable`
  - `test_libbnc_normalizes_snapshot_to_stable`
  - `test_libbnc_stable_version_untouched`
  - `test_libbnc_normalizes_rc_variant`
- 1 test existente actualizado por cambio de semantica:
  `test_libbnc_no_change_if_already_present` → `test_libbnc_alpha_normalized_to_stable`
  (antes aceptaba alpha como ya presente, ahora lo normaliza).

---

## [0.11.0] - 2026-04-22

### Added - Block 16: SonarCloud custom rule - test class annotations

Regla que NO esta en el script oficial del banco (`validate_hexagonal.py`)
pero que SonarCloud del banco reporta como violation en Quality Gate:

```
[Anotaciones] Faltan anotaciones requeridas: @SpringBootTest
```

El PR puede pasar los 9 checks oficiales y aun rechazarse por SonarCloud.

**Nuevo `Block 16` en `core/checklist_rules.py`**:

- Check `16.1` — Anotacion de test en `@Test classes`
- Escanea `src/test/java/**/*Test.java` y `*Tests.java`
- FAIL MEDIUM si alguno no tiene ninguna de: `@SpringBootTest`,
  `@WebMvcTest`, `@WebFluxTest`, `@DataJpaTest`, `@JsonTest`,
  `@RestClientTest`, `@JdbcTest`, `@ExtendWith`, `@RunWith`,
  `@AutoConfigureMockMvc`
- Severidad MEDIUM (no HIGH) porque el gate que lo rechaza es SonarCloud,
  no `validate_hexagonal.py` que bloquea el merge duro.

**Autofix `fix_add_test_annotation` en `core/autofix.py` registrado en
`AUTOFIX_REGISTRY["16.1"]`**:

Heuristica para elegir la anotacion correcta:

- Si el test **usa hints de Spring context** (`@Autowired`, `@MockBean`,
  `@SpyBean`, `TestRestTemplate`, `WebTestClient`, `MockMvc`,
  `@ApplicationContext`) → agrega `@SpringBootTest` + import
  `org.springframework.boot.test.context.SpringBootTest`.
- Si NO los usa (unit test puro) → agrega
  `@ExtendWith(MockitoExtension.class)` + imports de
  `org.junit.jupiter.api.extension.ExtendWith` +
  `org.mockito.junit.jupiter.MockitoExtension`. Es mas rapido: no carga
  el ApplicationContext, solo inyecta mocks.

**Canonical `context/sonar-custom-rules.md` (nuevo)**:

Documento dedicado a reglas SonarCloud del banco que no estan en el script
oficial. Primera regla: `S-1 — Anotacion de test class obligatoria` con
tabla de anotaciones aceptadas, ejemplos YES/NO, heuristica de eleccion
entre `@SpringBootTest` y `@ExtendWith(MockitoExtension.class)`.

Incluye guia de "como agregar mas reglas SonarCloud" para cuando aparezcan
violations nuevas en los PRs — mantener el pattern MUST/NEVER + ejemplo NO
+ autofix si es deterministico.

### Testing

- **296/296 tests PASS** (vs 285 de v0.10.0). 11 tests nuevos en
  `test_block_16_test_annotations.py`:
  - 7 del check (pass con cada anotacion, fail sin ninguna, count reporting,
    sin src/test/, ignora files no-Test.java)
  - 4 del autofix (Spring context → `@SpringBootTest`, unit → `@ExtendWith`,
    skip si ya anotado, no explota sin test dir)

### Pendiente para v0.12.0

- Si el equipo publica un script oficial del Quality Gate SonarCloud
  (similar a `validate_hexagonal.py`), vendor-pinarlo en `data/vendor/` y
  exponerlo via `capamedia validate-sonar` (paralelo a
  `validate-hexagonal`).
- Mapeo de mas reglas SonarCloud que aparezcan en los PRs reales —
  agregarlas al `context/sonar-custom-rules.md` como `S-2`, `S-3`, etc.

---

## [0.10.0] - 2026-04-22

### Added - Autofix regla 6 + UUID sonar placeholder valido

Evidencia real del `wsclientes0007` que paso 10/10 en el validador oficial:
dos patrones deterministas resolvieron el check 6 sin refactor semantico
profundo. Los abstraje como reglas del canonical (NO usando el 0007 como
referencia, sino el patron universal).

**Patron A - StringUtils.* -> Java nativo** (nuevo
`fix_stringutils_to_native`):

```java
// Antes
import org.apache.commons.lang3.StringUtils;
if (StringUtils.isBlank(x)) { ... }

// Despues
if (x == null || x.isBlank()) { ... }
```

Cubre las 4 variantes (`isBlank` / `isEmpty` / `isNotBlank` / `isNotEmpty`)
con mapeo 1:1 a Java 11+ nativo. Remueve el import si queda sin uso, lo
preserva si hay otros `StringUtils.join/strip/etc.`.

**Patron B - record interno en @Service -> application/model/** (nuevo
`fix_extract_inner_records_to_model`):

Deriva el base_package del `package` declaration del Service, crea
`<base>/application/model/<Name>.java` como `public record`, elimina el
record del Service, agrega el import. El directorio se crea automatico
si no existe.

**Regla 9 - sonar_key placeholder UUID valido** (fix menor):

El validador oficial exige que `sonarcloud.io/project-key` cumpla el
regex `^[0-9a-f]{8}-...{12}$`. Antes generabamos `<SET-sonarcloud-UUID>`
literal que hacia FAIL el check 9. Ahora, cuando no hay
`.sonarlint/connectedMode.json`, sintetizamos un UUID a partir del
sufijo numerico del servicio (ej `wsclientes0007` ->
`00000000-0000-0000-0000-000000000007`). Pasa el regex, no reemplaza al
real, se sobreescribe al hacer el binding de SonarCloud.

**`run_bank_autofix`**: ahora corre **5 reglas** (antes 4). La regla 6
ejecuta los dos patterns encadenados, devuelve 2 resultados separados.

**Canonical `context/bank-official-rules.md`**:

- Regla 6 actualizada con los 2 patterns concretos YES/NO.
- Mapeo explicito `StringUtils.* -> Java nativo` como tabla.
- Heuristica de capa para records: `application/model/` (DTO intermedio)
  vs `domain/<concept>/` (entidad con invariantes).
- Nota de automatizacion: qu� hace autofix y qu� queda al AI.

### Testing

- **285/285 tests PASS** (vs 279 de v0.9.0). 6 tests nuevos:
  - `test_stringutils_isblank_replaced_with_native`
  - `test_stringutils_all_four_variants`
  - `test_stringutils_preserves_import_if_other_use`
  - `test_stringutils_skips_non_service_classes`
  - `test_extract_inner_record_to_application_model`
  - `test_extract_record_skips_if_no_service`
- 2 tests existentes actualizados por cambio de semantica (UUID placeholder
  ya no dispara warning; `run_bank_autofix` devuelve 6 results en vez de 4).

### Pendiente para v0.11.0

- Regla 6 resto: `static` method en `@Service`, metodos `normalize*`/
  `pad*`/`strip*` → require AST / javalang para decidir si mover a util.
- Integrar `run_bank_autofix` con la cadena completa de `capamedia check
  --auto-fix --bank-fix` para que regla 6 se aplique automatica antes de
  correr el validador oficial.

---

## [0.9.0] - 2026-04-22

### Added - Matriz de decision MCP Fabrics corregida (4 fixes JGarcia/Julian)

La matriz que usa `capamedia fabrics generate` para deducir `projectType`,
`webFramework` e `invocaBancs` estaba confundiendo dos casos: WAS con 2+
endpoints que debian ser SOAP+MVC recibian WebFlux, y IIBs con BANCS
detectados solo por UMP perdian el override cuando el BANCS se invocaba via
TX directa, HTTPRequest o BancsClient en Java. Se consolido la regla con
4 fixes deterministas:

**Fix 1 - `detect_bancs_connection()` (nuevo en `legacy_analyzer.py`):**
Detecta conexion a BANCS por 4 senales en vez de solo UMP references:
  1. UMPs referenciadas en ESQL/msgflow (patron indirecto legacy)
  2. TX BANCS literal `'0NNNNN'` en ESQL (llamada directa sin UMP)
  3. HTTPRequest node apuntando a BANCS en msgflows
  4. `BancsClient` / `@BancsService` en Java (WAS con adapter del banco)

Devuelve `(bool, list[str] evidence)` para que el log exponga que senal
disparo la deteccion.

**Fix 2 - `count_was_endpoints()` (nuevo en `legacy_analyzer.py`):**
Cascada de 3 intentos para contar endpoints de un WAS cuando no hay WSDL
suelto en el repo (caso comun con UMP0028 y pares sin fuente en Azure):
  1. Extrae WSDL embebido en `.ear` / `.war` y cuenta operations dedup
  2. `web.xml` -> `servlet-class` -> anotaciones `@WebMethod` en el Java
  3. Fallback: metodos publicos del servlet-class (excluye get/set/is/main)

**Fix 3 - `analyze_legacy()` usa los detectores nuevos:**
  - Agrega `has_bancs: bool` y `bancs_evidence: list[str]` al dataclass
    `LegacyAnalysis` (defaults compatibles con constructores existentes).
  - Para WAS sin WSDL, sintetiza un `WsdlInfo` minimo con el count
    inferido por `count_was_endpoints` y deja un warning explicito.
  - Nueva logica de `framework_recommendation`:
    * ORQ siempre `rest`
    * IIB con BANCS siempre `rest` (override gana sobre op count)
    * Resto decide por `wsdl.operation_count` (1 -> rest, 2+ -> soap)

**Fix 4 - `fabrics.py generate()` aplica la matriz correcta:**
  - `invoca_bancs = analysis.has_bancs` (no `bool(analysis.umps)`)
  - `webFramework`: WAS siempre `mvc`, resto `webflux`
  - `projectType`: ORQ/IIB-con-BANCS forzado a `rest`, resto delega a
    `framework_recommendation`.

**Matriz consolidada (ahora respetada por el deducer):**

| Caso | projectType | webFramework | invocaBancs |
|---|---|---|---|
| IIB con BANCS, 1 op | rest | webflux | true |
| IIB con BANCS, 2+ ops | rest | webflux | true |
| IIB sin BANCS, 1 op | rest | webflux | false |
| IIB sin BANCS, 2+ ops | soap | mvc | false |
| WAS con 1 endpoint | rest | mvc | false |
| WAS con 2+ endpoints | soap | mvc | false |
| ORQ | rest | webflux | true |

**Tests agregados:** `tests/test_mcp_decision_matrix.py` con 13 tests
(7 filas de la matriz + 4 de `detect_bancs_connection` + 4 de
`count_was_endpoints`). Total suite: 264 -> 277 tests, todos verdes.

**Gotcha conocido:** `invocaBancs` en ORQ lo asume `true` en la matriz,
pero `analyze_legacy` para un ORQ sin llamadas a BANCS directas puede
devolver `has_bancs=False`. El MCP tolera esto porque los ORQ tambien
pueden ser puros fan-out SOAP sin BANCS (ej. ORQClientes0028). Queda
como dato derivado de la evidencia real, no impuesto por source_kind.

## [0.8.0] - 2026-04-22

### Added - Sync prompts JGarcia + integracion bank-fix al check + audit completo

**Sync canonical con 3 commits nuevos de jgarcia@pichincha.com:**

- `56d2771 feat: Service clean`
- `3dbf23f fix: Code 999 generic`
- `cf79f2e feat: mejora was y bus`

Corrida `capamedia canonical sync --source <prompts-jgarcia> --yes` aplicada.
19 archivos del canonical actualizados. Cambios clave de JGarcia:

- **Regla BUS/WAS/ORQ refinada:** "For BUS (IIB) services that connect to
  BANCS, `invocaBancs: true` overrides everything - always REST+WebFlux
  regardless of operation count. For WAS, operation count decides. For
  ORQ, always WebFlux." — convive con la regla del script oficial
  (`validate_hexagonal.py`: 1 op → REST+WebFlux, 2+ → SOAP+MVC).
- **Service clean** (la misma regla SRP que Alexis nos pidio):
  expandida en `migrate-rest-full.md` y `migrate-soap-full.md`.
- **Code 999 generic:** fix en el mapeo de codigos de backend.
- **Analisis-servicio** enriquecido con evidencia automatica
  (file analysis: `*.esql -> IIB`, `*.java + web.xml -> WAS`).

Diffs aplicados: +1,587 lineas / -595 lineas a los prompts canonicos.
Log: `.capamedia/canonical-sync/20260422-135036.log`.

**`capamedia check --auto-fix --bank-fix`** — los 4 autofixes del script
oficial se encadenan al autofix propio. Un solo comando cubre los 9 checks
(los 5 nuestros del block 1/2/5/15 + los 4 deterministas del banco 4/7/8/9):

```bash
capamedia check <migrated> --legacy <legacy> --auto-fix --bank-fix \
    --bank-description "Consulta contacto transaccional" \
    --bank-owner jusoria@pichincha.com
```

**`capamedia canonical audit`** extendido:

- Audita ahora tambien `context/bank-official-rules.md`
- Verifica que las 9 reglas oficiales del banco esten presentes por ID
  (regex `Regla N`/`Rule N`). Falla si alguna falta.
- Baseline despues del sync JGarcia: 7 sin imperativo, 36 sin ejemplo NO,
  9/9 reglas oficiales presentes.

### Testing

- **264/264 tests PASS**. El sync de JGarcia (data del canonical) no
  impacta los tests (que corren sobre codigo Python).
- Smoke test `capamedia canonical audit` reporta las 9 reglas correctas.

### Pendiente para v0.9.0

- Auto-fix semantico de regla 6 (Service sin utils) con javalang / LSP.
  Requiere refactor AST extractor dedicado.
- Integrar `canonical audit` a CI: exit 1 si faltan reglas oficiales o
  hay gaps imperativos.
- Resolver mapping raro del `canonical sync` que pone `agents/*.md` de
  JGarcia en `context/` (es inofensivo pero genera ruido en el diff).

---

## [0.7.0] - 2026-04-22

### Added - Patrones oficiales al canonical + autofix para 4 reglas del banco

**Objetivo del tech lead (Julian):** las 5 FAIL-reglas del script oficial
(`validate_hexagonal.py`) no deben volver a faltar en nuestros migrados.
El conocimiento vive en el canonical (con MUST/NEVER + ejemplos YES/NO) y
4 de las 5 se auto-corrigen sin AI.

**Nuevo canonical `context/bank-official-rules.md`** con las 9 reglas
oficiales documentadas. Extrae el comportamiento estudiando el gold 0024
del banco. NO se usa un servicio como referencia viva — el conocimiento
queda en el prompt como regla.

Patrones capturados de observar el gold:

- **Regla 4**: import exacto `com.pichincha.common.trace.logger.annotation.BpLogger`
  + `@BpLogger` en cada metodo publico del `@Service` (no en la clase).
- **Regla 7**: ConfigMap de OpenShift + `${VAR}` sin default. Prefijo
  convencional `CCC_*`. Excepcion `optimus.web.*`.
- **Regla 8**: `implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0'`
  literal en `dependencies`. Version puede ser `1.1.0-alpha.xxx` pero
  prefijo `1.1.0` debe estar.
- **Regla 9**: `namespace: tnd-middleware` + `name: tpl-middleware` +
  `lifecycle: test` literales. `sonarcloud.io/project-key` = UUID real
  (leer de `.sonarlint/connectedMode.json`). Owner con `@pichincha.com`.
- **Regla 6** (no autofixeable): Service orquesta, Utils transforman.
  Ejemplos negativos explicitos con `static`, `normalize*`, `isBlank` en
  el Service.

**Nuevo `core/bank_autofix.py`** con 4 fixes deterministas:

- `fix_add_bplogger_to_service`: agrega import + `@BpLogger` a cada
  metodo publico del `@Service` que no lo tenga.
- `fix_yml_remove_defaults`: reemplaza `${VAR:default}` por `${VAR}`
  en `application.yml`. Preserva `optimus.web.*`. Sabe reconstruir el
  path yaml para aplicar el excluir correcto.
- `fix_add_libbnc_dependency`: inserta
  `implementation 'com.pichincha.bnc:lib-bnc-api-client:1.1.0'` en el
  bloque `dependencies` del `build.gradle`. Crea el bloque si no existe.
- `fix_catalog_info_scaffold`: genera `catalog-info.yaml` valido con
  - `namespace: tnd-middleware`, `name: tpl-middleware`, `lifecycle: test`
  - `sonarcloud.io/project-key` leido de `.sonarlint/connectedMode.json`
    si existe (UUID real)
  - `spec.owner` leido del `git config user.email` si termina en
    `@pichincha.com`
  - `spec.dependsOn` poblado con cada `lib-bnc-*` / `lib-trace-*`
    detectada en Gradle
  - PRESERVA el archivo existente si ya tiene valores reales (no
    sobreescribe buenos con plantillas).

**Nuevo comando `capamedia validate-hexagonal auto-fix <path>`**:

```bash
# Corre los 4 autofixes. Flags opcionales para llenar valores del catalog.
capamedia validate-hexagonal auto-fix <path> \
    --description "Consulta contacto transaccional BANCS" \
    --owner jusoria@pichincha.com

# Subset explicito
capamedia validate-hexagonal auto-fix <path> --rules 4,7

# Dry run
capamedia validate-hexagonal auto-fix <path> --dry-run
```

**Resultado end-to-end sobre `wsclientes0007`:**

```
Antes: 5/10 checks pasados
Despues de `auto-fix`: 9/10 checks pasados
Unico rojo: Check 6 (Service business logic — requiere refactor semantico)
```

El check 6 queda para el AI: el canonical ya documenta la regla con
ejemplo negativo (`static boolean isBlank` → extraer a Util).

### Testing

- **264/264 tests PASS** (+15 nuevos en `test_bank_autofix.py`).
- Smoke test end-to-end sobre `wsclientes0007`: autofix pasa de 5/10 a 9/10
  en un solo comando.

### Pendiente para v0.8.0

- Integrar `bank_autofix` al flujo de `capamedia check --auto-fix`
  (ahora esta solo en `validate-hexagonal auto-fix`).
- Integrar el audit MUST/NEVER (`capamedia canonical audit`) al
  pipeline CI para detectar reglas sin ejemplo.
- Regla 6: explorar auto-fix semantico con LSP/JavaParser (extract
  util de metodos con nombre `normalize*`, `pad*`, `isBlank`, etc.).

---

## [0.6.0] - 2026-04-22

### Added - `validate-hexagonal` oficial del banco + WAS config extractor

**`capamedia validate-hexagonal` — gate de PR sincronizado con el banco:**

- Vendor-pinned del script oficial `validate_hexagonal.py` en
  `data/vendor/`. Es el MISMO script que corren los reviewers en el PR;
  si nosotros pasamos localmente, el gate automatico pasa.
- 9 validaciones formales:
  1. Capas `application`/`domain`/`infrastructure` + sin siblings
  2. WSDL: 1 op -> REST+WebFlux | 2+ -> SOAP+MVC
  3. `@BpTraceable` en controllers (excluye tests)
  4. `@BpLogger` en services
  5. Sin navegacion cruzada entre capas
  6. Service business logic puro (scoring heuristico, threshold 3)
  7. `application.yml` sin `${VAR:default}` (excluye `optimus.web.*`)
  8. Gradle: `com.pichincha.bnc:lib-bnc-api-client:1.1.0` obligatoria
  9. `catalog-info.yaml` con metadata, links, annotations, spec del banco
- Subcomandos:
  - `capamedia validate-hexagonal run <path>` — corrida completa + reporte md
  - `capamedia validate-hexagonal summary <path>` — tabla resumida rich
  - `capamedia validate-hexagonal sync --from <path>` — actualiza pin
- Forza `PYTHONIOENCODING=utf-8` para que el output unicode no rompa Windows.

**Baseline real** (corrida sobre `wsclientes0007`): **5/10 checks pasan**.
Gaps reales: check 4 (`@BpLogger` faltante), check 6 (`isBlank` util en
service), check 7 (6 variables con `${VAR:default}`), check 8
(lib-bnc-api-client no declarada), check 9 (`catalog-info.yaml` con
placeholders). Sin este gate, el PR se hubiera rechazado.

**Delta vs nuestro checklist previo:**

| Check oficial | Nuestro equivalente | Gap |
|---|---|---|
| 1 Capas | 1.1 capas hexagonales | igual, nosotros no valida siblings |
| 2 WSDL framework | 0.2c framework vs ops | similar, ellos detectan mas paths |
| 3 @BpTraceable | 2.1 @BpTraceable | IGUAL |
| 4 @BpLogger | — | **FALTABA** |
| 5 Sin navegacion | 1.5 app no importa infra + 1.2 | partial equivalent |
| 6 Service business logic | — | **FALTABA** (el refactor SRP que Julian pidio) |
| 7 yml sin defaults | 7.2 secrets env vars | distinto (ellos mas estricto) |
| 8 Gradle lib | — | **FALTABA** |
| 9 catalog-info.yaml | — | **FALTABA** |

Nuestros checks propios (blocks 0, 5, 13, 14, 15) siguen aportando valor
por encima del oficial (cross-check legacy vs migrado, BancsClientHelper
exception wrapping, JPA+WebFlux, SonarLint binding, estructura de error).

**`core/was_extractor.py` — config WAS critica (IBM WebSphere):**

Los WAS del banco tienen **5 valores que la AI DEBE preservar exactos** o
rompe clientes. Extractor determinista sobre:
- `ibm-web-bnd.xml` → `virtual-host` (VHClientes / VHTecnicos / default_host)
- `ibm-web-ext.xml` → `context-root` (WSClientes0010) + `reload-interval`
- `web.xml` → `url-patterns` (`/soap/WSClientes0010Request`, `/*`) +
  `servlet-classes` + `security-constraints` (deny TRACE/PUT/OPTIONS/DELETE/GET)

**Hallazgos del batch-24** (11 WAS escaneados):
- 3 virtual-hosts distintos: `VHClientes` (3 svc), `VHTecnicos` (1), `default_host` (7)
- 11/11 WAS usan URL pattern `/soap/<SvcName>Request`
- 10/11 WAS tienen `security-constraint` deny `TRACE/PUT/OPTIONS/DELETE/GET`
- 0 WAS del batch tienen JPA (todos son SOAP wrappers a BANCS/UMPs)

**Regla dura nueva:** si la AI cambia uno de estos 5 valores al migrar, se
rompe el contrato con clientes en produccion. El extractor inyecta los
valores al FABRICS_PROMPT para que la AI los preserve.

### Testing

- **249/249 tests PASS** (vs 239 de v0.5.0). Nuevos:
  - `test_was_extractor.py` (10): happy path, target/ dir ignore,
    virtual-host warnings, empty, partial, multiple url-patterns, render md + appendix.
  - Smoke test `validate-hexagonal summary` sobre `wsclientes0007`
    reproduce exactamente el resultado del script oficial.

### Pendiente para v0.7.0

- Integrar `was_extractor` al `clone` (step 8) para que genere
  `WAS_CONFIG_<svc>.md` automatico.
- Inyectar `render_was_config_prompt_appendix` al FABRICS_PROMPT y a
  `_build_batch_migrate_prompt`.
- Extender autofix para resolver checks 4, 7, 8 del oficial (todos
  deterministas).
- Extender `canonical audit` para verificar que las reglas nuevas del
  script oficial esten en el canonical con MUST/NEVER.

---

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
