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
from fantasee_server.production_runtime import (
    enqueue_task_job,
    find_active_task,
    finish_task,
    start_task,
    update_task,
    production_database_path,
    finalize_run_from_jobs,
    list_persisted_tasks,
)
from fantasee_server.production_store import ProductionStore
from fantasee_server.production_worker import ProductionWorker
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

async def _run_generation(task_id: str, req: GenerateRequest, job_progress=None):
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
    if getattr(req, "narration_style", ""):
        cmd += ["--narration-style", req.narration_style]
    world_parts = [part.strip() for part in (getattr(req, "world_context", ""), getattr(req, "voice_assignments", "")) if part and part.strip()]
    if world_parts:
        cmd += ["--world-context", "\n\n".join(world_parts)]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "XIAOMI_API_KEY": _resolve_env_var("XIAOMI_API_KEY"),
             "XIAOMI_BASE_URL": _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
             "FANTASEE_PRODUCTION_RUN_ID": task_id},
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
                    if job_progress and progress is not None:
                        job_progress(data.get("stage", "generate"), message, float(progress))
                    try:
                        update_task(
                            task_id,
                            stage=data.get("stage", "generate"),
                            progress=float(progress or 0),
                            message=message,
                        )
                    except Exception as exc:
                        print(f"[generation] durable progress update failed: {exc}", file=sys.stderr)

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
                    if job_progress:
                        job_progress("draft", _generation_tasks[task_id]["message"], 0.78)
                    try:
                        update_task(task_id, stage="draft", progress=0.78,
                                    message=_generation_tasks[task_id]["message"])
                    except Exception as exc:
                        print(f"[generation] durable draft update failed: {exc}", file=sys.stderr)
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
        if job_progress:
            job_progress("error", f"Failed: {failure_detail}", 0)
        try:
            finish_task(task_id, status="failed", message=f"Failed: {failure_detail}")
        except Exception as exc:
            print(f"[generation] durable failure update failed: {exc}", file=sys.stderr)
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
        if job_progress:
            job_progress("error", "Generation finished without a story result.", 0)
        try:
            finish_task(task_id, status="failed", message="Generation finished without a story result.")
        except Exception as exc:
            print(f"[generation] durable failure update failed: {exc}", file=sys.stderr)
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
        if job_progress:
            job_progress(stage, msg, progress)
        try:
            update_task(task_id, stage=stage, progress=progress, message=msg,
                        payload={"story_id": story_id})
        except Exception as exc:
            print(f"[generation] durable completion update failed: {exc}", file=sys.stderr)
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
        if job_progress:
            job_progress("complete", _generation_tasks[task_id]["message"], 1)
        try:
            finish_task(task_id, status="succeeded",
                        message=_generation_tasks[task_id]["message"],
                        payload={"story_id": story_id})
        except Exception as exc:
            print(f"[generation] durable completion update failed: {exc}", file=sys.stderr)
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
        if job_progress:
            job_progress("error", f"Failed: {detail}", _generation_tasks[task_id].get("progress", 0))
        try:
            finish_task(task_id, status="failed", message=f"Failed: {detail}",
                        payload={"story_id": story_id})
        except Exception as exc:
            print(f"[generation] durable failure update failed: {exc}", file=sys.stderr)
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
    existing = find_active_task(
        story_id=req.story_concept,
        kind="generate",
        metadata=req.model_dump(),
    )
    if existing:
        return {
            "task_id": existing["id"],
            "status": existing["status"],
            "message": "This production is already queued; showing the existing run.",
            "deduplicated": True,
        }
    task_id = new_uuid()[:8]
    _generation_tasks[task_id] = {
        "id": task_id,
        "status": "queued",
        "progress": 0,
        "message": "Queued for generation...",
        "request": req.model_dump(),
        "created_at": now(),
    }
    try:
        start_task(task_id, story_id=req.story_concept, kind="generate",
                   metadata=req.model_dump())
    except Exception as exc:
        print(f"[generation] durable task start failed: {exc}", file=sys.stderr)

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
    try:
        update_task(queue_id, stage="queue", progress=0,
                    message=queue_task["message"])
    except Exception as exc:
        print(f"[queue] durable start update failed: {exc}", file=sys.stderr)

    completed_titles: list[str] = []
    failed_titles: list[str] = []
    capabilities = tuple(
        value.strip()
        for value in os.environ.get("FANTASEE_WORKER_CAPABILITIES", "cpu,gpu").split(",")
        if value.strip()
    )
    worker = ProductionWorker(
        production_database_path(),
        worker_id=f"generation-{os.getpid()}",
        capabilities=capabilities,
    )

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
        try:
            start_task(sub_id, story_id=item.story_concept, kind="generate",
                       metadata=item.model_dump())
            enqueue_task_job(
                queue_id,
                job_id=sub_id,
                job_type="story.generate",
                payload=item.model_dump(),
            )
        except Exception as exc:
            print(f"[queue] durable child start failed: {exc}", file=sys.stderr)

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
            async def run_generation_job(job, progress):
                request = GenerateRequest.model_validate(job.payload)
                await _run_generation(job.id, request, progress)
                sub = _generation_tasks.get(job.id, {})
                if sub.get("status") != "done":
                    raise RuntimeError(sub.get("message", "Generation failed"))
                return sub.get("result")

            await worker.run_once(run_generation_job)
            with ProductionStore(production_database_path()) as store:
                job_state = store.get_job(sub_id)
            sub = _generation_tasks.get(sub_id, {})
            if job_state and job_state.status == "succeeded":
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
        try:
            update_task(queue_id, stage="queue", progress=overall,
                        message=queue_task["message"],
                        payload={"completed": completed_titles, "failed": failed_titles})
        except Exception as exc:
            print(f"[queue] durable progress update failed: {exc}", file=sys.stderr)

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
    try:
        finish_task(queue_id, status="succeeded" if not failed_titles else "failed",
                    message=queue_task["message"],
                    payload={"completed": completed_titles, "failed": failed_titles})
    except Exception as exc:
        print(f"[queue] durable finish update failed: {exc}", file=sys.stderr)

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


async def recover_generation_jobs() -> None:
    """Resume durable generation jobs left by a previous server process."""
    await asyncio.sleep(float(os.environ.get("FANTASEE_GENERATION_RECOVERY_DELAY", "5") or "5"))
    capabilities = tuple(
        value.strip()
        for value in os.environ.get("FANTASEE_WORKER_CAPABILITIES", "cpu,gpu").split(",")
        if value.strip()
    )
    worker = ProductionWorker(
        production_database_path(),
        worker_id=f"recovery-{os.getpid()}",
        capabilities=capabilities,
    )

    async def run_generation_job(job, progress):
        request = GenerateRequest.model_validate(job.payload)
        _generation_tasks.setdefault(job.id, {
            "id": job.id,
            "parent": job.run_id,
            "status": "running",
            "progress": 0,
            "message": "Recovered generation job",
            "request": request.model_dump(),
            "created_at": now(),
        })
        await _run_generation(job.id, request, progress)
        sub = _generation_tasks.get(job.id, {})
        if sub.get("status") != "done":
            raise RuntimeError(sub.get("message", "Recovered generation failed"))
        return sub.get("result")

    while True:
        with ProductionStore(production_database_path()) as store:
            next_job = next(
                (job for job in store.list_runnable_jobs() if job.job_type == "story.generate"),
                None,
            )
        if next_job is None:
            return
        handled = await worker.run_once(run_generation_job)
        if not handled:
            return
        finalize_run_from_jobs(next_job.run_id)


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
    try:
        start_task(queue_id, story_id="queue", kind="generation_queue",
                   metadata={"items": [item.model_dump() for item in req.items]})
    except Exception as exc:
        print(f"[queue] durable task start failed: {exc}", file=sys.stderr)

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
    tasks = {task["id"]: task for task in list(_generation_tasks.values())}
    for task in list_persisted_tasks():
        tasks.setdefault(task["id"], task)
    return {"tasks": list(tasks.values())}


@router.get("/api/generate/tasks/{task_id}")
def get_task(task_id: str):
    """Get the status of a generation task."""
    task = _generation_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
