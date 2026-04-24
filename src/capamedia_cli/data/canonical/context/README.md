# Configuracion Claude Code - Capa Media OLA1

## Como usar

Copiar la carpeta `.claude/` completa a la raiz de cada proyecto de migracion:

```bash
cp -r prompts/configuracion-claude-code/.claude/ /path/to/tnd-msa-sp-wsclientes0007/
```

Copiar el `CLAUDE.md` a la raiz del proyecto:

```bash
cp prompts/configuracion-claude-code/CLAUDE.md /path/to/tnd-msa-sp-wsclientes0007/
```

## Que incluye

```
.claude/
  settings.json          <- Permisos, auto-accept, env vars, hooks
  CLAUDE.md              <- Instrucciones del proyecto (alternativa a CLAUDE.md en raiz)
  agents/
    analista-legacy.md   <- Subagente para analisis pre-migracion
    migrador.md          <- Subagente para ejecutar la migracion
    validador-hex.md     <- Subagente para validar arquitectura hexagonal
    qa-generator.md      <- Subagente para generar artefactos QA
  skills/
    pre-migracion/SKILL.md   <- /pre-migracion command
    migrar/SKILL.md          <- /migrate command (legacy alias /migrar)
    post-migracion/SKILL.md  <- /post-migracion command
  rules/
    hexagonal.md         <- Reglas de arquitectura hexagonal
    code-style.md        <- Reglas de estilo de codigo
    bancs.md             <- Reglas de integracion BANCS
    security.md          <- Reglas de seguridad
CLAUDE.md                <- Instrucciones globales del proyecto
```

## Comandos disponibles despues de configurar

| Comando | Que hace |
|---|---|
| `/pre-migracion <ruta_zip>` | Analiza un servicio legacy y genera ANALISIS_*.md |
| `/migrate` | Ejecuta la migracion completa con loop de autocorreccion |
| `/post-migracion` | Genera PENDIENTES_*.md y guia de primera ejecucion |

## Subagentes disponibles

| Agente | Cuando se usa |
|---|---|
| `analista-legacy` | Se invoca automaticamente en pre-migracion |
| `migrador` | Se invoca automaticamente durante la migracion |
| `validador-hex` | Se invoca despues de cada bloque para verificar hexagonal |
| `qa-generator` | Se invoca en post-migracion para generar casos de uso |
