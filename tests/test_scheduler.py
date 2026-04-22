"""Tests para core/scheduler.py (BatchScheduler con throttle + rate limit pause)."""

from __future__ import annotations

import threading
import time

from capamedia_cli.core.scheduler import BatchScheduler


def test_scheduler_passthrough_when_no_limit() -> None:
    """Sin services_per_window, acquire no bloquea."""
    s = BatchScheduler(services_per_window=0)
    start = time.monotonic()
    for i in range(10):
        s.acquire(f"svc-{i}")
    assert time.monotonic() - start < 0.1


def test_scheduler_throttles_when_window_full() -> None:
    """Con services_per_window=2, el 3er acquire bloquea hasta liberar."""
    s = BatchScheduler(services_per_window=2, window_seconds=0.3)
    s.acquire("a")
    s.acquire("b")

    done = threading.Event()

    def third() -> None:
        s.acquire("c")
        done.set()

    t = threading.Thread(target=third)
    t.start()
    # Debe bloquear al menos hasta que la ventana expire (~0.3s)
    assert not done.wait(timeout=0.1)
    t.join(timeout=1.0)
    assert done.is_set()


def test_scheduler_events_emitted_for_throttle() -> None:
    """El callback on_event recibe mensajes cuando hay pausa."""
    messages: list[str] = []
    s = BatchScheduler(
        services_per_window=1,
        window_seconds=0.2,
        on_event=messages.append,
    )
    s.acquire("svc-a")

    def second() -> None:
        s.acquire("svc-b")

    t = threading.Thread(target=second)
    t.start()
    t.join(timeout=1.0)
    assert any("window full" in m for m in messages)


def test_scheduler_rate_limit_pauses_all() -> None:
    """handle_rate_limit pausa a todos, con retry_after_seconds."""
    s = BatchScheduler(services_per_window=0, default_rate_limit_pause=10.0)
    s.handle_rate_limit("svc-a", retry_after_seconds=0.2)
    stats = s.stats()
    assert stats["pause_remaining_seconds"] > 0
    # Un acquire nuevo bloquea hasta que termine la pausa
    start = time.monotonic()
    s.acquire("svc-b")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.15


def test_scheduler_rate_limit_default_when_retry_after_none() -> None:
    s = BatchScheduler(default_rate_limit_pause=0.2)
    s.handle_rate_limit("svc-a", retry_after_seconds=None)
    stats = s.stats()
    assert 0.1 < stats["pause_remaining_seconds"] <= 0.3


def test_scheduler_stats_snapshot_format() -> None:
    s = BatchScheduler(services_per_window=3, window_seconds=100)
    s.acquire("a")
    s.acquire("b")
    stats = s.stats()
    assert stats["launches_in_window"] == 2
    assert stats["services_per_window"] == 3
    assert stats["window_seconds"] == 100


def test_scheduler_thread_safety_under_contention() -> None:
    """Varios threads compitiendo por slots. No deadlock, no race."""
    s = BatchScheduler(services_per_window=5, window_seconds=2.0)
    done_count = 0
    lock = threading.Lock()

    def worker(idx: int) -> None:
        nonlocal done_count
        s.acquire(f"svc-{idx}")
        with lock:
            done_count += 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)
    assert done_count == 5


def test_scheduler_release_is_noop() -> None:
    """release() no debe romper aun cuando no hay tracking (hoy).
    Es hook por simetria."""
    s = BatchScheduler()
    s.release("whatever")  # sin excepcion
