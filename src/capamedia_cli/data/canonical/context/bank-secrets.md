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
| DTST | `jndi.clientes.riesgo.01` | `CCC-ORACLE-SIGLO-RIESGO-USER` | `CCC-ORACLE-SIGLO-RIESGO-PASSWORD` |
| M012BAND | `jndi.clientes.fnsonlf.01` | `CCC-ORACLE-M012BAND-USER` | `CCC-ORACLE-M012BAND-PASSWORD` |
| REPOSITORIO_SITAR | `jndi.clientes.repositorio_sitar.01` | `CCC-SQLSERVER-SITAR-USER` | `CCC-SQLSERVER-SITAR-PASSWORD` |
| TOTPAUT | `GEOLOCALIZACION_JNDI` | `CCC-ORACLE-GEOLOCALIZACION-TOTPAUT-USER` | `CCC-ORACLE-GEOLOCALIZACION-TOTPAUT-PASSWORD` |
| TPOMN | `jndi.seguridad.autentica` | `CCC-ORACLE-SEGURIDAD-AUTENTICA-TPOMN-USER` | `CCC-ORACLE-SEGURIDAD-AUTENTICA-TPOMN-PASSWORD` |
| TOTPAUT | `jdbc/notifica` | `CCC-ORACLE-NOTIFICA-TOTPAUT-USER` | `CCC-ORACLE-NOTIFICA-TOTPAUT-PASS` |
| TPOMN | `jdbc/omni` | `CCC-ORACLE-OMNI-TPOMN-USER` | `CCC-ORACLE-OMNI-TPOMN-PASS` |
| TOTPNOT | `jdbc/notificador2` | `CCC-ORACLE-NOTIFICADOR2-TOTPNOT-USER` | `CCC-ORACLE-NOTIFICADOR2-TOTPNOT-PASS` |
| TOTPNOT | `jdbc/notificador` | `CCC-ORACLE-NOTIFICADOR-TOTPNOT-USER` | `CCC-ORACLE-NOTIFICADOR-TOTPNOT-PASS` |
| TPOMN | `jndi.productos.cataloga` | `CCC-ORACLE-PRODUCTOS-CATALOGA-TPOMN-USER` | `CCC-ORACLE-PRODUCTOS-CATALOGA-TPOMN-PASS` |
| TOTPAUT | `jndi.notifier.notificacion` | `CCC-ORACLE-NOTIFIER-NOTIFICACION-TOTPAUT-USER` | `CCC-ORACLE-NOTIFIER-NOTIFICACION-TOTPAUT-PASS` |
| TPOMNLOG | `jndi.tecnicos.transacc` | `CCC-ORACLE-TECNICOS-TRANSACC-TPOMNLOG-USER` | `CCC-ORACLE-TECNICOS-TRANSACC-TPOMNLOG-PASS` |
| DTST | `jndi.cardholder.tarjetaxperta` | `CCC-ORACLE-CARDHOLDER-TARJETAXPERTA-DTST-USER` | `CCC-ORACLE-CARDHOLDER-TARJETAXPERTA-DTST-PASS` |
| DTST | `jndi.siglo.seguridad` | `CCC-ORACLE-SIGLO-SEGURIDAD-DTST-USER` | `CCC-ORACLE-SIGLO-SEGURIDAD-DTST-PASS` |
| TPOMNLOG | `jndi.tecnicos.logs002` | `CCC-ORACLE-TECNICOS-LOGS002-TPOMNLOG-USER` | `CCC-ORACLE-TECNICOS-LOGS002-TPOMNLOG-PASS` |
| TPOMN | `jndi.productos.cheqscanCamara` | `CCC-ORACLE-PRODUCTOS-CHEQSCANCAMARA-TPOMN-USER` | `CCC-ORACLE-PRODUCTOS-CHEQSCANCAMARA-TPOMN-PASS` |
| TOTPNOT | `jndi.clientes.cobrossms` | `CCC-ORACLE-CLIENTES-COBROSSMS-TOTPNOT-USER` | `CCC-ORACLE-CLIENTES-COBROSSMS-TOTPNOT-PASS` |
| M012BAND | `jndi.clientes.fnsonlf.01.bac` | `CCC-ORACLE-CLIENTES-FNSONLF-01-BAC-M012BAND-USER` | `CCC-ORACLE-CLIENTES-FNSONLF-01-BAC-M012BAND-PASS` |
| M012BAND | `jndi.bancs.clientes.bac` | `CCC-ORACLE-BANCS-CLIENTES-BAC-M012BAND-USER` | `CCC-ORACLE-BANCS-CLIENTES-BAC-M012BAND-PASS` |
| BPBPMD | `jndi.clientes.bpschema.01` | `CCC-ORACLE-CLIENTES-BPSCHEMA-01-BPBPMD-USER` | `CCC-ORACLE-CLIENTES-BPSCHEMA-01-BPBPMD-PASS` |
| DTST | `jndi.productos.riesgo` | `CCC-ORACLE-PRODUCTOS-RIESGO-DTST-USER` | `CCC-ORACLE-PRODUCTOS-RIESGO-DTST-PASS` |
| DTST | `OMNI_ORACLE_14_SIGLO_JNDI` | `CCC-ORACLE-OMNI-14-SIGLO-DTST-USER` | `CCC-ORACLE-OMNI-14-SIGLO-DTST-PASS` |
| TOTPNOT | `jdbc/notifier` | `CCC-ORACLE-NOTIFIER-TOTPNOT-USER` | `CCC-ORACLE-NOTIFIER-TOTPNOT-PASS` |
| DTST | `jdbc/cardHolder` | `CCC-ORACLE-CARDHOLDER-DTST-USER` | `CCC-ORACLE-CARDHOLDER-DTST-PASS` |
| TPOMN | `jndi.tecnicos` | `CCC-ORACLEXA-TECNICOS-TPOMN-USER` | `CCC-ORACLEXA-TECNICOS-TPOMN-PASS` |
| TPOMNLOG | `jndi.xa.tecnicos.transespera` | `CCC-ORACLEXA-TECNICOS-TRANSESPERA-TPOMNLOG-USER` | `CCC-ORACLEXA-TECNICOS-TRANSESPERA-TPOMNLOG-PASS` |
| TPOMN | `jndi.administracion` | `CCC-ORACLEXA-ADMINISTRACION-TPOMN-USER` | `CCC-ORACLEXA-ADMINISTRACION-TPOMN-PASS` |
| M012BAND | `jndi.catalogo.bancs.bac` | `CCC-ORACLEXA-CATALOGO-BANCS-BAC-M012BAND-USER` | `CCC-ORACLEXA-CATALOGO-BANCS-BAC-M012BAND-PASS` |
| DTST | `jndi.catalogo.siglo` | `CCC-ORACLEXA-CATALOGO-SIGLO-DTST-USER` | `CCC-ORACLEXA-CATALOGO-SIGLO-DTST-PASS` |
| TPOMN | `jndi.administracion.conadmin` | `CCC-ORACLEXA-ADMINISTRACION-CONADMIN-TPOMN-USER` | `CCC-ORACLEXA-ADMINISTRACION-CONADMIN-TPOMN-PASS` |
| TPOMN | `jndi.xa.seguridad.autentica` | `CCC-ORACLEXA-SEGURIDAD-AUTENTICA-TPOMN-USER` | `CCC-ORACLEXA-SEGURIDAD-AUTENTICA-TPOMN-PASS` |
| TPOMN | `jndi.interdin` | `CCC-ORACLEXA-INTERDIN-TPOMN-USER` | `CCC-ORACLEXA-INTERDIN-TPOMN-PASS` |
| M012BAND | `jndi.bancs.clientes` | `CCC-ORACLE-BANCS-CLIENTES-M012BAND-USER` | `CCC-ORACLE-BANCS-CLIENTES-M012BAND-PASS` |
| M014BANR_TAF | `jndi.bancs.clientes.reference` | `CCC-ORACLE-BANCS-CLIENTES-REFERENCE-M014BANR-TAF-USER` | `CCC-ORACLE-BANCS-CLIENTES-REFERENCE-M014BANR-TAF-PASS` |
| M012BAND | `jndi.catalogo.bancs` | `CCC-ORACLEXA-CATALOGO-BANCS-M012BAND-USER` | `CCC-ORACLEXA-CATALOGO-BANCS-M012BAND-PASS` |
| MOTOR_HOMOLOGACION | `jndi.homologacion.usuario` | `CCC-SQLSERVER-HOMOLOGACION-USUARIO-MOTOR-HOMOLOGACION-USER` | `CCC-SQLSERVER-HOMOLOGACION-USUARIO-MOTOR-HOMOLOGACION-PASS` |
| internexo | `OMNI_SQLSERVER_INTERNEXO_JNDI` | `CCC-SQLSERVER-OMNI-INTERNEXO-USER` | `CCC-SQLSERVER-OMNI-INTERNEXO-PASS` |
| Asesores | `asesores` | `CCC-SQLSERVER-ASESORES-USER` | `CCC-SQLSERVER-ASESORES-PASS` |
| BDD_PDMP | `jndi.productos.pdmp` | `CCC-SQLSERVER-PRODUCTOS-BDD-PDMP-USER` | `CCC-SQLSERVER-PRODUCTOS-BDD-PDMP-PASS` |
| SENTINEL_REPLICA | `jndi.tecnicos.sentinel_replica.01` | `CCC-SQLSERVER-TECNICOS-SENTINEL-REPLICA-01-USER` | `CCC-SQLSERVER-TECNICOS-SENTINEL-REPLICA-01-PASS` |
| BDD_INTERCAMBIO_DATA_BPM_BIZAGI | `jndi.productos.datint` | `CCC-SQLSERVER-PRODUCTOS-INTERCAMBIO-BPM-BIZAGI-USER` | `CCC-SQLSERVER-PRODUCTOS-INTERCAMBIO-BPM-BIZAGI-PASS` |
| REPOSITORIO_SITAR | `jndi.sitar.tarjetacredito` | `CCC-SQLSERVER-SITAR-TARJETACREDITO-USER` | `CCC-SQLSERVER-SITAR-TARJETACREDITO-PASS` |
| internexo | `jndi.internexo.cliente` | `CCC-SQLSERVER-INTERNEXO-CLIENTE-USER` | `CCC-SQLSERVER-INTERNEXO-CLIENTE-PASS` |
| ClientesPreaprobados | `AutogestionWeb/jdni` | `CCC-SQLSERVER-AUTOGESTIONWEB-CLIENTES-PREAPROBADOS-USER` | `CCC-SQLSERVER-AUTOGESTIONWEB-CLIENTES-PREAPROBADOS-PASS` |
| AutoGestion | `Autogestion/jdni` | `CCC-SQLSERVER-AUTOGESTION-USER` | `CCC-SQLSERVER-AUTOGESTION-PASS` |
| MOVILIDADMICRO | `jndi.microfinanzas` | `CCC-SQLSERVER-MICROFINANZAS-MOVILIDADMICRO-USER` | `CCC-SQLSERVER-MICROFINANZAS-MOVILIDADMICRO-PASS` |
| MDO_OFERTAS | `jndi.productos.mdo` | `CCC-SQLSERVER-PRODUCTOS-MDO-OFERTAS-USER` | `CCC-SQLSERVER-PRODUCTOS-MDO-OFERTAS-PASS` |
| MDO_PROCESOS | `jndi.productos.mdoprocesos` | `CCC-SQLSERVER-PRODUCTOS-MDO-PROCESOS-USER` | `CCC-SQLSERVER-PRODUCTOS-MDO-PROCESOS-PASS` |
| AutoGestion | `jndi.productos.autogestion` | `CCC-SQLSERVER-PRODUCTOS-AUTOGESTION-USER` | `CCC-SQLSERVER-PRODUCTOS-AUTOGESTION-PASS` |
| M012BAND | `jndi.tecnicos.portal.bac` | `CCC-ORACLE-TECNICOS-PORTAL-BAC-M012BAND-USER` | `CCC-ORACLE-TECNICOS-PORTAL-BAC-M012BAND-PASS` |
| DTST | `jndi.clientes.cardholder` | `CCC-ORACLE-CLIENTES-CARDHOLDER-DTST-USER` | `CCC-ORACLE-CLIENTES-CARDHOLDER-DTST-PASS` |
| TOTPNOT | `jndi.tecnicos.notificadormsg` | `CCC-ORACLE-TECNICOS-NOTIFICADORMSG-TOTPNOT-USER` | `CCC-ORACLE-TECNICOS-NOTIFICADORMSG-TOTPNOT-PASS` |
| ASYNCRONO | `jndi.bddvia.campanias` | `CCC-SQLSERVER--VIA-CAMPANIAS-ASYNCRONO-USER` | `CCC-SQLSERVER--VIA-CAMPANIAS-ASYNCRONO-PASS` |
| CLEANSING | `jndi.cleansing.cliente` | `CCC-SQLSERVER-CLEANSING-CLIENTE-USER` | `CCC-SQLSERVER-CLEANSING-CLIENTE-PASS` |
| SWMT950 | `jndi.transferencia.swmt950` | `CCC-SQLSERVER-TRANSFERENCIA-SWMT950-USER` | `CCC-SQLSERVER-TRANSFERENCIA-SWMT950-PASS` |
| SWIFT | `jndi.transferencias.swift` | `CCC-SQLSERVER-TRANSFERENCIAS-SWIFT-USER` | `CCC-SQLSERVER-TRANSFERENCIAS-SWIFT-PASS` |
| SWINQUIRY | `jndi.transferencias.swinquiry` | `CCC-SQLSERVER-TRANSFERENCIAS-SWINQUIRY-USER` | `CCC-SQLSERVER-TRANSFERENCIAS-SWINQUIRY-PASS` |
| ATM | `jndi.productos.atm` | `CCC-SQLSERVER-PRODUCTOS-ATM-USER` | `CCC-SQLSERVER-PRODUCTOS-ATM-PASS` |
| BDDPWA | `jndi.clientes.preguntas` | `CCC-SQLSERVER-CLIENTES-PREGUNTAS-PWA-USER` | `CCC-SQLSERVER-CLIENTES-PREGUNTAS-PWA-PASS` |
| WorkFlow | `jndi.tecnicos.workflow` | `CCC-SQLSERVER-TECNICOS-WORKFLOW-USER` | `CCC-SQLSERVER-TECNICOS-WORKFLOW-PASS` |
| TPOMN | `jndi.pagos` | `CCC-ORACLEXA-PAGOS-TPOMN-USER` | `CCC-ORACLEXA-PAGOS-TPOMN-PASS` |
| TPOMN | `jndi.seguridad.autoriza` | `CCC-ORACLEXA-SEGURIDAD-AUTORIZA-TPOMN-USER` | `CCC-ORACLEXA-SEGURIDAD-AUTORIZA-TPOMN-PASS` |
| BDD_BOTON_DE_CREDITO | `jdbc/botonCredito` | `CCC-SQLSERVER-BOTONCREDITO-USER` | `CCC-SQLSERVER-BOTONCREDITO-PASS` |
| Firmas | `jndi.clientes.firmas` | `CCC-SQLSERVER-CLIENTES-FIRMAS-USER` | `CCC-SQLSERVER-CLIENTES-FIRMAS-PASS` |
| mysqlUser | `jndi.tecnicos.controltransaccion` | `CCC-USER-DEF-TECNICOS-CONTROLTRANSACCION-USER` | `CCC-USER-DEF-TECNICOS-CONTROLTRANSACCION-PASS` |
| M012BAND | `jndi.tecnicos.portal` | `CCC-ORACLE-TECNICOS-PORTAL-M012BAND-USER` | `CCC-ORACLE-TECNICOS-PORTAL-M012BAND-PASS` |
| Firmas | `jndi.clientes.firmas.pry` | `CCC-SQLSERVER-CLIENTES-FIRMAS-PRY-FIRMAS-USER` | `CCC-SQLSERVER-CLIENTES-FIRMAS-PRY-FIRMAS-PASS` |

### JNDI ambiguos pendientes de confirmacion

Estos JNDI fueron recibidos con dos pares de secretos distintos. El CLI los
detecta y los reporta como `jndi_references_unknown`, pero no los convierte en
`SecretRequirement` hasta que SRE/arquitectura confirme la opcion correcta.

| JNDI ambiguo | Opciones recibidas |
|---|---|
| `jndi.xa.tecnicos.cataloga` | `TPOMN` -> `CCC-ORACLE-OMNI-CATALOGA-USER` / `CCC-ORACLE-OMNI-CATALOGA-PASSWORD`<br>`TPOMN` -> `CCC-ORACLEXA-TECNICOS-CATALOGA-TPOMN-USER` / `CCC-ORACLEXA-TECNICOS-CATALOGA-TPOMN-PASS` |
| `jndi.sfi` | `CREDIFE` -> `CCC-SQLSERVER-SFI-CREDIFE-USER` / `CCC-SQLSERVER-SFI-CREDIFE-PASS`<br>`CREDIFE` -> `CCC-SQLSERVER-SFI-USER` / `CCC-SQLSERVER-SFI-PASS` |
| `jndi.tecnicos.autorizador` | `AUTORIZADOR_PICHINCHA` -> `CCC-SQLSERVER-TECNICOS-AUTORIZADOR-USER` / `CCC-SQLSERVER-TECNICOS-AUTORIZADOR-PASS`<br>`AUTORIZADOR_PICHINCHA` -> `CCC-SQLSERVER-TECNICOS-AUTORIZADOR-PICHINCHA-USER` / `CCC-SQLSERVER-TECNICOS-AUTORIZADOR-PICHINCHA-PASS` |

## Detección del JNDI/datasource en un WAS legacy

El agente debe escanear los siguientes lugares (en orden):

1. **Archivo de discovery** del servicio legacy (`ibm-web-bnd.xml`,
   `web.xml`, o similar). El datasource aparece en `<resource-ref>` /
   `<data-source>` como `jndi.*`, `jdbc/*` o un nombre exacto del catalogo
   (por ejemplo `GEOLOCALIZACION_JNDI`).

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
   // tambien puede aparecer como jdbc/*
   DataSource ds2 = (DataSource) new InitialContext().lookup("jdbc/omni");
   ```

4. **`*.properties`** del servicio o sus UMPs — a veces el JNDI está
   parametrizado:
   ```properties
   OMNI_JNDI_CATALOGA = jndi.tecnicos.cataloga
   GEOLOCALIZACION_JNDI = GEOLOCALIZACION_JNDI
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
      ddl-auto: validate
```

**Importante**:
- Los **nombres de secretos del catalogo se usan TAL CUAL** (con guiones,
  mayusculas). No convertir a camelCase ni a snake_case.
- El **prefijo `${CCC-...}`** indica al agente que son secretos de KV, no
  variables CCC del ConfigMap (los ConfigMap usan `${CCC_...}` con
  underscore).

## Formato helm para montar los secretos del KV (MANDATORIO)

Ademas de referenciar los secretos en `application.yml` con `${CCC-...}`,
los secretos deben declararse en el bloque `secret:` del helm values para
que Azure Key Vault los monte como variables de entorno en el pod.

**Formato canonico** (`name == location`, ambos son el nombre literal del
secreto en el KV):

```yaml
# helm/values-dev.yml  (y test.yml, prod.yml — mismo nombre, distinto KV por env)
container:
  secret:
    - name: "CCC-SQLSERVER-MOTOR-HOMOLOGACION-USER"
      location: "CCC-SQLSERVER-MOTOR-HOMOLOGACION-USER"
    - name: "CCC-SQLSERVER-MOTOR-HOMOLOGACION-PASSWORD"
      location: "CCC-SQLSERVER-MOTOR-HOMOLOGACION-PASSWORD"
```

### Reglas del bloque `secret:`

- **`name`**: el nombre como se expone al contenedor (debe matchear exacto
  con la referencia `${CCC-XXX}` en `application.yml`).
- **`location`**: el nombre del secreto en Azure Key Vault. **Siempre igual
  a `name`** (convencion del banco — el secreto del KV tiene el mismo
  nombre que la env var expuesta).
- **Siempre `name == location`** — si difieren, es error de copia.
- **Orden del bloque**: USER primero, PASSWORD despues (por convencion).
- **Nombre literal del catalogo BPTPSRE**: NO inventar variantes
  (`sqlserver_motor_homologacion_user` en lowercase seria INCORRECTO).

### Ejemplo completo end-to-end (WAS con BD Oracle Omnicanal Cataloga)

**Paso 1** — legacy usa `jndi.tecnicos.cataloga` (detectado por el CLI):

```java
// legacy/ws-xxx-was/.../Propiedad.java
private static final String RUTA_ESPECIFICA = "jndi.tecnicos.cataloga";
```

**Paso 2** — mapeo al catalogo (tabla arriba):

```
jndi.tecnicos.cataloga  ->  CCC-ORACLE-OMNI-CATALOGA-USER  + CCC-ORACLE-OMNI-CATALOGA-PASSWORD
```

**Paso 3** — `application.yml` del servicio migrado:

```yaml
spring:
  datasource:
    url: ${CCC_ORACLE_OMNI_CATALOGA_URL}        # URL del config (no es secreto)
    username: ${CCC-ORACLE-OMNI-CATALOGA-USER}   # secreto KV (literal del catalogo)
    password: ${CCC-ORACLE-OMNI-CATALOGA-PASSWORD}
```

**Paso 4** — `helm/values-dev.yml` (y `test.yml`, `prod.yml`):

```yaml
container:
  secret:
    - name: "CCC-ORACLE-OMNI-CATALOGA-USER"
      location: "CCC-ORACLE-OMNI-CATALOGA-USER"
    - name: "CCC-ORACLE-OMNI-CATALOGA-PASSWORD"
      location: "CCC-ORACLE-OMNI-CATALOGA-PASSWORD"
```

Los 3 helms (dev/test/prod) tienen **los mismos nombres**, pero cada env
apunta a un KV distinto (el pod lo resuelve via annotations del namespace).

### NEVER

- `name != location` en el bloque `secret:`.
- Traducir a snake_case o camelCase (`sqlserver_motor_homologacion_user`).
- Declarar secretos huerfanos (en helm sin uso en `application.yml`).
- Omitir secretos que `application.yml` referencia con `${CCC-XXX}` —
  rompe al levantar el pod.

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
jndi_references_unknown: []   # JNDI/datasource fuera del catalogo o ambiguo
```

El agente `/migrate` consume ese yaml para poblar el `application.yml` y el
`helm/*.yml` con las refs correctas a KV (sin inventar nombres de secretos).

## Regla para el agente migrador

1. **Buscar JNDI/datasource** en los 5 lugares listados arriba (WAS + UMPs).
2. **Para cada JNDI/datasource detectado**, mapear al secreto del catalogo.
3. **Si el valor no esta en el catalogo o esta en la tabla de ambiguos**, reportar en
   `jndi_references_unknown` y dejar placeholder `${CCC-?-USER}` /
   `${CCC-?-PASSWORD}` con comentario `# TODO: solicitar secreto al team SRE`.
4. **NUNCA inventar nombres de secretos** o "adivinarlos" por convencion.
   El catalogo es la fuente de verdad.
5. Aplica SOLO a WAS con BD. BUS/ORQ/WAS-sin-BD no generan entradas.
