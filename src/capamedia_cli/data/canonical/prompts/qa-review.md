---
name: qa-review
title: QA - Migrated vs Legacy Service Review + Acceptance Criteria Validation
description: Revisa un servicio migrado (o su legacy counterpart) y valida que cumple los 14 acceptance criteria (AC-01..AC-14). Genera un reporte .md de aprobacion en docs/acceptance-criteria/ del repo migrado.
type: prompt
scope: project
stage: qa
source_kind: any
framework: any
complexity: medium
preferred_model:
  anthropic: claude-opus-4-7
fallback_model: opus
allowed_tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Write
---

# /qa-review — validacion de acceptance criteria

Fuente: `QA/SERVICE_MIGRATION_REVIEW_PROMPT.md` del repo `PromptCapaMedia` (2026-04-22).

Revisa un servicio migrado (o su legacy counterpart) y valida los 14 acceptance
criteria oficiales del equipo QA. El output es un archivo de evidencia en
`docs/acceptance-criteria/<ServiceName>_<Operation>_AcceptanceCriteria.md`
dentro del repo del servicio migrado.

## Analysis Scope

1. Identificar el servicio bajo revision (name, endpoint, operation, version).
2. Capturar la respuesta real (HTTP status, response time, size, encoding,
   estado: OK/ERROR).
3. Documentar la estructura XML/JSON de la respuesta.
4. Detallar headers de salida (headerOut) y, si aplica, el bloque error
   (code, type, resource, component, backend, businessMessage).
5. Si hay error, incluir analisis con:
   - Exception detectada
   - Backend HTTP status
   - Codigo interno
   - Clase afectada
   - Causas posibles
   - Acciones recomendadas

## Acceptance Criteria (MANDATORIO)

Validar los 14 criterios. Para cada uno: ✅ PASS / ❌ FAIL / ⚠️ PARTIAL con
evidencia.

### Funcionales

| # | Criterio | Validacion |
|---|---|---|
| AC-01 | Equivalencia funcional con legacy (mismos campos/valores/semantica) | Comparar campo por campo |
| AC-02 | Contrato de entrada cumple WSDL/OpenAPI | Revisar contrato vs request |
| AC-03 | Contrato de salida cumple WSDL/OpenAPI | Revisar contrato vs response |
| AC-04 | Manejo de errores consistente con legacy (codes, type, resource, component) | Comparar bloque error |
| AC-05 | Logica de negocio preservada (reglas, validaciones, transformaciones) | Comparar con mismo input |

### No-Funcionales

| # | Criterio | Validacion |
|---|---|---|
| AC-06 | Tiempo de respuesta <= legacy (SLA definido) | Medir y comparar |
| AC-07 | Disponibilidad / resilience (timeouts, retries, fallbacks) | Simular core no disponible |
| AC-08 | Seguridad (auth, tokens, sessions) | Revisar headers de seguridad |
| AC-09 | Logs con trace (traceId/correlationId) sin datos sensibles | Revisar logs middleware |
| AC-10 | UTF-8 + XML/JSON parseable | Validar con parser |

### Calidad de codigo (si aplica code review)

| # | Criterio | Validacion |
|---|---|---|
| AC-11 | Coverage unit tests > 85% | Reporte JaCoCo/SonarQube |
| AC-12 | Codigo duplicado 0% | SonarQube / duplication detector |
| AC-13 | Cumple `UNIT_TEST_GUIDELINES` (ver canonical) | Manual review + linter |
| AC-14 | Sin vulnerabilidades critical/high (SCA/SAST) | SonarQube / Snyk |

## Generacion del archivo de evidencia

Al final se debe generar un markdown en el repo del servicio migrado:

```
/docs/acceptance-criteria/<ServiceName>_<Operation>_AcceptanceCriteria.md
```

Ejemplo:
```
/docs/acceptance-criteria/WSClientes0006_ConsultarInformacionBasica01_AcceptanceCriteria.md
```

Estructura del archivo:

```markdown
# Acceptance Criteria – <Service> / <Operation>

## Informacion general
| Field | Value |
|---|---|
| Service | <name> |
| Operation | <operation> |
| Migrated version | <vX.Y.Z> |
| Validation date | YYYY-MM-DD |
| Owner | <name> |
| Overall result | ✅ APPROVED / ❌ REJECTED / ⚠️ APPROVED WITH OBSERVATIONS |

## Resumen de resultados
| # | Criterion | Result | Evidence |
|---|---|---|---|
| AC-01 | Functional equivalence | ✅/❌/⚠️ | Link/descripcion |
| ... | ... | ... | ... |
| AC-14 | No vulnerabilities | ✅/❌/⚠️ | ... |

## Detalle por criterio
### AC-01 – Functional equivalence with legacy
- **Result:** ✅ PASS
- **Evidence:** <descripcion, links, logs, screenshots>
- **Observations:** <si aplica>

(repetir para AC-01..AC-14)

## Findings / Deviations
Lista de findings que no pasan o pasan parcialmente. Para cada uno: impacto,
severidad, plan de remediacion y owner.

## Conclusion
Parrafo corto: el servicio migrado esta listo para produccion, requiere
ajustes, o debe rechazarse.
```

## Golden Rules

- NUNCA marcar ✅ PASS sin evidencia verificable.
- Si un criterio NO aplica, justificarlo explicitamente (no saltearlo).
- El archivo `.md` generado es el artefacto oficial de aprobacion.
- El overall result es **❌ REJECTED** si algun criterio funcional (AC-01..AC-05)
  o de seguridad (AC-08, AC-14) es ❌.
- El overall result es **⚠️ APPROVED WITH OBSERVATIONS** si todos los funcionales
  son ✅ pero hay ⚠️ en no-funcionales o calidad de codigo.
