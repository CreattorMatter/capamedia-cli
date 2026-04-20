---
name: migrar
description: Ejecuta la migracion completa de un servicio legacy a Java Spring Boot hexagonal OLA1 con loop de autocorreccion
allowed-tools: Read Glob Grep Bash Edit Write Agent
---

# /migrar

Ejecuta la migracion completa usando el ANALISIS_*.md previamente generado.

## Prerequisitos
- ANALISIS_<ServiceName>.md debe existir en el directorio actual o en docs/
- El servicio legacy debe estar accesible para referencia

## Pasos

1. **Leer el analisis** — Extraer: nombre, tribu, framework (webflux/mvc), operaciones, UMPs

1.5. **Rutear al prompt correcto segun el WSDL** (matriz oficial, sin excepciones):
   - Contar operaciones en el `<wsdl:portType>` (no el binding, que duplica)
   - Si **1 operacion** -> cargar `prompts/migracion/REST/02-REST-migrar-servicio.md` (REST + Spring WebFlux + @RestController)
   - Si **2+ operaciones** -> cargar `prompts/migracion/SOAP/02-SOAP-migrar-servicio.md` (SOAP + Spring MVC + @Endpoint, BancsClientHelper abstract + per-TX subclasses)
   - La presencia de BD NO cambia la decision (es ortogonal al conteo de operaciones). Si hay BD, el prompt elegido agrega HikariCP+JPA.
   - Documentar la decision con la cantidad de operaciones encontradas

2. **Bloque 1: Scaffolding**
   - Crear proyecto Gradle copiando patrones del proyecto referencia
   - Copiar WSDL/XSD, fix schemaLocation
   - GATE: verificar estructura

3. **Bloque 2: Domain**
   - Crear records, exceptions
   - GATE: grep domain/ por imports de Spring (debe ser vacio)

4. **Bloque 3: Application**
   - Crear abstract class ports + service impl
   - GATE: grep ports por "public interface" (debe ser 0), grep application/ por imports de infrastructure/ (debe ser vacio)

5. **Bloque 4: Infrastructure**
   - SOAP controller, DTOs, mappers, BANCS adapters (stubs si TX desconocida), config, error resolvers, application.yml
   - GATE: grep @Autowired (debe ser 0), verificar adapters extienden ports

6. **Bloque 5: Helm + Docker**
   - helm/dev.yml, test.yml, prod.yml con probes
   - GATE: grep probes en todos los Helm

7. **Bloque 6: Tests**
   - Unit tests JUnit 5 + Mockito + StepVerifier
   - GATE: intentar ./gradlew test (documentar si falla por credenciales)

8. **Loop de autocorreccion** en cada GATE:
   - Si falla: identificar → analizar → corregir → re-verificar
   - Max 3 intentos antes de escalar al usuario

9. **Generar MIGRATION_REPORT.md** con seccion GenAI

10. **Generar NO_VERIFICABLE_LOCAL.md** con lo que no se pudo probar

## Ejemplo de uso
```
/migrar
```
(ejecutar desde la raiz del proyecto destino, con ANALISIS_*.md presente)
