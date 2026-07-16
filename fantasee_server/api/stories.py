"""Legacy ``/api/stories*`` endpoints.

These were the original "built-in stories" routes. The hard-coded
``STORY_META`` dict that used to power them was removed; the routes
now just summarize the live ``_stories_cache`` so the original
frontend URL still works.

Also serves the legacy ``/images/<name>`` and ``/audio/<name>``
URLs — these are aliases for the newer ``/generated-images/`` and
``/generated-audio/`` URLs and exist for backwards compatibility
with old share links.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

import fantasee_server.state as _state
from fantasee_server.discovery import _story_scene_art_urls
from fantasee_server.paths import generated_path
from fantasee_server.state import _story_sort_ts


router = APIRouter(tags=["stories (legacy)"])


@router.get("/api/stories")
def list_stories():
    """Return summary of all stories (without full scene data)."""
    summaries = []
    for s in _state._stories_cache or []:
        scene_art_urls = s.get("scene_art_urls") or _story_scene_art_urls(s)
        cover = s.get("cover_image_url") or (scene_art_urls[0] if scene_art_urls else "")
        summaries.append({
            "id": s.get("id", ""),
            "title": s.get("title", ""),
            "subtitle": s.get("subtitle", ""),
            "description": (s.get("description") or "")[:200] + "...",
            "tags": s.get("tags", []),
            "year": s.get("year", ""),
            "created_at": s.get("created_at"),
            "updated_at": s.get("updated_at"),
            "sort_ts": s.get("sort_ts", 0),
            "completion": s.get("completion", {}),
            "hero_image": s.get("hero_image_url") or s.get("hero_image"),
            "cover_image_url": cover,
            "scene_art_urls": scene_art_urls[:6],
            "scene_count": s.get("scene_count", len(s.get("scenes", []))),
        })
    summaries.sort(key=_story_sort_ts, reverse=True)
    return {"stories": summaries}


@router.get("/api/stories/{story_id}")
def get_story(story_id: str):
    """Return full story detail with all scenes."""
    for s in _state._stories_cache or []:
        if s["id"] == story_id:
            return s
    raise HTTPException(status_code=404, detail="Story not found")


@router.get("/api/stories/{story_id}/scenes/{scene_idx}")
def get_scene(story_id: str, scene_idx: int):
    """Return a specific scene from a story."""
    for s in _state._stories_cache or []:
        if s["id"] == story_id:
            if 0 <= scene_idx < len(s["scenes"]):
                return s["scenes"][scene_idx]
            raise HTTPException(status_code=404, detail="Scene not found")
    raise HTTPException(status_code=404, detail="Story not found")


@router.get("/images/{filename:path}")
def serve_image(filename: str):
    """Serve a generated image from stories/ or legacy outputs/."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(filepath))


@router.get("/audio/{filename:path}")
def serve_audio(filename: str):
    """Serve a TTS narration audio file from stories/ or legacy outputs/."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(str(filepath), media_type="audio/mpeg")
