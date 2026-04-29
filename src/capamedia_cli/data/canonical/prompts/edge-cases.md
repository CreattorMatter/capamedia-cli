---
name: edge-cases
title: Implementar y cerrar edge cases Discovery
description: Revisa Discovery edge cases, implementa o prueba lo faltante en el servicio migrado, actualiza trazabilidad y repite checklist hasta que Block 22 quede sin pendientes.
type: prompt
scope: project
stage: post-migration
source_kind: any
framework: any
complexity: high
preferred_model:
  anthropic: claude-opus-4-7
fallback_model: opus
allowed_tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Task
---

# edge-cases

Cerrar los casos de borde detectados por Discovery sin ensuciar el repo
migrado oficial.

## Objetivo

Para cada edge case de Discovery:

1. Verificar si ya esta implementado o cubierto por tests.
2. Si falta, implementar el comportamiento minimo correcto en `destino/`.
3. Agregar o ajustar tests ejecutables.
4. Actualizar trazabilidad con decision, archivos tocados y prueba asociada.
5. Repetir `capamedia checklist` hasta que el Block 22 no tenga pendientes.

No inventes datos. Si falta evidencia, escribir `[VERIFICAR]` y dejar un
handoff concreto con owner/fuente esperada.

## Entradas

Ejecutar desde el workspace root, no desde `destino/`.

Leer en este orden:

1. Reporte Discovery actual:
   - preferido: `.capamedia/reports/discovery-edge-cases-*.md`
   - legacy/fallback: `DISCOVERY_EDGE_CASES*.md`
   - si no existe, correr `capamedia discovery edge-case --here`
2. WSDL/XSD:
   - preferido: `.capamedia/discovery/<servicio>/specs/`
   - cache sparse: `.capamedia/specs/`
   - legacy/fallback: `destino/*/src/test/resources/discovery/`
3. Proyecto migrado: `destino/<namespace>-msa-sp-<servicio>/`
4. Legacy: `legacy/<repo-legacy>/`
5. Reportes existentes: `MIGRATION_REPORT.md`, `CHECKLIST_*.md`,
   `COMPLEXITY_*.md`, `ANALISIS_*.md`

## Regla de higiene de repo

Los WSDL/XSD Discovery son evidencia local de CapaMedia. No deben quedar dentro
del repo migrado oficial.

- No crear archivos bajo `destino/*/src/test/resources/discovery/`.
- Si existen WSDL/XSD generados ahi y estan untracked, moverlos a
  `.capamedia/discovery/<servicio>/specs/` y eliminar la carpeta generada.
- Si estan trackeados o mezclados con tests reales, no borrarlos sin evidencia:
  dejar `[VERIFICAR]` en el reporte y explicar el handoff.
- No subir `.capamedia/` al repo migrado.

## Proceso

### Paso 1 - Detectar paths

Identificar:

- `MIGRATED=destino/<namespace>-msa-sp-<servicio>`
- `LEGACY=legacy/<repo-legacy>`
- `REPORT=.capamedia/reports/discovery-edge-cases-<servicio>.md` o el
  `DISCOVERY_EDGE_CASES*.md` existente.

Si hay mas de un candidato, elegir por el service name de `.capamedia/config.yaml`
o por el sufijo `ws...NNNN`. Si sigue ambiguo, detenerse con `[VERIFICAR]`.

### Paso 2 - Extraer edge cases

Leer el bloque `DISCOVERY_EDGE_CASES:` y la tabla `Discovery edge-case coverage`.
Armar una lista con:

- codigo
- severidad
- evidencia Discovery
- estado actual
- archivos/tests ya mencionados

Considerar pendiente cualquier caso con `PENDIENTE`, `TBD`,
`<pendiente_validar>`, `not_probed`, `not_provided`, `sin decision` o sin prueba
asociada.

### Paso 3 - Verificar implementacion real

Para cada codigo:

1. Buscar evidencia en `destino/`:
   - codigo productivo
   - tests unitarios/integracion
   - configuracion `application.yml` / `helm/*.yml`
   - mappers, adapters, validators, handlers de error
2. Buscar el comportamiento esperado en:
   - legacy `legacy/`
   - WSDL/XSD de `.capamedia/discovery` o `.capamedia/specs`
   - `COMPLEXITY_*.md` / `ANALISIS_*.md`
3. Clasificar:
   - `IMPLEMENTADO`: hay codigo y test ejecutable.
   - `YA_CUBIERTO`: el comportamiento ya existe y el test lo prueba.
   - `NO_APLICA`: la evidencia demuestra que no aplica al migrado.
   - `HANDOFF_[VERIFICAR]`: falta evidencia o dato externo.
   - `FALTA_IMPLEMENTAR`: no existe cobertura suficiente.

### Paso 4 - Implementar lo faltante

Si esta `FALTA_IMPLEMENTAR`:

- aplicar cambios minimos en `destino/`
- respetar arquitectura hexagonal y reglas del banco
- no re-migrar desde cero
- no tocar archivos no relacionados
- agregar o ajustar tests ejecutables
- si el dato exacto no existe, usar `[VERIFICAR]` y handoff en vez de inventar

### Paso 5 - Actualizar trazabilidad

Actualizar `REPORT` y `MIGRATION_REPORT.md`.

Por cada edge case dejar una linea o tabla con:

```text
codigo: <edge_case_code>
decision: IMPLEMENTADO | YA_CUBIERTO | NO_APLICA | HANDOFF_[VERIFICAR]
evidencia: <legacy/wsdl/xsd/test/reporte usado>
archivos_tocados: <paths>
prueba: <comando o test exacto>
handoff: <solo si aplica>
```

No dejar `PENDIENTE`, `TBD`, `<pendiente_validar>` ni `not_probed` como estado
final salvo dentro de un handoff marcado explicitamente con `[VERIFICAR]`.

## Validacion obligatoria

Desde el workspace root:

```bash
capamedia checklist ./destino/<namespace>-msa-sp-<servicio> --legacy ./legacy/<repo-legacy>
```

Ejemplo:

```bash
capamedia checklist ./destino/csg-msa-sp-wsreglas0010 --legacy ./legacy/sqb-msa-wsreglas0010
```

Si el Block 22 sigue con pendientes:

1. Leer el detalle exacto del checklist.
2. Corregir implementacion, tests o trazabilidad.
3. Volver a correr el mismo `capamedia checklist`.
4. Repetir hasta que Block 22 quede PASS o el unico residuo sea un
   `HANDOFF_[VERIFICAR]` concreto y justificado.

## Salida final

Responder con:

- estado final del Block 22
- edge cases cerrados
- archivos modificados
- tests/comandos ejecutados
- handoffs `[VERIFICAR]` si quedaron
- path del reporte actualizado
