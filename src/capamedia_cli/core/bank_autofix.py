"""Autofixes para las 4 reglas deterministas del `validate_hexagonal.py` oficial.

El canonical `context/bank-official-rules.md` tiene las 9 reglas completas con
ejemplos YES/NO. Aqui implementamos los fixes que se pueden aplicar sin AI:

- Regla 4: `@BpLogger` faltante en metodos publicos de @Service
- Regla 7: `${VAR:default}` en `application.yml` → `${VAR}` (excluye `optimus.web.*`)
- Regla 8: `com.pichincha.bnc:lib-bnc-api-client` (version segun OLA del
  servicio — 1.1.0 OLA 1, 2.0.0 OLA 2) solo para BUS/IIB con invocaBancs=true;
  en WAS/ORQ/BUS sin BANCS no se agrega.
- Regla 9: `catalog-info.yaml` con placeholders literales → esqueleto valido

Regla 6 (Service sin utils) **NO** es autofixeable: requiere refactor semantico.
Se reporta como HIGH con hint especifico via `core/self_correction.py`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from capamedia_cli.core.ola_policy import lib_bnc_api_client_version, ola_label
from capamedia_cli.core.version_policy import (
    NETTY_CORE_MODULES,
    NETTY_WEBFLUX_ALLOWED_VERSION,
    PEER_REVIEW_PLUGIN_ID,
    PEER_REVIEW_PLUGIN_VERSION,
    SPRING_FRAMEWORK_BOM_COORD,
    SPRING_FRAMEWORK_BOM_VERSION,
    WEBFLUX_SECURITY_DEPENDENCY_PINS,
    is_version_lower,
)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BankAutofixResult:
    """Resultado de aplicar los autofixes del banco."""

    rule: str               # "4" | "7" | "8" | "9"
    applied: bool
    files_modified: list[Path] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)   # human-readable log
    notes: str = ""


# ---------------------------------------------------------------------------
# Regla 4 — @BpLogger en @Service
# ---------------------------------------------------------------------------


BPLOGGER_IMPORT = "com.pichincha.common.trace.logger.annotation.BpLogger"
_BPLOGGER_IMPORT_LINE = f"import {BPLOGGER_IMPORT};"

_SERVICE_CLASS_RE = re.compile(
    r"(@Service\s*(?:\([^)]*\))?\s*"
    r"(?:@\w+(?:\([^)]*\))?\s*)*"
    r"public\s+class\s+\w+)",
    re.MULTILINE,
)

# Captura metodo publico (no-static, no-record-accessor) con su declaracion completa
_PUBLIC_METHOD_RE = re.compile(
    r"(?P<leading>\n[ \t]+(?:@\w+(?:\([^)]*\))?\s*\n[ \t]+)*)"
    r"(?P<sig>public\s+(?!static)(?!class\s)(?:\w+\s+)*"
    r"(?!void\s+set)(?!void\s+get)(?:[\w<>\[\],\s?]+?\s+)?"
    r"(?P<name>\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{)",
    re.MULTILINE,
)


def _has_bplogger_above(text: str, method_start_idx: int) -> bool:
    """Mira ~200 chars antes del metodo para ver si ya tiene @BpLogger."""
    window_start = max(0, method_start_idx - 200)
    window = text[window_start:method_start_idx]
    return "@BpLogger" in window


def _has_service_annotation(text: str) -> bool:
    return re.search(r"@Service\b", text) is not None


def fix_add_bplogger_to_service(project_root: Path) -> BankAutofixResult:
    """Agrega `@BpLogger` a cada metodo publico de clases `@Service`."""
    result = BankAutofixResult(rule="4", applied=False)

    service_files: list[Path] = []
    for java in project_root.rglob("*.java"):
        if "test" in [p.lower() for p in java.parts]:
            continue
        try:
            txt = java.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _has_service_annotation(txt):
            service_files.append(java)

    if not service_files:
        result.notes = "no se encontraron clases @Service"
        return result

    for java in service_files:
        try:
            text = java.read_text(encoding="utf-8")
        except OSError:
            continue
        original = text

        # 1. Agregar el import si falta
        if BPLOGGER_IMPORT not in text:
            # Insertar despues del ultimo import existente
            import_block_match = re.search(
                r"((?:^import\s+[^\n]+;\n)+)", text, re.MULTILINE
            )
            if import_block_match:
                end = import_block_match.end()
                text = text[:end] + _BPLOGGER_IMPORT_LINE + "\n" + text[end:]
            else:
                # No hay imports — insertar despues del package
                pkg_match = re.match(r"package\s+[^;]+;\n", text)
                if pkg_match:
                    end = pkg_match.end()
                    text = (
                        text[:end]
                        + "\n"
                        + _BPLOGGER_IMPORT_LINE
                        + "\n"
                        + text[end:]
                    )

        # 2. Agregar @BpLogger a cada metodo publico que no lo tenga
        added = 0
        new_parts: list[str] = []
        last_end = 0
        for m in _PUBLIC_METHOD_RE.finditer(text):
            if _has_bplogger_above(text, m.start("sig")):
                continue
            # Insertar @BpLogger en la linea anterior al metodo
            new_parts.append(text[last_end : m.start("sig")])
            # Deducir indentacion
            line_start = text.rfind("\n", 0, m.start("sig")) + 1
            indent = text[line_start : m.start("sig")]
            new_parts.append(f"@BpLogger\n{indent}")
            last_end = m.start("sig")
            added += 1

        if added > 0:
            new_parts.append(text[last_end:])
            text = "".join(new_parts)

        if text != original:
            java.write_text(text, encoding="utf-8")
            result.files_modified.append(java)
            result.changes.append(
                f"{java.relative_to(project_root)}: +@BpLogger en {added} "
                f"metodo(s), import agregado={BPLOGGER_IMPORT in text and _BPLOGGER_IMPORT_LINE not in original}"
            )
            result.applied = True

    if not result.applied:
        result.notes = f"{len(service_files)} @Service escaneados, ya tenian @BpLogger"
    return result


# ---------------------------------------------------------------------------
# Regla 7 — application.yml sin ${VAR:default}
# ---------------------------------------------------------------------------


# Prefijos excluidos por el script oficial (pueden tener defaults)
_YML_EXCLUDED_PREFIXES = ("optimus.web",)


def _is_excluded_yml_path(path: str) -> bool:
    return any(
        path == excl or path.startswith(excl + ".") for excl in _YML_EXCLUDED_PREFIXES
    )


def _build_yml_path(lines: list[str], target_idx: int) -> str:
    """Reconstruye el path yaml ancestral del item en la linea target_idx."""
    path_parts: list[tuple[int, str]] = []  # (indent, key)
    for i in range(target_idx + 1):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.rstrip()
        indent = len(line) - len(line.lstrip(" "))
        key_match = re.match(r"([\w\-]+)\s*:", stripped.lstrip())
        if not key_match:
            continue
        # descartar niveles mas profundos que este indent
        while path_parts and path_parts[-1][0] >= indent:
            path_parts.pop()
        path_parts.append((indent, key_match.group(1)))
    return ".".join(k for _, k in path_parts)


def fix_yml_remove_defaults(project_root: Path) -> BankAutofixResult:
    """Reemplaza `${VAR:default}` por `${VAR}` en application.yml, preserva `optimus.web.*`."""
    result = BankAutofixResult(rule="7", applied=False)

    yml_files: list[Path] = []
    excluded_segments = {"test", "tests"}
    for y in project_root.rglob("application.yml"):
        # Excluir archivos bajo un segmento de path que sea literal "test"/"tests".
        # Match exacto, no prefix (evita falsos positivos con tmp_path de pytest, etc).
        if any(p.lower() in excluded_segments for p in y.parts[:-1]):
            continue
        yml_files.append(y)

    if not yml_files:
        result.notes = "no se encontro application.yml"
        return result

    pat = re.compile(r"\$\{([^}:]+):([^}]+)\}")

    for y in yml_files:
        try:
            text = y.read_text(encoding="utf-8")
        except OSError:
            continue
        original = text
        lines = text.splitlines()
        modified_lines = list(lines)
        replacements = 0
        for i, line in enumerate(lines):
            if not pat.search(line):
                continue
            path = _build_yml_path(lines, i)
            if _is_excluded_yml_path(path):
                continue
            new_line = pat.sub(lambda m: f"${{{m.group(1).strip()}}}", line)
            if new_line != line:
                modified_lines[i] = new_line
                replacements += 1

        if replacements > 0:
            new_text = "\n".join(modified_lines)
            if text.endswith("\n"):
                new_text += "\n"
            y.write_text(new_text, encoding="utf-8")
            result.files_modified.append(y)
            result.changes.append(
                f"{y.relative_to(project_root)}: {replacements} default(s) removido(s)"
            )
            result.applied = True
        _ = original  # ruff unused guard

    if not result.applied:
        result.notes = f"{len(yml_files)} yml escaneados, ya limpios"
    return result


# ---------------------------------------------------------------------------
# Regla 8 — lib-bnc-api-client en build.gradle (version segun OLA)
#
# La version depende del OLA del servicio (ver `core/ola_policy.py`):
#   - OLA 1  -> 1.1.0
#   - OLA 2  -> 2.0.0  (servicios listados en OLA2_SERVICES)
# ---------------------------------------------------------------------------


LIBBNC_ARTIFACT = "com.pichincha.bnc:lib-bnc-api-client"

# Matchea la coordenada con CUALQUIER version declarada: estable, pre-release
# o de la otra OLA. Group 1 = `<artifact>:`, group 2 = la version.
_LIBBNC_COORD_RE = re.compile(
    r"(com\.pichincha\.bnc:lib-bnc-api-client:)([0-9][\w.\-]*)"
)


def _requires_bancs_from_matrix(source_type: str | None, has_bancs: bool) -> bool:
    """True solo para el caso oficial que requiere lib-bnc-api-client."""
    return (source_type or "").lower() in {"bus", "iib"} and has_bancs


def _detect_service_name(project_root: Path) -> str:
    """Best-effort: nombre de servicio para decidir el OLA.

    Mira `.capamedia/config.yaml`, `spring.application.name` y el nombre de la
    carpeta, en ese orden. El resultado se pasa a `core.ola_policy`, que extrae
    el token de servicio (ej. `tnd-msa-sp-wsclientes0011` -> `wsclientes0011`).
    """
    config = project_root / ".capamedia" / "config.yaml"
    if config.exists():
        try:
            import yaml

            data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and data.get("service_name"):
                return str(data["service_name"])
        except Exception:
            pass

    app_name = _read_spring_application_name(project_root)
    if app_name:
        return app_name

    return project_root.name


def fix_add_libbnc_dependency(
    project_root: Path,
    *,
    requires_bancs: bool | None = None,
    service: str | None = None,
) -> BankAutofixResult:
    """Fija `lib-bnc-api-client` en la version del OLA del servicio.

    Version (ver `core/ola_policy.py`):
      - OLA 1 (default): 1.1.0
      - OLA 2 (servicios de `OLA2_SERVICES`): 2.0.0

    Comportamiento:
      1. Si la libreria ya esta declarada con una version distinta a la del
         OLA — incluye pre-releases y la version de la otra OLA — la reescribe
         a la version correcta. Cubre `1.1.0` en un servicio OLA 2 y `2.0.0`
         en uno OLA 1.
      2. Si la matriz dice BUS/IIB + invocaBancs=true y la libreria no esta,
         la inserta con la version del OLA.
      3. Si la matriz dice WAS/ORQ/BUS sin BANCS, nunca la agrega.

    La deteccion de "ya esta declarada" es por NOMBRE de artefacto (no por
    version), de modo que un `build.gradle` correcto en `2.0.0` nunca recibe
    una segunda linea `1.1.0` en conflicto.
    """
    result = BankAutofixResult(rule="8", applied=False)

    if service is None:
        service = _detect_service_name(project_root)
    target_version = lib_bnc_api_client_version(service)
    label = ola_label(service)
    required_dep_line = f"    implementation '{LIBBNC_ARTIFACT}:{target_version}'"

    gradle_files = [
        f
        for f in project_root.rglob("build.gradle")
        if "test" not in [p.lower() for p in f.parts]
    ] + [
        f
        for f in project_root.rglob("build.gradle.kts")
        if "test" not in [p.lower() for p in f.parts]
    ]

    if not gradle_files:
        result.notes = "no se encontro build.gradle"
        return result

    for gf in gradle_files:
        try:
            text = gf.read_text(encoding="utf-8")
        except OSError:
            continue

        original = text

        # Paso 1: reescribir cualquier version declarada a la version del OLA.
        # Cubre pre-releases (1.1.0-alpha.*, 2.0.0-SNAPSHOT) y la version de la
        # otra OLA (1.1.0 en un servicio OLA 2, o 2.0.0 en uno OLA 1).
        present_versions = {m.group(2) for m in _LIBBNC_COORD_RE.finditer(text)}
        wrong_versions = sorted(present_versions - {target_version})
        if wrong_versions:
            text = _LIBBNC_COORD_RE.sub(
                lambda m: m.group(1) + target_version, text
            )
            result.changes.append(
                f"{gf.relative_to(project_root)}: lib-bnc-api-client "
                f"{', '.join(wrong_versions)} -> {target_version} ({label})"
            )

        # Paso 2: si la libreria no esta y la matriz la requiere, insertarla.
        # La deteccion es por nombre de artefacto, no por version.
        if LIBBNC_ARTIFACT not in text:
            if requires_bancs is True:
                m = re.search(r"dependencies\s*\{", text)
                if not m:
                    text = (
                        text.rstrip()
                        + "\n\ndependencies {\n"
                        + required_dep_line
                        + "\n}\n"
                    )
                else:
                    insert_pos = m.end()
                    text = (
                        text[:insert_pos]
                        + "\n"
                        + required_dep_line
                        + text[insert_pos:]
                    )
                result.changes.append(
                    f"{gf.relative_to(project_root)}: "
                    f"+lib-bnc-api-client:{target_version} ({label})"
                )
            elif not wrong_versions:
                result.notes = (
                    "Regla 8 omitida: lib-bnc-api-client solo aplica a "
                    "BUS/IIB con invocaBancs=true; sin contexto explicito no se agrega"
                )

        if text != original:
            gf.write_text(text, encoding="utf-8")
            result.files_modified.append(gf)
            result.applied = True

    if not result.applied and not result.notes:
        result.notes = (
            f"lib-bnc-api-client ya en {target_version} ({label}) "
            "o no aplica por matriz"
        )
    return result


# ---------------------------------------------------------------------------
# Regla 8b — `spring.autoconfigure.exclude` cuando lib-bnc-api-client esta en
# el classpath pero el servicio NO invoca BANCS.
#
# Contexto: Regla 8 oficial fuerza la libreria en build.gradle como substring
# match (validate_hexagonal.py). Si el servicio realmente no llama BANCS,
# Spring Boot levanta WebClientAutoConfiguration al arranque y muere con:
#   "At least one web client configuration must be provided under
#    'bancs.webclients'"
# El pod entra en CrashLoopBackOff. El fix es excluir las 3 auto-configs.
# ---------------------------------------------------------------------------


_BANCS_AUTOCONFIG_EXCLUSIONS = [
    "com.pichincha.bnc.apiclient.autoconfigure.BancsClientAutoConfiguration",
    "com.pichincha.bnc.apiclient.autoconfigure.BancsCircuitBreakerAutoConfiguration",
    "com.pichincha.bnc.apiclient.autoconfigure.WebClientAutoConfiguration",
]


def _service_uses_bancs(project_root: Path) -> bool:
    """True si el servicio realmente invoca BANCS.

    Senales: imports de `com.pichincha.bnc.*`, anotaciones `@BancsService`,
    helpers `BancsClientHelper`, o un bloque `bancs.webclients` declarado en
    application.yml.
    """
    src_java = project_root / "src" / "main" / "java"
    if src_java.exists():
        for java in src_java.rglob("*.java"):
            if "build" in java.parts or "test" in [p.lower() for p in java.parts]:
                continue
            try:
                text = java.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if (
                "com.pichincha.bnc" in text
                or "@BancsService" in text
                or "BancsClientHelper" in text
            ):
                return True

    resources = project_root / "src" / "main" / "resources"
    if resources.exists():
        for yml in list(resources.rglob("application*.yml")) + list(
            resources.rglob("application*.yaml")
        ):
            try:
                text = yml.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if re.search(r"(?m)^\s{0,2}bancs\s*:\s*$", text) and re.search(
                r"(?m)^\s+webclients\s*:", text
            ):
                return True
    return False


def _libbnc_in_classpath(project_root: Path) -> bool:
    for gf in list(project_root.rglob("build.gradle")) + list(
        project_root.rglob("build.gradle.kts")
    ):
        if "build" in gf.parts or ".git" in gf.parts:
            continue
        if "test" in [p.lower() for p in gf.parts]:
            continue
        try:
            if "lib-bnc-api-client" in gf.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def _yml_already_excludes_bancs(text: str) -> bool:
    """True si los 3 auto-configs ya estan listados bajo
    `spring.autoconfigure.exclude`. Se hace un match laxo por nombre simple."""
    if "autoconfigure" not in text or "exclude" not in text:
        return False
    needles = (
        "BancsClientAutoConfiguration",
        "BancsCircuitBreakerAutoConfiguration",
        "WebClientAutoConfiguration",
    )
    return all(needle in text for needle in needles)


_SPRING_BLOCK_RE = re.compile(r"(?m)^spring\s*:\s*$")


def _insert_autoconfigure_exclude_into_yml(text: str) -> str | None:
    """Devuelve el yml con el bloque `spring.autoconfigure.exclude` insertado.

    Si `spring:` ya existe, agrega `autoconfigure.exclude` adentro respetando
    indentacion. Si no existe, prepende el bloque al inicio del archivo.
    Devuelve None si ya esta presente y no hay nada que hacer.
    """
    if _yml_already_excludes_bancs(text):
        return None

    block = (
        "  autoconfigure:\n"
        "    # lib-bnc-api-client esta en el classpath por Regla 8 oficial,\n"
        "    # pero este servicio NO invoca BANCS. Sin esta exclusion, las\n"
        "    # auto-configs piden 'bancs.webclients' al arranque y el pod\n"
        "    # entra en CrashLoopBackOff.\n"
        "    exclude:\n"
        + "\n".join(f"      - {fqn}" for fqn in _BANCS_AUTOCONFIG_EXCLUSIONS)
        + "\n"
    )

    m = _SPRING_BLOCK_RE.search(text)
    if not m:
        return "spring:\n" + block + ("\n" + text if text and not text.startswith("\n") else text)

    # Insertar el bloque inmediatamente despues del `spring:` header,
    # preservando todo el contenido existente del bloque spring.
    insert_pos = m.end()
    if insert_pos < len(text) and text[insert_pos] != "\n":
        return text[:insert_pos] + "\n" + block + text[insert_pos:]
    return text[: insert_pos + 1] + block + text[insert_pos + 1 :]


def fix_bancs_autoconfigure_exclude(project_root: Path) -> BankAutofixResult:
    """Agrega `spring.autoconfigure.exclude` en application.yml cuando aplica.

    Aplica si:
      - `lib-bnc-api-client` esta en `build.gradle`, Y
      - el codigo no usa BANCS (sin imports `com.pichincha.bnc.*`, sin
        `@BancsService`, sin bloque `bancs.webclients` en `application.yml`), Y
      - el `application.yml` aun no tiene la exclusion.

    No toca `application-test.yml` ni perfiles de test.
    """
    result = BankAutofixResult(rule="8b", applied=False)

    if not _libbnc_in_classpath(project_root):
        result.notes = "lib-bnc-api-client no esta en build.gradle: no aplica"
        return result

    if _service_uses_bancs(project_root):
        result.notes = "servicio invoca BANCS: no aplica"
        return result

    yml = project_root / "src" / "main" / "resources" / "application.yml"
    if not yml.exists():
        yml = project_root / "src" / "main" / "resources" / "application.yaml"
    if not yml.exists():
        result.notes = "no se encontro src/main/resources/application.yml"
        return result

    try:
        text = yml.read_text(encoding="utf-8")
    except OSError as e:
        result.notes = f"no se pudo leer application.yml: {e}"
        return result

    new_text = _insert_autoconfigure_exclude_into_yml(text)
    if new_text is None:
        result.notes = "application.yml ya excluye las auto-configs BANCS"
        return result

    yml.write_text(new_text, encoding="utf-8")
    result.applied = True
    result.files_modified.append(yml)
    result.changes.append(
        f"{yml.relative_to(project_root)}: +spring.autoconfigure.exclude "
        f"(BancsClient/BancsCircuitBreaker/WebClient AutoConfiguration)"
    )
    return result


# ---------------------------------------------------------------------------
# Regla 9 — catalog-info.yaml
# ---------------------------------------------------------------------------


CATALOG_INFO_TEMPLATE = """apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  namespace: {catalog_namespace}
  name: tpl-middleware
  description: {description}
  annotations:
    dev.azure.com/project-repo: tpl-middleware/{repo_name}
    sonarcloud.io/project-key: {sonar_key}
  links:
    - url: https://dev.azure.com/BancoPichinchaEC/tpl-middleware/_git/{repo_name}
      title: Repositorio
      icon: link
    - url: https://app.swaggerhub.com/apis/BancoPichincha/{repo_name}/1.0.0
      title: OpenAPI
      icon: DataObject
    - url: https://pichincha.atlassian.net/wiki/spaces/CDSRL/pages/2808054060/Documentacion
      title: Documentacion tecnica
      icon: link
spec:
  type: service
  owner: {owner}
  lifecycle: test
{depends_on_yaml}
"""


def _detect_bnc_libs_in_gradle(project_root: Path) -> list[str]:
    """Devuelve lib-names (sin version) de `com.pichincha.*:lib-*` en build.gradle."""
    libs: set[str] = set()
    for gf in project_root.rglob("build.gradle"):
        if "test" in [p.lower() for p in gf.parts]:
            continue
        try:
            text = gf.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in re.finditer(
            r"com\.pichincha(?:\.\w+)?:(lib-[\w\-]+)(?::[^'\"]*)?['\"]",
            text,
        ):
            libs.add(m.group(1))
    return sorted(libs)


def _placeholder_uuid_from_name(repo_name: str) -> str:
    """Genera un UUID sintetico que pase el regex oficial del validador
    `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`
    usando el sufijo numerico del servicio. Ej: `wsclientes0007` -> el ultimo
    bloque termina en `...000000000007`. No reemplaza al real de SonarCloud,
    solo evita que el catalog-info falle el validador hasta que se haga
    binding.
    """
    nums = re.findall(r"\d+", repo_name)
    suffix = (nums[-1] if nums else "0").zfill(12)
    return f"00000000-0000-0000-0000-{suffix[-12:]}"


def _infer_repo_name(project_root: Path) -> str:
    """Deduce el nombre del repo Azure del servicio."""
    name = project_root.name
    # tnd-msa-sp-wsclientes0007 queda tal cual
    if name.startswith(("tnd-msa-sp-", "tia-msa-sp-", "tpr-msa-sp-", "csg-msa-sp-")):
        return name
    # fallback
    return name


def _read_spring_application_name(project_root: Path) -> str | None:
    for rel in (
        Path("src/main/resources/application.yml"),
        Path("src/main/resources/application.yaml"),
    ):
        yml = project_root / rel
        if not yml.exists():
            continue
        try:
            text = yml.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = re.search(
            r"(?ms)^\s*spring\s*:\s*.*?^\s*application\s*:\s*.*?^\s*name\s*:\s*['\"]?([^'\"\s#]+)",
            text,
        )
        if match:
            return match.group(1).strip()
    return None


def _catalog_namespace_from_repo(repo_name: str) -> str:
    prefix = repo_name.split("-", 1)[0] if "-" in repo_name else repo_name[:3]
    return f"{prefix}-middleware"


def _git_user_email(project_root: Path) -> str | None:
    """Intenta leer `user.email` del git config. Vacio si no tiene `@pichincha.com`."""
    try:
        import subprocess

        out = subprocess.run(
            ["git", "config", "--get", "user.email"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            cwd=str(project_root),
        )
        email = out.stdout.strip()
        if email.endswith("@pichincha.com"):
            return email
    except Exception:
        pass
    return None


def fix_catalog_info_scaffold(
    project_root: Path,
    *,
    description: str | None = None,
    owner: str | None = None,
) -> BankAutofixResult:
    """Genera `catalog-info.yaml` valido con placeholders CORRECTOS donde
    sean inevitables (owner, description), usando valores reales donde se
    puede (namespace, name, lifecycle, sonar_key, libs)."""
    result = BankAutofixResult(rule="9", applied=False)

    target = project_root / "catalog-info.yaml"
    if target.exists():
        # Si ya tiene valores reales (no placeholders), no tocar
        try:
            existing = target.read_text(encoding="utf-8")
        except OSError:
            existing = ""
        has_placeholders = (
            "<project-name>" in existing
            or "<owner>" in existing
            or "comming soon" in existing
            or "<lifecycle>" in existing
            or "<sonarcloud-project-key>" in existing
        )
        if not has_placeholders:
            result.notes = "catalog-info.yaml ya tiene valores reales (no tocar)"
            return result

    repo_name = _infer_repo_name(project_root)
    catalog_namespace = _catalog_namespace_from_repo(repo_name)
    sonar_key = _placeholder_uuid_from_name(repo_name)
    owner_resolved = owner or _git_user_email(project_root) or "<SET-email-pichincha>"
    desc_resolved = description or f"Servicio {repo_name}"

    detected_libs = _detect_bnc_libs_in_gradle(project_root)
    if detected_libs:
        depends_on = "  dependsOn:\n" + "\n".join(
            f"    - component:{lib}" for lib in detected_libs
        )
    else:
        depends_on = "  dependsOn: []"

    content = CATALOG_INFO_TEMPLATE.format(
        description=desc_resolved,
        repo_name=repo_name,
        catalog_namespace=catalog_namespace,
        sonar_key=sonar_key,
        owner=owner_resolved,
        depends_on_yaml=depends_on,
    )
    target.write_text(content, encoding="utf-8")
    result.files_modified.append(target)
    result.applied = True

    manual_notes: list[str] = [
        "sonarcloud.io/project-key (reemplazar UUID sintetico por el real de SonarCloud)",
    ]
    if owner_resolved.startswith("<"):
        manual_notes.append("spec.owner (setear email @pichincha.com)")
    result.notes = "Revisar manualmente: " + ", ".join(manual_notes)
    result.changes.append(
        f"{target.relative_to(project_root)}: generado con "
        f"namespace={catalog_namespace}, name=tpl-middleware, lifecycle=test, "
        f"dependsOn={detected_libs or '[]'}"
    )
    return result


# ---------------------------------------------------------------------------
# Regla 6 — Service business logic puro
# ---------------------------------------------------------------------------
#
# Dos patterns deterministas para eliminar senales del check 6 sin
# romper comportamiento:
#
# Pattern A: StringUtils.* del Apache Commons -> Java nativo
#   StringUtils.isBlank(x)    -> (x == null || x.isBlank())
#   StringUtils.isEmpty(x)    -> (x == null || x.isEmpty())
#   StringUtils.isNotBlank(x) -> (x != null && !x.isBlank())
#   StringUtils.isNotEmpty(x) -> (x != null && !x.isEmpty())
#   + remover `import org.apache.commons.lang3.StringUtils;` si queda sin uso.
#
# Pattern B: record / class interna en @Service -> domain/model/<Name>.java
#   Extrae `private record FooData(...)` o `private static record FooData(...)`
#   a un archivo nuevo bajo `application/model/<Name>.java` (o domain/model
#   si el caller indica) + agrega import en el Service.


_STRINGUTILS_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    # isNotBlank / isNotEmpty primero (mas especificos)
    (re.compile(r"StringUtils\.isNotBlank\(\s*([^)]+?)\s*\)"),
     r"(\1 != null && !\1.isBlank())"),
    (re.compile(r"StringUtils\.isNotEmpty\(\s*([^)]+?)\s*\)"),
     r"(\1 != null && !\1.isEmpty())"),
    (re.compile(r"StringUtils\.isBlank\(\s*([^)]+?)\s*\)"),
     r"(\1 == null || \1.isBlank())"),
    (re.compile(r"StringUtils\.isEmpty\(\s*([^)]+?)\s*\)"),
     r"(\1 == null || \1.isEmpty())"),
)

_STRINGUTILS_IMPORT_RE = re.compile(
    r"^import\s+org\.apache\.commons\.lang3\.StringUtils;\s*\n",
    re.MULTILINE,
)


def fix_stringutils_to_native(project_root: Path) -> BankAutofixResult:
    """Reemplaza `StringUtils.isBlank/isEmpty/isNotBlank/isNotEmpty` por Java
    nativo en clases @Service. Remueve el import si queda sin uso."""
    result = BankAutofixResult(rule="6", applied=False)

    service_files: list[Path] = []
    for java in project_root.rglob("*.java"):
        if "test" in [p.lower() for p in java.parts]:
            continue
        try:
            txt = java.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _has_service_annotation(txt) and "StringUtils." in txt:
            service_files.append(java)

    if not service_files:
        result.notes = "no se encontraron @Service con StringUtils"
        return result

    for java in service_files:
        try:
            text = java.read_text(encoding="utf-8")
        except OSError:
            continue
        original = text
        total_replacements = 0
        for pat, repl in _STRINGUTILS_REPLACEMENTS:
            text, n = pat.subn(repl, text)
            total_replacements += n
        if total_replacements == 0:
            continue
        # Si el import queda sin uso, removerlo
        if "StringUtils." not in text:
            text = _STRINGUTILS_IMPORT_RE.sub("", text)
        if text != original:
            java.write_text(text, encoding="utf-8")
            result.files_modified.append(java)
            result.changes.append(
                f"{java.relative_to(project_root)}: {total_replacements} "
                f"StringUtils.* -> Java nativo"
            )
            result.applied = True

    if not result.applied:
        result.notes = f"{len(service_files)} @Service escaneados, ningun patron matcheo"
    return result


_INNER_RECORD_RE = re.compile(
    r"(?P<indent>^[ \t]+)"
    r"(?P<modifiers>(?:(?:private|protected|public|static|final)\s+)+)"
    r"record\s+(?P<name>\w+)\s*"
    r"(?P<body>\([^)]*\)\s*(?:\{[^}]*\})?;?)",
    re.MULTILINE,
)


def _derive_base_package(service_text: str) -> str | None:
    """Extrae `com.pichincha.sp` de `package com.pichincha.sp.application.service;`."""
    m = re.match(r"package\s+([\w.]+);", service_text)
    if not m:
        return None
    full_pkg = m.group(1)
    # Quitar el sufijo tipico de la capa para quedarse con base
    for suffix in (
        ".application.service",
        ".application.input.port",
        ".application.output.port",
        ".infrastructure.input.adapter",
        ".infrastructure.output.adapter",
        ".infrastructure",
        ".application",
        ".domain",
    ):
        if full_pkg.endswith(suffix):
            return full_pkg[: -len(suffix)]
    return full_pkg


def fix_extract_inner_records_to_model(project_root: Path) -> BankAutofixResult:
    """Mueve records privados/internos del @Service a
    `application/model/<Name>.java`, los hace public, agrega el import.

    El target directory es `application/model/` por convencion: los records
    son DTOs internos del flujo de aplicacion, no entidades de dominio.
    """
    result = BankAutofixResult(rule="6", applied=False)

    for java in project_root.rglob("*.java"):
        if "test" in [p.lower() for p in java.parts]:
            continue
        try:
            text = java.read_text(encoding="utf-8")
        except OSError:
            continue
        if not _has_service_annotation(text):
            continue
        matches = list(_INNER_RECORD_RE.finditer(text))
        if not matches:
            continue

        base_pkg = _derive_base_package(text)
        if not base_pkg:
            continue
        model_pkg = f"{base_pkg}.application.model"
        # Localizar dir para escribir los archivos nuevos
        model_dir = (
            project_root
            / "src" / "main" / "java"
            / Path(*model_pkg.split("."))
        )
        model_dir.mkdir(parents=True, exist_ok=True)

        new_text = text
        imports_to_add: list[str] = []
        for m in reversed(matches):  # reversed para no romper offsets
            record_name = m.group("name")
            record_body = m.group("body").rstrip(";").strip()
            # Generar el archivo nuevo
            file_path = model_dir / f"{record_name}.java"
            if not file_path.exists():
                file_path.write_text(
                    f"package {model_pkg};\n\n"
                    f"public record {record_name}{record_body}\n"
                    if record_body.endswith("}")
                    else (
                        f"package {model_pkg};\n\n"
                        f"public record {record_name}{record_body} {{}}\n"
                    ),
                    encoding="utf-8",
                )
                result.files_modified.append(file_path)
                result.changes.append(
                    f"{file_path.relative_to(project_root)}: nuevo record {record_name}"
                )
            # Remover del Service
            new_text = new_text[: m.start()] + new_text[m.end():]
            # Eliminar linea vacia residual si quedo
            imports_to_add.append(f"{model_pkg}.{record_name}")

        # Agregar imports en el Service
        for imp in imports_to_add:
            full_import = f"import {imp};"
            if full_import in new_text:
                continue
            # Insertar despues del ultimo import existente
            m_imp = list(re.finditer(r"^import\s+[^\n]+;\n", new_text, re.MULTILINE))
            if m_imp:
                insert_at = m_imp[-1].end()
                new_text = new_text[:insert_at] + full_import + "\n" + new_text[insert_at:]
            else:
                # Sin imports previos: tras el package
                pkg_m = re.match(r"package\s+[^;]+;\n", new_text)
                if pkg_m:
                    insert_at = pkg_m.end()
                    new_text = (
                        new_text[:insert_at]
                        + "\n"
                        + full_import
                        + "\n"
                        + new_text[insert_at:]
                    )

        if new_text != text:
            java.write_text(new_text, encoding="utf-8")
            result.files_modified.append(java)
            result.changes.append(
                f"{java.relative_to(project_root)}: {len(matches)} "
                f"record(s) interno(s) movido(s) a application/model/"
            )
            result.applied = True

    if not result.applied:
        result.notes = "ningun @Service con record interno"
    return result


# ---------------------------------------------------------------------------
# Regla 9h.1 — Helm capacity baseline oficial (capacity Banco Pichincha).
# Ajuste 2026-05-29 (kevin armas): requests.memory 350Mi->100Mi, limits.memory
# 500Mi->400Mi. Ajuste 2026-07: HPA derogado, el autoscaling pasa a KEDA. El
# autofix ELIMINA el bloque `hpa:` (cambio seguro); la inyeccion de
# `keda:`/`servicemonitor:` la hacen las plantillas de migracion. Aplica a
# helm/dev.yml, helm/test.yml, helm/prod.yml. Valores referenciales hasta que
# pruebas de rendimiento definan definitivos.
# ---------------------------------------------------------------------------


HELM_CAPACITY_BASELINE_FIX: dict[str, str] = {
    "requests.cpu": "50m",
    "requests.memory": "100Mi",
    "limits.cpu": "200m",
    "limits.memory": "400Mi",
}


def _strip_top_block(text: str, key: str) -> str:
    """Elimina el bloque mapping top-level `key:` (la linea `key:` mas todas las
    lineas mas indentadas que le siguen) de un YAML helm. Conserva la linea en
    blanco separadora que quede tras el bloque. Idempotente si `key:` no existe.
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = re.match(rf"^(\s*){re.escape(key)}\s*:\s*(#.*)?$", line.rstrip("\n"))
        if m:
            key_indent = len(m.group(1))
            i += 1
            pending_blanks: list[str] = []
            while i < n:
                nxt = lines[i]
                if not nxt.strip():
                    pending_blanks.append(nxt)
                    i += 1
                    continue
                indent = len(nxt) - len(nxt.lstrip(" "))
                if indent <= key_indent:
                    break
                pending_blanks = []  # blanks pertenecian al interior del bloque
                i += 1
            out.extend(pending_blanks)  # re-emitir la separacion tras el bloque
            continue
        out.append(line)
        i += 1
    return "".join(out)


def fix_helm_capacity_baseline(project_root: Path) -> BankAutofixResult:
    """Aplica el baseline oficial de capacity/scaling en los 3 Helm:
       - resources.requests.cpu/memory y resources.limits.cpu/memory exactos.
       - Elimina el bloque `hpa:` (derogado 2026-07; lo reemplaza KEDA).

    Idempotente. Si un archivo helm/<env>.yml no existe, lo saltea sin tocar.
    NO inyecta `keda:`/`servicemonitor:` (cirugia YAML con contexto que hacen
    las plantillas de migracion); solo hace los cambios seguros: reescribir los
    valores de `resources` que difieren y quitar el `hpa:` derogado.
    """
    result = BankAutofixResult(rule="9h.1", applied=False)

    helm_dir = project_root / "helm"
    if not helm_dir.exists():
        result.notes = "helm/ no existe en el proyecto"
        return result

    helm_files = [
        f for f in helm_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".yml", ".yaml"}
    ]
    if not helm_files:
        result.notes = "helm/ vacio"
        return result

    modified_files: list[Path] = []
    for f in helm_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        original = text

        # HPA derogado (2026-07): el autoscaling pasa a KEDA. Eliminar el bloque
        # `hpa:` si existe (cambio seguro). El bloque `keda:` + `servicemonitor:`
        # lo generan las plantillas de migracion, no el autofix.
        text = _strip_top_block(text, "hpa")

        # Fix resources.requests/limits.cpu/memory
        # Procesamos el bloque resources: como un texto compuesto. Buscamos
        # las subsecciones requests: y limits: y reescribimos cpu/memory dentro
        # con los valores baseline. Mantenemos la indentacion original.
        text = _rewrite_helm_resources_block(text)

        if text != original:
            f.write_text(text, encoding="utf-8")
            modified_files.append(f)
            result.changes.append(
                f"{f.relative_to(project_root)}: capacity baseline aplicado"
            )

    if modified_files:
        result.applied = True
        result.files_modified = modified_files
    else:
        result.notes = "helm/ ya tiene el baseline oficial"
    return result


def _rewrite_helm_resources_block(text: str) -> str:
    """Reescribe valores cpu/memory dentro del bloque resources: por baseline."""
    lines = text.splitlines(keepends=True)
    in_resources = False
    resources_indent = -1
    current_section: str | None = None
    section_indent = -1

    for i, line in enumerate(lines):
        stripped = line.rstrip("\n").rstrip()
        if not stripped:
            continue

        # Cantidad de espacios al inicio
        indent = len(line) - len(line.lstrip(" "))

        if not in_resources:
            if re.match(r"^\s*resources\s*:\s*$", line):
                in_resources = True
                resources_indent = indent
                current_section = None
                section_indent = -1
            continue

        # Si encontramos una linea con indent <= resources_indent y no es
        # blank/comentario, salimos del bloque resources.
        if indent <= resources_indent:
            in_resources = False
            current_section = None
            continue

        # Dentro del bloque resources: detectar requests:/limits:
        sec_match = re.match(r"^\s*(requests|limits)\s*:\s*$", line)
        if sec_match:
            current_section = sec_match.group(1)
            section_indent = indent
            continue

        # Dentro de una subseccion (requests/limits): reescribir cpu/memory
        if current_section and indent > section_indent:
            leaf_match = re.match(
                r"^(?P<lead>\s*(?P<key>cpu|memory)\s*:\s*)['\"]?(?P<value>[^'\"\s#]+)['\"]?",
                line,
            )
            if leaf_match:
                key = leaf_match.group("key")
                value = leaf_match.group("value").strip()
                expected = HELM_CAPACITY_BASELINE_FIX.get(f"{current_section}.{key}")
                if expected and value != expected:
                    # Preservar el resto de la linea (comentarios, newline)
                    tail = line[leaf_match.end():]
                    lines[i] = f"{leaf_match.group('lead')}{expected}{tail}"
        elif indent <= section_indent:
            current_section = None

    return "".join(lines)


# ---------------------------------------------------------------------------
# Regla 9j — error.recurso / error.componente usan el nombre del componente
# MIGRADO, no el nombre legacy IIB/WAS/ORQ. QA del banco (ticket BTHCCC-6826,
# 2026-05) reporto como HIGH cualquier response que traiga el nombre legacy.
# Aplica a WAS, BUS y ORQ.
# ---------------------------------------------------------------------------


_LEGACY_NAME_RE_FOR_FIX = re.compile(
    r"(?P<setter>setRecurso|setComponente)\s*\(\s*\""
    r"(?P<legacy>(?:WS|ORQ|UMP)[A-Za-z]*\d{3,})"
    r"(?P<tail>(?:/[^\"]*)?)\"",
    re.IGNORECASE,
)


def _read_migrated_component_name(project_root: Path) -> str | None:
    """Read the migrated component name from application.yml or repo folder."""
    app_name = _read_spring_application_name(project_root)
    if app_name and re.match(r"^[a-z]{3}-msa-sp-", app_name.lower()):
        return app_name
    if re.match(r"^[a-z]{3}-msa-sp-", project_root.name.lower()):
        return project_root.name
    return None


def fix_legacy_name_in_error_payload(project_root: Path) -> BankAutofixResult:
    """Reemplaza `setRecurso("WSClientesNNNN/Op")` y `setComponente("WSClientesNNNN")`
    por el componente migrado.

    Solo aplica el fix si:
    - `spring.application.name` o la carpeta exponen `<ns>-msa-sp-<svc>`.
    - El legacy hallado (case-insensitive) coincide con el sufijo del migrado.
      Ej: `WSClientes0011` en setRecurso, migrado `tnd-msa-sp-wsclientes0011`
      -> match (los digitos+stem coinciden). Si el legacy no matchea con el
      migrado, no reemplaza (puede ser un upstream legitimo en logs).
    """
    result = BankAutofixResult(rule="9j", applied=False)
    component_name = _read_migrated_component_name(project_root)
    if not component_name:
        result.notes = "sin spring.application.name/carpeta <ns>-msa-sp-<svc>"
        return result

    migrated_short = component_name.rsplit("-msa-sp-", 1)[-1].lower()

    java_files: list[Path] = []
    for java in project_root.rglob("*.java"):
        if any(p.lower() in {"test", "build", ".git"} for p in java.parts):
            continue
        java_files.append(java)

    modified_files: list[Path] = []
    for java in java_files:
        try:
            text = java.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "setRecurso" not in text and "setComponente" not in text:
            continue

        def _replace(match: re.Match) -> str:
            setter = match.group("setter")
            legacy = match.group("legacy")
            tail = match.group("tail")
            # Solo reemplazar si el legacy hace referencia al servicio migrado.
            # Comparamos por el sufijo del componente migrado (ej. wsclientes0011)
            # contra el legacy normalizado (ej. WSClientes0011 -> wsclientes0011).
            if legacy.lower() != migrated_short:
                return match.group(0)  # legacy distinto: no es bug, no tocar
            new_value = f'"{component_name}{tail}"'
            return f"{setter}({new_value}"

        new_text = _LEGACY_NAME_RE_FOR_FIX.sub(_replace, text)
        if new_text != text:
            java.write_text(new_text, encoding="utf-8")
            modified_files.append(java)
            result.changes.append(
                f"{java.relative_to(project_root)}: nombre legacy reemplazado por '{component_name}'"
            )

    if modified_files:
        result.applied = True
        result.files_modified = modified_files
    else:
        result.notes = "ningun setter de recurso/componente con nombre legacy"
    return result


# ---------------------------------------------------------------------------
# Regla 5.6.5 — BusinessValidationException nunca se mapea a FATAL.
# QA del banco (informe WSClientes0011, 2026-05) reporto que el migrado usaba
# FATAL para validaciones de negocio, perdiendo la diferenciacion legacy.
# El autofix detecta el patron y lo rerutea a buildErrorResponse / ERROR_TYPE_ERROR.
# ---------------------------------------------------------------------------


# Patron a reescribir dentro de la ventana de un catch BVE:
#   buildFatalResponse / buildBancsErrorResponse / setTipo("FATAL") /
#   ERROR_TYPE_FATAL  ->  equivalente con ERROR.
_BVE_BUILDER_MAP = {
    "buildFatalResponse": "buildErrorResponse",
    "buildBancsErrorResponse": "buildErrorResponse",
    'setTipo("FATAL")': 'setTipo("ERROR")',
    "ERROR_TYPE_FATAL": "ERROR_TYPE_ERROR",
}

_BVE_CATCH_RE = re.compile(
    r"catch\s*\(\s*BusinessValidationException\b|"
    r"instanceof\s+BusinessValidationException\b",
)


def fix_bve_not_fatal(project_root: Path) -> BankAutofixResult:
    """Reescribe rutas FATAL aplicadas a `BusinessValidationException` para que
    usen el equivalente ERROR. Solo opera dentro de la ventana de 6 lineas
    posterior al catch para no tocar codigo no relacionado.

    Reemplazos:
    - `buildFatalResponse(...)`        -> `buildErrorResponse(...)`
    - `buildBancsErrorResponse(...)`   -> `buildErrorResponse(...)`
    - `setTipo("FATAL")`               -> `setTipo("ERROR")`
    - `ERROR_TYPE_FATAL`               -> `ERROR_TYPE_ERROR`
    """
    result = BankAutofixResult(rule="5.6.5", applied=False)

    java_files: list[Path] = []
    for java in project_root.rglob("*.java"):
        if any(p.lower() in {"test", "build", ".git"} for p in java.parts):
            continue
        java_files.append(java)

    modified_files: list[Path] = []
    for java in java_files:
        try:
            text = java.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "BusinessValidationException" not in text:
            continue

        lines = text.splitlines(keepends=True)
        changed = False
        i = 0
        while i < len(lines):
            if _BVE_CATCH_RE.search(lines[i]):
                # Operar sobre la ventana [i, i+6)
                end = min(len(lines), i + 6)
                for j in range(i, end):
                    original = lines[j]
                    new = original
                    for old_token, new_token in _BVE_BUILDER_MAP.items():
                        if old_token in new:
                            new = new.replace(old_token, new_token)
                    if new != original:
                        lines[j] = new
                        changed = True
                i = end  # saltar la ventana ya procesada
            else:
                i += 1

        if changed:
            java.write_text("".join(lines), encoding="utf-8")
            modified_files.append(java)
            result.changes.append(
                f"{java.relative_to(project_root)}: BusinessValidationException reruteada a ERROR"
            )

    if modified_files:
        result.applied = True
        result.files_modified = modified_files
    else:
        result.notes = "BusinessValidationException no se mapea a FATAL en ningun archivo"
    return result


# ---------------------------------------------------------------------------
# Regla 9h.2 — JAVA_OPTIONS baseline oficial en Helm env. Capacity Banco
# Pichincha; ajuste 2026-07: MaxRAMPercentage 70->60 y sin InitialRAMPercentage.
# Aplica a los 3 helms.
# ---------------------------------------------------------------------------


HELM_JAVA_OPTIONS_BASELINE_FIX: str = (
    "-XX:MaxRAMPercentage=60.0 "
    "-XX:+UseStringDeduplication -XX:+UseG1GC"
)


def _java_options_token_counter(value: str) -> Counter[str]:
    return Counter(part for part in value.split(" ") if part)


def _java_options_has_invalid_chars(value: str) -> bool:
    return any(ord(ch) > 0x7E or (ch.isspace() and ch != " ") for ch in value)


def fix_helm_java_options(project_root: Path) -> BankAutofixResult:
    """Si la env var JAVA_OPTIONS ya existe en helm/<env>.yml con un valor
    distinto al baseline oficial, lo reescribe. NO inyecta la env var si
    falta (modificar la lista `env:` sin contexto es propenso a romper el
    chart); en ese caso el check 7.5f la reporta como handoff manual.

    Idempotente. Skip si helm/ no existe o esta vacio.
    """
    result = BankAutofixResult(rule="9h.2", applied=False)
    helm_dir = project_root / "helm"
    if not helm_dir.exists():
        result.notes = "helm/ no existe en el proyecto"
        return result

    helm_files = [
        f for f in helm_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".yml", ".yaml"}
    ]
    if not helm_files:
        result.notes = "helm/ vacio"
        return result

    expected_tokens = _java_options_token_counter(HELM_JAVA_OPTIONS_BASELINE_FIX)
    modified_files: list[Path] = []
    for f in helm_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        original = text

        lines = text.splitlines(keepends=True)
        # Buscar cada bloque `name: JAVA_OPTIONS` seguido (en hasta 4 lineas)
        # de un `value:` y reemplazar el valor si difiere.
        for i, line in enumerate(lines):
            if not re.match(
                r"^\s*(?:-\s*)?name\s*:\s*['\"]?JAVA_OPTIONS['\"]?\s*(#.*)?$",
                line,
            ):
                continue
            for j in range(i + 1, min(len(lines), i + 5)):
                candidate = lines[j]
                stripped = candidate.strip()
                if not stripped:
                    continue
                m = re.match(
                    r"^(?P<indent>\s*)value\s*:\s*(?P<quote>['\"]?)"
                    r"(?P<value>[^'\"]*?)(?P=quote)\s*(?P<comment>#.*)?$",
                    candidate.rstrip("\n"),
                )
                if m:
                    actual_value = m.group("value").strip()
                    actual_tokens = _java_options_token_counter(actual_value)
                    if (
                        actual_tokens != expected_tokens
                        or _java_options_has_invalid_chars(actual_value)
                    ):
                        comment = m.group("comment") or ""
                        comment_part = (
                            f" {comment}" if comment else ""
                        )
                        # Conservar la indentacion y el tipo de comilla original
                        # (defaulting a comillas dobles si no habia).
                        quote = m.group("quote") or '"'
                        lines[j] = (
                            f"{m.group('indent')}value: "
                            f"{quote}{HELM_JAVA_OPTIONS_BASELINE_FIX}{quote}"
                            f"{comment_part}\n"
                        )
                    break
                if re.match(r"^[-\w].*?:", stripped):
                    # Llegamos a otra key sin haber visto value: -> no tocar
                    break

        new_text = "".join(lines)
        if new_text != original:
            f.write_text(new_text, encoding="utf-8")
            modified_files.append(f)
            result.changes.append(
                f"{f.relative_to(project_root)}: JAVA_OPTIONS value alineado al baseline"
            )

    if modified_files:
        result.applied = True
        result.files_modified = modified_files
    else:
        result.notes = (
            "JAVA_OPTIONS ya alineado al baseline o no declarado en ningun helm "
            "(si falta, declararlo manualmente en env: — el autofix no la inyecta)"
        )
    return result


# ---------------------------------------------------------------------------
# Regla 8.11 — Deps de metricas Prometheus para KEDA. Directiva capacity Banco
# Pichincha 2026-07: KEDA escala por http_server_requests_seconds_count via el
# ServiceMonitor que expone /actuator/prometheus. Aplica a todos los tipos.
# ---------------------------------------------------------------------------


# (nombre de artefacto -> linea gradle a inyectar si falta). El nombre se usa
# para deteccion idempotente; robusto a la version que fije el BOM.
_PROMETHEUS_GRADLE_DEPS: list[tuple[str, str]] = [
    (
        "micrometer-registry-prometheus",
        "    implementation 'io.micrometer:micrometer-registry-prometheus'",
    ),
    (
        "simpleclient_hotspot",
        "    implementation 'io.prometheus:simpleclient_hotspot:0.16.0'",
    ),
    (
        "simpleclient_common",
        "    implementation 'io.prometheus:simpleclient_common:0.16.0'",
    ),
]


def fix_add_prometheus_deps(project_root: Path) -> BankAutofixResult:
    """Inyecta las 3 deps de metricas Prometheus que KEDA necesita, si faltan.

    Deteccion por nombre de artefacto (idempotente). Solo toca el build.gradle
    raiz del microservicio (donde viven sus dependencias). Si no hay bloque
    `dependencies {`, lo crea al final del archivo.
    """
    result = BankAutofixResult(rule="8.11", applied=False)

    root_gradle = project_root / "build.gradle"
    root_gradle_kts = project_root / "build.gradle.kts"
    if root_gradle.exists():
        target = root_gradle
    elif root_gradle_kts.exists():
        target = root_gradle_kts
    else:
        result.notes = "no se encontro build.gradle en la raiz"
        return result

    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        result.notes = "no se pudo leer build.gradle"
        return result

    missing = [(name, line) for name, line in _PROMETHEUS_GRADLE_DEPS if name not in text]
    if not missing:
        result.notes = "deps de metricas Prometheus ya presentes"
        return result

    block = "\n".join(line for _, line in missing)
    m = re.search(r"dependencies\s*\{", text)
    if not m:
        new_text = (
            text.rstrip()
            + "\n\ndependencies {\n"
            + "    // Prometheus metrics for KEDA autoscaling\n"
            + block
            + "\n}\n"
        )
    else:
        insert_pos = m.end()
        new_text = (
            text[:insert_pos]
            + "\n    // Prometheus metrics for KEDA autoscaling\n"
            + block
            + text[insert_pos:]
        )

    target.write_text(new_text, encoding="utf-8")
    result.applied = True
    result.files_modified = [target]
    result.changes.append(
        f"{target.relative_to(project_root)}: +"
        + ", ".join(name for name, _ in missing)
        + " (metricas Prometheus para KEDA)"
    )
    return result


# ---------------------------------------------------------------------------
# Regla 8.12 — Version del plugin de peer review del banco. El task
# `architectureReview` bloquea el PR en Azure y los scaffolds viejos de Fabrics
# traen una version anterior a la vigente.
# ---------------------------------------------------------------------------


_PEER_REVIEW_PLUGIN_VERSION_RE = re.compile(
    r"(id\s*(?:\(\s*[\"']" + re.escape(PEER_REVIEW_PLUGIN_ID) + r"[\"']\s*\)"
    r"|[\"']" + re.escape(PEER_REVIEW_PLUGIN_ID) + r"[\"'])"
    r"\s*version\s*(?:\(\s*)?[\"'])([^\"']+)([\"'])",
)


def fix_peer_review_plugin_version(project_root: Path) -> BankAutofixResult:
    """Actualiza el plugin de peer review a PEER_REVIEW_PLUGIN_VERSION.

    Solo reescribe una declaracion **existente**: si el plugin no esta en el
    bloque `plugins {}` NO lo inyecta. Agregar un `id` que Gradle no pueda
    resolver (el plugin vive en el repo interno del banco, declarado en
    `settings.gradle`) romperia el build entero — peor que el FAIL del check.
    En ese caso el check 8.12 queda en HIGH para resolucion manual.

    Idempotente: no toca versiones ya iguales o mayores a la vigente.
    """
    result = BankAutofixResult(rule="8.12", applied=False)

    targets = [
        f
        for f in (project_root / "build.gradle", project_root / "build.gradle.kts")
        if f.exists()
    ]
    if not targets:
        result.notes = "no se encontro build.gradle en la raiz"
        return result

    modified: list[Path] = []
    for target in targets:
        try:
            text = target.read_text(encoding="utf-8")
        except OSError:
            continue

        found_old: list[str] = []

        def _bump(match: re.Match[str], _found: list[str] = found_old) -> str:
            current = match.group(2)
            if not is_version_lower(current, PEER_REVIEW_PLUGIN_VERSION):
                return match.group(0)
            _found.append(current)
            return f"{match.group(1)}{PEER_REVIEW_PLUGIN_VERSION}{match.group(3)}"

        new_text = _PEER_REVIEW_PLUGIN_VERSION_RE.sub(_bump, text)
        if not found_old:
            continue

        target.write_text(new_text, encoding="utf-8")
        modified.append(target)
        result.changes.append(
            f"{target.relative_to(project_root)}: plugin peer-review "
            + ", ".join(found_old)
            + f" -> {PEER_REVIEW_PLUGIN_VERSION}"
        )

    if not modified:
        result.notes = (
            f"plugin peer-review ya en {PEER_REVIEW_PLUGIN_VERSION} o superior, "
            "o no declarado en el bloque plugins (se agrega a mano)"
        )
        return result

    result.applied = True
    result.files_modified = modified
    return result


# ---------------------------------------------------------------------------
# Regla 8.7 / Snyk 2026-05 — Eliminar pins manuales de io.netty:* del bloque
# `dependencyManagement { dependencies { ... } }`. Los pins manuales se quedan
# atras al proximo CVE (era exactamente el bug del template viejo con
# netty-codec-http:4.1.132.Final).
#
# Excepcion oficial (v0.27.0): proyectos WebFlux pueden mantener el pin
# `io.netty:*:4.1.133.Final` porque cierra los CVEs 2026-05 del netty-codec-http
# sin esperar al proximo BOM. Solo aplica a WebFlux
# (`spring-boot-starter-webflux`); MVC/SOAP siguen sin pin manual.
# ---------------------------------------------------------------------------


_NETTY_PIN_LINE_RE = re.compile(
    r"^\s*(?:dependency|implementation|runtimeOnly|compileOnly)\s+"
    r"['\"]io\.netty:[^:]+:[^'\"]+['\"][^\n]*\n?",
    re.MULTILINE,
)
_NETTY_ALLOWED_PIN_RE = re.compile(
    r"['\"]io\.netty:[^:]+:" + re.escape(NETTY_WEBFLUX_ALLOWED_VERSION) + r"['\"]",
)


def fix_remove_netty_pin(project_root: Path) -> BankAutofixResult:
    """Elimina pins manuales de `io.netty:*:VERSION` del `build.gradle`.

    Solo opera sobre lineas dentro de bloques `dependencyManagement`, igual que
    el checker 8.7. Mantiene el resto del archivo intacto. Idempotente. Skip si
    no hay build.gradle. En proyectos WebFlux preserva el pin oficial
    `io.netty:*:4.1.133.Final`.
    """
    result = BankAutofixResult(rule="8.7", applied=False)
    gradle_files = [
        f
        for f in (
            project_root / "build.gradle",
            project_root / "build.gradle.kts",
        )
        if f.exists()
    ]
    if not gradle_files:
        result.notes = "no se encontro build.gradle"
        return result

    is_webflux = any(
        "spring-boot-starter-webflux" in f.read_text(encoding="utf-8", errors="replace")
        for f in gradle_files
    )

    modified_files: list[Path] = []
    for f in gradle_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "io.netty:" not in text:
            continue

        new_text, n = _remove_netty_pins_from_dependency_management(
            text, allow_webflux_pin=is_webflux
        )
        if n > 0 and new_text != text:
            # Limpiar lineas blancas dobles que pueden haber quedado
            new_text = re.sub(r"\n{3,}", "\n\n", new_text)
            f.write_text(new_text, encoding="utf-8")
            modified_files.append(f)
            result.changes.append(
                f"{f.relative_to(project_root)}: removed {n} io.netty:* pin(s)"
            )

    if modified_files:
        result.applied = True
        result.files_modified = modified_files
    else:
        if is_webflux:
            result.notes = (
                "no se encontraron pins de io.netty:* a remover (WebFlux: "
                f"pin {NETTY_WEBFLUX_ALLOWED_VERSION} permitido)"
            )
        else:
            result.notes = "no se encontraron pins de io.netty:* en build.gradle"
    return result


def _remove_netty_pins_from_dependency_management(
    text: str, *, allow_webflux_pin: bool = False
) -> tuple[str, int]:
    """Remove active io.netty pins only while inside dependencyManagement.

    Si `allow_webflux_pin=True`, preserva los pins con version
    `4.1.133.Final` (CVE-fix oficial 2026-05).
    """
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    removed = 0
    in_dep_mgmt = False
    brace_depth = 0
    dep_mgmt_brace = -1

    for raw_line in lines:
        stripped = raw_line.strip()
        opens = raw_line.count("{")
        closes = raw_line.count("}")
        is_comment = not stripped or stripped.startswith(("//", "/*", "*"))

        if (
            not in_dep_mgmt
            and not is_comment
            and "dependencyManagement" in stripped
            and "{" in raw_line
        ):
            in_dep_mgmt = True
            dep_mgmt_brace = brace_depth + opens
            output.append(raw_line)
            brace_depth += opens - closes
            continue

        if in_dep_mgmt and not is_comment and _NETTY_PIN_LINE_RE.match(raw_line):
            if allow_webflux_pin and _NETTY_ALLOWED_PIN_RE.search(raw_line):
                output.append(raw_line)
                brace_depth += opens - closes
                if brace_depth < dep_mgmt_brace:
                    in_dep_mgmt = False
                    dep_mgmt_brace = -1
                continue
            removed += 1
            brace_depth += opens - closes
            if brace_depth < dep_mgmt_brace:
                in_dep_mgmt = False
                dep_mgmt_brace = -1
            continue

        output.append(raw_line)
        brace_depth += opens - closes
        if in_dep_mgmt and brace_depth < dep_mgmt_brace:
            in_dep_mgmt = False
            dep_mgmt_brace = -1

    return "".join(output), removed


# ---------------------------------------------------------------------------
# Regla 8.8 — Arbol Netty completo pineado a la version permitida en WebFlux.
#
# El BOM de Spring Boot 3.5.x trae `io.netty:*:4.1.121.Final` (vulnerable). En
# WebFlux hay que pinear el arbol core de Netty (NETTY_CORE_MODULES)
# a NETTY_WEBFLUX_ALLOWED_VERSION con DOBLE mecanismo:
#   - `dependencyManagement { dependencies { dependency '...' } }`
#   - `configurations.all { resolutionStrategy { force '...' } }`
# El `force` es necesario porque dependencyManagement no siempre gana sobre
# transitivas (lib-bnc, el propio BOM). Validado en WSClientes0013 (2026-05-29):
# pinear solo `netty-codec*` dejaba `netty-handler-proxy` y otros transitivos en
# version vulnerable (9 CVEs). NO bumpear a 4.2.x: rompe Reactor Netty
# (StacklessClosedChannelException en AbstractChannel$AbstractUnsafe.ensureOpen).
# ---------------------------------------------------------------------------

_NETTY_DEP_LINE_RE = re.compile(r"^\s*dependency\s+['\"]io\.netty:")
_NETTY_FORCE_LINE_RE = re.compile(r"^\s*force\s+['\"]io\.netty:")
_NETTY_GA_RE = re.compile(r"io\.netty:(?P<mod>[A-Za-z0-9._\-]+):(?P<ver>[A-Za-z0-9._\-]+)")


def _netty_modules_pinned(text: str, line_re: re.Pattern[str]) -> dict[str, str]:
    """Mapa {modulo: version} de lineas io.netty que matchean `line_re`
    (`dependency '...'` o `force '...'`), ignorando comentarios."""
    found: dict[str, str] = {}
    for raw in text.splitlines():
        if raw.strip().startswith(("//", "/*", "*")):
            continue
        if not line_re.match(raw):
            continue
        m = _NETTY_GA_RE.search(raw)
        if m:
            found.setdefault(m.group("mod"), m.group("ver"))
    return found


def _insert_after_last_match(
    lines: list[str],
    anchor_re: re.Pattern[str],
    modules: list[str],
    keyword: str,
    version: str,
) -> list[str]:
    """Inserta `<keyword> 'io.netty:<mod>:<version>'` por cada modulo, justo
    despues de la ultima linea (no comentario) que matchea `anchor_re`,
    replicando su indentacion. Si no hay ancla, devuelve `lines` sin tocar."""
    last_idx = -1
    indent = "        "
    for i, raw in enumerate(lines):
        if raw.strip().startswith(("//", "/*", "*")):
            continue
        if anchor_re.match(raw):
            last_idx = i
            indent = raw[: len(raw) - len(raw.lstrip())]
    if last_idx == -1:
        return lines
    additions = [f"{indent}{keyword} 'io.netty:{mod}:{version}'\n" for mod in modules]
    return lines[: last_idx + 1] + additions + lines[last_idx + 1 :]


def _append_resolution_force_block(text: str, modules: list[str], version: str) -> str:
    """Agrega al final del archivo un bloque
    `configurations.all { resolutionStrategy { force ... } }` con los modulos
    dados. Gradle acumula multiples `configurations.all {}`, asi que es seguro
    aunque ya exista otro."""
    forces = "\n".join(f"        force 'io.netty:{mod}:{version}'" for mod in modules)
    block = (
        "\n"
        "configurations.all {\n"
        "    resolutionStrategy {\n"
        "        // Pin completo del arbol Netty (CVE-fix; el BOM de Spring Boot\n"
        "        // 3.5.x trae io.netty 4.1.121.Final vulnerable). NO bumpear a\n"
        "        // 4.2.x: rompe Reactor Netty (StacklessClosedChannelException).\n"
        f"{forces}\n"
        "    }\n"
        "}\n"
    )
    if not text.endswith("\n"):
        text += "\n"
    return text + block


def fix_netty_full_tree_pin(project_root: Path) -> BankAutofixResult:
    """En proyectos WebFlux que YA pinean `io.netty` en la version permitida,
    asegura que los modulos core (`NETTY_CORE_MODULES`) esten pineados a
    `NETTY_WEBFLUX_ALLOWED_VERSION` con doble mecanismo (dependencyManagement
    `dependency` + resolutionStrategy `force`).

    Idempotente. Solo AGREGA modulos faltantes; no toca pins existentes. Skip si:
    no hay build.gradle, no es WebFlux, o no hay pin io.netty en la version
    permitida en `dependencyManagement` (eso lo gobierna el Check/autofix 8.7).
    """
    result = BankAutofixResult(rule="8.8", applied=False)
    gradle_files = [
        f
        for f in (project_root / "build.gradle", project_root / "build.gradle.kts")
        if f.exists()
    ]
    if not gradle_files:
        result.notes = "no se encontro build.gradle"
        return result

    is_webflux = any(
        "spring-boot-starter-webflux" in f.read_text(encoding="utf-8", errors="replace")
        for f in gradle_files
    )
    if not is_webflux:
        result.notes = "no es WebFlux; el arbol Netty solo se pinea en WebFlux"
        return result

    modified: list[Path] = []
    for f in gradle_files:
        text = f.read_text(encoding="utf-8", errors="replace")
        dep_modules = _netty_modules_pinned(text, _NETTY_DEP_LINE_RE)
        # Solo completar cuando ya hay un pin en la version permitida; si la
        # version es otra (4.2.x, 4.1.132...) lo resuelve el Check/autofix 8.7.
        if NETTY_WEBFLUX_ALLOWED_VERSION not in dep_modules.values():
            continue
        version = NETTY_WEBFLUX_ALLOWED_VERSION
        force_modules = _netty_modules_pinned(text, _NETTY_FORCE_LINE_RE)
        missing_dep = [m for m in NETTY_CORE_MODULES if m not in dep_modules]
        missing_force = [m for m in NETTY_CORE_MODULES if m not in force_modules]
        if not missing_dep and not missing_force:
            continue

        new_text = text
        if missing_dep:
            lines = new_text.splitlines(keepends=True)
            lines = _insert_after_last_match(
                lines, _NETTY_DEP_LINE_RE, missing_dep, "dependency", version
            )
            new_text = "".join(lines)
        if missing_force:
            if force_modules:
                lines = new_text.splitlines(keepends=True)
                lines = _insert_after_last_match(
                    lines, _NETTY_FORCE_LINE_RE, missing_force, "force", version
                )
                new_text = "".join(lines)
            else:
                new_text = _append_resolution_force_block(
                    new_text, missing_force, version
                )

        if new_text != text:
            f.write_text(new_text, encoding="utf-8")
            modified.append(f)
            bits = []
            if missing_dep:
                bits.append(f"+{len(missing_dep)} dependency")
            if missing_force:
                bits.append(f"+{len(missing_force)} force")
            result.changes.append(
                f"{f.relative_to(project_root)}: arbol Netty completado "
                f"({', '.join(bits)}) en {version}"
            )

    if modified:
        result.applied = True
        result.files_modified = modified
    else:
        result.notes = "arbol Netty ya completo, o sin pin base en la version permitida"
    return result


# ---------------------------------------------------------------------------
# Regla 8.10 — Pins de seguridad NO-Netty del stack WebFlux (Snyk 2026-06).
#
# Mismo Snyk report que el arbol Netty (8.8) para servicios WebFlux: ademas del
# arbol io.netty hay que overridear micrometer-core, reactor-netty-http,
# spring-retry, spring-kafka (como `dependency`) y spring-framework-bom (como
# `mavenBom` import). SOLO WebFlux (BUS REST + ORQ): reactor-netty y spring-kafka
# no existen en MVC/SOAP. Gated igual que 8.8 (netty ya pineado en la version
# permitida) para mover toda la remediacion WebFlux como una unidad y garantizar
# que existe el bloque `dependencyManagement` donde insertar.
# ---------------------------------------------------------------------------

_DEP_LINE_ANY_RE = re.compile(
    r"^\s*dependency\s+['\"](?P<ga>[^:'\"]+:[^:'\"]+):(?P<ver>[^'\"]+)['\"]"
)
_MAVENBOM_LINE_RE = re.compile(
    r"^\s*mavenBom\s+['\"](?P<ga>[^:'\"]+:[^:'\"]+):(?P<ver>[^'\"]+)['\"]"
)
_DEP_ANCHOR_RE = re.compile(r"^\s*dependency\s+['\"]")
_MAVENBOM_ANCHOR_RE = re.compile(r"^\s*mavenBom\s+['\"]")
_IMPORTS_OPEN_RE = re.compile(r"^\s*imports\s*\{")
_DEP_MGMT_OPEN_RE = re.compile(r"^\s*dependencyManagement\s*\{")


def _is_gradle_comment(raw: str) -> bool:
    return raw.lstrip().startswith(("//", "/*", "*"))


def _coord_versions(text: str, line_re: re.Pattern[str]) -> dict[str, str]:
    """{group:artifact: version} de lineas `dependency`/`mavenBom` no comentadas."""
    found: dict[str, str] = {}
    for raw in text.splitlines():
        if _is_gradle_comment(raw):
            continue
        m = line_re.match(raw)
        if m:
            found.setdefault(m.group("ga"), m.group("ver"))
    return found


def _replace_coord_version(
    text: str, line_re: re.Pattern[str], coord: str, version: str, keyword: str
) -> tuple[str, bool]:
    """Reemplaza la version de una linea `<keyword> 'coord:oldver'` -> version."""
    out: list[str] = []
    changed = False
    for raw in text.splitlines(keepends=True):
        m = line_re.match(raw)
        if m and m.group("ga") == coord and not _is_gradle_comment(raw):
            indent = raw[: len(raw) - len(raw.lstrip())]
            out.append(f"{indent}{keyword} '{coord}:{version}'\n")
            changed = True
        else:
            out.append(raw)
    return "".join(out), changed


def _insert_generic_deps_after_last(
    text: str, ga_v_pairs: list[tuple[str, str]]
) -> tuple[str, bool]:
    """Inserta `dependency 'ga:ver'` despues de la ultima linea `dependency '...'`
    (no comentario). Sin ancla -> no toca."""
    lines = text.splitlines(keepends=True)
    last_idx = -1
    indent = "        "
    for i, raw in enumerate(lines):
        if _is_gradle_comment(raw):
            continue
        if _DEP_ANCHOR_RE.match(raw):
            last_idx = i
            indent = raw[: len(raw) - len(raw.lstrip())]
    if last_idx == -1:
        return text, False
    additions = [f"{indent}dependency '{ga}:{ver}'\n" for ga, ver in ga_v_pairs]
    return "".join(lines[: last_idx + 1] + additions + lines[last_idx + 1 :]), True


def _ensure_maven_bom(text: str, coord: str, version: str) -> tuple[str, bool]:
    """Asegura `mavenBom 'coord:version'` en el bloque `imports {}` del
    `dependencyManagement`. Reemplaza si esta en otra version; lo crea si falta
    el `imports {}` (justo despues de `dependencyManagement {`)."""
    boms = _coord_versions(text, _MAVENBOM_LINE_RE)
    if boms.get(coord) == version:
        return text, False
    if coord in boms:  # version distinta -> reemplazar in place
        return _replace_coord_version(text, _MAVENBOM_LINE_RE, coord, version, "mavenBom")

    lines = text.splitlines(keepends=True)
    # 1) insertar despues del ultimo mavenBom existente
    last_bom = -1
    indent = "        "
    for i, raw in enumerate(lines):
        if _is_gradle_comment(raw):
            continue
        if _MAVENBOM_ANCHOR_RE.match(raw):
            last_bom = i
            indent = raw[: len(raw) - len(raw.lstrip())]
    if last_bom != -1:
        line = f"{indent}mavenBom '{coord}:{version}'\n"
        return "".join([*lines[: last_bom + 1], line, *lines[last_bom + 1 :]]), True
    # 2) sin mavenBom: insertar dentro del bloque `imports {`
    for i, raw in enumerate(lines):
        if _IMPORTS_OPEN_RE.match(raw):
            inner = raw[: len(raw) - len(raw.lstrip())] + "    "
            line = f"{inner}mavenBom '{coord}:{version}'\n"
            return "".join([*lines[: i + 1], line, *lines[i + 1 :]]), True
    # 3) sin imports: crear el bloque justo despues de `dependencyManagement {`
    for i, raw in enumerate(lines):
        if _DEP_MGMT_OPEN_RE.match(raw):
            base = raw[: len(raw) - len(raw.lstrip())] + "    "
            block = [
                f"{base}imports {{\n",
                f"{base}    mavenBom '{coord}:{version}'\n",
                f"{base}}}\n",
            ]
            return "".join(lines[: i + 1] + block + lines[i + 1 :]), True
    return text, False


def fix_webflux_security_pins(project_root: Path) -> BankAutofixResult:
    """En proyectos WebFlux que YA pinean Netty en la version permitida, asegura
    los pins de seguridad NO-Netty del mismo Snyk report (WEBFLUX_SECURITY_
    DEPENDENCY_PINS como `dependency` + spring-framework-bom como `mavenBom`).

    Idempotente. Inserta los faltantes y corrige versiones distintas. Skip si:
    no hay build.gradle, no es WebFlux, o Netty aun no esta pineado en la version
    permitida (eso lo gobierna 8.7/8.8 primero).
    """
    result = BankAutofixResult(rule="8.10", applied=False)
    gradle_files = [
        f
        for f in (project_root / "build.gradle", project_root / "build.gradle.kts")
        if f.exists()
    ]
    if not gradle_files:
        result.notes = "no se encontro build.gradle"
        return result

    is_webflux = any(
        "spring-boot-starter-webflux" in f.read_text(encoding="utf-8", errors="replace")
        for f in gradle_files
    )
    if not is_webflux:
        result.notes = "no es WebFlux; los pins de seguridad WebFlux solo aplican alli"
        return result

    modified: list[Path] = []
    for f in gradle_files:
        text = f.read_text(encoding="utf-8", errors="replace")
        # Gate: solo cuando Netty ya esta pineado en la version permitida (mismo
        # bloque dependencyManagement de la remediacion CVE WebFlux).
        netty_deps = _netty_modules_pinned(text, _NETTY_DEP_LINE_RE)
        if NETTY_WEBFLUX_ALLOWED_VERSION not in netty_deps.values():
            continue

        new_text = text
        changes: list[str] = []

        # 1) dependency pins (micrometer, reactor-netty, spring-retry, spring-kafka)
        deps = _coord_versions(new_text, _DEP_LINE_ANY_RE)
        to_insert: list[tuple[str, str]] = []
        for coord, version in WEBFLUX_SECURITY_DEPENDENCY_PINS.items():
            current = deps.get(coord)
            if current == version:
                continue
            if current is None:
                to_insert.append((coord, version))
            else:  # version distinta -> reemplazar in place
                new_text, did = _replace_coord_version(
                    new_text, _DEP_LINE_ANY_RE, coord, version, "dependency"
                )
                if did:
                    changes.append(f"{coord} {current}->{version}")
        if to_insert:
            new_text, did = _insert_generic_deps_after_last(new_text, to_insert)
            if did:
                changes.extend(f"+{ga}:{ver}" for ga, ver in to_insert)

        # 2) spring-framework-bom (mavenBom)
        new_text, did_bom = _ensure_maven_bom(
            new_text, SPRING_FRAMEWORK_BOM_COORD, SPRING_FRAMEWORK_BOM_VERSION
        )
        if did_bom:
            changes.append(f"mavenBom {SPRING_FRAMEWORK_BOM_COORD}:{SPRING_FRAMEWORK_BOM_VERSION}")

        if new_text != text:
            f.write_text(new_text, encoding="utf-8")
            modified.append(f)
            result.changes.append(
                f"{f.relative_to(project_root)}: pins WebFlux Snyk ({', '.join(changes)})"
            )

    if modified:
        result.applied = True
        result.files_modified = modified
    else:
        result.notes = (
            "pins de seguridad WebFlux ya presentes, o sin pin base de Netty "
            "(8.7/8.8 primero)"
        )
    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_bank_autofix(
    project_root: Path,
    *,
    rules: list[str] | None = None,
    description: str | None = None,
    owner: str | None = None,
    source_type: str | None = None,
    has_bancs: bool = False,
    requires_bancs: bool | None = None,
    service: str | None = None,
) -> list[BankAutofixResult]:
    """Corre los autofixes del banco. Devuelve resultados por regla.

    `rules` permite subset explicito, ej `["4", "7"]`. Default: todos.
    `service` fija el OLA para la Regla 8; si falta se autodetecta del proyecto.
    """
    wanted = (
        set(rules)
        if rules
        else {
            "4", "6", "7", "8", "8b", "9", "9j", "5.6.5",
            "9h.1", "9h.2", "8.7", "8.8", "8.10", "8.11", "8.12",
        }
    )
    if requires_bancs is None:
        requires_bancs = _requires_bancs_from_matrix(source_type, has_bancs)
    results: list[BankAutofixResult] = []
    if "4" in wanted:
        results.append(fix_add_bplogger_to_service(project_root))
    if "6" in wanted:
        results.append(fix_stringutils_to_native(project_root))
        results.append(fix_extract_inner_records_to_model(project_root))
    if "7" in wanted:
        results.append(fix_yml_remove_defaults(project_root))
    if "8" in wanted:
        results.append(
            fix_add_libbnc_dependency(
                project_root, requires_bancs=requires_bancs, service=service
            )
        )
    if "8b" in wanted:
        results.append(fix_bancs_autoconfigure_exclude(project_root))
    if "9" in wanted:
        results.append(
            fix_catalog_info_scaffold(
                project_root, description=description, owner=owner
            )
        )
    if "9j" in wanted:
        results.append(fix_legacy_name_in_error_payload(project_root))
    if "5.6.5" in wanted:
        results.append(fix_bve_not_fatal(project_root))
    if "9h.1" in wanted:
        results.append(fix_helm_capacity_baseline(project_root))
    if "9h.2" in wanted:
        results.append(fix_helm_java_options(project_root))
    if "8.7" in wanted:
        results.append(fix_remove_netty_pin(project_root))
    if "8.8" in wanted:
        results.append(fix_netty_full_tree_pin(project_root))
    if "8.10" in wanted:
        results.append(fix_webflux_security_pins(project_root))
    if "8.11" in wanted:
        results.append(fix_add_prometheus_deps(project_root))
    if "8.12" in wanted:
        results.append(fix_peer_review_plugin_version(project_root))
    return results
