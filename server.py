"""Fantasee server entry point.

Wires the FastAPI app, middleware, lifespan, static frontend, and
all the modular routers in ``fantasee_server.api``. The actual
route handlers, helpers, and workers live in the ``fantasee_server``
package — this file is intentionally short.

The names re-exported near the bottom are what tests and CLI tools
expect to find on the ``server`` module (e.g. ``server._stories_cache``,
``server.load_stories``, ``server.auto_improve``). Adding a new
endpoint should normally mean adding it to the appropriate
``fantasee_server/api/*.py`` APIRouter; this file shouldn't grow.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import fantasee_server.state as _state
from fantasee_server.api import (
    actions,
    comfyui,
    delete,
    generated,
    generation,
    improvement,
    library_routes,
    migration,
    plex,
    production,
    settings,
    shots,
    stories,
    system,
    tts,
    ws,
)
from fantasee_server.library import _library_agent_loop, recover_library_jobs
from fantasee_server.paths import STATIC_DIR, load_stories
from fantasee_server.security import require_operator
from fantasee_server.startup import startup_ensure_workers
from fantasee_server.state import _library_agent_task


STUDIO_DIR = Path(__file__).parent / "studio" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Set the cache via the state module so the route handlers (which
    # imported `_stories_cache` from state at their own import time)
    # see the loaded list. Reassigning server._stories_cache would
    # only update the local name in this module.
    _state._stories_cache = load_stories()
    print(f"Loaded {len(_state._stories_cache)} stories with "
          f"{sum(len(s['scenes']) for s in _state._stories_cache)} total scenes")

    # Worker selection is durable, but the image adapter also needs a fast
    # process-local copy while it dispatches a request.
    try:
        from fantasee_server.production_runtime import production_database_path
        from fantasee_server.production_store import ProductionStore
        with ProductionStore(production_database_path()) as store:
            os.environ["FANTASEE_RENDERING_MODE"] = store.rendering_mode()
    except Exception as exc:
        print(f"[startup] Rendering mode could not be restored: {exc}")

    # Resume durable generation jobs after ComfyUI has had a chance to start.
    asyncio.create_task(generation.recover_generation_jobs())
    asyncio.create_task(recover_library_jobs())
    asyncio.create_task(shots.recover_shot_jobs())

    # On startup, check whether a ComfyUI worker is already running. If
    # not (e.g. user just ran `start.bat server` with no ComfyUI), auto-spawn
    # one DirectML GPU worker so image generation works out of the box. The
    # user can disable this with FANTASEE_AUTO_SPAWN_CPU=0.
    try:
        from comfyui_utils import is_running, _comfyui_bases
        if is_running().get("running"):
            print("[startup] ComfyUI already running on the default port")
        elif os.environ.get("COMFYUI_URLS", "").strip():
            # In max / multi-worker mode, the user has explicitly configured
            # workers via the env var. One healthy worker is enough for startup;
            # the rest are optional throughput and will be skipped until ready.
            n = len(_comfyui_bases())
            print(f"[startup] {n} workers configured via COMFYUI_URLS — "
                  f"waiting for one healthy worker in the background.")
            asyncio.create_task(startup_ensure_workers())
        elif os.environ.get("FANTASEE_AUTO_SPAWN_CPU", "1") != "0":
            print("[startup] No ComfyUI detected - auto-spawning a GPU worker "
                  "on port 8189. Set FANTASEE_AUTO_SPAWN_CPU=0 to disable.")
            # Fire and forget — the background task blocks for up to 120s
            # for the first worker to come up so the first image-gen request
            # doesn't wait on the full boot. The spawn is idempotent.
            asyncio.create_task(startup_ensure_workers())
        else:
            print("[startup] No ComfyUI detected and FANTASEE_AUTO_SPAWN_CPU=0; "
                  "image generation will fail until ComfyUI is started.")
    except Exception as e:
        print(f"[startup] ComfyUI check failed: {e}")

    if os.environ.get("FANTASEE_LIBRARY_AGENT", "1") != "0":
        print("[startup] Library maintenance agent enabled")
        _library_agent_task = asyncio.create_task(_library_agent_loop())
    else:
        print("[startup] Library maintenance agent disabled")

    yield

    if _library_agent_task:
        _library_agent_task.cancel()


app = FastAPI(title="Story Viewer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get(
            "FANTASEE_CORS_ORIGINS",
            "http://127.0.0.1:8765,http://localhost:8765",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────
# Each module in fantasee_server.api owns a family of endpoints.
# The actual handler functions live there too — see the ``# Public
# re-exports`` block below for the ones tests need to call directly.

app.include_router(stories.router)
app.include_router(generated.router)
app.include_router(generation.router, dependencies=[Depends(require_operator)])
app.include_router(comfyui.router, dependencies=[Depends(require_operator)])
app.include_router(system.router, dependencies=[Depends(require_operator)])
app.include_router(tts.router, dependencies=[Depends(require_operator)])
app.include_router(improvement.router, dependencies=[Depends(require_operator)])
app.include_router(plex.router, dependencies=[Depends(require_operator)])
app.include_router(delete.router, dependencies=[Depends(require_operator)])
app.include_router(actions.router, dependencies=[Depends(require_operator)])
app.include_router(library_routes.router, dependencies=[Depends(require_operator)])
app.include_router(migration.router, dependencies=[Depends(require_operator)])
app.include_router(production.router, dependencies=[Depends(require_operator)])
app.include_router(shots.router, dependencies=[Depends(require_operator)])
app.include_router(settings.router, dependencies=[Depends(require_operator)])
app.include_router(ws.router)

# Serve the bundled frontend (index.html, CSS, JS, etc.) at /static/.
# The root URL (``/``) is served by generated.router.serve_index
# so the SPA's index.html is returned even for the bare root.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/studio/{path:path}", include_in_schema=False)
def serve_studio(path: str = ""):
    """Serve the independently-built Studio client without replacing legacy UI."""
    index = STUDIO_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Studio is not built. Run npm run build in studio/.")
    requested = (STUDIO_DIR / path).resolve()
    if path and requested.is_file() and requested.is_relative_to(STUDIO_DIR.resolve()):
        return FileResponse(str(requested))
    return FileResponse(str(index))


# ── Public re-exports ───────────────────────────────────────────
# Tests and the few CLI tools that import ``server`` directly expect
# to find these names on the module. The actual implementations live
# in ``fantasee_server.*``; this block just re-exports the ones that
# are part of the public test surface. Internal callers should import
# from the appropriate submodule instead.

# State (mutable globals — tests patch these in place)
from fantasee_server.state import (  # noqa: E402  (re-exports below app setup)
    _broadcast_ws_json,
    _broadcast_ws_json_from_thread,
    _generation_tasks,
    _library_agent_failures,
    _library_maintenance_running,
    _resolve_env_var,
    _stories_cache,
    _story_sort_ts,
    _websocket_clients,
)

# Paths + storage
from fantasee_server.paths import (  # noqa: E402
    GEN_OUTPUTS,
    LEGACY_GEN_OUTPUTS,
    STATIC_DIR,
    STORY_VIEWER_DIR,
    generated_path,
    generated_story_dir,
    load_stories,
    path_under,
)

# Discovery
from fantasee_server.discovery import (  # noqa: E402
    _first_scene_art_url,
    _story_scene_art_urls,
    discover_generated_stories,
    generated_asset_url,
    iter_generated_story_dirs,
)

# Seed parser
from fantasee_server.seed import (  # noqa: E402
    SEED_SYSTEM,
    _coerce_seed_item,
    _parse_seed_response,
)

# Library maintenance
from fantasee_server.library import (  # noqa: E402
    _complete_story_for_library,
    _library_agent_loop,
    _run_library_maintenance_queue,
    _run_render_for_library,
    _start_library_maintenance_queue,
    incomplete_story_summaries,
    story_completion_report,
)

# Improver
from fantasee_server.improver import (  # noqa: E402
    _classify_scene_issues,
    _extract_typo_pairs,
    _llm_call_text,
    _apply_typo_fix,
    _progress_noop,
    _run_auto_improve_sync,
    _run_improve_loop_sync,
    _clamp_progress,
)

# Background-task helpers
from fantasee_server.background import (  # noqa: E402
    _push_story_action_progress,
    _run_story_action_background_task,
    _run_story_delete,
    _truthy,
)

# Route handlers (used directly by tests; mounted as routes via routers above)
from fantasee_server.api.stories import (  # noqa: E402
    get_scene,
    get_story,
    list_stories,
    serve_audio,
    serve_image,
)
from fantasee_server.api.generation import (  # noqa: E402
    _run_generation,
    _run_queue,
    get_task,
    list_tasks,
    seed_suggestions,
    start_generation,
    start_generation_queue,
)
from fantasee_server.api.comfyui import (  # noqa: E402
    comfyui_kill_cpu,
    comfyui_kill_worker,
    comfyui_spawn_cpu,
    comfyui_spawn_gpu,
    comfyui_status,
    comfyui_workers,
    serve_background_audio,
)
from fantasee_server.api.tts import (  # noqa: E402
    generate_tts_audio,
    tts_presets,
)
from fantasee_server.api.generated import (  # noqa: E402
    get_generated_story,
    get_story_review,
    list_generated_stories,
    run_critic,
    serve_generated_asset,
    serve_generated_audio,
    serve_generated_image,
    serve_generated_subtitles,
    serve_generated_video,
    serve_generated_vtt,
    serve_index,
)
from fantasee_server.api.improvement import (  # noqa: E402
    add_scene_image,
    refine_prompt,
    regenerate_scene,
    render_story,
)
from fantasee_server.api.plex import (  # noqa: E402
    export_plex,
    get_plex_export,
)
from fantasee_server.api.delete import (  # noqa: E402
    delete_story_endpoint,
)
from fantasee_server.api.actions import (  # noqa: E402
    add_images_bulk,
    auto_improve,
    extend_story,
    improve_loop,
    regenerate_story_endpoint,
    repair_story_endpoint,
    repair_story_preview,
)
from fantasee_server.api.library_routes import (  # noqa: E402
    list_incomplete_stories,
    queue_library_maintenance,
)
from fantasee_server.api.ws import (  # noqa: E402
    websocket_endpoint,
)


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Story Viewer — Netflix-style browser")
    print("  http://127.0.0.1:8765")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8765)
