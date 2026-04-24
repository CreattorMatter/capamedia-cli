# vendor/

Scripts **externos** pinned. No modificar directamente; son copia literal de la
fuente upstream que mantiene el equipo del banco.

## `validate_hexagonal.py`

Validador oficial de arquitectura hexagonal para los PRs del banco. Este
es el script **exacto** que corren los reviewers en el PR — si nosotros
pasamos sus 9 checks localmente, el PR pasa su gate automatico.

**Fuente:** equipo Capa Media del banco (pegado por Julian 2026-04-22).

**Comando CLI:** `capamedia validate-hexagonal <path>` envuelve este script
y mergea su output con nuestros checks propios del block 0/5/13/14/15.

### Actualizar

Cuando el equipo del banco publique una version nueva:

```bash
capamedia validate-hexagonal sync --from <url-o-path>
```

O reemplazar manualmente este archivo, verificar que la suite sigue verde
(`pytest tests/test_validate_hexagonal.py`), bump de `CHANGELOG.md`.

### Dependencias

- `pyyaml >= 6.0` (ya en `pyproject.toml`)
- Python 3.11+

### Checks del script oficial

1. Capas `application`/`domain`/`infrastructure` presentes + sin siblings ilegales
2. WSDL: invocaBancs=true -> REST+WebFlux; si no, 1 op -> REST+WebFlux | 2+ ops -> SOAP+MVC
3. `@BpTraceable` en controllers (excluye tests)
4. `@BpLogger` en services
5. No navegacion cruzada entre capas
6. Service business logic puro (scoring heuristico, threshold 3)
7. `application.yml` sin `${VAR:default}` (excluye `optimus.web.*`)
8. Gradle: `com.pichincha.bnc:lib-bnc-api-client:1.1.0` obligatoria
9. `catalog-info.yaml` con metadata, links, annotations, specs del banco

### Comandos del wrapper

- `capamedia validate-hexagonal <path>` — corre el oficial puro
- `capamedia validate-hexagonal <path> --merge-ours` — oficial + nuestros blocks 0/5/13/14/15
- `capamedia check <path> --official-gate` — nuestro check + falla si oficial no pasa
