---
name: sonar-custom-rules
kind: context
priority: 2
summary: Reglas de SonarCloud del banco que NO estan en el script oficial validate_hexagonal.py pero fallan el Quality Gate
---

# Reglas de SonarCloud del banco (Quality Gate)

**Fuente**: SonarCloud del banco (organizacion `bancopichinchaec`) tiene reglas
custom activas en el Quality Gate. Son ortogonales a `validate_hexagonal.py`:
un PR puede pasar los 9 checks oficiales y aun asi rechazarse por una violation
de SonarCloud.

**NO tenemos el script** — estas reglas se infieren de los mensajes de error
que SonarCloud devuelve en los PRs. Si el equipo del banco publica el
script/config oficial, lo vendor-pineamos igual que hicimos con
`validate_hexagonal.py`.

---

## Regla S-1 — Anotacion de test class obligatoria

**Mensaje SonarCloud**: `[Anotaciones] Faltan anotaciones requeridas: @SpringBootTest`

**MUST**: cada clase `*Test.java` / `*Tests.java` bajo `src/test/java/` lleva
al menos una anotacion de test reconocida.

**NEVER**: dejar una clase que termina en `Test.java` sin anotacion de
framework. SonarCloud la cuenta como violation incluso si los `@Test` corren
verde localmente.

### Anotaciones aceptadas

| Anotacion | Cuando usarla |
|---|---|
| `@SpringBootTest` | Integration test que carga el ApplicationContext completo |
| `@WebMvcTest` | Controller slice en proyectos MVC (WAS) |
| `@WebFluxTest` | Controller slice en proyectos WebFlux (BUS/ORQ) |
| `@DataJpaTest` | Repository slice contra H2 / Testcontainers |
| `@JsonTest` | Serializacion/deserializacion de DTOs |
| `@RestClientTest` | Tests del `WebClient` / `RestTemplate` contra WireMock |
| `@JdbcTest` | Tests de `JdbcTemplate` |
| `@ExtendWith(MockitoExtension.class)` | Unit test puro con mocks (NO carga Spring) |
| `@ExtendWith(SpringExtension.class)` | Legacy — usar `@SpringBootTest` mejor |
| `@RunWith(SpringRunner.class)` | JUnit 4 legacy. Preferir migrar a JUnit 5 |
| `@AutoConfigureMockMvc` | Combinado con `@SpringBootTest` para tests de controller |

### Heuristica para elegir

```java
// ✘ NO - sin anotacion, SonarCloud lo reporta
public class MyServiceTest {
    @Test
    public void shouldDoSomething() {
        // ...
    }
}

// ✔ OK - unit test puro sin Spring context
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
public class MyServiceTest {
    @Mock private Dependency dep;
    @InjectMocks private MyService service;
    // ...
}

// ✔ OK - integration test con Spring context
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.beans.factory.annotation.Autowired;

@SpringBootTest
public class MyServiceIntegrationTest {
    @Autowired private MyService service;
    // ...
}
```

### Regla de decision entre `@SpringBootTest` y `@ExtendWith(MockitoExtension.class)`

Si la clase **usa** alguno de estos hints → `@SpringBootTest`:
- `@Autowired`, `@MockBean`, `@SpyBean`
- `TestRestTemplate`, `WebTestClient`, `MockMvc`
- Cualquier referencia al `ApplicationContext`

Si NO usa ninguno → `@ExtendWith(MockitoExtension.class)` (mucho mas rapido:
no levanta el contexto Spring, solo inyecta mocks).

### Automatizacion en el CLI

- `capamedia check --auto-fix` aplica la regla `16.1` del `AUTOFIX_REGISTRY`:
  - Si el test usa Spring context hints -> agrega `@SpringBootTest` + import
  - Si no -> agrega `@ExtendWith(MockitoExtension.class)` + imports de
    `org.junit.jupiter.api.extension.ExtendWith` y
    `org.mockito.junit.jupiter.MockitoExtension`
- `capamedia check` reporta check `16.1 Anotacion de test en @Test classes`
  con severidad **MEDIUM** (no HIGH porque el gate es SonarCloud, no
  `validate_hexagonal.py` que rechaza el PR duro).

---

## Como agregar mas reglas SonarCloud a este archivo

Cuando aparezca una violation nueva de SonarCloud que no este cubierta por el
script oficial:

1. Copiar el mensaje literal que devuelve SonarCloud (ej: `[Anotaciones]
   Faltan anotaciones requeridas: @SpringBootTest`).
2. Agregar una seccion `## Regla S-N — <nombre descriptivo>` siguiendo el
   patron de arriba (MUST / NEVER / ejemplos YES-NO / heuristica).
3. Si es autofixeable deterministicamente, agregar fix a `core/autofix.py` y
   mapearlo en `AUTOFIX_REGISTRY` con la ID del check (ej `16.1`).
4. Si no lo es, dejar la regla documentada solo — la AI la lee en el canonical
   y la aplica al migrar.
5. Correr `capamedia canonical audit` para verificar que la regla tenga
   MUST/NEVER + ejemplo NO.
