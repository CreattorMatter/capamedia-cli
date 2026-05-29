# capamedia-cli como orquestador

> Documento de diseño. Norte arquitectónico de v0.28+. Fija el modelo mental
> y el roadmap; no todo lo descrito está implementado (cada sección marca el
> estado real).

## North Star — el orquestador "un click" (visión del owner, 2026-05-28)

La esencia del producto: **un click que migra un servicio de 0 a 100**, de punta
a punta, con subagentes en cada etapa, aprovechando al máximo Opus 4.8 y
workflows. Hoy esto es **alfa**; el norte es una experiencia guiada:

1. **Instalación simple** (un click, sin fricción) → pantalla *"Bienvenido a
   Capa Media"*.
2. **Elegir OLA** (el sistema soporta varias olas y se actualiza; el wizard
   muestra las disponibles).
3. **Configuración** navegable con flechas (estilo menú de Claude Code).
4. **Wizard de migración** que pide lo mínimo para tener contexto completo:
   - Servicio a migrar.
   - Acrónimo de nomenclatura (`tnd`/`csg`/`tpr`/…).
   - Proyecto Azure DevOps destino.
   - Rama: la **verifica/crea**, se posiciona, y trae el legacy + `destino/`.
5. **Resumen automático** del análisis: tipo (BUS/WAS/ORQ), UMPs, TX, properties
   referenciadas → habilita correr **Fabrics**.
6. **"Migrar automáticamente"**: abre el cloud, manda contexto + orden, migra.
7. **Doublecheck** automático tras la migración.
8. **Tests**: llegar hasta correr los tests del servicio migrado.

Todo orquestado con **subagentes de inicio a fin**. Las dimensiones de abajo
son los cimientos técnicos de esa experiencia; el roadmap las ordena hacia el
"un click".

## Decisión de modelo — siempre Opus 4.8 (owner, 2026-05-28)

El modelo de trabajo es **Opus 4.8 siempre** — calidad sobre costo. La
complejidad del servicio **no** modula el modelo (es opus para todos); modula
las otras palancas de esfuerzo (reasoning effort de Codex, retries-extra, gate
humano). Implementado en
[`core/effort_policy.py`](../src/capamedia_cli/core/effort_policy.py).

## Premisa

`capamedia` no es un generador de prompts ni un wrapper de un modelo. Es un
**orquestador**: reparte trabajo heterogéneo (N servicios, M etapas) a workers
heterogéneos (engines, modelos, subagentes) y **verifica el resultado en cada
frontera**. La pregunta de diseño no es "¿qué prompt es mejor?" sino:

> ¿quién hace cada parte, con qué modelo, bajo qué contrato, y con qué gate
> entre etapas?

Un orquestador maduro se mide en cuatro dimensiones. Hoy cubrimos cada una a
medias:

| Dimensión | Hoy | Objetivo |
|---|---|---|
| **Rol → modelo** | Un modelo para todo | Modelo por rol según fortaleza/costo |
| **Complejidad → esfuerzo** | Se calcula, no se usa para orquestar | El ranking decide modelo/profundidad/retries por servicio |
| **Contratos entre etapas** | Solo `migrate` exige JSON Schema | Cada transición con contrato verificable |
| **Gates** | Fabrics (duro) + review (final) | Gate verificable en cada frontera |

---

## Dimensión 1 — Rol → modelo

Cada etapa del pipeline es un **rol**, y cada rol tiene un perfil de cómputo
distinto. Usar un solo modelo para todo desperdicia capacidad en lo simple y
queda corto en lo complejo.

> **Nota (owner 2026-05-28)**: la decisión vigente es **siempre Opus** para el
> trabajo de migración. La tabla de abajo es el modelo conceptual de roles; en
> la práctica el migrador corre en Opus 4.8 para todas las complejidades. Los
> tiers `sonnet`/`haiku` quedan como opción para roles auxiliares baratos
> (revisores, documentador) a evaluar más adelante.

| Rol | Etapa CLI | Tier conceptual | Por qué |
|---|---|---|---|
| **Analista de legacy** | discovery / análisis | `opus` (Opus 4.8, 1M ctx) | Lee ESQL + msgflow + WSDL + UMPs completos sin truncar. Razonamiento profundo |
| **Migrador** | `ai migrate` | **`opus` siempre** | Escribe el hexagonal. Calidad sobre costo |
| **Corrector** | `ai doublecheck` | `opus` / `sonnet` | Aplica checklist + autofix |
| **Revisores por dimensión** | review AI (hexagonal/bancs/error/helm) | `haiku` ×N en paralelo | Baratos, paralelos, structured output |
| **QA Karate** | agente SQA Migration | `sonnet` | Genera features/XMLs |
| **Documentador** | `documentacion` | `haiku` | Plantilla determinista |

**Estado real:**
- ✅ La infra existe: cada asset del canonical declara `preferred_model.anthropic`
  ([core/canonical.py:49](../src/capamedia_cli/core/canonical.py)) y un
  `fallback_model` (tier lógico).
- ✅ **v0.28.0**: los IDs de modelo se centralizaron en
  [core/model_policy.py](../src/capamedia_cli/core/model_policy.py)
  (`opus → claude-opus-4-8`). Antes vivían hardcodeados y desactualizados
  (`claude-opus-4-7`) en cada adapter.
- ⏳ **Falta**: poblar `preferred_model` en los assets según la tabla de roles.
  Hoy casi todo cae al `fallback_model` default (`sonnet`).

**Opus 4.8 desbloquea el rol "analista"**: un ORQ con 10 UMPs + WSDL + ESQL no
entra en contextos chicos; en 1M sí. Es la pieza que faltaba para que el
analista lea el legacy completo sin trocear.

---

## Dimensión 2 — Complejidad → esfuerzo (el insight)

Ya calculamos complejidad y **no la usamos para orquestar**.

`score_complexity(op_count, ump_count, has_db)`
([core/legacy_analyzer.py:316](../src/capamedia_cli/core/legacy_analyzer.py))
devuelve `low | medium | high`, y `capamedia batch complexity` rankea N
servicios. Pero ese resultado **solo se escribe en `COMPLEXITY_<svc>.md`**: el
batch después trata a todos igual — mismo engine, mismo modelo, mismo flujo,
mismos retries.

El orquestador usa ese ranking para decidir el **nivel de esfuerzo por
servicio**. Con la decisión "siempre Opus", el modelo no varía; lo que escala
es reasoning effort (Codex), retries-extra y la señal de gate humano:

| Complejidad | Modelo | Reasoning (Codex) | Retries extra | Gate humano |
|---|---|---|---|---|
| **LOW** (WAS 1-op, sin BD) | `opus` | `high` | +0 | no |
| **MEDIUM** | `opus` | `xhigh` | +1 | no |
| **HIGH** (ORQ, muchos UMPs, BANCS, log transaccional) | `opus` | `xhigh` | +2 | **sí** |

**Estado real:**
- ✅ `score_complexity` y `batch complexity` existen y funcionan.
- ✅ **v0.28.1**: [`core/effort_policy.py`](../src/capamedia_cli/core/effort_policy.py)
  traduce complejidad → `EffortProfile` (modelo opus + reasoning + retries-extra
  + gate). `resolve_service_complexity()` lee `COMPLEXITY_<svc>.md` o recalcula.
- ✅ **v0.28.1**: `capamedia batch migrate --auto-effort` (opt-in) deriva el
  esfuerzo por servicio, muestra el plan (transparencia) y señala los HIGH para
  revisión humana. `--model` explícito sigue ganando.
- ⏳ **Falta**: extender `--auto-effort` a `batch pipeline`; volverlo default
  cuando esté validado en producción.

(Histórico) La complejidad del **asset** (`CanonicalAsset.complexity`,
[canonical.py:45](../src/capamedia_cli/core/canonical.py)) ya mapeaba a
`reasoning_effort` en Codex — pero es la complejidad del *prompt*, no la del
*servicio*. Lo nuevo es orquestar por la complejidad del *servicio*. Sigue
pendiente:
  mejora de orquestación de mayor ROI porque reaprovecha algo ya construido.

---

## Dimensión 3 — Contratos entre etapas

El pipeline es `clone → fabrics → migrate → doublecheck → review → qa`. Un
orquestador necesita que cada etapa devuelva un **contrato verificable** para
decidir "pasó → sigo; falló → reintento o escalo".

**Estado real:**
- ✅ `migrate` y `doublecheck` ya exigen salida JSON Schema
  (`_ensure_migrate_schema`, `_ensure_doublecheck_schema`).
- ⚠️ Para Codex el schema se valida nativo (`--output-schema`); **para Claude
  se inyecta en el prompt y se extrae el último JSON válido post-hoc**
  ([core/engine.py](../src/capamedia_cli/core/engine.py)) — frágil: si el modelo
  escribe texto extra o dos bloques JSON, falla.
- ⏳ **Falta**: structured output nativo en el path Claude (requiere migrar de
  shell-out `claude -p` al Agent SDK — ver Roadmap fase 3). Y contratos
  explícitos en las etapas que hoy no los tienen (`clone`, `documentacion`).

---

## Dimensión 4 — Gates

**Estado real:**
- ✅ Fabrics es gate duro (sin arquetipo no avanza).
- ✅ `review` es gate determinista final (Python, los Checks de
  [core/checklist_rules.py](../src/capamedia_cli/core/checklist_rules.py)).
- ✅ **v0.28.0**: el contrato (canonical) y los gates (checks) quedaron bajo
  test de consistencia
  ([tests/test_canonical_code_consistency.py](../tests/test_canonical_code_consistency.py))
  y las constantes compartidas en single-source
  ([tests/test_version_policy_sync.py](../tests/test_version_policy_sync.py)).
  Esto cierra el drift que causó v0.27.2.
- ⏳ **Falta**: gates verificables *dentro* de la etapa de agente (hook
  PostToolUse → `capamedia check` tras cada edición), para que el worker se
  autocorrija en loop sin esperar al doublecheck final.

---

## El drift como problema de orquestador

Los tres releases del 2026-05-27 (0.27.0 → 0.27.2) fueron el mismo problema:
**el código (gates) y el canonical (contrato) evolucionaban por separado**. El
canonical es lo que el orquestador le pide a sus workers; los checks son lo que
les exige al recibir. Si divergen, pide una cosa y exige otra.

v0.28.0 ataca esto de raíz con dos mecanismos complementarios:
1. **Single-source de constantes** (`model_policy.py`, `version_policy.py`):
   los valores viven en un solo lugar; el canonical los cita y un test verifica
   la cita. Atrapa drift de *valores* (fue el caso de v0.27.2: `4.1.133.Final`).
2. **Test de consistencia canonical↔código**: congela el drift heredado en un
   baseline documentado y falla ante drift *nuevo*. Atrapa checks/reglas
   huérfanas (gaps de enforcement).

---

## Roadmap

### v0.28.0 — Cerrar el drift (hecho)
- [x] `model_policy.py`: fuente única de modelos, Opus 4.8.
- [x] `NETTY_WEBFLUX_ALLOWED_VERSION` a `version_policy.py` (single-source).
- [x] Test de consistencia canonical↔código con baseline.
- [x] Test de sync version_policy↔canonical.
- [x] Este documento.

### v0.28.1 — Orquestación por complejidad (hecho)
- [x] `core/effort_policy.py`: complejidad → `EffortProfile` (siempre Opus +
      reasoning + retries-extra + gate humano).
- [x] `batch migrate --auto-effort` (opt-in): deriva esfuerzo por servicio,
      muestra el plan, señala HIGH para revisión humana.
- [x] Mapeo de modelos Codex centralizado en `model_policy.py` (fuente única
      total tier→modelo).

### v0.28.x — Completar la orquestación (próximo)
- [ ] Extender `--auto-effort` a `batch pipeline`.
- [ ] Volver `--auto-effort` default cuando esté validado en producción.
- [ ] Poblar `preferred_model` en los assets auxiliares (revisores/doc → haiku).
- [ ] `capamedia doctor`: avisar si el `model_policy` quedó atrás del modelo
      activo de la sesión.

### v0.29 — Workers finos (Agent SDK) + camino al "un click"
- [ ] Migrar `ClaudeEngine` de shell-out `claude -p` al Agent SDK: structured
      output nativo, prompt caching del canonical, subagentes programáticos
      (Dimensión 3). *Verificar nombre exacto del package del SDK antes.*
- [ ] Doublecheck por subagentes paralelos (un revisor por dimensión, `haiku`).
- [ ] Cerrar gaps de enforcement del baseline (Block 4, códigos fuera de
      catálogo) como Checks ejecutables.

### Backlog — Capacidades a evaluar
- Progressive disclosure del canonical vía Skills (ataca la "fatiga de
  contexto" que motivó la compactación de v0.26.2 de raíz).
- Hook PostToolUse → `capamedia check` (gate intra-etapa).
- Memoria con gate humano (`canonical propose`) para feedback de expertos del
  banco — NO memoria automática (el incidente de Netty mostró el riesgo).
- Distribución por plugin de Claude Code (evaluar contra el modelo multi-harness).

---

## Principios

1. **Un solo modelo no sirve para todo.** Asignar por rol y por complejidad.
2. **Toda frontera tiene un contrato verificable.** Si el orquestador no puede
   verificar el resultado de una etapa, no puede decidir el siguiente paso.
3. **Código y canonical son una sola verdad.** Cualquier valor compartido vive
   en un módulo `*_policy.py` y el canonical lo cita; un test verifica la cita.
4. **El drift se previene con tests, no con disciplina.** Lo de hoy lo demostró.
