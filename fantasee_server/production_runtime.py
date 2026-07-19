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


def production_database_path() -> Path:
    """Return the configured durable production database path."""
    return _database_path()


def _story_context(story_id: Any, fallback: Any = None) -> tuple[str | None, str]:
    """Resolve a durable job's story identity to a user-facing title."""
    candidate = str(story_id or "").strip()
    fallback_text = str(fallback or "").strip()
    if not candidate or candidate in {"queue", "library"}:
        return (candidate or None, fallback_text or "Story context pending")
    try:
        from fantasee_server.paths import generated_story_dir

        manifest_path = generated_story_dir(candidate) / f"{candidate}.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            title = str(manifest.get("title") or "").strip()
            if title:
                return candidate, title
    except Exception:
        pass
    return candidate, fallback_text or candidate


def record_llm_usage(run_id: str, result: Any) -> None:
    """Persist one bounded creative commission's token evidence."""
    with ProductionStore(_database_path()) as store:
        store.record_token_usage(
            run_id,
            call_name=str(result.name),
            estimated_tokens=int(result.estimated_tokens),
            reserved_tokens=int(result.reserved_tokens),
            actual_tokens=int(result.actual_tokens),
            retries=int(result.retries),
        )


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


def find_active_task(*, story_id: str, kind: str, metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Find an existing queued/running task with the same production input."""
    fingerprint = _fingerprint(metadata or {})
    with ProductionStore(_database_path()) as store:
        runs = store.list_runs(limit=200)
    for run in runs:
        if run.story_id == story_id and run.command == kind and run.input_fingerprint == fingerprint and run.status in {"queued", "running"}:
            return {"id": run.id, "status": run.status}
    return None


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


def enqueue_task_job(
    task_id: str,
    *,
    job_id: str,
    job_type: str,
    payload: dict[str, Any],
    required_capabilities: tuple[str, ...] = (),
) -> None:
    with ProductionStore(_database_path()) as store:
        store.enqueue_job(
            task_id,
            job_id=job_id,
            job_type=job_type,
            payload=payload,
            idempotency_key=job_id,
            required_capabilities=required_capabilities,
        )
        store.append_event(task_id, "task.job_queued", {
            "job_id": job_id,
            "job_type": job_type,
        })


def update_task_job(
    task_id: str,
    *,
    job_id: str,
    status: str,
    progress: float = 0,
    message: str | None = None,
) -> None:
    with ProductionStore(_database_path()) as store:
        store.set_job_status(
            job_id,
            status=status,
            progress=progress,
            message=message,
        )
        store.append_event(task_id, "task.job_updated", {
            "job_id": job_id,
            "status": status,
            "progress": progress,
            "message": message,
        })


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


def finalize_run_from_jobs(run_id: str) -> str | None:
    """Close a parent run once all of its durable jobs are terminal."""
    with ProductionStore(_database_path()) as store:
        run = store.get_run(run_id)
        jobs = store.list_jobs(run_id) if run else []
    if run is None or not jobs or any(job.status in {"queued", "leased", "running", "retryable"} for job in jobs):
        return None
    status = "succeeded" if all(job.status == "succeeded" for job in jobs) else "failed"
    finish_task(
        run_id,
        status=status,
        message=f"{run.command} complete: {sum(job.status == 'succeeded' for job in jobs)} succeeded, "
                f"{sum(job.status != 'succeeded' for job in jobs)} failed",
        payload={"job_count": len(jobs)},
    )
    return status


def get_persisted_task(task_id: str) -> dict[str, Any] | None:
    with ProductionStore(_database_path()) as store:
        run = store.get_run(task_id)
        if run is None:
            return None
        events = store.list_events(task_id)
        jobs = store.list_jobs(task_id)
        workers = {worker.id: worker for worker in store.list_workers()}
    job_context = {
        job.id: _story_context(
            job.payload.get("story_id") or run.story_id,
            job.payload.get("story_name")
            or job.payload.get("story_concept")
            or job.payload.get("concept")
            or job.payload.get("story_id")
            or run.story_id,
        )
        for job in jobs
    }
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
        "jobs": [
            {
                "id": job.id,
                "job_type": job.job_type,
                "status": job.status,
                "attempts": job.attempts,
                "progress": job.progress,
                "message": job.message,
                "required_capabilities": list(job.required_capabilities),
                "priority": job.priority,
                "worker_id": job.lease_owner,
                "worker_status": workers.get(job.lease_owner).status if job.lease_owner in workers else None,
                "lease_expires_at": job.lease_expires_at,
                "story_id": job_context[job.id][0],
                "story_name": job_context[job.id][1],
            }
            for job in jobs
        ],
    }


def list_persisted_tasks(*, limit: int = 50) -> list[dict[str, Any]]:
    """Return persisted runs in the shape expected by the task panel."""
    with ProductionStore(_database_path()) as store:
        runs = store.list_runs(limit=limit)
        workers = {worker.id: worker for worker in store.list_workers()}
        run_ids = {run.id for run in runs}
        result = []
        for run in runs:
            events = store.list_events(run.id)
            jobs = store.list_jobs(run.id)
            last = events[-1].payload if events else {}
            started = events[0].payload if events else {}
            status = {
                "queued": "queued",
                "running": "running",
                "succeeded": "done",
                "failed": "error",
                "cancelled": "error",
            }.get(run.status, run.status)
            task = {
                "id": run.id,
                "kind": run.command,
                "story_id": run.story_id,
                "status": status,
                "progress": last.get("progress", 0 if status != "done" else 1),
                "stage": last.get("stage", "complete" if status == "done" else "queued"),
                "message": last.get("message", run.status),
                "created_at": run.created_at,
                "updated_at": run.updated_at,
                "item_count": len(jobs) or started.get("metadata", {}).get("item_count"),
                "worker_ids": sorted({
                    job.lease_owner for job in jobs
                    if job.lease_owner and job.status in {"leased", "running"}
                }),
            }
            metadata = started.get("metadata") or {}
            if metadata.get("parent"):
                task["parent"] = metadata["parent"]
            result.append(task)
            if jobs and run.command in {"generation_queue", "library_maintenance"}:
                for job in jobs:
                    # A durable child run is already returned by list_runs.
                    # Do not append the parent's projection as a second copy.
                    if job.id in run_ids:
                        continue
                    story_id, story_name = _story_context(
                        job.payload.get("story_id") or run.story_id,
                        job.payload.get("story_name")
                        or job.payload.get("story_concept")
                        or job.payload.get("concept")
                        or job.payload.get("story_id")
                        or run.story_id,
                    )
                    child = {
                        "id": job.id,
                        "parent": run.id,
                        "kind": "library_story" if job.job_type == "library.complete" else "generate",
                        "status": {"succeeded": "done", "failed": "error"}.get(job.status, job.status),
                        "progress": job.progress,
                        "message": job.message or job.status,
                        "story_id": story_id,
                        "story_name": story_name,
                        "created_at": run.created_at,
                        "worker_id": job.lease_owner,
                        "worker_status": workers.get(job.lease_owner).status if job.lease_owner in workers else None,
                    }
                    result.append(child)
    return result
