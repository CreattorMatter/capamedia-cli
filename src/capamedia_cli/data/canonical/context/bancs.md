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

## Fechas no informadas = alto valor `31129999`
Convencion BANCS: cuando una fecha no esta informada, el valor canonico es el
**alto valor** `31129999` (31 de diciembre de 9999), no el bajo valor
`01011901` (1 de enero de 1901).

- **NEVER**: `LocalDate.MIN`, `LocalDate.of(1901, 1, 1)`, literales
  `"01011901"`, `"19010101"`, `"0001-01-01"` como default de fecha en el
  adapter/mapper de BANCS.
- **OK**: `LocalDate.of(9999, 12, 31)` o literal `"31129999"` (formato segun
  el contrato del campo).
- **Por que**: el legacy lee fechas no informadas de BANCS como alto valor
  y el migrado debe replicar esa convencion para que QA no marque diferencias
  funcionales (informe WSClientes0011, 2026-05, escenario 5).
- Si el contrato del campo BANCS usa otro formato (`yyyy-MM-dd`, `ddMMyyyy`),
  ajustar la representacion pero mantener la semantica de "alto valor".

Validado por checklist Block 5.8.
