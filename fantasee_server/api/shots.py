"""Semantic shot-plan endpoints for the Studio editor."""

from __future__ import annotations

import asyncio
import json
import re
import uuid

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
from fantasee_server.shot_planning import plan_semantic_shots, validate_shot_plan
from fantasee_server.state import atomic_write_json


router = APIRouter(tags=["shots"])


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
