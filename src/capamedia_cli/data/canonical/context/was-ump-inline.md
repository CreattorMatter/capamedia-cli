---
name: was-ump-inline
kind: context
priority: 2
summary: WAS con UMPs dentro del mismo repo — la logica del UMP se migra INLINE al microservicio, no como llamada externa
---

# WAS + UMPs en el mismo repo: migracion inline

**Caso observado**: algunos servicios WAS del banco tienen las UMPs **dentro
del mismo repositorio** en lugar de como repos separados (`sqb-msa-ump*`).
Estas UMPs NO son servicios independientes — son módulos auxiliares que
viven en subcarpetas del WAS legacy. Cuando migramos, la lógica de ese UMP
se **plasma inline en el microservicio**, no se invoca por red.

---

## Regla WAS-UMP-1 — Detectar UMPs inline vs UMPs externas

**Dos patrones distintos** que el CLI y la AI deben distinguir:

| Patron | Evidencia legacy | Como migrar |
|---|---|---|
| **UMP externa** | Repo propio `sqb-msa-ump<nombre><id>` + llamada HTTP/MQ desde el WAS | Output port + adapter que invoca el UMP migrado como REST/SOAP downstream |
| **UMP inline** | Subcarpeta del mismo WAS (`ws-<svc>-was/ump-<nombre>/` o similar) + referencia directa Java/import | Plasmar la logica Java/ESQL de la UMP DENTRO del microservicio migrado — service methods o util classes |

**MUST**: al clonar un WAS, `capamedia clone` busca UMPs dentro del propio repo
ANTES de buscar repos externos. Si encuentra carpetas con patron UMP (ej.
`ump-*`, `*-ump/`, o clases Java con prefijo UMP) adentro del legacy, las
reporta como **inline** en el `COMPLEXITY_<svc>.md`.

**NEVER**:
- Crear un adapter/port para una UMP inline. No hay red de por medio.
- Inventar una llamada `WebClient` hacia una UMP inline — rompe el build y
  deja el código sin sentido.
- Eliminar la lógica de la UMP inline durante la migración porque "no
  tiene repo propio". La lógica es parte del servicio.

## Regla WAS-UMP-2 — Traducir la logica inline al microservicio

**MUST**:

- Si la UMP inline es **logica de transformación de datos** (parseo, mapping,
  validación) → va a `infrastructure/util/<Nombre>Util.java` (ver Regla 6
  del script oficial: Services sin utilidades).
- Si la UMP inline es **lógica de orquestación/decisión de negocio** → va al
  `@Service` del caso de uso. Ejemplo: la UMP decide qué TX invocar según un
  input → esa decisión queda en el service method, no como util separada.
- Si la UMP inline tiene **wrapper de BANCS** (invocación TX del core) → se
  migra como un `@Component` output-adapter bajo
  `infrastructure/output/adapter/bancs/` con `BancsClient` del
  `lib-bnc-api-client:1.1.0`. Es el único caso donde la UMP inline sí se
  convierte en adapter — pero el adapter NO es remoto, usa el BANCS Core
  Adapter local.

**Ejemplo concreto** (hipotético WAS con UMP inline de transformación):

```
Legacy layout:
  ws-wsclientes0010-was/
    wsclientes0010-aplicacion/
      src/main/java/com/.../ConsultaContacto.java   # entry point SOAP
    wsclientes0010-infraestructura/
      src/main/webapp/WEB-INF/{web.xml,ibm-web-*.xml}
    ump-validador-cedula/                            # UMP INLINE
      src/main/java/com/.../ValidadorCedula.java     # logica: checksum + formato

Migrado:
  tnd-msa-sp-wsclientes0010/
    application/service/
      ConsultaContactoServiceImpl.java              # orquesta
    infrastructure/util/
      CedulaValidator.java                          # <<< aqui va la logica de ump-validador-cedula
```

**Import en el Service**:
```java
import com.pichincha.sp.infrastructure.util.CedulaValidator;

@Service
@RequiredArgsConstructor
public class ConsultaContactoServiceImpl implements ConsultaContactoPort {
  // ...
  public Response consultarContacto(Request req) {
    if (!CedulaValidator.isValid(req.cedula())) {
      throw new BusinessValidationException("cedula invalida");
    }
    // ... orquestacion
  }
}
```

## Regla WAS-UMP-3 — Tests

**MUST**: la lógica migrada desde una UMP inline **tiene tests propios** en
el módulo target (`CedulaValidatorTest.java`). No se considera migrado si
no hay tests que cubran los casos que cubría la UMP original (casos borde,
validaciones, etc.).

## Regla WAS-UMP-4 — Trazabilidad

**MUST**: el `MIGRATION_REPORT.md` del proyecto migrado incluye una sección
`## UMPs inline migradas` con tabla:

| UMP legacy (path) | Lógica | Destino en migrado |
|---|---|---|
| `ws-wsclientes0010-was/ump-validador-cedula/` | Checksum + formato | `infrastructure/util/CedulaValidator.java` |

Esto le permite al reviewer verificar rápido que la lógica de cada UMP
inline quedó plasmada en el código nuevo.

---

## Automatizacion en el CLI

- `capamedia clone <svc>` detecta UMPs inline buscando:
  - Subcarpetas con patron `ump-*`, `*-ump`, `UMP-*` dentro del legacy WAS
  - Clases Java con nombre que empieza en `UMP` dentro del mismo módulo
- Reporta en `COMPLEXITY_<svc>.md`:
  - `## UMPs inline detectadas` con path + cantidad de clases Java
- `capamedia review` incluye warning MEDIUM si el `MIGRATION_REPORT.md`
  del proyecto migrado NO tiene sección `## UMPs inline migradas` y el
  legacy tenía UMPs inline detectadas.
