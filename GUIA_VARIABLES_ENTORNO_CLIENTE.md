# Guía de Variables de Entorno — Bot de Reintegros AssistCard

Listado de las 14 variables que la aplicación necesita y dónde obtener cada valor.

---

## 1. `FOUNDRY_ENDPOINT`

1. Abrir [https://ai.azure.com/](https://ai.azure.com/) e iniciar sesión.
2. Abrir el proyecto de Azure AI Foundry.
3. Esquina superior derecha → **Ver código** (View code) o **Configuración del proyecto** → copiar la **Project endpoint URL**.
4. Formato: `https://<recurso>.services.ai.azure.com/api/projects/<proyecto>`.

---

## 2. `FOUNDRY_MODEL_DEPLOYMENT`

1. Dentro del proyecto Foundry → panel izquierdo → **Modelos + endpoints** → **Implementaciones** (Deployments).
2. Copiar el **nombre exacto** del deployment del modelo (ej. `gpt-4o`).

---

## 3. `SEARCH_ENDPOINT`

1. Abrir [https://portal.azure.com/](https://portal.azure.com/) → entrar al recurso **Azure AI Search**.
2. **Overview** → copiar el campo **URL**.
3. Formato: `https://<nombre>.search.windows.net`.

---

## 4. `SEARCH_KNOWLEDGE_BASE_NAME`

1. Recurso **Azure AI Search** → panel izquierdo → **Knowledge bases**.
2. Copiar el **nombre exacto** de la knowledge base usada por el bot.

---

## 5. `SEARCH_INDEX_NAME`

1. Recurso **Azure AI Search** → panel izquierdo → **Indexes**.
2. Copiar el **nombre exacto** del índice usado por el bot.

---

## 6. `SEARCH_API_KEY` *(opcional)*

1. Recurso **Azure AI Search** → **Settings** → **Keys**.
2. Copiar la **Primary admin key**.

> Dejar vacía si se autentica con Entra ID (variables 7, 8 y 9).

---

## 7. `AZURE_TENANT_ID`

1. Portal Azure → **Microsoft Entra ID** → **App registrations** → abrir la App Registration del bot.
2. **Overview** → copiar **Directory (tenant) ID**.

---

## 8. `AZURE_CLIENT_ID`

1. Misma App Registration → **Overview** → copiar **Application (client) ID**.

---

## 9. `AZURE_CLIENT_SECRET`

1. Misma App Registration → **Certificates & secrets** → pestaña **Client secrets**.
2. **+ New client secret** → completar descripción y vencimiento → **Add**.
3. Copiar el valor de la columna **Value** **inmediatamente** (solo se muestra una vez).

---

## 10. `AZURE_TRANSLATOR_ENDPOINT`

1. Portal Azure → recurso **Translator** → **Keys and Endpoint**.
2. Usar el endpoint global: `https://api.cognitive.microsofttranslator.com/`.

---

## 11. `AZURE_TRANSLATOR_KEY`

1. Recurso **Translator** → **Keys and Endpoint** → copiar **KEY 1**.

---

## 12. `AZURE_TRANSLATOR_REGION`

1. Recurso **Translator** → **Keys and Endpoint** → copiar el campo **Location/Region**.
2. Formato: en minúsculas, sin espacios (ej. `eastus2`, `brazilsouth`).

---

## 13. `Reintegros__BaseUrl`

Solicitar al equipo de integraciones de AssistCard. Valores típicos:

| Entorno | URL |
|---------|-----|
| QA | `https://samumiddlewareqa.assistcard.com/` |
| Producción | `https://samumiddleware.assistcard.com/` |

> Debe terminar con barra `/`.

---

## 14. `Reintegros__ApiKey`

Solicitar al equipo de integraciones de AssistCard la **API Key** del entorno correspondiente (QA o Producción).
