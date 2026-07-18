"""Story action endpoints.

Long-running actions that operate on an existing story:

* ``/extend``        — append N new scenes (in-line, streams progress).
* ``/regenerate``    — wipe + re-run the generation pipeline (background task).
* ``/repair``        — plan + execute asset repair (two-phase: GET = preview, POST = run).
* ``/improve-loop``  — iterative critic→improve cycles (background task).
* ``/improve``       — single-pass auto-improve (background task).
* ``/add-images``    — bulk-add images to scenes below the target count (sync).

Heavy lifting lives in ``story_actions.py`` (extend/regenerate/repair)
and ``fantasee_server.improver`` (improve/improve-loop). This module
is the HTTP wrapper that wires them up to the WebSocket progress
channel.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from fantasee_server.background import (
    _push_story_action_progress,
    _run_story_action_background_task,
    _truthy,
)
from fantasee_server.improver import (
    _run_auto_improve_sync,
    _run_improve_loop_sync,
)
from fantasee_server.models import ExtendRequest, RegenRequest, RepairRequest
from fantasee_server.paths import (
    STORY_VIEWER_DIR,
    generated_story_dir,
)
from fantasee_server.state import (
    _broadcast_ws_json,
    _generation_tasks,
    _websocket_clients,
    atomic_write_json,
    new_uuid,
    now,
)


router = APIRouter(tags=["actions"])


@router.patch("/api/stories/{story_id}/scenes/{scene_idx}")
async def update_story_scene(story_id: str, scene_idx: int, body: dict = Body(default=None)):
    """Persist a scene revision and invalidate its derived media."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes") or []
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")

    payload = body or {}
    allowed = {"title", "prompt", "narration"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown scene fields: {', '.join(unknown)}")
    if not payload:
        raise HTTPException(status_code=400, detail="At least one scene field is required")

    scene = scenes[scene_idx]
    stale = set(scene.get("stale_outputs") or [])
    if "title" in payload:
        title = str(payload["title"]).strip()
        if not title:
            raise HTTPException(status_code=400, detail="Scene title cannot be empty")
        scene["title"] = title
    if "prompt" in payload:
        prompt = str(payload["prompt"]).strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Scene visual direction cannot be empty")
        if prompt != str(scene.get("prompt") or ""):
            scene["prompt"] = prompt
            stale.update({"images", "scene_video", "full_video", "plex"})
    if "narration" in payload:
        narration = str(payload["narration"]).strip()
        if not narration:
            raise HTTPException(status_code=400, detail="Scene narration cannot be empty")
        current = str(scene.get("narration") or scene.get("narration_text") or "")
        if narration != current:
            scene["narration"] = narration
            scene["narration_text"] = narration
            stale.update({"audio", "subtitles", "scene_video", "full_video", "plex"})

    stale_order = ("images", "audio", "subtitles", "scene_video", "full_video", "plex")
    scene["stale_outputs"] = [kind for kind in stale_order if kind in stale]
    scene["editor_revision"] = now()
    manifest["status"] = "draft"
    atomic_write_json(manifest_path, manifest)
    return {"status": "ok", "scene": scene, "stale_outputs": scene["stale_outputs"]}


@router.patch("/api/stories/{story_id}/brief")
async def update_story_brief(story_id: str, body: dict = Body(default=None)):
    """Persist story-level creative direction before an explicit rebuild."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = body or {}
    allowed = {"story_concept", "description", "style", "tone", "voice_preset", "narration_style", "characters", "world_context", "voice_assignments", "num_scenes", "images_per_scene"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown story brief fields: {', '.join(unknown)}")
    if not payload:
        raise HTTPException(status_code=400, detail="At least one story brief field is required")
    for field, value in payload.items():
        if field in {"num_scenes", "images_per_scene"}:
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"{field} must be an integer") from exc
            limit = 24 if field == "num_scenes" else 12
            if number < 1 or number > limit:
                raise HTTPException(status_code=400, detail=f"{field} must be between 1 and {limit}")
            manifest[field] = number
            continue
        text = str(value).strip()
        if field == "story_concept" and len(text) < 10:
            raise HTTPException(status_code=400, detail="Story concept must be at least 10 characters")
        if field in {"style", "tone", "voice_preset"} and not text:
            raise HTTPException(status_code=400, detail=f"{field} cannot be empty")
        manifest[field] = text
    if "story_concept" in payload:
        manifest["description"] = manifest["story_concept"][:200]
    if "style" in payload or "tone" in payload:
        tags = list(manifest.get("tags") or ["", ""])
        while len(tags) < 2:
            tags.append("")
        if "style" in payload:
            tags[0] = manifest["style"]
        if "tone" in payload:
            tags[1] = manifest["tone"]
        manifest["tags"] = tags
    manifest["status"] = "draft"
    manifest["story_brief_revision"] = int(now())
    atomic_write_json(manifest_path, manifest)
    return {"status": "ok", "story_id": story_id, "manifest": manifest}


_CONTEXT_NAME_STOPWORDS = {
    "A", "An", "And", "Against", "At", "As", "Before", "Beyond", "But",
    "By", "Chapter", "Cold", "Dawn", "During", "Earth", "Every", "From",
    "He", "Her", "His", "In", "Into", "It", "Its", "Meanwhile", "My",
    "No", "On", "One", "Only", "Over", "Scene", "She", "The", "Their",
    "There", "This", "Through", "To", "Under", "When", "Where", "With",
    "You",
}
_CONTEXT_NAME_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?\b")


def _scan_story_context(manifest: dict) -> tuple[str, str, int]:
    """Recover a useful first canon pass from an older story manifest.

    This intentionally uses deterministic evidence already present in the
    story. It gives older stories an editable context seed without pretending
    that an inferred character sheet is authoritative or silently invoking an
    external provider.
    """
    scenes = manifest.get("scenes") or []
    source_parts = [
        str(manifest.get("story_concept") or "").strip(),
        str(manifest.get("description") or "").strip(),
    ]
    for scene in scenes:
        source_parts.extend(
            str(scene.get(field) or "").strip()
            for field in ("narration", "narration_text", "narrative", "prompt")
        )
    source_text = "\n".join(part for part in source_parts if part)

    names: list[str] = []
    for match in _CONTEXT_NAME_RE.findall(source_text):
        candidate = " ".join(match.split())
        first_word = candidate.split()[0]
        if first_word in _CONTEXT_NAME_STOPWORDS or candidate in names:
            continue
        if len(candidate) < 3 or candidate.lower() in {"story", "scene", "visual"}:
            continue
        names.append(candidate)
        if len(names) >= 12:
            break

    premise = str(manifest.get("story_concept") or manifest.get("description") or "").strip()
    if not premise:
        premise = "Context recovered from the existing story scenes."
    universe = str(manifest.get("universe_name") or manifest.get("world_name") or manifest.get("title") or "Untitled universe").strip()
    style = str(manifest.get("style") or "").strip()
    tone = str(manifest.get("tone") or "").strip()
    characters = "\n".join(
        f"{name} (story character) | Biography: Recovered from the existing scene text. "
        "Review and deepen this sheet before treating it as canon."
        for name in names
    ) or "No named characters were confidently recovered; review the scene editor and add the cast manually."
    rules = "Preserve the established setting, cause and effect, character continuity, and visual language already present in the scenes."
    if style or tone:
        rules += f" Direction: {style or 'existing visual language'}; {tone or 'existing tone'}."
    world_context = "\n\n".join([
        f"Universe: {universe}",
        f"Premise: {premise}",
        f"Rules and continuity: {rules}",
        f"Characters:\n{characters}",
        "Recovery note: This canon seed was inferred from the saved story manifest and scene text. Edit it to make the world authoritative.",
    ])
    return world_context, characters, len(names)


@router.post("/api/stories/{story_id}/context/scan")
async def scan_story_context(story_id: str, body: dict = Body(default=None)):
    """Persist an editable canon seed for stories created before world context."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = body or {}
    force = bool(payload.get("force", False))
    has_context = bool(str(manifest.get("world_context") or "").strip())
    has_characters = bool(str(manifest.get("characters") or "").strip() or str(manifest.get("voice_assignments") or "").strip())
    if has_context and has_characters and not force:
        return {
            "status": "existing",
            "story_id": story_id,
            "manifest": manifest,
            "summary": {"characters": 0, "scenes": len(manifest.get("scenes") or []), "scanned": False},
        }

    world_context, characters, character_count = _scan_story_context(manifest)
    manifest["world_context"] = world_context
    manifest["characters"] = characters
    manifest["context_scan"] = {
        "method": "manifest-scene-scan",
        "source_revision": manifest.get("story_brief_revision") or manifest.get("editor_revision") or int(now()),
        "scanned_at": int(now()),
        "scene_count": len(manifest.get("scenes") or []),
        "character_count": character_count,
    }
    manifest["status"] = "draft"
    atomic_write_json(manifest_path, manifest)
    return {
        "status": "scanned",
        "story_id": story_id,
        "manifest": manifest,
        "summary": {"characters": character_count, "scenes": len(manifest.get("scenes") or []), "scanned": True},
    }


# ── Extend ────────────────────────────────────────────────────────

@router.post("/api/stories/{story_id}/extend")
async def extend_story(story_id: str, body: dict = Body(default=None)):
    """Add N new scenes to the end of a story.

    Body:
      - ``scenes`` (int, optional): how many new scenes to generate.
      - ``duration_minutes`` (float, optional): approximate runtime to add;
        the current average scene duration determines the scene count.
      - ``images_per_scene`` (int, optional): override the story's default.
      - ``voice`` / ``tone`` (str, optional): override the story's defaults.
      - ``prompt`` (str, optional): continuation or ending instruction.

    Per-scene failures are isolated: a bad TTS or image-gen call for one
    scene is logged and skipped, and the manifest is written after every
    successful scene so a partial extension is always recoverable.
    """
    story_dir = generated_story_dir(story_id)
    if not (story_dir / f"{story_id}.json").exists():
        raise HTTPException(status_code=404, detail="Story not found")

    req = ExtendRequest(**(body or {}))
    if req.scenes is not None and req.scenes < 1:
        raise HTTPException(status_code=400, detail="scenes must be at least 1")
    if req.duration_minutes is not None and not 0 < req.duration_minutes <= 240:
        raise HTTPException(status_code=400, detail="duration_minutes must be between 0 and 240")
    if req.scenes is None and req.duration_minutes is None:
        req.scenes = 5
    scenes_n = max(1, min(50, int(req.scenes or 5)))

    # Allow voice/tone override via the request body without rewriting
    # the manifest (we mutate the in-memory copy in story_actions).
    sys.path.insert(0, str(STORY_VIEWER_DIR))
    import story_actions

    if req.voice or req.tone or req.images_per_scene:
        # Read the manifest, override the fields, write it back so
        # story_actions picks them up.
        manifest_path = story_dir / f"{story_id}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if req.voice:
            manifest["voice_preset"] = req.voice
        if req.tone:
            manifest["tone"] = req.tone
            tags = manifest.get("tags") or []
            if len(tags) >= 2:
                tags[1] = req.tone
                manifest["tags"] = tags
        if req.images_per_scene:
            manifest["images_per_scene"] = req.images_per_scene
        atomic_write_json(manifest_path, manifest)

    try:
        result = story_actions.apply_extend(
            story_id, scenes=scenes_n,
            duration_minutes=req.duration_minutes,
            prompt=req.prompt[:4000],
            progress=lambda stage, msg, pct: _push_story_action_progress(
                story_id, stage, msg, pct, kind="extend"),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extend failed: {e}")

    return result


# ── Regenerate ───────────────────────────────────────────────────

@router.post("/api/stories/{story_id}/regenerate")
async def regenerate_story_endpoint(story_id: str, body: dict = Body(default=None)):
    """Wipe the story and re-run the generation pipeline from scratch.

    Body:
      - ``backup`` (bool, default true): copy the story dir to
        ``stories/.trash/<slug>-<timestamp>`` before wiping.

    The endpoint spawns a background task that:
    1. Reads the saved concept / style / tone from the manifest.
    2. Optionally copies the story to ``.trash/``.
    3. Deletes everything in the story dir and re-creates the layout.
    4. Re-runs the generation pipeline in-process.
    """
    story_dir = generated_story_dir(story_id)
    if not (story_dir / f"{story_id}.json").exists():
        raise HTTPException(status_code=404, detail="Story not found")

    req = RegenRequest(**(body or {}))

    # Preview mode: walk the directory and report what would be deleted
    # + the would-be backup path. Lets the UI show a confirmation
    # dialog with the right size + on-disk footprint. Two trigger paths:
    #   - `dry_run: true` — always preview, never delete
    #   - `backup: false` without `force: true` — preview, requires force
    if req.dry_run or (not req.backup and not _truthy(body, "force", False)):
        files, total_bytes = [], 0
        for f in story_dir.rglob("*"):
            if f.is_file():
                files.append({"path": str(f.relative_to(story_dir)), "size": f.stat().st_size})
                total_bytes += f.stat().st_size
        return {
            "status": "preview",
            "story_id": story_id,
            "files_count": len(files),
            "bytes_freed": total_bytes,
            "files_sample": files[:20],
            "more_files": max(0, len(files) - 20),
            "note": ("Send {dry_run: false, backup: false, force: true} to delete without backup"
                     if req.dry_run
                     else "Send {backup: false, force: true} to delete without backup"),
        }

    task_id = f"regen-{new_uuid()[:6]}"
    _generation_tasks[task_id] = {
        "id": task_id,
        "kind": "regenerate",
        "story_id": story_id,
        "status": "running",
        "progress": 0,
        "message": "Re-generating story…",
        "stage": "discover",
        "created_at": now(),
    }

    async def _runner():
        loop = asyncio.get_event_loop()
        sys.path.insert(0, str(STORY_VIEWER_DIR))
        import story_actions

        def _progress(stage, msg, pct):
            _generation_tasks[task_id].update({"stage": stage, "progress": pct, "message": msg})
            for ws in _websocket_clients[:]:
                coro = ws.send_json({
                    "type": "task_update", "task_id": task_id,
                    "kind": "regenerate", "story_id": story_id,
                    "stage": stage, "status": "running", "progress": pct, "message": msg,
                })
                try:
                    asyncio.run_coroutine_threadsafe(coro, loop)
                except Exception:
                    pass

        try:
            result = await loop.run_in_executor(
                None,
                lambda: story_actions.regenerate_story(
                    story_id,
                    backup=req.backup,
                    progress_callback=_progress,
                ),
            )
            _generation_tasks[task_id].update({
                "status": "done", "stage": "complete", "progress": 1.0,
                "message": "Re-generation complete",
                "result": result,
            })
            for ws in _websocket_clients[:]:
                try:
                    await ws.send_json({
                        "type": "task_update", "task_id": task_id,
                        "kind": "regenerate", "story_id": story_id,
                        "status": "done", "stage": "complete", "progress": 1.0,
                        "message": "Re-generation complete",
                        "result": result,
                    })
                except Exception:
                    pass
        except Exception as e:
            _generation_tasks[task_id].update({
                "status": "error", "stage": "error",
                "message": f"Re-generation failed: {e}",
            })
            for ws in _websocket_clients[:]:
                try:
                    await ws.send_json({
                        "type": "task_update", "task_id": task_id,
                        "kind": "regenerate", "story_id": story_id,
                        "status": "error", "stage": "error",
                        "message": f"Re-generation failed: {e}",
                    })
                except Exception:
                    pass

    asyncio.create_task(_runner())
    return {
        "task_id": task_id,
        "status": "running",
        "story_id": story_id,
        "backup": req.backup,
        "message": "Re-generation started. Watch the progress panel for status.",
    }


# ── Repair ───────────────────────────────────────────────────────

@router.get("/api/stories/{story_id}/repair")
async def repair_story_preview(story_id: str):
    """Plan a repair: walk the manifest, list what's missing per scene.

    Two-phase design: the GET returns a preview the UI shows in a
    modal; the POST actually does the work.
    """
    story_dir = generated_story_dir(story_id)
    if not (story_dir / f"{story_id}.json").exists():
        raise HTTPException(status_code=404, detail="Story not found")
    sys.path.insert(0, str(STORY_VIEWER_DIR))
    import story_actions
    plan = story_actions.plan_repair(story_id)
    unfixable = getattr(story_actions, "UNFIXABLE_REPAIR_ACTIONS", set())
    return {
        "story_id": story_id,
        "scenes": [
            {
                "scene_idx": sr.scene_idx,
                "scene_key": sr.scene_key,
                "title": sr.title,
                "missing": sr.missing,
                "duplicate_image": sr.duplicate_image,
                "actions": sr.actions,
            }
            for sr in plan.scenes
        ],
        "scenes_checked": len(plan.scenes) + plan.skipped_complete,
        "scenes_to_repair": sum(1 for sr in plan.scenes if any(a not in unfixable for a in sr.actions)),
        "scenes_blocked": sum(1 for sr in plan.scenes if sr.actions and all(a in unfixable for a in sr.actions)),
        "scenes_already_complete": plan.skipped_complete,
    }


@router.post("/api/stories/{story_id}/repair")
async def repair_story_endpoint(story_id: str, body: dict = Body(default=None)):
    """Execute the repair plan from :func:`plan_repair`."""
    story_dir = generated_story_dir(story_id)
    if not (story_dir / f"{story_id}.json").exists():
        raise HTTPException(status_code=404, detail="Story not found")

    req = RepairRequest(**(body or {}))
    if req.dry_run:
        return await repair_story_preview(story_id)

    task_id = f"repair-{new_uuid()[:6]}"
    _generation_tasks[task_id] = {
        "id": task_id,
        "kind": "repair",
        "story_id": story_id,
        "status": "running",
        "progress": 0,
        "message": "Planning repair…",
        "stage": "discover",
        "created_at": now(),
    }

    async def _runner():
        loop = asyncio.get_event_loop()
        sys.path.insert(0, str(STORY_VIEWER_DIR))
        import story_actions

        def _progress(stage, msg, pct):
            _generation_tasks[task_id].update({"stage": stage, "progress": pct, "message": msg})
            for ws in _websocket_clients[:]:
                coro = ws.send_json({
                    "type": "task_update", "task_id": task_id,
                    "kind": "repair", "story_id": story_id,
                    "stage": stage, "status": "running", "progress": pct, "message": msg,
                })
                try:
                    asyncio.run_coroutine_threadsafe(coro, loop)
                except Exception:
                    pass

        try:
            plan = story_actions.plan_repair(story_id)
            _progress("repair", f"{plan.skipped_complete} scene(s) already complete, {sum(1 for sr in plan.scenes if sr.actions)} to repair", 0.05)
            result = await loop.run_in_executor(
                None,
                lambda: story_actions.apply_repair(story_id, plan, progress=_progress),
            )
            _generation_tasks[task_id].update({
                "status": "done", "stage": "complete", "progress": 1.0,
                "message": f"Repair complete: {result.scenes_repaired} scene(s) repaired",
                "result": result.to_dict(),
            })
            for ws in _websocket_clients[:]:
                try:
                    await ws.send_json({
                        "type": "task_update", "task_id": task_id,
                        "kind": "repair", "story_id": story_id,
                        "status": "done", "stage": "complete", "progress": 1.0,
                        "message": f"Repair complete: {result.scenes_repaired} scene(s) repaired",
                        "result": result.to_dict(),
                    })
                except Exception:
                    pass
        except Exception as e:
            _generation_tasks[task_id].update({
                "status": "error", "stage": "error",
                "message": f"Repair failed: {e}",
            })
            for ws in _websocket_clients[:]:
                try:
                    await ws.send_json({
                        "type": "task_update", "task_id": task_id,
                        "kind": "repair", "story_id": story_id,
                        "status": "error", "stage": "error",
                        "message": f"Repair failed: {e}",
                    })
                except Exception:
                    pass

    asyncio.create_task(_runner())
    return {
        "task_id": task_id,
        "status": "running",
        "message": "Repair started. Watch the progress panel for status.",
    }


# ── Improve-loop (iterative) ─────────────────────────────────────

@router.post("/api/stories/{story_id}/improve-loop")
async def improve_loop(story_id: str, body: dict = Body(default=None)):
    """Start iterative critic/improve cycles as a background task."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    task_id = f"improve-loop-{new_uuid()[:6]}"
    _generation_tasks[task_id] = {
        "id": task_id,
        "kind": "improve_loop",
        "story_id": story_id,
        "status": "running",
        "progress": 0,
        "message": "Starting improvement loop...",
        "stage": "queued",
        "request": body or {},
        "created_at": now(),
    }
    await _broadcast_ws_json({
        "type": "task_update",
        "task_id": task_id,
        "kind": "improve_loop",
        "story_id": story_id,
        "status": "running",
        "stage": "queued",
        "progress": 0,
        "message": "Starting improvement loop...",
    })
    asyncio.create_task(_run_story_action_background_task(
        task_id,
        story_id,
        "improve_loop",
        lambda progress: _run_improve_loop_sync(story_id, body or {}, progress=progress),
        lambda result: (
            f"Improvement target reached: {result.get('final_stars', 0)} stars"
            if result.get("status") == "target_reached"
            else f"Improvement loop complete: {result.get('final_stars', 0)} stars"
        ),
    ))
    return {
        "task_id": task_id,
        "status": "running",
        "story_id": story_id,
        "message": "Improvement loop started. Watch the progress panel for status.",
    }


# ── Bulk add images ──────────────────────────────────────────────

@router.post("/api/stories/{story_id}/add-images")
async def add_images_bulk(story_id: str, body: dict = Body(default=None)):
    """Add more images to scenes that have fewer than the target count."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    target_per_scene = (body or {}).get("images_per_scene", 2)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])

    sys.path.insert(0, str(STORY_VIEWER_DIR))
    from comfyui_utils import generate_image, is_running as comfyui_running
    status = comfyui_running()
    if not status.get("running", False):
        raise HTTPException(status_code=503, detail="ComfyUI not running")

    total_added = 0
    for i, sc in enumerate(scenes):
        current = len(sc.get("image_filenames", []))
        if current >= target_per_scene:
            continue

        scene_num = i + 1
        padded = f"{scene_num:02d}"
        safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', sc.get("title", "")).strip("_")[:30]

        for img_idx in range(current, target_per_scene):
            seed = hash(story_id + str(scene_num) + str(img_idx)) % (2**32 - 1)
            prefix = f"{story_id}_s{padded}_{safe_title}_{img_idx + 1:02d}"
            filename = generate_image(
                prompt=sc["prompt"],
                output_prefix=prefix,
                output_dir=str(story_dir),
                seed=seed,
                timeout=600,
            )
            if filename:
                sc.setdefault("image_filenames", []).append(filename)
                total_added += 1

    atomic_write_json(manifest_path, manifest)
    return {"status": "ok", "total_added": total_added}


# ── Improve (single-pass) ────────────────────────────────────────

@router.post("/api/stories/{story_id}/improve")
async def auto_improve(story_id: str, body: dict = Body(default=None)):
    """Start a one-pass auto-improve action as a background task."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    task_id = f"improve-{new_uuid()[:6]}"
    _generation_tasks[task_id] = {
        "id": task_id,
        "kind": "improve",
        "story_id": story_id,
        "status": "running",
        "progress": 0,
        "message": "Starting improvement...",
        "stage": "queued",
        "request": body or {},
        "created_at": now(),
    }
    await _broadcast_ws_json({
        "type": "task_update",
        "task_id": task_id,
        "kind": "improve",
        "story_id": story_id,
        "status": "running",
        "stage": "queued",
        "progress": 0,
        "message": "Starting improvement...",
    })
    asyncio.create_task(_run_story_action_background_task(
        task_id,
        story_id,
        "improve",
        lambda progress: _run_auto_improve_sync(story_id, body or {}, progress=progress),
        lambda result: f"Improve complete: {len(result.get('improved_scenes', []))} scene(s) improved",
    ))
    return {
        "task_id": task_id,
        "status": "running",
        "story_id": story_id,
        "message": "Improvement started. Watch the progress panel for status.",
    }
