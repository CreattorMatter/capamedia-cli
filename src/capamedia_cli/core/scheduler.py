"""Scheduler del batch con control de rate limit y ventana de suscripcion.

Objetivo: evitar reventar el rate limit de la suscripcion (Claude Max / ChatGPT
Plus) cuando corremos muchos servicios en paralelo. No gastamos tokens API, pero
las suscripciones sí tienen cupos por ventana (~5h).

Dos mecanismos:
1. `services_per_window`: throttle proactivo. Se puede procesar N servicios
   por `window_seconds`. Al agotarse, los threads esperan al siguiente slot.
2. Reactive pause: cuando un engine reporta `rate_limited=True`, el scheduler
   pausa TODOS los threads por `retry_after_seconds` (o un default sano).

Thread-safe. Sin scheduler configurado, opera en modo passthrough.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class BatchScheduler:
    """Limita cuantos servicios se pueden lanzar por ventana temporal.

    - services_per_window <= 0 desactiva el throttle proactivo.
    - window_seconds default 5h coincide con la ventana de Claude Max.
    - default_rate_limit_pause se usa cuando un engine reporta rate limit
      sin retry-after explicito.
    """

    services_per_window: int = 0
    window_seconds: float = 5 * 3600
    default_rate_limit_pause: float = 300.0
    on_event: Callable[[str], None] | None = None

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _cond: threading.Condition = field(init=False, repr=False)
    _launch_timestamps: deque[float] = field(default_factory=deque, init=False, repr=False)
    _paused_until: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._cond = threading.Condition(self._lock)

    # --- Public API ---------------------------------------------------------

    def acquire(self, service: str) -> None:
        """Bloquea hasta que haya slot disponible y la pausa activa termine."""
        with self._cond:
            while True:
                now = time.monotonic()
                if self._paused_until > now:
                    wait = self._paused_until - now
                    self._emit(
                        f"scheduler: pause active ({wait:.0f}s). {service} espera."
                    )
                    self._cond.wait(timeout=wait)
                    continue

                if self.services_per_window > 0:
                    self._prune_window(now)
                    if len(self._launch_timestamps) >= self.services_per_window:
                        oldest = self._launch_timestamps[0]
                        wait = max(0.0, (oldest + self.window_seconds) - now)
                        if wait > 0:
                            self._emit(
                                f"scheduler: window full ({self.services_per_window}/"
                                f"{self.window_seconds / 3600:.1f}h). {service} "
                                f"espera {wait:.0f}s."
                            )
                            self._cond.wait(timeout=wait)
                            continue

                self._launch_timestamps.append(time.monotonic())
                return

    def handle_rate_limit(
        self, service: str, retry_after_seconds: int | None = None
    ) -> None:
        """Pausa todo el scheduler por `retry_after_seconds` o default."""
        pause = float(retry_after_seconds or self.default_rate_limit_pause)
        with self._cond:
            target = time.monotonic() + pause
            if target > self._paused_until:
                self._paused_until = target
            self._emit(
                f"scheduler: rate limit hit en {service}. Pausa global "
                f"{pause:.0f}s. Reanuda en {pause / 60:.1f} min."
            )
            self._cond.notify_all()

    def release(self, service: str) -> None:
        """Hook por simetria. Hoy no hace nada (se basa en timestamps)."""
        _ = service

    def stats(self) -> dict[str, float | int]:
        """Snapshot util para debug/UI."""
        with self._lock:
            now = time.monotonic()
            self._prune_window(now)
            pause_remaining = max(0.0, self._paused_until - now)
            return {
                "launches_in_window": len(self._launch_timestamps),
                "services_per_window": self.services_per_window,
                "window_seconds": self.window_seconds,
                "pause_remaining_seconds": pause_remaining,
            }

    # --- Internals ----------------------------------------------------------

    def _prune_window(self, now: float) -> None:
        threshold = now - self.window_seconds
        while self._launch_timestamps and self._launch_timestamps[0] < threshold:
            self._launch_timestamps.popleft()

    def _emit(self, msg: str) -> None:
        if self.on_event:
            with contextlib.suppress(Exception):
                self.on_event(msg)
