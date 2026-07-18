"""Semantic shot-plan endpoints for the Studio editor."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from fantasee_server.production_runtime import (
    enqueue_task_job,
    finalize_run_from_jobs,
    production_database_path,
    start_task,
)
from fantasee_server.production_store import ProductionStore
from fantasee_server.production_worker import ProductionWorker
from fantasee_server.paths import STORY_VIEWER_DIR, generated_story_dir
from fantasee_server.discovery import generated_asset_url
from fantasee_server.shot_planning import ShotSpec, plan_semantic_shots, validate_shot_plan
from fantasee_server.state import atomic_write_json
from fantasee_server.media_timeline import (
    build_shot_timeline,
    build_story_shot_timeline as build_full_story_shot_timeline,
    write_shot_timeline,
)


router = APIRouter(tags=["shots"])


def _invalidate_shot_release(story_id: str, scene_idx: int) -> None:
    """Mark visual ordering changes as stale through the release chain."""
    manifest_path = generated_story_dir(story_id) / f"{story_id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scene = manifest["scenes"][scene_idx]
    existing = set(scene.get("stale_outputs") or [])
    existing.update({"shot_timeline", "scene_video", "full_video", "plex"})
    order = ("images", "audio", "subtitles", "shot_timeline", "scene_video", "full_video", "plex")
    scene["stale_outputs"] = [kind for kind in order if kind in existing]
    manifest["status"] = "draft"
    pipeline = manifest.get("pipeline")
    if not isinstance(pipeline, dict):
        pipeline = {}
    pipeline.update({"status": "draft", "next_stage": "shot_timeline"})
    manifest["pipeline"] = pipeline
    atomic_write_json(manifest_path, manifest)


def _scene_for(story_id: str, scene_idx: int) -> tuple[dict, str]:
    manifest_path = generated_story_dir(story_id) / f"{story_id}.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="Story not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes") or []
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")
    return scenes[scene_idx], f"scene-{scene_idx + 1:02d}"


@router.get("/api/stories/{story_id}/scenes/{scene_idx}/shots")
def list_scene_shots(story_id: str, scene_idx: int):
    _, scene_id = _scene_for(story_id, scene_idx)
    with ProductionStore(production_database_path()) as store:
        shots = store.list_shots(story_id, scene_id)
    return {"scene_id": scene_id, "shots": [shot.__dict__ for shot in shots]}


@router.post("/api/stories/{story_id}/scenes/{scene_idx}/shots")
def plan_scene_shots(story_id: str, scene_idx: int, body: dict = Body(default=None)):
    scene, scene_id = _scene_for(story_id, scene_idx)
    pacing = str((body or {}).get("pacing") or "balanced")
    narration = scene.get("narration") or scene.get("narration_text") or scene.get("narrative") or ""
    visual_direction = scene.get("prompt") or ""
    shots = plan_semantic_shots(
        scene_id=scene_id,
        narration=narration,
        visual_direction=visual_direction,
        pacing=pacing,
    )
    validation = validate_shot_plan(shots)
    if not validation.valid:
        raise HTTPException(status_code=422, detail={"codes": validation.codes})
    with ProductionStore(production_database_path()) as store:
        revision = store.save_shot_plan(story_id, scene_id, shots)
    return {"scene_id": scene_id, "revision": revision, "shots": [shot.__dict__ for shot in shots]}


@router.patch("/api/stories/{story_id}/scenes/{scene_idx}/shots/order")
def reorder_scene_shots(story_id: str, scene_idx: int, body: dict = Body(default=None)):
    _, scene_id = _scene_for(story_id, scene_idx)
    shot_ids = [str(value).strip() for value in (body or {}).get("shot_ids", []) if str(value).strip()]
    try:
        with ProductionStore(production_database_path()) as store:
            revision = store.reorder_shots(story_id, scene_id, shot_ids)
            shots = store.list_shots(story_id, scene_id, revision=revision)
        _invalidate_shot_release(story_id, scene_idx)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"scene_id": scene_id, "revision": revision, "shots": [shot.__dict__ for shot in shots], "timeline_stale": True}


@router.get("/api/stories/{story_id}/scenes/{scene_idx}/shots/revisions")
def list_scene_shot_revisions(story_id: str, scene_idx: int):
    _, scene_id = _scene_for(story_id, scene_idx)
    with ProductionStore(production_database_path()) as store:
        revisions = store.list_shot_plan_revisions(story_id, scene_id)
    return {"revisions": revisions}


@router.patch("/api/stories/{story_id}/scenes/{scene_idx}/shots/{shot_id}")
def revise_scene_shot(story_id: str, scene_idx: int, shot_id: str, body: dict = Body(default=None)):
    _, scene_id = _scene_for(story_id, scene_idx)
    visual_context = str((body or {}).get("visual_context") or "").strip()
    if not visual_context:
        raise HTTPException(status_code=400, detail="visual_context is required")
    try:
        with ProductionStore(production_database_path()) as store:
            revision = store.revise_shot(story_id, scene_id, shot_id, visual_context=visual_context)
            shots = store.list_shots(story_id, scene_id, revision=revision)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"scene_id": scene_id, "revision": revision, "shots": [shot.__dict__ for shot in shots]}


@router.patch("/api/stories/{story_id}/scenes/{scene_idx}/shots/{shot_id}/lock")
def lock_scene_shot(story_id: str, scene_idx: int, shot_id: str, body: dict = Body(default=None)):
    _, scene_id = _scene_for(story_id, scene_idx)
    if not shot_id.startswith(f"{scene_id}-shot-"):
        raise HTTPException(status_code=400, detail="Shot does not belong to this scene")
    with ProductionStore(production_database_path()) as store:
        shots = store.list_shots(story_id, scene_id)
        if not any(shot.id == shot_id for shot in shots):
            raise HTTPException(status_code=404, detail="Shot not found")
        locked = bool((body or {}).get("locked", True))
        lock = store.set_lock(story_id, "shot", shot_id, locked)
    return {"shot_id": shot_id, "locked": lock is not None, "locked_at": lock.locked_at if lock else None}


async def _run_shot_job(run_id: str) -> None:
    """Claim one queued shot job on a GPU-capable local worker."""
    worker = ProductionWorker(
        production_database_path(),
        worker_id=f"shot-gpu-{uuid.uuid4().hex[:8]}",
        capabilities=("gpu",),
        job_types=("shot.generate",),
        run_id=run_id,
        lease_seconds=900,
    )

    def generate(job, progress):
        payload = job.payload
        story_id = payload["story_id"]
        scene_idx = int(payload["scene_idx"])
        shot_id = payload["shot_id"]
        story_dir = generated_story_dir(story_id)
        manifest_path = story_dir / f"{story_id}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        progress("image", "Checking ComfyUI", 0.05)
        import sys
        sys.path.insert(0, str(STORY_VIEWER_DIR))
        from comfyui_utils import generate_image, is_running
        if not is_running().get("running"):
            raise RuntimeError("ComfyUI is not running -- start a GPU worker first")
        safe_shot = re.sub(r"[^a-zA-Z0-9_-]+", "-", shot_id)
        progress("image", "Generating candidate artwork", 0.15)
        filename = generate_image(
            prompt=payload["visual_context"],
            output_prefix=f"{story_id}_{safe_shot}_r{payload['revision']}",
            output_dir=str(story_dir),
            seed=hash(f"{story_id}:{shot_id}:{payload['revision']}") % (2**32 - 1),
            timeout=900,
            worker_kind="gpu",
        )
        if not filename:
            raise RuntimeError("ComfyUI did not return a shot image")
        progress("asset", "Recording candidate provenance", 0.9)
        manifest["scenes"][scene_idx].setdefault("image_filenames", []).append(filename)
        atomic_write_json(manifest_path, manifest)
        with ProductionStore(production_database_path()) as store:
            store.register_asset(
                story_id=story_id,
                scene_id=shot_id,
                asset_type="image",
                path=str(story_dir / filename),
                generation_fingerprint=f"shot:{shot_id}:revision:{payload['revision']}",
                metadata={"shot_id": shot_id, "scene_idx": scene_idx, "revision": payload["revision"]},
            )
        return {"filename": filename, "shot_id": shot_id}

    await worker.run_once(generate)
    finalize_run_from_jobs(run_id)


async def recover_shot_jobs() -> None:
    """Resume durable shot jobs after a local server restart."""
    with ProductionStore(production_database_path()) as store:
        run_ids = {
            job.run_id for job in store.list_runnable_jobs()
            if job.job_type == "shot.generate"
        }
    for run_id in run_ids:
        asyncio.create_task(_run_shot_job(run_id))


@router.post("/api/stories/{story_id}/scenes/{scene_idx}/shots/{shot_id}/generate")
async def generate_scene_shot(story_id: str, scene_idx: int, shot_id: str):
    _, scene_id = _scene_for(story_id, scene_idx)
    with ProductionStore(production_database_path()) as store:
        shots = store.list_shots(story_id, scene_id)
    shot = next((item for item in shots if item.id == shot_id), None)
    if shot is None:
        raise HTTPException(status_code=404, detail="Plan this shot before generating it")
    run_id = f"shot-{uuid.uuid4().hex[:12]}"
    payload = {
        "story_id": story_id,
        "scene_idx": scene_idx,
        "shot_id": shot.id,
        "revision": shot.revision,
        "visual_context": shot.visual_context,
    }
    start_task(run_id, story_id=story_id, kind="shot_generate", metadata=payload)
    enqueue_task_job(
        run_id,
        job_id=f"{run_id}-image",
        job_type="shot.generate",
        payload=payload,
        required_capabilities=("gpu",),
    )
    asyncio.create_task(_run_shot_job(run_id))
    return {"run_id": run_id, "status": "queued", "shot_id": shot_id}


@router.post("/api/stories/{story_id}/scenes/{scene_idx}/shots/revisions/{revision}/restore")
def restore_scene_shot_revision(story_id: str, scene_idx: int, revision: int):
    _, scene_id = _scene_for(story_id, scene_idx)
    try:
        with ProductionStore(production_database_path()) as store:
            restored = store.restore_shot_plan_revision(story_id, scene_id, revision=revision)
            shots = store.list_shots(story_id, scene_id, revision=restored)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"revision": restored, "shots": [shot.__dict__ for shot in shots]}


def _scene_shot_timeline(story_id: str, scene_idx: int):
    scene, scene_id = _scene_for(story_id, scene_idx)
    with ProductionStore(production_database_path()) as store:
        stored_shots = store.list_shots(story_id, scene_id)
        approved_assets = {}
        for shot in stored_shots:
            asset = store.get_current_asset(story_id, shot.id, "image")
            if asset is not None:
                approved_assets[shot.id] = asset.path
    shots = [
        ShotSpec(
            id=shot.id, scene_id=shot.scene_id, order=shot.order, purpose=shot.purpose,
            shot_type=shot.shot_type, duration_seconds=shot.duration_seconds,
            visual_context=shot.visual_context,
        )
        for shot in stored_shots
    ]
    segments = build_shot_timeline(
        scene_id=scene_id,
        scene_start=0,
        scene_duration=float(scene.get("audio_duration") or 0),
        shots=shots,
        approved_assets=approved_assets,
    )
    return scene_id, segments


@router.get("/api/stories/{story_id}/scenes/{scene_idx}/shots/timeline")
def preview_scene_shot_timeline(story_id: str, scene_idx: int):
    try:
        scene_id, segments = _scene_shot_timeline(story_id, scene_idx)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"scene_id": scene_id, "segments": [segment.__dict__ for segment in segments]}


@router.post("/api/stories/{story_id}/scenes/{scene_idx}/shots/timeline")
def build_scene_shot_timeline(story_id: str, scene_idx: int):
    try:
        scene_id, segments = _scene_shot_timeline(story_id, scene_idx)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    target = write_shot_timeline(story_id, generated_story_dir(story_id), segments)
    return {"scene_id": scene_id, "path": str(target), "segments": [segment.__dict__ for segment in segments]}


def _story_shot_timeline(story_id: str):
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="Story not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes") or []
    shot_plans = {}
    approved_assets = {}
    with ProductionStore(production_database_path()) as store:
        for index in range(1, len(scenes) + 1):
            scene_id = f"scene-{index:02d}"
            stored = store.list_shots(story_id, scene_id)
            if not stored:
                continue
            shot_plans[scene_id] = [ShotSpec(
                id=shot.id, scene_id=shot.scene_id, order=shot.order,
                purpose=shot.purpose, shot_type=shot.shot_type,
                duration_seconds=shot.duration_seconds,
                visual_context=shot.visual_context,
            ) for shot in stored]
            for shot in stored:
                asset = store.get_current_asset(story_id, shot.id, "image")
                if asset is not None:
                    approved_assets[shot.id] = asset.path
    if not shot_plans:
        raise ValueError("Story has no semantic shot plans")
    return story_dir, scenes, build_full_story_shot_timeline(scenes, shot_plans, approved_assets)


@router.post("/api/stories/{story_id}/shots/timeline")
def build_story_shot_timeline_route(story_id: str):
    try:
        story_dir, _, segments = _story_shot_timeline(story_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    target = write_shot_timeline(story_id, story_dir, segments)
    return {"path": str(target), "segments": [segment.__dict__ for segment in segments]}


@router.get("/api/stories/{story_id}/timeline")
def get_story_timeline(story_id: str):
    timeline_path = generated_story_dir(story_id) / "working" / "timeline.json"
    if not timeline_path.is_file():
        raise HTTPException(status_code=404, detail="Canonical timeline not built")
    try:
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail="Canonical timeline is unreadable") from exc
    return {
        "story_id": story_id,
        "segments": timeline.get("segments") or [],
        "shot_segments": timeline.get("shot_segments") or [],
    }


@router.get("/api/stories/{story_id}/scenes/{scene_idx}/shots/{shot_id}/assets")
def list_shot_assets(story_id: str, scene_idx: int, shot_id: str):
    _, scene_id = _scene_for(story_id, scene_idx)
    if not shot_id.startswith(f"{scene_id}-shot-"):
        raise HTTPException(status_code=400, detail="Shot does not belong to this scene")
    with ProductionStore(production_database_path()) as store:
        assets = [
            asset for asset in store.list_assets(story_id)
            if asset.scene_id == shot_id and asset.asset_type == "image"
        ]
    return {"assets": [{
        "id": asset.id,
        "status": asset.status,
        "filename": Path(asset.path).name,
        "url": generated_asset_url(story_id, Path(asset.path).name),
        "revision": asset.metadata.get("revision"),
    } for asset in assets]}


@router.post("/api/stories/{story_id}/scenes/{scene_idx}/shots/{shot_id}/assets/{asset_id}/approve")
def approve_shot_asset(story_id: str, scene_idx: int, shot_id: str, asset_id: str):
    _, scene_id = _scene_for(story_id, scene_idx)
    if not shot_id.startswith(f"{scene_id}-shot-"):
        raise HTTPException(status_code=400, detail="Shot does not belong to this scene")
    with ProductionStore(production_database_path()) as store:
        asset = store.get_asset(asset_id)
        if asset is None or asset.story_id != story_id or asset.scene_id != shot_id or asset.asset_type != "image":
            raise HTTPException(status_code=404, detail="Shot candidate not found")
        approved = store.approve_asset(asset_id)
    return {"id": approved.id, "status": approved.status}
