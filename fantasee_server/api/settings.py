"""Settings API — persistent configuration for Fantasee.

Stores runtime settings in ``fantasee_settings.json`` at the project root.
The frontend reads/writes through ``GET/PUT /api/settings``.

Settings are applied at read time — the API never hot-reloads env vars,
but the next story generation will pick up changed values.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from fantasee_server.security import validate_provider_url, validate_provider_urls

router = APIRouter(prefix="/api/settings", tags=["settings"])

SETTINGS_FILE = Path(__file__).parent.parent.parent / "fantasee_settings.json"

# ── Known tone presets (from tts_utils.py TONE_MODIFIERS) ─────────
# These map to specific narration tone modifiers. Freeform strings
# are also accepted by the generation pipeline.
KNOWN_TONES = ["dramatic", "normal", "dark", "whimsical", "epic", "mysterious"]

# ── Suggested art styles (freeform text, not exhaustive) ──────────
SUGGESTED_STYLES = [
    "fantasy painterly",
    "cyberpunk neon",
    "anime manga",
    "dark gothic",
    "watercolor storybook",
    "cinematic realism",
    "pixel art retro",
    "steampunk",
    "ink wash",
    "noir chiaroscuro",
    "sci-fi concept",
    "children's illustration",
]


# ── Defaults ──────────────────────────────────────────────────────

DEFAULTS: dict = {
    # ComfyUI
    "comfyui_urls": "http://127.0.0.1:8188",
    "comfyui_auto_spawn": True,

    # LLM (Xiaomi MiMo)
    "llm_base_url": "https://token-plan-sgp.xiaomimimo.com/v1",
    "llm_api_key": "",
    "llm_model": "mimo-v2.5-pro",

    # TTS — uses the same Xiaomi MiMo TTS endpoint (mimo-v2.5-tts models)
    # Voice presets: Dean, Milo, Mia, Chloe. Most voice aliases map to Mia.
    "tts_voice_preset": "Dean",
    "tts_speed": 1.3,

    # Plex
    "plex_destination": r"D:\Downloads\Plex",

    # Whisper
    "whisper_model_size": "base",

    # Generation defaults
    "default_scenes": 5,
    "default_images_per_scene": 5,
    "default_style": "fantasy painterly",
    "default_tone": "dramatic",
    "narration_style": "",
}


# ── Model ─────────────────────────────────────────────────────────

class Settings(BaseModel):
    # ComfyUI
    comfyui_urls: str = Field(default="http://127.0.0.1:8188", description="Comma-separated ComfyUI worker URLs")
    comfyui_auto_spawn: bool = Field(default=True, description="Auto-spawn ComfyUI worker on startup")

    # LLM
    llm_base_url: str = Field(default="https://token-plan-sgp.xiaomimimo.com/v1", description="LLM API base URL")
    llm_api_key: str = Field(default="", description="LLM API key (stored locally, never sent to browser)")
    llm_model: str = Field(default="mimo-v2.5-pro", description="LLM model name")

    # TTS
    tts_voice_preset: str = Field(default="Dean", description="Default TTS voice preset (Dean, Milo, Mia, Chloe)")
    tts_speed: float = Field(default=1.3, ge=0.5, le=3.0, description="TTS playback speed (0.5-3.0)")

    # Plex
    plex_destination: str = Field(default=r"D:\Downloads\Plex", description="Plex export destination directory")

    # Whisper
    whisper_model_size: str = Field(default="base", description="Whisper model size (tiny/base/small/medium/large)")

    # Generation defaults
    default_scenes: int = Field(default=5, ge=1, le=50)
    default_images_per_scene: int = Field(default=5, ge=1, le=10)
    default_style: str = Field(default="fantasy painterly")
    default_tone: str = Field(default="dramatic")
    narration_style: str = Field(default="", description="Narration style name (maps to skills/<name>-style-prompt.md)")


# ── Persistence ───────────────────────────────────────────────────

def _load_settings() -> dict:
    """Load settings from disk, falling back to defaults."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            merged = {**DEFAULTS, **saved}
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULTS)


def _save_settings(data: dict) -> None:
    """Atomically write settings to disk."""
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


def apply_settings_to_env(settings: dict) -> None:
    """Push settings into environment variables so existing code picks them up."""
    comfyui_urls = validate_provider_urls(
        settings.get("comfyui_urls", DEFAULTS["comfyui_urls"]),
        resolve_dns=False,
    )
    llm_base_url = validate_provider_url(
        settings.get("llm_base_url", DEFAULTS["llm_base_url"]),
        kind="llm",
        resolve_dns=False,
    )
    os.environ["COMFYUI_URLS"] = comfyui_urls
    os.environ["FANTASEE_AUTO_SPAWN_CPU"] = "0" if not settings.get("comfyui_auto_spawn", True) else "1"
    os.environ["XIAOMI_BASE_URL"] = llm_base_url
    os.environ["XIAOMI_API_KEY"] = settings.get("llm_api_key", DEFAULTS["llm_api_key"])
    os.environ["FANTASEE_PLEX_DEST"] = settings.get("plex_destination", DEFAULTS["plex_destination"])
    os.environ["FANTASEE_TTS_SPEED"] = str(settings.get("tts_speed", DEFAULTS["tts_speed"]))
    os.environ["FANTASEE_WHISPER_MODEL"] = settings.get("whisper_model_size", DEFAULTS["whisper_model_size"])


def _mask_settings(data: dict) -> dict:
    """Return settings safe for a browser or operator response."""
    masked = dict(data)
    for key in ("llm_api_key", "tts_api_key"):
        if masked.get(key):
            val = str(masked[key])
            masked[key] = f"{val[:4]}...{val[-4:]}" if len(val) > 8 else "****"
    return masked


# ── Apply on import ───────────────────────────────────────────────
apply_settings_to_env(_load_settings())


# ── API Endpoints ─────────────────────────────────────────────────

@router.get("")
def get_settings():
    """Return current settings. API keys are masked for the browser."""
    masked = _mask_settings(_load_settings())
    # Include known presets for UI dropdowns
    masked["_known_tones"] = KNOWN_TONES
    masked["_suggested_styles"] = SUGGESTED_STYLES
    return masked


@router.get("/raw")
def get_settings_raw():
    """Compatibility endpoint that never returns raw credentials."""
    return _mask_settings(_load_settings())


@router.put("")
def update_settings(body: Settings):
    """Update settings. Saves to disk and pushes into env vars."""
    data = body.model_dump()

    try:
        data["comfyui_urls"] = validate_provider_urls(data["comfyui_urls"])
        data["llm_base_url"] = validate_provider_url(data["llm_base_url"], kind="llm")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Don't overwrite keys with masked values
    current = _load_settings()
    for key in ("llm_api_key",):
        val = data.get(key, "")
        if val and ("..." in val or "••••" in val):
            data[key] = current.get(key, "")
        elif not val:
            data[key] = current.get(key, "")

    _save_settings(data)
    apply_settings_to_env(data)

    return {"ok": True, "settings": _mask_settings(data)}


@router.get("/narration-styles")
def list_narration_styles():
    """List available narration style prompts from skills/."""
    skills_dir = Path(__file__).parent.parent.parent / "skills"
    styles = []
    if skills_dir.exists():
        for f in sorted(skills_dir.glob("*-style-prompt.md")):
            name = f.name.replace("-style-prompt.md", "")
            # Read first non-empty, non-heading line as description
            desc = ""
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        desc = line[:120]
                        break
            except (OSError, UnicodeError):
                pass
            styles.append({"name": name, "description": desc})
    # Always include the default (Finn style from style.md)
    default_desc = ""
    default_path = skills_dir / "style.md"
    if default_path.exists():
        try:
            for line in default_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    default_desc = line[:120]
                    break
        except (OSError, UnicodeError):
            pass
    styles.insert(0, {"name": "finn", "description": default_desc or "Default literary narration style"})
    return {"styles": styles}


@router.get("/llm-models")
def list_llm_models():
    """Fetch available models from the configured LLM endpoint.

    Returns the model list so the frontend can populate a dropdown.
    The endpoint reads the current XIAOMI_BASE_URL and XIAOMI_API_KEY
    from the environment (which were pushed from settings on startup).
    """
    import requests as req
    base_url = os.environ.get("XIAOMI_BASE_URL", DEFAULTS["llm_base_url"])
    api_key = os.environ.get("XIAOMI_API_KEY", "")

    if not api_key:
        # Try loading from saved settings as fallback
        settings = _load_settings()
        api_key = settings.get("llm_api_key", "")

    try:
        base_url = validate_provider_url(base_url, kind="llm")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r = req.get(
            f"{base_url}/models",
            headers=headers,
            timeout=10,
            allow_redirects=False,
        )
        if r.status_code == 200:
            data = r.json()
            # Handle both { data: [...] } and [...] response formats
            models = data.get("data", data) if isinstance(data, dict) else data
            ids = [m["id"] for m in models if isinstance(m, dict) and m.get("id")]
            return {"ok": True, "models": ids}
        else:
            return {"ok": False, "error": f"HTTP {r.status_code}", "models": []}
    except Exception as e:
        return {"ok": False, "error": str(e), "models": []}


@router.post("/test-connection")
def test_connection(body: dict):
    """Test connectivity to configured services."""
    import shutil
    import subprocess
    import requests as req
    results = {}

    # ── ComfyUI ───────────────────────────────────────────────
    urls = body.get("comfyui_urls", DEFAULTS["comfyui_urls"]).split(",")
    comfyui_results = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            url = validate_provider_url(url, kind="comfyui")
            r = req.get(f"{url}/system_stats", timeout=3, allow_redirects=False)
            stats = r.json() if r.status_code == 200 else {}
            comfyui_results.append({
                "url": url,
                "ok": r.status_code == 200,
                "status": r.status_code,
                "version": stats.get("system", {}).get("comfyui_version", ""),
            })
        except Exception as e:
            comfyui_results.append({"url": url, "ok": False, "error": str(e)})
    results["comfyui"] = comfyui_results

    # ── LLM ──────────────────────────────────────────────────
    llm_url = body.get("llm_base_url", DEFAULTS["llm_base_url"])
    llm_key = body.get("llm_api_key", "") or _load_settings().get("llm_api_key", "")
    model_list = []
    try:
        llm_url = validate_provider_url(llm_url, kind="llm")
        headers = {"Authorization": f"Bearer {llm_key}"} if llm_key else {}
        r = req.get(
            f"{llm_url}/models",
            headers=headers,
            timeout=10,
            allow_redirects=False,
        )
        if r.status_code == 200:
            data = r.json()
            models = data.get("data", data) if isinstance(data, dict) else data
            model_list = [m["id"] for m in models if isinstance(m, dict) and m.get("id")]
        results["llm"] = {"ok": r.status_code == 200, "status": r.status_code, "models": model_list}
    except Exception as e:
        results["llm"] = {"ok": False, "error": str(e), "models": []}

    # ── FFmpeg ────────────────────────────────────────────────
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        try:
            out = subprocess.run(
                ["ffmpeg", "-version"], capture_output=True, text=True, timeout=5
            )
            # Parse version from first line: "ffmpeg version X.Y.Z-..."
            first_line = out.stdout.splitlines()[0] if out.stdout else ""
            ver = first_line.split("version ")[1].split(" ")[0] if "version " in first_line else "unknown"

            # Check critical codecs for Plex export
            codecs_out = subprocess.run(
                ["ffmpeg", "-codecs"], capture_output=True, text=True, timeout=5
            )
            codec_text = codecs_out.stdout
            has_h264 = "libx264" in codec_text
            has_hevc = "libx265" in codec_text
            has_mp3 = "libmp3lame" in codec_text
            has_aac = "aac " in codec_text

            results["ffmpeg"] = {
                "ok": True,
                "path": ffmpeg_path,
                "version": ver,
                "codecs": {
                    "h264": has_h264,
                    "hevc": has_hevc,
                    "mp3": has_mp3,
                    "aac": has_aac,
                }
            }
        except Exception as e:
            results["ffmpeg"] = {"ok": False, "path": ffmpeg_path, "error": str(e)}
    else:
        results["ffmpeg"] = {"ok": False, "error": "ffmpeg not found in PATH"}

    # ── Plex destination ─────────────────────────────────────
    plex_dest = body.get("plex_destination", DEFAULTS["plex_destination"])
    plex_path = Path(plex_dest)
    results["plex"] = {
        "ok": plex_path.exists(),
        "path": str(plex_path),
        "exists": plex_path.exists(),
        "writable": os.access(str(plex_path), os.W_OK) if plex_path.exists() else False,
    }

    return results
