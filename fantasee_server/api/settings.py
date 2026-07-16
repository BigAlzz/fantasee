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

router = APIRouter(prefix="/api/settings", tags=["settings"])

SETTINGS_FILE = Path(__file__).parent.parent.parent / "fantasee_settings.json"

# ── Defaults ──────────────────────────────────────────────────────

DEFAULTS: dict = {
    # ComfyUI
    "comfyui_urls": "http://127.0.0.1:8188",
    "comfyui_auto_spawn": True,

    # LLM (Xiaomi MiMo)
    "llm_base_url": "https://token-plan-sgp.xiaomimimo.com/v1",
    "llm_api_key": "",
    "llm_model": "mimo-v2.5-pro",

    # TTS
    "tts_base_url": "https://token-plan-sgp.xiaomimimo.com/v1",
    "tts_api_key": "",
    "tts_voice_preset": "Dean",

    # Plex
    "plex_destination": r"D:\Downloads\Plex",

    # Whisper
    "whisper_model_size": "base",

    # Generation defaults
    "default_scenes": 5,
    "default_images_per_scene": 5,
    "default_style": "fantasy painterly",
    "default_tone": "dramatic",
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
    tts_base_url: str = Field(default="https://token-plan-sgp.xiaomimimo.com/v1", description="TTS API base URL")
    tts_api_key: str = Field(default="", description="TTS API key")
    tts_voice_preset: str = Field(default="Dean", description="Default TTS voice preset")

    # Plex
    plex_destination: str = Field(default=r"D:\Downloads\Plex", description="Plex export destination directory")

    # Whisper
    whisper_model_size: str = Field(default="base", description="Whisper model size (tiny/base/small/medium/large)")

    # Generation defaults
    default_scenes: int = Field(default=5, ge=1, le=50)
    default_images_per_scene: int = Field(default=5, ge=1, le=10)
    default_style: str = Field(default="fantasy painterly")
    default_tone: str = Field(default="dramatic")


# ── Persistence ───────────────────────────────────────────────────

def _load_settings() -> dict:
    """Load settings from disk, falling back to defaults."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            # Merge with defaults so new fields are always present
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
    """Push settings into environment variables so existing code picks them up.

    This is called after loading from disk and after every PUT, so the
    rest of the codebase (comfyui_utils, generate_story.py, tts_utils,
    critic.py, plex_export.py) sees the updated values via os.environ.
    """
    os.environ["COMFYUI_URLS"] = settings.get("comfyui_urls", DEFAULTS["comfyui_urls"])
    os.environ["FANTASEE_AUTO_SPAWN_CPU"] = "0" if settings.get("comfyui_auto_spawn") else "1"
    os.environ["XIAOMI_BASE_URL"] = settings.get("llm_base_url", DEFAULTS["llm_base_url"])
    os.environ["XIAOMI_API_KEY"] = settings.get("llm_api_key", DEFAULTS["llm_api_key"])
    os.environ["FANTASEE_PLEX_DEST"] = settings.get("plex_destination", DEFAULTS["plex_destination"])

    # TTS uses the same Xiaomi endpoint by default
    if settings.get("tts_base_url"):
        os.environ["XIAOMI_BASE_URL"] = settings["tts_base_url"]
    if settings.get("tts_api_key"):
        os.environ["XIAOMI_API_KEY"] = settings["tts_api_key"]


# ── Apply on import ───────────────────────────────────────────────
apply_settings_to_env(_load_settings())


# ── API Endpoints ─────────────────────────────────────────────────

@router.get("")
def get_settings():
    """Return current settings. API keys are masked for the browser."""
    data = _load_settings()
    # Mask keys so the frontend never sees the real value
    masked = dict(data)
    for key in ("llm_api_key", "tts_api_key"):
        if masked.get(key):
            val = masked[key]
            masked[key] = f"{val[:4]}...{val[-4:]}" if len(val) > 8 else "••••"
    return masked


@router.get("/raw")
def get_settings_raw():
    """Return unmasked settings (internal use only — not exposed to browser)."""
    return _load_settings()


@router.put("")
def update_settings(body: Settings):
    """Update settings. Saves to disk and pushes into env vars."""
    data = body.model_dump()

    # Don't overwrite keys with masked values
    current = _load_settings()
    for key in ("llm_api_key", "tts_api_key"):
        val = data.get(key, "")
        if val and ("..." in val or val == "••••"):
            data[key] = current.get(key, "")
        elif not val:
            data[key] = current.get(key, "")

    _save_settings(data)
    apply_settings_to_env(data)

    # Return masked version
    masked = dict(data)
    for key in ("llm_api_key", "tts_api_key"):
        if masked.get(key):
            val = masked[key]
            masked[key] = f"{val[:4]}...{val[-4:]}" if len(val) > 8 else "••••"
    return {"ok": True, "settings": masked}


@router.post("/test-connection")
def test_connection(body: dict):
    """Test connectivity to configured services."""
    import requests as req
    results = {}

    # Test ComfyUI
    urls = body.get("comfyui_urls", DEFAULTS["comfyui_urls"]).split(",")
    comfyui_results = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            r = req.get(f"{url}/system_stats", timeout=3)
            comfyui_results.append({"url": url, "ok": r.status_code == 200, "status": r.status_code})
        except Exception as e:
            comfyui_results.append({"url": url, "ok": False, "error": str(e)})
    results["comfyui"] = comfyui_results

    # Test LLM
    llm_url = body.get("llm_base_url", DEFAULTS["llm_base_url"])
    llm_key = body.get("llm_api_key", "") or _load_settings().get("llm_api_key", "")
    try:
        r = req.get(f"{llm_url}/models", headers={"Authorization": f"Bearer {llm_key}"}, timeout=5)
        results["llm"] = {"ok": r.status_code == 200, "status": r.status_code}
    except Exception as e:
        results["llm"] = {"ok": False, "error": str(e)}

    # Test Plex destination
    plex_dest = body.get("plex_destination", DEFAULTS["plex_destination"])
    plex_path = Path(plex_dest)
    results["plex"] = {"ok": plex_path.exists(), "path": str(plex_path), "exists": plex_path.exists()}

    return results
