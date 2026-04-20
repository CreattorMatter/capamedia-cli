# Changelog

Todos los cambios notables en `capamedia-cli` estan documentados aqui.
Formato basado en [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning [SemVer](https://semver.org/lang/es/).

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
