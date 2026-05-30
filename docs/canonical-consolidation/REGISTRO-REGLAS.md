# Registro de consolidación del canonical

## Estado (2026-05-30)

- ⚠️ **Bug de ruta corregido:** la ruta real tiene **espacios**
  (`Banco Pichincha/Capa Media`), no guiones. Mientras estuvo mal, los `grep`
  fallaban en silencio y se generaron números de línea y secciones inventados.
  Todo lo de abajo está verificado con la ruta correcta + el contrato real.
- ✅ **Backup real:** tag `backup-canonical-pre-consolidacion-20260530` +
  `_backup_canonical/canonical-20260530/` (45 `.md`, gitignored).
- ✅ **Regla #1 (estructura de error) consolidada** → commit `9d5a158` (sin push).

## Regla del owner (intocable)

No borrar ni editar prompts hasta validar lo nuevo a fondo. Se construye al lado,
se verifica (diff + **código/contrato como árbitro**) y recién se reemplaza.
Backup siempre.

## Principio de arquitectura

- **Una regla, un solo hogar.** Cada regla en UN home; los demás la **referencian**,
  no la copian. Menos líneas por regla = menos costo y menos confusión para la IA.
- **El árbitro es el artefacto ejecutable** (contrato XSD/WSDL, código desplegado,
  `*_policy.py`). NUNCA un `.md` escrito de memoria. ← causa raíz de las
  "contradicciones sobre contradicciones".

## Mapa real prompt → código (verificado, 68 .py)

| Prompt | refs | Dónde |
|---|---|---|
| `checklist-rules.md` | 4 | version_policy, checklist_rules, canonical, clone |
| `migrate-rest-full.md` | 3 (+12 doc/test) | version_policy, canonical, clone |
| `migrate.md` | 2 | batch, ai |
| `migrate-soap-full.md` | 2 | canonical, clone |
| `check/doublecheck/analisis-*/edge-cases` | 1 c/u | ai / canonical / checklist_rules |
| `clone/fabric/qa/qa-review/qacases/info` | 0 | renderizados a harness, no cargados por nombre |

## Servicios de referencia reales (en disco, dir padre `Capa Media/`)

- `0077/destino/tnd-msa-sp-wsclientes0077`
- `OLA1/WSClientes0013/destino/tnd-msa-sp-wsclientes0013`

Usar para validar reglas contra el código que de verdad se despliega.

---

## Regla #1 — Estructura de error ✅ CONSOLIDADA (commit 9d5a158)

### Árbitro: contrato XSD `GenericError` (idéntico en 0077 y 0013)

7 campos en orden, todos `minOccurs=1`:

```
1. codigo   2. mensaje   3. mensajeNegocio   4. tipo   5. recurso   6. componente   7. backend
```

El populador real es `infrastructure/soap/helper/SoapResponseHelper.java`.

### La contradicción que había (3 vías, todas distintas)

| Fuente | Estructura |
|---|---|
| **XSD REAL** (0077+0013) | codigo, mensaje, mensajeNegocio, tipo, recurso, componente, backend |
| `bank-error-structure.md` (se decía "fuente de verdad") | inventó mensajeCliente/mensajeAplicacion/momentoError; faltaban mensaje/recurso/componente |
| `checklist_rules.py:2840` (docstring) | "8 campos" + severidad (no se enforcea) |
| `CLAUDE.md` / `check.md` | "8 campos" |

El PDF citado por el home como autoridad (`BPTPSRE-Estructura de error-...pdf`)
**no existe en el repo**. El home se escribió de memoria → era el más equivocado.

### Corrección aplicada

- `bank-error-structure.md`: tabla + ejemplos XML/Java reescritos al contrato real;
  nota explícita de campos inexistentes; cita al XSD en vez del PDF; punto 5 del
  migrador corregido (recurso/componente).
- `CLAUDE.md` L27 + `check.md` L103: "8 campos" → "7 campos del contrato XSD".
- `checklist_rules.py` run_block_15 docstring: 8/severidad → 7 campos reales.
- Playbooks (`migrate-*`, `doublecheck`, `qa`, `log-transaccional-orq`): 0 campos
  fantasma (ya estaban bien; el daño estaba solo en los docs de referencia).
- **950 tests verdes**, sin cambio de lógica. Commit `9d5a158` (sin push).

---

## Regla #2 — phantoms dominio error + drift versión ✅ (commit 7a81b55)

- Tabla de backend codes (00045 BANCS / 00638 IIB / 00000 no-oficial) trasladada
  a su hogar natural `bank-error-codes.md` (antes solo en log-transaccional-orq.md).
  Verificado vs código real del 0077 (`BackendCodesProperties.java`: iib=00638, bancsApp=00045).
- `reference_error_types.md` (phantom, 4 refs) → `bank-error-structure.md`.
- `reference_codigos_backend.md` (phantom, 3 refs) → `bank-error-codes.md`.
  Incluía instrucción ROTA en `self_correction.py` (apuntaba a archivo inexistente).
- `documentacion.py`: `"3.5.13"` hardcoded → `SPRING_BOOT_BASELINE_VERSION`.

## Regla #3 — phantom feedback_bancs_header_out_no_echo.md ✅ (commit a41a3fb)

- 2 refs, código no lo usa. El gap `<bancs>`-no-echo ya vivía completo inline en
  `bank-error-structure.md`. Se quitó la muleta + se reapuntó la ref de
  log-transaccional-orq.md al hogar real. Sin pérdida de info.

## Pendientes mapeados (NO tocados)

### #4 Nombres `01-`/`03-` en SKILL.md / prompts — NO es bug, BAJA prioridad
**Hallazgo del árbitro:** `commands/canonical.py:47-56` tiene un MAPA de alias
INTENCIONAL que resuelve `pre-migracion/01-analisis-servicio.md` →
`prompts/analisis-servicio.md` (y similares). Los nombres viejos en los SKILL.md
NO están rotos: el código los traduce. Tocarlos a ciegas rompería el mapa. Es deuda
cosmética que el código ya maneja → dejar como está salvo decisión explícita.

### #5 `agents/` vs `context/` — NO es duplicado, es INTENCIONAL ✅ (descartado)
**Hallazgo del árbitro:** `canonical.py:104-107` carga `agents/` como kind=`agent`
(subagente ejecutable) y `context/` como kind=`context` (conocimiento inyectable).
El diff confirma que NO son copias: el de context tiene `name: <x>-context`, kind
distinto, y una nota *"Para el subagente ejecutable ver agents/..."*. Se referencian
a propósito. Tests dependen de ambos (`test_canonical.py:122/125`,
`test_adapters.py:129`). Borrar uno rompe la dualidad agente↔contexto (justo el
patrón neutro que se busca). **NO tocar.**

### #6 Monolito `bank-official-rules.md`
1148 líneas, 69 headers (`## Regla N`), gate de PR (`validate_hexagonal.py`). Bien
estructurado. Consolidar valores que repite (versiones → policy, etc.).

## Loop por regla (no destructivo)

1. grep provenance real → 2. diff fuentes → 3. **verificar vs código/contrato** →
4. dejar la verdad en el home → 5. los demás referencian → 6. tests → ✅.
