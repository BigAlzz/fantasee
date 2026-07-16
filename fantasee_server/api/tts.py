"""TTS (text-to-speech) endpoints.

Thin wrappers over ``tts_utils.generate_tts``:

* ``/api/tts/presets`` — list the available voice presets
  (read from ``tts_utils.XIAOMI_VOICES``).
* ``/api/tts/generate`` — synthesize an arbitrary snippet of text
  to a WAV under ``stories/`` and return its duration + URL.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException

from fantasee_server.models import TTSRequest
from fantasee_server.paths import GEN_OUTPUTS, path_under


router = APIRouter(tags=["tts"])


@router.get("/api/tts/presets")
def tts_presets():
    """List available TTS voice presets."""
    try:
        from tts_utils import XIAOMI_VOICES
        return {"voices": XIAOMI_VOICES}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"presets": {}, "error": str(e)}


@router.post("/api/tts/generate")
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
