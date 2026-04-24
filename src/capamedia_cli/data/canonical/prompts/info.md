---
name: info
title: Info - dashboard de pendientes del workspace
description: Muestra que archivos faltan (properties del banco, secretos KV, UMPs/TX, handoffs catalog-info/sonar) en el workspace actual. Contempla los 3 tipos de servicio (WAS, BUS, ORQ).
type: prompt
scope: project
stage: any
source_kind: any
framework: any
complexity: low
preferred_model:
  anthropic: claude-opus-4-7
fallback_model: opus
allowed_tools:
  - Bash
  - Read
---

# /info — dashboard de pendientes del workspace

Muestra un resumen consolidado de **que tiene y que le falta** al workspace
actual para estar listo para PR. Contempla los 3 tipos de servicio:

- **WAS**: properties (`<ump>.properties`, `<svc>.properties`), secretos KV
  si hay BD, UMPs clonadas, handoffs catalog-info/sonar.
- **BUS (IIB)**: UMPs + TX repos + configurables CSV + handoffs.
- **ORQ**: servicios downstream que invoca (deben ser los migrados de
  `tpl-middleware`, no legacy), handoffs.

## Cuando usarlo

- Al inicio de una sesion de trabajo, para ver que esta pendiente.
- Despues de `clone` o `adopt`, para confirmar que los reportes se
  generaron bien.
- Antes de `checklist` / `doublecheck`, para saber que falta pedir al owner.
- Antes del PR, para asegurar que no quedan inputs sin resolver.

## Accion

Ejecutar:

```bash
capamedia info
```

### UMPs faltantes (v0.23.13)

Si el usuario migro un servicio pero no trajo sus UMPs, el CLI detecta las
UMPs **referenciadas** por el legacy (en `pom.xml` + `import`s Java) y las
compara con las carpetas `umps/*`. Las **referenciadas pero NO clonadas**
se marcan explicitamente como faltantes, con:

- El codigo de la UMP (ej. `umpclientes0025`).
- El archivo `.properties` esperado (ej. `umpclientes0025.properties`).
- El comando `git clone` exacto para traerla.

Sin las UMPs clonadas, el detector de properties **no ve las keys** que
cada UMP requiere del banco — y la migracion queda incompleta. `/info` lo
flagea como prioridad maxima en el "siguiente paso".

Si el usuario esta parado en:
- La raiz del workspace (con `destino/` + `legacy/` hermanos) → autodetecta OK.
- Adentro de `destino/<svc>/` → sube 2 niveles automaticamente.

Output del comando:

```
╔═ capamedia info ═════════════════════════════════════╗
║ Servicio: wsclientes0076                             ║
║ Tipo: WAS · invocaBancs: NO                          ║
║ Workspace: C:\Dev\BancoPichincha\wsclientes0076      ║
╚═══════════════════════════════════════════════════════╝

Properties del banco
  Catalogo compartido (embebido en CLI, no requiere accion):
    ✓ generalServices.properties (3 keys)
    ✓ CatalogoAplicaciones.properties (4 keys)
  Pendientes del banco (1):
    ✗ umpclientes0025.properties (6 keys - source: ump:umpclientes0025)
      keys: GRUPO_CENTRALIZADA, RECURSO_01, COMPONENTE_01, COD_DATOS_VACIOS,
            DES_DATOS_VACIOS, UNIDAD_PERSISTENCIA
    -> pegar en `.capamedia/inputs/` o en la raiz del workspace

Secretos Azure Key Vault
  (no aplica a WAS - solo WAS con BD requiere secretos KV)

Downstream / Integraciones
  UMPs clonadas: 1 (ump-umpclientes0025-was)

Handoffs pendientes (NO son bugs del codigo)
  ~ catalog-info.yaml: completar spec.owner con email real + URL Confluence
  ~ .sonarlint/connectedMode.json: reemplazar placeholder con project_key real

Siguiente paso
  1) Pedir los .properties pendientes al owner del servicio
  2) Pegar en .capamedia/inputs/<file>.properties (o en la raiz)
  3) capamedia ai doublecheck --engine codex (o --engine claude/auto)
  4) capamedia review
```

## Interpretacion

- **Catalogo compartido ✓**: resueltos por el CLI embebido, sin accion.
- **Pendientes del banco ✗**: faltan archivos → pedirselos al owner.
- **Secretos KV**: solo WAS con BD; para BUS/ORQ/WAS-sin-BD se saltea.
- **Downstream**: UMPs+TX para BUS/WAS, servicios migrados para ORQ.
- **Handoffs**: items que no pueden autofixearse (son del owner / ops).
- **Siguiente paso**: recomendacion concreta segun el estado.

## No confundir con check y doublecheck

- `/info` — **read-only**, solo muestra estado. No corre el checklist.
- `capamedia check` — corre el checklist contra el codigo (los 20 blocks).
- `capamedia ai doublecheck` — corre checklist + autofixes + re-check.

`/info` es ideal para **entender que falta** antes de arrancar con los otros.
