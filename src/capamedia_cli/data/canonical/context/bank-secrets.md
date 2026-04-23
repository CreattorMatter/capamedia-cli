---
name: bank-secrets
kind: context
priority: 1
summary: Catalogo de secretos Azure Key Vault para WAS con BD - mapping JNDI -> secret name
---

# Catalogo de secretos Azure Key Vault (Lift and Shift)

Este documento mapea los JNDI usados por los WAS legacy con BD a los secretos
preconfigurados en los Key Vaults (KV) de Azure del banco. Fuente:
`BPTPSRE-Secretos` (documentacion oficial Lift and Shift).

> **Los secretos mantienen el mismo nombre en todos los ambientes**
> (dev/test/prod). No hay que generar variantes por ambiente — el Key Vault
> que monta el pod difiere pero el nombre del secreto es el mismo.

## Aplicabilidad

- **SI aplica a**: servicios **WAS** migrados que tienen acceso a **base de datos**
  (detectado cuando `has_database=true` en el `LegacyAnalysis`, o cuando el
  legacy tiene `persistence.xml` / `ibm-web-bnd.xml` / referencias `@Resource`
  a JNDI, o cuando sus UMPs levantan JNDI).

- **NO aplica a**:
  - Servicios BUS (IIB) — no tienen BD directa, usan BANCS via TX
  - Servicios ORQ — solo orquestan, no acceden a BD
  - Servicios WAS sin BD (caso `wstecnicos0008` — UMPs con JAXB sobre XML, no JPA)

## Catalogo completo

| Base de datos | JNDI usado por el legacy | Secreto USER | Secreto PASSWORD |
|---|---|---|---|
| DTST | `jndi.sar.creditos` | `CCC-ORACLE-SAR-CREDITOS-USER` | `CCC-ORACLE-SAR-CREDITOS-PASSWORD` |
| TPOMN | `jndi.productos.productos` | `CCC-ORACLE-OMNI-PRODUCTOS-USER` | `CCC-ORACLE-OMNI-PRODUCTOS-PASSWORD` |
| TPOMN | `jndi.tecnicos.cataloga` | `CCC-ORACLE-OMNI-CATALOGA-USER` | `CCC-ORACLE-OMNI-CATALOGA-PASSWORD` |
| TPOMN | `jndi.clientes.conclient` | `CCC-ORACLE-OMNI-CLIENTE-USER` | `CCC-ORACLE-OMNI-CLIENTE-PASSWORD` |
| CREDITO_TARJETAS | `jndi.bddvia` | `CCC-SQLSERVER-CREDITO-TARJETAS-USER` | `CCC-SQLSERVER-CREDITO-TARJETAS-PASSWORD` |
| MOTOR_HOMOLOGACION | `jndi.clientes.homologacionCRM` | `CCC-SQLSERVER-MOTOR-HOMOLOGACION-USER` | `CCC-SQLSERVER-MOTOR-HOMOLOGACION-PASSWORD` |

## Detección del JNDI en un WAS legacy

El agente debe escanear los siguientes lugares (en orden):

1. **Archivo de discovery** del servicio legacy (`ibm-web-bnd.xml`,
   `web.xml`, o similar). El JNDI aparece en `<resource-ref>` / `<data-source>`.

2. **`persistence.xml`** del módulo aplicacion o dominio:
   ```xml
   <persistence-unit name="...">
     <jta-data-source>jndi.tecnicos.cataloga</jta-data-source>
   </persistence-unit>
   ```

3. **Código Java** con `@Resource` o lookup:
   ```java
   @Resource(name = "jndi.tecnicos.cataloga")
   private DataSource dataSource;
   // o
   DataSource ds = (DataSource) new InitialContext().lookup("jndi.tecnicos.cataloga");
   ```

4. **`*.properties`** del servicio o sus UMPs — a veces el JNDI está
   parametrizado:
   ```properties
   OMNI_JNDI_CATALOGA = jndi.tecnicos.cataloga
   ```

5. **UMPs clonadas junto al servicio**: si el servicio importa un UMP que
   accede a BD (ej. un UMP de persistencia), el JNDI vive en el UMP. El
   scanner debe cubrir también las UMPs clonadas en `umps/`.

## Generación de `application.yml` del servicio migrado

Una vez detectado el JNDI, el agente debe escribir el `application.yml` con
referencias a los secretos del Key Vault:

```yaml
spring:
  datasource:
    # Ejemplo para jndi.tecnicos.cataloga (TPOMN)
    url: ${CCC_ORACLE_OMNI_CATALOGA_URL}        # URL del Key Vault Variable Group
    username: ${CCC-ORACLE-OMNI-CATALOGA-USER}  # secreto literal del KV
    password: ${CCC-ORACLE-OMNI-CATALOGA-PASSWORD}
    driver-class-name: oracle.jdbc.OracleDriver
  jpa:
    database-platform: org.hibernate.dialect.OracleDialect
    hibernate:
      ddl-auto: none
```

**Importante**:
- Los **nombres de secretos del catalogo se usan TAL CUAL** (con guiones,
  mayusculas). No convertir a camelCase ni a snake_case.
- El **prefijo `${CCC-...}`** indica al agente que son secretos de KV, no
  variables CCC del ConfigMap (los ConfigMap usan `${CCC_...}` con
  underscore).

## Reporte del CLI

Cuando `capamedia clone <svc>` detecta un WAS con BD, genera
`.capamedia/secrets-report.yaml` con los secretos requeridos por KV:

```yaml
service: wsclientesXXXX
service_kind: was
has_database: true
secrets_required:
  - base_de_datos: TPOMN
    jndi: jndi.tecnicos.cataloga
    user_secret: CCC-ORACLE-OMNI-CATALOGA-USER
    password_secret: CCC-ORACLE-OMNI-CATALOGA-PASSWORD
    detected_from:
      - legacy/ws-<svc>-was/...-aplicacion/persistence.xml
jndi_references_unknown: []   # JNDI que no matchean el catalogo (requiere verificar)
```

El agente `/migrate` consume ese yaml para poblar el `application.yml` y el
`helm/*.yml` con las refs correctas a KV (sin inventar nombres de secretos).

## Regla para el agente migrador

1. **Buscar JNDI** en los 5 lugares listados arriba (WAS + UMPs).
2. **Para cada JNDI detectado**, mapear al secreto del catalogo.
3. **Si el JNDI no esta en el catalogo**, reportar en
   `jndi_references_unknown` y dejar placeholder `${CCC-?-USER}` /
   `${CCC-?-PASSWORD}` con comentario `# TODO: solicitar secreto al team SRE`.
4. **NUNCA inventar nombres de secretos** o "adivinarlos" por convencion.
   El catalogo es la fuente de verdad.
5. Aplica SOLO a WAS con BD. BUS/ORQ/WAS-sin-BD no generan entradas.
