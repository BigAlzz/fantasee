"""ComfyUI status + worker management endpoints.

The actual ComfyUI spawn/kill logic lives in ``comfyui_utils``; this
module is a thin FastAPI wrapper that:

* Reports whether a worker is running (``/api/comfyui/status``).
* Lists all known workers + their per-worker stats (``/api/comfyui/workers``).
* Lets the user force-spawn CPU / GPU workers from the GUI.
* Lets the user kill a specific worker by URL or port.

Also serves background-music tracks from the ``Background/`` folder
at ``/api/background/<name>`` — the player uses a separate ``<audio>``
element for background music so its volume is independent from the
narration.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse


router = APIRouter(tags=["comfyui"])


@router.get("/api/background/tracks")
def background_tracks():
    """List selectable background tracks without exposing filesystem paths."""
    try:
        from background_music import build_track_index
        return {
            "tracks": [
                {
                    "filename": track.filename,
                    "duration_seconds": track.duration_seconds,
                    "tags": track.tags,
                }
                for track in build_track_index()
            ]
        }
    except Exception as exc:
        return {"tracks": [], "error": str(exc)}


@router.get("/api/comfyui/status")
def comfyui_status():
    """Check if ComfyUI is running and return system info."""
    try:
        from comfyui_utils import is_running
        return is_running()
    except ImportError:
        return {"running": False, "error": "comfyui_utils module not found"}


@router.get("/api/background/{filename:path}")
def serve_background_audio(filename: str):
    """Serve a track from Background/ for the in-browser player.

    The player uses a separate <audio> element for background music so its
    volume is independent from the narration. The filename comes from the
    story manifest's ``background_audio`` field, which is auto-selected by
    the generator from the Background/ folder.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from background_music import configured_background_dir
    safe = Path(filename).name  # strip any path components the URL might carry
    background_dir = configured_background_dir().resolve()
    target = (background_dir / safe).resolve()
    try:
        target.relative_to(background_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Background track not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Background track not found")
    media = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
             ".ogg": "audio/ogg", ".flac": "audio/flac"}
    return FileResponse(str(target), media_type=media.get(target.suffix.lower(), "audio/mpeg"))


@router.get("/api/comfyui/workers")
def comfyui_workers():
    """Report all known ComfyUI workers (auto-spawned + manually configured).

    Includes per-worker status (running, queue depth, system stats) and
    whether the auto-spawner would launch a CPU instance to hit the
    `min_workers` target. The frontend uses this to show GPU/CPU badges
    in the navbar.
    """
    try:
        from comfyui_utils import get_worker_status
        return get_worker_status()
    except Exception as e:
        return {"error": str(e), "workers": []}


@router.post("/api/comfyui/workers/spawn-cpu")
def comfyui_spawn_cpu():
    """Force-spawn a CPU ComfyUI on the configured CPU port.

    Idempotent: if a CPU worker is already running (or one we
    previously spawned is alive), returns its current status. This
    endpoint lets the GUI add slower-but-parallel CPU throughput while
    the GPU worker handles a different image job.
    """
    try:
        from comfyui_utils import spawn_cpu_worker, get_worker_status
        spawn_cpu_worker(wait=True, wait_timeout=120)
        return get_worker_status()
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/comfyui/workers/spawn-gpu")
def comfyui_spawn_gpu():
    """Force-spawn an additional DirectML/GPU ComfyUI worker."""
    try:
        from comfyui_utils import spawn_gpu_worker, get_worker_status
        spawn_gpu_worker(wait=True, wait_timeout=120)
        return get_worker_status()
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/comfyui/workers/kill-cpu")
def comfyui_kill_cpu():
    """Stop the auto-spawned CPU ComfyUI (if we started it)."""
    try:
        from comfyui_utils import _kill_cpu_comfyui
        _kill_cpu_comfyui()
        from comfyui_utils import get_worker_status
        return get_worker_status()
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/comfyui/workers/kill")
def comfyui_kill_worker(body: dict = Body(default=None)):
    """Stop one selected local ComfyUI worker by URL or port."""
    try:
        worker_url = (body or {}).get("url") or (body or {}).get("worker_url") or (body or {}).get("port")
        from comfyui_utils import kill_worker, get_worker_status
        result = kill_worker(str(worker_url or ""))
        status = get_worker_status()
        status["result"] = result
        return status
    except Exception as e:
        return {"error": str(e)}
