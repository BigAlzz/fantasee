"""Durable production progress endpoints."""

from fastapi import APIRouter, Body, HTTPException

import os
import time
from pathlib import Path

from fantasee_server.production_runtime import get_persisted_task, list_persisted_tasks, production_database_path
from fantasee_server.production_store import ProductionStore
from story_storage import validate_story_id
from fastapi.responses import FileResponse


router = APIRouter(tags=["production"])


@router.get("/api/production/control")
def get_production_control():
    with ProductionStore(production_database_path()) as store:
        paused = store.admission_paused()
        mode = store.rendering_mode()
    os.environ["FANTASEE_RENDERING_MODE"] = mode
    return {"admission_paused": paused, "rendering_mode": mode}


@router.post("/api/production/control")
def set_production_control(
    admission_paused: bool | None = Body(default=None, embed=True),
    rendering_mode: str | None = Body(default=None, embed=True),
):
    with ProductionStore(production_database_path()) as store:
        paused = store.admission_paused() if admission_paused is None else store.set_admission_paused(admission_paused)
        try:
            mode = store.rendering_mode() if rendering_mode is None else store.set_rendering_mode(rendering_mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    os.environ["FANTASEE_RENDERING_MODE"] = mode
    return {"admission_paused": paused, "rendering_mode": mode}


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


def _release_asset(story_id: str, release_id: str, suffixes: tuple[str, ...]) -> Path:
    validate_story_id(story_id)
    with ProductionStore(production_database_path()) as store:
        release = store.get_release(release_id)
    if release is None or release.story_id != story_id:
        raise HTTPException(status_code=404, detail="Release not found")
    root = Path(release.path).expanduser().resolve()
    candidates = [root] if root.is_file() else sorted(
        (path for path in root.glob("*") if path.is_file() and path.suffix.lower() in suffixes),
        key=lambda path: path.name.lower(),
    ) if root.is_dir() else []
    if not candidates:
        raise HTTPException(status_code=404, detail="Release asset is no longer available")
    return candidates[0]


@router.get("/api/stories/{story_id}/releases/{release_id}/video")
def serve_release_video(story_id: str, release_id: str):
    return FileResponse(str(_release_asset(story_id, release_id, (".mp4", ".webm", ".mkv"))), media_type="video/mp4")


@router.get("/api/stories/{story_id}/releases/{release_id}/subtitles")
def serve_release_subtitles(story_id: str, release_id: str):
    return FileResponse(str(_release_asset(story_id, release_id, (".vtt", ".srt"))), media_type="text/vtt")


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


@router.post("/api/production/jobs/{job_id}/priority")
def reprioritize_production_job(job_id: str, priority: int = Body(..., embed=True)):
    try:
        with ProductionStore(production_database_path()) as store:
            job = store.set_job_priority(job_id, priority)
        return {"job_id": job.id, "status": job.status, "priority": job.priority}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
