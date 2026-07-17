"""Durable production progress endpoints."""

from fastapi import APIRouter, HTTPException

import os
import time

from fantasee_server.production_runtime import get_persisted_task, list_persisted_tasks, production_database_path
from fantasee_server.production_store import ProductionStore


router = APIRouter(tags=["production"])


@router.get("/api/production/runs")
def list_production_runs(limit: int = 50):
    return {"runs": list_persisted_tasks(limit=limit)}


@router.get("/api/production/workers")
def list_production_workers():
    stale_after = float(os.environ.get("FANTASEE_WORKER_STALE_SECONDS", "180") or "180")
    now = time.time()
    with ProductionStore(production_database_path()) as store:
        workers = store.list_workers()
    return {
        "workers": [
            {
                "id": worker.id,
                "capabilities": list(worker.capabilities),
                "status": "stale" if now - worker.last_seen > stale_after else worker.status,
                "current_job_id": worker.current_job_id,
                "last_seen": worker.last_seen,
                "created_at": worker.created_at,
            }
            for worker in workers
        ]
    }


@router.get("/api/production/runs/{run_id}")
def get_production_run(run_id: str):
    """Return a persisted run and its events for restart-safe progress UI."""
    task = get_persisted_task(run_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Production run not found")
    return task


@router.get("/api/production/runs/{run_id}/events")
def list_production_events(run_id: str, after_sequence: int = 0):
    """Return durable progress events after a reconnect cursor."""
    with ProductionStore(production_database_path()) as store:
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Production run not found")
        events = store.list_events(run_id, after_sequence=max(0, after_sequence))
    return {
        "run_id": run_id,
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at,
            }
            for event in events
        ],
        "next_sequence": events[-1].sequence if events else max(0, after_sequence),
    }


@router.get("/api/production/runs/{run_id}/token-usage")
def get_production_token_usage(run_id: str):
    with ProductionStore(production_database_path()) as store:
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Production run not found")
        return {
            "run_id": run_id,
            "totals": store.token_usage_totals(run_id),
            "calls": [usage.__dict__ for usage in store.list_token_usage(run_id)],
        }


@router.get("/api/stories/{story_id}/releases")
def list_story_releases(story_id: str):
    with ProductionStore(production_database_path()) as store:
        releases = store.list_releases(story_id)
    return {"releases": [release.__dict__ for release in releases]}


@router.post("/api/production/jobs/{job_id}/retry")
def retry_production_job(job_id: str):
    try:
        with ProductionStore(production_database_path()) as store:
            job = store.retry_job(job_id)
        return {"job_id": job.id, "status": job.status}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/production/jobs/{job_id}/cancel")
def cancel_production_job(job_id: str):
    try:
        with ProductionStore(production_database_path()) as store:
            job = store.cancel_job(job_id)
        return {"job_id": job.id, "status": job.status}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
