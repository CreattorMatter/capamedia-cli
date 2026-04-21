"""Persistent state helpers for resumable batch runs."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


def state_file(workspace: Path, run_kind: str) -> Path:
    """Return the canonical state file path for a workspace/run kind pair."""
    return workspace / ".capamedia" / "batch-state" / f"{run_kind}.json"


def load_state(workspace: Path, run_kind: str, service: str, *, reset: bool = False) -> dict[str, Any]:
    """Load or initialize persistent state for a batch service run."""
    path = state_file(workspace, run_kind)
    if not reset and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("service", service)
                data.setdefault("run_kind", run_kind)
                data.setdefault("stages", {})
                data.setdefault("result", {})
                return data
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "service": service,
        "run_kind": run_kind,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "updated_at": dt.datetime.now(dt.UTC).isoformat(),
        "stages": {},
        "result": {},
    }


def save_state(workspace: Path, run_kind: str, state: dict[str, Any]) -> Path:
    """Persist batch state to disk."""
    path = state_file(workspace, run_kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    path.write_text(json.dumps(state, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return path


def stage_status(state: dict[str, Any], stage: str) -> str:
    stage_data = state.get("stages", {}).get(stage, {})
    if isinstance(stage_data, dict):
        return str(stage_data.get("status", ""))
    return ""


def stage_ok(state: dict[str, Any], stage: str) -> bool:
    return stage_status(state, stage) == "ok"


def mark_stage(
    state: dict[str, Any],
    stage: str,
    *,
    status: str,
    detail: str = "",
    fields: dict[str, str] | None = None,
) -> None:
    """Update a single stage entry in memory."""
    stages = state.setdefault("stages", {})
    existing = stages.get(stage, {}) if isinstance(stages, dict) else {}
    attempts = int(existing.get("attempts", 0)) + 1
    stages[stage] = {
        "status": status,
        "detail": detail,
        "fields": fields or {},
        "attempts": attempts,
        "updated_at": dt.datetime.now(dt.UTC).isoformat(),
    }


def set_result(
    state: dict[str, Any],
    *,
    status: str,
    detail: str,
    fields: dict[str, str] | None = None,
) -> None:
    """Update the final result snapshot in memory."""
    state["result"] = {
        "status": status,
        "detail": detail,
        "fields": fields or {},
        "updated_at": dt.datetime.now(dt.UTC).isoformat(),
    }
