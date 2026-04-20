---
name: pre-migracion
description: Detecta tipo de legacy (IIB / WAS / ORQ) y genera ANALISIS_*.md con cuantificacion y score de confianza
allowed-tools: Read Glob Grep Bash Agent
---

# /pre-migracion <ruta_al_servicio_legacy>

Ejecuta el analisis completo de un servicio legacy para preparar su migracion. Soporta tres tipos de fuente: **IIB**, **WAS** y **ORQ** (orquestadores).

## Pasos

1. **Localizar artefactos** en la ruta proporcionada ($ARGUMENTS):
   - Buscar *.esql, *.wsdl, *.xsd, *.msgflow, *.subflow, pom.xml (IIB)
   - Buscar *.java, web.xml, persistence.xml, ibm-web-bnd.xml, build.gradle (WAS)
   - Listar todo lo encontrado

2. **Detectar tipo de legacy** y elegir prompt:
   - Si el nombre contiene `ORQ*` o el msgflow contiene `IniciarOrquestacionSOAP` -> tipo **ORQ**, usar `prompts/pre-migracion/01-analisis-orq.md` (analisis liviano, no profundizar logica)
   - Si hay `*.esql` -> tipo **IIB**, usar `prompts/pre-migracion/01-analisis-servicio.md`
   - Si hay `*.java` + `web.xml` (sin `.esql`) -> tipo **WAS**, usar `prompts/pre-migracion/01-analisis-servicio.md` (cubre IIB y WAS)
   - Si ambiguo -> preguntar al usuario antes de continuar
   - Documentar la deteccion con evidencia (archivos clave que decidieron)

3. **Para WAS:** ejecutar Step E.2 del prompt (deteccion de BD: persistence.xml, EntityManager, JdbcTemplate, queries SQL). Output: flag `DB_USAGE: YES | NO`

4. **Lanzar agente analista-legacy** con el prompt elegido

5. **Generar `ANALISIS_<ServiceName>.md`** (o `ANALISIS_ORQ_<ServiceName>.md` para orquestadores) con:
   - Tipo de fuente detectado (IIB / WAS / ORQ)
   - Descripcion general del servicio
   - Endpoints expuestos (contrato SOAP completo)
   - Servicios downstream (UMPs) con mapeo a TX BANCS
   - **Si WAS:** tablas BD accedidas + flag DB_USAGE
   - Tabla de cuantificacion (operaciones, UMPs, errores, campos, configs)
   - Logica de negocio paso a paso (en ORQ: solo delegaciones, sin profundizar)
   - Mapa de propagacion de errores
   - Clasificacion: BUS (WebFlux/REST) vs WAS (MVC con HikariCP+JPA si DB)
   - Score de confianza
   - Incertidumbres y supuestos

6. **Mostrar resumen** al usuario con:
   - Tipo de fuente legacy (IIB / WAS / ORQ)
   - Nombre del servicio
   - Modo recomendado (REST / SOAP) — basado en N° operaciones + DB_USAGE
   - Cantidad de UMPs
   - DB_USAGE (si aplica)
   - Score de confianza
   - Recomendacion GO/NO-GO

## Ejemplo de uso
```
/pre-migracion C:\Dev\Banco Pichincha\CapaMedia\_extracted\sqb-msa-wsclientes0007
/pre-migracion C:\Dev\Banco Pichincha\CapaMedia\_extracted\sqb-was-cuentas0039
/pre-migracion C:\Dev\Banco Pichincha\CapaMedia\_extracted\sqb-msa-orqtransferencias0003
```
