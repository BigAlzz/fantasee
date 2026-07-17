"""Durable production progress endpoints."""

from fastapi import APIRouter, HTTPException

from fantasee_server.production_runtime import get_persisted_task


router = APIRouter(tags=["production"])


@router.get("/api/production/runs/{run_id}")
def get_production_run(run_id: str):
    """Return a persisted run and its events for restart-safe progress UI."""
    task = get_persisted_task(run_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Production run not found")
    return task
