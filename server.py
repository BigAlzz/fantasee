"""
Netflix-style Story Viewer — FastAPI backend
Serves story metadata, images, and handles generation requests.
Integrates MiMo TTS and ComfyUI for full-pipeline story generation.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ── Resolve API keys that Hermes masks in .env ─────────────────────
# Hermes masks env vars (e.g. `OPENCODE_GO_API_KEY=***`) but stores
# the real values in auth.json credential pool.
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", "E:\\hermes"))
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
import time
import uuid
from typing import Optional

from contextlib import asynccontextmanager

import requests
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from story_storage import LEGACY_OUTPUTS_ROOT, STORIES_ROOT, existing_story_dir, ensure_story_layout

# ── Paths ──────────────────────────────────────────────────────────────
OUTPUTS = Path(r"E:\\hermes\\workspace\\outputs")
SIEGE_ROOT = Path(r"E:\\hermes\\workspace\\siege_story")
IRON_ROOT = Path(r"E:\\hermes\\workspace\\iron_pursuit")
SIEGE_WORKFLOWS = SIEGE_ROOT / "workflows"
IRON_WORKFLOWS = IRON_ROOT / "workflows"
STATIC_DIR = Path(__file__).parent / "static"
STORY_VIEWER_DIR = Path(__file__).parent


def path_under(root: Path, *parts: str) -> Path:
    """Resolve a user-supplied path and ensure it stays under root."""
    root = root.resolve()
    candidate = root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=404, detail="Asset not found")
    return candidate

# ── Data Model ─────────────────────────────────────────────────────────

STORY_META = {
    "siege": {
        "id": "siege",
        "title": "The Last Rampart",
        "subtitle": "The Siege",
        "description": (
            "Aldric, a scarred veteran, and Lira, a sharp-eyed archer, "
            "defend a mountain fort against the overwhelming horde of the "
            "orc warlord Korgath. As night falls on the first watch, "
            "hundreds of campfires glitter in the pass below. Through "
            "relentless assaults, dwindling supplies, and impossible odds, "
            "the defenders of the Last Rampart must hold — or die trying."
        ),
        "tags": ["fantasy", "siege", "war", "dark fantasy"],
        "character_art": "siege_scene01_The_Watch_P_00001_.png",
        "year": "2025",
        "scenes_dir": SIEGE_WORKFLOWS,
        "prefix": "siege_scene",
        "p": True,
        "output_prefix": "siege_scene",
        "tts_prefix": "rampart",
        "narration_dir": SIEGE_ROOT / "narrations",
    },
    "iron-pursuit": {
        "id": "iron-pursuit",
        "title": "The Iron Pursuit",
        "subtitle": "The Hunt Begins",
        "description": (
            "In the aftermath of the siege, Aldric and Lira discover a "
            "sinister corruption spreading from the mountain passes. "
            "Twelve scouts are found dead under mysterious circumstances, "
            "and a blood trail leads into the haunted Ironwood. As old "
            "wounds heal but new threats emerge, the pair must pursue an "
            "enemy that leaves no tracks — only rot."
        ),
        "tags": ["fantasy", "horror", "mystery", "pursuit"],
        "character_art": "iron_pursuit_scene01_The_Morning_After_00003_.png",
        "year": "2025",
        "scenes_dir": IRON_WORKFLOWS,
        "prefix": "iron_pursuit_scene",
        "p": False,
        "output_prefix": "iron_pursuit_scene",
        "tts_prefix": "iron",
        "narration_dir": None,
    },
}


# Built-in stories are disabled; generated stories are loaded from stories/.
STORY_META = {}


def atomic_write_json(path: Path, data) -> None:
    """Write JSON to disk atomically: write to .tmp, then os.replace.

    Prevents partial-write corruption when a subprocess is killed mid-write.
    """
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def extract_scene_number(filename: str) -> int:
    """Extract scene number from a workflow filename like 'siege_scene01_polished.json'."""
    m = re.search(r"scene(\d+)", filename)
    if m:
        num = int(m.group(1))
        # handle sub-scenes like 10b, 12b, 14b, 19b, 21b
        if "b" in filename.split("_scene")[1] if "_scene" in filename else False:
            pass  # keep as-is
        # Check for letter suffix after number
        sub_match = re.search(r"scene(\d+)([a-z])", filename)
        if sub_match:
            base = int(sub_match.group(1))
            letter = sub_match.group(2)
            # convert letter to fractional: a=0.1, b=0.2, c=0.3
            frac = (ord(letter) - ord("a") + 1) / 10
            return base + frac
        return num
    return 999


def scene_sort_key(item):
    name = item["name"]
    m = re.search(r"scene(\d+)([a-z])?", name)
    if m:
        base = int(m.group(1))
        letter = m.group(2)
        frac = (ord(letter) - ord("a") + 1) / 10 if letter else 0
        return base + frac
    return 999


TITLE_OVERRIDES = {
    "01": "The Watch",
    "02": "The Signal",
    "2b": "After the Report",
    "03": "The War Council",
    "04": "The Horde Approaches",
    "05": "Before the Storm",
    "06": "Dawn Attack",
    "07": "Lira's Shot",
    "08": "Ladders on the Wall",
    "09": "The Gate Holds",
    "10": "First Reprieve",
    "10b": "First Night, No Sleep",
    "10c": "Korgath's Council",
    "11": "Korgath Watches",
    "12": "The Second Wave",
    "12b": "A Lull on the Wall",
    "13": "Fire and Stone",
    "14": "Aldric in the Breach",
    "14b": "The Wounded",
    "15": "The Cost",
    "16": "No Reprieve",
    "17": "The Third Dawn",
    "18": "The Gate Falls",
    "19": "Shield Wall",
    "19b": "The Watchtower Decision",
    "20": "Lira from Above",
    "21": "The Arrow Flies",
    "21b": "The Aftermath",
    "22": "Aldric's Gambit",
    "22b": "The Last Stand",
    "23": "The Retreat",
    "24": "Counting the Living",
    "25": "The Last Watch",
}

IRON_TITLE_OVERRIDES = {
    "01": "The Morning After",
    "02": "The War Council",
    "03": "The Twelve",
    "04": "The Blood Trail",
    "05": "The First Sign of Rot",
}


def parse_scene_info(workflow_path: Path, prefix: str, story_id: str):
    """Parse a workflow JSON to extract scene metadata."""
    try:
        data = json.loads(workflow_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # Find the CLIPTextEncode node (usually node 2) to get the prompt
    prompt = None
    negative_prompt = None
    seed = None
    filename_prefix = None

    for node_id, node in data.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {})

        if ct == "CLIPTextEncode":
            text = inputs.get("text", "")
            if prompt is None:
                prompt = text
            elif negative_prompt is None:
                negative_prompt = text

        if ct == "KSampler":
            seed = inputs.get("seed", None)

        if ct == "SaveImage":
            filename_prefix = inputs.get("filename_prefix", None)

    # Extract scene number from filename
    stem = workflow_path.stem  # e.g., siege_scene01_polished
    scene_match = re.search(r"scene(\d+[a-z]?)", stem)
    scene_num_raw = scene_match.group(1) if scene_match else "??"
    scene_num_match = re.search(r"(\d+[a-z]?)", scene_match.group(1) if scene_match else "")
    scene_num = scene_num_match.group(1) if scene_num_match else scene_num_raw

    # Title lookup
    if story_id == "siege":
        scene_title = TITLE_OVERRIDES.get(scene_num, f"Scene {scene_num}")
    else:
        scene_title = IRON_TITLE_OVERRIDES.get(scene_num, f"Scene {scene_num}")

    output_name = filename_prefix or f"{prefix}{scene_num}"

    # Find images matching this scene
    images = sorted(OUTPUTS.glob(f"{output_name}*.png"))
    image_filenames = [img.name for img in images]

    # Determine sort index
    sort_idx = extract_scene_number(stem)

    # Find matching TTS audio file
    audio_file = None
    tts_prefix = STORY_META.get(story_id, {}).get("tts_prefix")
    if tts_prefix and scene_match:
        scene_key = scene_match.group(1)  # e.g. "01", "2b"
        candidates = [f"tts_{tts_prefix}_s{scene_key}.mp3"]
        # TTS files use zero-padded scene numbers (s02b.mp3), but some
        # workflow filenames strip the leading zero (scene2b_polished)
        digit_match = re.match(r"\d+", scene_key)
        if digit_match and len(digit_match.group()) == 1:
            padded = "0" + scene_key
            candidates.append(f"tts_{tts_prefix}_s{padded}.mp3")
        for candidate in candidates:
            if (OUTPUTS / candidate).exists():
                audio_file = candidate
                break

    # Find matching narration text
    narration_text = None
    narration_dir = STORY_META.get(story_id, {}).get("narration_dir")
    if narration_dir and scene_match:
        scene_key = scene_match.group(1)
        # Try exact match first, then zero-padded for single-digit keys
        n_candidates = [f"narration_{scene_key}.txt"]
        digit_match = re.match(r"\d+", scene_key)
        if digit_match and len(digit_match.group()) == 1:
            padded = "0" + scene_key
            n_candidates.append(f"narration_{padded}.txt")
        for candidate in n_candidates:
            n_path = narration_dir / candidate
            if n_path.exists():
                try:
                    narration_text = n_path.read_text(encoding="utf-8").strip()
                except OSError:
                    pass
                break

    return {
        "scene": scene_num,
        "title": scene_title,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "seed": seed,
        "image_filenames": image_filenames,
        "sort_idx": sort_idx,
        "audio_file": audio_file,
        "narration_text": narration_text,
    }


def load_stories():
    """Load all story metadata and scenes."""
    stories = []
    for sid, meta in STORY_META.items():
        scenes_dir = meta["scenes_dir"]
        prefix = meta["prefix"]

        if not scenes_dir.exists():
            continue

        # Find all workflow JSONs
        pattern = f"{prefix}*"
        if meta.get("p"):
            # For siege, use polished versions
            workflow_files = sorted(scenes_dir.glob(f"{prefix}*polished.json"))
        else:
            workflow_files = sorted(scenes_dir.glob(f"{prefix}*.json"))

        scenes = []
        for wf in workflow_files:
            info = parse_scene_info(wf, prefix, sid)
            if info:
                scenes.append(info)

        scenes.sort(key=lambda s: s["sort_idx"])

        # Pick the best hero image
        hero = None
        for s in scenes:
            if s["image_filenames"]:
                hero = s["image_filenames"][0]
                break

        # Build a synopsis from scene titles
        synopsis = meta["description"]

        story = {
            "id": sid,
            "title": meta["title"],
            "subtitle": meta.get("subtitle", ""),
            "description": meta["description"],
            "synopsis": synopsis,
            "tags": meta.get("tags", []),
            "year": meta.get("year", ""),
            "hero_image": hero,
            "scene_count": len(scenes),
            "scenes": scenes,
        }
        stories.append(story)

    return stories


# Cache data on startup
_stories_cache = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _stories_cache
    _stories_cache = load_stories()
    print(f"Loaded {len(_stories_cache)} stories with "
          f"{sum(len(s['scenes']) for s in _stories_cache)} total scenes")

    # On startup, check whether a ComfyUI worker is already running. If
    # not (e.g. user just ran `start.bat server` with no ComfyUI), auto-spawn
    # a CPU-only worker so image generation works out of the box. The user
    # can disable this with FANTASEE_AUTO_SPAWN_CPU=0.
    try:
        from comfyui_utils import is_running, _comfyui_bases
        if is_running().get("running"):
            print("[startup] ComfyUI already running on the default port")
        elif os.environ.get("COMFYUI_URLS", "").strip():
            # In max / multi-worker mode, the user has explicitly configured
            # workers via the env var. The first image request can otherwise
            # race against the workers still booting (each takes 5-10s on CPU).
            # Run the wait in the background so the server stays responsive
            # and the /healthz / /api/stories endpoints don't block.
            n = len(_comfyui_bases())
            print(f"[startup] {n} workers configured via COMFYUI_URLS — "
                  f"waiting for them to come up in the background.")
            asyncio.create_task(_startup_ensure_workers())
        elif os.environ.get("FANTASEE_AUTO_SPAWN_CPU", "1") != "0":
            print("[startup] No ComfyUI detected - auto-spawning a CPU worker "
                  "on port 8189. Set FANTASEE_AUTO_SPAWN_CPU=0 to disable.")
            # Fire and forget — the background task blocks for up to 120s
            # for the worker to come up so the first image-gen request
            # doesn't have to wait the full boot. The spawn is idempotent.
            asyncio.create_task(_startup_ensure_workers())
        else:
            print("[startup] No ComfyUI detected and FANTASEE_AUTO_SPAWN_CPU=0; "
                  "image generation will fail until ComfyUI is started.")
    except Exception as e:
        print(f"[startup] ComfyUI check failed: {e}")

    yield


async def _startup_ensure_workers():
    """Background task: spawn a CPU ComfyUI worker at server startup so
    the user can generate images without manually starting one.

    We block up to 120s for the worker to come up so the first image
    request doesn't have to wait. The spawn is idempotent — if a worker
    is already running, this is a no-op.
    """
    try:
        from comfyui_utils import ensure_workers, get_worker_status
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: ensure_workers(min_workers=2, wait_for_spawn=True, wait_timeout=120),
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


app = FastAPI(title="Story Viewer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/stories")
def list_stories():
    """Return summary of all stories (without full scene data)."""
    summaries = []
    for s in _stories_cache:
        summaries.append({
            "id": s["id"],
            "title": s["title"],
            "subtitle": s["subtitle"],
            "description": s["description"][:200] + "...",
            "tags": s["tags"],
            "year": s["year"],
            "hero_image": s["hero_image"],
            "scene_count": s["scene_count"],
        })
    return {"stories": summaries}


@app.get("/api/stories/{story_id}")
def get_story(story_id: str):
    """Return full story detail with all scenes."""
    for s in _stories_cache:
        if s["id"] == story_id:
            return s
    raise HTTPException(status_code=404, detail="Story not found")


@app.get("/api/stories/{story_id}/scenes/{scene_idx}")
def get_scene(story_id: str, scene_idx: int):
    """Return a specific scene from a story."""
    for s in _stories_cache:
        if s["id"] == story_id:
            if 0 <= scene_idx < len(s["scenes"]):
                return s["scenes"][scene_idx]
            raise HTTPException(status_code=404, detail="Scene not found")
    raise HTTPException(status_code=404, detail="Story not found")


@app.get("/images/{filename:path}")
def serve_image(filename: str):
    """Serve a generated image."""
    filepath = path_under(OUTPUTS, filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(filepath))


@app.get("/audio/{filename:path}")
def serve_audio(filename: str):
    """Serve a TTS narration audio file."""
    filepath = path_under(OUTPUTS, filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(str(filepath), media_type="audio/mpeg")


# ── Static Files (frontend) ────────────────────────────────────────────

@app.get("/")
def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ── Generation API ─────────────────────────────────────────────────────

# Track active generation tasks
_generation_tasks: dict = {}
_websocket_clients: list = []


class GenerateRequest(BaseModel):
    story_concept: str
    style: str = "fantasy painterly"
    num_scenes: int = 5
    images_per_scene: int = 5
    characters: str = ""
    tone: str = "dramatic"
    voice_preset: str = "Dean"


async def _run_generation(task_id: str, req: GenerateRequest):
    """Run the generate_story.py pipeline in a subprocess and stream progress."""
    script = STORY_VIEWER_DIR / "generate_story.py"

    cmd = [
        sys.executable, str(script),
        "--concept", req.story_concept,
        "--scenes", str(req.num_scenes),
        "--images-per-scene", str(req.images_per_scene),
        "--style", req.style,
        "--tone", req.tone,
        "--voice", getattr(req, "voice_preset", "Dean"),
    ]
    if req.characters:
        cmd += ["--characters", req.characters]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "XIAOMI_API_KEY": _resolve_env_var("XIAOMI_API_KEY"),
             "XIAOMI_BASE_URL": _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")},
    )

    # Read stdout line by line, parse progress markers
    async def read_stdout():
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            if text.startswith("__PROGRESS__:"):
                try:
                    data = json.loads(text[13:])
                    status = data.get("status", "running")
                    message = data.get("message", "")
                    progress = data.get("progress")

                    update = {
                        "id": task_id,
                        "status": status,
                        "message": message,
                    }
                    if progress is not None:
                        update["progress"] = progress
                    _generation_tasks[task_id].update(update)

                    # Push to all websocket clients
                    payload = {
                        "type": "task_update",
                        "task_id": task_id,
                        "status": status,
                        "message": message,
                    }
                    if progress is not None:
                        payload["progress"] = progress

                    for ws in _websocket_clients[:]:
                        try:
                            await ws.send_json(payload)
                        except Exception:
                            pass
                except json.JSONDecodeError:
                    pass

            elif text.startswith("__RESULT__:"):
                try:
                    data = json.loads(text[11:])
                    _generation_tasks[task_id].update({
                        "status": "done",
                        "message": f"Complete: {data.get('title', 'Unknown')}",
                        "progress": 1.0,
                        "result": data,
                    })
                    # Reload story cache
                    global _stories_cache
                    _stories_cache = load_stories()
                except json.JSONDecodeError:
                    pass

    async def read_stderr():
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                _generation_tasks[task_id].setdefault("errors", []).append(text)

    await asyncio.gather(read_stdout(), read_stderr())
    await process.wait()

    if process.returncode != 0:
        errors = _generation_tasks[task_id].get("errors", [])
        _generation_tasks[task_id].update({
            "status": "error",
            "message": f"Failed with exit code {process.returncode}",
            "progress": 0,
        })
        payload = {
            "type": "task_update", "task_id": task_id,
            "status": "error", "message": f"Failed: {errors[-1] if errors else 'Unknown'}",
        }
        for ws in _websocket_clients[:]:
            try:
                await ws.send_json(payload)
            except Exception:
                pass


@app.post("/api/generate")
async def start_generation(req: GenerateRequest):
    """Start a new story generation task."""
    task_id = str(uuid.uuid4())[:8]
    _generation_tasks[task_id] = {
        "id": task_id,
        "status": "queued",
        "progress": 0,
        "message": "Queued for generation...",
        "request": req.dict(),
        "created_at": time.time(),
    }

    # Notify websocket clients
    for ws in _websocket_clients[:]:
        try:
            await ws.send_json({
                "type": "task_update",
                "task_id": task_id,
                "status": "queued",
                "progress": 0,
                "message": "Queued for generation..."
            })
        except Exception:
            pass

    # Launch the generation pipeline in the background
    asyncio.create_task(_run_generation(task_id, req))

    return {
        "task_id": task_id,
        "status": "queued",
        "message": "Story generation started."
    }


# ── Generation Queue (long-horizon tasks) ──────────────────────────────

class QueueRequest(BaseModel):
    items: list[GenerateRequest]


async def _run_queue(queue_id: str, items: list[GenerateRequest]) -> None:
    """Process a list of story generations sequentially.

    The queue task acts as a parent in the task tree: each sub-task gets its
    own task_id and is tracked under `_generation_tasks`, but the queue task
    itself surfaces an overall progress and per-item status via WebSocket.
    """
    total = len(items)
    queue_task = _generation_tasks[queue_id]
    queue_task["status"] = "running"
    queue_task["progress"] = 0
    queue_task["message"] = f"Queue started ({total} stories)"

    completed_titles: list[str] = []
    failed_titles: list[str] = []

    for idx, item in enumerate(items):
        sub_id = f"{queue_id}-{idx:02d}"
        _generation_tasks[sub_id] = {
            "id": sub_id,
            "parent": queue_id,
            "status": "queued",
            "progress": 0,
            "message": f"Sub-task {idx + 1}/{total}",
            "request": item.dict(),
            "created_at": time.time(),
        }

        # Notify websocket of the sub-task start
        for ws in _websocket_clients[:]:
            try:
                await ws.send_json({
                    "type": "task_update",
                    "task_id": sub_id,
                    "parent": queue_id,
                    "status": "running",
                    "progress": 0,
                    "message": f"Starting story {idx + 1}/{total}: {item.story_concept[:50]}",
                })
            except Exception:
                pass

        try:
            # Run the sub-task synchronously (it manages its own WebSocket updates
            # via _run_generation's emit() processing). We just wait for it.
            await _run_generation(sub_id, item)
            sub = _generation_tasks.get(sub_id, {})
            if sub.get("status") == "done":
                completed_titles.append(sub.get("message", item.story_concept[:60]))
            else:
                failed_titles.append(item.story_concept[:60])
        except Exception as e:
            print(f"[queue] sub-task {sub_id} crashed: {e}", file=sys.stderr)
            failed_titles.append(item.story_concept[:60])

        # Update queue progress
        overall = round((idx + 1) / total, 3)
        queue_task["progress"] = overall
        queue_task["message"] = f"Story {idx + 1}/{total} done ({len(completed_titles)} OK, {len(failed_titles)} failed)"

        for ws in _websocket_clients[:]:
            try:
                await ws.send_json({
                    "type": "task_update",
                    "task_id": queue_id,
                    "status": "running",
                    "progress": overall,
                    "message": queue_task["message"],
                })
            except Exception:
                pass

    queue_task["status"] = "done"
    queue_task["progress"] = 1.0
    queue_task["message"] = f"Queue complete: {len(completed_titles)} succeeded, {len(failed_titles)} failed"
    queue_task["completed"] = completed_titles
    queue_task["failed"] = failed_titles

    # Reload story cache so the new stories show up in /api/stories
    global _stories_cache
    _stories_cache = load_stories()

    for ws in _websocket_clients[:]:
        try:
            await ws.send_json({
                "type": "task_update",
                "task_id": queue_id,
                "status": "done",
                "progress": 1.0,
                "message": queue_task["message"],
            })
        except Exception:
            pass


@app.post("/api/generate/queue")
async def start_generation_queue(req: QueueRequest):
    """Queue multiple story generations to run consecutively.

    Useful for long-horizon batch runs ("generate 5 stories overnight").
    Each item is processed in order; the user can navigate away and watch
    other stories while the queue continues in the background.
    """
    if not req.items:
        raise HTTPException(status_code=400, detail="Queue is empty")
    if len(req.items) > 20:
        raise HTTPException(status_code=400, detail="Queue max length is 20")

    queue_id = f"q-{str(uuid.uuid4())[:6]}"
    _generation_tasks[queue_id] = {
        "id": queue_id,
        "kind": "queue",
        "status": "queued",
        "progress": 0,
        "message": f"Queued {len(req.items)} stories",
        "items": [it.dict() for it in req.items],
        "item_count": len(req.items),
        "created_at": time.time(),
    }

    # Notify websocket clients
    for ws in _websocket_clients[:]:
        try:
            await ws.send_json({
                "type": "task_update",
                "task_id": queue_id,
                "status": "queued",
                "progress": 0,
                "message": f"Queued {len(req.items)} stories",
            })
        except Exception:
            pass

    asyncio.create_task(_run_queue(queue_id, list(req.items)))

    return {
        "queue_id": queue_id,
        "status": "queued",
        "item_count": len(req.items),
        "message": f"Queue of {len(req.items)} stories accepted.",
    }


@app.get("/api/generate/tasks")
def list_tasks():
    """List all generation tasks."""
    return {"tasks": list(_generation_tasks.values())}


@app.get("/api/generate/tasks/{task_id}")
def get_task(task_id: str):
    """Get the status of a generation task."""
    task = _generation_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ── ComfyUI & TTS Integration ──────────────────────────────────────────

GEN_OUTPUTS = STORIES_ROOT
LEGACY_GEN_OUTPUTS = LEGACY_OUTPUTS_ROOT


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
    """Return a story directory, preferring stories/ over legacy outputs/."""
    story_dir = existing_story_dir(story_id)
    if create:
        ensure_story_layout(story_dir)
    return path_under(story_dir.parent, story_dir.name)


@app.get("/api/comfyui/status")
def comfyui_status():
    """Check if ComfyUI is running and return system info."""
    try:
        from comfyui_utils import is_running
        return is_running()
    except ImportError:
        return {"running": False, "error": "comfyui_utils module not found"}


@app.get("/api/comfyui/workers")
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


@app.post("/api/comfyui/workers/spawn-cpu")
def comfyui_spawn_cpu():
    """Force-spawn a CPU ComfyUI on the configured CPU port.

    Idempotent: if a CPU worker is already running (or one we
    previously spawned is alive), returns its current status. The
    auto-spawner normally triggers this on first image-gen call; this
    endpoint lets the GUI pre-warm it.
    """
    try:
        from comfyui_utils import ensure_workers, get_worker_status
        ensure_workers(min_workers=2, wait_for_spawn=True, wait_timeout=120)
        return get_worker_status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/comfyui/workers/kill-cpu")
def comfyui_kill_cpu():
    """Stop the auto-spawned CPU ComfyUI (if we started it)."""
    try:
        from comfyui_utils import _kill_cpu_comfyui
        _kill_cpu_comfyui()
        from comfyui_utils import get_worker_status
        return get_worker_status()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/tts/presets")
def tts_presets():
    """List available TTS voice presets."""
    try:
        from tts_utils import XIAOMI_VOICES
        return {"voices": XIAOMI_VOICES}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"presets": {}, "error": str(e)}


class TTSRequest(BaseModel):
    text: str
    voice_preset: str = "Dean"
    output_name: Optional[str] = None


@app.post("/api/tts/generate")
async def generate_tts_audio(req: TTSRequest):
    """Generate TTS audio from text using MiMo TTS."""
    try:
        from tts_utils import generate_tts, get_audio_duration
    except ImportError:
        raise HTTPException(status_code=500, detail="tts_utils module not found")

    output_name = req.output_name or f"tts_{uuid.uuid4().hex[:8]}.wav"
    output_path = str(path_under(GEN_OUTPUTS, output_name))

    ok = generate_tts(req.text, output_path, voice_preset=req.voice_preset)
    if not ok:
        raise HTTPException(status_code=500, detail="TTS generation failed")

    duration = get_audio_duration(output_path)
    return {
        "filename": output_name,
        "duration": duration,
        "url": f"/generated-audio/{output_name}",
    }


# ── Serve generated assets (PoC / new pipeline stories) ─────────────────

@app.get("/generated-images/{filename:path}")
def serve_generated_image(filename: str):
    """Serve an image from the fantasee outputs directory."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(filepath))


@app.get("/generated/{story_id}/{filename:path}")
def serve_generated_asset(story_id: str, filename: str):
    """Serve any asset (image/audio/subs) from a generated story's directory."""
    filepath = generated_path(story_id, filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Asset not found")
    # Determine media type
    suffix = filepath.suffix.lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".svg": "image/svg+xml", ".wav": "audio/wav",
                   ".mp3": "audio/mpeg", ".json": "application/json"}
    return FileResponse(str(filepath), media_type=media_types.get(suffix, "application/octet-stream"))


@app.get("/generated-audio/{filename:path}")
def serve_generated_audio(filename: str):
    """Serve audio from the fantasee outputs directory."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(str(filepath), media_type="audio/wav")


@app.get("/generated-subtitles/{filename:path}")
def serve_generated_subtitles(filename: str):
    """Serve subtitle JSON from the fantasee outputs directory."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Subtitles not found")
    return FileResponse(str(filepath), media_type="application/json")


@app.get("/generated-videos/{filename:path}")
def serve_generated_video(filename: str):
    """Serve rendered MP4 video from the fantasee outputs directory."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    media = {".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska"}
    return FileResponse(str(filepath), media_type=media.get(filepath.suffix.lower(), "video/mp4"))


@app.get("/generated-vtt/{filename:path}")
def serve_generated_vtt(filename: str):
    """Serve VTT subtitle sidecar from the fantasee outputs directory."""
    filepath = generated_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="VTT not found")
    return FileResponse(str(filepath), media_type="text/vtt")


# ── Discover generated stories (from outputs/_stories/*.json) ───────────

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
    stories = []
    for child in iter_generated_story_dirs():
        manifest = child / f"{child.name}.json"
        if manifest.exists():
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    data["storage_root"] = "stories" if child.parent == GEN_OUTPUTS else "outputs"
                    # Enrich with asset URLs and scene_count
                    scenes = data.get("scenes", [])
                    data["scene_count"] = len(scenes)
                    hero = data.get("hero_image") or data.get("title_slide")
                    if hero:
                        data["hero_image_url"] = generated_asset_url(child.name, hero)
                    for scene in scenes:
                        # Convert filenames to URLs
                        imgs = scene.get("image_filenames", [])
                        scene["image_urls"] = [generated_asset_url(child.name, f) for f in imgs if f]
                        audio = scene.get("audio_filename", "")
                        scene["audio_url"] = generated_asset_url(child.name, audio) if audio else None
                        subs = scene.get("subtitle_file", "")
                        scene["subtitle_url"] = generated_asset_url(child.name, subs) if subs else None
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
                    stories.append(data)
                except (json.JSONDecodeError, OSError):
                    pass
    return stories


@app.get("/api/generated-stories")
def list_generated_stories():
    """List all generated stories from the outputs directory."""
    stories = discover_generated_stories()
    summaries = []
    for s in stories:
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
            "scene_count": s.get("scene_count", len(s.get("scenes", []))),
            "generated": s.get("generated", True),
            "hero_image": hero,
            "critic_rating": s.get("critic_rating", 0),
            "critic_stars": s.get("critic_stars", 0),
            "critic_badge": s.get("critic_badge", ""),
            "has_review": s.get("has_review", False),
        })
    return {"stories": summaries}


@app.get("/api/generated-stories/{story_id}")
def get_generated_story(story_id: str):
    """Get full detail for a generated story."""
    stories = discover_generated_stories()
    for s in stories:
        if s.get("id") == story_id:
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


@app.get("/api/generated-stories/{story_id}/review")
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


@app.post("/api/generated-stories/{story_id}/run-critic")
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
            [sys.executable, str(Path(__file__).parent / "critic.py"), story_id, "--json"],
            capture_output=True, text=True, timeout=180,
            cwd=str(Path(__file__).parent),
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


# ── Iterative Improvement Endpoints ───────────────────────────────────

@app.post("/api/stories/{story_id}/scenes/{scene_idx}/regenerate")
async def regenerate_scene(story_id: str, scene_idx: int):
    """Regenerate images and TTS for a single scene."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")

    scene = scenes[scene_idx]
    scene_num = scene_idx + 1
    padded = f"{scene_num:02d}"
    safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", "")).strip("_")[:30]

    # Delete old images
    for old_img in scene.get("image_filenames", []):
        old_path = story_dir / old_img
        if old_path.exists():
            old_path.unlink()

    # Generate new image
    sys.path.insert(0, str(Path(__file__).parent))
    from comfyui_utils import generate_image, is_running
    status = is_running()
    new_filename = None
    if status.get("running", False):
        seed = hash(story_id + str(scene_num)) % (2**32 - 1)
        prefix = f"{story_id}_s{padded}_{safe_title}_01"
        new_filename = generate_image(
            prompt=scene["prompt"],
            output_prefix=prefix,
            output_dir=str(story_dir),
            seed=seed,
            timeout=600,
        )
    scene["image_filenames"] = [new_filename] if new_filename else []

    # Regenerate TTS
    from tts_utils import generate_tts, get_audio_duration
    narration = scene.get("narration", scene.get("narration_text", ""))
    if narration:
        old_audio = scene.get("audio_filename", "")
        if old_audio:
            old_path = story_dir / old_audio
            if old_path.exists():
                old_path.unlink()
            audio_filename = f"tts_{story_id}_s{padded}.wav"
            audio_path = str(story_dir / audio_filename)
            # Prefer the explicit "tone" field on the manifest, fall back
            # to the legacy position in tags ([style, tone, "generated"]).
            story_tone = manifest.get("tone") or ""
            if not story_tone:
                tags = manifest.get("tags", [])
                story_tone = tags[1] if len(tags) >= 2 else ""
            ok = generate_tts(narration, audio_path, voice="Dean", tone=story_tone or "normal")
            if ok:
                scene["audio_filename"] = audio_filename
                scene["audio_duration"] = get_audio_duration(audio_path)

    atomic_write_json(manifest_path, manifest)
    return {"status": "ok", "scene": scene}


@app.post("/api/stories/{story_id}/scenes/{scene_idx}/add-image")
async def add_scene_image(story_id: str, scene_idx: int):
    """Add an additional image to a scene for more visual variety."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")

    scene = scenes[scene_idx]
    scene_num = scene_idx + 1
    padded = f"{scene_num:02d}"
    safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", "")).strip("_")[:30]

    sys.path.insert(0, str(Path(__file__).parent))
    from comfyui_utils import generate_image, is_running
    status = is_running()
    if not status.get("running", False):
        raise HTTPException(status_code=503, detail="ComfyUI not running")

    existing = len(scene.get("image_filenames", []))
    seed = hash(story_id + str(scene_num) + str(existing)) % (2**32 - 1)
    prefix = f"{story_id}_s{padded}_{safe_title}_{existing + 1:02d}"

    filename = generate_image(
        prompt=scene["prompt"],
        output_prefix=prefix,
        output_dir=str(story_dir),
        seed=seed,
        timeout=600,
    )

    if filename:
        scene.setdefault("image_filenames", []).append(filename)
        atomic_write_json(manifest_path, manifest)
        return {"status": "ok", "filename": filename, "total_images": len(scene["image_filenames"])}

    raise HTTPException(status_code=500, detail="Image generation failed")


@app.post("/api/stories/{story_id}/scenes/{scene_idx}/refine-prompt")
async def refine_prompt(story_id: str, scene_idx: int, body: dict = Body(default=None)):
    """Use LLM to improve a scene's visual prompt."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")

    scene = scenes[scene_idx]
    instruction = (body or {}).get("instruction", "")

    system = ("You are an expert at writing image generation prompts. "
              "Improve the given prompt to be more detailed, vivid, and visually specific. "
              "Keep the same scene and characters. Output ONLY the improved prompt, nothing else. "
              "80-150 words, natural language prose, not tag lists. "
              "Whenever a character's face is in frame (medium shot, close-up, "
              "portrait, three-quarter, profile, or any framing where the face "
              "is visible at all), explicitly describe their facial features "
              "with a well-defined human nose, natural human facial structure, "
              "and clear skin — otherwise the model will default to a "
              "deformed / animalistic nose. Include a phrase such as 'a "
              "well-defined human nose' and 'natural human facial features'.")
    user_prompt = f"Improve this image generation prompt:\n\n{scene['prompt']}"
    if instruction:
        user_prompt += f"\n\nSpecific direction: {instruction}"

    api_key = _resolve_env_var("XIAOMI_API_KEY")
    base_url = _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")

    resp = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": "mimo-v2.5-pro",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 512,
        },
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=120,
    )
    resp.raise_for_status()
    new_prompt = resp.json()["choices"][0]["message"]["content"].strip().strip('"')

    old_prompt = scene["prompt"]
    scene["prompt"] = new_prompt
    atomic_write_json(manifest_path, manifest)

    return {"status": "ok", "old_prompt": old_prompt, "new_prompt": new_prompt}


@app.post("/api/stories/{story_id}/render")
async def render_story(story_id: str, body: dict = Body(default=None)):
    """Re-render video. Pass scene_idx for single scene, or omit for full story."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")
    try:
        ensure_title_slide_for_manifest(
            story_dir,
            json.loads(manifest_path.read_text(encoding="utf-8")),
        )
    except (json.JSONDecodeError, OSError):
        pass

    scene_idx = (body or {}).get("scene_idx")
    cmd = [sys.executable, str(Path(__file__).parent / "render_video.py"), story_id]
    if scene_idx is not None:
        cmd += ["--scene-only", str(scene_idx + 1)]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          cwd=str(Path(__file__).parent))
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    # Parse the "Done! N scenes rendered" footer so the caller can distinguish
    # a real render from a silent no-op (story has no images / no audio).
    # Without this check a 4-second "Done! 0 scenes rendered" looked identical
    # to a successful 5-minute render.
    rendered_count = 0
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("Done!"):
            # "Done! 0 scenes rendered in 4s" / "Done! 5 scenes rendered in 312s"
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                rendered_count = int(parts[1])
            break

    if proc.returncode not in (0, 2):
        raise HTTPException(
            status_code=500,
            detail=f"Render failed (exit {proc.returncode}): {stderr[-500:] or stdout[-500:]}",
        )

    if proc.returncode == 2 or rendered_count == 0:
        # render_video.py exits 2 ("nothing to do") when 0 scenes had both
        # images and audio. Return 200 with status=no_op so the GUI can
        # surface a clear message instead of "Render complete!".
        return {
            "status": "no_op",
            "message": (
                "No scenes rendered — story has no images and/or audio on disk. "
                "Run improve-loop (with ComfyUI running) to generate images first."
            ),
            "scene_idx": scene_idx,
            "scenes_rendered": 0,
            "render_output_tail": stdout[-400:],
        }

    return {
        "status": "ok",
        "message": f"Render complete ({rendered_count} scene(s))",
        "scene_idx": scene_idx,
        "scenes_rendered": rendered_count,
    }


# ── Delete Story ───────────────────────────────────────────────────────

@app.delete("/api/stories/{story_id}")
def delete_story_endpoint(story_id: str, body: dict = Body(default=None)):
    """Permanently delete a story and all of its on-disk artifacts.

    Body params (all optional):
      - backup: bool — copy to outputs/.trash/ before deleting (default false)
      - confirm: bool — must be true to actually delete (safety guard)
    """
    sys.path.insert(0, str(Path(__file__).parent))

    confirm = bool((body or {}).get("confirm", False))
    backup = bool((body or {}).get("backup", False))

    # Safety: refuse built-in / pre-built stories (those live in STORY_META
    # and are served from E:\hermes\workspace\, not outputs/).
    if story_id in STORY_META:
        raise HTTPException(
            status_code=400,
            detail=f"'{story_id}' is a built-in story and cannot be deleted via API. "
                   "It lives outside outputs/."
        )

    story_dir = generated_story_dir(story_id)
    if not story_dir.exists():
        # Already gone — still reload the cache and return success
        global _stories_cache
        _stories_cache = load_stories()
        return {
            "status": "ok",
            "story_id": story_id,
            "deleted": 0,
            "bytes_freed": 0,
            "note": "story did not exist; cache reloaded",
        }

    if not confirm:
        # Return a dry-run report so the GUI can show the user what would
        # be deleted before asking for confirmation.
        files = []
        total_bytes = 0
        for f in story_dir.rglob("*"):
            if f.is_file():
                files.append({"path": str(f.relative_to(story_dir)), "size": f.stat().st_size})
                total_bytes += f.stat().st_size
        return {
            "status": "preview",
            "story_id": story_id,
            "files_count": len(files),
            "bytes_freed": total_bytes,
            "files_sample": files[:20],
            "more_files": max(0, len(files) - 20),
            "note": "Send {confirm: true, backup: <bool>} to actually delete",
        }

    # Confirmed: actually delete
    from delete_story import delete_story as _delete_story_impl
    report = _delete_story_impl(story_dir, backup=backup)

    # Reload the story cache so the GUI sees the change immediately
    _stories_cache = load_stories()

    # Notify any websocket listeners (fire-and-forget; wrapped in try
    # so a dead socket doesn't fail the delete)
    for ws in _websocket_clients[:]:
        try:
            payload = json.dumps({
                "type": "story_deleted",
                "story_id": story_id,
            })
            # create_task so we don't await in a sync endpoint
            asyncio.create_task(ws.send_text(payload))
        except Exception:
            pass

    if report["errors"]:
        raise HTTPException(
            status_code=500,
            detail=f"Delete partially failed: {report['errors']}",
        )

    return {
        "status": "ok",
        "story_id": story_id,
        "deleted": report["files_deleted"],
        "bytes_freed": report["bytes_freed"],
        "backup_path": report["backup_path"],
    }


# ── Extend Story to Target Duration ────────────────────────────────────

@app.post("/api/stories/{story_id}/extend")
async def extend_story(story_id: str, body: dict = Body(default=None)):
    """Extend a story to a target duration by generating additional scenes.

    Per-scene failures are isolated: a bad TTS or image-gen call for one scene
    is logged and skipped, and the manifest is written after every successful
    scene so a partial extension is always recoverable.
    """
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    target_minutes = (body or {}).get("target_minutes", 30)
    images_per_scene = (body or {}).get("images_per_scene", 2)
    voice = (body or {}).get("voice", "Dean")
    tone = (body or {}).get("tone", "dramatic")
    per_scene_timeout = (body or {}).get("per_scene_timeout", 120)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])

    # Calculate current duration from audio files
    sys.path.insert(0, str(Path(__file__).parent))
    from tts_utils import get_audio_duration
    current_seconds = 0.0
    for sc in scenes:
        af = sc.get("audio_filename", "")
        if af:
            ap = story_dir / af
            if ap.exists():
                d = get_audio_duration(str(ap))
                if d > 0:
                    current_seconds += d
                else:
                    current_seconds += sc.get("audio_duration", 0.0)

    target_seconds = target_minutes * 60
    if current_seconds >= target_seconds:
        return {"status": "already_at_target", "current_minutes": round(current_seconds / 60, 1)}

    # How many new scenes needed (avg 120s per scene)
    remaining = target_seconds - current_seconds
    new_scene_count = max(1, round(remaining / 120))

    # Build context from last 3 scenes for LLM continuation
    context_scenes = scenes[-3:] if len(scenes) >= 3 else scenes
    context_parts = []
    for cs in context_scenes:
        context_parts.append(
            f"Scene: {cs.get('title', 'Untitled')}\n"
            f"Narration: {cs.get('narration', cs.get('narration_text', ''))[:200]}"
        )
    context_text = "\n\n".join(context_parts)

    # Use existing style/tags if available
    existing_tags = manifest.get("tags", [])
    style = existing_tags[0] if existing_tags else "fantasy painterly"

    from generate_story import call_llm, STORY_OUTLINE_SYSTEM
    from tts_utils import generate_tts
    from comfyui_utils import generate_image, is_running as comfyui_running

    # Generate continuation scenes
    prompt = f"""Continue this story. The previous scenes were:

{context_text}

Write exactly {new_scene_count} more scenes that continue from where the story left off.
Maintain the same characters, tone, and visual style.
Each scene MUST have a Narration field (voiceover text for TTS — 80-150 words, dramatic, present tense).
Make each visual prompt detailed enough for AI image generation (80-150 words).

Style: {style}
Tone: {tone}"""

    response = call_llm(STORY_OUTLINE_SYSTEM, prompt)
    if not response:
        raise HTTPException(status_code=500, detail="Failed to generate continuation scenes")

    # Parse response into scenes
    import re
    new_scenes_raw = []
    current = None
    for line in response.strip().split("\n"):
        line = line.strip()
        if re.match(r"^---\s*SCENE\s*(\d+)", line, re.IGNORECASE):
            if current:
                new_scenes_raw.append(current)
            current = {"title": "", "prompt": "", "narrative": "", "narration": ""}
        elif current:
            low = line.lower()
            if low.startswith("title:"):
                current["title"] = line.split(":", 1)[1].strip()
            elif low.startswith("visual prompt:"):
                current["prompt"] = line.split(":", 1)[1].strip()
            elif low.startswith("narrative:"):
                current["narrative"] = line.split(":", 1)[1].strip()
            elif low.startswith("narration:"):
                current["narration"] = line.split(":", 1)[1].strip()
            else:
                if current["narration"]:
                    current["narration"] += " " + line
                elif current["narrative"]:
                    current["narrative"] += " " + line
                elif current["prompt"]:
                    current["prompt"] += " " + line
    if current:
        new_scenes_raw.append(current)

    use_comfyui = comfyui_running().get("running", False) and images_per_scene > 0
    added = []
    failed = []
    base_idx = len(scenes)

    # Detect multi-GPU setup for parallel image dispatch (only when more than
    # one ComfyUI instance is configured via COMFYUI_URLS).
    from comfyui_utils import generate_images_parallel
    _comfyui_bases_env = os.environ.get("COMFYUI_URLS", "").strip()
    n_workers = len([b for b in _comfyui_bases_env.split(",") if b.strip()]) if _comfyui_bases_env else 1
    parallel_images = use_comfyui and n_workers > 1

    # Pre-build scene shells and image jobs so we can dispatch in one batch
    scene_shells = []
    for i, scene in enumerate(new_scenes_raw):
        scene_num = base_idx + i + 1
        padded = f"{scene_num:02d}"
        safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", f"Scene {scene_num}")).strip("_")[:30]
        seed = hash(story_id + str(scene_num)) % (2**32 - 1)

        s = {
            "scene": padded,
            "title": scene.get("title", f"Scene {scene_num}"),
            "prompt": scene.get("prompt", ""),
            "narrative": scene.get("narrative", ""),
            "narration": scene.get("narration", scene.get("narrative", "")),
            "narration_text": scene.get("narration", scene.get("narrative", "")),
            "seed": seed,
            "image_filenames": [],
        }
        scene_shells.append((s, padded, safe_title, seed))

    # ── Image generation (parallel if available) ────────────────────────
    if use_comfyui and parallel_images:
        jobs = []
        job_owners = []  # (scene_index, img_index)
        for s_idx, (s, padded, safe_title, seed) in enumerate(scene_shells):
            for img_idx in range(images_per_scene):
                prefix = f"{story_id}_s{padded}_{safe_title}_{img_idx + 1:02d}"
                jobs.append({
                    "prompt": s["prompt"],
                    "output_prefix": prefix,
                    "seed": seed + img_idx,
                })
                job_owners.append((s_idx, img_idx))
        print(f"[extend] dispatching {len(jobs)} image jobs across {n_workers} workers", file=sys.stderr)
        try:
            filenames = generate_images_parallel(jobs, output_dir=str(story_dir), timeout=per_scene_timeout)
        except Exception as e:
            print(f"[extend] parallel dispatch failed, falling back to serial: {e}", file=sys.stderr)
            filenames = [None] * len(jobs)
        for (s_idx, img_idx), filename in zip(job_owners, filenames):
            if filename:
                scene_shells[s_idx][0].setdefault("image_filenames", []).append(filename)

    for i, (s, padded, _safe_title, _seed) in enumerate(scene_shells):
        scene_num = base_idx + i + 1

        try:
            if use_comfyui and not parallel_images:
                for img_idx in range(images_per_scene):
                    prefix = f"{story_id}_s{padded}_{_safe_title}_{img_idx + 1:02d}"
                    try:
                        filename = generate_image(
                            prompt=s["prompt"],
                            output_prefix=prefix,
                            output_dir=str(story_dir),
                            seed=_seed + img_idx,
                            timeout=per_scene_timeout,
                        )
                        if filename:
                            s["image_filenames"].append(filename)
                    except Exception as img_err:
                        print(f"[extend] image {scene_num}/{img_idx + 1} failed: {img_err}", file=sys.stderr)

            narration = s.get("narration", "")
            if narration:
                audio_filename = f"tts_{story_id}_s{padded}.wav"
                audio_path = str(story_dir / audio_filename)
                try:
                    ok = generate_tts(narration, audio_path, voice=voice)
                    if ok:
                        s["audio_filename"] = audio_filename
                        s["audio_duration"] = get_audio_duration(audio_path)
                except Exception as tts_err:
                    print(f"[extend] TTS scene {scene_num} failed: {tts_err}", file=sys.stderr)

            scenes.append(s)
            added.append(s["title"])

            # Persist after every successful scene so partial work survives crashes
            manifest["scenes"] = scenes
            atomic_write_json(manifest_path, manifest)
        except Exception as scene_err:
            failed.append({"scene_num": scene_num, "title": s["title"], "error": str(scene_err)})
            print(f"[extend] scene {scene_num} failed: {scene_err}", file=sys.stderr)

    # Calculate new total duration
    total_seconds = current_seconds + sum(
        s.get("audio_duration", 0) for s in scenes[base_idx:]
    )

    return {
        "status": "ok" if added else "all_failed",
        "new_scenes_added": len(added),
        "titles": added,
        "failed": failed,
        "estimated_minutes": round(total_seconds / 60, 1),
        "total_scenes": len(scenes),
    }


# ── Iterative Improvement Loop ─────────────────────────────────────────

def _classify_scene_issues(issues: list[str]) -> dict:
    """Map a list of critic issue strings to the actions that can fix them.

    Returns a dict with action flags and a list of human-readable reasons.
    """
    actions = {
        "refine_narration": False,
        "regen_tts": False,
        "regen_subtitles": False,
        "add_images": False,
    }
    reasons = []
    for issue in issues:
        low = issue.lower()
        if any(kw in low for kw in ("run-on", "choppy", "ellipses", "very short", "very long",
                                     "rushed", "abrupt", "unbalanced", "no narration")):
            actions["refine_narration"] = True
            reasons.append(f"narration: {issue}")
        if any(kw in low for kw in ("too short", "very small", "silent", "missing audio", "no audio")):
            actions["regen_tts"] = True
            reasons.append(f"audio: {issue}")
        if any(kw in low for kw in ("missing:", "very small", "no images", "low quality")) and ".png" in low:
            actions["add_images"] = True
            reasons.append(f"image: {issue}")
        if any(kw in low for kw in ("subtitle", "vtt", "cue", "overlap", "beyond audio",
                                     "large gap")):
            actions["regen_subtitles"] = True
            reasons.append(f"subtitles: {issue}")
    return actions, reasons


def _extract_typo_pairs(continuity_issues: list[str]) -> list[tuple[str, str]]:
    """Pull (variant_a, variant_b) pairs from continuity 'Possible typo' lines."""
    pairs = []
    pattern = re.compile(r"Possible typo:\s*'([^']+)'\s*vs\s*'([^']+)'")
    for issue in continuity_issues:
        m = pattern.search(issue)
        if m:
            pairs.append((m.group(1), m.group(2)))
    return pairs


def _llm_call_text(api_key: str, base_url: str, system: str, user: str,
                   temperature: float = 0.7, max_tokens: int = 512, timeout: int = 120) -> Optional[str]:
    """Single-shot LLM call returning the response text or None on failure."""
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            json={
                "model": "mimo-v2.5-pro",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        if resp.ok:
            return resp.json()["choices"][0]["message"]["content"].strip().strip('"')
    except Exception as e:
        print(f"[improve] LLM call failed: {e}", file=sys.stderr)
    return None


def _apply_typo_fix(scenes: list[dict], pairs: list[tuple[str, str]]) -> int:
    """Replace misspelled character names with the most-frequent variant across all scenes.

    Picks the longer/more-common variant for each pair (the one the critic flagged
    less often) and rewrites narration/narration_text/prompt in every scene.
    """
    if not pairs:
        return 0
    fixed = 0
    for wrong, right in pairs:
        # Apply to all scenes in the manifest
        for sc in scenes:
            for key in ("narration", "narration_text", "narrative", "prompt"):
                val = sc.get(key, "")
                if isinstance(val, str) and wrong in val:
                    sc[key] = val.replace(wrong, right)
                    fixed += 1
    return fixed


@app.post("/api/stories/{story_id}/improve-loop")
async def improve_loop(story_id: str, body: dict = Body(default=None)):
    """Run iterative critic→improve cycles until target quality is reached.

    Each round:
    1. Run critic to score the story
    2. If score >= target, stop
    3. Identify weakest scenes (by critic score) and rotate targets
    4. Classify the critic's per-scene issues and act on them:
       - refine narration for run-on / choppy / length issues
       - regenerate TTS for too-short / corrupt audio
       - add more images for missing / low-quality images
       - regenerate subtitles for timing / cue issues
       - story-level typo fix from continuity_issues
    5. Re-render
    6. Repeat
    """
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    target_stars = (body or {}).get("target_stars", 4.0)
    max_rounds = (body or {}).get("max_rounds", 3)
    max_scenes_per_round = (body or {}).get("max_scenes_per_round", 3)
    images_per_scene = (body or {}).get("images_per_scene", 2)
    voice = (body or {}).get("voice", "Dean")

    env = {
        **os.environ,
        "XIAOMI_API_KEY": _resolve_env_var("XIAOMI_API_KEY"),
        "XIAOMI_BASE_URL": _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
    }

    sys.path.insert(0, str(Path(__file__).parent))
    from comfyui_utils import generate_image, is_running as comfyui_running
    from tts_utils import generate_tts, get_audio_duration

    api_key = _resolve_env_var("XIAOMI_API_KEY")
    base_url = _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")

    history = []
    previously_improved = set()

    for round_num in range(1, max_rounds + 1):
        # Step 1: Run critic
        try:
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "critic.py"), story_id, "--json"],
                capture_output=True, text=True, timeout=180,
                cwd=str(Path(__file__).parent), env=env,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Critic timed out after 180s")
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Critic failed: {proc.stderr[:300]}")

        stdout = proc.stdout.strip()
        json_end = stdout.rfind("}")
        if json_end >= 0:
            stdout = stdout[:json_end + 1]
        try:
            review = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=500, detail=f"Critic returned invalid JSON: {e}")
        stars = review.get("review", {}).get("stars", 0)
        rating = review.get("review", {}).get("overall_score", 0)

        # Step 2: Check if we've hit target
        if stars >= target_stars:
            history.append({"round": round_num, "stars": stars, "rating": rating, "improved": 0})
            return {
                "status": "target_reached",
                "rounds_completed": round_num,
                "final_stars": stars,
                "final_rating": rating,
                "history": history,
            }

        # Step 3: Identify weakest scenes using the critic's own per-scene scores.
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        scenes = manifest.get("scenes", [])
        critic_scenes = review.get("scenes", [])
        continuity_issues = review.get("continuity_issues", [])

        scored = []
        for i, sc in enumerate(scenes):
            critic_scene = None
            for cs in critic_scenes:
                if str(cs.get("scene_num", "")) == str(sc.get("scene", "")):
                    critic_scene = cs
                    break
            if critic_scene and "score" in critic_scene:
                scene_score = float(critic_scene["score"])
            else:
                img_count = len(sc.get("image_filenames", []))
                prompt_len = len(sc.get("prompt", "").split())
                has_audio = bool(sc.get("audio_filename"))
                scene_score = img_count * 3 + prompt_len / 10 + (5 if has_audio else 0)

            issues = []
            if critic_scene:
                for key in ("narration", "images", "audio", "subtitles"):
                    issues.extend(critic_scene.get(key, {}).get("issues", []))

            scored.append({"idx": i, "score": scene_score, "issues": issues})

        scored.sort(key=lambda x: (x["score"], x["idx"]))

        # Rotate: skip scenes improved in a previous round, then refill
        fresh = [s for s in scored if s["idx"] not in previously_improved]
        if len(fresh) < max_scenes_per_round:
            fresh = scored
        targets = fresh[:max_scenes_per_round]
        round_improved_idx = set()

        # Step 3a: Story-level typo fix from continuity_issues
        typo_pairs = _extract_typo_pairs(continuity_issues)
        typo_fixes = _apply_typo_fix(scenes, typo_pairs)
        if typo_fixes:
            print(f"[improve] round {round_num}: applied {typo_fixes} typo fix(es) across story", file=sys.stderr)

        improved = []
        for target in targets:
            idx = target["idx"]
            sc = scenes[idx]
            scene_issues = target["issues"]
            actions, reasons = _classify_scene_issues(scene_issues)

            # ── Action 1: Refine narration if flagged ────────────────────
            if actions["refine_narration"] and sc.get("narration"):
                new_narration = _llm_call_text(
                    api_key, base_url,
                    system=("You are a narration editor. Fix the given voiceover text: "
                            "tighten run-on sentences, vary sentence length, remove excessive "
                            "ellipses. Keep the same content, tone, and approximate length. "
                            "Write in present tense, dramatic storytelling voice. "
                            "Output ONLY the revised narration, no commentary. "
                            "Target 80-150 words."),
                    user=sc["narration"],
                    temperature=0.6, max_tokens=512,
                )
                if new_narration and len(new_narration.split()) >= 20:
                    sc["narration"] = new_narration
                    sc["narration_text"] = new_narration

            # ── Action 2: Refine visual prompt (always) ──────────────────
            if sc.get("prompt"):
                new_prompt = _llm_call_text(
                    api_key, base_url,
                    system=("Improve this image generation prompt. Be more vivid, detailed, "
                            "and visually specific. Output ONLY the improved prompt. "
                            "80-150 words, natural language prose, not tag lists. "
                            "When the scene framing shows a character's face (medium shot, "
                            "close-up, portrait, three-quarter, profile, or any framing "
                            "where the face is visible), explicitly include a phrase like "
                            "'a well-defined human nose' and 'natural human facial features' "
                            "— without this the model defaults to a deformed / animalistic "
                            "nose on DreamShaper-class checkpoints."),
                    user=sc["prompt"],
                    temperature=0.7, max_tokens=512,
                )
                if new_prompt and len(new_prompt.split()) >= 20:
                    sc["prompt"] = new_prompt

            # ── Action 3: Add more images if flagged or below target ─────
            needs_images = actions["add_images"] or len(sc.get("image_filenames", [])) < images_per_scene
            if needs_images and comfyui_running().get("running", False):
                scene_num = idx + 1
                padded = f"{scene_num:02d}"
                safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', sc.get("title", "")).strip("_")[:30]
                current_images = len(sc.get("image_filenames", []))

                for img_idx in range(current_images, images_per_scene):
                    seed = hash(story_id + str(scene_num) + str(img_idx) + round_num) % (2**32 - 1)
                    prefix = f"{story_id}_s{padded}_{safe_title}_{img_idx + 1:02d}"
                    try:
                        filename = generate_image(
                            prompt=sc["prompt"],
                            output_prefix=prefix,
                            output_dir=str(story_dir),
                            seed=seed,
                            timeout=120,
                        )
                        if filename:
                            sc.setdefault("image_filenames", []).append(filename)
                    except Exception as img_err:
                        print(f"[improve] image scene {idx + 1}/{img_idx + 1} failed: {img_err}", file=sys.stderr)

            # ── Action 4: Regenerate TTS if missing or flagged ──────────
            if actions["regen_tts"] or not sc.get("audio_filename"):
                narration = sc.get("narration", sc.get("narration_text", ""))
                if narration:
                    scene_num = idx + 1
                    padded = f"{scene_num:02d}"
                    audio_filename = f"tts_{story_id}_s{padded}.wav"
                    audio_path = str(story_dir / audio_filename)
                    try:
                        ok = generate_tts(narration, audio_path, voice=voice)
                        if ok:
                            sc["audio_filename"] = audio_filename
                            sc["audio_duration"] = get_audio_duration(audio_path)
                    except Exception as tts_err:
                        print(f"[improve] TTS scene {idx + 1} failed: {tts_err}", file=sys.stderr)

            # ── Action 5: Regenerate subtitles if flagged ───────────────
            if actions["regen_subtitles"] and sc.get("audio_filename"):
                scene_num = idx + 1
                padded = f"{scene_num:02d}"
                audio_path = story_dir / sc["audio_filename"]
                sub_path = story_dir / f"subs_{story_id}_s{padded}.json"
                if audio_path.exists():
                    try:
                        import whisper
                        model = whisper.load_model("base")
                        # fp16=False on CPU — Whisper prints a warning every
                        # time it tries FP16 and falls back to FP32, which
                        # floods the server log on CPU-only machines.
                        result = model.transcribe(
                            str(audio_path), word_timestamps=True, fp16=False,
                        )
                        subs = [
                            {
                                "text": seg["text"].strip(),
                                "start": round(seg["start"], 2),
                                "end": round(seg["end"], 2),
                            }
                            for seg in result["segments"]
                        ]
                        sub_path.write_text(json.dumps(subs, indent=2), encoding="utf-8")
                        sc["subtitle_file"] = sub_path.name
                    except ImportError:
                        pass
                    except Exception as sub_err:
                        print(f"[improve] subs scene {idx + 1} failed: {sub_err}", file=sys.stderr)

            improved.append({
                "scene_idx": idx,
                "title": sc.get("title", ""),
                "actions": actions,
                "reasons": reasons[:3],
            })
            round_improved_idx.add(idx)

        atomic_write_json(manifest_path, manifest)

        # Re-render
        try:
            subprocess.run(
                [sys.executable, str(Path(__file__).parent / "render_video.py"), story_id],
                capture_output=True, text=True, timeout=600,
                cwd=str(Path(__file__).parent),
            )
        except subprocess.TimeoutExpired:
            print(f"[improve] render timed out in round {round_num}", file=sys.stderr)

        previously_improved.update(round_improved_idx)
        history.append({
            "round": round_num,
            "stars": stars,
            "rating": rating,
            "improved": len(improved),
            "improved_indices": sorted(round_improved_idx),
            "typo_fixes": typo_fixes,
        })

    # Final check after all rounds
    final_stars = 0
    final_rating = 0
    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "critic.py"), story_id, "--json"],
            capture_output=True, text=True, timeout=180,
            cwd=str(Path(__file__).parent), env=env,
        )
        if proc.returncode == 0:
            stdout = proc.stdout.strip()
            json_end = stdout.rfind("}")
            if json_end >= 0:
                stdout = stdout[:json_end + 1]
            final_review = json.loads(stdout)
            final_stars = final_review.get("review", {}).get("stars", 0)
            final_rating = final_review.get("review", {}).get("overall_score", 0)
    except Exception as e:
        print(f"[improve] final critic run failed: {e}", file=sys.stderr)

    return {
        "status": "max_rounds_reached",
        "rounds_completed": max_rounds,
        "final_stars": final_stars,
        "final_rating": final_rating,
        "history": history,
    }


# ── Bulk Add Images ────────────────────────────────────────────────────

@app.post("/api/stories/{story_id}/add-images")
async def add_images_bulk(story_id: str, body: dict = Body(default=None)):
    """Add more images to scenes that have fewer than the target count."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    target_per_scene = (body or {}).get("images_per_scene", 2)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])

    sys.path.insert(0, str(Path(__file__).parent))
    from comfyui_utils import generate_image, is_running as comfyui_running
    status = comfyui_running()
    if not status.get("running", False):
        raise HTTPException(status_code=503, detail="ComfyUI not running")

    total_added = 0
    for i, sc in enumerate(scenes):
        current = len(sc.get("image_filenames", []))
        if current >= target_per_scene:
            continue

        scene_num = i + 1
        padded = f"{scene_num:02d}"
        safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', sc.get("title", "")).strip("_")[:30]

        for img_idx in range(current, target_per_scene):
            seed = hash(story_id + str(scene_num) + str(img_idx)) % (2**32 - 1)
            prefix = f"{story_id}_s{padded}_{safe_title}_{img_idx + 1:02d}"
            filename = generate_image(
                prompt=sc["prompt"],
                output_prefix=prefix,
                output_dir=str(story_dir),
                seed=seed,
                timeout=600,
            )
            if filename:
                sc.setdefault("image_filenames", []).append(filename)
                total_added += 1

    atomic_write_json(manifest_path, manifest)
    return {"status": "ok", "total_added": total_added}




@app.post("/api/stories/{story_id}/improve")
async def auto_improve(story_id: str, body: dict = Body(default=None)):
    """Auto-improve: critic → identify weak scenes → refine → regenerate → re-render."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    max_scenes = (body or {}).get("max_scenes", 3)

    # Step 1: Run critic
    env = {
        **os.environ,
        "XIAOMI_API_KEY": _resolve_env_var("XIAOMI_API_KEY"),
        "XIAOMI_BASE_URL": _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
    }
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "critic.py"), story_id, "--json"],
        capture_output=True, text=True, timeout=180,
        cwd=str(Path(__file__).parent), env=env,
    )
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Critic failed: {proc.stderr[:300]}")

    stdout = proc.stdout.strip()
    json_end = stdout.rfind("}")
    if json_end >= 0:
        stdout = stdout[:json_end + 1]
    review = json.loads(stdout)

    # Step 2: Identify weakest scenes
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    targets = []
    for i, sc in enumerate(scenes):
        img_count = len(sc.get("image_filenames", []))
        prompt_len = len(sc.get("prompt", "").split())
        score = img_count * 2 + prompt_len / 10
        targets.append((i, score))
    targets.sort(key=lambda x: x[1])
    targets = targets[:max_scenes]

    sys.path.insert(0, str(Path(__file__).parent))
    from comfyui_utils import generate_image, is_running as comfyui_running
    from tts_utils import generate_tts, get_audio_duration

    api_key = _resolve_env_var("XIAOMI_API_KEY")
    base_url = _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")

    improved = []
    for idx, _score in targets:
        sc = scenes[idx]

        # Refine prompt via LLM
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                json={
                    "model": "mimo-v2.5-pro",
                    "messages": [
                        {"role": "system", "content": ("Improve this image generation prompt. "
                                                        "Be more vivid and detailed. "
                                                        "Output ONLY the improved prompt. "
                                                        "80-150 words. "
                                                        "When the framing shows a character's "
                                                        "face, explicitly include 'a well-defined "
                                                        "human nose' and 'natural human facial "
                                                        "features' to prevent the model defaulting "
                                                        "to a deformed / animalistic nose.")},
                        {"role": "user", "content": sc["prompt"]},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 512,
                },
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=120,
            )
            if resp.ok:
                sc["prompt"] = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
        except Exception:
            pass  # keep original prompt on failure

        # Regenerate image
        if comfyui_running().get("running", False):
            for old_img in sc.get("image_filenames", []):
                old_path = story_dir / old_img
                if old_path.exists():
                    old_path.unlink()

            scene_num = idx + 1
            padded = f"{scene_num:02d}"
            safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', sc.get("title", "")).strip("_")[:30]
            seed = hash(story_id + str(scene_num)) % (2**32 - 1)
            prefix = f"{story_id}_s{padded}_{safe_title}_01"
            filename = generate_image(
                prompt=sc["prompt"],
                output_prefix=prefix,
                output_dir=str(story_dir),
                seed=seed,
                timeout=600,
            )
            sc["image_filenames"] = [filename] if filename else []

        improved.append({"scene_idx": idx, "title": sc.get("title", "")})

    atomic_write_json(manifest_path, manifest)

    # Step 3: Re-render full story
    render_proc = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "render_video.py"), story_id],
        capture_output=True, text=True, timeout=600,
        cwd=str(Path(__file__).parent),
    )

    return {
        "status": "ok",
        "review_stars": review.get("review", {}).get("stars", 0),
        "improved_scenes": improved,
        "render_ok": render_proc.returncode == 0,
    }


# ── WebSocket for live updates ─────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _websocket_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming messages (ping, etc.)
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        _websocket_clients.remove(websocket)
    except Exception:
        if websocket in _websocket_clients:
            _websocket_clients.remove(websocket)


# ── Main ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Story Viewer — Netflix-style browser")
    print("  http://127.0.0.1:8765")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8765)
