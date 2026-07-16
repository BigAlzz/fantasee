"""Path helpers for the Fantasee server.

Centralizes filesystem layout:

* ``STATIC_DIR``       — directory served at ``/`` (the index.html).
* ``STORY_VIEWER_DIR`` — repo root (parent of this file's parent).
* ``GEN_OUTPUTS``      — canonical generated-story root (``stories/``).
* ``LEGACY_GEN_OUTPUTS``— legacy root (``outputs/``) for pre-migration stories.

The ``path_under`` helper prevents path-traversal when callers
request ``/images/<name>`` style URLs. The ``generated_path`` helper
resolves a generated asset by trying the canonical root first, then
falling back to the legacy one (so old stories still work after the
``outputs/`` → ``stories/`` migration).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from story_storage import (
    LEGACY_OUTPUTS_ROOT,
    STORIES_ROOT,
    ensure_story_layout,
    existing_story_dir,
    validate_story_id,
)

from fantasee_server.state import atomic_write_json


STATIC_DIR = Path(__file__).parent.parent / "static"
STORY_VIEWER_DIR = Path(__file__).parent.parent

GEN_OUTPUTS = STORIES_ROOT
LEGACY_GEN_OUTPUTS = LEGACY_OUTPUTS_ROOT


def path_under(root: Path, *parts: str) -> Path:
    """Resolve a user-supplied path and ensure it stays under root."""
    root = root.resolve()
    candidate = root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=404, detail="Asset not found")
    return candidate


def generated_path(*parts: str) -> Path:
    """Resolve a generated asset from stories/, falling back to legacy outputs/."""
    try:
        primary = path_under(GEN_OUTPUTS, *parts)
    except HTTPException:
        raise
    if primary.exists():
        return primary
    legacy = path_under(LEGACY_GEN_OUTPUTS, *parts)
    if legacy.exists():
        return legacy
    return primary


def generated_story_dir(story_id: str, create: bool = False) -> Path:
    """Return a story directory, preferring stories/ over legacy outputs."""
    try:
        validate_story_id(story_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    story_dir = existing_story_dir(story_id)
    if create:
        ensure_story_layout(story_dir)
    return path_under(story_dir.parent, story_dir.name)


def load_stories():
    """Load all story metadata and scenes.

    Thin wrapper around :func:`discover_generated_stories` for the
    legacy ``/api/stories*`` endpoints. The original implementation
    walked a hard-coded ``STORY_META`` dict for the built-in siege
    and iron-pursuit stories; that data has been removed and the live
    server only serves generated stories.
    """
    # Imported here to avoid an import cycle (discovery → library → ...).
    from fantasee_server.discovery import (
        _story_scene_art_urls,
        discover_generated_stories,
    )

    stories = discover_generated_stories()
    # Truncate the description for the legacy ``/api/stories`` summary
    # endpoint so we don't blow out the response with a 5-paragraph
    # synopsis when the caller only wants a one-line preview.
    for s in stories:
        if "description" in s and isinstance(s["description"], str):
            s["description"] = s["description"][:200] + "..." if len(s["description"]) > 200 else s["description"]
        scene_art_urls = _story_scene_art_urls(s)
        if scene_art_urls:
            s["cover_image_url"] = scene_art_urls[0]
            s["scene_art_urls"] = scene_art_urls[:10]
    return stories
