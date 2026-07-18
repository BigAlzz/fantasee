"""
MiMo TTS — Xiaomi MiMo-V2.5-TTS integration for Fantasee.

Uses the [Character / Scene / Guidance] director-mode structure (per the
official v2.5 TTS docs) to give each voice a rich, consistent identity
that survives across many scenes. Per-tone modifiers overlay the base
voice style so a "dark" Mia sounds different from a "normal" Mia.

Key references from the docs that drive the design:
- The `role: user` message is the style/instruction prompt (optional for
  built-in voices but powerful when present).
- The `role: assistant` message is the text to speak.
- Built-in voice list: Mia, Chloe, Milo, Dean (English); 冰糖/茉莉/苏打/白桦 (Chinese).
- Director Mode uses three dimensions: [Character], [Scene], [Guidance].
- Multi-granularity control: paragraph → sentence → word → character.
- Inline audio tags in the text (e.g. (pauses), (whispers)) for fine-grained control.
"""

import base64
import io
import json
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Optional

import requests

from fantasee_server.security import validate_provider_url

# ── Config ──────────────────────────────────────────────────────────────
TTS_API_URL = "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions"
DEFAULT_TTS_SPEED = float(os.environ.get("FANTASEE_TTS_SPEED", "1.3"))
NARRATION_LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11:linear=false"


def configured_tts_speed() -> float:
    """Read the current narration speed without requiring a module reload."""
    try:
        return max(0.5, min(3.0, float(os.environ.get("FANTASEE_TTS_SPEED", DEFAULT_TTS_SPEED))))
    except (TypeError, ValueError):
        return DEFAULT_TTS_SPEED

# Xiaomi named voices (built-in, per official v2.5 TTS docs)
XIAOMI_VOICES = {
    # English voices
    "Mia":      {"id": "Mia",      "gender": "female", "language": "en"},
    "Chloe":    {"id": "Chloe",    "gender": "female", "language": "en"},
    "Milo":     {"id": "Milo",     "gender": "male",   "language": "en"},
    "Dean":     {"id": "Dean",     "gender": "male",   "language": "en"},
    # Chinese voices (per docs: 冰糖, 茉莉, 苏打, 白桦)
    "bingtang": {"id": "冰糖",      "gender": "female", "language": "zh", "aliases": ["bingtang"]},
    "moli":     {"id": "茉莉",      "gender": "female", "language": "zh", "aliases": ["moli"]},
    "soda":     {"id": "苏打",      "gender": "male",   "language": "zh", "aliases": ["soda"]},
    "birch":    {"id": "白桦",      "gender": "male",   "language": "zh", "aliases": ["birch", "baihua"]},
}

VOICE_ALIASES = {
    # Legacy aliases (back-compat)
    "af_heart": "Mia", "af_bella": "Mia", "mimo_default": "Mia", "default_en": "Mia",
    "af_nicole": "Chloe", "af_sarah": "Chloe",
    "am_adam": "Milo",
    "am_michael": "Dean",
    "dramatic_male": "Dean", "warm_male": "Milo", "british_male": "Dean",
    "warm_female": "Mia", "ethereal_female": "Chloe", "gruff_male": "Dean",
}

# TTS model variants (per docs)
TTS_MODELS = {
    "preset": "mimo-v2.5-tts",                  # built-in voices
    "design": "mimo-v2.5-tts-voicedesign",      # text-described voice
    "clone":  "mimo-v2.5-tts-voiceclone",       # audio-cloned voice
}

# ── Voice presets with director-mode style prompts ──────────────────
# Each voice has a rich [Character / Scene / Guidance] style description
# that tells the TTS model exactly how to speak. The base voice identity
# is preserved across all tones; the tone modifier overlays scene-specific
# instructions on top.

VOICE_PRESETS = {
    "Dean": {
        "name": "Dean (Deep Male Narrator)",
        "voice": "Dean",
        "gender": "male",
        "language": "en",
        "is_default": True,
        "style": (
            "[Character] A middle-aged male narrator with a deep, warm chest "
            "voice and a touch of gravel — like a seasoned storyteller by a "
            "fireside, the kind of person who has earned his calm through years "
            "of listening before he ever spoke.\n\n"
            "[Guidance] Calibrated, unhurried pacing with deliberate micro-pauses "
            "between sentences for emphasis. Chest resonance, never strained. "
            "Speak with quiet authority and old-world wisdom — the kind of voice "
            "that makes a listener lean in. Audio tags may include (soft pause) "
            "between thoughts and (gentle exhale) at natural breath points."
        ),
    },
    "Milo": {
        "name": "Milo (Warm Male)",
        "voice": "Milo",
        "gender": "male",
        "language": "en",
        "style": (
            "[Character] A young adult male with a friendly, clear, slightly "
            "bright voice — the storyteller you actually want at your table, "
            "animated and engaged, sharing a tale he genuinely loves.\n\n"
            "[Guidance] Natural conversational pace, friendly and warm with a "
            "light smile audible in the voice. Grounded and relatable — never "
            "theatrical. Use (laughs softly) for wry moments and (slight pause) "
            "before good punchlines."
        ),
    },
    "Mia": {
        "name": "Mia (Warm Female)",
        "voice": "Mia",
        "gender": "female",
        "language": "en",
        "style": (
            "[Character] A young adult female narrator with a warm, clear voice "
            "and a hint of brightness — like a thoughtful friend sharing a "
            "meaningful story over a quiet cup of tea.\n\n"
            "[Guidance] Steady, gentle pace with a present, caring quality. "
            "Don't sound clinical — sound like someone who genuinely cares about "
            "the story. Use (soft pause) between scenes and a slightly higher "
            "energy on hopeful moments."
        ),
    },
    "Chloe": {
        "name": "Chloe (Soft Female)",
        "voice": "Chloe",
        "gender": "female",
        "language": "en",
        "style": (
            "[Character] A mature female with a soft, slightly breathy voice. "
            "Intimate and reflective — like a quiet conversation late at night, "
            "candlelight optional.\n\n"
            "[Guidance] Slow, measured pace. Lower energy but high warmth. "
            "Long pauses between thoughts, as if considering each one carefully. "
            "Use (sighs gently) sparingly for emotional beats. The voice should "
            "feel close — like the listener is the only person in the room."
        ),
    },
}

# Per-tone style modifiers — layered on top of the voice's base style.
# Each is a snippet that emphasizes different aspects of the delivery.
# Kept short so we don't blow past the model's context window when stacked.
TONE_MODIFIERS = {
    "normal":      "\n\n[Tone] Neutral and clear — the baseline.",
    "dramatic":    "\n\n[Tone] Reserve a touch of dramatic weight for key moments. Slight slowdowns before revelations, a touch more intensity on action verbs. Never stage-act; never oversell.",
    "dark":         "\n\n[Tone] Lower the pitch slightly, pace more deliberately. Shadowed tone with longer pauses before ominous moments. A faint dread in the undertone — never melodramatic.",
    "epic":         "\n\n[Tone] Broader, more resonant delivery. Pauses for gravitas on pivotal moments. The voice should feel larger than the room.",
    "heroic":      "\n\n[Tone] Rising energy at moments of courage and resolve. Steadier, more committed pace. A quiet strength underneath.",
    "mysterious":  "\n\n[Tone] Subtly lowered volume, deliberate pace. Slight trailing off on sentences to leave questions hanging. A sense of secrets half-revealed.",
    "lighthearted": "\n\n[Tone] Light, playful, a smile in the voice. Faster pace allowed but not rushed. (chuckles) at wry moments.",
    "comedic":     "\n\n[Tone] Wry, energetic, a real sense of fun. Punchlines should land — use (slight pause) before the kicker.",
    "romantic":    "\n\n[Tone] Warm and soft, with breathy intimacy. Slow down during tender moments. Let silences breathe.",
    "melancholic": "\n\n[Tone] Slower, lower energy, with a wistful quality. (sighs) at the end of long sentences. Don't wallow — stay restrained.",
    "hopeful":     "\n\n[Tone] Lift gently toward the end of scenes. A touch of brightness in the voice. (slight smile) on the closing line.",
    "suspenseful": "\n\n[Tone] Taut and measured. Hold tension — don't resolve it prematurely. Use (beat) before the twist. Lower the volume on quiet moments.",
    "whimsical":   "\n\n[Tone] Playful cadence, a sing-song quality, light and airy. (giggles softly) at absurd moments. Never cynical.",
    "epic-fantasy": "\n\n[Tone] Grandeur with restraint. Roll the long vowels of ancient names with reverence. A bardic quality, as if the words themselves matter.",
    "noir":        "\n\n[Tone] Tired, world-weary, sardonic. Short clipped sentences. (cigarette exhale) between paragraphs.",
    "lyrical":     "\n\n[Tone] Poetic cadence with rhythmic pauses. Let the imagery breathe. A musical, almost-sung quality on descriptive passages.",
    "gritty":      "\n\n[Tone] Raw, unpolished, in-the-mud. No flourishes. Short punchy sentences. (clenched jaw) at hard moments.",
    "manhwa":      "\n\n[Tone] Korean webtoon energy — punchy present-tense narration that hits hard on action verbs and lands revelations with weight. Rapid bursts of kinetic motion broken by quiet, gut-punch character beats. (sharp inhale) before twist reveals. Speed up — short short short — for action sequences, then full stop. Drop register into something almost spoken-word on the slower internal-monologue beats. Confidence that can't quite believe what it's watching. Let tension build through pacing alone. Don't explain; show, then cut. (slight smirk) at the cocky character moments. (quiet exhale) on the gut-punch losses. The voice should feel like a friend who can't stop reading the next panel.",
    "tense":       "\n\n[Tone] Taut, alert, slightly elevated. Short sentences. Hold tension. Don't over-explain.",
    "emotional":   "\n\n[Tone] Emotionally resonant with controlled warmth. Allow the voice to thicken slightly on emotional beats. (pause) before vulnerable moments.",
    "whisper":     "\n\n[Tone] Intimate and soft but still clearly audible. (whispers) through intimate passages. (normal voice) returns for narration breaks.",
    "urgent":      "\n\n[Tone] Purposeful, focused. Brief moments of intensity. (sharp inhale) at key turns. Never rushed — controlled urgency.",
    "excited":     "\n\n[Tone] Gently energized, warm enthusiasm, not loud. Lifted pitch on the closing line of a beat. (laughs) at happy moments.",
    "calm":        "\n\n[Tone] Soft, unhurried, inviting. The voice should feel like a steady hand on a shoulder. (gentle exhale) at natural breath points.",
}

# Current house style: smooth audiobook voice acting, not trailer narration.
# These overrides intentionally keep some performance/emotion while removing
# the exaggerated pauses, gasps, and melodramatic spikes that made subtitles
# drift and the player feel over-acted.
VOICE_PRESETS["Dean"]["style"] = (
    "[Character] A middle-aged male narrator with a deep, warm chest voice "
    "and a light touch of gravel. He sounds grounded, intelligent, and close "
    "to the listener, like a skilled audiobook actor rather than a movie "
    "trailer announcer.\n\n"
    "[Guidance] Smooth, natural voice acting with clear phrasing and restrained "
    "emotion. Let character beats color the line, but keep the performance "
    "conversational and believable. Avoid booming, whispering, gasping, "
    "theatrical pauses, exaggerated breaths, and over-sold dramatic reveals."
)
TONE_MODIFIERS.update({
    "normal": "\n\n[Tone] Clear, smooth, lightly expressive narration.",
    "dramatic": "\n\n[Tone] Light dramatic shading only. Keep it believable and conversational; never stage-act, boom, whisper, or oversell.",
    "dark": "\n\n[Tone] Serious and shadowed, but calm. No horror-trailer intensity, long ominous pauses, or melodrama.",
    "epic": "\n\n[Tone] Measured and spacious with restrained gravitas. Do not make the voice larger than life.",
    "manhwa": "\n\n[Tone] Modern serialized adventure narration with momentum and subtle attitude. Keep it controlled, clear, and human. No sharp inhales, smirks, huge trailer pauses, shouted action beats, or exaggerated emotional drops.",
    "urgent": "\n\n[Tone] Focused and purposeful with mild urgency. Stay smooth and controlled; do not rush or gasp.",
    "emotional": "\n\n[Tone] Emotionally present but restrained. Let warmth and vulnerability come through naturally, without breaking into melodrama.",
})

# Map of which built-in voice to use per language (when the LLM picks a language)
VOICE_FOR_LANGUAGE = {
    "en": "Dean",   # default English narrator
    "zh": "bingtang",
}

DEFAULT_VOICE = "Dean"

# Legacy single-line style descriptions (back-compat). New code should
# use VOICE_PRESETS + TONE_MODIFIERS for richer director-mode prompts.
STYLE_MAP = {
    "normal":    "calm, steady, conversational narration — like a smooth storyteller sharing a tale with friends",
    "dramatic":  "reserved emphasis on key moments — like a calm narrator drawing you in, not stage-acting",
    "tense":     "slightly tense but controlled, never frantic",
    "emotional": "emotionally resonant with controlled warmth and restraint",
    "whisper":   "intimate and soft, but still clearly audible",
    "urgent":    "purposeful and steady, with brief moments of focus — never rushed",
    "excited":   "gently energized — warm enthusiasm, not loud",
    "calm":      "soft, calm, unhurried, and inviting",
}

def get_style_for(voice: str, tone: str = "normal") -> str:
    """Combine a voice's base director-mode prompt with a tone modifier.

    Returns the full instruction string to send in `role: user`.
    Falls back to a generic warm-narrator prompt if voice/tone is unknown.
    """
    preset = VOICE_PRESETS.get(voice, VOICE_PRESETS.get("Dean"))
    base = preset.get("style", "") if preset else ""
    modifier = TONE_MODIFIERS.get(tone, TONE_MODIFIERS.get("normal", ""))
    return (base + modifier).strip()


def _get_api_key() -> str:
    """Resolve the Xiaomi API key from environment or .env file."""
    key = os.environ.get("XIAOMI_API_KEY", "")
    if key and not key.startswith("***"):
        return key

    env_paths = [
        Path("E:/hermes/.env"),
        Path.home() / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("XIAOMI_API_KEY=") and not stripped.startswith("#"):
                        val = stripped.split("=", 1)[1]
                        if val and not val.startswith("***"):
                            return val
    return ""


def _get_base_url() -> str:
    """Resolve the Xiaomi API base URL."""
    return os.environ.get(
        "XIAOMI_BASE_URL",
        "https://token-plan-sgp.xiaomimimo.com/v1",
    )


def normalize_voice(voice: str) -> str:
    """Map voice aliases to Xiaomi preset names."""
    raw = str(voice or "").strip()
    if not raw:
        return DEFAULT_VOICE
    # Direct match
    if raw in XIAOMI_VOICES:
        return raw
    # Alias match
    return VOICE_ALIASES.get(raw, raw)


def synthesize(
    text: str,
    voice: str = DEFAULT_VOICE,
    style: str = "",
    *,
    model: str = "preset",
    timeout: int = 90,
    tone: str = "",
    voice_sample: Optional[str] = None,
    optimize_text_preview: bool = True,
    stream: bool = False,
) -> bytes | None:
    """Synthesize speech using Xiaomi MiMo TTS.

    Per the official v2.5 docs:
    - Built-in voices (preset model): use `audio.voice` to pick a name
      (Mia/Chloe/Milo/Dean for English, 冰糖/茉莉/苏打/白桦 for Chinese).
      The `role: user` message is an optional but powerful style/instruction
      prompt that controls delivery.
    - Voice design model: the `role: user` message IS the voice
      description; `audio.voice` is not used. Use `optimize_text_preview`
      to let the model polish the assistant text.
    - Inline audio tags in the assistant text (e.g. (pauses), (whispers))
      give fine-grained control over the spoken performance.

    Args:
        text: The text to be spoken (placed in `role: assistant`).
        voice: Built-in voice id (Mia/Chloe/Milo/Dean/冰糖/...).
        style: Natural-language style/voice description (placed in `role: user`).
        model: "preset" for built-in voices, "design" for voice design, or
            "clone" for an audio sample clone.
        timeout: Request timeout in seconds.
        tone: Optional tone name (e.g. "dark", "epic", "epic-fantasy"). When
            provided, the matching TONE_MODIFIERS snippet is appended to
            `style` before sending. If `style` is already non-empty, the
            tone is layered on top of it.

    Returns:
        WAV bytes or None on failure.
    """
    api_key = _get_api_key()
    if not api_key:
        print("[tts_utils] ERROR: XIAOMI_API_KEY not found", file=sys.stderr)
        return None

    try:
        base_url = validate_provider_url(_get_base_url(), kind="llm")
    except ValueError as exc:
        print(f"[tts_utils] ERROR: unsafe provider URL: {exc}", file=sys.stderr)
        return None
    voice = normalize_voice(voice)

    # Determine which provider voice contract applies.
    voice_design = model == "design" or "voicedesign" in model
    voice_clone = model == "clone" or "voiceclone" in model
    if voice_clone and not voice_sample:
        print("[tts_utils] ERROR: clone mode requires a voice sample", file=sys.stderr)
        return None
    if stream and model != "preset":
        print("[tts_utils] ERROR: streaming is only supported for preset voices", file=sys.stderr)
        return None

    # Compose final style: if a tone is given, layer its modifier on top
    # of any explicit style the caller passed.
    final_style = (style or "").strip()
    if tone:
        modifier = TONE_MODIFIERS.get(tone)
        if modifier:
            final_style = (final_style + "\n\n" + modifier).strip() if final_style else modifier.strip()

    # If we still have no style, build one from the voice preset so the
    # model always has a director-mode prompt to work with.
    if not final_style and not voice_design:
        final_style = get_style_for(voice, tone="normal")

    # Build messages
    messages = []
    if voice_design:
        messages.append({"role": "user", "content": final_style or "Use a warm, cinematic narrator voice."})
        messages.append({"role": "assistant", "content": text})
    elif voice_clone:
        messages.append({"role": "user", "content": final_style})
        messages.append({"role": "assistant", "content": text})
    else:
        if final_style:
            messages.append({"role": "user", "content": final_style})
        messages.append({"role": "assistant", "content": text})

    # Build payload
    payload = {
        "model": TTS_MODELS.get(model, model),
        "messages": messages,
    }
    if voice_design:
        payload["audio"] = {"format": "pcm16" if stream else "wav", "optimize_text_preview": optimize_text_preview}
    elif voice_clone:
        payload["audio"] = {"format": "wav", "voice": voice_sample}
    else:
        payload["audio"] = {"format": "pcm16" if stream else "wav", "voice": voice}
    if stream:
        payload["stream"] = True

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Try primary endpoint, retry with alternate header on failure
    for attempt_headers in [headers, {**headers, "api-key": api_key}]:
        try:
            r = requests.post(
                f"{base_url}/chat/completions",
                headers=attempt_headers,
                json=payload,
                timeout=timeout,
                allow_redirects=False,
                stream=stream,
            )
            if r.status_code == 200:
                if stream:
                    return _decode_streaming_pcm(r)
                data = r.json()
                audio_b64 = data["choices"][0]["message"]["audio"]["data"]
                return base64.b64decode(audio_b64)
            elif r.status_code >= 500:
                continue  # Try alternate header
            else:
                # Non-5xx error — don't retry
                print(f"[tts_utils] ERROR: TTS returned {r.status_code}: {r.text[:200]}", file=sys.stderr)
                return None
        except requests.exceptions.Timeout:
            print("[tts_utils] ERROR: TTS request timed out", file=sys.stderr)
            return None
        except requests.exceptions.ConnectionError:
            continue  # Try alternate header
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            print(f"[tts_utils] ERROR: Unexpected response format: {e}", file=sys.stderr)
            return None

    print("[tts_utils] ERROR: All TTS endpoints failed", file=sys.stderr)
    return None


def _decode_streaming_pcm(response: requests.Response) -> bytes | None:
    """Collect MiMo PCM16 SSE chunks into a normal WAV for the local pipeline."""
    chunks = bytearray()
    try:
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
                audio = event.get("choices", [{}])[0].get("delta", {}).get("audio")
                if audio and audio.get("data"):
                    chunks.extend(base64.b64decode(audio["data"]))
            except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
    finally:
        response.close()
    if not chunks:
        return None
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(bytes(chunks))
    return output.getvalue()


def _atempo_filter(speed: float) -> str:
    """Build an ffmpeg atempo chain, preserving pitch while changing speed."""
    speed = max(0.5, min(float(speed or 1.0), 4.0))
    parts = []
    while speed > 2.0:
        parts.append("atempo=2.0")
        speed /= 2.0
    while speed < 0.5:
        parts.append("atempo=0.5")
        speed /= 0.5
    parts.append(f"atempo={speed:.3f}")
    return ",".join(parts)


def _write_tts_audio(audio_bytes: bytes, output_path: Path, speed: Optional[float] = None) -> bool:
    """Write synthesized audio with consistent loudness and app-wide speed."""
    speed = configured_tts_speed() if speed is None else speed
    raw_wav = output_path.with_name(output_path.stem + ".raw_tts.wav")
    sped_wav = output_path.with_name(output_path.stem + ".speed_tts.wav")
    normalized_wav = output_path.with_name(output_path.stem + ".normalized_tts.wav")
    try:
        raw_wav.write_bytes(audio_bytes)
        if abs(float(speed or 1.0) - 1.0) > 0.01:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(raw_wav),
                    "-filter:a", _atempo_filter(speed),
                    str(sped_wav),
                ],
                capture_output=True,
                timeout=60,
                check=True,
            )
            source = sped_wav
        else:
            source = raw_wav

        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(source),
                "-af", NARRATION_LOUDNORM_FILTER,
                "-ar", "48000", "-ac", "2",
                str(normalized_wav),
            ],
            capture_output=True,
            timeout=60,
            check=True,
        )
        source = normalized_wav

        if output_path.suffix.lower() == ".mp3":
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(source), "-codec:a", "libmp3lame", "-b:a", "128k", str(output_path)],
                capture_output=True,
                timeout=60,
                check=True,
            )
        else:
            output_path.write_bytes(source.read_bytes())
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[tts_utils] WARNING: ffmpeg speed processing failed ({e}); saving original audio", file=sys.stderr)
        output_path.write_bytes(audio_bytes)
        return True
    finally:
        for tmp in (raw_wav, sped_wav, normalized_wav):
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass


def generate_tts(
    text: str,
    output_path: str,
    voice: str = DEFAULT_VOICE,
    style: str = "",
    voice_preset: Optional[str] = None,
    tone: str = "",
    speed: Optional[float] = None,
    model: str = "preset",
    voice_sample: Optional[str] = None,
    optimize_text_preview: bool = True,
    stream: bool = False,
) -> bool:
    """Generate TTS audio from text.

    Args:
        text: The narration text to convert to speech.
        output_path: Path to save the output audio file (.wav or .mp3).
        voice: Voice name (Mia, Chloe, Milo, Dean, 冰糖, 茉莉, 苏打, 白桦).
        style: Voice style description (full natural language). If a key
            from the legacy STYLE_MAP is passed, it's translated to a
            director-mode prompt. If empty, the voice's preset style is
            used automatically.
        voice_preset: Legacy alias — maps to voice parameter.
        tone: Story tone (dramatic/dark/epic/mysterious/...). When set,
            TONE_MODIFIERS[tone] is appended to the style prompt so the
            delivery matches the mood.
        speed: Playback speed baked into the generated file. When omitted,
            the current FANTASEE_TTS_SPEED setting is read at call time.
        model: MiMo model mode: preset, design, or clone.
        voice_sample: MP3/WAV data URI required for clone mode.
        optimize_text_preview: Let MiMo polish preview text in design mode.
        stream: Request low-latency PCM streaming for built-in voices.

    Returns:
        True if successful, False otherwise.
    """
    # Resolve voice
    if voice_preset:
        voice = voice_preset

    # Resolve legacy STYLE_MAP keys to the modern director-mode style
    if style in STYLE_MAP:
        style = STYLE_MAP[style]

    # Use preset model for named voices. The synthesize() function will
    # combine `style` with `tone` automatically and fall back to the
    # voice's preset if both are empty.
    audio_bytes = synthesize(
        text,
        voice=voice,
        style=style,
        model=model,
        tone=tone,
        voice_sample=voice_sample,
        optimize_text_preview=optimize_text_preview,
        stream=stream,
    )
    if not audio_bytes:
        return False

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    return _write_tts_audio(audio_bytes, output_path, speed=speed)


def generate_tts_batch(
    scenes: list[dict],
    output_dir: str,
    story_id: str,
    voice: str = DEFAULT_VOICE,
    tone: str = "",
    filename_pattern: str = "tts_{story_id}_s{scene_num:02d}.wav",
) -> dict:
    """Generate TTS audio for multiple scenes.
    
    Returns:
        Dict mapping scene index (str) to filename (str) for successful generations.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scene_audios = {}
    total = len(scenes)

    for i, scene in enumerate(scenes):
        text = scene.get("narration_text") or scene.get("narration") or scene.get("narrative", "")
        if not text or len(text.strip()) < 10:
            print(f"  [SKIP] Scene {i + 1}: no narration text", file=sys.stderr)
            continue

        filename = filename_pattern.format(story_id=story_id, scene_num=i + 1)
        filepath = output_dir / filename

        # Check if already cached
        if filepath.exists() and filepath.stat().st_size > 1000:
            print(f"  [CACHED] Scene {i + 1}: {filename}", file=sys.stderr)
            scene_audios[str(i)] = filename
            continue

        print(f"  [TTS] Scene {i + 1}/{total}: {scene.get('title', f'Scene {i + 1}')}...", file=sys.stderr)
        ok = generate_tts(text, str(filepath), voice=voice, tone=tone)
        if ok:
            scene_audios[str(i)] = filename
            print(f"    ✓ Saved {filename}", file=sys.stderr)
        else:
            print(f"    ✗ Failed scene {i + 1}", file=sys.stderr)

    return scene_audios


def get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds from WAV or MP3 file.

    Uses the standard library `wave` for WAV (handles all PCM variants
    correctly) and mutagen for MP3. Falls back to ffprobe if available,
    and only as a last resort to a rough size estimate.
    """
    path = Path(audio_path)
    if not path.exists() or path.stat().st_size < 100:
        return 0.0

    ext = path.suffix.lower()

    if ext == ".wav":
        try:
            import wave as _wave
            with _wave.open(str(path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return frames / float(rate)
        except Exception:
            pass

    if ext in (".mp3", ".wav", ".m4a", ".ogg", ".flac"):
        try:
            from mutagen import File as MutagenFile
            mf = MutagenFile(str(path))
            if mf is not None and mf.info is not None and getattr(mf.info, "length", None):
                return float(mf.info.length)
        except Exception:
            pass

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
             str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass

    try:
        size = path.stat().st_size
        if ext == ".mp3":
            return max(3.0, size / 16000)
        return max(3.0, size / 32000)
    except Exception:
        return 0.0


# ── CLI ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MiMo TTS — generate narration audio")
    parser.add_argument("text", nargs="?", help="Text to convert to speech")
    parser.add_argument("-o", "--output", help="Output file path (.wav or .mp3)")
    parser.add_argument("--voice", choices=list(XIAOMI_VOICES.keys()), default=DEFAULT_VOICE,
                        help="Voice name")
    parser.add_argument("--style", help="Voice style (or key from STYLE_MAP)")
    parser.add_argument("--list-voices", action="store_true", help="List available voices")
    parser.add_argument("--list-styles", action="store_true", help="List available styles")
    args = parser.parse_args()

    if args.list_voices:
        for name, info in XIAOMI_VOICES.items():
            print(f"  {name} ({info['gender']}) — aliases: {', '.join(info.get('aliases', []))}")
        sys.exit(0)

    if args.list_styles:
        for key, desc in STYLE_MAP.items():
            print(f"  {key}: {desc}")
        sys.exit(0)

    if not args.text:
        parser.error("text argument required (or use --list-voices)")

    output = args.output or "tts_output.wav"
    style = args.style or STYLE_MAP.get("normal", "")
    ok = generate_tts(args.text, output, voice=args.voice, style=style)
    if ok:
        print(f"✓ Saved to {output}")
    else:
        print("✗ TTS generation failed", file=sys.stderr)
        sys.exit(1)
