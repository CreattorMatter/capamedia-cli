---
name: post-migracion
description: Audita un proyecto Java migrado contra la checklist BPTPSRE y genera reporte pass/fail por bloque con severidad y accion sugerida
allowed-tools: Read Glob Grep Bash Write Agent
---

# /post-migracion

Ejecuta la auditoria de calidad post-migracion contra las reglas vivas del equipo BPTPSRE de Banco Pichincha.

**NO modifica codigo.** Solo audita y reporta. Los fixes se hacen en un flujo aparte.

## Prerequisitos
- Proyecto Java migrado en el directorio actual
- ANALISIS_<ServiceName>.md disponible para cross-reference
- Acceso a `prompts/post-migracion/03-checklist.md` (cargado via `AGENTS.md` o `CLAUDE.md`, segun el harness)

## Cuando se usa
- Despues de correr `/migrar` y antes de abrir PR
- Para auditar servicios que ya estan en `develop` antes de pasar a `release`

## Input

Dos argumentos (el segundo es opcional pero recomendado):

1. **`<MIGRATED_PATH>`** — path al proyecto migrado (ej: `C:\Dev\Banco Pichincha\CapaMedia\0007\destino`). OBLIGATORIO. Si no se pasa, asumir el directorio actual.
2. **`<LEGACY_PATH>`** — path al servicio legacy original (ej: `C:\Dev\Banco Pichincha\CapaMedia\0007\legacy\sqb-msa-wsclientes0007`). OPCIONAL pero recomendado: habilita el análisis cruzado del BLOQUE 0 (WSDL legacy vs migrado, operaciones, namespaces, XSDs).

Si el segundo argumento no se pasa, los Checks 0.3/0.4/0.5 degradan a severidad MEDIUM con la nota "legacy no provisto, cruce saltado".

## Pasos

1. **Bloque 0: Pre-check + análisis cruzado legacy ↔ migrado**
   - 0.1 Tipo de proyecto (REST/SOAP/MVC) y gold standard aplicable (REST → `tnd-msa-sp-wsclientes0024`; SOAP → `tnd-msa-sp-wsclientes0015`)
   - 0.2 Conteo de operaciones WSDL (legacy vs migrado) + veredicto conversacional vs framework usado ("¿es 1 op? → ¿va REST? → ¿está OK?")
   - 0.3 Nombres de operaciones coinciden entre legacy y migrado (solo si `<LEGACY_PATH>` provisto)
   - 0.4 `targetNamespace` del WSDL coincide (solo si `<LEGACY_PATH>` provisto)
   - 0.5 XSDs referenciados están presentes en el migrado

2. **Ejecutar la checklist** (`prompts/post-migracion/03-checklist.md`) bloque por bloque (1 a 14)
   - Cada bloque referencia su origen: PDF oficial, feedback Jean Pierre Garcia, commits especificos, MCP fabrics
   - Para cada regla: pass/fail con evidencia (archivo + linea)
   - Severidad por hallazgo: HIGH / MEDIUM / LOW
   - Accion sugerida concreta para cada fail

3. **Generar reporte estructurado** `CHECKLIST_<ServiceName>.md` con:
   - Resumen ejecutivo (pass/fail totales por bloque)
   - Detalle por bloque con violaciones encontradas (incluye diálogo conversacional del Check 0.2)
   - Tabla de severidad agregada
   - Lista priorizada de fixes (HIGH primero)
   - Recomendacion: APTO PARA PR / REQUIERE FIXES

## Ejemplo de uso

```
# Solo el proyecto migrado (checks 0.3/0.4/0.5 degradan a MEDIUM)
/post-migracion C:\Dev\Banco Pichincha\CapaMedia\0007\destino

# Con legacy para análisis cruzado completo (recomendado)
/post-migracion C:\Dev\Banco Pichincha\CapaMedia\0007\destino C:\Dev\Banco Pichincha\CapaMedia\0007\legacy\sqb-msa-wsclientes0007
```
