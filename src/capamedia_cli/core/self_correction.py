"""Self-correction con error especifico para retries de `batch migrate`.

Cuando una iteracion del engine AI falla (build roto, checklist HIGH/MEDIUM,
timeout, rate limit), la siguiente iteracion NO debe re-correr el mismo prompt
a ciegas. Queremos alimentarle un resumen del fallo previo + hints especificos
de que corregir.

Pipeline por iteracion (retry > 0):

    1. extract_failure_context(workspace, project, state) ->
       lee los logs batch-migrate/*.log + el CHECKLIST_*.md (si existe) +
       el campo stages.migrate del state, y devuelve un FailureContext.
    2. build_correction_appendix(ctx, base_prompt) ->
       devuelve base_prompt + un appendix Markdown con la categoria de
       fallo, build errors tail, checklist violations y hints concretos
       para que el AI sepa que corregir SIN re-migrar desde cero.

Thread-safety: el FailureContext se deriva de archivos por-workspace y se
guarda (opcionalmente) en el state dict del servicio, que ya es aislado por
workspace. No hay cache global ni thread-local.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# -- Hints por check_id -----------------------------------------------------

# Hints especificos para cada check del checklist BPTPSRE. Para los IDs que
# tienen autofix registrado en core.autofix.AUTOFIX_REGISTRY, reproducimos la
# transformacion deterministica como guia textual. Para los demas, damos un
# hint conservador.

_CHECK_HINTS: dict[str, str] = {
    "0.1": "Elegir UN solo tipo de proyecto: remover @RestController o @Endpoint segun corresponda.",
    "0.2a": "Copiar el WSDL del legacy a src/main/resources/. Sin WSDL el proyecto SOAP no arranca.",
    "0.2b": "Regenerar el WSDL del migrado para que tenga el mismo count de operaciones que el legacy.",
    "0.2c": "Reclasificar el framework (1 op -> WebFlux / multi-op -> SOAP MVC). Revisar build.gradle.",
    "0.3": "Renombrar operaciones del migrado para matchear EXACTAMENTE las del WSDL legacy.",
    "0.4": "Ajustar targetNamespace del WSDL migrado para que matchee el del legacy.",
    "0.5": "Copiar los XSDs faltantes a src/main/resources/ junto al WSDL.",
    "1.1": "Crear las carpetas hexagonales faltantes (application/domain/infrastructure).",
    "1.2": "Remover imports de Spring/JAX-WS del package domain. Domain debe ser framework-agnostico.",
    "1.3": "Convertir `public abstract class XxxPort` -> `public interface XxxPort`. Ajustar adapters para usar `implements` en lugar de `extends`.",
    "1.4": "Un solo port por dominio de negocio. Fusionar ports que apunten al mismo dominio.",
    "2.1": "Usar constructor injection con @RequiredArgsConstructor de Lombok. Eliminar @Autowired en campos.",
    "2.2": "Reemplazar @Slf4j por ServiceLogHelper + @BpLogger/@BpTraceable. Eliminar imports de org.slf4j.",
    "5.1": "Envolver llamadas a BancsClient en try-catch que convierta RuntimeException en BancsException propia del servicio.",
    "15.1": "Remover el setter de mensajeNegocio en el response mapper. Los errores se emiten solo via ServiceLogHelper.",
    "15.2": "Normalizar el formato de <recurso>: usar slash-prefix tipo '/servicio/operacion'. Ver PDF BPTPSRE.",
    "15.3": "setComponente debe recibir exactamente uno de: nombre-servicio, 'ApiClient', o el valor canonico del PDF BPTPSRE. No inventar valores.",
    "15.4": "setBackend debe usar un codigo del catalogo oficial (ej 00638 para IIB, 00045 para BANCS app). Consultar reference_codigos_backend.md.",
}

_GENERIC_FIX_HINT = (
    "Revisar el suggested_fix del CHECKLIST y aplicar la correccion minima. "
    "NO re-migrar desde cero."
)


# -- Dataclass --------------------------------------------------------------


@dataclass
class FailureContext:
    """Snapshot del fallo de la iteracion previa que queremos alimentar al retry."""

    attempt: int
    failure_category: str  # "build" | "checklist" | "timeout" | "rate_limit" | "unknown"
    build_errors: list[str] = field(default_factory=list)
    checklist_violations: list[dict[str, str]] = field(default_factory=list)
    stdout_tail: str = ""
    stderr_tail: str = ""

    def is_empty(self) -> bool:
        return (
            not self.build_errors
            and not self.checklist_violations
            and not self.stdout_tail
            and not self.stderr_tail
        )


# -- Parsers ----------------------------------------------------------------


_BUILD_ERROR_MARKERS = (
    "error:",
    "FAILED",
    "Compilation failed",
    "> Task :",
    "BUILD FAILED",
    "What went wrong",
)


def _tail_lines(text: str, n: int = 50) -> list[str]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-n:]


def _extract_build_errors(stdout: str, stderr: str, max_lines: int = 50) -> list[str]:
    """Devuelve el tail de lineas relevantes de build.

    Prioriza lineas que contienen markers de error Gradle/Java. Si no hay
    markers (p.ej. el build no llego a correr) devuelve el tail crudo del
    stderr.
    """
    combined = stderr + "\n" + stdout
    matches = [
        ln.rstrip()
        for ln in combined.splitlines()
        if any(marker in ln for marker in _BUILD_ERROR_MARKERS)
    ]
    if matches:
        return matches[-max_lines:]
    return _tail_lines(stderr, max_lines)


_CHECK_HEADER_RE = re.compile(
    r"^\*\*(?P<id>[\d\.]+[a-z]?)\s+(?P<title>.+?)\*\*\s*-\s*`(?P<verdict>[A-Z\-]+)`"
)


def _parse_checklist_violations(md_path: Path) -> list[dict[str, str]]:
    """Parsea un CHECKLIST_<svc>.md y extrae las violaciones (status=FAIL).

    Formato esperado (ver commands/check.py::_write_report):

        **1.3 Ports son interfaces** - `FAIL-HIGH`
          - Detail: foo bar
          - Fix: bar baz

    Devuelve una lista de dicts {check_id, severity, title, evidence, hint}.
    """
    if not md_path.exists():
        return []
    try:
        text = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    violations: list[dict[str, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _CHECK_HEADER_RE.match(line.strip())
        if not m or not m.group("verdict").startswith("FAIL"):
            i += 1
            continue
        verdict = m.group("verdict")
        severity = verdict.split("-", 1)[1] if "-" in verdict else "low"
        check_id = m.group("id")
        title = m.group("title").strip()
        detail = ""
        suggested_fix = ""
        j = i + 1
        while j < len(lines):
            nxt = lines[j].rstrip()
            if nxt.startswith("  - Detail:"):
                detail = nxt.split("Detail:", 1)[1].strip()
            elif nxt.startswith("  - Fix:"):
                suggested_fix = nxt.split("Fix:", 1)[1].strip()
            elif nxt.startswith("**") or nxt.startswith("### ") or nxt.startswith("## "):
                break
            elif nxt == "":
                pass
            j += 1
        hint = _CHECK_HINTS.get(check_id) or suggested_fix or _GENERIC_FIX_HINT
        violations.append(
            {
                "check_id": check_id,
                "severity": severity,
                "title": title,
                "evidence": detail,
                "hint": hint,
            }
        )
        i = j
    return violations


def _find_latest_log(run_dir: Path, suffix: str) -> Path | None:
    if not run_dir.exists():
        return None
    candidates = sorted(run_dir.glob(f"*{suffix}"))
    return candidates[-1] if candidates else None


def _read_text_safe(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _classify_failure(
    state: dict[str, Any],
    stdout: str,
    stderr: str,
    build_errors: list[str],
    checklist_violations: list[dict[str, str]],
) -> str:
    migrate_stage = state.get("stages", {}).get("migrate", {})
    detail = ""
    fields: dict[str, Any] = {}
    if isinstance(migrate_stage, dict):
        detail = str(migrate_stage.get("detail", ""))
        raw_fields = migrate_stage.get("fields")
        if isinstance(raw_fields, dict):
            fields = raw_fields
    if fields.get("codex") == "timeout" or "timeout" in detail.lower():
        return "timeout"
    if fields.get("rate_limited") == "yes" or "rate limit" in (stderr + stdout).lower():
        return "rate_limit"
    if build_errors:
        return "build"
    if checklist_violations:
        return "checklist"
    check_value = str(fields.get("check", "")) if fields else ""
    if check_value.startswith("BLOCKED_BY_HIGH"):
        return "checklist"
    if fields.get("build") in {"red", "failed"}:
        return "build"
    return "unknown"


# -- Public API -------------------------------------------------------------


def extract_failure_context(
    workspace: Path,
    migrated_project: Path | None,
    state: dict[str, Any],
) -> FailureContext | None:
    """Construye un FailureContext desde el estado previo del workspace.

    Devuelve None si el state no refleja ningun fallo previo (p.ej. es el
    primer intento o el intento anterior fue exitoso).
    """
    migrate_stage = state.get("stages", {}).get("migrate", {})
    attempts = 0
    previous_status = ""
    if isinstance(migrate_stage, dict):
        try:
            attempts = int(migrate_stage.get("attempts", 0))
        except (TypeError, ValueError):
            attempts = 0
        previous_status = str(migrate_stage.get("status", ""))

    result = state.get("result", {}) if isinstance(state.get("result"), dict) else {}
    result_status = str(result.get("status", ""))

    # Fallback para retries en primer attempt del loop donde migrate_stage
    # todavia no existe pero si hay result fail.
    if previous_status != "fail" and result_status != "fail":
        return None

    run_dir = workspace / ".capamedia" / "batch-migrate"
    stdout_log = _find_latest_log(run_dir, "-stdout-*.log") or _find_latest_log(
        run_dir, "stdout.log"
    )
    stderr_log = _find_latest_log(run_dir, "-stderr-*.log") or _find_latest_log(
        run_dir, "stderr.log"
    )
    stdout_text = _read_text_safe(stdout_log)
    stderr_text = _read_text_safe(stderr_log)

    build_errors = _extract_build_errors(stdout_text, stderr_text)

    checklist_violations: list[dict[str, str]] = []
    if migrated_project is not None:
        # Tomar el nombre del servicio del state (mas confiable que path)
        service = str(state.get("service", migrated_project.name))
        md_candidates = [
            migrated_project / f"CHECKLIST_{service}.md",
            migrated_project / f"CHECKLIST_{service.lower()}.md",
            migrated_project / f"CHECKLIST_{service.upper()}.md",
        ]
        for cand in md_candidates:
            if cand.exists():
                checklist_violations = _parse_checklist_violations(cand)
                break

    stdout_tail = "\n".join(_tail_lines(stdout_text, 50))
    stderr_tail = "\n".join(_tail_lines(stderr_text, 50))

    category = _classify_failure(
        state, stdout_text, stderr_text, build_errors, checklist_violations
    )

    ctx = FailureContext(
        attempt=attempts,
        failure_category=category,
        build_errors=build_errors,
        checklist_violations=checklist_violations,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )
    if ctx.is_empty() and category == "unknown":
        # No hay senal clara de fallo, mejor no mentirle al AI.
        return None
    return ctx


_APPENDIX_MARKER = "<!-- capamedia:self-correction -->"


def build_correction_appendix(ctx: FailureContext, base_prompt: str) -> str:
    """Devuelve base_prompt + appendix que explica el fallo previo + hints.

    Si base_prompt ya contiene un appendix previo (marcado con
    `<!-- capamedia:self-correction -->`), lo reemplaza en lugar de duplicar.
    """
    category_label = {
        "build": "build roto (./gradlew build fallo)",
        "checklist": "violaciones del checklist BPTPSRE",
        "timeout": "timeout de la iteracion anterior",
        "rate_limit": "rate limit del engine",
        "unknown": "fallo no clasificado",
    }.get(ctx.failure_category, ctx.failure_category)

    lines: list[str] = []
    lines.append(_APPENDIX_MARKER)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"# INTENTO {ctx.attempt + 1} (correccion automatica)")
    lines.append(f"## Error previo: {category_label}")
    lines.append("")

    if ctx.checklist_violations:
        lines.append("### Fallos del checklist detectados")
        for v in ctx.checklist_violations:
            sev = (v.get("severity") or "LOW").upper()
            evidence = v.get("evidence") or "(sin detalle)"
            lines.append(
                f"- [{sev}] {v.get('check_id', '?')} {v.get('title', '')}".rstrip()
            )
            lines.append(f"  Evidencia: {evidence}")
            lines.append(f"  Hint: {v.get('hint', _GENERIC_FIX_HINT)}")
        lines.append("")

    if ctx.build_errors:
        lines.append("### Build errors (tail)")
        lines.append("```")
        lines.extend(ctx.build_errors[-50:])
        lines.append("```")
        lines.append("")

    if not ctx.checklist_violations and not ctx.build_errors and ctx.stderr_tail:
        lines.append("### Stderr (tail)")
        lines.append("```")
        lines.append(ctx.stderr_tail)
        lines.append("```")
        lines.append("")

    lines.append("### Instrucciones para este retry")
    lines.append("1. Corregi ESPECIFICAMENTE los fallos listados arriba.")
    lines.append("2. NO intentes re-migrar desde cero. Solo fixes.")
    lines.append(
        "3. Cuando termines, corre `./gradlew build` y verifica que pase."
    )
    if ctx.checklist_violations:
        lines.append(
            "4. Volve a correr el checklist deterministico y validar que "
            "los items HIGH/MEDIUM esten en PASS."
        )

    appendix = "\n".join(lines)

    if _APPENDIX_MARKER in base_prompt:
        # Reemplazar el appendix previo (desde el marker hasta el final).
        idx = base_prompt.index(_APPENDIX_MARKER)
        trimmed = base_prompt[:idx].rstrip() + "\n\n"
        return trimmed + appendix + "\n"

    return base_prompt.rstrip() + "\n\n" + appendix + "\n"


def stash_failure_context(state: dict[str, Any], ctx: FailureContext | None) -> None:
    """Guarda el FailureContext dentro del state dict (thread-safe por workspace)."""
    if ctx is None:
        state.pop("last_failure", None)
        return
    state["last_failure"] = {
        "attempt": ctx.attempt,
        "failure_category": ctx.failure_category,
        "build_errors": list(ctx.build_errors),
        "checklist_violations": list(ctx.checklist_violations),
        "stdout_tail": ctx.stdout_tail,
        "stderr_tail": ctx.stderr_tail,
    }


def load_failure_context(state: dict[str, Any]) -> FailureContext | None:
    """Inverso de stash_failure_context: devuelve el ctx guardado, o None."""
    raw = state.get("last_failure")
    if not isinstance(raw, dict):
        return None
    try:
        return FailureContext(
            attempt=int(raw.get("attempt", 0)),
            failure_category=str(raw.get("failure_category", "unknown")),
            build_errors=list(raw.get("build_errors", []) or []),
            checklist_violations=list(raw.get("checklist_violations", []) or []),
            stdout_tail=str(raw.get("stdout_tail", "")),
            stderr_tail=str(raw.get("stderr_tail", "")),
        )
    except (TypeError, ValueError):
        return None
