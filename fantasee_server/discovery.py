"""Story manifest discovery + URL enrichment.

Walks the ``stories/`` (and legacy ``outputs/``) directory, reads each
story's ``<id>.json`` manifest, and enriches it with:

* ``sort_ts`` (newest-first ordering key)
* ``storage_root`` ("stories" vs legacy "outputs")
* ``hero_image_url`` / ``cover_image_url`` / ``scene_art_urls``
* per-scene ``image_urls`` / ``audio_url`` / ``subtitle_url`` / ``video_url`` / ``vtt_url``
* subtitle segments loaded from the per-scene JSON so the player can
  sync captions to the actual Whisper timing.
* ``full_video_url`` / ``full_vtt_url`` for the rendered full MP4
* ``plex_video_url`` / ``plex_srt_url`` / ``plex_vtt_url`` / ``plex_poster_url``
  for the Plex package.
* a ``completion`` block (delegated to ``library.story_completion_report``)
  that summarizes what's still missing.

The functions here are pure (no FastAPI dependencies) so they're easy
to unit-test in isolation. Routes that need a list of stories call
``discover_generated_stories()`` and use the result.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from fantasee_server.paths import (
    GEN_OUTPUTS,
    LEGACY_GEN_OUTPUTS,
    atomic_write_json,
    generated_story_dir,
)
from fantasee_server.state import _coerce_timestamp, _story_sort_ts


def iter_generated_story_dirs() -> list[Path]:
    """Return story directories, preferring stories/ over legacy outputs/."""
    found: dict[str, Path] = {}
    for root in (GEN_OUTPUTS, LEGACY_GEN_OUTPUTS):
        if not root.exists():
            continue
        for child in root.iterdir():
            if not child.is_dir() or child.name.startswith(".") or child.name.startswith("_"):
                continue
            manifest = child / f"{child.name}.json"
            if manifest.exists() and child.name not in found:
                found[child.name] = child
    return sorted(found.values(), key=lambda p: p.name)


def generated_asset_url(story_id: str, filename: str) -> str:
    """Return a URL for an asset inside a generated story folder."""
    filename = str(filename).replace("\\", "/").lstrip("/")
    return f"/generated/{story_id}/{filename}"


def ensure_title_slide_for_manifest(story_dir: Path, manifest: dict) -> None:
    """Create a title slide for an existing story if it does not have one."""
    story_id = manifest.get("id") or story_dir.name
    title_slide = manifest.get("title_slide") or manifest.get("hero_image")
    if title_slide and (story_dir / str(title_slide).lstrip("/")).exists():
        return
    try:
        from generate_story import write_title_slide
        title = manifest.get("title") or story_id.replace("-", " ").title()
        concept = manifest.get("description") or manifest.get("subtitle") or title
        tags = manifest.get("tags") or []
        style = tags[0] if tags else "fantasy painterly"
        tone = manifest.get("tone") or (tags[1] if len(tags) > 1 else "dramatic")
        rel = write_title_slide(story_dir, story_id, title, concept, tone, style)
        manifest["title_slide"] = rel
        manifest["hero_image"] = rel
        manifest["storage_root"] = "stories"
        atomic_write_json(story_dir / f"{story_id}.json", manifest)
    except Exception as e:
        print(f"[title-slide] failed for {story_id}: {e}", file=sys.stderr)


def discover_generated_stories() -> list[dict]:
    """Load story manifests from stories/ and legacy outputs/ directories."""
    # Imported lazily to avoid a cycle (library.py imports discovery too).
    from fantasee_server.library import story_completion_report

    stories = []
    for child in iter_generated_story_dirs():
        manifest = child / f"{child.name}.json"
        if manifest.exists():
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    manifest_stat = manifest.stat()
                    dir_stat = child.stat()
                    data.setdefault("created_at", dir_stat.st_ctime)
                    data.setdefault("updated_at", manifest_stat.st_mtime)
                    data["sort_ts"] = max(
                        _coerce_timestamp(data.get("updated_at")),
                        _coerce_timestamp(data.get("created_at")),
                        manifest_stat.st_mtime,
                        dir_stat.st_ctime,
                    )
                    data["storage_root"] = "stories" if child.parent == GEN_OUTPUTS else "outputs"
                    # Enrich with asset URLs and scene_count
                    scenes = data.get("scenes", [])
                    data["scene_count"] = len(scenes)
                    # Surface the new background / chapters fields so the
                    # player + detail UI can read them without falling back
                    # to manifest lookups.
                    data.setdefault("background_volume", 0.05)
                    data.setdefault("background_muted", False)
                    data.setdefault("chapters", [])
                    # Use story artwork for library cards. Title slides are
                    # metadata, not story content, so they remain a fallback.
                    scene_hero = next(
                        (filename for scene in scenes for filename in (scene.get("image_filenames", []) or [])
                         if filename and (child / str(filename).lstrip("/")).is_file()),
                        None,
                    )
                    if scene_hero:
                        data["hero_image_url"] = generated_asset_url(child.name, scene_hero)
                        data["hero_image"] = scene_hero
                        data["cover_image_url"] = data["hero_image_url"]
                    else:
                        hero = (
                            data.get("title_image")
                            or data.get("hero_image")
                            or data.get("title_slide")
                        )
                        if hero and (child / str(hero).lstrip("/")).exists():
                            data["hero_image_url"] = generated_asset_url(child.name, hero)
                            data["hero_image"] = hero
                        else:
                            # Last-ditch: the legacy title-slide paths.
                            for fallback in ("assets/title/title_slide.png", "assets/title/title_slide.svg"):
                                if (child / fallback).exists():
                                    data["hero_image_url"] = generated_asset_url(child.name, fallback)
                                    data["hero_image"] = fallback
                                    break
                    for scene in scenes:
                        # Convert filenames to URLs
                        imgs = scene.get("image_filenames", [])
                        scene["image_urls"] = [generated_asset_url(child.name, f) for f in imgs if f]
                        audio = scene.get("audio_filename", "")
                        scene["audio_url"] = generated_asset_url(child.name, audio) if audio else None
                        subs = scene.get("subtitle_file", "")
                        scene["subtitle_url"] = generated_asset_url(child.name, subs) if subs else None
                        # Load Whisper subtitle segments so the frontend
                        # can sync captions to the actual audio timing
                        # instead of approximating by character length.
                        if subs:
                            subs_path = child / subs
                            if subs_path.exists():
                                try:
                                    with open(subs_path, "r", encoding="utf-8") as f:
                                        scene["subtitle_segments"] = json.load(f)
                                except (OSError, json.JSONDecodeError):
                                    pass
                        # Rendered video + VTT sidecar (from render_video.py)
                        scene_key = scene.get("scene", "")
                        if scene_key:
                            mp4 = f"{child.name}_s{scene_key}.mp4"
                            vtt = f"{child.name}_s{scene_key}.vtt"
                            if (child / mp4).exists():
                                scene["video_url"] = generated_asset_url(child.name, mp4)
                            if (child / vtt).exists():
                                scene["vtt_url"] = generated_asset_url(child.name, vtt)
                    # Full story video + VTT
                    full_mp4 = f"{child.name}_full.mp4"
                    full_vtt = f"{child.name}_full.vtt"
                    if (child / full_mp4).exists():
                        data["full_video_url"] = generated_asset_url(child.name, full_mp4)
                    elif (child / "final" / full_mp4).exists():
                        data["full_video_url"] = generated_asset_url(child.name, f"final/{full_mp4}")
                    if (child / full_vtt).exists():
                        data["full_vtt_url"] = generated_asset_url(child.name, full_vtt)
                    elif (child / "final" / full_vtt).exists():
                        data["full_vtt_url"] = generated_asset_url(child.name, f"final/{full_vtt}")
                    # Plex package (final/plex/) — the deliverable for /api/export-plex
                    plex_dir = child / "final" / "plex"
                    if plex_dir.is_dir():
                        plex_mp4 = next(plex_dir.glob("*.mp4"), None)
                        if plex_mp4 and plex_mp4.exists():
                            data["plex_video_url"] = generated_asset_url(child.name, f"final/plex/{plex_mp4.name}")
                        plex_srt = next(plex_dir.glob("*.en.srt"), None)
                        if plex_srt and plex_srt.exists():
                            data["plex_srt_url"] = generated_asset_url(child.name, f"final/plex/{plex_srt.name}")
                        plex_vtt = next(plex_dir.glob("*.en.vtt"), None)
                        if plex_vtt and plex_vtt.exists():
                            data["plex_vtt_url"] = generated_asset_url(child.name, f"final/plex/{plex_vtt.name}")
                        plex_poster = next(plex_dir.glob("*-poster.*"), None)
                        if plex_poster and plex_poster.exists():
                            data["plex_poster_url"] = generated_asset_url(child.name, f"final/plex/{plex_poster.name}")
                    data["completion"] = story_completion_report(child.name, story=data, story_dir=child)
                    stories.append(data)
                except (json.JSONDecodeError, OSError):
                    pass
    stories.sort(key=_story_sort_ts, reverse=True)
    return stories


def _first_scene_art_url(story_id: str, scenes: list[dict]) -> Optional[str]:
    """Return the art URL of the first scene that has any images, or None.

    Used as a fallback for the "cover/hero" thumbnail when the manifest's
    own ``hero_image`` field is empty. Walks scenes in order and returns
    the URL of the first image filename in the first scene that has one.
    """
    for scene in scenes or []:
        for filename in scene.get("image_filenames", []) or []:
            if filename:
                return generated_asset_url(story_id, filename)
    return None


def _story_scene_art_urls(story: dict) -> list[str]:
    """Return generated scene-art URLs, excluding title-slide assets."""
    story_id = story.get("id", "")
    urls: list[str] = []
    for scene in story.get("scenes", []) or []:
        for url in scene.get("image_urls", []) or []:
            if url:
                urls.append(url)
        for filename in scene.get("image_filenames", []) or []:
            if filename:
                urls.append(generated_asset_url(story_id, filename))
    seen = set()
    deduped = []
    for url in urls:
        if url in seen:
            continue
        lowered = url.lower()
        if "title_slide" in lowered or "/assets/title/" in lowered:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped
