# capamedia-cli - v0.28.1

CLI multi-harness para migrar servicios legacy (IIB / WAS / ORQ) de Banco Pichincha a Java 21 + Spring Boot hexagonal **OLA 1 / OLA 2**.

Un solo canonical, 6 harnesses soportados: **Claude Code · Cursor · Windsurf · GitHub Copilot · OpenAI Codex · opencode**.

---

## Que hace

Separa claramente tres responsabilidades:

1. **Setup local**: `capamedia install`, `capamedia check-install`, `capamedia pat`, `capamedia auth bootstrap`, `capamedia init`, `capamedia fabrics setup`
2. **Trabajo por servicio**: `capamedia clone`, `capamedia fabrics generate`, `capamedia ai migrate`, `capamedia ai doublecheck`, `capamedia review`, `capamedia qa prepare`, `capamedia documentacion`
3. **Fabrica batch**: `capamedia batch complexity|clone|init|pipeline|migrate|check|review|watch|engines`

El CLI genera assets nativos del harness elegido, pero el flujo operativo portable vive en comandos shell. Para Fabrics usa siempre el MCP del banco como gate del arquetipo; si el arquetipo no sale de Fabrics, la migracion no avanza.

```text
install -> check-install -> pat / auth bootstrap -> init -> fabrics setup
                                      |
                                      v
          clone -> fabrics generate -> ai migrate -> ai doublecheck -> review
                                      |
                                      v
                qa prepare -> /qa (analisis) -> qe-migration -> /qacases
                                      |
                                      v
                            documentacion -> Confluence HTML
                                      |
                                      v
                         batch pipeline / batch migrate / batch watch
```

A partir de `v0.25.0` el pipeline QA es nativo: `qa prepare` clona legacy + migrado y deja el workspace listo para los 3 pasos del banco — `/qa` paso 1 (analisis comparativo, go/no-go, Diffy), `qe-migration` paso 2 (casos BDD Gherkin, payloads, matriz de riesgos en `docs/qa/**`) y `/qacases` paso 3 (tests Karate `.feature` ejecutables dentro del microservicio).

---

## Instalacion

> 📘 **Guia completa Windows + macOS con troubleshooting:** [`docs/INSTALL.md`](docs/INSTALL.md)
>
> Cubre paso-a-paso: winget/Homebrew, Python 3.12, uv, Git, GCM, Java 21, Gradle,
> Node 20, VS Code + SonarLint, Claude Code/Codex, Azure Artifacts, y los
> errores tipicos que ya fixeamos (UnicodeDecodeError, PATH de Python 3.14,
> init con subcarpeta anidada, UMPs en tpl-integration-services-was, etc).

Quick install:

```bash
# Recomendado — isolated con uv (agrega capamedia al PATH automatico)
uv tool install capamedia-cli --from .

# Alternativa — editable con pip
pip install -e .
```

**Importante si usas `pip install -e .`**: en Windows, el binario
`capamedia.exe` se instala en `%USERPROFILE%\AppData\Local\Python\
pythoncore-<ver>-64\Scripts\` y ese directorio no siempre esta en PATH
por default. Si te da `capamedia: command not found`, agregalo:

```powershell
# Sesion actual
$env:PATH += ";$env:USERPROFILE\AppData\Local\Python\pythoncore-3.14-64\Scripts"

# Permanente (usuario)
[Environment]::SetEnvironmentVariable(
  "PATH",
  [Environment]::GetEnvironmentVariable("PATH", "User") + ";$env:USERPROFILE\AppData\Local\Python\pythoncore-3.14-64\Scripts",
  [EnvironmentVariableTarget]::User
)
```

Con `uv tool install` este problema no aparece — uv resuelve el PATH solo.

## Setup de una maquina

### 1. Toolchain

```bash
capamedia install
capamedia check-install
```

`capamedia install` instala el toolchain automatizable:

- Git
- Java 21
- Gradle
- Node.js LTS
- Codex CLI
- Python 3.12
- uv
- VS Code

### 2. Credenciales y MCP

> **Desde la version Unreleased (post v0.26.4)** la persistencia de credenciales
> es automatica: `auth bootstrap` escribe `~/.capamedia/user.env` (Unix) o el
> registro de usuario (Windows) sin necesidad del flag `--env-file` ni de
> exportar variables en `.zshrc` / `.bashrc`. El modulo `core/auth.py` lee ese
> archivo al importarse, asi que `capamedia clone` y el resto de comandos ven
> el PAT al instante.

Bootstrap recomendado para una Mac o runner que va a ejecutar batch unattended:

```bash
capamedia auth bootstrap \
  --scope global \
  --artifact-token <AZURE_ARTIFACTS_PAT> \
  --azure-pat <AZURE_DEVOPS_PAT> \
  --openai-api-key <OPENAI_API_KEY>
```

Esto hace cuatro cosas:

- persiste `CAPAMEDIA_ARTIFACT_TOKEN`, `CAPAMEDIA_AZDO_PAT` y `OPENAI_API_KEY`
  en `~/.capamedia/user.env` (Unix) o en el registro de usuario (Windows)
- registra Fabrics en `~/.mcp.json`
- refresca `~/.npmrc` para `@pichincha/fabrics-project`
- autentica Codex CLI via `codex login --with-api-key`

Si usas el mismo Personal Access Token para Azure Artifacts y Azure DevOps
(PAT con permisos amplios), el camino simple es:

```bash
capamedia pat <PERSONAL_ACCESS_TOKEN>
```

Para una VDI/Windows donde ademas queres dejar el PATH configurado en el
usuario sin editar variables a mano:

```bash
capamedia pat <PERSONAL_ACCESS_TOKEN> \
  --path "%APPDATA%\\Python\\Python314\\Scripts"
```

Esto persiste `CAPAMEDIA_ARTIFACT_TOKEN`, `ARTIFACT_TOKEN`,
`CAPAMEDIA_AZDO_PAT`, `AZURE_DEVOPS_EXT_PAT`, agrega el `--path` al PATH del
usuario y registra Fabrics global + `~/.npmrc` con ese mismo PAT. Antes de
persistir nada prueba el PAT contra Azure DevOps y Azure Artifacts. Desde
`Unreleased` el comando es tolerante: un 401 contra Azure DevOps sigue siendo
critico y aborta, pero un 404 en un feed especifico de Artifacts se reporta
como `WARN` y la configuracion se guarda igual. No imprime los secretos; en
Windows hay que abrir una terminal nueva para que las vars entren en efecto.

Si no queres usar `auth bootstrap`, tambien podes hacer cada paso por separado:

```bash
capamedia fabrics setup --scope global --refresh-npmrc
codex login
```

### 3. Paso manual que sigue existiendo

Lo unico que queda manual por ahora es SonarCloud connected mode / SonarQube for IDE.

---

## Flujo por servicio

```bash
mkdir -p "C:/Dev/Banco Pichincha/CapaMedia/wsclientes0008"
cd "C:/Dev/Banco Pichincha/CapaMedia/wsclientes0008"

capamedia init wsclientes0008 --ai codex
```

Eso genera, segun el harness:

- `.claude/commands/*`
- `.cursor/rules/*`
- `.github/prompts/*`
- `.codex/prompts/*`
- `.codex/agents/*.toml`
- `.agents/skills/*/SKILL.md`
- `CLAUDE.md` o `AGENTS.md`
- `.mcp.json`
- `.sonarlint/connectedMode.json`

Flujo recomendado por servicio:

```text
capamedia clone <servicio> -> capamedia fabrics generate -> capamedia ai migrate -> capamedia ai doublecheck -> capamedia review
                                                                                                                       |
                                                                                                                       v
                                                                            capamedia qa prepare -> /qa -> qe-migration -> /qacases
                                                                                                                       |
                                                                                                                       v
                                                                                                  capamedia documentacion
```

`capamedia review` admite forzar el `source_type` cuando la deteccion automatica
puede confundirse (ORQ con catalog `tpl-middleware`, WAS con Spring WS, etc.):

```bash
capamedia review orq   # fuerza Block 20 (ORQ -> migrado, no legacy)
capamedia review bus   # aplica matriz BUS + invocaBancs -> REST
capamedia review was   # aplica matriz WAS: 1op REST / 2+ops SOAP
```

Los slash commands legacy pueden seguir existiendo en algunos harnesses, pero
no son la entrada recomendada para Codex ni para el flujo multi-IA.

### Pipeline QA (desde v0.25.0)

Reemplaza al viejo `qa-generator`. Son 3 pasos canonicos del banco:

```bash
# 1. Prepara workspace: clona legacy + migrado y deja apuntado /qa
capamedia qa prepare <servicio>

# 2. En Claude Code / Copilot / Codex, dentro del workspace preparado:
#    /qa         -> Paso 1: analisis comparativo legacy vs migrado, go/no-go, Diffy
#                  Paso 2: handoff al agente qe-migration que escribe
#                  docs/qa/** (criterios, BDD Gherkin, payloads, matriz de riesgos)
#    /qacases    -> Paso 3: implementa los casos como tests Karate .feature
#                  ejecutables, configura build.gradle, runner JUnit5,
#                  karate-config.js
```

El paso 3 (`/qacases`, v0.26.0) consume los specs del paso 2 — no regenera
el documento de casos de uso.

---

## Fabrica paralela

### Batch migrate

Cuando los workspaces ya existen y `destino/` ya fue generado por Fabrics:

```bash
capamedia batch migrate \
  --from services.txt \
  --root "C:/Dev/Banco Pichincha/CapaMedia" \
  --workers 3 \
  --resume \
  --retries 2
```

Este comando:

- ejecuta Codex CLI por defecto (`codex exec`) una vez por servicio
- usa GPT-5.5 + `xhigh` si el workspace fue generado por `capamedia init --ai codex`
- permite override explicito con `--model gpt-5.5 --reasoning-effort xhigh`
- exige evidencia previa de Fabrics en `.capamedia/fabrics.json`
- exige salida final estructurada por JSON Schema
- guarda prompt, stdout, stderr y last message en `.capamedia/batch-migrate/`
- corre checklist post-migracion por defecto

### Batch pipeline

Para correr la cadena completa desde cero por servicio:

```bash
capamedia batch pipeline \
  --from services.txt \
  --root "C:/Dev/Banco Pichincha/CapaMedia" \
  --namespace tnd \
  --workers 2 \
  --resume \
  --retries 2
```

Ese comando encadena:

```text
clone -> init -> fabrics generate -> codex exec -> check
```

Garantias del pipeline:

- `Fabrics` es prerequisito duro
- `Codex` es el engine headless default; usar `--engine claude` o `--engine auto` si se quiere Claude
- `--reasoning-effort` permite `low | medium | high | xhigh` para Codex, con `xhigh` como default recomendado
- `batch-state/*.json` permite resume por etapa
- `--retries` reintenta solo lo fallido o pendiente
- Azure DevOps puede correr unattended via `CAPAMEDIA_AZDO_PAT`

### Mirador operativo

```bash
capamedia batch watch "C:/Dev/Banco Pichincha/CapaMedia" --kind auto --follow
```

Muestra por servicio:

- fase actual
- intentos
- ultimo update
- estado de Fabrics
- proyecto objetivo

---

## Cross-platform

Esta version corre desde macOS, Linux o Windows:

- `fabrics setup` genera `.mcp.json` con `npx -y @pichincha/fabrics-project@latest`
- el launcher de MCP soporta cache `npm` tanto en Windows (`AppData`) como en Unix (`~/.npm/_npx`)
- `clone` soporta PAT por env sin prompts y, desde `v0.26.4`, diagnostica el caso "PAT valido pero git no lo aplica" (git <2.31, credential helper macOS)
- la persistencia de credenciales es nativa por SO: `~/.capamedia/user.env` en Unix, registro de usuario en Windows (desde Unreleased)
- `install` y `check-install` ya contemplan Codex CLI
- hay workflow de CI y workflow de release

---

## Comandos principales

### Setup y diagnostico

| Comando | Uso |
|---|---|
| `capamedia install` | instala el toolchain automatizable |
| `capamedia check-install` | valida toolchain, Fabrics, Azure auth, Codex auth, Sonar binding |
| `capamedia doctor` | diagnostico extendido del entorno |
| `capamedia status` | estado del workspace actual |
| `capamedia info` | dashboard de pendientes (v0.23.12+) |
| `capamedia update` | autoupdate del CLI |
| `capamedia version` | imprime version actual |

### Credenciales

| Comando | Uso |
|---|---|
| `capamedia pat <token>` | configura un PAT unico para Azure DevOps + Artifacts (tolerante a 404 en feeds desde Unreleased) |
| `capamedia auth bootstrap` | registra Fabrics, autentica Codex y persiste credenciales en `~/.capamedia/user.env` (auto desde Unreleased) |
| `capamedia auth configure-user` | persiste credenciales del usuario y entradas de PATH sin imprimir secretos |

### Por servicio

| Comando | Uso |
|---|---|
| `capamedia init` | scaffold del workspace y harnesses |
| `capamedia adopt` | adopta un workspace no-canonico (v0.23.11+) |
| `capamedia clone <svc>` | clona legacy, UMPs y TX; acepta `--legacy-repo` para nomenclaturas no estandar (v0.24.5) |
| `capamedia clone-migrated` | trae legacy + UMPs + TX + repos migrados existentes desde `tpl-middleware` |
| `capamedia fabrics setup` | registra el MCP Fabrics |
| `capamedia fabrics generate` | invoca el MCP y genera `destino/` |
| `capamedia fabrics preflight` | valida prerequisitos antes de invocar Fabrics |
| `capamedia ai migrate` | migracion AI headless del workspace actual (Codex/Claude) |
| `capamedia ai doublecheck` | doble check AI post-migracion; no reemplaza `review` |
| `capamedia check` / `checklist` | corre el checklist deterministico |
| `capamedia review [orq\|bus\|was]` | auditoria final deterministica; subcomando opcional para forzar `source_type` |
| `capamedia qa prepare <svc>` | prepara workspace QA (clona legacy + migrado) y apunta a `/qa` |
| `capamedia qa pack` | empaqueta evidencia QA |
| `capamedia documentacion` | genera HTML Confluence-friendly o Markdown del servicio |
| `capamedia upgrade` | upgrade del workspace canonico |
| `capamedia discovery edge-case` | extrae casos de borde desde WSDL/XSD a `.capamedia/` |

### Batch

| Comando | Uso |
|---|---|
| `capamedia batch complexity` | rankea servicios por complejidad |
| `capamedia batch clone` | clona N servicios |
| `capamedia batch init` | scaffold N workspaces |
| `capamedia batch pipeline` | fabrica completa por servicio (clone -> init -> fabrics -> codex -> check) |
| `capamedia batch migrate` | migracion headless sobre workspaces ya preparados |
| `capamedia batch check` | checklist en lote |
| `capamedia batch review` | review en lote |
| `capamedia batch watch` | mirador operativo del lote |
| `capamedia batch engines` | inspecciona engines disponibles (Codex/Claude) |

### Canonical y validador oficial

| Comando | Uso |
|---|---|
| `capamedia canonical sync` | sincroniza prompts/skills/agents/context |
| `capamedia canonical diff` | diff vs canonical |
| `capamedia canonical audit` | audita assets del workspace |
| `capamedia validate-hexagonal run` | corre los 9 checks formales del validador oficial vendored |
| `capamedia validate-hexagonal summary` | resumen del ultimo run |
| `capamedia validate-hexagonal sync` | actualiza el script vendored desde el banco |
| `capamedia validate-hexagonal auto-fix` | aplica autofixes deterministicos |

---

## Harnesses soportados

| Harness | Flag | Que genera |
|---|---|---|
| Claude Code | `claude` | `.claude/commands/`, `.claude/agents/`, `.claude/skills/`, `CLAUDE.md` |
| GitHub Copilot | `copilot` | `.github/prompts/`, `.github/copilot-instructions.md` |
| Cursor | `cursor` | `.cursor/rules/*.mdc` |
| Windsurf | `windsurf` | `.windsurf/rules/`, `.windsurfrules` |
| OpenAI Codex CLI | `codex` | `.codex/prompts/`, `.codex/agents/*.toml`, `.agents/skills/`, `.codex/config.toml`, `AGENTS.md` |
| opencode | `opencode` | `.opencode/`, `opencode.json`, `AGENTS.md` |

---

## Repo layout

```text
capamedia-cli/
├── pyproject.toml
├── CHANGELOG.md
├── .github/workflows/
│   ├── ci.yml
│   └── release.yml
├── src/capamedia_cli/
│   ├── cli.py
│   ├── commands/
│   │   ├── adopt.py
│   │   ├── ai.py
│   │   ├── auth.py
│   │   ├── batch.py
│   │   ├── canonical.py
│   │   ├── check.py
│   │   ├── check_install.py
│   │   ├── clone.py
│   │   ├── discovery.py
│   │   ├── doctor.py
│   │   ├── documentacion.py
│   │   ├── fabrics.py
│   │   ├── info.py
│   │   ├── init.py
│   │   ├── install.py
│   │   ├── qa.py
│   │   ├── review.py
│   │   ├── status.py
│   │   ├── uninstall.py
│   │   ├── update.py
│   │   ├── upgrade.py
│   │   ├── validate.py
│   │   └── version.py
│   ├── core/
│   │   ├── auth.py
│   │   ├── batch_state.py
│   │   ├── canonical.py
│   │   ├── local_resolver.py
│   │   └── mcp_launcher.py
│   ├── adapters/
│   └── data/
└── tests/
```

---

## Roadmap

### Hitos completados

- [x] v0.1.0 - MVP: `install`, `check-install`, `init`, `fabrics setup`, 4 slash commands, 6 adapters
- [x] v0.2.0 - shell parity: `clone`, `check`, `fabrics generate`
- [x] v0.2.4 - Fabrics real via MCP + scaffold con clases JAXB
- [x] v0.3.0 - batch mode inicial
- [x] v0.3.4 - `batch migrate` con `codex exec`
- [x] v0.3.5 - `batch pipeline`
- [x] v0.3.6 - `resume` + `retries` + agents/skills reales de Codex
- [x] v0.3.7 - Fabrics como gate duro + `batch watch`
- [x] v0.3.8 - bootstrap unattended, Azure PAT por env, Codex install/check, CI/release
- [x] v0.23.16 - Codex first-class: GPT-5.5, `xhigh`, batch default Codex, `--reasoning-effort`
- [x] v0.23.17 - `capamedia ai migrate/doublecheck` como flujo portable multi-IA
- [x] v0.23.19 - `clone-migrated` trae legacy/UMPs/TX y repos migrados existentes desde `tpl-middleware`
- [x] v0.23.21 - `capamedia discovery edge-case --here` + Discovery OLA canonico empaquetado
- [x] v0.23.22 - BLOQUE 22 ejecutable: Discovery edge cases con decision, archivo/test/handoff
- [x] v0.23.23..0.23.26 - `capamedia documentacion` HTML Confluence con diagrama, casos textuales, curl happy path OpenShift derivado del WSDL
- [x] v0.23.24 - Regla 8 BANCS endurecida (solo BUS/IIB + `invocaBancs=true`)
- [x] v0.23.30 - `/edge-cases` en Claude Code cierra Discovery edge cases con implementacion, tests, reporte y checklist Block 22

### Releases 0.24.x — checks de banco y robustez de clone

- [x] v0.24.0 - Spring Boot baseline 4.0.6 (BREAKING, **revertido luego en 0.24.3**); Check 8.7 Netty pin prohibido; Block 7 capacity (HPA/JAVA_OPTIONS exactos); Block 5 patterns QA WSClientes0011; Block 15 nombres legacy en `error.recurso`/`error.componente`
- [x] v0.24.1 - 3 checks hexagonal del peer-review wstecnicos0008: Check 1.7 (helpers `infrastructure/input/` no inyectan output ports), Check 1.3c ampliado (`@ConfigurationProperties` que implementa `*Port`), Check 7.1c (`metadata.name` pattern `<ns>-msa-sp-<svc>`)
- [x] v0.24.2 - `validate_hexagonal.py` reconoce `spring-boot-starter-web-services`/`@Endpoint`/`MessageDispatcherServlet` como `SOAP + MVC`; `review` reconstruye metadata Fabrics minima desde legacy si falta `fabrics.json`
- [x] v0.24.3 - `capamedia pat` top-level con validacion; Discovery extrae facets XSD (`length`, `pattern`, `enumeration`, etc.); fix Helm `JAVA_OPTIONS` con caracteres invisibles; **Spring Boot baseline vuelve a 3.5.14**; `catalog-info.metadata.name` vuelve a `tpl-middleware`
- [x] v0.24.4 - `SECRETS_CATALOG` de 6 a 73 datasource/JNDI mapeados a secretos Key Vault
- [x] v0.24.5 - `capamedia clone` ya no oculta el motivo real del fallo: lista cada repo probado con su error, clasifica `auth`/`not_found`/`mixed`, agrega flag `--legacy-repo` y `probe_azure_devops_pat` antes del clone

### Releases 0.25.x — OLA 2 y pipeline QA nativo

- [x] v0.25.0 - **OLA 2**: `core/ola_policy.py` como fuente de verdad (25 servicios entrega 1), `lib-bnc-api-client:2.0.0` para OLA 2 vs `1.1.0` para OLA 1, autofix OLA-aware. **Compuerta pre-QA**: nuevo `/qa` (analisis comparativo + handoff), agente `qe-migration` (artefactos QA bajo `docs/qa/**`), retarget de `capamedia qa pack/prepare`

### Releases 0.26.x — cierre del pipeline QA y diagnostico

- [x] v0.26.0 - `/qacases` paso 3 del pipeline QA: implementa los casos como tests Karate `.feature` ejecutables, agrega dependencia Karate, runner JUnit5, `karate-config.js`
- [x] v0.26.1 - `<xsd:documentation>` deja de ser contrato exigible: las restricciones solo salen de facets formales o del legacy real; la prosa queda como "intencion documentada"
- [x] v0.26.2 - Compactacion del prompt `checklist-rules.md` (<25 KB) para evitar fatiga de contexto; severidades de logs (2.8/2.9) y "Quitar Etiquetas" (18.3) degradadas a `info`
- [x] v0.26.3 - `log-transaccional-orq.md` reconciliado con PDF 2026-05-26: LT-1 (Spring Boot 3.5.12 agnostico), LT-4 (patron real Azure `sqb-cfg-<TipoTransaccion>-plantillasTransaccional`), fallback con `bodyIn`/`bodyOut` en `null`
- [x] v0.26.4 - Diagnostico de `capamedia clone` cuando el PAT esta OK pero git no lo aplica (git <2.31 sin `GIT_CONFIG_COUNT`, credential helper macOS interfiriendo)

### Release 0.30.0 — Catálogos del banco embebidos (Discovery OLA 2 + adaptadores BANCS)

- [x] v0.30.0 - **Discovery OLA 2 embebido** (`data/catalog/ola2.json`: 25 servicios, 5 ORQ, 37 relaciones): al migrar cualquier servicio del catálogo el prompt recibe su **ficha** (tribu, tecnología, métodos, links IcePanel/WSDL/código); un ORQ recibe además su **mapa de downstreams** (`in_discovery`/`in_ola1`) que `analisis-orq.md` usa como fuente primaria con reconciliación 3-way. **Adaptadores BANCS embebidos** (`data/catalog/bancs_adapters.json`: 8 adaptadores Core Adapter, 55 TX): el prompt recibe la tabla TX→adaptador→URL interna; prevalece `prompts/tx-adapter-catalog.json`; patrón `CCC_BANCS_ADAPTER_<SUFFIX>_BASE_URL`. Guardrails en todo: **catálogo=contexto NO árbitro** (el ESQL manda; los checks no los importan), sanitización estructural (el `.numbers` de adaptadores trae cookies/PII y NO se versiona). Generadores reproducibles `tools/build_*.py`. +57 tests, suite 1009. (2 revisiones adversariales ejecutando el código)

### Release 0.40.0 — Spring Boot 4 baseline, probes liveness/readiness y sondas fuera del trace-logger

- [x] v0.40.0 - **Baseline Spring Boot `3.5.15` → `4.1.1`** (`SPRING_BOOT_BASELINE_VERSION`; correos BPTPSRE 2026-08, MCP Fabrics `v20260827161016` ya lo emite). Política de versiones **nunca bajar**: el Check 8.1 acepta cualquier versión mayor que emita el MCP, marca `3.5.15 <= v < 4` como MEDIUM (línea SB3 solo para proyectos existentes, `SPRING_BOOT_LEGACY_BASELINE_VERSION`) y HIGH por debajo del mínimo de cada línea; el autofix sube solo dentro de la misma línea (`3.5.x → 3.5.15`, `4.x → 4.1.1`) y jamás salta `3.x → 4.x`. `/migrate` (router, prompts REST/SOAP, skill `migrar`) y `doublecheck` instruyen lo mismo: conservar lo que trae el MCP, subir un scaffold nuevo en 3.5.x a `4.1.1` con el set SB4 y dejar en `3.5.15+` un proyecto ya construido.
- [x] v0.40.0 - **Librerías SB4**: `lib-trace-logger-sb4:1.2.0` (artifactId nuevo — Check 8.13 + `fix_trace_logger_sb4_artifact`), `lib-event-logs-*:2.0.0` en ORQ (Check 8.14 + `fix_event_logs_sb4_version`), `lib-bnc-api-client:3.0.0` final en SB4 para cualquier OLA (Check 8.9 endurecido, Regla 8; la alpha `3.0.0-alpha.*` queda prohibida). Pins Netty/Snyk de SB3 (8.7/8.8/8.10 y sus autofixes) gated a Spring Boot 3.5.x: en SB4 un pin `io.netty:*:4.1.x` es downgrade (MEDIUM) y el resto queda `pendiente_validar`.
- [x] v0.40.0 - **Probes Kubernetes** (Check 7.10 + `fix_helm_probe_paths`): `livenessProbe` → `/actuator/health/liveness`, `readinessProbe` → `/actuator/health/readiness` (formas `grep -q` y `cut` aceptadas; HIGH en SB4, MEDIUM en SB3). Check 7.11 + `fix_helm_probes_enabled_env`: `CCC_ACTUATOR_HEALTH_PROBES_ENABLED: "true"` en los 3 Helm.
- [x] v0.40.0 - **Sondas fuera del trace-logger** (hallazgo TO 2026-08-25): Check 2.10 exige `infrastructure/config/TraceLoggerManagementPathConfig` (BeanPostProcessor, variante MVC o WebFlux según stack) y 2.11 su test (≥ 6 casos); `fix_add_trace_logger_management_config` genera ambos desde `core/sb4_templates.py`. Check 17.8 + `fix_event_logs_excluded_paths`: `logging.event.excluded-paths: /actuator/**,...` en ORQ (LT-2 MUST). Check 2.6: logs INFO diagnósticos (`Request received`, `Input validation passed`, ...) → DEBUG. Check 0.6: un cURL por operación WSDL en README/docs antes de asignar al TO. Nueva Regla 9e (9e.1 / 9e.3) en `bank-official-rules.md`.
- [x] v0.40.0 - **`capamedia fabrics generate`** avisa si el build del MCP es anterior a `v20260827161016` (scaffold en 3.5.x) y registra `mcp_min_version` / `mcp_build_current` en `.capamedia/fabrics.json`. **Namespace `tem`** disponible (`tem-msa-sp-<servicio>`; `tca` ya estaba). +38 tests, suite 1104.

### Release 0.39.0 — Namespace `fse`

- [x] v0.39.0 - **`fse` disponible en `capamedia fabrics generate`** (`fse-msa-sp-<servicio>`). Una sola línea gracias a la fuente única `BANK_NAMESPACES` (v0.35.0): `fabrics`/`qa`, `adopt` y `clone --migrated` lo reconocen automáticamente. +1 test, suite 1071.

### Release 0.38.0 — Observabilidad ORQ: niveles de log externalizados + `@BpLogger`

- [x] v0.38.0 - **Niveles de log de las libs del banco externalizados via ConfigMap** (referencia orqproductos0061 `5e92bfa`): `logging.level` referencia `${CCC_LOG_LEVEL_KAFKA}` / `${CCC_LOG_LEVEL_EVENT_LOGS}` / `${CCC_LOG_LEVEL_TRACE_LOGGER}` y el valor vive en los 3 Helm (`OFF`/`OFF`/`INFO`). Check 17.3 endurecido (el literal `kafka: OFF` pasa a FAIL) + Checks 17.5/17.6 nuevos. **Check 17.7 nuevo**: `@BpLogger` junto a `@EventAudit` en cada adapter downstream. Paso 1.8 nuevo en `doublecheck.md` y canonical LT-2/LT-3 actualizados. ORQ-only. +12 tests, suite 1070.

### Release 0.37.0 — Namespace `tca`

- [x] v0.37.0 - **`tca` disponible en `capamedia fabrics generate`** (`tca-msa-sp-<servicio>`). Una sola línea gracias a la fuente única `BANK_NAMESPACES` (v0.35.0): `fabrics`/`qa`, `adopt` y `clone --migrated` lo reconocen automáticamente. +1 test, suite 1060.

### Release 0.36.0 — WebClient oficial para downstream WS (LT-3b + Check 7.9)

- [x] v0.36.0 - **Patrón oficial WebClient del banco** (doc lib-event-logs/WebFlux) incorporado al canonical: Regla LT-3b + prompt REST §4.17 con el código completo (records `HttpClientProperty`/`WebClientProperty` prefix `webclient`, helper con `ConnectionProvider` + `responseTimeout`, bean `WebClient.Builder` + bean `WebClient` por downstream) y política de env vars (los 5 knobs por downstream como `${CCC_<SVC>_*}`; `max-idle-time`/`pending-acquire-timeout` quedan en defaults del código). **Check 7.9** (MEDIUM, WebFlux + `WebClient.builder(` manual) detecta el patrón legacy: sin `ConnectionProvider`, `ReadTimeoutHandler`, y beans `<svc>WebClient` sin entrada `webclient.<svc>:` en application.yml. Verificado contra ORQClientes0023 real (los 3 síntomas). +7 tests, suite 1055.

### Release 0.35.0 — Baseline Spring Boot 3.5.15 + namespace `taa`

- [x] v0.35.0 - **Baseline Spring Boot `3.5.14` → `3.5.15`** (`SPRING_BOOT_BASELINE_VERSION`), propagado a los 5 canonicales y a los textos de prompt de `ai.py`/`batch.py`. Resuelve un drift de 6 releases: `doublecheck.md` pedía `3.5.15` desde v0.29.0 mientras el código y los prompts de migración decían `3.5.14`, así que el agente generaba una versión y el doublecheck la subía a otra sin que ningún check lo exigiera. **Guard nuevo** que falla si cualquier canonical propone una versión de Spring Boot distinta del baseline (el guard anterior solo verificaba presencia, no exclusividad).
- [x] v0.35.0 - **`taa` disponible en `capamedia fabrics generate`** (`taa-msa-sp-<servicio>`). De paso se corrige un bug latente: la lista de namespaces estaba duplicada en 4 módulos y había divergido — `tmi` (v0.30.1) se agregó solo al prompt, así que era elegible pero `clone --migrated` y `adopt` no reconocían un `tmi-msa-sp-*`. Nueva fuente única `BANK_NAMESPACES` en `core/ola_policy.py`; `fabrics`/`qa`, `adopt` y `clone` derivan de ella. Textos de ayuda dinámicos. +5 tests de guard anti-drift, suite 1048.

### Release 0.34.0 — trace-logger + payload por defecto (Checks 7.7 / 7.8)

- [x] v0.34.0 - **Observabilidad por defecto en TODO servicio** (orquestador Y microservicio, ya no ORQ-only): **Check 7.7** exige el bloque `trace-logger:` con `payload.mode` en `application.yml` referenciando las 7 `${CCC_*}` (sin defaults inline), y **Check 7.8** exige esas 7 env vars en los 3 helm con el valor por ambiente — `CCC_CUSTOM_LEVEL_DEBUG_ENABLED = true` solo en dev, `CCC_PAYLOAD_MODE = NONE` en los 3 (nunca loguear payload/PII). Autofixes `fix_trace_logger_application` / `fix_trace_logger_helm` (conservadores: no reescriben lo existente). Fuente única `LIB_TRACE_LOGGER_VERSION = 1.4.0` + 2 guards anti-drift. El log transaccional (`lib-event-logs`) **sigue siendo ORQ-only**. Además: política de comentarios (sin JavaDoc ni ruido) y de commits (breves, sin atribución a Claude/Anthropic) en los prompts de migración. +16 tests, suite 1043.

### Release 0.33.0 — Check 8.12: version del plugin peer-review

- [x] v0.33.0 - **Check 8.12 + autofix `fix_peer_review_plugin_version`**: el `build.gradle` debe declarar `id 'com.pichincha.frm-plugin-peer-review-gradle' version '1.1.2'` (los scaffolds viejos de Fabrics traen `1.1.0`). Azure corre `gradle build -x test` pero el task `architectureReview` sigue bloqueando el PR, asi que una version vieja se descubria recien en el merge. Detecta Groovy y Kotlin DSL; acepta versiones mayores. El autofix actualiza una declaracion existente pero **no inyecta el plugin si falta** (se resuelve del repo interno del banco; un `id` no resoluble rompe el build). Regla 9h.4 nueva en el canonical. +15 tests, suite 1027.

### Release 0.32.0 — Netty 4.1.136 (Snyk 2026-07)

- [x] v0.32.0 - Netty WebFlux `4.1.135.Final` → `4.1.136.Final` (`NETTY_WEBFLUX_ALLOWED_VERSION`): Checks 8.7/8.8/8.10 y sus autofixes exigen y preservan la nueva version; `4.1.135.Final` pasa a bloqueada. Mismos 13 modulos core y mismo doble pin (`dependency` + `force`); 4.2.x sigue prohibida.

### Release 0.29.0 — Netty 4.1.135 + Check 8.10 (Snyk 2026-06)

- [x] v0.29.0 - Netty `4.1.133.Final` → `4.1.135.Final` (árbol completo + `unix-common`), Check/autofix 8.10 pins WebFlux Snyk 2026-06, baseline Spring Boot 3.5.15 en doublecheck

### Release 0.28.10 — Revert del parser por-rama del 5.13 + señal 2b (3ª revisión)

- [x] v0.28.10 - **Revert de heurísticas frágiles**: tras 3 rondas de regresiones (el mini-tokenizer de v0.28.9 fallaba con text blocks Java/`<` relacional/TX en comillas dobles), el **Check 5.13 vuelve al conteo agregado conservador** validado en v0.28.7 (homogéneo→HIGH, mixto→LOW, **sin parsear Java**). **Señal 2b revertida** (reabría el falso positivo de WSReglas0010). **8.9** conserva submódulos con early-return estricto. Se conserva: gate ORQ por token, exclusión test, F11, docs, mensajeNegocio, Helm, netty. Suite 952. (lección: parsear Java a mano no escala — el 5.13 prefiere LOW manual a un veredicto fuerte incorrecto)

### Release 0.28.9 — Fix de la revisión adversarial de v0.28.8 (tokenizer + 2b)

- [x] v0.28.9 - **Mini-tokenizer literal-aware** para el parser `Mono.zip` (neutraliza strings/comentarios, ignora `Mono.zipDelayError`, balancea generics, grupos por-zip) → cierra los FALSE HIGH del Check 5.13. Familias `onError*` (Resume/Return/Complete), parseo sucio → LOW (nunca PASS), mixto comparado solo con un zip (M4), best-effort en helper → LOW (M1). **Detector 2b**: denylist `NON_BANCS_UMP_PREFIXES` + filtro de fechas → cierra el falso positivo de WSReglas0010 (`'000404'`) que la señal 2b había reabierto. **Check 8.9**: `all_gradle` antes del early-return (monorepos) + exclusión `test` (paridad PR-gate). Claim `orquideas` corregido. +6 tests regresión, suite 965. (2 HIGH + 6 MEDIUM de la revisión adversarial, todos verificados ejecutando el código)

### Release 0.28.8 — Pendientes del review: robustez 5.13/8.9 + detector

- [x] v0.28.8 - **Check 5.13 por-rama**: conteo de `onErrorResume` por rama del `Mono.zip` (parseo balanceado) en vez de global; mixto → MEDIUM/LOW, nunca HIGH con parseo sucio. Gate ORQ por token (no el `orq` embebido de `mayorque`) + respeta `source_type`. **Check 8.9** escanea submódulos. **Detector**: señal TX también en UMPs clonadas; `BANCS_UMP_PREFIXES` documentada + test de sincronía. `analisis-orq.md` clasifica mandatory/best-effort. +14 tests, suite 959. (el matching 1:1 del 5.13 se descartó por inviable — un 2º workflow de diseño confirmó que el legacy no expone una llave estable)

### Release 0.28.7 — Hardening checks 8.9/5.13 (revisión adversarial)

- [x] v0.28.7 - **Check 8.9 corregido**: leía `invoca_bancs` como bool pero el formato real es string → réplica exacta de `validate_hexagonal` (`_load_fabrics_metadata` + `_fabrics_requires_bancs`, acepta string/camelCase/source_kind), test de paridad contra el vendor. Detección de lib ignora comentarios
- [x] v0.28.7 - **Check 5.13 corregido**: `onErrorResume` scopeado a los servicios con `Mono.zip` + sus `util/*Helper.java` (antes era global y contradecía Service Purity); caso mixto → LOW manual; helper ESQL descarta comentarios. Detector: `startswith` para UMP compuestas. +6 tests, suite 945. Hallado por un workflow de revisión adversarial sobre el diff de v0.28.6

### Release 0.28.6 — Regla 8 falso positivo BANCS + ORQ-RETURN-PARITY

- [x] v0.28.6 - **Fix detector BANCS (falso positivo Regla 8)**: `detect_bancs_connection` ya no marca BANCS por cualquier `UMP*`; solo UMPs de prefijo BANCS conocido (`BANCS_UMP_PREFIXES`) o TX literal `0NNNNN`. Evita reinsertar `lib-bnc-api-client` en BUS-sin-BANCS (WSReglas0010). + **Check 8.9** (lib solo si BUS+invocaBancs, lee `fabrics.json`, espejo del PR-gate). +8 tests
- [x] v0.28.6 - **Check 5.13 ORQ-RETURN-PARITY**: cruza ramas `Mono.zip`/`onErrorResume` del migrado vs `RETURN FALSE` de los PROCEDURE legacy; best-effort migrado como mandatorio → HIGH (rompe productivo, caso ORQClientes0022/OP21). + regla en `migrate-rest-full.md`. +6 tests. 6 canónicos sincronizados

### Release 0.28.5 — mensajeNegocio: no borrar el tag (vaciar) + respetar legacy

- [x] v0.28.5 - **`mensajeNegocio` regla refinada**: el tag NUNCA se elimina; vacío por defecto (`<mensajeNegocio/>`). El micro no inventa valor (lo pone DataPower) **salvo que el legacy lo poblara**. Check 15.1 cross-chequea el legacy (`_legacy_populates_mensaje_negocio`): no poblaba→HIGH, poblaba→PASS, sin legacy→LOW. Autofix `fix_remove_mensajeNegocio_setter`→`fix_empty_mensajeNegocio_setter`: **vacía** en vez de borrar. Canónico `bank-error-structure.md` + self_correction + catalog_injector alineados. +3 tests

### Release 0.28.4 — Helm capacity: memory 100Mi/400Mi (ajuste banco)

- [x] v0.28.4 - **Ajuste de capacity (kevin armas, 2026-05-29)**: `resources.requests.memory` `350Mi`→`100Mi` y `resources.limits.memory` `500Mi`→`400Mi`. CPU (`50m`/`200m`) y `hpa` (min/max=1, CPU avg 100m) sin cambios. Fuente única `HELM_CAPACITY_BASELINE` (Check 7.5e + autofix `fix_helm_capacity_baseline`); canónicos/prompts sincronizados

### Release 0.28.3 — Arbol Netty completo en WebFlux (Check 8.8 + autofix)

- [x] v0.28.3 - **Check 8.8 + `fix_netty_full_tree_pin`**: el BOM de Spring Boot 3.5.14 trae `io.netty` 4.1.121.Final vulnerable; pinear solo `netty-codec*` dejaba transitivos como `netty-handler-proxy` vulnerables (WSClientes0013: 9 CVEs). Ahora se exige/autofixea el **árbol core de 12 módulos** a `4.1.133.Final` con **doble mecanismo** (`dependencyManagement` + `resolutionStrategy.force`). Constante `NETTY_CORE_MODULES` en `version_policy.py`. NO 4.2.x (rompe Reactor Netty). +10 tests
- [x] v0.28.3 - (descartado el intento previo de alinear a `4.2.13.Final`: 4.2.x rompe Reactor Netty del Spring Boot 3.5.x → `StacklessClosedChannelException`; revertido antes de pushear)

### Release 0.28.2 — `doublecheck` no quita el pin Netty en WebFlux

- [x] v0.28.2 - **`doublecheck.md` regla 11 ampliada**: documentaba Netty solo como servidor embebido; ahora deja explícito que el doublecheck NO debe eliminar el pin oficial en WebFlux. Cierra el drift codigo↔canonical

### Release 0.28.1 — Orquestacion por complejidad (`--auto-effort`)

- [x] v0.28.1 - **`core/effort_policy.py`**: complejidad del servicio → perfil de esfuerzo. Decision owner: **siempre Opus 4.8**; la complejidad modula reasoning effort (Codex), retries-extra (LOW+0/MEDIUM+1/HIGH+2) y gate humano (solo HIGH)
- [x] v0.28.1 - **`batch migrate --auto-effort`** (opt-in): deriva esfuerzo por servicio, muestra el plan (transparencia), señala HIGH para revision humana. `--model` explicito gana. Default = comportamiento actual
- [x] v0.28.1 - **Mapeo Codex centralizado** en `model_policy.py` (fuente unica total tier→modelo); guard extendido a `gpt-5.x`
- [x] v0.28.1 - North Star documentada (wizard "un click" de punta a punta) + backup `v0.28.0`/`backup/v0.28.0-stable`

### Release 0.28.0 — Vision de orquestador + cierre del drift codigo↔canonical

- [x] v0.28.0 - **`core/model_policy.py`**: fuente unica de modelos Claude. `opus → claude-opus-4-8` (antes hardcodeado `4-7` y drifteando). Adapters consumen desde ahi; eliminado `MODEL_MAP` duplicado. El tier logico expresa el ROL (opus=analista/1M, sonnet=grueso, haiku=workers paralelos)
- [x] v0.28.0 - **Single-source de constantes**: `NETTY_WEBFLUX_ALLOWED_VERSION` movida a `version_policy.py` (ataca de raiz el drift de v0.27.2)
- [x] v0.28.0 - **3 tests anti-drift**: guard de modelos hardcodeados, sync version_policy↔canonical, consistencia canonical↔codigo con baseline (congela 16 checks-sin-doc + 27 reglas-sin-check, falla ante drift nuevo)
- [x] v0.28.0 - **[`docs/ARQUITECTURA_ORQUESTADOR.md`](docs/ARQUITECTURA_ORQUESTADOR.md)**: diseno del CLI como orquestador (rol→modelo, complejidad→esfuerzo, contratos, gates) + roadmap v0.28.x/v0.29

### Release 0.27.2 — Canonicals sincronizados con excepcion Netty WebFlux

- [x] v0.27.2 - **Doc fix**: canonicals (`bank-official-rules.md` Regla 8.5, `migrate-rest-full.md`, `checklist-rules.md` Check 8.7) ahora mencionan explicitamente la excepcion `io.netty:*:4.1.133.Final` en WebFlux. En v0.27.0 se agrego al codigo Python pero los canonicales decian "NUNCA pinear" — el gap confundia al agente AI que leia la regla vieja

### Release 0.27.1 — Errores BANCS son ERROR (aclaracion Kevin Armas)

- [x] v0.27.1 - **Errores de BANCS son `tipo=ERROR`, no `FATAL`** (aclaracion oficial Kevin Armas / BPTPSRE 2026-05-27). Invierte la regla anterior de `bank-error-structure.md`: BancsOperationException (9929), BancsClientException (9922) y TimeoutException de BANCS (9991) pasan a ERROR. Header missing (9927) y catch-all (9999) siguen FATAL. Canonicales actualizados (bank-error-structure, bank-error-codes, migrate-rest-full, check.md, checklist-rules). **Check 5.7b nuevo**: detecta BANCS/GlobalErrorException mapeados a FATAL como FAIL HIGH (anti-patron inverso al 5.6.5). +6 tests, suite 884 passing

### Release 0.27.0 — Politica nueva headerIn + Netty WebFlux

- [x] v0.27.0 - **Politica `<headerIn>` 2026-05-26**: el `HeaderRequestValidator` con regex + maxLength por campo se elimina; cero validacion sintactica del header. Solo null-check inline del bloque `<bancs>` cuando `invocaBancs=true` (codigo 9927 / FATAL / backend 00638). Block 4 canonical reescrito entero (5 checks detectan el anti-patron); §4.6 del prompt REST reescrita; Rule 9b alineada
- [x] v0.27.0 - **Netty 4.1.133.Final permitido en WebFlux**: Check 8.7 + `fix_remove_netty_pin` detectan `spring-boot-starter-webflux` y preservan el pin oficial CVE-fix 2026-05; otras versiones siguen bloqueadas; MVC/SOAP siguen sin pins manuales
- [x] v0.27.0 - **Block 14 (SonarLint binding) eliminado** del CLI. Extension SonarLint para VS Code se preserva
- [x] v0.27.0 - Persistencia automatica de credenciales en `~/.capamedia/user.env` (Unix) / registro de usuario (Windows), sin `--env-file` ni exports manuales
- [x] v0.27.0 - Autocarga nativa del `user.env` en `core/auth.py` al importarse
- [x] v0.27.0 - `capamedia pat` tolerante: diferencia 401 (Azure DevOps critico) de 404 (Artifacts feed -> WARN) y procede a guardar
- [x] v0.27.0 - Fix `capamedia update`: usa `sys.executable -m pip` en vez de `pip` directo

### Pendiente

- [ ] v0.4.0 - integracion con Jira / Azure Boards / Confluence / Slack

## Licencia

MIT © Banco Pichincha - Capa Media Team
