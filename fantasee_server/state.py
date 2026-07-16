"""Process-wide state for the Fantasee server.

Holds the mutable globals the rest of the app shares:

* ``_generation_tasks``        — dict of all in-flight and recently-completed
  tasks keyed by ``task_id``. Anything that runs in the background (a
  generate, a queue, a library run, a delete, an improve loop) gets an
  entry here so the frontend can poll for status.
* ``_websocket_clients``       — list of currently connected WebSocket
  clients. ``_broadcast_ws_json`` and ``_broadcast_ws_json_from_thread``
  fan progress events out to all of them.
* ``_stories_cache``           — in-memory snapshot of all generated
  stories, rebuilt by ``load_stories`` on startup and after every
  background task that can add or remove stories.
* ``_library_maintenance_running`` / ``_library_agent_task`` /
  ``_library_agent_failures`` — bookkeeping for the background
  "library maintenance" worker that re-completes / re-renders / re-exports
  any story that fell out of sync.

Also exposes ``_resolve_env_var`` (Hermes-aware env-var lookup) and
``atomic_write_json`` (crash-safe JSON writer). These used to be
duplicated across modules; the canonical copies now live here.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
import warnings
from datetime import datetime
from pathlib import Path

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import requests  # noqa: F401  (re-exported for downstream modules)


# ── Resolve API keys that may be Hermes-masked in .env ──────────────
# If the env var is set to a Hermes placeholder (e.g. `OPENCODE_GO_API_KEY=***`),
# the real value lives in the Hermes agent's auth.json credential pool.
# We only consult auth.json when the var is masked, so non-Hermes setups
# (the common case) keep working with plain env vars.
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path(__file__).parent.parent)))
_AUTH_PATH = _HERMES_HOME / "auth.json"


def _resolve_env_var(name: str, default: str = "") -> str:
    """Get an env var, unmasking it from auth.json if it's Hermes-masked."""
    val = os.environ.get(name, "")
    if val and not val.startswith("***"):
        return val
    # Try auth.json credential pool
    try:
        with open(_AUTH_PATH) as f:
            auth = json.load(f)
        for provider_creds in auth.get("credential_pool", {}).values():
            for cred in provider_creds:
                if cred.get("label") == name and cred.get("access_token"):
                    return cred["access_token"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return val or default


# ── Process-wide task / client bookkeeping ──────────────────────────
# ``_generation_tasks`` is a flat dict so the frontend can poll a
# single endpoint for everything: a single generate, a queue parent,
# a queue sub-task, a delete, an improve loop, etc. Tasks add a
# ``kind`` and optional ``parent`` so the UI can group them.
_generation_tasks: dict = {}
_websocket_clients: list = []

# Library maintenance bookkeeping. ``_library_maintenance_running`` is
# a coarse "is anything running right now" flag so the auto-spawned
# agent doesn't double-queue. ``_library_agent_failures`` tracks
# per-story retry counts so a story that keeps blowing up doesn't
# monopolize the agent's loop forever.
_library_maintenance_running = False
_library_agent_task = None
_library_agent_failures: dict[str, int] = {}
LIBRARY_AGENT_MAX_FAILURES = int(os.environ.get("FANTASEE_LIBRARY_AGENT_MAX_FAILURES", "3") or "3")

# In-memory snapshot of all generated stories. Rebuilt by ``load_stories``
# on startup and after background tasks that mutate the library.
_stories_cache: list[dict] | None = None


# ── WebSocket broadcast helpers ────────────────────────────────────

async def _broadcast_ws_json(payload: dict) -> None:
    """Send a JSON payload to every connected websocket client."""
    for ws in _websocket_clients[:]:
        try:
            await ws.send_json(payload)
        except Exception:
            pass


def _broadcast_ws_json_from_thread(loop: asyncio.AbstractEventLoop, payload: dict) -> None:
    """Schedule a websocket JSON broadcast from executor/thread code."""
    for ws in _websocket_clients[:]:
        try:
            asyncio.run_coroutine_threadsafe(ws.send_json(payload), loop)
        except Exception:
            pass


# ── Atomic JSON writer ─────────────────────────────────────────────

def atomic_write_json(path, data) -> None:
    """Write JSON to disk atomically: write to .tmp, then os.replace.

    Prevents partial-write corruption when a subprocess is killed mid-write.
    """
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ── Timestamp coercion (used by sort helpers and discovery) ────────

def _coerce_timestamp(value) -> float:
    """Accept epoch seconds or ISO-ish datetime strings as sort timestamps."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return 0.0
        try:
            return float(raw)
        except ValueError:
            pass
        try:
            # Python's fromisoformat accepts "YYYY-MM-DDTHH:MM:SS";
            # normalize Zulu suffix if a future writer includes one.
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _story_sort_ts(story: dict) -> float:
    """Newest-first ordering key for story lists."""
    for key in ("sort_ts", "updated_at", "created_at", "generated_at"):
        ts = _coerce_timestamp(story.get(key))
        if ts:
            return ts
    return 0.0


# ── Public utilities re-exported for convenience ──────────────────
# These used to live as ``time.time()`` / ``uuid.uuid4()`` calls in
# dozens of places; surfacing them here lets the rest of the codebase
# mock them in tests without monkey-patching stdlib.

now = time.time
new_uuid = lambda: str(uuid.uuid4())  # noqa: E731
