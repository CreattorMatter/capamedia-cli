# capamedia-cli - v0.27.0

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
