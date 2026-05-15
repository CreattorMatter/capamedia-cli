---
paths:
- src/main/java/**/application/**
- src/main/java/**/domain/**
---

# Reglas de Arquitectura Hexagonal OLA1

## domain/
- CERO imports de org.springframework.* (excepcion: HttpStatus en GlobalErrorException si referencia lo usa)
- CERO imports de jakarta.xml.*, jakarta.persistence.*
- CERO imports de com.pichincha.sp.infrastructure.*
- CERO imports de com.pichincha.sp.application.* (domain no conoce application)
- Solo Java puro + Lombok

## application/
- CERO imports de com.pichincha.sp.infrastructure.*
- Ports son INTERFACES, nunca abstract classes
- Services usan @RequiredArgsConstructor, nunca @Autowired
- Services implementan el input port correspondiente

## Layout de paquetes canonico
- Entrada: `application/input/port/*InputPort.java`
- Salida: `application/output/port/*OutputPort.java`
- Servicios: `application/service/*Service.java` o `*ServiceImpl.java`
- NO usar `application/port/input` ni `application/port/output`: compila, pero
  el peer-review del banco penaliza `Paquetes` y genera observaciones.

## Direccion de dependencias
- infrastructure -> application (permitido, con matiz: ver abajo)
- infrastructure -> domain (permitido)
- application -> domain (permitido)
- domain -> application (PROHIBIDO)
- domain -> infrastructure (PROHIBIDO)
- application -> infrastructure (PROHIBIDO)

### Matiz dentro de `infrastructure/`
- `infrastructure/input/**` (controllers, soap helpers, request mappers): solo puede **consumir input ports** (`application/input/port`). NUNCA inyectar output ports — eso cortocircuita la application layer.
- `infrastructure/output/adapter/**`: **implementa** output ports (`application/output/port`). Es su rol.
- `infrastructure/config/**` (`@Configuration`, `@ConfigurationProperties`): puede referenciar ports para `@Bean` wiring, pero NO debe `implements *Port` (eso es config disfrazada — Check 1.3c).

Si un helper de `infra/input/` necesita datos de un output port, los recibe via parametro desde el Service en `application/`. Validado por checklist Block 1.7.
