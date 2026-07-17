"""Small adapter that persists existing background task progress.

The legacy task dictionary remains the live WebSocket/UI cache for now. This
adapter mirrors durable lifecycle events so a later request can reconstruct
truthful progress after a process restart.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fantasee_server.production_store import ProductionStore


_ROOT = Path(__file__).resolve().parent.parent


def _database_path() -> Path:
    configured = os.environ.get("FANTASEE_PRODUCTION_DB", "").strip()
    return Path(configured) if configured else _ROOT / ".fantasee" / "production.db"


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def start_task(task_id: str, *, story_id: str, kind: str, metadata: dict[str, Any] | None = None) -> None:
    with ProductionStore(_database_path()) as store:
        if store.get_run(task_id) is None:
            store.create_run(
                run_id=task_id,
                story_id=story_id,
                command=kind,
                input_fingerprint=_fingerprint(metadata or {}),
            )
        store.update_run(task_id, status="running")
        store.append_event(task_id, "task.started", {
            "story_id": story_id,
            "kind": kind,
            "metadata": metadata or {},
        })


def update_task(
    task_id: str,
    *,
    stage: str,
    progress: float,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    with ProductionStore(_database_path()) as store:
        store.update_run(task_id, status="running")
        event_payload = {
            "stage": stage,
            "progress": progress,
            "message": message,
        }
        if payload:
            event_payload.update(payload)
        store.append_event(task_id, "task.progress", event_payload)


def finish_task(
    task_id: str,
    *,
    status: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if status not in {"succeeded", "failed", "cancelled"}:
        raise ValueError(f"invalid terminal task status: {status}")
    with ProductionStore(_database_path()) as store:
        store.update_run(task_id, status=status)
        event_payload = {"status": status, "progress": 1.0, "message": message}
        if payload:
            event_payload.update(payload)
        store.append_event(task_id, "task.finished", event_payload)


def get_persisted_task(task_id: str) -> dict[str, Any] | None:
    with ProductionStore(_database_path()) as store:
        run = store.get_run(task_id)
        if run is None:
            return None
        events = store.list_events(task_id)
    return {
        "run": {
            "id": run.id,
            "story_id": run.story_id,
            "command": run.command,
            "status": run.status,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        },
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }
