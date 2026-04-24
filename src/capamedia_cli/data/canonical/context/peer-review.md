---
name: peer-review
kind: context
priority: 1
summary: Reglas obligatorias para pasar frm-plugin-peer-review-gradle architectureReview en CI del banco
---

# Peer Review Plugin Gate

El pipeline del banco ejecuta `gradle build -x test`, pero el task
`architectureReview` igual analiza codigo de produccion y tests de forma
estatica. No declares una migracion lista si ese task queda con score bajo,
`BLOQUEAR PR: SI`, o con observaciones de arquitectura/tests sin resolver.

## Gate obligatorio

- Ejecutar o leer la salida de `gradle architectureReview` / `gradle build -x test`.
- Score global esperado: >= 7. Objetivo operativo: >= 9.
- Si aparecen secciones `OBSERVACIONES GENERALES`, `OBSERVACIONES TEST` o
  `BLOQUEAR PR: SI`, corregir antes de cerrar.
- No considerar `build_status=green` si el build compila pero el peer review
  queda bajo el umbral o con observaciones bloqueantes.

## Layout de paquetes detectable por el plugin

Usar este layout exacto en `src/main/java/com/pichincha/sp/`:

```text
application/
  input/port/*InputPort.java
  output/port/*OutputPort.java
  service/*Service.java o *ServiceImpl.java
domain/
  model/
  exception/
infrastructure/
  input/adapter/rest|soap/
  output/adapter/
```

No usar `application/port/input` ni `application/port/output`. Esa variante
compila, pero el peer-review del banco suele penalizar `Paquetes` y deja
observaciones generales.

Los ports son `public interface`, nunca `abstract class`. Los servicios
implementan el input port y dependen solo de output ports.

## Naming permitido

Evitar nombres genericos (`Service`, `Adapter`, `Port`, `Request`, `Response`,
`Dto`, `Mapper`). Cada clase debe tener prefijo de dominio u operacion:

- `ConsultarClienteInputPort`
- `BancsClienteOutputPort`
- `ConsultarClienteService`
- `ClienteBancsAdapter`
- `ConsultarClienteRequest`
- `ConsultarClienteResponse`

## Tests detectables por peer review

El plugin inspecciona los tests aunque el pipeline use `-x test`. Deben existir
tests que el analizador reconozca:

- `src/test/resources/application-test.yml` o `.properties`.
- Configuracion H2 en `application-test` cuando haya JPA/DB.
- Al menos un test de integracion con `@SpringBootTest`.
- Para REST/MVC: `@SpringBootTest` + `@AutoConfigureMockMvc` + `MockMvc`.
- Para WebFlux: `@SpringBootTest(webEnvironment = RANDOM_PORT)` o
  `@WebFluxTest` cuando corresponda, con `WebTestClient`.
- Para SOAP: `@SpringBootTest` + `MockWebServiceClient`.
- Validar HTTP 200 happy path y errores 404/500 donde aplique.

Tests unitarios con `@ExtendWith(MockitoExtension.class)` siguen siendo validos,
pero no reemplazan el integration smoke test que el peer-review espera.

## Fixes tipicos por observacion

- `Paquetes: 3 / 4`: mover ports a `application/input/port` y
  `application/output/port`; revisar sufijos de clases.
- `Faltan anotaciones requeridas: @SpringBootTest`: agregar integration smoke
  test con Spring context.
- `No se detecta uso de H2`: agregar `application-test.yml` con datasource H2 y
  activar `test` profile.
- `Falta validacion de HTTP status`: agregar asserts de 200, 404 y 500 segun el
  tipo de controlador.
