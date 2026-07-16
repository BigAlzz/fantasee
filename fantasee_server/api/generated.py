"""Generated-stories API + on-disk asset serving.

The "generated stories" endpoints are the live ones (vs the legacy
``/api/stories*`` aliases in ``api/stories``). The list endpoint
prefers ``stories/`` and falls back to ``outputs/`` for pre-migration
content. The detail endpoint enriches the manifest with image / audio
/ video / subtitle URLs so the frontend can render the player.

Asset serving lives here too: ``/generated-images/``,
``/generated-audio/``, ``/generated-videos/``, ``/generated-vtt/``,
``/generated-subtitles/``, and ``/generated/{story_id}/{filename}``
— the latter is the URL format embedded in the manifest so the
frontend can fetch any file under a story directory without knowing
its on-disk path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from fantasee_server.discovery import (
    _story_scene_art_urls,
    discover_generated_stories,
    generated_asset_url,
)
from fantasee_server.paths import (
    STATIC_DIR,
    STORY_VIEWER_DIR,
    generated_path,
    generated_story_dir,
    path_under,
)
from fantasee_server.security import require_operator
from story_storage import validate_story_id
from fantasee_server.state import (
    _resolve_env_var,
    _story_sort_ts,
    atomic_write_json,
)


router = APIRouter(tags=["generated-stories"])


# ── Generated-asset serving ───────────────────────────────────────

@router.get("/")
def serve_index():
    """Serve the bundled frontend SPA at the root URL."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@router.get("/generated-images/{filename:path}")
def serve_generated_image(filename: str):
    """Serve an image from the fantasee outputs directory."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(filepath))


@router.get("/generated/{story_id}/{filename:path}")
def serve_generated_asset(story_id: str, filename: str):
    """Serve any asset (image/audio/subs) from a generated story's directory."""
    try:
        validate_story_id(story_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    story_dir = generated_story_dir(story_id)
    filepath = path_under(story_dir, filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Asset not found")
    # Determine media type
    suffix = filepath.suffix.lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".svg": "image/svg+xml", ".wav": "audio/wav",
                   ".mp3": "audio/mpeg", ".json": "application/json"}
    return FileResponse(str(filepath), media_type=media_types.get(suffix, "application/octet-stream"))


@router.get("/generated-audio/{filename:path}")
def serve_generated_audio(filename: str):
    """Serve audio from the fantasee outputs directory."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(str(filepath), media_type="audio/wav")


@router.get("/generated-subtitles/{filename:path}")
def serve_generated_subtitles(filename: str):
    """Serve subtitle JSON from the fantasee outputs directory."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Subtitles not found")
    return FileResponse(str(filepath), media_type="application/json")


@router.get("/generated-videos/{filename:path}")
def serve_generated_video(filename: str):
    """Serve rendered MP4 video from the fantasee outputs directory."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    media = {".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska"}
    return FileResponse(str(filepath), media_type=media.get(filepath.suffix.lower(), "video/mp4"))


@router.get("/generated-vtt/{filename:path}")
def serve_generated_vtt(filename: str):
    """Serve VTT subtitle sidecar from the fantasee outputs directory."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="VTT not found")
    return FileResponse(str(filepath), media_type="text/vtt")


# ── Generated story list / detail ─────────────────────────────────

@router.get("/api/generated-stories")
def list_generated_stories():
    """List all generated stories from the outputs directory."""
    stories = discover_generated_stories()
    summaries = []
    for s in stories:
        scene_art_urls = _story_scene_art_urls(s)
        cover = scene_art_urls[0] if scene_art_urls else ""
        # For generated stories, derive hero_image from first scene's first image
        hero = s.get("hero_image_url") or s.get("hero_image")
        if not hero and s.get("scenes"):
            first_scene = s["scenes"][0]
            imgs = first_scene.get("image_filenames", [])
            if imgs:
                hero = generated_asset_url(s.get("id", ""), imgs[0])

        summaries.append({
            "id": s.get("id", ""),
            "title": s.get("title", ""),
            "subtitle": s.get("subtitle", ""),
            "description": s.get("description", "")[:200],
            "tags": s.get("tags", []),
            "created_at": s.get("created_at"),
            "updated_at": s.get("updated_at"),
            "sort_ts": s.get("sort_ts", 0),
            "completion": s.get("completion", {}),
            "scene_count": s.get("scene_count", len(s.get("scenes", []))),
            "generated": s.get("generated", True),
            "hero_image": hero,
            "cover_image_url": cover,
            "scene_art_urls": scene_art_urls[:6],
            "background_audio": s.get("background_audio"),
            "background_volume": s.get("background_volume", 0.05),
            "background_muted": s.get("background_muted", False),
            "critic_rating": s.get("critic_rating", 0),
            "critic_stars": s.get("critic_stars", 0),
            "critic_badge": s.get("critic_badge", ""),
            "has_review": s.get("has_review", False),
        })
    summaries.sort(key=_story_sort_ts, reverse=True)
    return {"stories": summaries}


@router.get("/api/generated-stories/{story_id}")
def get_generated_story(story_id: str):
    """Get full detail for a generated story."""
    stories = discover_generated_stories()
    for s in stories:
        if s.get("id") == story_id:
            scene_art_urls = _story_scene_art_urls(s)
            if scene_art_urls:
                s["cover_image_url"] = scene_art_urls[0]
                s["scene_art_urls"] = scene_art_urls[:10]
            # Enrich hero_image if missing (same logic as list endpoint)
            if s.get("hero_image_url"):
                s["hero_image"] = s["hero_image_url"]
            elif s.get("hero_image"):
                s["hero_image"] = generated_asset_url(s.get("id", ""), s["hero_image"])
            elif s.get("scenes"):
                first_scene = s["scenes"][0]
                imgs = first_scene.get("image_filenames", [])
                if imgs:
                    s["hero_image"] = generated_asset_url(s.get("id", ""), imgs[0])
            return s
    raise HTTPException(status_code=404, detail="Generated story not found")


@router.get("/api/generated-stories/{story_id}/review")
def get_story_review(story_id: str):
    """Get the critic review for a generated story."""
    story_dir = generated_story_dir(story_id)
    review_path = story_dir / f"{story_id}_review.json"
    if review_path.exists():
        try:
            return json.loads(review_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    raise HTTPException(status_code=404, detail="No review found for this story")


@router.post(
    "/api/generated-stories/{story_id}/run-critic",
    dependencies=[Depends(require_operator)],
)
async def run_critic(story_id: str):
    """Run the critic on a generated story and return the review."""
    story_dir = generated_story_dir(story_id)
    if not story_dir.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    manifest = story_dir / f"{story_id}.json"
    if not manifest.exists():
        raise HTTPException(status_code=404, detail="Manifest not found")

    # Resolve env vars for the subprocess
    env = {
        **os.environ,
        "XIAOMI_API_KEY": _resolve_env_var("XIAOMI_API_KEY"),
        "XIAOMI_BASE_URL": _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
    }

    try:
        proc = subprocess.run(
            [sys.executable, str(STORY_VIEWER_DIR / "critic.py"), story_id, "--json"],
            capture_output=True, text=True, timeout=180,
            cwd=str(STORY_VIEWER_DIR),
            env=env,
        )
        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Critic failed: {proc.stderr[:500]}",
            )

        # Strip non-JSON trailing output (e.g. "Review saved: ..." messages)
        stdout = proc.stdout.strip()
        json_end = stdout.rfind("}")
        if json_end >= 0:
            stdout = stdout[:json_end + 1]
        result = json.loads(stdout)

        # Save review JSON
        review_path = story_dir / f"{story_id}_review.json"
        atomic_write_json(review_path, result)

        # Update manifest
        review = result.get("review", {})
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_data["critic_rating"] = review.get("rating", 0)
        manifest_data["critic_stars"] = review.get("stars", 0)
        manifest_data["critic_badge"] = review.get("badge", "")
        manifest_data["has_review"] = True
        atomic_write_json(manifest, manifest_data)

        return result
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Critic timed out")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid critic output: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
