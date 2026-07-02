---
paths:
- src/main/java/**/output/adapter/bancs/**
- src/main/java/**/config/**
---

# Reglas de Integracion BANCS

## Cuando NO va `lib-bnc-api-client`

Antes de aplicar cualquier regla BANCS, verificar si el servicio realmente llama
a BANCS. **NO** llama a BANCS un servicio que:

- Solo invoca proveedores SOAP externos (Cyxtera/DetectID, motor ODM, autorizadores).
- Solo consulta XMLs operativos del banco (Catalogo Omnicanal).
- Solo consume otros servicios `WS*` migrados, no el Core Adapter BANCS.
- Tiene UMPs `UMPSeguridad*` / `UMPAutorizadores*` / `UMPGenerico*` que envuelven
  destinos no-BANCS.

En estos casos: **NO** declarar `lib-bnc-api-client` ni las
`spring.autoconfigure.exclude` BANCS; crear `.capamedia/fabrics.json` con
`invoca_bancs: false` (fuente del PR-gate). Solo el servicio que invoca el Core
Adapter via TX literal `0NNNNN` (o UMP de prefijo BANCS) necesita la lib. El CLI
lo valida en el Check 8.9.

### Prefijos UMP que SÍ son BANCS (allowlist de la señal 1)

El detector marca BANCS por una UMP **solo** si su prefijo (parte alfabética)
empieza (`startswith`) con uno de estos 8 — espejo de
`legacy_analyzer.BANCS_UMP_PREFIXES` (árbitro = código; un test de sincronía lo
valida):

`UMPClientes`, `UMPCuentas`, `UMPTransacciones`, `UMPProductos`, `UMPTarjetas`,
`UMPTransferencias`, `UMPPagos`, `UMPContratos`.

El árbitro fuerte sigue siendo la TX literal `0NNNNN` (en el ESQL del servicio o
de la UMP clonada). La completitud de esta lista depende del catálogo de dominios
del banco (pendiente de validar).

## Core Adapter
- NUNCA llamar BANCS TCP directamente desde un MSA consumidor
- NUNCA agregar frm-lib-ad-bnc-core-adapter como dependencia del MSA consumidor
- NUNCA configurar bancs.connection.* ni bancs.transaction-mapping en el MSA consumidor
- Siempre usar Core Adapter via REST: POST /bancs/trx/{trxId}
- WebClient con timeout y retry configurables via ${CCC_*} env vars

### Adaptadores relevados (OLA 2 — sirven para cualquier ola)

El Core Adapter esta particionado en adaptadores por dominio funcional. El CLI
embebe el relevamiento del banco en `data/catalog/bancs_adapters.json` (mapa
TX→adaptador, generado con `tools/build_bancs_adapters.py`) y lo inyecta al prompt
de migracion cuando detecta las TX del servicio:

- `tnd-msa-ad-bnc-customers-profile` — perfil/datos de cliente
- `tpr-msa-ad-bnc-products-details` — detalle de productos/cuentas
- `tpr-msa-ad-bnc-products-transactions` — transacciones de productos
- `tpr-msa-ad-bnc-products-insurances` — seguros
- `tpr-msa-ad-bnc-products-ownership` — titularidad
- `taa-msa-ad-bnc-products-compliance` — listas/compliance
- `tct-msa-ad-bnc-payments-parameters` — parametros de pagos
- `tia-msa-ad-bnc-catalogs` — catalogos BANCS

Rutas (relevamiento dev/test): la `https` externa (`*-enp.apps.ocp*`) es SOLO para
pruebas locales (entra a OCP4 via F5); la interna
`http://service-<adaptador>.arq-adaptadores.svc.cluster.local` es la visible
pod-a-pod dentro del cluster y es la que corresponde al despliegue. En el servicio
migrado la URL va SIEMPRE via `${CCC_*}` env vars (NUNCA hardcodear estas URLs; son
referenciales del relevamiento, contexto no configuracion).

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
