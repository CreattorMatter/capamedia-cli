---
paths:
- src/**/*.java
---

# Code Style - Banco Pichincha OLA1

## Formato
- Indentacion: 2 spaces (4 para lineas continuadas)
- Linea maxima: 100 columnas
- Metodo maximo: 20 lineas de codigo
- Sin imports no utilizados
- Todo el codigo en INGLES

## Naming
- Clases: UpperCamelCase (ConsultarContactoService)
- Metodos/variables: lowerCamelCase (consultarContacto)
- Constantes: UPPER_SNAKE_CASE (MAX_RETRY_COUNT)
- Paquetes: lowercase (com.pichincha.sp)

## Naming por responsabilidad
- Puerto entrada: *InputPort.java (public interface) en application/input/port
- Puerto salida: *OutputPort.java (public interface) en application/output/port
- Service impl: *ServiceImpl.java
- Adapter: *Adapter.java o *BancsAdapter.java
- DTO: *Dto.java, *DtoRequest.java, *DtoResponse.java
- Mapper: *Mapper.java
- Config: *Config.java
- Exception: *Exception.java
- Constants: *Constants.java

## Lombok permitido (canonico)
- `@RequiredArgsConstructor` en servicios y adapters (NUNCA `@Autowired`)
- `@Builder` en records/DTOs (preferir records sobre clases mutables)
- `@Getter` en excepciones tipadas
- `@UtilityClass` en clases con solo metodos estaticos (helpers, constantes)
- `@Getter @Setter @Builder @NoArgsConstructor @AllArgsConstructor` SOLO en DTOs JAXB SOAP envelope (requieren beans mutables)
- `@Data @Builder @NoArgsConstructor @AllArgsConstructor` SOLO en DTOs BANCS request (serializacion Jackson)

## Lombok PROHIBIDO
- `@Slf4j` — duplica el logging del banco. Usar `ServiceLogHelper log` inyectado + `@BpLogger` / `@BpTraceable` (`lib-trace-logger`). Validado por checklist Block 2.5 y 8.4.
- `import org.slf4j.Logger` / `LoggerFactory` directos — misma razon.

## Logging
- Inyectar `ServiceLogHelper log` por constructor (via `@RequiredArgsConstructor`).
- `@BpTraceable` en Controllers.
- `@BpLogger` en TODOS los metodos publicos de `@Service`.
- `log.info` reservado para eventos de contrato; diagnostico va a `log.debug`.

## Java 21
- Preferir records sobre classes para value objects
- Preferir switch expressions sobre if/else chains
- Preferir text blocks para XML/SQL literals
- Preferir sealed classes donde aplique
