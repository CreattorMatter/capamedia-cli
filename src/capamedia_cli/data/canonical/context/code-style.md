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
- Puerto entrada: *InputPort.java (abstract class)
- Puerto salida: *OutputPort.java (abstract class)
- Service impl: *ServiceImpl.java
- Adapter: *Adapter.java o *BancsAdapter.java
- DTO: *Dto.java, *DtoRequest.java, *DtoResponse.java
- Mapper: *Mapper.java
- Config: *Config.java
- Exception: *Exception.java
- Constants: *Constants.java

## Lombok obligatorio
- @RequiredArgsConstructor en servicios y adapters (NUNCA @Autowired)
- @Slf4j en todas las clases con comportamiento
- @Builder(toBuilder = true) en records/DTOs
- @Getter en excepciones
- @Data en @ConfigurationProperties classes

## Java 21
- Preferir records sobre classes para value objects
- Preferir switch expressions sobre if/else chains
- Preferir text blocks para XML/SQL literals
- Preferir sealed classes donde aplique
