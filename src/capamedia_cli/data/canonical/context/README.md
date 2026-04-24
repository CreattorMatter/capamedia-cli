# Configuracion AI - Capa Media OLA1

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

## Flujo operativo portable

| Comando shell | Que hace |
|---|---|
| `capamedia clone <servicio>` | Trae legacy, UMPs y TX |
| `capamedia fabrics generate` | Genera el arquetipo oficial con MCP Fabrics |
| `capamedia ai migrate --engine codex` | Ejecuta la migracion con Codex/Claude headless |
| `capamedia ai doublecheck --engine codex` | Corre checklist + autofixes + re-check |
| `capamedia review` | Auditoria final deterministica |

Claude Code puede exponer slash commands legacy (`/migrate`, `/doublecheck`),
pero el flujo recomendado para cualquier IA es el shell flow anterior.

## Subagentes disponibles

| Agente | Cuando se usa |
|---|---|
| `analista-legacy` | Se invoca automaticamente en pre-migracion |
| `migrador` | Se invoca automaticamente durante la migracion |
| `validador-hex` | Se invoca despues de cada bloque para verificar hexagonal |
| `qa-generator` | Se invoca en post-migracion para generar casos de uso |
