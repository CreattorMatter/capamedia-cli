"""Cliente JSON-RPC 2.0 minimalista para hablar con MCP servers por stdio.

Implementa el protocolo MCP (Model Context Protocol) 2024-11-05:
  1. initialize  - handshake con versiones y capabilities
  2. notifications/initialized - ack
  3. tools/list - enumera tools expuestas
  4. tools/call - invoca una tool con sus argumentos

Diseñado para una sola sesion corta: arrancar, invocar una tool, cerrar.
Para sesiones long-running hay librerias mas completas.
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    """Error devuelto por el MCP server (JSON-RPC error or tool failure)."""


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def required_params(self) -> list[str]:
        return list(self.input_schema.get("required", []))

    @property
    def all_params(self) -> list[str]:
        return list(self.input_schema.get("properties", {}).keys())


class MCPClient:
    """Cliente para una sesion MCP stdio. Usar con context manager."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None, cwd: str | None = None):
        self._command = command
        self._env = env
        self._cwd = cwd
        self._proc: subprocess.Popen | None = None
        self._next_id = 0
        self._stderr_buffer: list[str] = []

    # -- Context manager ----------------------------------------------------

    def __enter__(self) -> MCPClient:
        self._proc = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env,
            cwd=self._cwd,
            bufsize=0,
        )
        # Start stderr drain thread so the process does not block on stderr buffer fill
        t = threading.Thread(target=self._drain_stderr, daemon=True)
        t.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            try:
                self._proc.kill()
            except OSError:
                pass

    # -- Internal ------------------------------------------------------------

    def _drain_stderr(self) -> None:
        assert self._proc is not None
        assert self._proc.stderr is not None
        try:
            for raw in iter(self._proc.stderr.readline, b""):
                try:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                except Exception:  # noqa: BLE001
                    line = str(raw)
                if line:
                    self._stderr_buffer.append(line)
        except (OSError, ValueError):
            pass

    def _next_request_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _send(self, msg: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        line = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

    def _recv(self) -> dict[str, Any]:
        assert self._proc is not None and self._proc.stdout is not None
        raw = self._proc.stdout.readline()
        if not raw:
            err_tail = "\n".join(self._stderr_buffer[-20:])
            raise MCPError(f"MCP server cerro stdout sin responder. stderr tail:\n{err_tail}")
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            raise MCPError(f"Respuesta no-JSON del MCP: {raw[:200]!r}") from e

    def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        req_id = self._next_request_id()
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)
        resp = self._recv()
        if resp.get("id") != req_id:
            raise MCPError(f"ID de respuesta no coincide: esperaba {req_id}, recibi {resp.get('id')}")
        if "error" in resp:
            err = resp["error"]
            raise MCPError(f"MCP error {err.get('code')}: {err.get('message')}")
        return resp.get("result")

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    # -- Public API ----------------------------------------------------------

    def initialize(self, client_name: str = "capamedia-cli", client_version: str = "0.2.3") -> dict[str, Any]:
        """Perform the MCP initialize handshake. Returns server info."""
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": client_version},
            },
        )
        self._notify("notifications/initialized")
        return result or {}

    def list_tools(self) -> list[MCPTool]:
        result = self._request("tools/list") or {}
        return [
            MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in result.get("tools", [])
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool and return its raw response. Raises MCPError if the tool reports an error."""
        result = self._request("tools/call", {"name": name, "arguments": arguments}) or {}
        if result.get("isError"):
            content = result.get("content", [])
            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            raise MCPError(f"Tool '{name}' fallo: {' | '.join(text_parts) or result}")
        return result

    @property
    def stderr_lines(self) -> list[str]:
        return list(self._stderr_buffer)
