"""Engine abstraction para `batch migrate` — soporta Claude Code CLI y Codex CLI.

Filosofia:
- Ambos engines corren como subprocess headless, consumiendo la suscripcion
  del usuario (Claude Max o ChatGPT Plus/Pro). NO usan API tokens pagos.
- La seleccion es transparente: `--engine claude|codex|auto`. Auto prioriza
  Claude si esta disponible.
- Ambos devuelven un `EngineResult` uniforme con deteccion de rate limit.

El contrato de entrada (EngineInput) esta tipado por JSON Schema, el engine
se encarga de inyectar al prompt la instruccion de respetarlo.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

TEXT_IO_KWARGS = {"encoding": "utf-8", "errors": "replace"}

RATE_LIMIT_PATTERNS = (
    re.compile(r"rate[_\s-]?limit", re.IGNORECASE),
    re.compile(r"\b429\b"),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"quota.{0,20}exceeded", re.IGNORECASE),
    re.compile(r"usage.{0,20}limit", re.IGNORECASE),
    re.compile(r"retry.{0,10}after", re.IGNORECASE),
)

RETRY_AFTER_PATTERN = re.compile(r"retry[-_\s]?after[:\s=]+(\d+)", re.IGNORECASE)


def _resolve_executable(bin_path: str) -> str:
    return shutil.which(bin_path) or bin_path


@dataclass
class EngineInput:
    """Parametros para una corrida headless del engine."""

    workspace: Path
    prompt: str
    schema_path: Path | None
    output_path: Path
    timeout_seconds: int
    model: str | None = None
    reasoning_effort: str | None = None
    unsafe: bool = False


@dataclass
class EngineResult:
    """Resultado uniforme cualquiera sea el engine."""

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    rate_limited: bool = False
    retry_after_seconds: int | None = None
    failure_reason: str | None = None


class Engine(Protocol):
    name: str
    subscription_type: str

    def is_available(self) -> tuple[bool, str]: ...
    def run_headless(self, einput: EngineInput) -> EngineResult: ...


def _detect_rate_limit(text: str) -> tuple[bool, int | None]:
    """True + optional retry-after en segundos si detecta rate limit."""
    if not text:
        return (False, None)
    hit = any(p.search(text) for p in RATE_LIMIT_PATTERNS)
    if not hit:
        return (False, None)
    m = RETRY_AFTER_PATTERN.search(text)
    if m:
        try:
            return (True, int(m.group(1)))
        except ValueError:
            pass
    return (True, None)


class CodexEngine:
    """Engine basado en `codex exec` (ChatGPT Plus/Pro sin API key)."""

    name = "codex"
    subscription_type = "ChatGPT"

    def __init__(self, bin_path: str = "codex") -> None:
        self.bin_path = bin_path

    def is_available(self) -> tuple[bool, str]:
        executable = _resolve_executable(self.bin_path)
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                **TEXT_IO_KWARGS,
                timeout=5,
                check=False,
            )
        except FileNotFoundError:
            return (False, f"binario `{self.bin_path}` no encontrado en PATH")
        except OSError as exc:
            return (False, f"binario `{self.bin_path}` no ejecutable: {exc}")
        except subprocess.TimeoutExpired:
            return (False, f"`{self.bin_path} --version` timeout")
        if result.returncode != 0:
            return (False, f"`{self.bin_path} --version` exit {result.returncode}")
        # Check login (best effort)
        try:
            login = subprocess.run(
                [executable, "login", "status"],
                capture_output=True,
                text=True,
                **TEXT_IO_KWARGS,
                timeout=5,
                check=False,
            )
            if login.returncode != 0:
                return (False, "codex no autenticado (correr `codex login`)")
        except Exception:
            pass
        return (True, f"codex {result.stdout.strip()}")

    def run_headless(self, einput: EngineInput) -> EngineResult:
        executable = _resolve_executable(self.bin_path)
        cmd = [
            executable,
            "exec",
            "--skip-git-repo-check",
            "--cd",
            str(einput.workspace),
            "--output-last-message",
            str(einput.output_path),
            "--color",
            "never",
        ]
        if einput.schema_path is not None:
            cmd.extend(["--output-schema", str(einput.schema_path)])
        if einput.model:
            cmd.extend(["--model", einput.model])
        if einput.reasoning_effort:
            cmd.extend(["-c", f'model_reasoning_effort="{einput.reasoning_effort}"'])
        if einput.unsafe:
            cmd.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            cmd.append("--full-auto")
        cmd.append("-")

        started = time.perf_counter()
        try:
            result = subprocess.run(
                cmd,
                input=einput.prompt,
                text=True,
                **TEXT_IO_KWARGS,
                capture_output=True,
                check=False,
                timeout=einput.timeout_seconds,
            )
        except FileNotFoundError:
            elapsed = time.perf_counter() - started
            return EngineResult(
                exit_code=127,
                stdout="",
                stderr="",
                duration_seconds=elapsed,
                failure_reason=f"binario `{self.bin_path}` no encontrado",
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - started
            return EngineResult(
                exit_code=124,
                stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
                duration_seconds=elapsed,
                failure_reason=f"timeout despues de {einput.timeout_seconds}s",
            )

        elapsed = time.perf_counter() - started
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        rate_limited, retry_after = _detect_rate_limit(stderr + "\n" + stdout)
        return EngineResult(
            exit_code=result.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=elapsed,
            rate_limited=rate_limited,
            retry_after_seconds=retry_after,
        )


class ClaudeEngine:
    """Engine basado en `claude -p` (Claude Code CLI, suscripcion Max)."""

    name = "claude"
    subscription_type = "Claude Max"

    # Tools default que el orquestador necesita para migrar codigo legacy
    DEFAULT_ALLOWED_TOOLS = (
        "Read,Write,Edit,Bash,Glob,Grep,TodoWrite"
    )

    def __init__(self, bin_path: str = "claude") -> None:
        self.bin_path = bin_path

    def is_available(self) -> tuple[bool, str]:
        executable = _resolve_executable(self.bin_path)
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                **TEXT_IO_KWARGS,
                timeout=5,
                check=False,
            )
        except FileNotFoundError:
            return (False, f"binario `{self.bin_path}` no encontrado en PATH")
        except OSError as exc:
            return (False, f"binario `{self.bin_path}` no ejecutable: {exc}")
        except subprocess.TimeoutExpired:
            return (False, f"`{self.bin_path} --version` timeout")
        if result.returncode != 0:
            return (False, f"`{self.bin_path} --version` exit {result.returncode}")
        return (True, f"claude {result.stdout.strip()}")

    def _prompt_with_schema(self, prompt: str, schema_path: Path | None) -> str:
        if schema_path is None or not schema_path.exists():
            return prompt
        try:
            schema_text = schema_path.read_text(encoding="utf-8")
        except OSError:
            return prompt
        appendix = (
            "\n\n---\n\n"
            "# Formato de salida OBLIGATORIO\n\n"
            "Al terminar el trabajo, tu ULTIMO mensaje debe ser SOLO un "
            "objeto JSON (sin markdown, sin prefijo, sin texto adicional) "
            "que cumpla exactamente este JSON Schema:\n\n"
            f"```json\n{schema_text}\n```\n\n"
            "NO escribas nada mas despues de ese JSON. El orquestador lo "
            "parsea directo del ultimo mensaje."
        )
        return prompt + appendix

    def run_headless(self, einput: EngineInput) -> EngineResult:
        executable = _resolve_executable(self.bin_path)
        prompt = self._prompt_with_schema(einput.prompt, einput.schema_path)
        cmd = [
            executable,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--allowed-tools",
            self.DEFAULT_ALLOWED_TOOLS,
        ]
        if einput.unsafe:
            cmd.extend(["--permission-mode", "bypassPermissions"])
        else:
            cmd.extend(["--permission-mode", "acceptEdits"])
        if einput.model:
            cmd.extend(["--model", einput.model])

        # Claude Code CLI no tiene --cd, lo corremos con cwd del subprocess
        started = time.perf_counter()
        try:
            result = subprocess.run(
                cmd,
                text=True,
                **TEXT_IO_KWARGS,
                capture_output=True,
                check=False,
                timeout=einput.timeout_seconds,
                cwd=str(einput.workspace),
            )
        except FileNotFoundError:
            elapsed = time.perf_counter() - started
            return EngineResult(
                exit_code=127,
                stdout="",
                stderr="",
                duration_seconds=elapsed,
                failure_reason=f"binario `{self.bin_path}` no encontrado",
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - started
            return EngineResult(
                exit_code=124,
                stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
                duration_seconds=elapsed,
                failure_reason=f"timeout despues de {einput.timeout_seconds}s",
            )

        elapsed = time.perf_counter() - started
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # Claude --output-format json devuelve un envelope con el mensaje final
        # en `result` o `output`. Extraemos el ultimo JSON del output que matchee
        # el schema, lo escribimos en output_path para compatibilidad con el
        # resto del pipeline.
        self._extract_structured_output(stdout, einput.output_path)

        rate_limited, retry_after = _detect_rate_limit(stderr + "\n" + stdout)
        return EngineResult(
            exit_code=result.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=elapsed,
            rate_limited=rate_limited,
            retry_after_seconds=retry_after,
        )

    @staticmethod
    def _extract_structured_output(stdout: str, output_path: Path) -> None:
        """Del envelope JSON de Claude extrae el ultimo mensaje y lo escribe
        al output_path para que el orquestador existente lo parsee."""
        if not stdout.strip():
            return
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError:
            # Fallback: buscar el ultimo bloque JSON del output
            last_json = _last_json_block(stdout)
            if last_json is None:
                return
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(last_json, encoding="utf-8")
            return

        # Formato claude --output-format json:
        #   { "type": "result", "result": "texto final...", ... }
        # El texto final puede ser un JSON embebido o markdown con JSON.
        result_text = ""
        if isinstance(envelope, dict):
            result_text = envelope.get("result") or envelope.get("output") or ""
        if not isinstance(result_text, str):
            result_text = json.dumps(result_text)

        last_json = _last_json_block(result_text) or result_text
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(last_json, encoding="utf-8")


def _last_json_block(text: str) -> str | None:
    """Devuelve el ultimo bloque JSON valido embebido en `text`, o None."""
    if not text:
        return None
    # Prefer triple-backtick json blocks
    backtick = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    for candidate in reversed(backtick):
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    # Fallback: buscar la ultima llave balanceada
    stack: list[int] = []
    best: str | None = None
    for idx, ch in enumerate(text):
        if ch == "{":
            stack.append(idx)
        elif ch == "}" and stack:
            start = stack.pop()
            if not stack:
                candidate = text[start : idx + 1]
                try:
                    json.loads(candidate)
                    best = candidate
                except json.JSONDecodeError:
                    continue
    return best


def available_engines(
    *,
    claude_bin: str = "claude",
    codex_bin: str = "codex",
) -> dict[str, tuple[bool, str]]:
    """Retorna el status de cada engine soportado."""
    return {
        "claude": ClaudeEngine(claude_bin).is_available(),
        "codex": CodexEngine(codex_bin).is_available(),
    }


def select_engine(
    preference: str | None,
    *,
    claude_bin: str = "claude",
    codex_bin: str = "codex",
) -> Engine:
    """Selecciona un engine concreto segun preferencia del usuario.

    preference:
      - "claude": fuerza Claude. Error si no esta disponible.
      - "codex":  fuerza Codex.  Error si no esta disponible.
      - "auto" o None: elige el primero disponible. Prioriza Claude sobre Codex.
    """
    pref = (preference or "auto").strip().lower()
    claude = ClaudeEngine(claude_bin)
    codex = CodexEngine(codex_bin)

    if pref == "claude":
        ok, reason = claude.is_available()
        if not ok:
            raise RuntimeError(f"engine claude no disponible: {reason}")
        return claude
    if pref == "codex":
        ok, reason = codex.is_available()
        if not ok:
            raise RuntimeError(f"engine codex no disponible: {reason}")
        return codex
    if pref not in {"auto", ""}:
        raise ValueError(
            f"engine invalido: '{preference}'. Usa claude | codex | auto"
        )

    # auto: Claude primero (preferencia del tech lead), luego Codex
    ok_claude, _ = claude.is_available()
    if ok_claude:
        return claude
    ok_codex, reason = codex.is_available()
    if ok_codex:
        return codex
    raise RuntimeError(
        "ningun engine disponible. Probar `claude --version` / "
        "`codex --version` y `auth bootstrap`"
    )


def engine_from_env() -> str | None:
    """Lee preferencia desde env (`CAPAMEDIA_ENGINE`)."""
    val = os.environ.get("CAPAMEDIA_ENGINE")
    return val.strip().lower() if val else None
