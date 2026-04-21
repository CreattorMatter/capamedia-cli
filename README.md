# capamedia-cli · v0.3.2

CLI multi-harness para la migración de servicios legacy (IIB / WAS / ORQ) de Banco Pichincha a Java 21 + Spring Boot hexagonal OLA1.

Un solo canonical, 6 harnesses soportados: **Claude Code · Cursor · Windsurf · GitHub Copilot · OpenAI Codex · opencode**.

---

## Qué hace

Separa claramente dos responsabilidades:

1. **Setup local** (comandos shell): `capamedia install`, `check-install`, `init`, `fabrics setup`
2. **Trabajo diario** (slash commands del IDE): `/clone`, `/fabric`, `/migrate`, `/check`

El CLI genera los slash commands nativos del harness elegido en la carpeta de trabajo. Los comandos se ejecutan desde el chat del IDE — la AI entiende el contexto del proyecto, lee el legacy, invoca el MCP Fabrics, y responde conversacionalmente.

```
┌───────────────────── capamedia-cli (shell) ─────────────────────┐
│                                                                  │
│   install ─→ check-install ─→ init ─→ fabrics setup              │
│                                                                  │
└──────────────────────────── genera ──────────────────────────────┘
                                ↓
         ┌──────────────────────┴──────────────────────┐
         │    .claude/commands/{clone,fabric,migrate,check}.md   │
         │    .cursor/rules/*.mdc · .windsurf/rules/*.md         │
         │    .github/prompts/*.md · .codex/prompts/*.md         │
         │    .opencode/prompts/*.md                             │
         │    CLAUDE.md · .mcp.json · .sonarlint/                │
         └──────────────────────┬──────────────────────┘
                                ↓
               [Chat del IDE con la AI del harness]
                                ↓
   /clone <svc> ─→ /fabric ─→ /migrate ─→ /check
```

---

## Instalación

```bash
uv tool install capamedia-cli --from .
# o
pip install -e .
```

## Flujo completo

### 1) Setup (una vez por desarrollador)

```bash
# Instala toolchain (Git, Java 21, Gradle, Node.js LTS, Python 3.12, uv, VS Code)
capamedia install

# Verifica que todo esté OK
capamedia check-install

# Registra el MCP Fabrics del banco (pide ARTIFACT_TOKEN)
capamedia fabrics setup
```

**Manual** (no automatizable):
- Azure DevOps PAT — primer `git clone` interactivo para cachear via GCM
- SonarCloud binding — desde el sidebar de VS Code → *Share Configuration*

### 2) Por cada servicio a migrar

```bash
# Crear carpeta del servicio
mkdir -p "C:/Dev/Banco Pichincha/CapaMedia/wsclientes0008"
cd "C:/Dev/Banco Pichincha/CapaMedia/wsclientes0008"

# Inicializar con el harness preferido (interactivo por default)
capamedia init wsclientes0008
# → te pregunta uno por uno: claude? cursor? windsurf? copilot? codex? opencode?
# → genera .claude/, .cursor/, .mcp.json, CLAUDE.md, .sonarlint/, .gitignore

# Abrir en el IDE
code .        # o "claude", o "cursor .", o "windsurf ."

# En el CHAT del IDE:
/clone wsclientes0008
#   → trae legacy, UMPs, TX catalogs, gold reference
#   → responde: "Cloné. Es 1 op, 3 UMPs (TX 060480, 061404, 067010). Va REST+WebFlux. MEDIUM complexity."

/fabric
#   → preflight del MCP, invoca mcp__fabrics__create_project_with_wsdl
#   → aplica workarounds conocidos (webflux starter, jaxws-rt, versiones)
#   → responde: "Arquetipo generado en ./destino/tnd-msa-sp-wsclientes0008/. Listo para /migrate."

/migrate
#   → lanza agente migrador (sub-agente)
#   → implementa 7 blocks con GATEs + self-correction loop
#   → corre ./gradlew build hasta que pase
#   → responde: "Migración OK. 47 archivos. Build verde. Tests 92%."

/check
#   → corre BLOQUES 0-14 del checklist BPTPSRE
#   → cruza WSDL legacy ↔ migrado (operaciones, namespaces, XSDs)
#   → diálogo conversacional: "¿1 op? SÍ. ¿REST? SÍ. ¿OK? SÍ."
#   → responde: "14 bloques · 58 PASS · 3 MEDIUM · 1 HIGH. ¿Fix los MEDIUM?"
```

---

## Arquitectura

```
capamedia-cli/
├── pyproject.toml
├── src/capamedia_cli/
│   ├── cli.py                        # typer entry
│   ├── commands/
│   │   ├── install.py               # winget/brew/apt toolchain
│   │   ├── check_install.py         # verifica toolchain + MCP + Azure PAT + SonarCloud
│   │   ├── init.py                  # scaffolding interactivo con rich.Confirm
│   │   ├── fabrics.py               # setup + preflight del MCP
│   │   ├── doctor.py                # diagnóstico
│   │   └── upgrade.py               # --add/--remove harness
│   ├── core/
│   │   ├── canonical.py             # loader con schema validation
│   │   └── frontmatter.py           # YAML frontmatter parse/serialize
│   ├── adapters/                    # 1 por harness (copiados de specapi-cli)
│   │   ├── base.py  claude.py  cursor.py  windsurf.py
│   │   ├── copilot.py  codex.py  opencode.py
│   └── data/
│       ├── canonical/
│       │   ├── schema.json          # JSON Schema del frontmatter
│       │   ├── prompts/
│       │   │   ├── clone.md · fabric.md · migrate.md · check.md   # slash commands
│       │   │   ├── analisis-servicio.md · analisis-orq.md          # pre-migración
│       │   │   ├── migrate-rest-full.md · migrate-soap-full.md     # migración detallada
│       │   │   └── checklist-rules.md                              # checklist 15 bloques
│       │   ├── skills/{pre-migracion,migrar,post-migracion}/SKILL.md
│       │   ├── agents/{analista-legacy,migrador,qa-generator,validador-hex}.md
│       │   └── context/{hexagonal,bancs,security,code-style,sonarlint}.md
│       └── templates/
│           ├── CLAUDE.md.j2
│           ├── mcp.json.j2
│           └── sonarlint-connectedMode.json.j2
└── tests/
    ├── test_canonical.py            # loader sanity
    └── test_adapters.py             # adapters roundtrip
```

---

## Matriz oficial (sin excepciones)

| WSDL ops | Framework target | Stack | Aplicable a |
|---|---|---|---|
| **1 op** | REST + `@RestController` | Spring WebFlux + Netty | IIB / WAS / ORQ |
| **2+ ops** | SOAP + `@Endpoint` | Spring WS + Spring MVC + Undertow | IIB / WAS / ORQ |

**BD** es ortogonal:
- WAS + DB → HikariCP + JPA dentro de SOAP/MVC
- Caso raro REST + DB → R2DBC o `Schedulers.boundedElastic()` (flag `ATTENTION_NEEDED_REST_WITH_DB`)

---

## Harnesses soportados

| Harness | Flag | Qué genera |
|---------|------|-----------|
| **Claude Code** | `claude` | `.claude/commands/`, `.claude/agents/`, `.claude/skills/`, `.claude/settings.json`, `CLAUDE.md` |
| **GitHub Copilot** | `copilot` | `.github/prompts/`, `.github/copilot-instructions.md` |
| **Cursor** | `cursor` | `.cursor/rules/*.mdc` |
| **Windsurf** | `windsurf` | `.windsurf/rules/`, `.windsurfrules` |
| **OpenAI Codex CLI** | `codex` | `.codex/prompts/`, `.codex/config.toml`, `AGENTS.md` |
| **opencode** | `opencode` | `.opencode/`, `opencode.json`, `AGENTS.md` |

---

## Referencias internas

- [PromptCapaMedia](https://github.com/CreattorMatter/PromptCapaMedia) — repo predecesor (prompts como markdown sueltos, ahora migrados al canonical de este CLI)
- [spec-api-ai-v2](../spec-api-ai-v2) — CLI hermano para migraciones Apigee → Azure APIM (misma arquitectura de adapters)

---

## Roadmap

- [x] v0.1.0 — MVP: `install`, `check-install`, `init` interactivo, `fabrics setup`, 4 slash commands canónicos, 6 adapters
- [x] v0.2.0 — Shell parity: `clone`, `check`, `fabrics generate` como comandos shell deterministas (sin AI). `migrate` queda solo como slash command (requiere AI)
- [x] v0.2.4 — `fabrics generate` invoca el MCP Fabrics real y deja `destino/` con clases JAXB generadas
- [x] v0.3.0 — Batch mode: `batch complexity` / `clone` / `check` / `init` en paralelo con ThreadPool + BLOQUE 15 del checklist (Estructura de error oficial). Tests: 35/35 ✅
- [ ] v0.4.0 — Integración con Jira / Azure Boards / Confluence / Slack

## Licencia

MIT © Banco Pichincha - Capa Media Team
