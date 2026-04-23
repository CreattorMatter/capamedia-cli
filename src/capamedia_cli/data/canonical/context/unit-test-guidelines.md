---
name: unit-test-guidelines
kind: context
priority: 1
summary: Reglas canonicas para tests unitarios en servicios migrados - given_when_then, English, 85% coverage, 0% duplicacion
---

# Unit Test Guidelines

Fuente: `QA/UNIT_TEST_GUIDELINES.md` del repo `PromptCapaMedia` (2026-04-22).

Reglas obligatorias cuando el agente genera o refactoriza tests unitarios
para servicios migrados. Aplica a los tests bajo `src/test/java/`.

## Idioma

- **Todo en ingles**: method names, variables, comments, Javadoc, nested
  class names, string literals usados como data de test.
- **Excepcion**: mensajes de produccion validados en asserts (ej. mensajes de
  error del servicio) quedan exactos al codigo de produccion aunque esten
  en otro idioma.

## Estructura

- **NO usar** `@DisplayName`.
- **Method names** deben seguir el patron `given[Context]_when[Action]_then[ExpectedResult]`.
- Si hay precondiciones adicionales: `given[Context]_and[AdditionalContext]_when[Action]_then[ExpectedResult]`.

## Cuerpo del test (3 secciones)

Cada test tiene 3 comentarios obligatorios separadores:

```java
// Given — Setup: data, mocks (when(...).thenReturn(...))
// When  — Execution: una sola llamada al metodo under test, asignada a variable
// Then  — Verification: assertions + verify(...)
```

Para tests reactive (Project Reactor):
- En `// When`: asignar el Mono/Flux a variable (ej. `Mono<Customer> result = service.method(...)`).
- En `// Then`: usar `StepVerifier.create(result)` para verificar la chain.

## Naming conventions

- **Variables**: ingles descriptivo (`requestWithNullId`, `customerFromStratio`, `expectedResponse`).
- **Constants**: `UPPER_SNAKE_CASE` (`TRANSACTION_ID`, `ERROR_HEADER`).
- **Nested test classes**: ingles descriptivo (`SuccessfulQuery`, `ServiceErrorTests`, `BancsClientExceptions`).
- **Comments y Javadoc**: solo ingles.

## Coverage requirements (MANDATORIO)

- **Line coverage** > 85%.
- **Branch coverage** > 85%.
- **Method coverage** > 85%.
- Medir con JaCoCo (o la tool configurada) y attachar el reporte como evidencia.

Si coverage < 85%:
1. Identificar lineas/ramas/metodos no cubiertos.
2. Agregar tests faltantes (happy path, error path, edge cases, null/empty, boundary).
3. Re-correr coverage hasta pasar el umbral.

**Exclusiones permitidas**: solo DTOs/records sin logica, codigo generado,
config classes. Documentar cada exclusion en test README o `pom.xml/build.gradle`
con razon justificada.

## Duplication requirements (MANDATORIO)

- **Duplicated code en el test suite = 0%**.
- Analizar con SonarQube (o PMD-CPD / jscpd) antes de entregar.

Si hay duplication, refactorizar con:
- `@BeforeEach` / `@BeforeAll` para setup comun.
- Helper methods / private factory methods para data repetida.
- Test fixtures / builders (ej. `CustomerTestDataBuilder`).
- Parameterized tests (`@ParameterizedTest` + `@ValueSource` / `@CsvSource` / `@MethodSource`) para escenarios que solo varian input/output.
- Nested classes con shared context.

**NO duplicar**:
- Mock setups que se repiten → `@BeforeEach` o helpers.
- Bloques de asserts → helpers privados (`assertCustomer(...)`).
- Literales de test data → constantes o builders.

El 0% aplica tanto dentro de una test class como entre classes del mismo modulo.

## Ejemplos canonicos

### Test reactive (Mono) con happy path

```java
@Test
void givenValidInput_whenGetCustomerByIdentification_thenReturnsCustomerSuccessfully() {
    // Given
    when(customerQueryStrategy.query(any(), any())).thenReturn(Mono.just(mockCustomer));

    // When
    Mono<Customer> result = customerService.getCustomerByIdentification(validRequest, null);

    // Then
    StepVerifier.create(result)
            .assertNext(customer -> {
                assertNotNull(customer);
                assertEquals("115678", customer.cif());
                assertEquals("0500563358", customer.identificacion());
            })
            .verifyComplete();

    verify(customerQueryStrategy, times(1)).query(any(), any());
}
```

### Test con "and" en el nombre (precondiciones adicionales)

```java
@Test
void givenStratioFails_andBancsAvailable_whenQuery_thenReturnsCustomerFromBancs() {
    // Given
    when(stratioPort.getCustomerInfo(any(), isNull(), any()))
            .thenReturn(Mono.error(new RuntimeException("Stratio unreachable")));
    when(bancsPort.getCustomerInfo(any()))
            .thenReturn(Mono.just(customerFromBancs));

    // When
    Mono<Customer> result = strategy.query(validRequest, null);

    // Then
    StepVerifier.create(result)
            .expectNextMatches(customer -> {
                assertEquals("3860119", customer.cif());
                assertThat(customer.dataSource()).isEqualTo(DataSourceTypeEnum.BANCS);
                return true;
            })
            .verifyComplete();

    verify(bancsPort, times(1)).getCustomerInfo(validRequest);
}
```

### Test no-reactive (mapper)

```java
@Test
void givenCompleteCustomerCollection_whenToCustomer_thenMapsAllFieldsCorrectly() {
    // Given
    CustomerCollection bancsCustomer = new CustomerCollection("115678", "JUAN PEREZ", ...);

    // When
    Customer result = mapper.toCustomer(bancsCustomer, request);

    // Then
    assertThat(result).isNotNull();
    assertThat(result.cif()).isEqualTo("115678");
    assertThat(result.nombre()).isEqualTo("JUAN PEREZ");
}
```

### Test de error

```java
@Test
void givenNullIdentification_whenGetCustomerByIdentification_thenThrowsBusinessValidationException() {
    // Given
    CustomerRequest requestWithNullId = new CustomerRequest(null, "0001");

    // When
    Mono<?> result = service.getCustomerByIdentification(requestWithNullId, null);

    // Then
    StepVerifier.create(result)
            .expectErrorMatches(throwable -> {
                assertThat(throwable).isInstanceOf(BusinessValidationException.class);
                return true;
            })
            .verify();

    verify(strategy, never()).query(any(), any());
}
```

### Parameterized para evitar duplication

```java
@ParameterizedTest
@CsvSource({
    "null, 0001, BusinessValidationException",
    "'',   0001, BusinessValidationException",
    "123,  null, BusinessValidationException"
})
void givenInvalidInput_whenGetCustomerByIdentification_thenThrowsValidationException(
        String identification, String office, String expectedException) {
    // Given
    CustomerRequest invalidRequest = new CustomerRequest(identification, office);

    // When
    Mono<?> result = service.getCustomerByIdentification(invalidRequest, null);

    // Then
    StepVerifier.create(result)
            .expectError(BusinessValidationException.class)
            .verify();
}
```

## Delivery checklist (antes de entregar los tests)

- [ ] Todos los method names siguen `given_when_then`.
- [ ] Cada test tiene `// Given` / `// When` / `// Then` explicitos.
- [ ] Variables, comments, constants y nested classes en ingles.
- [ ] Line/branch/method coverage > 85% (JaCoCo attachado).
- [ ] Code duplication = 0% (SonarQube / jscpd attachado).
- [ ] Sin `@DisplayName`.
- [ ] Setup compartido via `@BeforeEach` / builders / helpers.
- [ ] Escenarios repetidos convertidos a `@ParameterizedTest` cuando aplica.
- [ ] Tests pasan localmente y en CI.
