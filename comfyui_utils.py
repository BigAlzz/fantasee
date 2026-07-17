"""
ComfyUI Utils — Health check, workflow injection, and image generation
for Fantasee's local ComfyUI instance (AMD DirectML).
"""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from fantasee_server.security import validate_provider_url
from image_quality import inspect_story_image

# ── Config ──────────────────────────────────────────────────────────────
COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188
COMFYUI_BASE = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"


class ComfyGenerationError(RuntimeError):
    """A ComfyUI prompt completed with a provider-side execution error."""


def _safe_output_filename(filename: str) -> str:
    """Return a Windows-safe leaf filename for a generated image."""
    leaf = Path(str(filename).replace("\\", "/")).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", leaf).strip(" .")
    if not safe or safe in {".", ".."}:
        raise ValueError("ComfyUI returned an invalid image filename")
    return safe


def _history_error_message(status: dict) -> str | None:
    """Extract a compact provider error from a ComfyUI history status."""
    status_text = str(status.get("status_str") or "").lower()
    if status_text not in {"error", "failed", "failure"}:
        return None
    messages = status.get("messages") or []
    for message in messages:
        if isinstance(message, (list, tuple)) and len(message) > 1:
            detail = message[1]
            if isinstance(detail, dict):
                detail = detail.get("exception_message") or detail.get("message") or detail
            if detail:
                return str(detail)[:300]
        elif message:
            return str(message)[:300]
    return f"ComfyUI reported status {status_text}"


def _is_oom_error(message: str) -> bool:
    """Recognize provider messages that indicate a video-memory allocation failure."""
    text = str(message or "").lower()
    return any(token in text for token in ("out of memory", "not enough gpu", "cuda oom", "video memory"))


def _degraded_dimensions(width: Optional[int], height: Optional[int]) -> tuple[int, int] | None:
    """Return one conservative fallback size, preserving the source aspect ratio."""
    source_width = int(width or QUALITY_SETTINGS["width"])
    source_height = int(height or QUALITY_SETTINGS["height"])
    if source_width <= 640 and source_height <= 384:
        return None
    scale = min(0.75, 640 / max(1, source_width))
    fallback_width = max(512, int(source_width * scale) // 8 * 8)
    fallback_height = max(320, int(source_height * scale) // 8 * 8)
    return fallback_width, fallback_height


def _comfyui_bases() -> list[str]:
    """Return the list of ComfyUI base URLs to use.

    Reads COMFYUI_URLS (comma-separated) from the environment. If unset,
    returns a single-element list with the default COMFYUI_BASE so all
    existing call sites keep working unchanged.
    """
    env_val = os.environ.get("COMFYUI_URLS", "").strip()
    if not env_val:
        return [COMFYUI_BASE]
    bases = []
    for raw_url in env_val.split(","):
        try:
            bases.append(validate_provider_url(raw_url, kind="comfyui"))
        except ValueError as exc:
            print(f"[comfyui_utils] Ignoring unsafe worker URL: {exc}", file=sys.stderr)
    return bases

# Default base workflow template (the generator will inject prompt + seed).
# Resolved at request time via ``_resolve_workflow_path`` so a per-story
# workflow in ``stories/<id>/working/workflows/`` wins over a global default,
# and a missing workflow is reported with actionable guidance instead of
# a stale hard-coded path.
DEFAULT_WORKFLOW_PATH: Optional[Path] = None  # resolved lazily


def _resolve_workflow_path(explicit: Optional[str] = None) -> Optional[Path]:
    """Pick the ComfyUI workflow JSON to use for image generation.

    Resolution order (first hit wins):
    1. ``explicit`` — the caller passed a path (e.g. from a future
       admin UI or a per-scene override).
    2. ``FANTASEE_WORKFLOW_PATH`` env var.
    3. Any ``*.json`` in the current story's ``working/workflows/`` dir
       (looks up ``STORY_DIR`` from the cwd if set, otherwise skips).
    4. ``./workflow.json`` in the project root (a single shipped workflow).
    5. ``None`` — caller decides what to do.
    """
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    env = os.environ.get("FANTASEE_WORKFLOW_PATH", "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    # 3: per-story override
    story_dir_env = os.environ.get("FANTASEE_CURRENT_STORY_DIR", "").strip()
    if story_dir_env:
        wf_dir = Path(story_dir_env) / "working" / "workflows"
        if wf_dir.is_dir():
            for candidate in sorted(wf_dir.glob("*.json")):
                return candidate
    # 4: project-root default
    root_default = Path(__file__).parent / "workflow.json"
    if root_default.exists():
        return root_default
    return None

# Available checkpoints and their best use cases
CHECKPOINTS = {
    "fantasy": "DreamShaper_8_pruned.safetensors",
    "anime": "Counterfeit-V3.0_fp16.safetensors",
    "realistic": "Realistic_Vision_V5.1_fp16-no-ema.safetensors",
    "sdxl": "sd_xl_base_1.0.safetensors",
    "anything": "anything-v5.safetensors",
}


def checkpoint_for_style(style: Optional[str] = None) -> str:
    """Return the checkpoint filename best suited to a story style."""
    s = (style or "").lower()
    if any(token in s for token in ("anime", "manga", "manhwa", "webtoon")):
        return CHECKPOINTS["anime"]
    if any(token in s for token in ("fantasy", "painterly", "epic", "storybook")):
        return CHECKPOINTS["fantasy"]
    return CHECKPOINTS["fantasy"]

# Quality defaults — 896x512 (16:9). Smaller is faster: image gen is
# the bottleneck of story generation, and 512p gives plenty of detail for
# the Ken Burns zoom/pan in render_video.py while halving per-image time
# vs. 720p. The video render upscales to 1080p, masking the lower source res.
QUALITY_SETTINGS = {
    "sampler": "dpmpp_2m",
    "scheduler": "karras",
    "steps": 30,
    "cfg": 7.5,
    "width": 896,
    "height": 512,
}

# Default negative prompt.
#
# The "face / nose" block is the important one for medium-shot portraits
# on SD 1.5 (DreamShaper / Counterfeit). Without these explicit terms the
# model will happily render a pig snout / animalistic nose whenever the
# framing puts a face close to the camera — "deformed" and "bad anatomy"
# alone are too weak to block it. Keep the block explicit and aggressive.
DEFAULT_NEGATIVE = (
    "low quality, blurry, deformed, ugly, bad anatomy, distorted, "
    "watermark, text, signature, logo, extra limbs, fused fingers, "
    "mutated hands, bad proportions, cropped, out of frame, "
    "worst quality, low resolution, jpeg artifacts, "
    "photorealistic, realistic, modern, futuristic, sci-fi, "
    "cartoon, chibi, 3d render, cgi, "
    "nocturnal, peaceful, calm, relaxing, comic, manga lineart, "
    # Face / nose guard — blocks the "pig snout" failure mode on medium / close-up shots
    "pig snout, snout, animal nose, animalistic nose, animalistic face, "
    "deformed nose, ugly nose, misshapen nose, twisted nose, crooked nose, "
    "broad flat nose, button nose, button-nose, flat nose, wide nose, "
    "fused lips, missing lips, extra nostrils, two noses, "
    "deformed face, ugly face, asymmetric face, "
    "cross-eyed, lazy eye, extra eyes, missing eyes, "
    "bad eyes, poorly drawn eyes, dead eyes, "
    "bad eyebrows, missing eyebrows, "
    "unnatural skin, plastic skin, waxy skin, "
    "overexposed face, underexposed face, blown highlights on face, "
    "bad teeth, missing teeth, extra teeth, "
    "mutated face, malformed, disfigured, "
    "skin blemishes, acne, wrinkles, old age, elderly, child, baby, "
    "lowres, error, cropped, jpeg artifacts, signature, watermark, username, blurry"
)


# Keep the guard compact and scene-neutral. A large face/portrait suffix
# consumes the CLIP budget and can override the scene's action.
DEFAULT_POSITIVE_GUARD_SUFFIX = (
    "cinematic digital illustration, dynamic composition, clear subject and action, "
    "detailed environment, coherent anatomy, sharp focus, high detail"
)

# ── Health Check ────────────────────────────────────────────────────────

def is_running_at(base_url: str, timeout: float = 3.0) -> dict:
    """Check whether a ComfyUI is responding at a specific base URL.

    Same shape as is_running() but addressable; used by the auto-spawn
    supervisor to poll CPU/secondary workers.
    """
    result = {
        "running": False,
        "url": base_url,
        "queue_running": 0,
        "queue_pending": 0,
        "system_stats": None,
    }
    try:
        resp = requests.get(f"{base_url}/system_stats", timeout=timeout, allow_redirects=False)
        if resp.status_code == 200:
            result["running"] = True
            result["system_stats"] = resp.json()
            try:
                q = requests.get(
                    f"{base_url}/queue", timeout=timeout, allow_redirects=False
                ).json()
                result["queue_running"] = len(q.get("queue_running", []))
                result["queue_pending"] = len(q.get("queue_pending", []))
            except Exception:
                pass
            return result
    except (requests.ConnectionError, requests.Timeout, Exception):
        pass
    return result


def is_running(timeout: float = 3.0) -> dict:
    """
    Check if ANY configured ComfyUI worker is running. Returns the
    status of the first healthy worker found (or the default base if
    none are up).

    The previous version of this function hardcoded port 8188, which
    made every call to `is_running()` return False in CPU-only "max"
    mode where the workers are on 8189/8190/8191 and nothing is on
    8188. That caused `generate_image()` to silently bail out and
    return None, with no image ever being generated.

    Returns:
        {
            "running": bool,
            "url": str,              # URL of the first healthy worker
            "queue_running": int,
            "queue_pending": int,
            "system_stats": dict | None,
        }
    """
    # Use a short per-call timeout so we don't sit waiting for 4 dead
    # workers in series — we need to find a healthy one quickly.
    short_timeout = min(timeout, 1.5)
    for base in _comfyui_bases():
        try:
            resp = requests.get(
                f"{base}/system_stats",
                timeout=short_timeout,
                allow_redirects=False,
            )
            if resp.status_code == 200:
                result = {
                    "running": True,
                    "url": base,
                    "system_stats": resp.json(),
                    "queue_running": 0,
                    "queue_pending": 0,
                }
                # Fetch queue info for the same worker
                try:
                    q = requests.get(
                        f"{base}/queue",
                        timeout=short_timeout,
                        allow_redirects=False,
                    ).json()
                    result["queue_running"] = len(q.get("queue_running", []))
                    result["queue_pending"] = len(q.get("queue_pending", []))
                except Exception:
                    pass
                return result
        except (requests.ConnectionError, requests.Timeout, Exception):
            continue

    return {
        "running": False,
        "url": _comfyui_bases()[0] if _comfyui_bases() else COMFYUI_BASE,
        "queue_running": 0,
        "queue_pending": 0,
        "system_stats": None,
    }


def wait_for_ready(timeout: int = 120) -> bool:
    """Wait for ComfyUI to become ready. Returns True if ready within timeout."""
    start = time.time()
    while time.time() - start < timeout:
        status = is_running()
        if status["running"]:
            return True
        time.sleep(2)
    return False


# ── Worker Pool / Auto-spawn Supervisor ────────────────────────────────
#
# A single healthy GPU worker is enough for startup and first-run image
# generation. Extra workers are optional throughput capacity: configured
# workers are used when they are healthy, and the explicit worker-spawn
# endpoint can still request a second worker.
#
# Disable with FANTASEE_AUTO_SPAWN_CPU=0.
# Override CPU port with COMFYUI_CPU_PORT=8189.

import subprocess
import threading

_cpu_process: Optional[subprocess.Popen] = None
_gpu_processes: dict[str, subprocess.Popen] = {}
_cpu_lock = threading.Lock()
_gpu_lock = threading.Lock()
_cpu_spawn_attempted: bool = False


def _comfyui_paths() -> tuple[Optional[str], Optional[str]]:
    """Return (python_exe, comfyui_dir) for spawning, or (None, None).

    Reads from env vars first, then falls back to the known install path.
    """
    py = (os.environ.get("COMFYUI_PY") or "").strip()
    d = (os.environ.get("COMFYUI_DIR") or "").strip()
    if not py:
        # Known default install path on this machine
        candidate = Path.home() / "Documents" / "comfy" / "venv" / "Scripts" / "python.exe"
        if candidate.exists():
            py = str(candidate)
    if not d:
        candidate = Path.home() / "Documents" / "comfy" / "ComfyUI"
        if candidate.exists():
            d = str(candidate)
    if py and d and Path(py).exists() and Path(d).exists():
        return py, d
    return None, None


def _spawn_cpu_comfyui(port: int) -> Optional[subprocess.Popen]:
    """Spawn a GPU-backed ComfyUI on the given port as a detached subprocess.

    The function is still called ``_spawn_cpu_comfyui`` for back-compat
    with the callers (``ensure_workers``, ``_startup_ensure_workers``),
    but the spawn uses ``--directml`` (AMD GPU) — the auto-spawn is
    meant as a "the user has no ComfyUI running at all" fallback, and
    in that case we want the GPU path so renders are fast. Set
    ``FANTASEE_AUTO_SPAWN_CPU=0`` to disable this auto-spawn entirely.

    Returns the Popen handle, or None if spawn failed. The process is
    started with a new process group so it can be killed cleanly.
    """
    global _cpu_process
    py, d = _comfyui_paths()
    if not py or not d:
        print("[comfyui_utils] GPU spawn skipped: COMFYUI_PY/COMFYUI_DIR not set or not found",
              file=sys.stderr)
        return None

    log_path = Path(d).parent / f"comfyui-gpu-{port}.log"
    log_fh = open(log_path, "ab", buffering=0)

    # Force UTF-8 for the child's stdout/stderr so custom-node log lines
    # containing emoji (e.g. rgthree-comfy's celebration emoji) don't
    # crash with UnicodeEncodeError on Windows cp1252 consoles.
    spawn_env = os.environ.copy()
    spawn_env["PYTHONIOENCODING"] = "utf-8"
    spawn_env["PYTHONUTF8"] = "1"

    db_path = Path(d) / "user" / f"comfyui-{port}.db"
    # ComfyUI's --database-url is a SQLAlchemy URL, not a filesystem path.
    # sqlite:///<forward-slash-absolute-path> on Windows. The 3 slashes
    # are scheme + empty host + path; the drive letter sits in the path.
    db_url = "sqlite:///" + str(db_path).replace("\\", "/")
    kwargs = {
        "args": [py, "main.py", "--directml", "--listen", "127.0.0.1", "--port", str(port),
                 "--disable-auto-launch", "--database-url", db_url],
        "cwd": d,
        "stdout": log_fh,
        "stderr": log_fh,
        "stdin": subprocess.DEVNULL,
        "env": spawn_env,
    }
    if os.name == "nt":
        # CREATE_NEW_PROCESS_GROUP lets us kill it cleanly without
        # taking down the parent. No priority tweak — the auto-spawned
        # worker is now a GPU render and shouldn't yield to other tasks
        # the way a CPU worker would.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    print(f"[comfyui_utils] spawning GPU ComfyUI on :{port} (cwd={d}, log={log_path})",
          file=sys.stderr)
    try:
        proc = subprocess.Popen(**kwargs)
        log_fh.close()  # Close the file handle — Popen keeps its own dup
        _cpu_process = proc
        # Register this URL as a GPU worker so the picker treats it
        # as the preferred target. (Function/variable name kept
        # ``_cpu_process`` for back-compat — the global is just a
        # handle to "the auto-spawned worker".)
        gpu_url = f"http://127.0.0.1:{port}"
        _register_worker_kind(gpu_url, "gpu")
        return proc
    except Exception as e:
        print(f"[comfyui_utils] GPU spawn failed: {e}", file=sys.stderr)
        return None


def _worker_db_url(comfyui_dir: str, port: int) -> str:
    db_path = Path(comfyui_dir) / "user" / f"comfyui_{port}.db"
    return "sqlite:///" + str(db_path).replace("\\", "/")


def _add_comfyui_url(url: str) -> None:
    explicit = os.environ.get("COMFYUI_URLS", "").strip()
    urls = _comfyui_bases() if explicit else []
    if not explicit and url != COMFYUI_BASE and is_running_at(COMFYUI_BASE, timeout=0.5)["running"]:
        urls.append(COMFYUI_BASE)
    if url not in urls:
        urls.append(url)
    os.environ["COMFYUI_URLS"] = ",".join(urls)


def _remove_comfyui_url(url: str) -> None:
    urls = [u for u in _comfyui_bases() if u != url]
    os.environ["COMFYUI_URLS"] = ",".join(urls)
    _worker_kinds.pop(url, None)


def _find_free_worker_port(preferred: int, *, search_to: int = 8205) -> int:
    for port in range(preferred, search_to + 1):
        if not is_running_at(f"http://127.0.0.1:{port}", timeout=0.5)["running"]:
            return port
    raise RuntimeError(f"No free ComfyUI worker port found from {preferred} to {search_to}")


def _normalize_local_worker_url(url_or_port: str) -> tuple[str, int]:
    raw = str(url_or_port or "").strip()
    if not raw:
        raise ValueError("Worker URL is required")
    if raw.isdigit():
        raw = f"http://127.0.0.1:{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not parsed.port:
        raise ValueError(f"Invalid worker URL: {url_or_port}")
    host = parsed.hostname.lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Only local ComfyUI workers can be killed from the UI")
    if parsed.port < 1 or parsed.port > 65535:
        raise ValueError(f"Invalid worker port: {parsed.port}")
    normalized_host = "127.0.0.1" if host in ("localhost", "::1") else host
    return f"{parsed.scheme}://{normalized_host}:{parsed.port}", parsed.port


def _pid_for_listening_port(port: int) -> Optional[int]:
    try:
        if os.name == "nt":
            cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    f"$p = Get-NetTCPConnection -LocalPort {port} -State Listen "
                    "-ErrorAction SilentlyContinue | Select-Object -First 1 "
                    "-ExpandProperty OwningProcess; if ($p) { $p }"
                ),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            lines = (proc.stdout or "").strip().splitlines()
            return int(lines[0]) if lines and lines[0].strip().isdigit() else None
        proc = subprocess.run(
            ["sh", "-c", f"lsof -ti tcp:{port} -sTCP:LISTEN | head -n 1"],
            capture_output=True, text=True, timeout=10,
        )
        text = (proc.stdout or "").strip()
        return int(text) if text.isdigit() else None
    except Exception as e:
        print(f"[comfyui_utils] pid lookup failed for :{port}: {e}", file=sys.stderr)
        return None


def kill_worker(worker_url: str) -> dict:
    """Kill one local ComfyUI worker by URL or port."""
    global _cpu_process
    url, port = _normalize_local_worker_url(worker_url)
    pid = _pid_for_listening_port(port)
    if not pid:
        _remove_comfyui_url(url)
        return {"url": url, "port": port, "killed": False, "message": "Worker was not listening"}

    try:
        if os.name == "nt":
            proc_result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True, timeout=15,
            )
            if proc_result.returncode != 0:
                msg = (proc_result.stderr or proc_result.stdout or "").strip()
                raise RuntimeError(msg or f"taskkill exited {proc_result.returncode}")
        else:
            os.kill(pid, 15)
    except Exception as e:
        raise RuntimeError(f"Failed to kill worker on :{port}: {e}") from e

    proc = _gpu_processes.pop(url, None)
    if proc and proc.poll() is None:
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
    if _cpu_process and getattr(_cpu_process, "pid", None) == pid:
        _cpu_process = None
    _remove_comfyui_url(url)
    return {"url": url, "port": port, "pid": pid, "killed": True}


def _spawn_explicit_worker(port: int, kind: str) -> Optional[subprocess.Popen]:
    """Spawn a detached CPU or DirectML worker using start.bat conventions."""
    if kind not in ("cpu", "gpu"):
        raise ValueError(f"Unsupported worker kind: {kind}")

    py, d = _comfyui_paths()
    if not py or not d:
        print("[comfyui_utils] worker spawn skipped: COMFYUI_PY/COMFYUI_DIR not found",
              file=sys.stderr)
        return None

    log_path = Path(d).parent / f"comfyui-{kind}-{port}.log"
    log_fh = open(log_path, "ab", buffering=0)
    spawn_env = os.environ.copy()
    spawn_env["PYTHONIOENCODING"] = "utf-8"
    spawn_env["PYTHONUTF8"] = "1"

    mode_arg = "--directml" if kind == "gpu" else "--cpu"
    kwargs = {
        "args": [py, "main.py", mode_arg, "--listen", "127.0.0.1", "--port", str(port),
                 "--disable-auto-launch", "--database-url", _worker_db_url(d, port)],
        "cwd": d,
        "stdout": log_fh,
        "stderr": log_fh,
        "stdin": subprocess.DEVNULL,
        "env": spawn_env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    print(f"[comfyui_utils] spawning {kind.upper()} ComfyUI on :{port} (log={log_path})",
          file=sys.stderr)
    try:
        proc = subprocess.Popen(**kwargs)
        log_fh.close()
        url = f"http://127.0.0.1:{port}"
        _register_worker_kind(url, kind)
        _add_comfyui_url(url)
        return proc
    except Exception as e:
        print(f"[comfyui_utils] {kind.upper()} spawn failed: {e}", file=sys.stderr)
        return None


def spawn_gpu_worker(port: Optional[int] = None, *, wait: bool = True,
                     wait_timeout: int = 120) -> dict:
    """Force-spawn an additional DirectML/GPU ComfyUI worker."""
    preferred = port or int(os.environ.get("COMFYUI_GPU_PORT", "8188"))
    chosen_port = port or _find_free_worker_port(preferred)
    url = f"http://127.0.0.1:{chosen_port}"
    if is_running_at(url, timeout=0.5)["running"]:
        _register_worker_kind(url, "gpu")
        _add_comfyui_url(url)
        return {"url": url, "port": chosen_port, "started": False}

    with _gpu_lock:
        proc = _spawn_explicit_worker(chosen_port, "gpu")
        if proc:
            _gpu_processes[url] = proc

    if wait:
        start = time.time()
        while time.time() - start < wait_timeout:
            if is_running_at(url, timeout=1.5)["running"]:
                break
            time.sleep(1.5)
    return {"url": url, "port": chosen_port, "started": True}


def spawn_cpu_worker(port: Optional[int] = None, *, wait: bool = True,
                     wait_timeout: int = 120) -> dict:
    """Force-spawn a CPU-only ComfyUI worker."""
    global _cpu_process
    preferred = port or int(os.environ.get("COMFYUI_CPU_PORT", "8189"))
    chosen_port = port or _find_free_worker_port(preferred)
    url = f"http://127.0.0.1:{chosen_port}"
    if is_running_at(url, timeout=0.5)["running"]:
        _register_worker_kind(url, "cpu")
        _add_comfyui_url(url)
        return {"url": url, "port": chosen_port, "started": False}

    with _cpu_lock:
        proc = _spawn_explicit_worker(chosen_port, "cpu")
        if proc:
            _cpu_process = proc

    if wait:
        start = time.time()
        while time.time() - start < wait_timeout:
            if is_running_at(url, timeout=1.5)["running"]:
                break
            time.sleep(1.5)
    return {"url": url, "port": chosen_port, "started": True}


def _kill_cpu_comfyui() -> None:
    """Terminate the auto-spawned CPU ComfyUI if we started it."""
    global _cpu_process
    with _cpu_lock:
        proc = _cpu_process
        _cpu_process = None
    if not proc:
        return
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # Kill the whole process group
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=10,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception as e:
        print(f"[comfyui_utils] CPU kill failed: {e}", file=sys.stderr)


def ensure_workers(min_workers: int = 1, wait_for_spawn: bool = False,
                   wait_timeout: int = 90) -> list[str]:
    """Make sure at least `min_workers` ComfyUI workers are available.

    Behaviour:
    1. If COMFYUI_URLS is set, trust the list and (optionally) wait for
       every configured worker to come up. Previously this function
       returned the env-var list immediately without verifying the
       workers were actually reachable — which meant the very first
       image request after start-max.bat would silently fail because
       the workers were still booting.
    2. Otherwise, probe the default GPU ComfyUI on 8188. If running, use it.
    3. If fewer than `min_workers` are present AND FANTASEE_AUTO_SPAWN_CPU is
       not "0", auto-spawn a DirectML GPU ComfyUI on the fallback port and add it.
    4. Updates the COMFYUI_URLS env var with whatever we ended up with.

    Set wait_for_spawn=True to block up to wait_timeout seconds for the
    required worker count to come up. Optional extra workers are not required
    for readiness; callers should filter to healthy workers before dispatch.
    """
    global _cpu_spawn_attempted

    explicit_urls = os.environ.get("COMFYUI_URLS", "").strip()
    existing = _comfyui_bases()
    if explicit_urls and len(existing) >= min_workers:
        # User configured enough workers via env. Verify they're reachable
        # before returning, so the very first call after start-max.bat
        # doesn't fire image jobs into a half-booted worker. If
        # wait_for_spawn=False we still do a fast poll (returns as soon
        # as at least one is up), so the calling code can retry via
        # _pick_healthy_base() if needed.
        if wait_for_spawn:
            start = time.time()
            while time.time() - start < wait_timeout:
                up = [b for b in existing if is_running_at(b, timeout=1.5)["running"]]
                if len(up) >= min_workers:
                    return existing
                time.sleep(1.5)
            # Timeout — log and return what we have; caller will fall back
            # to the healthy subset at job-dispatch time.
            up_now = [b for b in existing if is_running_at(b, timeout=1.5)["running"]]
            print(
                f"[comfyui_utils] wait_for_spawn: only {len(up_now)}/{len(existing)} "
                f"workers came up within {wait_timeout}s. Configured: {existing}. "
                f"Up: {up_now}. Continuing — dead workers will be skipped at job time.",
                file=sys.stderr,
            )
        return existing

    # Auto-discover actual local workers. The default 8188 URL is only a
    # fallback address, not proof that a worker exists.
    discovered: list[str] = []
    gpu = is_running_at(COMFYUI_BASE)
    if gpu["running"]:
        discovered.append(COMFYUI_BASE)
        # Opportunistically discover optional local workers for throughput,
        # but use a short timeout so a missing second worker never delays
        # first-run generation.
        for probe_port in (8189, 8190, 8191):
            probe_url = f"http://127.0.0.1:{probe_port}"
            probe = is_running_at(probe_url, timeout=0.5)
            if probe["running"]:
                discovered.append(probe_url)

    # If we discovered any worker on a non-default port and didn't already
    # know its kind, mark it as GPU (we only auto-spawn CPU on 8189+,
    # so anything else we discover via probe is presumably GPU).
    if len(discovered) >= 2 and discovered[1] not in _worker_kinds:
        _register_worker_kind(discovered[1], "gpu")

    if os.environ.get("FANTASEE_AUTO_SPAWN_CPU", "1") == "0":
        os.environ["COMFYUI_URLS"] = ",".join(discovered)
        return discovered

    # Auto-spawn fallback worker if we still need more.
    if len(discovered) < min_workers:
        with _cpu_lock:
            if not _cpu_spawn_attempted:
                _cpu_spawn_attempted = True
                cpu_port = int(os.environ.get("COMFYUI_CPU_PORT", "8189"))
                # Don't try to spawn if the port is already taken
                if not is_running_at(f"http://127.0.0.1:{cpu_port}")["running"]:
                    _spawn_cpu_comfyui(cpu_port)

    # If wait requested, poll for the CPU worker to come up
    cpu_url = f"http://127.0.0.1:{os.environ.get('COMFYUI_CPU_PORT', '8189')}"
    if wait_for_spawn and cpu_url not in discovered:
        start = time.time()
        while time.time() - start < wait_timeout:
            if is_running_at(cpu_url)["running"]:
                discovered.append(cpu_url)
                break
            time.sleep(1.5)
    elif cpu_url not in discovered and is_running_at(cpu_url)["running"]:
        discovered.append(cpu_url)

    os.environ["COMFYUI_URLS"] = ",".join(discovered)
    return discovered


def get_worker_status() -> dict:
    """Report the current state of all known/auto-spawned workers.

    Each worker entry includes a `kind` field (one of: "gpu", "cpu",
    "manual") so the GUI can render the right label. The default
    ComfyUI base is always treated as "gpu" (it's the canonical GPU
    ComfyUI on 8188). Any worker we auto-spawn is marked "cpu" via the
    _worker_kinds registry.
    """
    urls = _comfyui_bases()
    status = {
        "auto_spawn_enabled": os.environ.get("FANTASEE_AUTO_SPAWN_CPU", "1") != "0",
        "cpu_spawned_by_us": _cpu_process is not None and _cpu_process.poll() is None,
        "cpu_pid": _cpu_process.pid if (_cpu_process and _cpu_process.poll() is None) else None,
        "workers": [],
    }
    seen = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        info = is_running_at(url)
        info["url"] = url
        try:
            _, port = _normalize_local_worker_url(url)
            info["pid"] = _pid_for_listening_port(port)
        except Exception:
            info["pid"] = None
        inferred_kind = "gpu" if url == COMFYUI_BASE else "manual"
        argv = ((info.get("system_stats") or {}).get("system") or {}).get("argv") or ""
        argv_text = " ".join(str(x) for x in argv) if isinstance(argv, list) else str(argv)
        if "--directml" in argv_text:
            inferred_kind = "gpu"
        elif "--cpu" in argv_text:
            inferred_kind = "cpu"
        info["kind"] = _worker_kinds.get(url, inferred_kind)
        status["workers"].append(info)
    return status


# Map of worker URL -> kind ("gpu", "cpu", "manual"). The auto-spawner
# populates this when it starts a CPU worker so the GUI can label it
# correctly. The default ComfyUI base is implicitly "gpu" via the
# get_worker_status() fallback above.
_worker_kinds: dict[str, str] = {}


def _register_worker_kind(url: str, kind: str) -> None:
    """Mark a worker URL as a particular kind (used by the auto-spawner)."""
    _worker_kinds[url] = kind


# ── Workflow Manipulation ───────────────────────────────────────────────

def load_workflow(path: Optional[str] = None) -> Optional[dict]:
    """Load a ComfyUI workflow JSON file.

    Resolution order is documented on :func:`_resolve_workflow_path`. When
    no workflow can be located the function logs a single actionable line
    (was previously spamming ``Workflow not found: <stale path>`` on
    every call) and returns ``None`` so the caller can surface a clear
    error to the user.
    """
    wf_path = _resolve_workflow_path(path)
    if not wf_path:
        print(
            "[comfyui_utils] No ComfyUI workflow found. Set FANTASEE_WORKFLOW_PATH "
            "to a JSON file, or place a workflow in the story's working/workflows/ "
            "directory, or drop a workflow.json next to comfyui_utils.py.",
            file=sys.stderr,
        )
        return None
    with open(wf_path, "r", encoding="utf-8") as f:
        return json.load(f)


# SD 1.5's CLIP encoder has a 77-token limit. ComfyUI silently truncates
# prompts beyond that, which causes the model to ignore the most
# descriptive parts of a long prompt. We approximate the BPE token
# count and pre-truncate intelligently, keeping the front of the prompt
# (subject, framing, action) and the back (style, quality), and dropping
# the middle if necessary.
def _approx_token_count(text: str) -> int:
    """Rough BPE token estimate. BPE on natural English text produces
    roughly 0.75 tokens per word, with commas, periods and short
    words inflating the ratio. We use 0.6 to stay safely under the
    77-token CLIP limit even on prose-heavy input.
    """
    if not text:
        return 0
    words = len(text.split())
    # Count punctuation and short tokens that often become their own BPE
    # tokens. This is a rough heuristic; exact counting requires the
    # full BPE tokenizer, which is heavyweight to load just for this.
    punct = sum(1 for c in text if c in ",.;:!?\"'()")
    return max(1, int(words / 0.6) + punct // 4)


def _clip_truncate(text: str, max_tokens: int = 77, *, preserve_tail: bool = False) -> str:
    """Truncate a prompt to fit SD 1.5's 77-token CLIP limit.

    Strategy: keep the beginning of the prompt (subject, framing,
    primary action — these set the image) and the end (style/quality
    tokens — these refine the look). If the middle has to be cut,
    prefer to drop the LEAST-informative middle. If the prompt is
    already short, return it unchanged.
    """
    if not text:
        return text
    if _approx_token_count(text) <= max_tokens:
        return text
    # Rough word budget. Use a smaller multiplier than 0.6 to leave
    # headroom for tokenization edge cases.
    # Use most of the CLIP budget. The old 55% budget plus a large portrait
    # suffix left too little room for the scene action and setting.
    word_budget = max(1, int(max_tokens * 0.58))
    words = text.split()
    if len(words) <= word_budget:
        return text
    if not preserve_tail:
        return " ".join(words[:word_budget])

    # Keep first 70% and last 30% for unordered negative terms.
    head_count = int(word_budget * 0.70)
    tail_count = word_budget - head_count
    head = " ".join(words[:head_count])
    tail = " ".join(words[-tail_count:]) if tail_count else ""
    if tail:
        return f"{head} {tail}"
    return head


def inject_prompt(
    workflow: dict,
    positive_prompt: str,
    negative_prompt: str = DEFAULT_NEGATIVE,
    seed: int = 0,
    checkpoint: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    quality: Optional[dict] = None,
    filename_prefix: Optional[str] = None,
) -> dict:
    """
    Inject a prompt and settings into a loaded workflow.

    Modifies the workflow in-place and returns it.

    Args:
        workflow: The ComfyUI workflow dict.
        positive_prompt: The text prompt for image generation.
        negative_prompt: What to avoid.
        seed: Random seed for reproducibility.
        checkpoint: Model checkpoint filename (overrides workflow default).
        width/height: Output dimensions (overrides workflow default).
        quality: Override sampler/steps/cfg settings.
        filename_prefix: Custom output filename prefix.
    """
    q = {**QUALITY_SETTINGS, **(quality or {})}

    # ComfyUI silently truncates text beyond the selected encoder limit.
    # The workflow-aware limit below preserves the scene action for both
    # standard SD 1.5 CLIP and SeaArt Long-CLIP.
    # Standard SD 1.5 CLIP accepts 77 tokens. SeaArtLongClip expands the
    # same encoder to 248 tokens, so detect it from the selected workflow.
    long_clip_nodes = {"SeaArtLongClip", "LongCLIPTextEncodeFlux"}
    has_long_clip = any(
        isinstance(node, dict) and node.get("class_type") in long_clip_nodes
        for node in workflow.values()
    )
    MAX_TOKENS = 248 if has_long_clip else 77
    positive_prompt = _clip_truncate(positive_prompt, MAX_TOKENS, preserve_tail=False)
    negative_prompt = _clip_truncate(negative_prompt, MAX_TOKENS, preserve_tail=True)

    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")

        # Positive prompt
        if ct == "CLIPTextEncode":
            existing = node["inputs"].get("text", "")
            # First CLIPTextEncode = positive, second = negative
            # Heuristic: if it contains negative keywords, it's the negative prompt
            if any(w in existing.lower() for w in ["ugly", "blurry", "deformed", "low quality"]):
                node["inputs"]["text"] = negative_prompt
            else:
                node["inputs"]["text"] = positive_prompt

        # KSampler — inject seed + quality settings
        if ct == "KSampler":
            node["inputs"]["seed"] = seed
            node["inputs"]["sampler_name"] = q["sampler"]
            node["inputs"]["scheduler"] = q["scheduler"]
            node["inputs"]["steps"] = q["steps"]
            node["inputs"]["cfg"] = q["cfg"]

        # EmptyLatentImage — dimensions
        if ct == "EmptyLatentImage":
            node["inputs"]["width"] = width or q["width"]
            node["inputs"]["height"] = height or q["height"]

        # CheckpointLoaderSimple — model
        if ct == "CheckpointLoaderSimple" and checkpoint:
            node["inputs"]["ckpt_name"] = checkpoint

        # SaveImage — filename prefix
        if ct == "SaveImage" and filename_prefix:
            node["inputs"]["filename_prefix"] = filename_prefix

    return workflow


# ── Image Generation ───────────────────────────────────────────────────

# Module-level round-robin counter so single-image calls distribute
# evenly across the configured workers instead of always hitting the
# first one. Wrapped in a lock so concurrent threads (e.g. parallel
# image jobs) don't trample each other.
import threading
_rr_lock = threading.Lock()
_rr_counter = 0
_base_lock = threading.Lock()


def _healthy_bases(timeout: float = 1.5) -> list[str]:
    """Return the subset of configured ComfyUI bases that are currently up.

    Polls every configured base in parallel-friendly order (the env-var
    list, or the default 8188 if no env is set) and returns only the
    URLs that respond to /system_stats. Used by generate_image() and
    generate_images_parallel() to avoid silently sending jobs to dead
    workers.
    """
    healthy = []
    for base in _comfyui_bases():
        status = is_running_at(base, timeout=timeout)
        if status["running"]:
            _infer_worker_kind(base, status)
            healthy.append(base)
    return healthy


def _worker_kind(url: str) -> str:
    """Return the kind of a ComfyUI worker: "gpu", "cpu", or "manual".

    Mirrors the fallback logic in :func:`get_worker_status`: an
    explicit registration in ``_worker_kinds`` wins; the default
    ComfyUI base (8188) is implicitly GPU; anything else is treated as
    a manually-configured worker of unknown kind.
    """
    if url in _worker_kinds:
        return _worker_kinds[url]
    if url == COMFYUI_BASE:
        return "gpu"
    return "manual"


def _infer_worker_kind(url: str, status: dict) -> None:
    """Record a worker's capability from ComfyUI's reported argv metadata."""
    if url in _worker_kinds:
        return
    if url == COMFYUI_BASE:
        _register_worker_kind(url, "gpu")
        return
    system = (status.get("system_stats") or {}).get("system") or {}
    argv = system.get("argv") or ""
    argv_text = " ".join(str(item) for item in argv) if isinstance(argv, list) else str(argv)
    if "--directml" in argv_text:
        _register_worker_kind(url, "gpu")
    elif "--cpu" in argv_text:
        _register_worker_kind(url, "cpu")


def _bases_by_priority(bases: list[str]) -> list[str]:
    """Reorder a worker list so GPU workers come first, then CPU, then manual.

    Within each group the original order is preserved, so
    ``COMFYUI_URLS`` order is still respected for that kind.
    """
    gpus = [b for b in bases if _worker_kind(b) == "gpu"]
    cpus = [b for b in bases if _worker_kind(b) == "cpu"]
    manuals = [b for b in bases if _worker_kind(b) not in ("gpu", "cpu")]
    return gpus + cpus + manuals


def _pick_healthy_base(worker_kind: Optional[str] = None) -> Optional[str]:
    """Pick a healthy ComfyUI worker.

    Workers are ordered GPU, then CPU, then manual for unconstrained work.
    A constrained job is only assigned to a worker with the requested kind;
    a GPU-only job must never silently fall back to a CPU worker.

    Returns None if no configured worker is currently up.
    """
    healthy = _healthy_bases()
    if not healthy:
        return None
    pool = _bases_by_priority(healthy)
    if worker_kind:
        pool = [base for base in pool if _worker_kind(base) == worker_kind]
    if not pool:
        return None

    global _rr_counter
    with _rr_lock:
        idx = _rr_counter % len(pool)
        _rr_counter += 1
        return pool[idx]


def generate_image(
    prompt: str,
    output_prefix: str = "fantasee_scene",
    output_dir: Optional[str] = None,
    negative_prompt: str = DEFAULT_NEGATIVE,
    seed: Optional[int] = None,
    checkpoint: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    timeout: int = 600,
    workflow_path: Optional[str] = None,
    append_positive_guard: bool = True,
    base_url: Optional[str] = None,
    worker_kind: Optional[str] = None,
    _degraded_retry: bool = False,
) -> Optional[str]:
    """
    Generate a single image via ComfyUI.

    Picks a healthy worker via round-robin across all configured bases
    (COMFYUI_URLS env var), so multi-worker / "max" mode actually
    distributes load. Previously this function hardcoded port 8188 and
    silently returned None in any setup that didn't have a worker on
    8188 — see the regression that prompted this fix.

    Args:
        prompt: The positive text prompt.
        output_prefix: Filename prefix for the output image.
        output_dir: Directory to copy the generated image to (ComfyUI saves to its own output dir).
        negative_prompt: What to avoid.
        seed: Random seed (random if None).
        checkpoint: Model checkpoint name.
        width/height: Output dimensions.
        timeout: Max seconds to wait for completion.
        workflow_path: Custom workflow file path.
        append_positive_guard: If True, append DEFAULT_POSITIVE_GUARD_SUFFIX to the
            positive prompt so medium / close-up shots get an explicit
            well-defined-human-nose cue. Disable only when an external caller
            has already baked the guard into its prompt.
        base_url: Optional explicit ComfyUI worker URL for queue fan-out.
        worker_kind: Optional required worker kind (``gpu`` or ``cpu``).

    Returns:
        Output filename on success, None on failure.
    """
    # Ensure at least one worker is known. A single healthy GPU is sufficient
    # for first-run generation; optional extra workers are used only when they
    # are already healthy.
    ensure_workers(min_workers=1, wait_for_spawn=False)

    # Pick a healthy worker via round-robin. This is the actual fix:
    # previously we hardcoded port 8188 here, which meant any setup
    # without a worker on 8188 (CPU-only "max" mode, GPU on a different
    # port, etc.) would silently bail out and never generate an image.
    #
    # Brief wait+retry: handles the first-request race right after
    # start-max.bat, when workers are still booting (each takes 5-10s
    # on CPU). Without this, the very first image job would silently
    # fail. ~5s total wait is enough for the spawn loop to finish and
    # the /system_stats endpoint to come up.
    base = base_url.rstrip("/") if base_url else None
    if base and worker_kind and _worker_kind(base) != worker_kind:
        raise ValueError(
            f"Worker {base} is {_worker_kind(base)}, but this job requires {worker_kind}"
        )
    for wait_attempt in range(5):
        if base:
            if is_running_at(base, timeout=2.0)["running"]:
                break
            base = None
            if base_url:
                time.sleep(1.0)
                continue
        base = _pick_healthy_base(worker_kind)
        if base:
            break
        time.sleep(1.0)
    if not base:
        # Surface a clear error instead of returning silently.
        configured = _comfyui_bases()
        print(
            f"[comfyui_utils] No healthy ComfyUI worker found after 5s. "
            f"Configured: {configured}. Did you run start-max.bat? "
            f"Is ComfyUI listening on the right port? Check the worker "
            f"window for startup errors.",
            file=sys.stderr,
        )
        return None

    # Resolve checkpoint key to actual filename
    if checkpoint and checkpoint in CHECKPOINTS:
        checkpoint = CHECKPOINTS[checkpoint]

    # Load and inject workflow
    workflow = load_workflow(workflow_path)
    if not workflow:
        return None

    use_seed = seed if seed is not None else int(time.time()) % (2**32 - 1)

    # Append the positive guard suffix (well-defined human nose etc.) so
    # medium / close-up shots don't drift into a pig snout. Skip if the
    # caller already baked equivalent language into their prompt.
    final_prompt = prompt
    if append_positive_guard and DEFAULT_POSITIVE_GUARD_SUFFIX:
        # Guard against double-append if a caller already included it.
        if DEFAULT_POSITIVE_GUARD_SUFFIX.strip() not in prompt:
            final_prompt = (prompt.rstrip(". ") + ". " + DEFAULT_POSITIVE_GUARD_SUFFIX).strip()

    workflow = inject_prompt(
        workflow,
        positive_prompt=final_prompt,
        negative_prompt=negative_prompt,
        seed=use_seed,
        checkpoint=checkpoint,
        width=width,
        height=height,
        filename_prefix=output_prefix,
    )

    # Submit to ComfyUI
    try:
        # Final health check on the worker we picked. If it died
        # between the round-robin pick and the submit, try the next
        # healthy one (up to 3 attempts).
        health_tries = 0
        while health_tries < 3:
            health = requests.get(
                f"{base}/system_stats", timeout=5, allow_redirects=False
            )
            if health.status_code == 200:
                break
            print(f"[comfyui_utils] {base} health check failed, picking another worker", file=sys.stderr)
            base = base_url.rstrip("/") if base_url else _pick_healthy_base()
            if not base:
                print("[comfyui_utils] No healthy ComfyUI worker on retry", file=sys.stderr)
                return None
            health_tries += 1
        else:
            print(f"[comfyui_utils] {base} not available after retries", file=sys.stderr)
            return None

        payload = {"prompt": workflow}
        resp = requests.post(
            f"{base}/prompt",
            json=payload,
            timeout=30,
            allow_redirects=False,
        )
        if resp.status_code != 200:
            print(f"[comfyui_utils] ComfyUI returned {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
            # Retry once after a brief pause (transient issue) and on
            # a different worker if the first one is now dead.
            time.sleep(2)
            alt = _pick_healthy_base()
            if alt and alt != base:
                base = alt
            resp = requests.post(
                f"{base}/prompt",
                json=payload,
                timeout=30,
                allow_redirects=False,
            )
            if resp.status_code != 200:
                print(f"[comfyui_utils] Retry also failed: {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
                return None
        resp.raise_for_status()
        result = resp.json()
        prompt_id = result.get("prompt_id", "")

        if not prompt_id:
            print("[comfyui_utils] No prompt_id in response", file=sys.stderr)
            return None

        print(f"[comfyui_utils] Submitted prompt_id={prompt_id} to {base}, waiting...", file=sys.stderr)

        # Poll for completion
        start_time = time.time()
        empty_output_polls = 0
        MAX_EMPTY_OUTPUT_POLLS = 2
        while time.time() - start_time < timeout:
            try:
                history_resp = requests.get(
                    f"{base}/history/{prompt_id}",
                    timeout=5,
                    allow_redirects=False,
                )
                if history_resp.status_code == 200:
                    history = history_resp.json()
                    if prompt_id in history:
                        entry = history[prompt_id]
                        status = entry.get("status", {})
                        provider_error = _history_error_message(status)
                        if provider_error:
                            raise ComfyGenerationError(
                                f"ComfyUI prompt {prompt_id} failed: {provider_error}"
                            )
                        if status.get("completed", False) is False and status.get("status_str") not in ("success", None):
                            # Still running, keep waiting
                            time.sleep(3)
                            continue

                        # Find output images
                        outputs = entry.get("outputs", {})
                        found_image = None
                        found_subfolder = ""
                        for node_out in outputs.values():
                            for img_list in node_out.values():
                                if isinstance(img_list, list):
                                    for img in img_list:
                                        if isinstance(img, dict) and img.get("filename"):
                                            found_image = img["filename"]
                                            found_subfolder = str(img.get("subfolder") or "")
                                            break
                                    if found_image:
                                        break
                            if found_image:
                                break

                        if found_image:
                            elapsed = time.time() - start_time
                            print(
                                f"[comfyui_utils] Image ready in {elapsed:.1f}s on {base}: {found_image}",
                                file=sys.stderr,
                            )
                            # Copy from ComfyUI output to our output dir
                            comfyui_out = Path.home() / "Documents/comfy/ComfyUI/output"
                            safe_filename = _safe_output_filename(found_image)
                            subfolder_path = Path(found_subfolder.replace("\\", "/")) if found_subfolder else Path()
                            if subfolder_path.is_absolute() or ".." in subfolder_path.parts:
                                raise ValueError("ComfyUI returned an unsafe image subfolder")
                            source_relative = subfolder_path / found_image if found_subfolder else Path(found_image)
                            src = comfyui_out / source_relative
                            validated_path = src
                            if src.exists():
                                dest_dir = Path(output_dir) if output_dir else Path(".")
                                dest_dir.mkdir(parents=True, exist_ok=True)
                                import shutil
                                dest = dest_dir / safe_filename
                                shutil.copy2(str(src), str(dest))
                                validated_path = dest
                                print(
                                    f"[comfyui_utils] Copied to: {dest}",
                                    file=sys.stderr,
                                )
                            usable, reason = inspect_story_image(validated_path)
                            if not usable:
                                print(
                                    f"[comfyui_utils] Rejected invalid image {validated_path}: {reason}",
                                    file=sys.stderr,
                                )
                                return None
                            return safe_filename

                        # Prompt finished but produced no images — this is a real error
                        empty_output_polls += 1
                        if empty_output_polls >= MAX_EMPTY_OUTPUT_POLLS:
                            print(
                                f"[comfyui_utils] Prompt {prompt_id} finished with no image outputs "
                                f"after {empty_output_polls} polls — workflow may have no SaveImage node "
                                f"or it errored silently",
                                file=sys.stderr,
                            )
                            return None
                time.sleep(3)
            except ComfyGenerationError:
                raise
            except Exception:
                time.sleep(3)

        print(f"[comfyui_utils] Timeout after {timeout}s waiting for prompt_id={prompt_id}", file=sys.stderr)
        return None

    except ComfyGenerationError as error:
        if base_url is None:
            alternatives = [
                worker for worker in _healthy_bases()
                if worker != base and (not worker_kind or _worker_kind(worker) == worker_kind)
            ]
            if alternatives:
                fallback = alternatives[0]
                print(
                    f"[comfyui_utils] Retrying failed prompt on alternate worker {fallback}",
                    file=sys.stderr,
                )
                return generate_image(
                    prompt=prompt,
                    output_prefix=output_prefix,
                    output_dir=output_dir,
                    negative_prompt=negative_prompt,
                    seed=seed,
                    checkpoint=checkpoint,
                    width=width,
                    height=height,
                    timeout=timeout,
                    workflow_path=workflow_path,
                    append_positive_guard=append_positive_guard,
                    base_url=fallback,
                    worker_kind=worker_kind,
                    _degraded_retry=_degraded_retry,
                )
        message = str(error)
        if not _degraded_retry and _is_oom_error(message):
            fallback_dimensions = _degraded_dimensions(width, height)
            if fallback_dimensions:
                fallback_width, fallback_height = fallback_dimensions
                print(
                    f"[comfyui_utils] Retrying OOM prompt at reduced dimensions "
                    f"{fallback_width}x{fallback_height}",
                    file=sys.stderr,
                )
                return generate_image(
                    prompt=prompt,
                    output_prefix=output_prefix,
                    output_dir=output_dir,
                    negative_prompt=negative_prompt,
                    seed=seed,
                    checkpoint=checkpoint,
                    width=fallback_width,
                    height=fallback_height,
                    timeout=timeout,
                    workflow_path=workflow_path,
                    append_positive_guard=append_positive_guard,
                    base_url=base,
                    worker_kind=worker_kind,
                    _degraded_retry=True,
                )
        raise
    except requests.ConnectionError:
        print(f"[comfyui_utils] Connection error to {base} — ComfyUI may have stopped", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[comfyui_utils] Error: {e}", file=sys.stderr)
        return None


def _generate_image_to_base(base_url: str, prompt: str, output_prefix: str,
                            output_dir: str, negative_prompt: str = DEFAULT_NEGATIVE,
                            seed: Optional[int] = None, checkpoint: Optional[str] = None,
                            width: Optional[int] = None, height: Optional[int] = None,
                            timeout: int = 600,
                            workflow_path: Optional[str] = None,
                            worker_kind: Optional[str] = None) -> Optional[str]:
    """Generate a single image on a specific ComfyUI base URL.

    Same as generate_image() but accepts an explicit base URL, which lets us
    fan out work across multiple ComfyUI instances running on different ports.
    """
    return generate_image(
        prompt=prompt,
        output_prefix=output_prefix,
        output_dir=output_dir,
        negative_prompt=negative_prompt,
        seed=seed,
        checkpoint=checkpoint,
        width=width,
        height=height,
        timeout=timeout,
        workflow_path=workflow_path,
        base_url=base_url,
        worker_kind=worker_kind,
    )


def generate_images_parallel(
    jobs: list[dict],
    output_dir: str,
    timeout: int = 600,
    max_workers: Optional[int] = None,
) -> list[Optional[str]]:
    """Run a batch of image-generation jobs in parallel across ComfyUI instances.

    Args:
        jobs: list of dicts with keys: prompt, output_prefix, seed (optional),
              checkpoint (optional), width/height (optional).
        output_dir: where to copy the output images.
        timeout: per-image timeout.
        max_workers: override parallelism (default: number of available ComfyUI bases).

    Returns:
        list of filenames (or None) in the same order as `jobs`.
    """
    # First-run stories only require one healthy worker. Extra workers still
    # improve throughput once they are up, but a second configured worker must
    # not delay the first image.
    ensure_workers(min_workers=1, wait_for_spawn=True, wait_timeout=90)

    bases = _bases_by_priority(_healthy_bases())
    if not bases:
        return [None] * len(jobs)
    if max_workers is None:
        max_workers = min(len(bases), 4)  # cap to avoid OOM

    from concurrent.futures import ThreadPoolExecutor, as_completed
    results: list[Optional[str]] = [None] * len(jobs)

    def _run_one(idx: int, base: str, job: dict) -> tuple[int, Optional[str]]:
        return idx, _generate_image_to_base(
            base,
            prompt=job["prompt"],
            output_prefix=job["output_prefix"],
            output_dir=output_dir,
            seed=job.get("seed"),
            checkpoint=job.get("checkpoint"),
            width=job.get("width"),
            height=job.get("height"),
            timeout=timeout,
            worker_kind=job.get("worker_kind"),
        )

    # Round-robin assign jobs to available bases so load is spread evenly
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = []
        for i, job in enumerate(jobs):
            requested_kind = job.get("worker_kind")
            eligible = [base for base in bases if not requested_kind or _worker_kind(base) == requested_kind]
            if not eligible:
                print(
                    f"[comfyui_utils] No healthy {requested_kind} worker for parallel job {i}",
                    file=sys.stderr,
                )
                continue
            base = eligible[i % len(eligible)]
            futures.append(ex.submit(_run_one, i, base, job))
        for fut in as_completed(futures):
            try:
                idx, filename = fut.result()
                results[idx] = filename
            except Exception as e:
                print(f"[comfyui_utils] parallel job failed: {e}", file=sys.stderr)

    return results


def generate_scene_images(
    scenes: list[dict],
    story_id: str,
    output_dir: str,
    checkpoint: str = "fantasy",
    images_per_scene: int = 5,
    quality: Optional[dict] = None,
) -> dict:
    """
    Generate images for multiple scenes.

    Args:
        scenes: List of scene dicts with 'prompt' key.
        story_id: Story identifier for filenames.
        output_dir: Directory for output images.
        checkpoint: Checkpoint key from CHECKPOINTS dict.
        images_per_scene: Number of images per scene.
        quality: Override quality settings.

    Returns:
        Dict mapping scene index (str) to list of filenames.
    """
    ckpt_name = CHECKPOINTS.get(checkpoint, CHECKPOINTS["fantasy"])
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    scene_images = {}
    total = len(scenes)

    for i, scene in enumerate(scenes):
        prompt_text = scene.get("prompt", "")
        if not prompt_text or len(prompt_text.strip()) < 10:
            print(f"  [SKIP] Scene {i + 1}: no prompt", file=sys.stderr)
            continue

        images = []
        for img_idx in range(images_per_scene):
            scene_num = f"{i + 1:02d}"
            safe_title = re.sub(r"[^a-zA-Z0-9]+", "_", scene.get("title", f"scene{scene_num}")).strip("_")[:30]
            prefix = f"{story_id}_s{scene_num}_{safe_title}_{img_idx + 1:02d}"

            # Check if already exists (cached)
            cached = list(output_path.glob(f"{prefix}*"))
            if cached:
                print(f"  [CACHED] Scene {i + 1} img {img_idx + 1}", file=sys.stderr)
                images.append(cached[0].name)
                continue

            print(f"  [GEN] Scene {i + 1}/{total} img {img_idx + 1}/{images_per_scene}...", file=sys.stderr)
            filename = generate_image(
                prompt=prompt_text,
                output_prefix=prefix,
                seed=int(hashlib.md5(f"{story_id}{i}{img_idx}".encode()).hexdigest()[:8], 16) % (2**32 - 1),
                checkpoint=ckpt_name,
                width=quality.get("width") if quality else None,
                height=quality.get("height") if quality else None,
            )
            if filename:
                images.append(filename)
                print(f"    ✓ {filename}", file=sys.stderr)
            else:
                print(f"    ✗ Failed", file=sys.stderr)

        scene_images[str(i)] = images

    return scene_images


# ── CLI ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ComfyUI utilities")
    sub = parser.add_subparsers(dest="command")

    # Status command
    sub.add_parser("status", help="Check ComfyUI status")

    # Generate command
    gen = sub.add_parser("generate", help="Generate a single image")
    gen.add_argument("prompt", help="Text prompt for image generation")
    gen.add_argument("-o", "--output", default="fantasee_test", help="Output filename prefix")
    gen.add_argument("--checkpoint", default="fantasy", choices=list(CHECKPOINTS.keys()))
    gen.add_argument("--seed", type=int, help="Random seed")
    gen.add_argument("--width", type=int, default=896)
    gen.add_argument("--height", type=int, default=512)
    gen.add_argument("--timeout", type=int, default=180)

    # List checkpoints
    sub.add_parser("checkpoints", help="List available checkpoints")

    args = parser.parse_args()

    if args.command == "status":
        s = is_running()
        print(f"Running: {s['running']}")
        print(f"URL: {s['url']}")
        if s["running"]:
            print(f"Queue: {s['queue_running']} running, {s['queue_pending']} pending")
            if s["system_stats"]:
                print(f"System: {json.dumps(s['system_stats'], indent=2)}")

    elif args.command == "checkpoints":
        for name, ckpt in CHECKPOINTS.items():
            print(f"  {name}: {ckpt}")

    elif args.command == "generate":
        filename = generate_image(
            prompt=args.prompt,
            output_prefix=args.output,
            seed=args.seed,
            checkpoint=args.checkpoint,
            width=args.width,
            height=args.height,
            timeout=args.timeout,
        )
        if filename:
            print(f"✓ Generated: {filename}")
        else:
            print("✗ Generation failed", file=sys.stderr)
            sys.exit(1)

    else:
        parser.print_help()
