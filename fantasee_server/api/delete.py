"""Story deletion endpoint.

``DELETE /api/stories/{id}`` — two-phase: without ``confirm: true``,
returns a preview of what would be deleted; with ``confirm: true``,
spawns a background task that runs ``delete_story.delete_story_with_progress``
and streams per-file progress over the WebSocket.

The actual deletion work happens in ``delete_story.py`` (and the
background runner in ``fantasee_server.background``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from fantasee_server.background import _run_story_delete
import fantasee_server.paths as _paths
import fantasee_server.state as _state
from fantasee_server.paths import generated_story_dir
from fantasee_server.state import (
    _broadcast_ws_json,
    _generation_tasks,
    new_uuid,
    now,
)


router = APIRouter(tags=["delete"])


@router.delete("/api/stories/{story_id}")
async def delete_story_endpoint(story_id: str, body: dict = Body(default=None)):
    """Permanently delete a story and all of its on-disk artifacts.

    Body params (all optional):
      - backup: bool — copy to outputs/.trash/ before deleting (default false)
      - confirm: bool — must be true to actually delete (safety guard)
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    confirm = bool((body or {}).get("confirm", False))
    backup = bool((body or {}).get("backup", False))

    # No built-in stories to protect anymore — the legacy
    # ``STORY_META`` dict was removed. The check below is a no-op
    # kept as a defensive guard so any future re-introduction of
    # static built-ins is caught by the same code path.
    if False and story_id in {  # noqa: STORY_META placeholder
        # The original built-in story IDs (siege, iron-pursuit) used to
        # live here. Keep this guard so a re-introduction is a 1-line
        # change.
    }:
        raise HTTPException(
            status_code=400,
            detail=f"'{story_id}' is a built-in story and cannot be deleted via API. "
                   "It lives outside outputs/."
        )

    story_dir = generated_story_dir(story_id)
    if not story_dir.exists():
        # Already gone — still reload the cache and return success
        _state._stories_cache = _paths.load_stories()
        return {
            "status": "ok",
            "story_id": story_id,
            "deleted": 0,
            "bytes_freed": 0,
            "note": "story did not exist; cache reloaded",
        }

    if not confirm:
        # Return a dry-run report so the GUI can show the user what would
        # be deleted before asking for confirmation.
        files = []
        total_bytes = 0
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
            "note": "Send {confirm: true, backup: <bool>} to actually delete",
        }

    task_id = f"delete-{new_uuid()[:6]}"
    _generation_tasks[task_id] = {
        "id": task_id,
        "kind": "delete_story",
        "story_id": story_id,
        "status": "running",
        "progress": 0,
        "message": "Deleting story...",
        "stage": "queued",
        "backup": backup,
        "created_at": now(),
    }
    await _broadcast_ws_json({
        "type": "task_update",
        "task_id": task_id,
        "kind": "delete_story",
        "story_id": story_id,
        "status": "running",
        "stage": "queued",
        "progress": 0,
        "message": "Deleting story...",
    })
    asyncio.create_task(_run_story_delete(task_id, story_id, story_dir, backup))
    return {
        "status": "running",
        "story_id": story_id,
        "task_id": task_id,
        "message": "Story deletion started. Watch the progress panel for status.",
    }
