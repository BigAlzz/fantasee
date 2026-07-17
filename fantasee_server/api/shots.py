"""Semantic shot-plan endpoints for the Studio editor."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException

from fantasee_server.production_runtime import production_database_path
from fantasee_server.production_store import ProductionStore
from fantasee_server.paths import generated_story_dir
from fantasee_server.shot_planning import plan_semantic_shots, validate_shot_plan


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
