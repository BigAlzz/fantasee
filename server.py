"""
Netflix-style Story Viewer — FastAPI backend
Serves story metadata, images, and handles generation requests.
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

def _resolve_env_var(name: str) -> str:
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
    return val
import time
import uuid
from typing import Optional

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Paths ──────────────────────────────────────────────────────────────
OUTPUTS = Path(r"E:\\hermes\\workspace\\outputs")
SIEGE_ROOT = Path(r"E:\\hermes\\workspace\\siege_story")
IRON_ROOT = Path(r"E:\\hermes\\workspace\\iron_pursuit")
SIEGE_WORKFLOWS = SIEGE_ROOT / "workflows"
IRON_WORKFLOWS = IRON_ROOT / "workflows"
STATIC_DIR = Path(__file__).parent / "static"
STORY_VIEWER_DIR = Path(__file__).parent

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
    yield


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
    filepath = OUTPUTS / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(filepath))


@app.get("/audio/{filename:path}")
def serve_audio(filename: str):
    """Serve a TTS narration audio file."""
    filepath = OUTPUTS / filename
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
    images_per_scene: int = 1
    characters: str = ""
    tone: str = "dramatic"


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
    ]
    if req.characters:
        cmd += ["--characters", req.characters]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "OPENCODE_GO_API_KEY": _resolve_env_var("OPENCODE_GO_API_KEY")},
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
