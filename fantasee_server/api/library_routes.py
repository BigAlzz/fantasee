"""Library maintenance HTTP routes.

* ``/api/library-maintenance/incomplete`` — list every story that
  is missing one or more pipeline outputs (text, images, audio,
  subtitles, video, Plex package).
* ``/api/library-maintenance/queue`` — kick off the per-story
  repair pipeline (regenerate → repair → render → plex export)
  for the listed stories, or for the top N incomplete ones.

The actual repair work happens in ``fantasee_server.library``;
this module is just the HTTP layer.
"""

from __future__ import annotations

from fastapi import APIRouter, Body

from fantasee_server.library import (
    _start_library_maintenance_queue,
    incomplete_story_summaries,
)


router = APIRouter(tags=["library-maintenance"])


@router.get("/api/library-maintenance/incomplete")
def list_incomplete_stories():
    """List stories that are missing story text, assets, video, or Plex output."""
    stories = incomplete_story_summaries(include_failed=True)
    return {"stories": stories, "count": len(stories)}


@router.post("/api/library-maintenance/queue")
async def queue_library_maintenance(body: dict = Body(default=None)):
    """Queue incomplete stories for completion, rendering, and Plex export."""
    body = body or {}
    limit = body.get("limit")
    try:
        limit = int(limit) if limit is not None else None
    except (TypeError, ValueError):
        limit = None
    story_ids = body.get("story_ids") or None
    return await _start_library_maintenance_queue(
        story_ids=story_ids,
        limit=limit,
        include_failed=bool(body.get("include_failed", True)),
        auto=False,
    )
