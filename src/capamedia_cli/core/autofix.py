"""Autofix registry para checks HIGH/MEDIUM del checklist BPTPSRE.

Cada fix es deterministico (regex + edit, sin AI). El loop corre hasta
`max_iter` rondas o hasta que no queden HIGH+MEDIUM autofixeables.

Uso tipico desde `commands/check.py`:

    from capamedia_cli.core.autofix import run_autofix_loop
    from capamedia_cli.core.checklist_rules import run_all_blocks, CheckContext

    def rerun() -> list[CheckResult]:
        return run_all_blocks(CheckContext(migrated_path=root, legacy_path=legacy))

    report = run_autofix_loop(root, rerun)

Los fixes son conservadores: si el patron es ambiguo, NO se toca el archivo
y se deja que quede pendiente para revision humana (NEEDS_HUMAN).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from capamedia_cli.core.version_policy import (
    ACTUATOR_LIVENESS_PATH,
    ACTUATOR_PROBES_ENV_VAR,
    ACTUATOR_READINESS_PATH,
    SPRING_BOOT_BASELINE_VERSION,
    SPRING_BOOT_LEGACY_BASELINE_VERSION,
    is_version_lower,
    lib_event_logs_version,
    lib_trace_logger_coord,
    spring_boot_target_version,
)

# -- Constantes -------------------------------------------------------------

_SKIP_DIRS = {".git", "build", "target", ".gradle", ".idea", "node_modules"}

# Codigos backend oficiales del catalogo Banco Pichincha (ref catalogosBackend)
BACKEND_BANCS_APP = "00045"  # TX BANCS consumidas directo
BACKEND_IIB = "00638"  # IIB / Bus
BACKEND_DATAPOWER = "00640"  # DataPower

SUSPECT_BACKEND_VALUES = {"00000", "999", "0", "00"}


# -- Dataclasses ------------------------------------------------------------


@dataclass
class Violation:
    """Una violacion concreta del checklist que un fix puede intentar resolver."""

    check_id: str
    severity: str  # "high" | "medium" | "low"
    file: Path
    line: int
    message: str
    evidence: str


@dataclass
class AutofixResult:
    """Resultado de ejecutar un fix sobre una violacion."""

    applied: bool
    files_modified: list[Path] = field(default_factory=list)
    before: str = ""
    after: str = ""
    notes: str = ""


@dataclass
class AutofixReport:
    """Reporte consolidado de un loop de autofix."""

    iterations: int
    converged: bool
    applied_fixes: list[dict] = field(default_factory=list)
    remaining: list[dict] = field(default_factory=list)
    log_path: Path | None = None

    @property
    def needs_human(self) -> bool:
        return not self.converged

    @property
    def total_applied(self) -> int:
        return len(self.applied_fixes)


AutofixFn = Callable[[Path, Violation], AutofixResult]


# -- File helpers -----------------------------------------------------------


def _iter_java_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for f in root.rglob("*.java"):
        if any(part in _SKIP_DIRS for part in f.parts):
            continue
        files.append(f)
    return files


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _grep(root: Path, pattern: str) -> list[tuple[Path, int, str]]:
    matches: list[tuple[Path, int, str]] = []
    regex = re.compile(pattern)
    for f in _iter_java_files(root):
        for i, line in enumerate(_read(f).splitlines(), 1):
            if regex.search(line):
                matches.append((f, i, line.rstrip()))
    return matches


# -- Individual fixes -------------------------------------------------------


def fix_abstract_to_interface(root: Path, violation: Violation) -> AutofixResult:
    """1.3 - Convierte `public abstract class XxxPort` -> `public interface XxxPort`.

    Ajusta adapters/impls que extendian el port para usar `implements`.
    Deja intactas abstract classes que no terminen en `Port`.
    """
    modified: list[Path] = []
    before_samples: list[str] = []
    after_samples: list[str] = []

    port_pattern = re.compile(r"public\s+abstract\s+class\s+(\w+Port)\b")
    renamed_ports: set[str] = set()

    # Pass 1: convertir la declaracion del port
    for f in _iter_java_files(root):
        text = _read(f)
        if not text:
            continue
        m = port_pattern.search(text)
        if not m:
            continue
        port_name = m.group(1)
        new_text = port_pattern.sub(r"public interface \1", text)
        # Remover metodos abstractos -> firmas de interfaz: `public abstract T m(...)` -> `T m(...);`
        new_text = re.sub(
            r"public\s+abstract\s+([\w<>,\s\[\]]+?\s+\w+\s*\([^)]*\))\s*;",
            r"\1;",
            new_text,
        )
        if new_text != text:
            before_samples.append(m.group(0))
            after_samples.append(f"public interface {port_name}")
            _write(f, new_text)
            modified.append(f)
            renamed_ports.add(port_name)

    if not renamed_ports:
        return AutofixResult(
            applied=False,
            notes="no se encontro `public abstract class XxxPort` para convertir",
        )

    # Pass 2: adapters/impls que extendian -> ahora implementan
    for f in _iter_java_files(root):
        text = _read(f)
        if not text:
            continue
        new_text = text
        for port_name in renamed_ports:
            new_text = re.sub(
                rf"\bextends\s+{re.escape(port_name)}\b",
                f"implements {port_name}",
                new_text,
            )
        if new_text != text:
            _write(f, new_text)
            if f not in modified:
                modified.append(f)

    return AutofixResult(
        applied=True,
        files_modified=modified,
        before="\n".join(before_samples),
        after="\n".join(after_samples),
        notes=f"ports convertidos a interface: {sorted(renamed_ports)}",
    )


def fix_slf4j_to_bplogger(root: Path, violation: Violation) -> AutofixResult:
    """2.2 - Elimina `import org.slf4j.*` y reemplaza `@Slf4j` por `@BpLogger`.

    Si el archivo ya tenia @BpLogger, solo se limpia el import.
    Si declaraba `private static final Logger log = ...` se elimina esa linea.
    """
    modified: list[Path] = []
    before_samples: list[str] = []
    after_samples: list[str] = []

    slf4j_import = re.compile(r"^\s*import\s+org\.slf4j\.[\w.*]+\s*;\s*$", re.MULTILINE)
    slf4j_logger_decl = re.compile(
        r"^\s*private\s+static\s+final\s+(?:org\.slf4j\.)?Logger\s+\w+\s*=\s*LoggerFactory\.[^;]+;\s*$",
        re.MULTILINE,
    )
    slf4j_ann = re.compile(r"@Slf4j\b")
    lombok_slf4j_import = re.compile(
        r"^\s*import\s+lombok\.extern\.slf4j\.Slf4j\s*;\s*$", re.MULTILINE
    )

    for f in _iter_java_files(root):
        text = _read(f)
        if not text:
            continue
        has_slf4j_import = bool(slf4j_import.search(text)) or bool(lombok_slf4j_import.search(text))
        has_slf4j_ann = bool(slf4j_ann.search(text))
        if not (has_slf4j_import or has_slf4j_ann):
            continue

        new_text = text
        removed_sample = ""
        hit = slf4j_import.search(new_text) or lombok_slf4j_import.search(new_text)
        if hit:
            removed_sample = hit.group(0).strip()
        new_text = slf4j_import.sub("", new_text)
        new_text = lombok_slf4j_import.sub("", new_text)
        new_text = slf4j_logger_decl.sub("", new_text)

        if has_slf4j_ann:
            if "@BpLogger" in new_text:
                new_text = slf4j_ann.sub("", new_text)
            else:
                new_text = slf4j_ann.sub("@BpLogger", new_text)
            # Asegurar import de BpLogger
            if "@BpLogger" in new_text and "import com.pichincha.bp.traces" not in new_text:
                new_text = _inject_import(
                    new_text, "import com.pichincha.bp.traces.BpLogger;"
                )

        # Limpiar lineas vacias consecutivas que pudo dejar el borrado
        new_text = re.sub(r"\n{3,}", "\n\n", new_text)

        if new_text != text:
            _write(f, new_text)
            modified.append(f)
            before_samples.append(removed_sample or "@Slf4j")
            after_samples.append("(removed) / @BpLogger")

    if not modified:
        return AutofixResult(applied=False, notes="no se encontro slf4j para migrar")

    return AutofixResult(
        applied=True,
        files_modified=modified,
        before="\n".join(before_samples[:3]),
        after="\n".join(after_samples[:3]),
        notes=f"slf4j limpiado en {len(modified)} archivo(s)",
    )


def fix_lombok_slf4j_removal(root: Path, violation: Violation) -> AutofixResult:
    """2.2 (complemento) - Solo remueve `@Slf4j` + su import, sin agregar BpLogger.

    Util cuando no hay alternativa clara (por ejemplo clases utilitarias
    que no necesitan el logger del harness). Mas conservador que
    fix_slf4j_to_bplogger.
    """
    modified: list[Path] = []
    before_samples: list[str] = []

    slf4j_ann = re.compile(r"^\s*@Slf4j\b.*$", re.MULTILINE)
    slf4j_import = re.compile(
        r"^\s*import\s+lombok\.extern\.slf4j\.Slf4j\s*;\s*$", re.MULTILINE
    )

    for f in _iter_java_files(root):
        text = _read(f)
        if not text:
            continue
        ann_hit = slf4j_ann.search(text)
        imp_hit = slf4j_import.search(text)
        if not (ann_hit or imp_hit):
            continue
        new_text = slf4j_ann.sub("", text) if ann_hit else text
        new_text = slf4j_import.sub("", new_text) if imp_hit else new_text
        new_text = re.sub(r"\n{3,}", "\n\n", new_text)
        if new_text != text:
            _write(f, new_text)
            modified.append(f)
            if ann_hit:
                before_samples.append(ann_hit.group(0).strip())

    if not modified:
        return AutofixResult(applied=False, notes="no se encontro @Slf4j para remover")

    return AutofixResult(
        applied=True,
        files_modified=modified,
        before="\n".join(before_samples[:3]),
        after="(removed)",
        notes=f"@Slf4j removido en {len(modified)} archivo(s)",
    )


def fix_bancs_exception_wrapping(root: Path, violation: Violation) -> AutofixResult:
    """5.1 - Envuelve RuntimeException en BancsOperationException en `BancsClientHelper`.

    Agrega un `catch (RuntimeException e)` al metodo principal del helper si no
    existe ninguno. Busca un `try { ... } catch (...)` y le injecta el catch
    adicional antes del primer catch existente.
    """
    helpers = [
        f for f in _iter_java_files(root)
        if "BancsClientHelper" in f.name or "BancsHelper" in f.name
    ]
    if not helpers:
        return AutofixResult(applied=False, notes="no se encontro BancsClientHelper")

    modified: list[Path] = []
    before_samples: list[str] = []
    after_samples: list[str] = []

    for helper in helpers:
        text = _read(helper)
        if re.search(r"catch\s*\(\s*RuntimeException", text):
            continue  # ya catchea
        # Buscar el primer `} catch (`: inyectar uno nuevo justo antes
        match = re.search(
            r"^(?P<indent>[ \t]+)\}\s*catch\s*\(",
            text,
            re.MULTILINE,
        )
        if not match:
            continue
        indent = match.group("indent")
        insert = (
            f"{indent}}} catch (RuntimeException e) {{\n"
            f"{indent}    throw new BancsOperationException("
            f'"BANCS call failed", e);\n'
            f"{indent}"
        )
        new_text = text[: match.start()] + insert + text[match.start() + len(indent) + 1 :]
        # Asegurar import si no existe
        if "BancsOperationException" in new_text and (
            "import " not in new_text or "BancsOperationException" not in _imports_block(new_text)
        ):
            new_text = _inject_import(
                new_text,
                "import com.pichincha.bancs.exception.BancsOperationException;",
            )
        if new_text != text:
            _write(helper, new_text)
            modified.append(helper)
            before_samples.append("(sin catch RuntimeException)")
            after_samples.append("catch (RuntimeException e) -> BancsOperationException")

    if not modified:
        return AutofixResult(
            applied=False,
            notes="BancsClientHelper sin try/catch reconocible para wrappear",
        )

    return AutofixResult(
        applied=True,
        files_modified=modified,
        before="\n".join(before_samples),
        after="\n".join(after_samples),
        notes=f"wrapping RuntimeException agregado en {len(modified)} helper(s)",
    )


def fix_empty_mensajeNegocio_setter(  # noqa: N802
    root: Path, violation: Violation
) -> AutofixResult:
    """15.1 - Vacia `.setMensajeNegocio("valor")` dejando `setMensajeNegocio("")`
    SIN eliminar la linea: el tag debe seguir presente (slot vacio) para que
    DataPower lo complete. `null`/`""` ya se preservan.

    El check 15.1 solo falla HIGH (y este autofix solo corre) cuando el legacy NO
    poblaba mensajeNegocio; si el legacy lo poblaba el check pasa y no se toca.
    """
    modified: list[Path] = []
    before_samples: list[str] = []

    pattern = re.compile(
        r"^(?P<pre>\s*[\w.]+\.setMensajeNegocio\s*\()(?P<arg>[^;]*?)(?P<post>\)\s*;\s*)$",
        re.MULTILINE,
    )
    allowed = re.compile(
        r"setMensajeNegocio\s*\(\s*(?:\"\"|''|null|StringUtils\.EMPTY|EMPTY)\s*\)"
    )

    for f in _iter_java_files(root):
        text = _read(f)
        if ".setMensajeNegocio(" not in text:
            continue
        bad_hits = [
            m.group(0) for m in pattern.finditer(text) if not allowed.search(m.group(0))
        ]
        if not bad_hits:
            continue

        def _replace(match: re.Match[str]) -> str:
            line = match.group(0)
            if allowed.search(line):
                return line
            return f'{match.group("pre")}""{match.group("post")}'

        new_text = pattern.sub(_replace, text)
        if new_text != text:
            _write(f, new_text)
            modified.append(f)
            before_samples.extend(h.strip() for h in bad_hits[:2])

    if not modified:
        return AutofixResult(
            applied=False, notes="no se encontro setMensajeNegocio(...) con valor real"
        )

    return AutofixResult(
        applied=True,
        files_modified=modified,
        before="\n".join(before_samples[:3]),
        after='setMensajeNegocio("")',
        notes=f"mensajeNegocio vaciado, slot preservado, en {len(modified)} archivo(s)",
    )


def fix_recurso_format(root: Path, violation: Violation) -> AutofixResult:
    """15.2 - Si `setRecurso("valor")` no tiene `/`, lo reformatea a `<service>/<metodo>`.

    - Sirve cuando el servicio expone UN solo metodo obvio: service name del
      archivo + metodo mas comun.
    - Conservador: si ya hay slash se deja; si no hay pista del metodo
      devuelve `applied=False` y no toca el archivo.
    """
    modified: list[Path] = []
    before_samples: list[str] = []
    after_samples: list[str] = []

    service = _infer_service_name(root)
    pattern = re.compile(r'setRecurso\s*\(\s*"([^"]*)"\s*\)')

    for f in _iter_java_files(root):
        text = _read(f)
        if "setRecurso" not in text:
            continue
        file_service = service or _class_service_hint(f, text)

        def _replace(
            m: re.Match[str],
            *,
            _file=f,
            _text=text,
            _service=file_service,
        ) -> str:
            current = m.group(1)
            if "/" in current:
                return m.group(0)  # ya OK
            method_hint = _infer_method_hint(_text, _file)
            if not method_hint or not _service:
                return m.group(0)  # no tocar si no tenemos pista
            new_val = f"{_service}/{method_hint}"
            before_samples.append(m.group(0))
            after_samples.append(f'setRecurso("{new_val}")')
            return f'setRecurso("{new_val}")'

        new_text = pattern.sub(_replace, text)
        if new_text != text:
            _write(f, new_text)
            modified.append(f)

    if not modified:
        return AutofixResult(
            applied=False,
            notes="no se encontraron setRecurso sin '/' o falto pista de metodo",
        )

    return AutofixResult(
        applied=True,
        files_modified=modified,
        before="\n".join(before_samples[:3]),
        after="\n".join(after_samples[:3]),
        notes=f"recurso reformateado en {len(modified)} archivo(s)",
    )


def fix_componente_from_catalog(root: Path, violation: Violation) -> AutofixResult:
    """15.3 - Si `setComponente("valor")` no matchea el catalogo BPTPSRE,
    lo reemplaza por el nombre del servicio (opcion valida universal).

    Valores validos segun PDF:
      - IIB: <nombre-servicio>, `ApiClient`, `TX<6digits>`
      - WAS: <nombre-servicio>, <metodo>, <valor-archivo-config>
    El nombre del servicio es valido en ambos, asi que es el fallback seguro.
    """
    modified: list[Path] = []
    before_samples: list[str] = []
    after_samples: list[str] = []

    service = _infer_service_name(root)
    if not service:
        return AutofixResult(
            applied=False,
            notes="no se pudo inferir nombre de servicio para componente",
        )

    pattern = re.compile(r'setComponente\s*\(\s*"([^"]*)"\s*\)')
    valid = (re.compile(r"^TX\d{6}$"), re.compile(r"^ApiClient$"))

    for f in _iter_java_files(root):
        text = _read(f)
        if "setComponente" not in text:
            continue

        def _replace(m: re.Match[str]) -> str:
            current = m.group(1)
            # Ya valido?
            if any(p.match(current) for p in valid):
                return m.group(0)
            if current == service:
                return m.group(0)
            # Reemplazar por service name
            before_samples.append(m.group(0))
            after_samples.append(f'setComponente("{service}")')
            return f'setComponente("{service}")'

        new_text = pattern.sub(_replace, text)
        if new_text != text:
            _write(f, new_text)
            modified.append(f)

    if not modified:
        return AutofixResult(
            applied=False,
            notes="todos los setComponente ya son validos",
        )

    return AutofixResult(
        applied=True,
        files_modified=modified,
        before="\n".join(before_samples[:3]),
        after="\n".join(after_samples[:3]),
        notes=f"componente normalizado en {len(modified)} archivo(s)",
    )


def fix_backend_from_catalog(root: Path, violation: Violation) -> AutofixResult:
    """15.4 - Reemplaza `setBackend("00000")` / `"999"` por codigo oficial (HIGH).

    Heuristica del tipo:
    - Si el archivo/path contiene "bancs" o "Bancs" -> 00045
    - Si el archivo menciona "iib" / "Bus" / es un resolver de error de IIB -> 00638
    - Por defecto (IIB es el wrapper tipico) -> 00638
    """
    modified: list[Path] = []
    before_samples: list[str] = []
    after_samples: list[str] = []

    pattern = re.compile(r'setBackend\s*\(\s*"([^"]*)"\s*\)')

    for f in _iter_java_files(root):
        text = _read(f)
        if "setBackend" not in text:
            continue
        path_lower = str(f).lower()
        body_lower = text.lower()
        is_bancs = (
            "bancs" in path_lower
            or "bancs" in body_lower
            or "bpoperacionesbancs" in body_lower
        )
        chosen = BACKEND_BANCS_APP if is_bancs else BACKEND_IIB

        def _replace(m: re.Match[str], *, _chosen=chosen) -> str:
            current = m.group(1)
            if current in SUSPECT_BACKEND_VALUES or current == "":
                before_samples.append(m.group(0))
                after_samples.append(f'setBackend("{_chosen}")')
                return f'setBackend("{_chosen}")'
            return m.group(0)

        new_text = pattern.sub(_replace, text)
        if new_text != text:
            _write(f, new_text)
            modified.append(f)

    if not modified:
        return AutofixResult(
            applied=False,
            notes="no se encontraron backend sospechosos (00000/999)",
        )

    return AutofixResult(
        applied=True,
        files_modified=modified,
        before="\n".join(before_samples[:3]),
        after="\n".join(after_samples[:3]),
        notes=f"backend reemplazado por codigo de catalogo en {len(modified)} archivo(s)",
    )


# -- Block 16 — SonarCloud custom: test class annotations -----------------


_TEST_ANNOTATIONS = (
    "@SpringBootTest",
    "@WebMvcTest",
    "@WebFluxTest",
    "@DataJpaTest",
    "@JsonTest",
    "@RestClientTest",
    "@JdbcTest",
    "@ExtendWith",
    "@RunWith",
    "@AutoConfigureMockMvc",
)

# Detecta si la clase usa tipos que implican Spring context (heuristica para
# elegir @SpringBootTest vs @ExtendWith(MockitoExtension.class))
_SPRING_CONTEXT_HINTS = (
    "@Autowired",
    "@MockBean",
    "@SpyBean",
    "TestRestTemplate",
    "WebTestClient",
    "MockMvc",
    "@ApplicationContext",
)

_PUBLIC_CLASS_RE = re.compile(
    r"(?P<prefix>(?:^|\n)(?:@\w+(?:\([^)]*\))?\s*\n)*)"
    r"public\s+(?:abstract\s+|final\s+)?class\s+(?P<name>\w+)",
    re.MULTILINE,
)

_TEST_ANNOTATION_IMPORTS = {
    "@SpringBootTest": "org.springframework.boot.test.context.SpringBootTest",
    "@ExtendWith": "org.junit.jupiter.api.extension.ExtendWith",
}

_MOCKITO_EXTENSION_IMPORT = "org.mockito.junit.jupiter.MockitoExtension"


def fix_add_test_annotation(project_root: Path, violation: Violation) -> AutofixResult:
    """Agrega `@SpringBootTest` a clases `*Test.java` que no tengan ninguna
    anotacion de test reconocida. Si la clase luce como unit test puro (no
    usa Spring context hints), usa `@ExtendWith(MockitoExtension.class)` —
    mas barato que cargar el ApplicationContext.
    """
    _ = violation
    test_root = project_root / "src" / "test" / "java"
    if not test_root.exists():
        return AutofixResult(applied=False, notes="no hay src/test/java/")

    test_files = [
        f
        for f in test_root.rglob("*.java")
        if f.name.endswith("Test.java") or f.name.endswith("Tests.java")
    ]

    modified: list[Path] = []
    before_samples: list[str] = []
    after_samples: list[str] = []

    for f in test_files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        original = text

        # Ya tiene alguna anotacion -> skip
        if any(ann in text for ann in _TEST_ANNOTATIONS):
            continue

        # Elegir anotacion segun heuristica
        uses_spring_ctx = any(h in text for h in _SPRING_CONTEXT_HINTS)
        if uses_spring_ctx:
            chosen = "@SpringBootTest"
            needed_imports = [_TEST_ANNOTATION_IMPORTS["@SpringBootTest"]]
        else:
            chosen = "@ExtendWith(MockitoExtension.class)"
            needed_imports = [
                _TEST_ANNOTATION_IMPORTS["@ExtendWith"],
                _MOCKITO_EXTENSION_IMPORT,
            ]

        # Agregar imports si faltan
        for imp in needed_imports:
            if f"import {imp};" in text:
                continue
            m_imports = list(re.finditer(r"^import\s+[^\n]+;\n", text, re.MULTILINE))
            if m_imports:
                insert_at = m_imports[-1].end()
                text = text[:insert_at] + f"import {imp};\n" + text[insert_at:]
            else:
                m_pkg = re.match(r"package\s+[^;]+;\n", text)
                if m_pkg:
                    insert_at = m_pkg.end()
                    text = (
                        text[:insert_at] + "\n" + f"import {imp};\n" + text[insert_at:]
                    )

        # Agregar la anotacion antes del `public class`
        m_cls = _PUBLIC_CLASS_RE.search(text)
        if not m_cls:
            continue
        # Buscar la linea exacta donde aparece `public class` para indent
        line_before_class = text.rfind("\n", 0, m_cls.start("name")) + 1
        indent_match = re.match(r"^(\s*)", text[line_before_class:])
        indent = indent_match.group(1) if indent_match else ""
        # Encontrar la posicion real de `public ... class`
        public_pos = text.rfind("public", 0, m_cls.start("name"))
        if public_pos < 0:
            continue
        text = (
            text[:public_pos]
            + f"{chosen}\n{indent}"
            + text[public_pos:]
        )

        if text != original:
            f.write_text(text, encoding="utf-8")
            modified.append(f)
            rel = f.relative_to(project_root)
            before_samples.append(f"{rel}: sin anotacion test")
            after_samples.append(f"{rel}: +{chosen}")

    if not modified:
        return AutofixResult(applied=False, notes="todos los tests ya tienen anotacion")

    return AutofixResult(
        applied=True,
        files_modified=modified,
        before="\n".join(before_samples[:3]),
        after="\n".join(after_samples[:3]),
        notes=f"anotacion test agregada a {len(modified)} archivo(s)",
    )


# -- Adapters para fixes definidos en bank_autofix.py -----------------------


def fix_bancs_autoconfigure_exclude_adapter(
    root: Path, violation: Violation
) -> AutofixResult:
    """Adapter para usar `bank_autofix.fix_bancs_autoconfigure_exclude` desde
    el AUTOFIX_REGISTRY. Convierte el `BankAutofixResult` en `AutofixResult`.
    """
    from capamedia_cli.core.bank_autofix import fix_bancs_autoconfigure_exclude

    bank_result = fix_bancs_autoconfigure_exclude(root)
    return AutofixResult(
        applied=bank_result.applied,
        files_modified=bank_result.files_modified,
        before="" if bank_result.applied else (bank_result.notes or ""),
        after="\n".join(bank_result.changes),
        notes=bank_result.notes
        or ("spring.autoconfigure.exclude agregado" if bank_result.applied else ""),
    )


_SPRING_BOOT_PLUGIN_DECL_RE = re.compile(
    r"(?P<prefix>id\s*(?:\(\s*[\"']org\.springframework\.boot[\"']\s*\)|"
    r"[\"']org\.springframework\.boot[\"'])\s*version\s*(?:\(\s*)?)"
    r"(?P<quote>[\"'])(?P<version>[^\"']+)(?P=quote)",
    re.IGNORECASE,
)


def fix_spring_boot_plugin_version(root: Path, violation: Violation) -> AutofixResult:
    """8.1 - Sube el plugin Spring Boot al minimo de SU linea mayor.

    Politica 2026-09 (nunca bajar, subir solo si hace falta):
      - `3.5.x < 3.5.15` -> `3.5.15` (linea SB3, proyectos existentes).
      - `4.x < 4.1.1`    -> `4.1.1` (baseline SB4).
      - Igual o mayor al minimo de su linea -> se conserva tal cual (incluida
        cualquier version mas alta que emita el MCP Fabrics).
    El salto 3.x -> 4.x NO se automatiza: cambia artifactIds
    (`lib-trace-logger-sb4`) y librerias (event-logs 2.0.0, lib-bnc 3.0.0), lo
    decide el migrador (proyecto nuevo) o un PR de librerias (existente).

    Tambien actualiza `spring_boot_version` en `migration-context.json` para
    mantener consistencia entre el build y el contexto declarado del servicio
    (Slack 2026-05: decision del equipo tras Snyk 7 CVEs HIGH transitivas).
    """
    modified: list[Path] = []
    before_versions: list[str] = []
    after_versions: set[str] = set()

    gradle_files = [
        f
        for f in list(root.rglob("build.gradle")) + list(root.rglob("build.gradle.kts"))
        if "build" not in f.parts and "test" not in [p.lower() for p in f.parts]
    ]
    for gradle_file in gradle_files:
        text = _read(gradle_file)
        if "org.springframework.boot" not in text:
            continue

        replacements = 0
        rel_gradle = gradle_file.relative_to(root)

        def _replace(match: re.Match[str], rel_path: Path = rel_gradle) -> str:
            nonlocal replacements
            current = match.group("version")
            target = spring_boot_target_version(current)
            if target is None:
                return match.group(0)
            replacements += 1
            before_versions.append(f"{rel_path}={current}")
            after_versions.add(target)
            return (
                f"{match.group('prefix')}{match.group('quote')}"
                f"{target}{match.group('quote')}"
            )

        new_text = _SPRING_BOOT_PLUGIN_DECL_RE.sub(_replace, text)
        if replacements and new_text != text:
            _write(gradle_file, new_text)
            modified.append(gradle_file)

    # Tambien actualizar `spring_boot_version` en migration-context.json si existe
    # y declara una version mas vieja que el baseline. Mantiene consistencia
    # entre el build.gradle y el contexto registrado del servicio.
    ctx_file = root / "migration-context.json"
    if ctx_file.exists():
        ctx_text = _read(ctx_file)
        ctx_match = re.search(
            r'(?P<prefix>"spring_boot_version"\s*:\s*")'
            r"(?P<version>[^\"]+)"
            r'(?P<suffix>")',
            ctx_text,
        )
        if ctx_match:
            current = ctx_match.group("version").strip()
            # El contexto sigue al build.gradle: si el build quedo en una version
            # concreta, el contexto se alinea a esa; si no, sube dentro de su linea.
            ctx_target = (
                max(after_versions, key=lambda v: tuple(int(x) for x in re.findall(r"\d+", v)))
                if after_versions
                else spring_boot_target_version(current)
            )
            if current and ctx_target and is_version_lower(current, ctx_target):
                new_ctx = (
                    ctx_text[: ctx_match.start("version")]
                    + ctx_target
                    + ctx_text[ctx_match.end("version") :]
                )
                _write(ctx_file, new_ctx)
                modified.append(ctx_file)
                before_versions.append(
                    f"migration-context.json:spring_boot_version={current}"
                )
                after_versions.add(ctx_target)

    if not modified:
        return AutofixResult(
            applied=False,
            notes=(
                "org.springframework.boot ya cumple el minimo de su linea "
                f"(SB3 >= {SPRING_BOOT_LEGACY_BASELINE_VERSION}, SB4 >= "
                f"{SPRING_BOOT_BASELINE_VERSION}); nunca se baja una version"
            ),
        )
    after = ", ".join(sorted(after_versions)) or SPRING_BOOT_BASELINE_VERSION
    return AutofixResult(
        applied=True,
        files_modified=modified,
        before=", ".join(before_versions),
        after=f"org.springframework.boot={after}",
        notes=f"Spring Boot subido a {after} (minimo de su linea; nunca se baja)",
    )


# -- trace-logger + payload (Checks 7.7 / 7.8) ------------------------------
#
# Observabilidad por defecto en TODO servicio (orquestador Y microservicio).
# main: referencia env vars (Regla 7, sin defaults inline). test: literales con
# enabled=false. El bloque de log transaccional (lib-event-logs) NO se toca: es
# ORQ-only. Los fixes son conservadores: si `trace-logger:` ya aparece (aunque
# sea parcial) no se reescribe, queda para revision humana.
_TRACE_LOGGER_BLOCK_MAIN = (
    "trace-logger:\n"
    "  enabled: ${CCC_TRACE_LOGGER_ENABLED}\n"
    "  custom-level:\n"
    "    enabled: ${CCC_CUSTOM_LEVEL_ENABLED}\n"
    "    infoEnabled: ${CCC_CUSTOM_LEVEL_INFO_ENABLED}\n"
    "    debugEnabled: ${CCC_CUSTOM_LEVEL_DEBUG_ENABLED}\n"
    "    warnEnabled: ${CCC_CUSTOM_LEVEL_WARN_ENABLED}\n"
    "    errorEnabled: ${CCC_CUSTOM_LEVEL_ERROR_ENABLED}\n"
    "  payload:\n"
    "    mode: ${CCC_PAYLOAD_MODE}\n"
)

_TRACE_LOGGER_BLOCK_TEST = (
    "trace-logger:\n"
    "  enabled: false\n"
    "  custom-level:\n"
    "    enabled: true\n"
    "    infoEnabled: true\n"
    "    debugEnabled: false\n"
    "    warnEnabled: true\n"
    "    errorEnabled: true\n"
    "  payload:\n"
    "    mode: NONE\n"
)

_TRACE_LOGGER_KEY_RE = re.compile(r"^[ \t]*trace-logger[ \t]*:", re.MULTILINE)


def _append_top_level_block(text: str, block: str) -> str:
    """Agrega un bloque top-level YAML al final, con una linea en blanco de
    separacion si el archivo tenia contenido."""
    if not text:
        return block
    if text.endswith("\n\n"):
        return text + block
    if text.endswith("\n"):
        return text + "\n" + block
    return text + "\n\n" + block


def fix_trace_logger_application(root: Path, violation: Violation) -> AutofixResult:
    """7.7 - Inyecta el bloque `trace-logger:` en application.yml (env vars) y en
    application-test.yml (literales, enabled=false) si falta. No reescribe un
    bloque ya presente."""
    targets = (
        (Path("src/main/resources/application.yml"), _TRACE_LOGGER_BLOCK_MAIN),
        (Path("src/main/resources/application.yaml"), _TRACE_LOGGER_BLOCK_MAIN),
        (Path("src/test/resources/application-test.yml"), _TRACE_LOGGER_BLOCK_TEST),
        (Path("src/test/resources/application-test.yaml"), _TRACE_LOGGER_BLOCK_TEST),
    )
    modified: list[Path] = []
    changes: list[str] = []
    for rel, block in targets:
        f = root / rel
        if not f.exists():
            continue
        text = _read(f)
        if _TRACE_LOGGER_KEY_RE.search(text):
            continue
        _write(f, _append_top_level_block(text, block))
        modified.append(f)
        changes.append(str(rel).replace("\\", "/"))
    if not modified:
        return AutofixResult(
            applied=False,
            notes="trace-logger ya presente o application.yml no encontrado",
        )
    return AutofixResult(
        applied=True,
        files_modified=modified,
        after=", ".join(changes),
        notes="bloque trace-logger inyectado en application.yml/application-test.yml",
    )


# Item existente de la lista de env vars (`- name: "CCC_X"`). Es el anclaje mas
# confiable para insertar: alcanza con copiar su indentacion y queda como
# hermano, sin tener que adivinar la forma del chart.
_HELM_ENV_ITEM_RE = re.compile(
    r"""^(?P<indent>[ \t]*)-[ \t]+name[ \t]*:[ \t]*['"]?(?P<var>[A-Za-z_][\w.-]*)""",
)
# Claves que contienen una lista de env vars. `variables:` NO esta: en los charts
# del MCP es un MAPPING (`variables.own.config`), e insertar un item de lista
# ahi rompe el YAML (bug real en WSSeguridad0069, 2026-09-03: los 3 helm
# quedaron con ParserError y el Check 7.8 igual daba PASS).
_HELM_ENV_CONTAINER_RE = re.compile(r"^(?P<indent>[ \t]*)(config|environment|env)[ \t]*:[ \t]*$")


def _next_content_line(lines: list[str], start: int) -> str | None:
    for line in lines[start:]:
        if line.strip() and not line.lstrip().startswith("#"):
            return line
    return None


def _helm_env_insert_point(lines: list[str]) -> tuple[int, str, str] | None:
    """(indice donde insertar, indent del `-`, indent del `value:`).

    Estrategia por orden de confiabilidad:
      1. Como hermano del PRIMER item `- name:` existente (todo chart del banco
         trae al menos `JAVA_OPTIONS`), copiando su indentacion exacta.
      2. Bajo una clave contenedora (`config:`/`environment:`/`env:`) cuyo
         contenido siguiente sea una lista o este vacio.
    Devuelve None si el chart no tiene estructura de env vars reconocible.
    """
    for i, line in enumerate(lines):
        m = _HELM_ENV_ITEM_RE.match(line)
        if not m:
            continue
        item_indent = m.group("indent")
        value_indent = item_indent + "  "
        # Copiar la indentacion real del `value:` hermano si esta disponible.
        for sibling in lines[i + 1 : i + 4]:
            vm = re.match(r"^(?P<indent>[ \t]+)value[ \t]*:", sibling)
            if vm:
                value_indent = vm.group("indent")
                break
        return i, item_indent, value_indent

    for i, line in enumerate(lines):
        m = _HELM_ENV_CONTAINER_RE.match(line)
        if not m:
            continue
        following = _next_content_line(lines, i + 1)
        # Solo si lo que sigue es una lista (o la clave esta vacia): si es un
        # mapping (`own:`), insertar un `- item` ahi produce YAML invalido.
        if following is not None and not following.lstrip().startswith("-"):
            deeper = len(following) - len(following.lstrip()) > len(m.group("indent"))
            if deeper:
                continue
        item_indent = m.group("indent") + "  "
        return i + 1, item_indent, item_indent + "  "
    return None


def _misplaced_helm_env_pairs(lines: list[str]) -> list[tuple[int, int, str, str]]:
    """Items `- name:`/`value:` que son hermanos de una clave de mapping.

    Devuelve `[(inicio, fin_exclusivo, var, valor)]`. Una secuencia mezclada
    dentro de un mapping es YAML invalido: es la firma exacta del bug del
    injector viejo, que insertaba `- name: ...` bajo `variables:` cuando ahi
    vive el mapping `own:`.
    """
    found: list[tuple[int, int, str, str]] = []
    for i, line in enumerate(lines):
        m = _HELM_ENV_ITEM_RE.match(line)
        if not m:
            continue
        indent = len(m.group("indent"))
        end = i + 1
        value = ""
        while end < len(lines):
            candidate = lines[end]
            if not candidate.strip():
                break
            if len(candidate) - len(candidate.lstrip()) <= indent:
                break
            vm = re.match(r"^[ \t]*value[ \t]*:[ \t]*['\"]?(?P<value>[^'\"#]*)", candidate)
            if vm:
                value = vm.group("value").strip()
            end += 1
        following = _next_content_line(lines, end)
        if following is None:
            continue
        same_level = len(following) - len(following.lstrip()) == indent
        is_mapping_key = bool(re.match(r"^[ \t]*[\w.-]+[ \t]*:", following))
        if same_level and is_mapping_key:
            found.append((i, end, m.group("var"), value))
    return found


def repair_helm_env_structure(text: str) -> tuple[str, dict[str, str]]:
    """Quita los env vars mal ubicados de un helm que NO parsea.

    Devuelve `(texto_limpio, {var: valor})` para que el llamador los re-inserte
    en la lista correcta. Conservador a proposito: si el chart parsea bien no
    toca nada, asi que no puede danar un chart sano.
    """
    try:
        yaml.safe_load(text)
        return text, {}
    except yaml.YAMLError:
        pass
    lines = text.splitlines(keepends=True)
    misplaced = _misplaced_helm_env_pairs([line.rstrip("\n") for line in lines])
    if not misplaced:
        return text, {}
    removed: dict[str, str] = {}
    for start, end, var, value in reversed(misplaced):
        removed[var] = value
        del lines[start:end]
    return "".join(lines), dict(reversed(list(removed.items())))


def _inject_helm_env_vars(text: str, missing: dict[str, str]) -> str:
    """Inserta pares `- name: <var>` / `value: <val>` en la lista de env vars del
    helm, como hermanos de los items que ya existen (ver
    `_helm_env_insert_point`). Si el chart no tiene ninguna estructura de env
    vars, crea un bloque `environment:` al final. Solo AGREGA: para corregir un
    valor existente usar `_set_helm_env_value`."""
    lines = text.splitlines()
    point = _helm_env_insert_point(lines)
    if point is not None:
        index, item_indent, value_indent = point
        block: list[str] = []
        for var, val in missing.items():
            block.append(f'{item_indent}- name: "{var}"')
            block.append(f'{value_indent}value: "{val}"')
        new_lines = lines[:index] + block + lines[index:]
        result = "\n".join(new_lines)
        return result + "\n" if text.endswith("\n") else result
    block = ["environment:"]
    for var, val in missing.items():
        block.append(f'  - name: "{var}"')
        block.append(f'    value: "{val}"')
    suffix = "\n".join(block)
    if not text:
        return suffix + "\n"
    sep = "" if text.endswith("\n") else "\n"
    return text + sep + suffix + "\n"


def _set_helm_env_value(text: str, var: str, value: str) -> str:
    """Reescribe el `value:` de una env var ya declarada, preservando indentacion.

    Necesario porque los 7 flags del trace-logger tienen UN solo valor valido por
    ambiente y `CCC_PAYLOAD_MODE=NONE` es requisito de seguridad (no loguear
    payload/PII). Dejar un `FULL` heredado del scaffold significa payloads con
    PII en los logs, asi que el autofix lo corrige en vez de solo reportarlo.
    """
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if not re.match(
            rf"^[ \t]*(?:-[ \t]+)?name[ \t]*:[ \t]*['\"]?{re.escape(var)}['\"]?[ \t]*(#.*)?$",
            line.rstrip("\n"),
        ):
            continue
        for j in range(i + 1, min(len(lines), i + 5)):
            candidate = lines[j]
            vm = re.match(r"^(?P<prefix>[ \t]*value[ \t]*:[ \t]*)(?P<quote>['\"]?)", candidate)
            if vm:
                newline = "\n" if candidate.endswith("\n") else ""
                quote = vm.group("quote") or '"'
                lines[j] = f"{vm.group('prefix')}{quote}{value}{quote}{newline}"
                return "".join(lines)
            if re.match(r"^[ \t]*[-\w].*?:", candidate):
                break
    return text


def fix_trace_logger_helm(root: Path, violation: Violation) -> AutofixResult:
    """7.8 - Inyecta las env vars CCC_* del trace-logger que falten en cada helm
    por-entorno (dev/test/prod) con el valor esperado del ambiente
    (DEBUG_ENABLED=true solo en dev, PAYLOAD_MODE=NONE en los 3). Solo agrega las
    ausentes; los valores incorrectos existentes quedan para revision."""
    from capamedia_cli.core.checklist_rules import (
        TRACE_LOGGER_ENV_VARS,
        _helm_env_of,
        _helm_env_var_value,
        _trace_logger_expected,
    )

    helm_dir = root / "helm"
    if not helm_dir.exists():
        return AutofixResult(applied=False, notes="no hay carpeta helm/")

    helm_names = (
        "dev.yml",
        "test.yml",
        "prod.yml",
        "values-dev.yml",
        "values-test.yml",
        "values-prod.yml",
        "values-dev.yaml",
        "values-test.yaml",
        "values-prod.yaml",
    )
    modified: list[Path] = []
    changes: list[str] = []
    for name in helm_names:
        f = helm_dir / name
        if not f.exists():
            continue
        env = _helm_env_of(f)
        if not env:
            continue
        expected = _trace_logger_expected(env)
        text = _read(f)
        # Auto-sanacion: si una version vieja del injector dejo env vars en un
        # nivel invalido (chart que no parsea), se sacan de ahi y se re-insertan
        # abajo en la lista correcta.
        text, relocated = repair_helm_env_structure(text)
        current = {var: _helm_env_var_value(text, var) for var in TRACE_LOGGER_ENV_VARS}
        missing = {var: expected[var] for var, value in current.items() if value is None}
        # Valores presentes pero distintos del unico valido para el ambiente.
        # Se corrigen (antes solo se reportaban): `CCC_PAYLOAD_MODE=FULL` que
        # trae el scaffold deja payloads con PII en los logs.
        wrong = {
            var: expected[var]
            for var, value in current.items()
            if value is not None and value != expected[var]
        }
        if not missing and not wrong and not relocated:
            continue
        new_text = _inject_helm_env_vars(text, missing) if missing else text
        for var, value in wrong.items():
            new_text = _set_helm_env_value(new_text, var, value)
        if new_text == text:
            continue
        _write(f, new_text)
        modified.append(f)
        detail = []
        if relocated:
            detail.append("reubicadas " + ", ".join(sorted(relocated)) + " (YAML invalido)")
        if missing:
            detail.append(f"+{len(missing)} env vars")
        if wrong:
            detail.append(
                "corregidas " + ", ".join(f"{v}={wrong[v]}" for v in sorted(wrong))
            )
        changes.append(f"{name}: " + "; ".join(detail))
    if not modified:
        return AutofixResult(
            applied=False,
            notes="env vars trace-logger ya correctas o sin helm por-entorno",
        )
    return AutofixResult(
        applied=True,
        files_modified=modified,
        after="; ".join(changes),
        notes="env vars trace-logger inyectadas/corregidas en helm",
    )


# -- Spring Boot 4: probes, trace-logger-sb4, event-logs, sondas fuera del
#    trace-logger (doc BPTPSRE-SpringBoot4-probes-actuator-logs, 2026-09) --------

_ENV_HELM_NAMES: tuple[str, ...] = (
    "dev.yml",
    "test.yml",
    "prod.yml",
    "values-dev.yml",
    "values-test.yml",
    "values-prod.yml",
    "values-dev.yaml",
    "values-test.yaml",
    "values-prod.yaml",
)


def _env_helm_paths(root: Path) -> list[Path]:
    helm_dir = root / "helm"
    if not helm_dir.exists():
        return []
    return [helm_dir / n for n in _ENV_HELM_NAMES if (helm_dir / n).exists()]


def _detected_spring_boot_version_for_fix(root: Path) -> str:
    from capamedia_cli.core.checklist_rules import _detected_spring_boot_version

    return _detected_spring_boot_version(root)


def _project_gradle_files(root: Path) -> list[Path]:
    return [
        f
        for f in list(root.rglob("build.gradle")) + list(root.rglob("build.gradle.kts"))
        if "build" not in f.parts and "test" not in [p.lower() for p in f.parts]
    ]


# `/actuator/health` NO seguido de `/` ni letra (el agregado): es lo que hay que
# cambiar dentro de cada bloque de probe. Cubre `curl -s http://...:8080/actuator/health |`,
# `.../actuator/health"`, `path: /actuator/health` y `.../actuator/health )`.
_AGGREGATE_HEALTH_RE = re.compile(r"/actuator/health(?![/A-Za-z])")


def _rewrite_probe_block(text: str, probe: str, expected_path: str) -> tuple[str, int]:
    """Reemplaza `/actuator/health` por `expected_path` SOLO dentro del bloque
    `<probe>:`. Devuelve (texto, reemplazos). No toca initialDelaySeconds & co."""
    lines = text.splitlines(keepends=True)
    replacements = 0
    i = 0
    while i < len(lines):
        m = re.match(rf"^(?P<indent>[ \t]*){probe}[ \t]*:[ \t]*(#.*)?\r?\n?$", lines[i])
        if not m:
            i += 1
            continue
        indent = len(m.group("indent"))
        j = i + 1
        while j < len(lines):
            line = lines[j]
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            new_line, n = _AGGREGATE_HEALTH_RE.subn(expected_path, line)
            if n:
                lines[j] = new_line
                replacements += n
            j += 1
        i = j
    return "".join(lines), replacements


def fix_helm_probe_paths(root: Path, violation: Violation) -> AutofixResult:
    """7.10 - livenessProbe -> /actuator/health/liveness y readinessProbe ->
    /actuator/health/readiness en helm/{dev,test,prod}.yml. Solo reescribe el
    path del agregado `/actuator/health` dentro de cada bloque de probe;
    conserva la forma de shell (grep -q o cut) y los timings. Idempotente."""
    modified: list[Path] = []
    changes: list[str] = []
    for f in _env_helm_paths(root):
        text = _read(f)
        new_text, n_live = _rewrite_probe_block(text, "livenessProbe", ACTUATOR_LIVENESS_PATH)
        new_text, n_ready = _rewrite_probe_block(new_text, "readinessProbe", ACTUATOR_READINESS_PATH)
        if new_text != text:
            _write(f, new_text)
            modified.append(f)
            changes.append(f"{f.name}: liveness x{n_live}, readiness x{n_ready}")
    if not modified:
        return AutofixResult(
            applied=False,
            notes="probes ya apuntan a liveness/readiness o sin helm por-entorno",
        )
    return AutofixResult(
        applied=True,
        files_modified=modified,
        after="; ".join(changes),
        notes=(
            f"probes Helm reescritos a {ACTUATOR_LIVENESS_PATH} / {ACTUATOR_READINESS_PATH} "
            f"(Spring Boot 4; requiere {ACTUATOR_PROBES_ENV_VAR}=true)"
        ),
    )


def fix_helm_probes_enabled_env(root: Path, violation: Violation) -> AutofixResult:
    """7.11 - Inyecta `CCC_ACTUATOR_HEALTH_PROBES_ENABLED: "true"` en cada helm
    por-entorno donde falte. Solo agrega; un valor distinto existente queda
    para revision (no se pisa)."""
    from capamedia_cli.core.checklist_rules import _helm_env_value_any

    modified: list[Path] = []
    for f in _env_helm_paths(root):
        text = _read(f)
        text, relocated = repair_helm_env_structure(text)
        pending = dict(relocated)
        if _helm_env_value_any(text, ACTUATOR_PROBES_ENV_VAR) is None:
            pending[ACTUATOR_PROBES_ENV_VAR] = "true"
        if not pending:
            continue
        new_text = _inject_helm_env_vars(text, pending)
        if new_text != text:
            _write(f, new_text)
            modified.append(f)
    if not modified:
        return AutofixResult(
            applied=False,
            notes=(
                f"{ACTUATOR_PROBES_ENV_VAR} ya declarada (o sin helm por-entorno); "
                "valores distintos de true se revisan a mano"
            ),
        )
    return AutofixResult(
        applied=True,
        files_modified=modified,
        after=", ".join(f.name for f in modified),
        notes=f"{ACTUATOR_PROBES_ENV_VAR}=true inyectada en helm",
    )


_LIB_TRACE_LOGGER_DECL_FIX_RE = re.compile(
    r"(?P<prefix>com\.pichincha\.common:lib-trace-logger)(?P<sfx>-sb4)?:(?P<ver>[0-9][\w.\-]*)"
)


def fix_trace_logger_sb4_artifact(root: Path, violation: Violation) -> AutofixResult:
    """8.13 - Alinea la coordenada de lib-trace-logger al major de Spring Boot.

    SB4: `lib-trace-logger:<v>` -> `lib-trace-logger-sb4:1.2.0`; `-sb4:<v<1.2.0>`
    -> `1.2.0`. SB3: `lib-trace-logger:<v<1.4.0>` -> `1.4.0`. Nunca baja una
    version mayor y NO revierte `-sb4` en SB3 (eso es senal de que el proyecto
    debe ir a SB4: revision manual). Solo reescribe declaraciones existentes.
    """
    sb_version = _detected_spring_boot_version_for_fix(root)
    coord, target_ver = lib_trace_logger_coord(sb_version)
    target_sfx = "-sb4" if coord.endswith("-sb4") else ""
    modified: list[Path] = []
    changes: list[str] = []
    for gf in _project_gradle_files(root):
        text = _read(gf)
        if "lib-trace-logger" not in text:
            continue

        def _sub(m: re.Match[str], name: str = gf.name) -> str:
            sfx = m.group("sfx") or ""
            ver = m.group("ver")
            if sfx == target_sfx:
                if is_version_lower(ver, target_ver):
                    changes.append(f"{name}: {m.group(0)} -> {coord}:{target_ver}")
                    return f"{coord}:{target_ver}"
                return m.group(0)
            if target_sfx == "-sb4":
                changes.append(f"{name}: {m.group(0)} -> {coord}:{target_ver}")
                return f"{coord}:{target_ver}"
            return m.group(0)  # SB3 con -sb4: no revertir (revision manual)

        new_text = _LIB_TRACE_LOGGER_DECL_FIX_RE.sub(_sub, text)
        if new_text != text:
            _write(gf, new_text)
            modified.append(gf)
    if not modified:
        return AutofixResult(
            applied=False,
            notes=(
                f"lib-trace-logger ya en {coord}:{target_ver} o superior para Spring Boot "
                f"{sb_version or 'baseline'} (un -sb4 en SB3 se revisa a mano)"
            ),
        )
    return AutofixResult(
        applied=True,
        files_modified=modified,
        after="; ".join(changes),
        notes=f"lib-trace-logger alineado a Spring Boot {sb_version or 'baseline'}",
    )


_LIB_EVENT_LOGS_DECL_FIX_RE = re.compile(
    r"(?P<prefix>com\.pichincha\.common:lib-event-logs-(?:webflux|mvc)):(?P<ver>[0-9][\w.\-]*)"
)


def fix_event_logs_sb4_version(root: Path, violation: Violation) -> AutofixResult:
    """8.14 - Sube lib-event-logs-* a la version minima del major de Spring Boot
    (2.0.0 en SB4). Nunca baja. Solo reescribe declaraciones existentes."""
    sb_version = _detected_spring_boot_version_for_fix(root)
    target_ver = lib_event_logs_version(sb_version)
    modified: list[Path] = []
    changes: list[str] = []
    for gf in _project_gradle_files(root):
        text = _read(gf)
        if "lib-event-logs" not in text:
            continue

        def _sub(m: re.Match[str], name: str = gf.name) -> str:
            if is_version_lower(m.group("ver"), target_ver):
                changes.append(f"{name}: {m.group(0)} -> {m.group('prefix')}:{target_ver}")
                return f"{m.group('prefix')}:{target_ver}"
            return m.group(0)

        new_text = _LIB_EVENT_LOGS_DECL_FIX_RE.sub(_sub, text)
        if new_text != text:
            _write(gf, new_text)
            modified.append(gf)
    if not modified:
        return AutofixResult(
            applied=False,
            notes=(
                f"lib-event-logs ya >= {target_ver} para Spring Boot "
                f"{sb_version or 'baseline'} (o no declarada)"
            ),
        )
    return AutofixResult(
        applied=True,
        files_modified=modified,
        after="; ".join(changes),
        notes=f"lib-event-logs subida a {target_ver}",
    )


_LOGGING_BLOCK_RE = re.compile(
    r"^(?P<lindent>[ \t]*)logging[ \t]*:[ \t]*\n(?P<body>(?:(?P=lindent)[ \t]+.*\n?)*)",
    re.MULTILINE,
)


def fix_event_logs_excluded_paths(root: Path, violation: Violation) -> AutofixResult:
    """17.8 - Agrega `excluded-paths: /actuator/**,/health,/metrics,/prometheus`
    bajo `logging.event` en application.yml si falta. Si ya existe (aunque sin
    /actuator/**) no se toca: queda para revision humana. Idempotente."""
    from capamedia_cli.core.checklist_rules import ORQ_EVENT_LOGS_EXCLUDED_PATHS

    modified: list[Path] = []
    for rel in ("src/main/resources/application.yml", "src/main/resources/application.yaml"):
        f = root / rel
        if not f.exists():
            continue
        text = _read(f)
        if re.search(r"^[ \t]*excluded-paths[ \t]*:", text, re.MULTILINE):
            continue
        m = _LOGGING_BLOCK_RE.search(text)
        if not m:
            continue
        em = re.search(r"^(?P<eindent>[ \t]+)event[ \t]*:[ \t]*(#.*)?$", m.group("body"), re.MULTILINE)
        if not em:
            continue
        child_indent = em.group("eindent") + "  "
        insert_at = m.start("body") + em.end()
        nl = text.find("\n", insert_at)
        line = f"{child_indent}excluded-paths: {ORQ_EVENT_LOGS_EXCLUDED_PATHS}\n"
        new_text = text + "\n" + line if nl == -1 else text[: nl + 1] + line + text[nl + 1 :]
        _write(f, new_text)
        modified.append(f)
    if not modified:
        return AutofixResult(
            applied=False,
            notes=(
                "excluded-paths ya declarado (se revisa a mano si no incluye /actuator/**) "
                "o falta el bloque logging.event (Check 17.2)"
            ),
        )
    return AutofixResult(
        applied=True,
        files_modified=modified,
        after=f"logging.event.excluded-paths: {ORQ_EVENT_LOGS_EXCLUDED_PATHS}",
        notes="excluded-paths inyectado bajo logging.event",
    )


def _base_package(root: Path) -> str:
    """Paquete base del proyecto: el de la clase @SpringBootApplication; si no,
    el primer `package` bajo src/main/java recortado a la raiz hexagonal;
    default com.pichincha.sp."""
    src_java = root / "src" / "main" / "java"
    fallback = ""
    for f in _iter_java_files(src_java):
        text = _read(f)
        m = re.search(r"^package\s+([\w.]+)\s*;", text, re.MULTILINE)
        if not m:
            continue
        if "@SpringBootApplication" in text:
            return m.group(1)
        if not fallback:
            pkg = m.group(1)
            for layer in (".infrastructure", ".application", ".domain"):
                if layer in pkg:
                    pkg = pkg.split(layer)[0]
                    break
            fallback = pkg
    return fallback or "com.pichincha.sp"


def fix_add_trace_logger_management_config(root: Path, violation: Violation) -> AutofixResult:
    """2.10 / 2.11 - Crea `infrastructure/config/TraceLoggerManagementPathConfig.java`
    (variante MVC o WebFlux segun `spring-boot-starter-webflux`) y su test si
    no existen. No sobreescribe archivos existentes (si la clase esta pero con
    la variante equivocada, queda para revision: el Check 2.10 lo reporta)."""
    from capamedia_cli.core.checklist_rules import (
        TRACE_LOGGER_MGMT_CONFIG_CLASS,
        _find_java_class_file,
        _project_uses_webflux,
        _root_gradle_files,
    )
    from capamedia_cli.core.sb4_templates import (
        MGMT_CONFIG_MVC,
        MGMT_CONFIG_TEST_MVC,
        MGMT_CONFIG_TEST_WEBFLUX,
        MGMT_CONFIG_WEBFLUX,
    )

    uses_webflux = _project_uses_webflux(_root_gradle_files(root))
    base_pkg = _base_package(root)
    pkg_path = Path(*base_pkg.split("."))
    src_java = root / "src" / "main" / "java"
    test_java = root / "src" / "test" / "java"
    cfg_dir = Path("infrastructure") / "config"

    modified: list[Path] = []
    existing = (
        _find_java_class_file(src_java, TRACE_LOGGER_MGMT_CONFIG_CLASS) if src_java.exists() else None
    )
    if existing is None:
        target = src_java / pkg_path / cfg_dir / f"{TRACE_LOGGER_MGMT_CONFIG_CLASS}.java"
        target.parent.mkdir(parents=True, exist_ok=True)
        template = MGMT_CONFIG_WEBFLUX if uses_webflux else MGMT_CONFIG_MVC
        _write(target, template.replace("__PKG__", base_pkg))
        modified.append(target)

    existing_test = (
        _find_java_class_file(test_java, f"{TRACE_LOGGER_MGMT_CONFIG_CLASS}Test")
        if test_java.exists()
        else None
    )
    if existing_test is None:
        target_test = test_java / pkg_path / cfg_dir / f"{TRACE_LOGGER_MGMT_CONFIG_CLASS}Test.java"
        target_test.parent.mkdir(parents=True, exist_ok=True)
        template = MGMT_CONFIG_TEST_WEBFLUX if uses_webflux else MGMT_CONFIG_TEST_MVC
        _write(target_test, template.replace("__PKG__", base_pkg))
        modified.append(target_test)

    if not modified:
        return AutofixResult(
            applied=False,
            notes=(
                f"{TRACE_LOGGER_MGMT_CONFIG_CLASS} y su test ya existen "
                "(variante equivocada se revisa a mano)"
            ),
        )
    return AutofixResult(
        applied=True,
        files_modified=modified,
        after=", ".join(str(p.relative_to(root)).replace("\\", "/") for p in modified),
        notes=(
            f"{TRACE_LOGGER_MGMT_CONFIG_CLASS} ({'WebFlux' if uses_webflux else 'MVC'}) creado en "
            f"{base_pkg}.infrastructure.config (Regla 9e.3)"
        ),
    )


# -- Registry ---------------------------------------------------------------

# La clave es el ID del checklist_rules (NO un slug inventado). Asi calza 1:1
# con `CheckResult.id`. Para 2.2 tenemos 2 fixes encadenados: primero el
# conversor slf4j->BpLogger, y si aun quedan @Slf4j sueltos el removal puro.
AUTOFIX_REGISTRY: dict[str, list[AutofixFn]] = {
    "0.2e": [fix_bancs_autoconfigure_exclude_adapter],
    "1.3": [fix_abstract_to_interface],
    "2.5": [fix_slf4j_to_bplogger, fix_lombok_slf4j_removal],
    "2.10": [fix_add_trace_logger_management_config],
    "2.11": [fix_add_trace_logger_management_config],
    "5.1": [fix_bancs_exception_wrapping],
    "8.1": [fix_spring_boot_plugin_version],
    "8.13": [fix_trace_logger_sb4_artifact],
    "8.14": [fix_event_logs_sb4_version],
    "15.1": [fix_empty_mensajeNegocio_setter],
    "15.2": [fix_recurso_format],
    "15.3": [fix_componente_from_catalog],
    "15.4": [fix_backend_from_catalog],
    "16.1": [fix_add_test_annotation],
    "7.7": [fix_trace_logger_application],
    "7.8": [fix_trace_logger_helm],
    "7.10": [fix_helm_probe_paths],
    "7.11": [fix_helm_probes_enabled_env],
    "17.8": [fix_event_logs_excluded_paths],
}


def autofixable_ids() -> set[str]:
    """IDs del checklist que tienen al menos un fix registrado."""
    return set(AUTOFIX_REGISTRY.keys())


# -- Violation helpers ------------------------------------------------------


def check_result_to_violation(result) -> Violation:
    """Convierte un `CheckResult` (de checklist_rules) a `Violation`.

    El CheckResult no siempre trae file/line concretos; el fix re-escanea
    por su cuenta. Aqui solo armamos el pasaje de datos de alto nivel.
    """
    return Violation(
        check_id=result.id,
        severity=result.severity or "low",
        file=Path(""),
        line=0,
        message=result.detail or result.title,
        evidence=result.title,
    )


# -- Main loop --------------------------------------------------------------


RerunFn = Callable[[], list]  # devuelve list[CheckResult]


def run_autofix_loop(
    project_root: Path,
    rerun_checks: RerunFn,
    *,
    max_iter: int = 3,
    log_dir: Path | None = None,
) -> AutofixReport:
    """Corre el loop de autofix hasta convergencia o `max_iter`.

    Args:
      project_root: raiz del proyecto migrado.
      rerun_checks: callable que ejecuta el checklist y devuelve la lista de
        CheckResult fresca. Se llama en cada iteracion.
      max_iter: tope de rondas (default 3).
      log_dir: si se provee, se escribe `<timestamp>.log` con los diffs.

    Returns:
      AutofixReport con lista de fixes aplicados y lo que quedo sin resolver.
    """
    applied_log: list[dict] = []
    iterations = 0
    last_results: list = []

    for iteration in range(1, max_iter + 1):
        iterations = iteration
        last_results = rerun_checks()
        pending = [
            r
            for r in last_results
            if r.status == "fail"
            and r.severity in ("high", "medium")
            and r.id in AUTOFIX_REGISTRY
        ]
        if not pending:
            break

        progress = False
        for result in pending:
            fns = AUTOFIX_REGISTRY.get(result.id, [])
            violation = check_result_to_violation(result)
            for fn in fns:
                try:
                    outcome = fn(project_root, violation)
                except Exception as e:
                    outcome = AutofixResult(applied=False, notes=f"exception: {e}")
                if outcome.applied:
                    progress = True
                    applied_log.append(
                        {
                            "iteration": iteration,
                            "check_id": result.id,
                            "severity": result.severity,
                            "fix": fn.__name__,
                            "files": [str(p) for p in outcome.files_modified],
                            "before": outcome.before,
                            "after": outcome.after,
                            "notes": outcome.notes,
                        }
                    )

        if not progress:
            # Nada se movio; no tiene sentido seguir iterando
            break

    # Resultado final
    final_results = rerun_checks()
    remaining = [
        {
            "check_id": r.id,
            "severity": r.severity,
            "title": r.title,
            "detail": r.detail,
            "autofixable": r.id in AUTOFIX_REGISTRY,
        }
        for r in final_results
        if r.status == "fail" and r.severity in ("high", "medium")
    ]
    converged = len(remaining) == 0

    log_path: Path | None = None
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        log_path = log_dir / f"{stamp}.log"
        _write_log(log_path, applied_log, remaining, iterations, converged)

    return AutofixReport(
        iterations=iterations,
        converged=converged,
        applied_fixes=applied_log,
        remaining=remaining,
        log_path=log_path,
    )


def _write_log(
    path: Path,
    applied: list[dict],
    remaining: list[dict],
    iterations: int,
    converged: bool,
) -> None:
    lines: list[str] = []
    lines.append(f"# autofix run @ {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"iterations={iterations} converged={converged}")
    lines.append(f"applied_fixes={len(applied)} remaining_high_medium={len(remaining)}")
    lines.append("")
    lines.append("## Applied")
    for entry in applied:
        lines.append(
            f"- iter={entry['iteration']} id={entry['check_id']} "
            f"severity={entry['severity']} fix={entry['fix']}"
        )
        lines.append(f"    files: {entry['files']}")
        if entry["before"]:
            lines.append(f"    before: {entry['before'][:200]}")
        if entry["after"]:
            lines.append(f"    after:  {entry['after'][:200]}")
        lines.append(f"    notes:  {entry['notes']}")
    lines.append("")
    lines.append("## Remaining (NEEDS_HUMAN)" if remaining else "## Remaining: none")
    for r in remaining:
        flag = "(autofixable-no-converge)" if r["autofixable"] else "(no-autofix)"
        lines.append(
            f"- {r['check_id']} [{r['severity']}] {r['title']} {flag}: {r['detail']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# -- Internal helpers -------------------------------------------------------


def _imports_block(text: str) -> str:
    """Primeros imports del archivo (aproximacion)."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            lines.append(stripped)
        elif stripped.startswith("package "):
            continue
        elif stripped and not stripped.startswith("//") and not stripped.startswith("/*"):
            break
    return "\n".join(lines)


def _inject_import(text: str, import_line: str) -> str:
    if import_line in text:
        return text
    # Insertar tras la ultima linea `import ...;`
    lines = text.splitlines()
    last_import = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("import "):
            last_import = i
    if last_import == -1:
        # Insertar despues del package (si existe) o al inicio
        for i, line in enumerate(lines):
            if line.strip().startswith("package "):
                lines.insert(i + 1, "")
                lines.insert(i + 2, import_line)
                return "\n".join(lines)
        return import_line + "\n" + text
    lines.insert(last_import + 1, import_line)
    return "\n".join(lines)


_SERVICE_NAME_PATTERNS = (
    re.compile(r"(WSClientes\d+)"),
    re.compile(r"(WSTecnicos\d+)"),
    re.compile(r"(ORQClientes\d+)"),
    re.compile(r"(tnd-msa-[\w-]+)"),
)


def _infer_service_name(root: Path) -> str | None:
    """Intenta sacar el nombre de servicio del path o de config/build files."""
    # De path
    for pattern in _SERVICE_NAME_PATTERNS:
        m = pattern.search(str(root))
        if m:
            return m.group(1)
    # De settings.gradle
    settings = root / "settings.gradle"
    if settings.exists():
        text = _read(settings)
        m = re.search(r"rootProject\.name\s*=\s*['\"]([^'\"]+)['\"]", text)
        if m:
            return m.group(1)
    # De .capamedia/config.yaml
    cfg = root / ".capamedia" / "config.yaml"
    if cfg.exists():
        text = _read(cfg)
        m = re.search(r"service_name:\s*([\w-]+)", text)
        if m:
            return m.group(1)
    # Del nombre del directorio
    if root.name and root.name not in {"migrated", "src"}:
        return root.name
    return None


def _class_service_hint(file: Path, text: str) -> str | None:
    """Intenta derivar un service name del propio archivo."""
    for pattern in _SERVICE_NAME_PATTERNS:
        for source in (str(file), text):
            m = pattern.search(source)
            if m:
                return m.group(1)
    return None


_METHOD_PATTERNS = (
    re.compile(r'@PostMapping\s*\(\s*["\']?/?([\w-]+)'),
    re.compile(r'@GetMapping\s*\(\s*["\']?/?([\w-]+)'),
    re.compile(r"@PayloadRoot\s*\([^)]*localPart\s*=\s*\"([^\"]+)\""),
)


def _infer_method_hint(text: str, file: Path) -> str | None:
    """Busca el nombre de operacion mas cercano en el archivo."""
    for pattern in _METHOD_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1)
    # Fallback: nombre de clase menos el sufijo
    stem = file.stem
    for suffix in ("Controller", "Endpoint", "Service", "Mapper", "Resolver"):
        if stem.endswith(suffix):
            base = stem[: -len(suffix)]
            if base:
                return base[0].lower() + base[1:]
    return None
