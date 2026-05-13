---
paths:
- src/**/*.java
- src/**/*.yml
- helm/**
---

# Reglas de Seguridad

## Credenciales
- NUNCA hardcodear passwords, tokens, secrets en codigo o YAMLs
- Siempre via ${CCC_*} env vars o Azure DevOps Variable Groups
- NUNCA commitear .env, credentials.json, *.pem, *.key

## Config
- spring.jpa.hibernate.ddl-auto: NUNCA create, update ni create-drop. En WAS+DB/JPA usar validate salvo excepcion explicita del runtime bancario.
- spring.jpa.open-in-view: false

## Logging
- NUNCA loguear passwords, tokens, PII (cedula completa, email, telefono)
- Usar CCC_PAYLOAD_MODE=PARTIAL en produccion

## SQL
- SIEMPRE bind variables (nunca concatenar valores en queries)
- NUNCA SELECT * (listar campos explicitos)

## Dependencias
- Snyk: 0 critical, 0 high
- Pinear versiones de Jackson, Netty, commons-lang3 si hay CVEs conocidos

## Helm
- Capacity baseline oficial (`resources` + `hpa`): ver `bank-official-rules.md` Regla 9h.1.
- `CMDB_APPLICATION_ID: "Red Hat OpenShift Container Platform"` (valor exacto, no `"CAPA_COMUN"` viejo).
- Route (OpenShift), NUNCA Ingress (Kubernetes).
