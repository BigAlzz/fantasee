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
