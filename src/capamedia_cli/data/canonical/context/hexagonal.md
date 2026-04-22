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

## Direccion de dependencias
- infrastructure -> application (permitido)
- infrastructure -> domain (permitido)
- application -> domain (permitido)
- domain -> application (PROHIBIDO)
- domain -> infrastructure (PROHIBIDO)
- application -> infrastructure (PROHIBIDO)
