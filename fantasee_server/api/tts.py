"""TTS (text-to-speech) endpoints.

Thin wrappers over ``tts_utils.generate_tts``:

* ``/api/tts/presets`` — list the available voice presets
  (read from ``tts_utils.XIAOMI_VOICES``).
* ``/api/tts/generate`` — synthesize an arbitrary snippet of text
  to a WAV under ``stories/`` and return its duration + URL.
"""

from __future__ import annotations

import uuid
import base64
import re
from typing import Optional

from fastapi import APIRouter, HTTPException

from fantasee_server.models import TTSRequest
from fantasee_server.paths import GEN_OUTPUTS, path_under


router = APIRouter(tags=["tts"])

_VOICE_SAMPLE_RE = re.compile(r"^data:(audio/(?:mpeg|mp3|wav));base64,([A-Za-z0-9+/=]+)$")
_MAX_VOICE_SAMPLE_BASE64_BYTES = 10 * 1024 * 1024


def _validate_voice_sample(sample: Optional[str]) -> Optional[str]:
    """Validate the local clone sample before sending it to MiMo."""
    if not sample:
        return None
    match = _VOICE_SAMPLE_RE.fullmatch(sample)
    if not match:
        raise HTTPException(status_code=400, detail="Voice clone samples must be MP3 or WAV data URIs")
    encoded = match.group(2)
    if len(encoded) > _MAX_VOICE_SAMPLE_BASE64_BYTES:
        raise HTTPException(status_code=400, detail="Voice clone sample exceeds MiMo's 10 MB encoded limit")
    try:
        base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Voice clone sample is not valid base64") from None
    return sample


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

    if req.model == "clone" and not req.voice_sample:
        raise HTTPException(status_code=400, detail="Voice clone mode requires an MP3 or WAV sample")
    if req.stream and req.model != "preset":
        raise HTTPException(status_code=400, detail="Low-latency streaming is only available for built-in MiMo voices")
    voice_sample = _validate_voice_sample(req.voice_sample)
    output_name = req.output_name or f"tts_{uuid.uuid4().hex[:8]}.wav"
    output_path = str(path_under(GEN_OUTPUTS, output_name))

    ok = generate_tts(
        req.text,
        output_path,
        voice_preset=req.voice_preset,
        style=req.style or req.voice_description,
        model=req.model,
        voice_sample=voice_sample,
        optimize_text_preview=req.optimize_text_preview,
        stream=req.stream,
        tone=req.tone,
        speed=req.speed,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="TTS generation failed")

    duration = get_audio_duration(output_path)
    return {
        "filename": output_name,
        "duration": duration,
        "url": f"/generated-audio/{output_name}",
    }
