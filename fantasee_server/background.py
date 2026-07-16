"""Background task runners.

Helpers that wrap a synchronous function in an asyncio task, with
WebSocket progress streaming. Two pieces:

* ``_run_story_action_background_task`` — generic runner used by
  ``/api/stories/{id}/{improve,improve-loop,...}`` endpoints to spin
  up a sync worker in the executor and stream ``task_update`` events
  to the WebSocket clients.

* ``_run_story_delete`` — specific runner for ``DELETE /api/stories/{id}``
  that streams per-file progress from ``delete_story.delete_story_with_progress``.

Also includes the ``_push_story_action_progress`` helper used by the
``/extend`` endpoint (which runs in-line rather than as a background
task) and a tiny ``_truthy`` helper that normalizes a request body
field to a bool.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fantasee_server.paths import generated_story_dir
from fantasee_server.improver import _clamp_progress
import fantasee_server.paths as _paths
import fantasee_server.state as _state
from fantasee_server.state import (
    _broadcast_ws_json,
    _broadcast_ws_json_from_thread,
    _generation_tasks,
    _websocket_clients,
)


def _push_story_action_progress(story_id, stage, msg, pct, *, kind):
    """Helper for the extend endpoint (which is in-line, not a task)."""
    for task_id, task in list(_generation_tasks.items()):
        if task.get("kind") == kind and task.get("story_id") == story_id:
            task.update({"stage": stage, "progress": pct, "message": msg})
            for ws in _websocket_clients[:]:
                try:
                    coro = ws.send_json({
                        "type": "task_update", "task_id": task_id,
                        "kind": kind, "story_id": story_id,
                        "stage": stage, "status": "running",
                        "progress": pct, "message": msg,
                    })
                    asyncio.run_coroutine_threadsafe(coro, asyncio.get_event_loop())
                except Exception:
                    pass


def _truthy(body, key, default):
    if not body:
        return default
    val = body.get(key, default)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


# ── Generic background-task runner ────────────────────────────────

async def _run_story_action_background_task(
    task_id: str,
    story_id: str,
    kind: str,
    worker,
    complete_message,
) -> None:
    """Run a synchronous story action in the executor and stream task updates."""
    loop = asyncio.get_running_loop()

    def _progress(stage: str, msg: str, pct: float) -> None:
        pct = _clamp_progress(pct)
        _generation_tasks[task_id].update({
            "stage": stage,
            "status": "running",
            "progress": pct,
            "message": msg,
        })
        _broadcast_ws_json_from_thread(loop, {
            "type": "task_update",
            "task_id": task_id,
            "kind": kind,
            "story_id": story_id,
            "stage": stage,
            "status": "running",
            "progress": pct,
            "message": msg,
        })

    try:
        result = await loop.run_in_executor(None, lambda: worker(_progress))
        message = complete_message(result)
        _generation_tasks[task_id].update({
            "status": "done",
            "stage": "complete",
            "progress": 1.0,
            "message": message,
            "result": result,
        })
        try:
            _state._stories_cache = _paths.load_stories()
        except Exception as cache_err:
            print(f"[{kind}] story cache reload failed: {cache_err}", file=sys.stderr)
        await _broadcast_ws_json({
            "type": "task_update",
            "task_id": task_id,
            "kind": kind,
            "story_id": story_id,
            "status": "done",
            "stage": "complete",
            "progress": 1.0,
            "message": message,
            "result": result,
        })
    except Exception as e:
        message = f"{kind.replace('_', ' ').title()} failed: {e}"
        _generation_tasks[task_id].update({
            "status": "error",
            "stage": "error",
            "progress": 1.0,
            "message": message,
        })
        await _broadcast_ws_json({
            "type": "task_update",
            "task_id": task_id,
            "kind": kind,
            "story_id": story_id,
            "status": "error",
            "stage": "error",
            "progress": 1.0,
            "message": message,
        })


# ── Story delete worker ──────────────────────────────────────────

async def _run_story_delete(task_id: str, story_id: str, story_dir: Path, backup: bool) -> None:
    """Run story deletion off the request path and stream task updates."""
    loop = asyncio.get_running_loop()
    import sys
    sys.path.insert(0, str(story_dir.parent.parent))
    from delete_story import delete_story_with_progress

    def _progress(event: dict) -> None:
        stage = event.get("stage", "delete")
        message = event.get("message", "")
        pct = event.get("progress", 0)
        report = event.get("report")
        _generation_tasks[task_id].update({
            "stage": stage,
            "progress": pct,
            "message": message,
            "report": report,
        })
        _broadcast_ws_json_from_thread(loop, {
            "type": "task_update",
            "task_id": task_id,
            "kind": "delete_story",
            "story_id": story_id,
            "stage": stage,
            "status": "error" if stage == "error" else "running",
            "progress": pct,
            "message": message,
            "report": report,
        })

    try:
        report = await loop.run_in_executor(
            None,
            lambda: delete_story_with_progress(
                story_dir,
                backup=backup,
                progress_callback=_progress,
            ),
        )

        global _state  # noqa: F824  (no-op placeholder, just to silence linters)
        _generation_tasks[task_id]["report"] = report
        if report["errors"]:
            message = f"Delete partially failed: {report['errors']}"
            _generation_tasks[task_id].update({
                "status": "error",
                "stage": "error",
                "progress": 1.0,
                "message": message,
                "result": report,
            })
            await _broadcast_ws_json({
                "type": "task_update",
                "task_id": task_id,
                "kind": "delete_story",
                "story_id": story_id,
                "status": "error",
                "stage": "error",
                "progress": 1.0,
                "message": message,
                "result": report,
            })
            return

        _state._stories_cache = _paths.load_stories()
        message = (
            f"Deleted {story_id}: {report['files_deleted']} file(s), "
            f"{report['bytes_freed']} bytes freed"
        )
        _generation_tasks[task_id].update({
            "status": "done",
            "stage": "complete",
            "progress": 1.0,
            "message": message,
            "result": report,
        })
        await _broadcast_ws_json({
            "type": "task_update",
            "task_id": task_id,
            "kind": "delete_story",
            "story_id": story_id,
            "status": "done",
            "stage": "complete",
            "progress": 1.0,
            "message": message,
            "result": report,
        })
        await _broadcast_ws_json({
            "type": "story_deleted",
            "story_id": story_id,
            "task_id": task_id,
        })
    except Exception as e:
        message = f"Delete failed: {e}"
        _generation_tasks[task_id].update({
            "status": "error",
            "stage": "error",
            "progress": 1.0,
            "message": message,
        })
        await _broadcast_ws_json({
            "type": "task_update",
            "task_id": task_id,
            "kind": "delete_story",
            "story_id": story_id,
            "status": "error",
            "stage": "error",
            "progress": 1.0,
            "message": message,
        })
