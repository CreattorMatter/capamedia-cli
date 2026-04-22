# capamedia-cli · v0.3.8

CLI multi-harness para migrar servicios legacy (IIB / WAS / ORQ) de Banco Pichincha a Java 21 + Spring Boot hexagonal OLA1.

Un solo canonical, 6 harnesses soportados: **Claude Code · Cursor · Windsurf · GitHub Copilot · OpenAI Codex · opencode**.

---

## Que hace

Separa claramente dos responsabilidades:

1. **Setup de maquina**: `capamedia setup machine`, `capamedia doctor`
2. **Trabajo diario en IDE**: `/clone`, `/fabric`, `/migrate`, `/check`
3. **Fabrica batch**: `capamedia worker run`, `capamedia batch complexity|clone|init|pipeline|migrate|check|watch`

El CLI genera slash commands y assets nativos del harness elegido. Para Fabrics usa siempre el MCP del banco como gate del arquetipo; si el arquetipo no sale de Fabrics, la migracion no avanza.

```text
setup machine -> doctor -> worker run
                     |
                     v
        batch pipeline / batch migrate / batch watch / IDE slash commands
```

---

## Instalacion

```bash
uv tool install capamedia-cli --from .
# o
pip install -e .
```

## Setup de una maquina

### 1. Bootstrap recomendado

Para dejar una maquina runner realmente reproducible:

```bash
capamedia setup machine \
  --provider codex \
  --auth-mode session \
  --scope global \
  --workspace-root "/Users/julio/CapaMedia/lotes" \
  --queue-dir ~/.capamedia/queue
```

Esto orquesta:

- `capamedia install`
- `capamedia auth bootstrap`
- registro de MCPs (`capamedia` + Fabrics)
- escritura de `~/.capamedia/machine.toml`
- validacion final con `capamedia doctor`

Tambien deja un contrato machine-local en `~/.capamedia/machine.toml` con:

- runner principal (`codex` o `claude`)
- modo de auth (`session` o `api` para Codex)
- `workspace_root`
- `queue_dir`
- defaults operativos del worker

### 2. Toolchain

Si queres correr las piezas por separado, `capamedia install` instala el toolchain automatizable:

- Git
- Java 21
- Gradle
- Node.js LTS
- Codex CLI
- Claude Code CLI
- Python 3.12
- uv
- VS Code

### 3. Credenciales y MCP

Bootstrap recomendado para una Mac o runner que va a ejecutar batch unattended:

```bash
capamedia auth bootstrap \
  --scope global \
  --artifact-token <AZURE_ARTIFACTS_PAT> \
  --azure-pat <AZURE_DEVOPS_PAT> \
  --env-file ~/.capamedia/auth.env
```

Esto hace tres cosas:

- registra Fabrics en `~/.mcp.json`
- registra el MCP interno `capamedia` en `~/.codex/config.toml`
- refresca `~/.npmrc` para `@pichincha/fabrics-project`
- opcionalmente autentica Codex CLI via `codex login --with-api-key`

Y opcionalmente escribe un `auth.env` con:

- `CAPAMEDIA_ARTIFACT_TOKEN`
- `CAPAMEDIA_AZDO_PAT`
- `CODEX_API_KEY`
- `OPENAI_API_KEY`

Si no queres usar `auth bootstrap`, tambien podes hacer cada paso por separado:

```bash
capamedia fabrics setup --scope global --refresh-npmrc
codex login
claude auth login
```

### 4. Doctor operativo

`capamedia doctor` ya no es solo un sanity check. Ahora clasifica la maquina en:

- `READY`
- `BLOCKED_TOOLCHAIN`
- `BLOCKED_PROVIDER_AUTH`
- `BLOCKED_CORP_REPO`
- `BLOCKED_BUILD_PLUGIN`
- `BLOCKED_INPUT`

Ejemplo:

```bash
capamedia doctor
capamedia doctor --workspace /ruta/wsclientes0007 --probe-build
```

### 5. Paso manual que sigue existiendo

Lo unico que sigue manual es SonarCloud connected mode / SonarQube for IDE, y el login humano inicial del runner elegido cuando usas `auth-mode=session`.

### 6. MCP interno de CapaMedia para Codex

El scaffold `capamedia init --ai codex` ya deja configurado en `.codex/config.toml` un MCP local `capamedia` para que Codex consulte el corpus canónico sin depender solo de prompts estáticos.

Si queres agregarlo a un proyecto ya existente:

```bash
capamedia mcp setup --scope project
```

El MCP expone:

- búsqueda de prompts, agentes, skills y contexto canónico
- lectura completa de assets por nombre o URI
- schema canónico del toolkit
- overview del workspace actual

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
- `.codex/config.toml` con el MCP `capamedia`
- `.agents/skills/*/SKILL.md`
- `CLAUDE.md` o `AGENTS.md`
- `.mcp.json`
- `.sonarlint/connectedMode.json`

En modo IDE el flujo sigue siendo:

```text
/clone <servicio> -> /fabric -> /migrate -> /check
```

---

## Fabrica paralela

### Worker local

El worker usa `~/.capamedia/machine.toml` como contrato operativo y reejecuta `batch` con `--resume`.

```bash
capamedia worker run --mode pipeline --once
capamedia worker run --mode migrate
```

Defaults:

- toma la cola desde `~/.capamedia/queue/services.txt` o `migrate.txt`
- usa el runner configurado (`codex` o `claude`)
- reutiliza `workspace_root`, `workers`, `namespace`, `timeout` y `retries`
- valida `doctor` antes de arrancar salvo `--skip-doctor`

### Batch migrate

Cuando los workspaces ya existen y `destino/` ya fue generado por Fabrics:

```bash
capamedia batch migrate \
  --from services.txt \
  --root "C:/Dev/Banco Pichincha/CapaMedia" \
  --provider codex \
  --workers 3 \
  --resume \
  --retries 2
```

Este comando:

- ejecuta `codex exec` una vez por servicio
- tambien puede usar `claude -p` con `--provider claude`
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
  --provider claude \
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

Esta version deja cerrados los P0 para correr desde macOS, Linux o Windows:

- `fabrics setup` genera `.mcp.json` con `npx -y @pichincha/fabrics-project@latest`
- el launcher de MCP soporta cache `npm` tanto en Windows (`AppData`) como en Unix (`~/.npm/_npx`)
- `clone` soporta PAT por env sin prompts
- `install` y `check-install` ya contemplan Codex CLI y Claude Code CLI
- hay workflow de CI y workflow de release

---

## Comandos principales

| Comando | Uso |
|---|---|
| `capamedia install` | instala el toolchain automatizable |
| `capamedia check-install` | valida toolchain, Fabrics, Azure auth, Codex auth, Sonar binding |
| `capamedia setup machine` | deja una maquina runner lista y escribe `~/.capamedia/machine.toml` |
| `capamedia auth bootstrap` | registra Fabrics y autentica Codex; opcionalmente escribe `auth.env` |
| `capamedia doctor` | clasifica readiness real de la maquina en `READY/BLOCKED_*` |
| `capamedia init` | scaffold del workspace y harnesses |
| `capamedia mcp setup` | registra el MCP interno de CapaMedia en Codex |
| `capamedia clone` | clona legacy, UMPs y TX |
| `capamedia fabrics setup` | registra el MCP Fabrics |
| `capamedia fabrics generate` | invoca el MCP y genera `destino/` |
| `capamedia check` | corre el checklist deterministico |
| `capamedia worker run` | loop local que consume una cola y reusa `batch --resume` |
| `capamedia batch pipeline` | fabrica completa por servicio |
| `capamedia batch migrate` | migracion headless sobre workspaces ya preparados |
| `capamedia batch watch` | mirador operativo del lote |

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
│   │   ├── auth.py
│   │   ├── batch.py
│   │   ├── check_install.py
│   │   ├── clone.py
│   │   ├── fabrics.py
│   │   ├── init.py
│   │   └── install.py
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

- [x] v0.1.0 - MVP: `install`, `check-install`, `init`, `fabrics setup`, 4 slash commands, 6 adapters
- [x] v0.2.0 - shell parity: `clone`, `check`, `fabrics generate`
- [x] v0.2.4 - Fabrics real via MCP + scaffold con clases JAXB
- [x] v0.3.0 - batch mode inicial
- [x] v0.3.4 - `batch migrate` con `codex exec`
- [x] v0.3.5 - `batch pipeline`
- [x] v0.3.6 - `resume` + `retries` + agents/skills reales de Codex
- [x] v0.3.7 - Fabrics como gate duro + `batch watch`
- [x] v0.3.8 - bootstrap unattended, Azure PAT por env, Codex install/check, CI/release
- [ ] v0.4.0 - integracion con Jira / Azure Boards / Confluence / Slack

## Licencia

MIT © Banco Pichincha - Capa Media Team
