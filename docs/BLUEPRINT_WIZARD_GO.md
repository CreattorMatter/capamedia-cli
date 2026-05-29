# Blueprint — Wizard "un click" (`capamedia start`)

> Producto de un workflow de diseño (10 subagentes: 5 mapeo + 3 enfoques + judge
> + síntesis, 2026-05-29). Documento para revisión del owner ANTES de codear.
> No se construye nada hasta aprobación. Backup `v0.28.0` ya existe como red.
>
> **Decisiones del owner (2026-05-29)**: comando = `capamedia start` (alias
> `go`/`wizard`); tests del proyecto migrado **opcionales, off por default**
> (`--run-tests` para activarlos).

## Enfoque elegido (judge)

**`capamedia start`** (alias `go`/`wizard`) — capa delgada Typer + rich sobre el
pipeline YA probado, **cero dependencias nuevas**. Ganó sobre `questionary`
(8.0) y `textual` (6.3) con **8.6**.

Por qué (verificado contra el código, no asumido):
- **Cero deps nuevas.** En `.venv` solo hay `rich` + `typer`. Agregar
  `questionary`/`textual` implica revisión de cadena de suministro y aprobación
  en un CLI bancario. El proyecto ya fuerza UTF-8 en `cli.py:74` por glitches de
  render — meter una TUI pesada va en contra.
- **Reuso honesto.** El estilo interactivo del proyecto YA es selección
  numerada de rich: `_interactive_harness_picker` (`init.py:60`, usa
  `Confirm.ask`) y `fabrics.generate` ya pregunta namespace con
  `Prompt.ask(choices=...)` (`fabrics.py:821`). El wizard reusa ese patrón tal
  cual; los otros enfoques tendrían que *portar* esos primitivos (código nuevo
  disfrazado de reuso).
- **Backbone probado.** `_process_pipeline_service` (`batch.py:1055`) ya tiene
  resume idempotente (`stage_ok`) con test (`test_batch.py:522`). La capa-wizard
  hereda esa cobertura.
- **Honestidad bancaria.** El "menú con flechas" se entrega como **selección
  numerada** (no arrow-keys — eso exige dep prohibida). El "abrir el cloud +
  fan-out de N subagentes paralelos" queda como **gancho v0.29 (Agent SDK),
  deshabilitado con nota honesta**, NO prometido.

## Principios del blueprint

1. **Cero reescritura de engines.** El wizard *orquesta* funciones puras
   existentes; nunca las reimplementa.
2. **Modelo siempre Opus 4.8**, forzado en un solo lugar
   (`model_policy.anthropic_model('opus')`).
3. **Gates humanos** en los puntos sensibles: preview pre-ejecución,
   `BLOCKED_BY_HIGH`/`needs_human_gate` solo en HIGH, **sin auto-push/PR**.
4. **Cada fase es entregable y reversible** por sí sola; los comandos
   shell/batch existentes nunca se rompen (caminos paralelos).
5. **Flags no-interactivos** (`--service --namespace --branch --yes`) para que
   corra en CI/SSH sin TTY sin colgarse.

## Fases (de la más chica/segura a la única capacidad nueva)

| # | Fase | Riesgo | Qué hace | Reusa |
|---|---|---|---|---|
| **0** | Backup + branch + baseline | low | Tag de respaldo + rama `feature/wizard-start` + `pytest` baseline + foto de `--help`. PRE-código. | patrón tarea backup, suite pytest |
| **1** | Esqueleto `capamedia start` | low | Comando que orquesta `_process_pipeline_service` con `workers=1` y flags no-interactivos. Persiste `wizard.json`. Sin prompts aún. | `_process_pipeline_service`, `batch_state`, `model_policy`, `select_engine` |
| **2** | Bienvenida + preflight + menú raíz | low | Panel "Bienvenido a Capa Media" + LOGO; preflight verde/rojo (doctor + PAT + engine) no-bloqueante; menú numerado; detección de `wizard.json` para reanudar. | `init.LOGO`, `doctor`, `probe_azure_devops_pat`, `available_engines`, `Prompt.ask` |
| **3** | Sub-wizard de inputs | low | Servicio (auto-padding), OLA (de `ola_policy`, la lib se DERIVA), acrónimo/namespace, Azure destino (derivado), harnesses (fuerza claude). Resumen pre-ejecución + Confirm. Sin tocar red. | `normalize_service_name`, `ola_policy`, `NAMESPACE_OPTIONS`, `AZURE_PROJECTS`, `_interactive_harness_picker`, `_save_config` |
| **4** | Rama interactiva | medium | Verifica/crea/posiciona rama; convierte el caso `ambiguous` de `_auto_checkout_migrated_branch` (hoy error duro) en picker numerado. Toca red (git). | `_list_remote_branches`, `_checkout_branch`, `_auto_checkout_migrated_branch` |
| **5** | Clone guiado + resumen visual | medium | Plan + Confirm → `clone_service`/`clone_migrated_service` con Progress → Panel unificado del análisis (bus/was/orq, UMPs, TX, BD, properties, secrets + badge LOW/MED/HIGH + EffortProfile). Cierra el gap "el COMPLEXITY se escribe pero no se muestra". | `clone_service`, `clone_migrated_service`, `_collect_report_texts`, `_show_*_table`, `resolve_service_complexity`, `effort_for` |
| **6** | Fabrics + migrate + doublecheck encadenado | medium | Fabrics → gate migrate (local headless / solo preparar / [nube DESHABILITADA v0.29]) → `_process_migrate_workspace` con retries=base+`effort.extra_retries`, Opus fijo, stream → doublecheck auto-encadenado; PARA en `BLOCKED_BY_HIGH`. | `fabrics.generate`, `_process_migrate_workspace`, `_run_service_with_retries`, `_process_doublecheck_workspace`, `self_correction` |
| **7** | Runner de tests reales + cierre | medium | **Único bloque nuevo, OFF por default** (`--run-tests` lo activa): detecta gradlew/pom, corre `./gradlew build/test` via `_run_text_process` con timeout, parsea PASS/FAIL, realimenta `FailureContext` con retry acotado. Resumen final. PR = paso manual. | `_run_text_process`, patrón `_run_gradlew_wsdl_import`, `_extract_build_errors`, `batch_state` |

**Cada fase cierra con: suite verde + revisión antes de declarar listo.**

## Preguntas abiertas

**Resueltas (owner, 2026-05-29):**
1. ✅ **Nombre del comando**: `capamedia start` (alias `go`/`wizard`).
2. ✅ **Tests (Fase 7)**: **opcionales, OFF por default**; `--run-tests` los
   activa, con timeout configurable. El "un click" no queda colgado en builds
   lentos por default.

**Pendientes (se pueden resolver al llegar a la fase):**
3. **Build tool**: el blueprint asume `gradlew` (consistente con
   `tpl-middleware`). ¿Algún namespace genera Maven (`pom.xml`)? ¿El target es
   `build`, `test` o `check`? — se confirma en Fase 7.
4. **Pre-clone para la rama (Fase 4)**: ¿clone ligero del destino para listar
   ramas y luego clone completo, o diferir el branch-picker a post-clone (evita
   clonar dos veces)? — se decide en Fase 4.
5. **Override de Azure destino (Fase 3)**: `AZURE_PROJECTS` cubre el caso
   estándar; los ORQ no estándar usan `--legacy-repo`. ¿Exponer ese override en
   el alfa o dejarlo solo para el modo flags? — se decide en Fase 3.
6. **group_id**: hoy no se auto-detecta desde `pom.xml`. Queda como gap conocido
   (el diseño ganador lo deja fuera de esta iteración).

## Lo que este blueprint NO entrega (honestidad alfa)

- **No** hay menú con flechas reales (selección numerada; arrow-keys exige dep
  prohibida).
- **No** hay fan-out de N subagentes paralelos "en la nube" — eso es v0.29
  (Agent SDK), documentado como gancho deshabilitado, no prometido.
- **No** hay auto-push ni creación de PR (revisión humana obligatoria en banca).
