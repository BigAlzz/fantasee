"""Lifespan helpers.

Background tasks launched from the FastAPI ``lifespan`` async context
manager. They live in their own module so the entry-point ``server.py``
stays focused on wiring the app, middleware, and routes.

* ``startup_ensure_workers`` — if no ComfyUI worker is running,
  auto-spawn a GPU one. Idempotent; blocks up to 120s for the first
  worker to come up so the first image-gen request doesn't pay the
  boot cost.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


async def startup_ensure_workers() -> None:
    """Background task: ensure one ComfyUI worker at server startup.

    We block up to 120s for the worker to come up so the first image
    request doesn't have to wait. The spawn is idempotent — if a worker
    is already running, this is a no-op.
    """
    try:
        from comfyui_utils import ensure_workers, get_worker_status
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: ensure_workers(min_workers=1, wait_for_spawn=True, wait_timeout=120),
        )
        status = get_worker_status()
        urls = [w["url"] for w in status.get("workers", []) if w.get("running")]
        if urls:
            print(f"[startup] ComfyUI workers ready: {', '.join(urls)}")
        else:
            print("[startup] Auto-spawn finished but no workers are running. "
                  "Check logs or start one manually with start.bat gpu1.")
    except Exception as e:
        print(f"[startup] Auto-spawn failed: {e}")
