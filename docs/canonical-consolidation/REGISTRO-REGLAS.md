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

## Pendientes mapeados (NO tocados)

### Phantom `reference_error_types.md` — referenciado, no existe
Refs en `bank-error-structure.md` + `log-transaccional-orq.md`. El código NO lo usa.
La tabla de tipos ya vive inline en `bank-error-structure.md` → repuntar las refs. SAFE.

### Drift de versión — `documentacion.py:1033`
`doc.spring_boot_version or "3.5.13"` → debería ser `SPRING_BOOT_BASELINE_VERSION`
(3.5.14). SAFE.

### Duplicados `agents/` vs `context/` (DIFIEREN)
`analista-legacy.md` (31/32), `migrador.md` (40/40), `validador-hex.md` (81/85).
`qe-migration.md` solo en agents/. Decidir home único por cada uno (diff fino).

### Monolito `bank-official-rules.md`
1148 líneas, 69 headers (`## Regla N`), gate de PR (`validate_hexagonal.py`). Bien
estructurado. Consolidar valores que repite (versiones → policy, etc.).

## Loop por regla (no destructivo)

1. grep provenance real → 2. diff fuentes → 3. **verificar vs código/contrato** →
4. dejar la verdad en el home → 5. los demás referencian → 6. tests → ✅.
