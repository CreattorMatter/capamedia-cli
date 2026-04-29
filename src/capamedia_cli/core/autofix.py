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


def fix_remove_mensajeNegocio_setter(  # noqa: N802
    root: Path, violation: Violation
) -> AutofixResult:
    """15.1 - Elimina llamadas `.setMensajeNegocio("...")` con valor real (HIGH).

    Por PDF BPTPSRE, mensajeNegocio lo setea DataPower; el microservicio no debe
    poblar texto de negocio. `null` o `""` se preservan porque algunos contratos
    SOAP necesitan emitir el slot vacio para que DataPower lo complete.
    """
    modified: list[Path] = []
    before_samples: list[str] = []

    pattern = re.compile(r"^\s*[\w.]+\.setMensajeNegocio\s*\([^;]*\)\s*;\s*$", re.MULTILINE)
    allowed = re.compile(
        r"setMensajeNegocio\s*\(\s*(?:\"\"|''|null|StringUtils\.EMPTY|EMPTY)\s*\)"
    )

    for f in _iter_java_files(root):
        text = _read(f)
        if ".setMensajeNegocio(" not in text:
            continue
        hits = pattern.findall(text)
        if not hits:
            continue
        bad_hits = [h for h in hits if not allowed.search(h)]
        if not bad_hits:
            continue

        def _replace(match: re.Match[str]) -> str:
            line = match.group(0)
            return line if allowed.search(line) else ""

        new_text = pattern.sub(_replace, text)
        new_text = re.sub(r"\n{3,}", "\n\n", new_text)
        if new_text != text:
            _write(f, new_text)
            modified.append(f)
            before_samples.extend(h.strip() for h in bad_hits[:2])

    if not modified:
        return AutofixResult(applied=False, notes="no se encontro setMensajeNegocio(...)")

    return AutofixResult(
        applied=True,
        files_modified=modified,
        before="\n".join(before_samples[:3]),
        after="(removed)",
        notes=f"setMensajeNegocio eliminado en {len(modified)} archivo(s)",
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


# -- Registry ---------------------------------------------------------------

# La clave es el ID del checklist_rules (NO un slug inventado). Asi calza 1:1
# con `CheckResult.id`. Para 2.2 tenemos 2 fixes encadenados: primero el
# conversor slf4j->BpLogger, y si aun quedan @Slf4j sueltos el removal puro.
AUTOFIX_REGISTRY: dict[str, list[AutofixFn]] = {
    "1.3": [fix_abstract_to_interface],
    "2.2": [fix_slf4j_to_bplogger, fix_lombok_slf4j_removal],
    "5.1": [fix_bancs_exception_wrapping],
    "15.1": [fix_remove_mensajeNegocio_setter],
    "15.2": [fix_recurso_format],
    "15.3": [fix_componente_from_catalog],
    "15.4": [fix_backend_from_catalog],
    "16.1": [fix_add_test_annotation],
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
