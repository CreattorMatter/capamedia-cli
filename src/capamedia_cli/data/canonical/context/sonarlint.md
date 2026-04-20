---
name: sonarlint
title: SonarLint - Setup local con SonarCloud organizacional
description: Guia paso a paso para configurar SonarQube for IDE (SonarLint) contra la organizacion bancopichinchaec de SonarCloud.
type: context
scope: project
stage: setup
---

# SonarLint (SonarQube for IDE) — Setup local

Guía resumida para correr SonarLint en local contra el SonarCloud organizacional del Banco Pichincha (`bancopichinchaec`). Basada en el PDF oficial **CDSRL-Guía de configuración SonarQube for ide (SonarLint)** del 5-feb-2024.

> El objetivo: feedback temprano de issues de calidad y seguridad **antes** del PR, alineado con los Quality Gates organizacionales que ya corren en SonarCloud.

---

## Resumen ejecutivo

1. **Instalar la extensión/plugin SonarQube for IDE** en tu IDE (VS Code o IntelliJ).
2. **Crear una conexión Connected Mode** apuntando a SonarCloud, organización `bancopichinchaec`. Nombre de la conexión: **`bancopichinchaec`** (literal — importa).
3. **Autenticarte vía Azure DevOps** y generar el token. SonarCloud genera un token nombrado por el IDE (ej: `SonarLint-Visual Studio Code`).
4. **Crear el binding** entre la carpeta de tu repo local y el proyecto correspondiente en SonarCloud (lookup por nombre o `projectKey`).
5. **Compartir la configuración** → SonarLint genera `.sonarlint/connectedMode.json` en la raíz del repo. **Versionarlo y commitearlo** para que el resto del equipo lo use sin re-hacer el binding.

A partir de ahí: cada vez que guardás un archivo, SonarLint lo analiza y muestra issues en el panel de problemas del IDE.

---

## Prerrequisitos

### VS Code
- VS Code **1.95.2+**
- Extensión **SonarQube for IDE v4.14.1+** (id: `SonarSource.sonarlint-vscode`)
- SO: Windows x86-64, Linux x86-64, macOS x86-64 / arm-64

### IntelliJ
- IntelliJ IDEA **2024.3.1.1+**
- Plugin **SonarQube for IDE v10.15.0+**
- SO: Windows x86-64, Linux x86-64, macOS x86-64 / arm-64

---

## Paso a paso — VS Code

1. **Instalar extensión.** `Ctrl/Cmd+Shift+X` → buscar *SonarQube for IDE* → Install. Reiniciar VS Code.

2. **Vista SonarQube.** Click en el ícono de SonarQube en la barra lateral izquierda.

3. **Add SonarQube Cloud Connection** → completar:
   - **User Token:** click en `Generate Token` → se abre el navegador → log in con **Azure DevOps** → autorizar → copiar el token y pegarlo.
   - **Organization:** `Banco Pichincha EC` (key: `bancopichinchaec`)
   - **Connection Name:** `bancopichinchaec` (literal, sin variaciones)
   - **Receive notifications:** dejar tildado.
   - `Save Connection`.

4. **Verificar conexión habilitada.** En la vista SonarQube → CONNECTED MODE → debe aparecer `✓ bancopichinchaec`.

5. **Add Project Binding.** Click en `+` al lado de `bancopichinchaec` → buscar tu proyecto (ej: `tnd-msa-sp-wsclientes0024`) → seleccionar → bind.

6. **Share configuration.** Cuando aparezca el toast `Do you want to share this new SonarQube Connected Mode configuration?` → **Share configuration**.

7. **Verificar.** Debe aparecer la carpeta `.sonarlint/` en la raíz del repo con `connectedMode.json` adentro:
   ```json
   {
       "sonarCloudOrganization": "bancopichinchaec",
       "projectKey": "<UUID-del-proyecto>"
   }
   ```

8. **Commitear** `.sonarlint/connectedMode.json` al repo (el resto del equipo no tiene que volver a bindar).

---

## Paso a paso — IntelliJ

1. **Instalar plugin.** `Settings → Plugins → Marketplace` → buscar *SonarQube for IDE* → Install. Reiniciar IntelliJ.

2. **Verificar instalación.** Tab `SonarQube for IDE` debe aparecer en el bottom dock con sub-tabs Current File / Report / Security Hotspots / Taint Vulnerabilities / Log.

3. **Configurar conexión.** `Settings → Tools → SonarQube for IDE` → `+` para crear conexión:
   - **Connection Name:** `bancopichinchaec`
   - **Tipo:** SonarQube Cloud
   - `Next` → si no tenés token, `Create token` → autorizar en navegador → copiar.
   - **Organization:** `Banco Pichincha EC` (`bancopichinchaec`)
   - Confirmar notificaciones → Create.

4. **Project binding.** `Settings → Tools → SonarQube for IDE → Project Settings`:
   - Marcar `Bind project to SonarQube (Server, Cloud)`
   - **Connection:** `bancopichinchaec`
   - **Project key:** click `Search in list...` → buscar tu proyecto → OK.

5. **Share configuration.** Toast `Share This Connected Mode Configuration?` → **Share Configuration**.

6. **Verificar y commitear** `.sonarlint/connectedMode.json` igual que en VS Code.

---

## El archivo `.sonarlint/connectedMode.json`

Es el contrato versionable. Un nuevo dev del equipo solo tiene que:
1. Instalar la extensión / plugin.
2. Abrir el repo.
3. Aceptar la conexión que SonarLint le ofrece automáticamente al detectar `connectedMode.json`.

**NO commitear:**
- `~/.sonarlint/` (carpeta global del usuario, contiene tokens) → se queda fuera del repo siempre.
- Tokens en cualquier formato → SonarLint los guarda cifrados en el secret store del IDE.

**Sí commitear:**
- `.sonarlint/connectedMode.json` (NO contiene secretos, solo `sonarCloudOrganization` + `projectKey`).

---

## ¿Cómo obtener el `projectKey` sin pasar por la UI?

1. Abrir SonarCloud → buscar el proyecto.
2. URL del proyecto tiene la forma:
   `https://sonarcloud.io/project/overview?id=<UUID>`
3. El `<UUID>` es el `projectKey`.

También aparece en `Project Information → Project Key` dentro de SonarCloud.

---

## Troubleshooting rápido

| Síntoma | Causa probable | Fix |
|---|---|---|
| No aparecen issues en el IDE | Binding no completado o `connectedMode.json` ausente | Re-hacer pasos 5-6 |
| `Authentication failed` | Token expirado o revocado | Generar token nuevo desde SonarCloud → re-pegar en la conexión |
| Binding no se mantiene tras reinstalar el IDE | `connectedMode.json` no commiteado | Commitear y push |
| Reglas locales distintas a las de SonarCloud | Connected Mode no activo | Verificar que `bancopichinchaec` aparezca con ✓ verde en CONNECTED MODE |
| `Pop-up: Configure Trusted Domains` | VS Code bloqueó la URL `sonarcloud.io/sonarlint/auth` | Click `Configure Trusted Domains` → permitir |

---

## Integración con el flujo de migración

Cada proyecto migrado en este toolkit **DEBE** tener `.sonarlint/connectedMode.json` antes del primer PR. La checklist post-migración (`prompts/post-migracion/03-checklist.md`, BLOQUE 14) lo valida automáticamente.

**Template** disponible en `configuracion-claude-code/sonarlint/connectedMode.template.json`. Reemplazar `<PROJECT_KEY_FROM_SONARCLOUD>` por el `projectKey` real del proyecto en SonarCloud.

---

## Referencias

- PDF interno: `prompts/documentacion/CDSRL-Guía de configuración SonarQube for ide (SonarLint)-140426-180128.pdf`
- [SonarQube for IDE — VS Code installation](https://docs.sonarsource.com/sonarqube-for-ide/vs-code/getting-started/installation/)
- [SonarQube for IDE — IntelliJ installation](https://docs.sonarsource.com/sonarqube-for-ide/intellij/getting-started/installation/)
- [Connected Mode setup — VS Code](https://docs.sonarsource.com/sonarqube-for-ide/vs-code/team-features/connected-mode-setup/)
