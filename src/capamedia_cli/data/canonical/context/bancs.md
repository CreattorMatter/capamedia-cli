---
paths:
- src/main/java/**/output/adapter/bancs/**
- src/main/java/**/config/**
---

# Reglas de Integracion BANCS

## Core Adapter
- NUNCA llamar BANCS TCP directamente desde un MSA consumidor
- NUNCA agregar frm-lib-ad-bnc-core-adapter como dependencia del MSA consumidor
- NUNCA configurar bancs.connection.* ni bancs.transaction-mapping en el MSA consumidor
- Siempre usar Core Adapter via REST: POST /bancs/trx/{trxId}
- WebClient con timeout y retry configurables via ${CCC_*} env vars

## Formato CIF (CRITICO)
- Puede variar entre servicios downstream del MISMO servicio
- Algunos UMPs requieren CIF zero-padded a 16 chars: String.format("%016d", Long.parseLong(cif))
- Otros requieren CIF integer-cast sin padding: String.valueOf(Long.parseLong(cif))
- SIEMPRE documentar en MIGRATION_REPORT.md que formato usa cada adapter

## Circuit Breaker
- Resilience4j en cada instancia de WebClient
- Configuracion via application.yml, valores via ${CCC_*} env vars
- @CircuitBreaker(name = "bancs-client") en adapters

## Error handling
- Errores de BANCS se propagan como GlobalErrorException con codigo y mensaje original
- El service decide que hacer con cada codigo (fallback, error, passthrough)
- HTTP 200 para errores de negocio (compatibilidad IIB)
