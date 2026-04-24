---
name: bank-checklist-desarrollo
kind: context
priority: 1
summary: Checklist oficial de desarrollo del banco - cobertura 75%, Snyk, SonarLint, azure-pipeline por namespace
---

# Checklist oficial de desarrollo — Banco Pichincha

**Fuente autoritativa**:
`prompts/documentacion/BPTPSRE-CheckList Desarrollo-140426-212740.pdf`.

Este canonical es la **única fuente de verdad** para los thresholds oficiales
del gate de entrega: cobertura, análisis estático, vulnerabilidades y
configuración de pipeline. Cualquier canonical o prompt que mencione alguno
de estos thresholds **debe referenciar este archivo** — no reformular.

## Secciones del checklist oficial

### 1. Cobertura de tests

**Umbral oficial**: **≥ 75%** (line, branch, method).

| Métrica | Umbral | Herramienta |
|---|---|---|
| Line coverage | ≥ 75% | JaCoCo |
| Branch coverage | ≥ 75% | JaCoCo |
| Method coverage | ≥ 75% | JaCoCo |

**Zonas del checklist donde aparece este umbral** (todas deben coincidir con
este canonical):

- `checklist-rules.md` Block 9 Check 9.1 (75%)
- `migrate-rest-full.md` Rule 19 (75%)
- `migrate-soap-full.md` Rule 19 (75%)
- `context/unit-test-guidelines.md` § Coverage requirements (75%)
- `prompts/qa-review.md` AC-11 (75%)

**Exclusiones permitidas** (documentar en `build.gradle`):
- DTOs / records sin lógica.
- Código autogenerado (`build/generated-src/**`, `target/generated-sources/**`).
- Classes de config puras (`@Configuration` sin lógica).

**NEVER**: subir o bajar el umbral unilateralmente. Si el proyecto necesita
un threshold distinto, documentarlo y escalarlo al equipo BPTPSRE.

### 2. Análisis estático — SonarLint local

**MUST**: todo proyecto migrado incluye `.sonarlint/connectedMode.json`
conectado al SonarCloud `bancopichinchaec`.

**Template**: `prompts/configuracion-claude-code/sonarlint/connectedMode.template.json`.

**Guía completa**: `BPTPSRE-Guía de configuración SonarQube for ide
(SonarLint)-140426-180128.pdf` (PDF CDSRL).

Detalles técnicos en `context/sonarlint.md` — este canonical solo marca el
**gate** (SonarLint conectado = obligatorio).

### 3. SonarCloud — reglas custom del banco

**MUST**: configuración en `catalog-info.yaml`:

```yaml
metadata:
  annotations:
    sonarcloud.io/project-key: <UUID>   # formato xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

**Reglas específicas**: ver `context/sonar-custom-rules.md`.

### 4. Vulnerabilidades — Snyk

**MUST**: 0 vulnerabilidades **critical** o **high** en el build final.

**Scan obligatorio** antes del merge al main:
- Dependencies (Gradle lockfile).
- Container image (Dockerfile + base image).

**NEVER**: mergear un PR con vulnerabilidad critical/high sin plan de
mitigación documentado + approval del security lead.

### 5. Pipeline — `azure-pipeline.yml` por namespace

**MUST**: el pipeline Azure DevOps está **namespaced** por servicio
(`tpl-middleware/<namespace>-msa-sp-<svc>`).

El `azure-pipeline.yml` del repo debe:
- Correr `./gradlew build` (incluye tests + JaCoCo ≥ 75%).
- Correr Snyk (critical/high = fail).
- Ejecutar análisis Sonar con el `project-key` del catalog.
- Publicar artifacts (jar + Helm chart) al registry del banco.

**Validación del CLI**: `capamedia check` verifica que `azure-pipeline.yml`
existe y que el project-key del SonarCloud matchea el `catalog-info.yaml`
(Regla 9 de `bank-official-rules.md`).

### 6. Gates obligatorios antes del PR

Resumen del PDF para revisión rápida:

- ✅ Build verde (`./gradlew build` sin warnings críticos).
- ✅ Coverage JaCoCo ≥ 75%.
- ✅ 0 vulns critical/high (Snyk).
- ✅ `.sonarlint/connectedMode.json` versionado.
- ✅ `catalog-info.yaml` completo (Regla 9).
- ✅ `azure-pipeline.yml` presente y ejecutable.
- ✅ Tests siguen `unit-test-guidelines.md` (given/when/then, English).
- ✅ 9 reglas de `validate_hexagonal.py` pasan (script oficial del banco).

## Relación con otros canonicals

- **`bank-official-rules.md`** → las 9 reglas de `validate_hexagonal.py`.
  Este canonical cubre gates adicionales (cobertura, Snyk, pipeline).
- **`unit-test-guidelines.md`** → cómo escribir los tests. Este canonical
  define **cuánto** cobertura exigir (75%).
- **`sonarlint.md` + `sonar-custom-rules.md`** → setup técnico. Este
  canonical marca el **gate** (SonarLint conectado = obligatorio).
- **`checklist-rules.md` Block 9** → checks ejecutables que validan este
  canonical en tiempo de CLI.

## Regla para el agente migrador

1. **Antes de entregar un PR**, correr los 8 gates de la sección §6.
2. **Si coverage < 75%**: agregar tests faltantes (`unit-test-guidelines.md`).
3. **Si Snyk reporta critical/high**: priorizar mitigación antes del merge.
4. **No cambiar los thresholds** sin consultar este canonical — son
   umbrales oficiales del banco.
