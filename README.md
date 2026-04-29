# capamedia-cli - v0.23.29

CLI multi-harness para migrar servicios legacy (IIB / WAS / ORQ) de Banco Pichincha a Java 21 + Spring Boot hexagonal OLA1.

Un solo canonical, 6 harnesses soportados: **Claude Code · Cursor · Windsurf · GitHub Copilot · OpenAI Codex · opencode**.

---

## Que hace

Separa claramente dos responsabilidades:

1. **Setup local**: `capamedia install`, `capamedia check-install`, `capamedia auth bootstrap`, `capamedia init`, `capamedia fabrics setup`
2. **Trabajo por servicio**: `capamedia clone`, `capamedia fabrics generate`, `capamedia ai migrate`, `capamedia ai doublecheck`, `capamedia review`, `capamedia documentacion`
3. **Fabrica batch**: `capamedia batch complexity|clone|init|pipeline|migrate|check|watch`

El CLI genera assets nativos del harness elegido, pero el flujo operativo portable vive en comandos shell. Para Fabrics usa siempre el MCP del banco como gate del arquetipo; si el arquetipo no sale de Fabrics, la migracion no avanza.

```text
install -> check-install -> auth bootstrap -> init -> fabrics setup
                                      |
                                      v
          clone -> fabrics generate -> ai migrate -> ai doublecheck -> review
                                      |
                                      v
                            documentacion -> Confluence HTML
                                      |
                                      v
                         batch pipeline / batch migrate / batch watch
```

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

Bootstrap recomendado para una Mac o runner que va a ejecutar batch unattended:

```bash
capamedia auth bootstrap \
  --scope global \
  --artifact-token <AZURE_ARTIFACTS_PAT> \
  --azure-pat <AZURE_DEVOPS_PAT> \
  --openai-api-key <OPENAI_API_KEY> \
  --env-file ~/.capamedia/auth.env
```

Esto hace tres cosas:

- registra Fabrics en `~/.mcp.json`
- refresca `~/.npmrc` para `@pichincha/fabrics-project`
- autentica Codex CLI via `codex login --with-api-key`

Y opcionalmente escribe un `auth.env` con:

- `CAPAMEDIA_ARTIFACT_TOKEN`
- `CAPAMEDIA_AZDO_PAT`
- `OPENAI_API_KEY`

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
```

Los slash commands legacy pueden seguir existiendo en algunos harnesses, pero no son la entrada recomendada para Codex ni para el flujo multi-IA.

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

Esta version deja cerrados los P0 para correr desde macOS, Linux o Windows:

- `fabrics setup` genera `.mcp.json` con `npx -y @pichincha/fabrics-project@latest`
- el launcher de MCP soporta cache `npm` tanto en Windows (`AppData`) como en Unix (`~/.npm/_npx`)
- `clone` soporta PAT por env sin prompts
- `install` y `check-install` ya contemplan Codex CLI
- hay workflow de CI y workflow de release

---

## Comandos principales

| Comando | Uso |
|---|---|
| `capamedia install` | instala el toolchain automatizable |
| `capamedia check-install` | valida toolchain, Fabrics, Azure auth, Codex auth, Sonar binding |
| `capamedia auth bootstrap` | registra Fabrics y autentica Codex; opcionalmente escribe `auth.env` |
| `capamedia init` | scaffold del workspace y harnesses |
| `capamedia clone` | clona legacy, UMPs y TX |
| `capamedia fabrics setup` | registra el MCP Fabrics |
| `capamedia fabrics generate` | invoca el MCP y genera `destino/` |
| `capamedia ai migrate` | migracion AI headless del workspace actual (Codex/Claude) |
| `capamedia ai doublecheck` | doble check AI post-migracion; no reemplaza `review` |
| `capamedia check` | corre el checklist deterministico |
| `capamedia review` | auditoria final deterministica del banco |
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
- [x] v0.23.29 - `capamedia discovery edge-case --here` deja WSDL/XSD y reporte en `.capamedia/`, fuera del repo migrado oficial
- [x] v0.23.28 - checklist oficial bloquea Helm HPA `averageValue` distinto de `100m` en `dev/test/prod`
- [x] v0.23.27 - `capamedia discovery edge-case --here` corrige paths de specs por sufijo WS y detecta WSDL/XSD por servicio
- [x] v0.23.26 - `capamedia documentacion` genera HTML Confluence con diagrama, casos textuales y curl happy path OpenShift derivado del WSDL/tests/legacy
- [x] v0.23.25 - `capamedia documentacion` replica el esqueleto de encabezados del Word WSClientes0020
- [x] v0.23.24 - Regla 8 BANCS endurecida: solo BUS/IIB + `invocaBancs=true`; WAS/ORQ/BUS sin BANCS quedan bloqueados si traen artefactos BANCS
- [x] v0.23.23 - `capamedia documentacion` genera documentacion de servicio en HTML Google Docs friendly o Markdown
- [x] v0.23.22 - BLOQUE 22 ejecutable: Discovery edge cases requieren decision, archivo/test/handoff y loop hasta cero pendientes
- [x] v0.23.21 - `capamedia discovery edge-case --here` + Discovery OLA canonico empaquetado para LINK WSDL, observaciones y casos de desborde
- [x] v0.23.20 - checklist TX Java/YAML, `mensajeNegocio` vacio permitido por contrato SOAP y `connection-test-query: SELECT 1` para WAS+JPA
- [x] v0.23.19 - `clone-migrated` trae legacy/UMPs/TX y repos migrados existentes desde `tpl-middleware`
- [x] v0.23.18 - higiene de `.gitignore` en migrate/doublecheck/checklist para no subir artefactos CapaMedia/AI a Azure DevOps
- [x] v0.23.17 - `capamedia ai migrate/doublecheck` como flujo portable multi-IA
- [x] v0.23.16 - Codex first-class: GPT-5.5, `xhigh`, batch default Codex, `--reasoning-effort`
- [ ] v0.4.0 - integracion con Jira / Azure Boards / Confluence / Slack

## Licencia

MIT © Banco Pichincha - Capa Media Team
