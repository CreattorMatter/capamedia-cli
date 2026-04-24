# Guía de instalación — CapaMedia CLI

Guía completa para poner a punto el entorno en **Windows 10/11** y **macOS 13+**,
con troubleshooting de todo lo que nos mordió durante el desarrollo del CLI.

Si algo te falla, buscá en la sección [Troubleshooting](#troubleshooting) al final.

---

## Contenido

1. [Qué necesitás instalar](#qué-necesitás-instalar)
2. [Windows — paso a paso](#windows--paso-a-paso)
3. [macOS — paso a paso](#macos--paso-a-paso)
4. [Instalar el CLI](#instalar-el-cli)
5. [Verificar con `capamedia status`](#verificar-con-capamedia-status)
6. [Configurar credenciales Azure DevOps](#configurar-credenciales-azure-devops)
7. [Troubleshooting](#troubleshooting)

---

## Qué necesitás instalar

| Herramienta | Versión mínima | Uso |
|---|---|---|
| **Python** | 3.11+ (3.12/3.13 recomendado) | Ejecutar el CLI |
| **uv** | última | Gestor de paquetes Python (reemplaza pip) |
| **Git** | 2.40+ | Clonar repos Azure DevOps |
| **Git Credential Manager (GCM)** | última | Auth OAuth con Azure DevOps |
| **Java JDK** | 21 | Build del servicio migrado |
| **Gradle** | 8.5+ | Wrapper incluido, pero conviene tenerlo instalado |
| **Node.js** | 20 LTS | Para MCP Fabrics (`npx`) |
| **VS Code** + SonarLint | última | SonarCloud connected mode |
| **Claude Code** o **Codex** | última | Harness AI (al menos uno) |

Detalles más abajo.

---

## Windows — paso a paso

### 0. Pre-requisitos

- Windows 10 21H2 / Windows 11
- Terminal como **Administrador** para las instalaciones de sistema (abrir `Terminal` con click derecho → *Ejecutar como administrador*)
- Si estás en red corporativa, confirmar con IT que no hay **proxy** bloqueando `github.com`, `pkgs.dev.azure.com`, `registry.npmjs.org` y `dev.azure.com`.

### 1. Instalar `winget` (si no lo tenés)

En Windows 11 ya viene. En Windows 10 puede faltar. Check:

```powershell
winget --version
```

Si tira "winget no se reconoce como comando", instalá **App Installer** de Microsoft:

```powershell
# Como Admin
$url = "https://aka.ms/getwinget"
$msi = "$env:TEMP\Microsoft.DesktopAppInstaller.msixbundle"
Invoke-WebRequest -Uri $url -OutFile $msi
Add-AppxPackage -Path $msi
# Cerrar y reabrir terminal
winget --version
```

> El CLI también tiene `capamedia install` que hace esto automáticamente si detecta que winget falta. Ver sección [Instalar el CLI](#instalar-el-cli).

### 2. Python 3.12

**Recomendado: NO usar 3.14** (tiene bugs conocidos con PATH y encoding en Windows — el CLI ya los mitiga pero mejor evitar).

```powershell
# Como Admin
winget install -e --id Python.Python.3.12
# Reabrir terminal para que PATH tome efecto
py --version   # debe mostrar 3.12.x
```

**Agregar Scripts al PATH** (muchas veces el instalador lo saltea):

```powershell
# Verificar si python está accesible
python --version

# Si tira "no se reconoce", agregar manualmente al PATH de usuario:
$pyScripts = "$env:USERPROFILE\AppData\Roaming\Python\Python312\Scripts"
$pyRoot    = "$env:USERPROFILE\AppData\Local\Programs\Python\Python312"
[Environment]::SetEnvironmentVariable(
    "Path",
    ([Environment]::GetEnvironmentVariable("Path", "User") + ";$pyRoot;$pyScripts"),
    "User"
)
# Cerrar y reabrir terminal
```

### 3. `uv` (gestor Python moderno)

```powershell
# Instalador oficial (no necesita admin)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Reabrir terminal
uv --version
```

### 4. Git + Git Credential Manager

```powershell
# Como Admin
winget install -e --id Git.Git
```

GCM viene incluido en Git para Windows. Verificalo:

```powershell
git credential-manager --version
```

### 5. Java JDK 21

```powershell
# Como Admin - Temurin es el distro recomendado
winget install -e --id EclipseAdoptium.Temurin.21.JDK
# Reabrir terminal
java --version   # debe decir "openjdk 21.x.x"
```

Si Java 21 no se ve, agregar `JAVA_HOME` y el `bin` al PATH:

```powershell
$javaHome = "C:\Program Files\Eclipse Adoptium\jdk-21.0.5.11-hotspot"   # ajustar version
[Environment]::SetEnvironmentVariable("JAVA_HOME", $javaHome, "User")
$path = [Environment]::GetEnvironmentVariable("Path", "User")
[Environment]::SetEnvironmentVariable("Path", "$path;$javaHome\bin", "User")
```

### 6. Gradle

```powershell
# Como Admin
winget install -e --id Gradle.Gradle
gradle --version   # debe decir "Gradle 8.x"
```

Si winget no trae Gradle o falla, hay **fallback directo** integrado en el CLI:

```powershell
capamedia install gradle   # descarga, extrae a $env:USERPROFILE\gradle y agrega al PATH
```

### 7. Node.js 20 LTS

```powershell
# Como Admin
winget install -e --id OpenJS.NodeJS.LTS
node --version   # debe decir v20.x.x
npx --version
```

### 8. VS Code + SonarLint

```powershell
# Como Admin
winget install -e --id Microsoft.VisualStudioCode
```

Fallback directo si winget falla:

```powershell
capamedia install vscode   # descarga e instala silent
```

Después abrí VS Code y desde Extensions instalá **SonarQube for IDE** (ex SonarLint).

### 9. Claude Code o Codex

Instalá **al menos uno** de los dos. Son alternativos entre sí. Para fabrica batch, Codex es el default recomendado.

**Claude Code**:
```powershell
npm install -g @anthropic-ai/claude-code
claude --version
```

**Codex**:
```powershell
npm install -g @openai/codex
codex --version
codex login
```

Recomendado para migraciones pesadas con Codex CLI:

```toml
model = "gpt-5.5"
model_reasoning_effort = "xhigh"
```

### 10. MCP Fabrics (dep del flujo)

El MCP Server `@pichincha/fabrics-project` se usa para scaffoldear el proyecto target. No requiere instalación global — el CLI lo invoca via `npx`. Solo necesitás tener **Node 20+**.

---

## macOS — paso a paso

### 0. Pre-requisitos

- macOS 13 Ventura o superior
- **Homebrew** instalado:
  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  brew --version
  ```

### 1. Python + uv

```bash
brew install python@3.12 uv
python3.12 --version
uv --version
```

### 2. Git + Git Credential Manager

```bash
brew install git
brew install --cask git-credential-manager
git credential-manager configure
```

### 3. Java JDK 21

```bash
brew install --cask temurin@21
# Agregar a shell init (~/.zshrc):
echo 'export JAVA_HOME=$(/usr/libexec/java_home -v 21)' >> ~/.zshrc
echo 'export PATH="$JAVA_HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
java --version
```

### 4. Gradle + Node.js 20

```bash
brew install gradle node@20
gradle --version
node --version
```

### 5. VS Code + SonarLint

```bash
brew install --cask visual-studio-code
```

Abrir VS Code, instalar **SonarQube for IDE** desde el marketplace.

### 6. Claude Code o Codex

```bash
# Claude Code
npm install -g @anthropic-ai/claude-code

# Codex (alternativa)
npm install -g @openai/codex
codex login
```

---

## Instalar el CLI

### Opción A — desde GitHub (recomendado para equipo)

```powershell
# Windows / PowerShell
uv tool install --from "git+https://github.com/CreattorMatter/capamedia-cli.git" capamedia-cli

# macOS / bash
uv tool install --from "git+https://github.com/CreattorMatter/capamedia-cli.git" capamedia-cli
```

### Opción B — desde un clon local (desarrollo del propio CLI)

```powershell
# Windows (ajustar path)
git clone https://github.com/CreattorMatter/capamedia-cli.git "C:\Dev\Banco Pichincha\capamedia-cli"
uv tool install capamedia-cli --from "C:\Dev\Banco Pichincha\capamedia-cli"

# macOS
git clone https://github.com/CreattorMatter/capamedia-cli.git ~/dev/capamedia-cli
uv tool install capamedia-cli --from ~/dev/capamedia-cli
```

### Verificar

```bash
capamedia version
# debe mostrar la version (ej 0.19.0)
```

### Actualizar

```bash
uv tool upgrade capamedia-cli
# o desde fuente local:
uv tool upgrade capamedia-cli --from "<path al clon>"
```

### Desinstalar

```bash
capamedia uninstall      # remueve el CLI y opcionalmente su cache
# o directo con uv:
uv tool uninstall capamedia-cli
```

---

## Verificar con `capamedia status`

Corré esto después de instalar todo:

```powershell
capamedia status
```

Esperado: todas las filas en `OK`. Las que queden en `FAIL` indican qué falta.

Ejemplo de output sano:

```
┌─ Estado del entorno ─────────────────────────────┐
│ Python 3.11+            OK   3.12.7              │
│ Git                     OK   2.48.1              │
│ Git Credential Manager  OK   2.5.1               │
│ Java 21                 OK   21.0.5              │
│ Gradle                  OK   8.11.1              │
│ Node.js 20+             OK   20.18.0             │
│ Claude Code / Codex     OK   claude 1.2.0        │
│ VS Code + SonarLint     OK   1.97.0 + sonarlint  │
│ Azure DevOps PAT        OK   GCM resuelve auth   │
│ MCP Fabrics             OK   reachable via npx   │
└──────────────────────────────────────────────────┘
```

Si algo está en `FAIL`, corré `capamedia install --fix` para que intente resolverlo automáticamente (cascade winget → scoop → choco → direct download).

---

## Configurar credenciales Azure DevOps

El CLI clona repos privados del banco en Azure DevOps. Necesitás auth:

### Opción A — GCM (recomendado, interactivo)

Primera vez:
```powershell
git clone https://dev.azure.com/BancoPichinchaEC/OmniCanalidad/_git/sqb-msa-wsclientes0006
```

Se abre un browser, logueás con tu cuenta corporativa, GCM guarda el token.

### Opción B — PAT explícito (automático, CI-friendly)

1. Azure DevOps → User Settings → **Personal Access Tokens** → *New Token*
2. Scopes: `Code (Read & Write)`, `Packaging (Read)`, `Build (Read)`
3. Expiración: 90 días
4. Copiar el token.
5. Guardarlo:
   ```powershell
   # Windows
   [Environment]::SetEnvironmentVariable("CAPAMEDIA_AZDO_PAT", "<tu-token>", "User")
   # macOS/Linux
   echo 'export CAPAMEDIA_AZDO_PAT="<tu-token>"' >> ~/.zshrc
   ```
6. Reabrir terminal.

El CLI lo detecta automáticamente vía `capamedia.core.auth.resolve_azure_devops_pat`.

---

## Troubleshooting

### ❌ `winget : No se reconoce como comando`

Windows 10 sin App Installer. Ver [paso 1 de Windows](#1-instalar-winget-si-no-lo-tenés) arriba — o correr `capamedia install --bootstrap` que lo resuelve solo.

### ❌ `python : no se reconoce` pero Python está instalado

Python 3.14 (y a veces 3.12) no agregan `Scripts/` al PATH. Solución:

```powershell
# Python 3.12
$root = "$env:LOCALAPPDATA\Programs\Python\Python312"
# Python 3.14
# $root = "$env:LOCALAPPDATA\Python\pythoncore-3.14-64"

$p = [Environment]::GetEnvironmentVariable("Path", "User")
[Environment]::SetEnvironmentVariable("Path", "$p;$root;$root\Scripts", "User")
# Reabrir terminal
```

### ❌ `uv tool install --from . capamedia-cli` da "missing PACKAGE argument"

La sintaxis correcta es `uv tool install capamedia-cli --from .` (package **antes** que flag). Alternativas:

```powershell
uv tool install capamedia-cli --from "C:\Dev\Banco Pichincha\capamedia-cli"
# o instalar pip-editable para desarrollo:
pip install -e "C:\Dev\Banco Pichincha\capamedia-cli"
```

### ❌ `pip install -e` deja el binario fuera del PATH (Python 3.14)

Python 3.14 en Windows pone el binario en `$env:USERPROFILE\AppData\Local\Python\pythoncore-3.14-64\Scripts`. Agregalo al PATH (ver anterior).

### ❌ `Codex CLI: falta` pero tengo Claude Code

Corregido en v0.15.2: el CLI acepta Claude Code **como alternativa** a Codex. Si seguís viendo el error, actualizá:

```bash
uv tool upgrade capamedia-cli
capamedia version   # debe ser >= 0.15.2
capamedia status
```

### ❌ `capamedia review` Fase 4: `UnicodeDecodeError`

Corregido en v0.18.1. En Windows con Python 3.14, el subprocess decodifica con cp1252 y explota con emojis UTF-8 del validador oficial.

```bash
uv tool upgrade capamedia-cli   # >= 0.18.1
```

### ❌ `init` crea subcarpeta anidada `wstecnicos0008\wstecnicos0008\`

Corregido en v0.17.3. Si corriste init desde dentro del workspace sin `--here`, el CLI ahora lo detecta automáticamente. Actualizá:

```bash
uv tool upgrade capamedia-cli   # >= 0.17.3
```

Para limpiar el estado ya creado:

```powershell
cd C:\Dev\BancoPichincha\wstecnicos0008
Move-Item .\wstecnicos0008\.claude    . -Force
Move-Item .\wstecnicos0008\.sonarlint . -Force
Move-Item .\wstecnicos0008\.mcp.json  . -Force
Move-Item .\wstecnicos0008\CLAUDE.md  . -Force
Move-Item .\wstecnicos0008\.gitignore . -Force -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\wstecnicos0008
```

### ❌ `git clone` pide password repetidamente

GCM no está configurado o el token expiró:

```bash
git credential-manager configure
git credential-manager delete https://dev.azure.com
# Próxima clone abre el browser para reautenticar
```

### ❌ `./gradlew build` falla con `Could not resolve com.pichincha.bnc:lib-bnc-api-client:1.1.0`

Falta el feed de Azure Artifacts o las credenciales. Configurar en `~/.gradle/init.d/credentials.gradle`:

```groovy
allprojects {
    repositories {
        maven {
            url "https://pkgs.dev.azure.com/BancoPichinchaEC/_packaging/OmniCanalidad/maven/v1"
            credentials {
                username = "anyuser"   // literal, Azure ignora
                password = System.getenv("AZURE_ARTIFACTS_TOKEN")
            }
        }
    }
}
```

Exportar `AZURE_ARTIFACTS_TOKEN` con un PAT que tenga scope `Packaging (Read)`.

### ❌ No puedo borrar la carpeta `destino`: "Se requieren permisos de Administrador"

Pasa con carpetas creadas por pnpm/fabrics que dejan ACLs raras. Opción más directa:

```powershell
# PowerShell como Admin
takeown /F .\destino /R /D Y
icacls .\destino /grant "$env:USERNAME`:F" /T /C
Remove-Item -Recurse -Force .\destino
```

### ❌ `./gradlew build` dentro del proyecto generado falla con errores de CXF

Es normal la primera vez: CXF genera clases desde el WSDL en `build/generated/sources/wsdl/`. Correr primero:

```powershell
.\gradlew generateFromWsdl
.\gradlew build
```

### ❌ MCP Fabrics tira timeout o "ECONNREFUSED" al generar

Verificar con `capamedia status` que:
- Node 20+ instalado
- Tu PAT de Azure Artifacts esté exportado (para que `npm install` descargue `@pichincha/fabrics-project`)
- Acceso a `registry.npmjs.org` (sin proxy bloqueando)

Si el MCP no arranca, podés correr fabrics directamente:

```powershell
capamedia fabrics generate
```

### ❌ `capamedia clone <svc>` dice `0 UMPs detectados` pero sabés que hay

Corregido en v0.17.1. El detector WAS ahora soporta:
- WSDL sin prefijo `wsdl:` (solo `<operation>`)
- UMPs referenciadas en `pom.xml` (artifactId) y en `import` Java
- UMPs en `tpl-integration-services-was/ump-<ump>-was` (no solo en `tpl-bus-omnicanal`)

Actualizá al CLI >= 0.17.2.

### ❌ MIGRATION_REPORT.md reporta "blocker: OMNI_COD_SERVICIO_OK falta"

Corregido en v0.18.0 embebiendo el catálogo de `generalservices.properties` + `catalogoaplicaciones.properties`. El agente ahora usa los valores literales (`"0"`, `"9999"`, `"00633"`, etc.) en vez de marcar env vars faltantes.

Actualizá al CLI >= 0.18.0 y re-corré `capamedia init <svc> --force` para regenerar `CLAUDE.md`.

### ❌ `ai migrate` no sabe que `.properties` del UMP pedirle al banco

Corregido en v0.19.0. El `capamedia clone <svc>` ahora genera `.capamedia/properties-report.yaml` con la lista de `.properties` especificos que estan `PENDING_FROM_BANK`. Abrilo antes de lanzar `capamedia ai migrate` para saber que tenes que pedir.

---

## Checklist final pre-migración

Antes de lanzar tu primer `capamedia ai migrate`, confirma:

- [ ] `capamedia status` todas las filas en OK
- [ ] `capamedia version` >= 0.19.0
- [ ] `git clone` desde Azure DevOps funciona sin pedir password
- [ ] Abrís VS Code y SonarLint carga sin errores
- [ ] Podés correr `./gradlew --version` desde cualquier carpeta
- [ ] Tu harness AI (Claude Code o Codex) arranca con `claude --version` o `codex --version`
- [ ] Si vas a usar Codex, `codex login status` responde OK y `~/.codex/config.toml` usa `model = "gpt-5.5"` con `model_reasoning_effort = "xhigh"`
- [ ] Tenés un PAT de Azure Artifacts exportado como `AZURE_ARTIFACTS_TOKEN` (para el build del servicio generado)
- [ ] Revisaste `.capamedia/properties-report.yaml` del workspace y ya le pediste los `PENDING_FROM_BANK` al owner (si los hay)

Si todo OK:

```powershell
capamedia ai migrate --engine codex
capamedia ai doublecheck --engine codex
capamedia review
```

Usa `--engine claude` o `--engine auto` si ese es tu engine disponible.
