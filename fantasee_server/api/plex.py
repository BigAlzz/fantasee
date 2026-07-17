"""Plex export endpoints.

* ``POST /api/stories/{id}/export-plex`` — kick off a Plex-ready
  MP4 + sidecar subtitles export as a background task. The
  exporter writes to ``<story>/final/plex/`` and optionally copies
  the package to a configured Plex library root.
* ``GET /api/stories/{id}/export-plex`` — return the URL of the
  latest Plex package on disk, or 404 if it doesn't exist.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from typing import Optional

from fastapi import APIRouter, HTTPException

from fantasee_server.discovery import ensure_title_slide_for_manifest
from fantasee_server.models import PlexExportRequest
from fantasee_server.paths import STORY_VIEWER_DIR, generated_story_dir
from fantasee_server.state import (
    _broadcast_ws_json,
    _generation_tasks,
    _websocket_clients,
    new_uuid,
    now,
)
from fantasee_server.library import story_completion_report
from fantasee_server.production_runtime import production_database_path
from fantasee_server.production_store import ProductionStore


router = APIRouter(tags=["plex"])


@router.post("/api/stories/{story_id}/export-plex")
async def export_plex(story_id: str, req: PlexExportRequest):
    """Render a Plex-ready MP4 + sidecar subtitles for a generated story.

    Body params (all optional):
      - background_volume: 0.0-1.0 override of the manifest's mix level
      - background_muted:  true to skip background audio entirely
      - background_audio:  filename from Background/ to mix in (overrides manifest)
      - destination:       Plex library root (e.g. ``D:\\Downloads\\Plex``).
        Defaults to ``FANTASEE_PLEX_DEST`` env var, then
        ``D:\\Downloads\\Plex``. The package is copied to
        ``<dest>/Movies/<Title> (<Year>)/`` so a Plex library scan
        picks it up automatically.

    Side effects:
      * Writes final MP4 + .en.srt + .en.vtt + poster + chapters.ffmeta into
        ``<story-dir>/final/plex/``.
      * Emits ``task_update`` WebSocket events with the standard progress
        stages: ``discover`` → ``subtitles`` → ``chapters`` → ``audio_mix``
        → ``finalize``. So the GUI can show the same "scenes / audio mix /
        finalization" timeline as the other long-horizon tasks.
    """
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    completion = story_completion_report(story_id, story_dir=story_dir)
    if not completion.get("complete"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Plex publishing is blocked until the completion contract passes",
                "missing": completion.get("missing", []),
                "issues": completion.get("issues", [])[:20],
            },
        )

    # Make sure the title slide exists (in case this story pre-dates the
    # image-backed version). Skips silently if Pillow isn't available.
    try:
        ensure_title_slide_for_manifest(
            story_dir,
            json.loads(manifest_path.read_text(encoding="utf-8")),
        )
    except (json.JSONDecodeError, OSError):
        pass

    task_id = f"plex-{new_uuid()[:6]}"
    _generation_tasks[task_id] = {
        "id": task_id,
        "kind": "plex_export",
        "story_id": story_id,
        "status": "running",
        "progress": 0,
        "message": "Starting Plex export...",
        "stage": "discover",
        "created_at": now(),
    }

    async def _runner():
        sys.path.insert(0, str(STORY_VIEWER_DIR))
        from plex_export import export_plex_package

        loop = asyncio.get_event_loop()

        def _progress(stage: str, msg: str, pct: float) -> None:
            # The export runs in an executor thread, so we can't await
            # directly. Queue the websocket pushes via run_coroutine_threadsafe.
            _generation_tasks[task_id].update({
                "stage": stage,
                "progress": pct,
                "message": msg,
            })
            for ws in _websocket_clients[:]:
                coro = ws.send_json({
                    "type": "task_update",
                    "task_id": task_id,
                    "kind": "plex_export",
                    "story_id": story_id,
                    "stage": stage,
                    "status": "running",
                    "progress": pct,
                    "message": msg,
                })
                try:
                    asyncio.run_coroutine_threadsafe(coro, loop)
                except Exception:
                    pass

        try:
            result = await loop.run_in_executor(
                None,
                lambda: export_plex_package(
                    story_id,
                    background_volume=req.background_volume,
                    background_muted=req.background_muted,
                    background_audio=req.background_audio,
                    destination=req.destination,
                    progress_callback=_progress,
                ),
            )
            _generation_tasks[task_id].update({
                "status": "done",
                "stage": "complete",
                "progress": 1.0,
                "message": "Plex export complete",
                "result": result.to_dict(),
            })
            final_mp4 = result.mp4
            fingerprint_source = story_dir / "working" / "timeline.json"
            fingerprint = hashlib.sha256()
            if fingerprint_source.is_file():
                fingerprint.update(fingerprint_source.read_bytes())
            if final_mp4 and final_mp4.is_file():
                fingerprint.update(final_mp4.read_bytes())
            with ProductionStore(production_database_path()) as store:
                store.record_release(
                    story_id,
                    release_type="plex",
                    fingerprint=fingerprint.hexdigest(),
                    path=str(result.plex_dir),
                )
            for ws in _websocket_clients[:]:
                try:
                    await ws.send_json({
                        "type": "task_update",
                        "task_id": task_id,
                        "kind": "plex_export",
                        "story_id": story_id,
                        "status": "done",
                        "stage": "complete",
                        "progress": 1.0,
                        "message": "Plex export complete",
                        "result": result.to_dict(),
                    })
                except Exception:
                    pass
        except Exception as e:
            _generation_tasks[task_id].update({
                "status": "error",
                "stage": "error",
                "message": f"Plex export failed: {e}",
            })
            for ws in _websocket_clients[:]:
                try:
                    await ws.send_json({
                        "type": "task_update",
                        "task_id": task_id,
                        "kind": "plex_export",
                        "story_id": story_id,
                        "status": "error",
                        "stage": "error",
                        "message": f"Plex export failed: {e}",
                    })
                except Exception:
                    pass

    asyncio.create_task(_runner())

    return {
        "task_id": task_id,
        "status": "running",
        "message": "Plex export started. Watch the progress panel for status.",
    }


@router.get("/api/stories/{story_id}/export-plex")
def get_plex_export(story_id: str):
    """Return the latest Plex package for a story, or 404 if it doesn't exist.

    Used by the player/detail UI to surface the export button + check if
    a package is already on disk.
    """
    story_dir = generated_story_dir(story_id)
    plex_dir = story_dir / "final" / "plex"
    if not plex_dir.is_dir():
        raise HTTPException(status_code=404, detail="No Plex export yet")
    mp4 = next(plex_dir.glob("*.mp4"), None)
    srt = next(plex_dir.glob("*.en.srt"), None)
    vtt = next(plex_dir.glob("*.en.vtt"), None)
    poster = next(plex_dir.glob("*-poster.*"), None)
    if not mp4:
        raise HTTPException(status_code=404, detail="No MP4 in Plex directory")
    return {
        "story_id": story_id,
        "plex_dir": str(plex_dir).replace("\\", "/"),
        "mp4": str(mp4).replace("\\", "/") if mp4 else None,
        "mp4_url": f"/generated/{story_id}/final/plex/{mp4.name}" if mp4 else None,
        "srt": str(srt).replace("\\", "/") if srt else None,
        "srt_url": f"/generated/{story_id}/final/plex/{srt.name}" if srt else None,
        "vtt": str(vtt).replace("\\", "/") if vtt else None,
        "vtt_url": f"/generated/{story_id}/final/plex/{vtt.name}" if vtt else None,
        "poster": str(poster).replace("\\", "/") if poster else None,
        "poster_url": f"/generated/{story_id}/final/plex/{poster.name}" if poster else None,
    }
