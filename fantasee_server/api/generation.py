"""Generation pipeline endpoints.

Owns the long-horizon story generation flow:

* ``/api/seed-suggestions`` — ask the LLM for N distinct story
  seeds (title + description + style + tone) for a concept, so the
  picker UI can show variety.
* ``/api/generate`` — kick off a full story generation. The handler
  spawns ``generate_story.py`` as a subprocess and streams its
  ``__PROGRESS__:`` / ``__RESULT__:`` markers to the WebSocket.
* ``/api/generate/queue`` — schedule multiple generations to run
  one after the other (the parent task aggregates per-item status).
* ``/api/generate/tasks`` and ``/api/generate/tasks/{id}`` — poll
  the in-memory task store for status.

The actual generation subprocess (``generate_story.py``) and the
final completion pass (regenerate/repair/render/plex) live in
separate modules — this file is just the HTTP layer that
orchestrates them and streams progress to the WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Optional

from fastapi import APIRouter, Body, HTTPException

from fantasee_server.library import _complete_story_for_library
from fantasee_server.models import GenerateRequest, QueueRequest, SeedRequest
from fantasee_server.paths import STORY_VIEWER_DIR
import fantasee_server.paths as _paths
import fantasee_server.state as _state
from fantasee_server.seed import SEED_SYSTEM, _parse_seed_response
from fantasee_server.state import (
    _broadcast_ws_json,
    _broadcast_ws_json_from_thread,
    _generation_tasks,
    _websocket_clients,
    _resolve_env_var,
    new_uuid,
    now,
)


router = APIRouter(tags=["generation"])


# ── Seed suggestions ──────────────────────────────────────────────

@router.post("/api/seed-suggestions")
async def seed_suggestions(req: SeedRequest):
    """Return N distinct story seeds for the given concept.

    The LLM picks the seeds' style + tone per item, so the picker can
    show variety without locking the user into one combination.
    """
    concept = (req.concept or "").strip()
    if len(concept) < 10:
        raise HTTPException(status_code=400,
                            detail="Concept must be at least 10 characters.")
    count = max(1, min(6, int(req.count or 3)))

    sys.path.insert(0, str(STORY_VIEWER_DIR))
    # call_llm lives in generate_story.py; importing it here is fine because
    # generate_story.py is a sibling module with no side effects at import.
    from generate_story import call_llm

    user_prompt = f"""Concept: {concept}
Style baseline: {req.style}
Tone baseline: {req.tone}
Characters hint: {req.characters or "(none)"}

Generate exactly {count} distinct story seeds. Output ONLY the JSON array."""

    raw = call_llm(SEED_SYSTEM, user_prompt, temperature=0.9)
    if not raw:
        raise HTTPException(status_code=500,
                            detail="LLM did not return any seed suggestions.")

    try:
        seeds = _parse_seed_response(raw, count)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=500,
                            detail=f"Could not parse seed response: {e}")

    return {"seeds": seeds, "style": req.style, "tone": req.tone}


# ── Single generation ─────────────────────────────────────────────

async def _run_generation(task_id: str, req: GenerateRequest):
    """Run story generation, then complete/render/export before marking done."""
    script = STORY_VIEWER_DIR / "generate_story.py"
    last_progress_error: str | None = None
    generated_result: dict | None = None

    cmd = [
        sys.executable, str(script),
        "--concept", req.story_concept,
        "--scenes", str(req.num_scenes),
        "--images-per-scene", str(req.images_per_scene),
        "--style", req.style,
        "--tone", req.tone,
        "--voice", getattr(req, "voice_preset", "Dean"),
    ]
    if req.characters:
        cmd += ["--characters", req.characters]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "XIAOMI_API_KEY": _resolve_env_var("XIAOMI_API_KEY"),
             "XIAOMI_BASE_URL": _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")},
    )

    # Read stdout line by line, parse progress markers
    async def read_stdout():
        nonlocal generated_result, last_progress_error
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            if text.startswith("__PROGRESS__:"):
                try:
                    data = json.loads(text[13:])
                    status = data.get("status", "running")
                    message = data.get("message", "")
                    progress = data.get("progress")
                    if status in ("done", "complete"):
                        status = "running"
                        message = message or "Generated draft; completing assets..."
                        if progress is None:
                            progress = 0.78

                    update = {
                        "id": task_id,
                        "status": status,
                        "message": message,
                    }
                    if progress is not None:
                        update["progress"] = progress
                    _generation_tasks[task_id].update(update)

                    # Push to all websocket clients
                    payload = {
                        "type": "task_update",
                        "task_id": task_id,
                        "status": status,
                        "message": message,
                    }
                    if progress is not None:
                        payload["progress"] = progress
                    if status == "error" and message:
                        last_progress_error = message

                    for ws in _websocket_clients[:]:
                        try:
                            await ws.send_json(payload)
                        except Exception:
                            pass
                except json.JSONDecodeError:
                    pass

            elif text.startswith("__RESULT__:"):
                try:
                    data = json.loads(text[11:])
                    generated_result = data
                    _generation_tasks[task_id].update({
                        "status": "running",
                        "message": f"Generated draft: {data.get('title', 'Unknown')}. Completing assets...",
                        "progress": 0.78,
                        "result": data,
                    })
                    await _broadcast_ws_json({
                        "type": "task_update",
                        "task_id": task_id,
                        "status": "running",
                        "progress": 0.78,
                        "message": _generation_tasks[task_id]["message"],
                    })
                    # Reload story cache so the draft appears while final
                    # completion/render/export continues.
                    _state._stories_cache = _paths.load_stories()
                except json.JSONDecodeError:
                    pass

    async def read_stderr():
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if text and "RequestsDependencyWarning" not in text and "warnings.warn(" not in text:
                _generation_tasks[task_id].setdefault("errors", []).append(text)

    await asyncio.gather(read_stdout(), read_stderr())
    await process.wait()

    if process.returncode != 0:
        errors = _generation_tasks[task_id].get("errors", [])
        failure_detail = last_progress_error
        if not failure_detail:
            failure_detail = next(
                (line for line in reversed(errors)
                 if "RequestsDependencyWarning" not in line and "warnings.warn(" not in line),
                None,
            )
        if not failure_detail:
            failure_detail = errors[-1] if errors else "Unknown"
        _generation_tasks[task_id].update({
            "status": "error",
            "message": f"Failed with exit code {process.returncode}",
            "progress": 0,
            "error_detail": failure_detail,
        })
        payload = {
            "type": "task_update", "task_id": task_id,
            "status": "error", "message": f"Failed: {failure_detail}",
        }
        for ws in _websocket_clients[:]:
            try:
                await ws.send_json(payload)
            except Exception:
                pass
        return

    if not generated_result or not generated_result.get("id"):
        _generation_tasks[task_id].update({
            "status": "error",
            "message": "Generation finished without a story result.",
            "progress": 0,
            "error_detail": "generate_story.py did not emit __RESULT__",
        })
        await _broadcast_ws_json({
            "type": "task_update",
            "task_id": task_id,
            "status": "error",
            "message": "Failed: generation finished without a story result.",
        })
        return

    story_id = generated_result["id"]
    loop = asyncio.get_running_loop()

    def completion_progress(stage: str, msg: str, pct: float) -> None:
        progress = 0.78 + max(0.0, min(1.0, float(pct))) * 0.21
        _generation_tasks[task_id].update({
            "status": "running",
            "stage": stage,
            "message": msg,
            "progress": progress,
        })
        _broadcast_ws_json_from_thread(loop, {
            "type": "task_update",
            "task_id": task_id,
            "kind": "generate",
            "story_id": story_id,
            "status": "running",
            "stage": stage,
            "message": msg,
            "progress": progress,
        })

    try:
        completion = await asyncio.to_thread(
            _complete_story_for_library,
            story_id,
            completion_progress,
        )
        generated_result["completion"] = completion.get("completion")
        generated_result["completion_steps"] = completion.get("steps", [])
        _generation_tasks[task_id].update({
            "status": "done",
            "stage": "complete",
            "message": f"Complete: {generated_result.get('title', story_id)}",
            "progress": 1.0,
            "result": generated_result,
        })
        global _state  # noqa: F824  (state lives in fantasee_server.state)
        _state._stories_cache = _paths.load_stories()
        await _broadcast_ws_json({
            "type": "task_update",
            "task_id": task_id,
            "kind": "generate",
            "story_id": story_id,
            "status": "done",
            "stage": "complete",
            "progress": 1.0,
            "message": _generation_tasks[task_id]["message"],
        })
    except Exception as e:
        detail = str(e)
        _generation_tasks[task_id].update({
            "status": "error",
            "stage": "completion_failed",
            "message": f"Completion failed: {detail}",
            "progress": _generation_tasks[task_id].get("progress", 0.78),
            "error_detail": detail,
        })
        await _broadcast_ws_json({
            "type": "task_update",
            "task_id": task_id,
            "kind": "generate",
            "story_id": story_id,
            "status": "error",
            "stage": "completion_failed",
            "message": f"Failed: {detail}",
        })


@router.post("/api/generate")
async def start_generation(req: GenerateRequest):
    """Start a new story generation task."""
    task_id = new_uuid()[:8]
    _generation_tasks[task_id] = {
        "id": task_id,
        "status": "queued",
        "progress": 0,
        "message": "Queued for generation...",
        "request": req.model_dump(),
        "created_at": now(),
    }

    # Notify websocket clients
    for ws in _websocket_clients[:]:
        try:
            await ws.send_json({
                "type": "task_update",
                "task_id": task_id,
                "status": "queued",
                "progress": 0,
                "message": "Queued for generation..."
            })
        except Exception:
            pass

    # Launch the generation pipeline in the background
    asyncio.create_task(_run_generation(task_id, req))

    return {
        "task_id": task_id,
        "status": "queued",
        "message": "Story generation started.",
    }


# ── Generation queue (long-horizon tasks) ─────────────────────────

async def _run_queue(queue_id: str, items: list[GenerateRequest]) -> None:
    """Process a list of story generations sequentially.

    The queue task acts as a parent in the task tree: each sub-task gets its
    own task_id and is tracked under `_generation_tasks`, but the queue task
    itself surfaces an overall progress and per-item status via WebSocket.
    """
    total = len(items)
    queue_task = _generation_tasks[queue_id]
    queue_task["status"] = "running"
    queue_task["progress"] = 0
    queue_task["message"] = f"Queue started ({total} stories)"

    completed_titles: list[str] = []
    failed_titles: list[str] = []

    for idx, item in enumerate(items):
        sub_id = f"{queue_id}-{idx:02d}"
        _generation_tasks[sub_id] = {
            "id": sub_id,
            "parent": queue_id,
            "status": "queued",
            "progress": 0,
            "message": f"Sub-task {idx + 1}/{total}",
            "request": item.model_dump(),
            "created_at": now(),
        }

        # Notify websocket of the sub-task start
        for ws in _websocket_clients[:]:
            try:
                await ws.send_json({
                    "type": "task_update",
                    "task_id": sub_id,
                    "parent": queue_id,
                    "status": "running",
                    "progress": 0,
                    "message": f"Starting story {idx + 1}/{total}: {item.story_concept[:50]}",
                })
            except Exception:
                pass

        try:
            # Run the sub-task synchronously (it manages its own WebSocket updates
            # via _run_generation's emit() processing). We just wait for it.
            await _run_generation(sub_id, item)
            sub = _generation_tasks.get(sub_id, {})
            if sub.get("status") == "done":
                completed_titles.append(sub.get("message", item.story_concept[:60]))
            else:
                failed_titles.append(item.story_concept[:60])
        except Exception as e:
            print(f"[queue] sub-task {sub_id} crashed: {e}", file=sys.stderr)
            failed_titles.append(item.story_concept[:60])

        # Update queue progress
        overall = round((idx + 1) / total, 3)
        queue_task["progress"] = overall
        queue_task["message"] = f"Story {idx + 1}/{total} done ({len(completed_titles)} OK, {len(failed_titles)} failed)"

        for ws in _websocket_clients[:]:
            try:
                await ws.send_json({
                    "type": "task_update",
                    "task_id": queue_id,
                    "status": "running",
                    "progress": overall,
                    "message": queue_task["message"],
                })
            except Exception:
                pass

    queue_task["status"] = "done"
    queue_task["progress"] = 1.0
    queue_task["message"] = f"Queue complete: {len(completed_titles)} succeeded, {len(failed_titles)} failed"
    queue_task["completed"] = completed_titles
    queue_task["failed"] = failed_titles

    # Reload story cache so the new stories show up in /api/stories
    _state._stories_cache = _paths.load_stories()

    for ws in _websocket_clients[:]:
        try:
            await ws.send_json({
                "type": "task_update",
                "task_id": queue_id,
                "status": "done",
                "progress": 1.0,
                "message": queue_task["message"],
            })
        except Exception:
            pass


@router.post("/api/generate/queue")
async def start_generation_queue(req: QueueRequest):
    """Queue multiple story generations to run consecutively.

    Useful for long-horizon batch runs ("generate 5 stories overnight").
    Each item is processed in order; the user can navigate away and watch
    other stories while the queue continues in the background.
    """
    if not req.items:
        raise HTTPException(status_code=400, detail="Queue is empty")
    if len(req.items) > 20:
        raise HTTPException(status_code=400, detail="Queue max length is 20")

    queue_id = f"q-{new_uuid()[:6]}"
    _generation_tasks[queue_id] = {
        "id": queue_id,
        "kind": "queue",
        "status": "queued",
        "progress": 0,
        "message": f"Queued {len(req.items)} stories",
        "items": [it.model_dump() for it in req.items],
        "item_count": len(req.items),
        "created_at": now(),
    }

    # Notify websocket clients
    for ws in _websocket_clients[:]:
        try:
            await ws.send_json({
                "type": "task_update",
                "task_id": queue_id,
                "status": "queued",
                "progress": 0,
                "message": f"Queued {len(req.items)} stories",
            })
        except Exception:
            pass

    asyncio.create_task(_run_queue(queue_id, list(req.items)))

    return {
        "queue_id": queue_id,
        "status": "queued",
        "item_count": len(req.items),
        "message": f"Queue of {len(req.items)} stories accepted.",
    }


@router.get("/api/generate/tasks")
def list_tasks():
    """List all generation tasks."""
    return {"tasks": list(_generation_tasks.values())}


@router.get("/api/generate/tasks/{task_id}")
def get_task(task_id: str):
    """Get the status of a generation task."""
    task = _generation_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
