---
name: piper-tts
description: "Configure, tune, and troubleshoot Piper TTS for narration — local neural VITS voice synthesis, optimised for narration quality on this host (Windows/MSYS)."
version: 1.0.0
author: Hermes
platforms: [windows]
---

# Piper TTS

Local neural VITS text-to-speech via the `piper-tts` Python package. Installed
in the Hermes venv and configured as the default TTS provider.

## Config Location

Settings live under `tts.piper.*` in `E:\hermes\config.yaml`:

```yaml
tts:
  provider: piper
  piper:
    voice: en_US-bryce-medium    # .onnx model name (see Voices section)
    length_scale: 0.9             # speaking speed (1.0 = default, <1 = faster, >1 = slower)
    noise_scale: 0.667            # generator noise (default, keep at 0.667)
    noise_w_scale: 0.333          # phoneme width variation (default 0.8)
    buffer_ms: 400                # silence prepended to fix initial warbling
```

## Narration-Optimised Parameters

Researched values for natural, flowing narration (not general-purpose TTS):

| Parameter | Recommended | Default | Effect |
|-----------|-------------|---------|--------|
| `length_scale` | **0.85–0.95** (user prefers faster). General range: 0.7–1.3 | 1.0 | Overall speaking speed. Higher = slower (beyond 1.3 sounds stretched). Lower = faster (below 0.7 can sound rushed/chipmunky). |
| `noise_scale` | **0.667** | 0.667 | Noise added to generator. Keep at default for narration. |
| `noise_w_scale` | **0.333–0.4** | 0.8 | **Phoneme width variation.** This is the most critical parameter for smooth narration. Default 0.8 causes jerky, stuttery timing. At 0.333–0.4, speech flows naturally. **Values above 0.8 produce extreme stutters and pauses.** |
| `buffer_ms` | **400+** | 0 | Silence prepended before speech. Piper's initial synthesis sometimes produces a warbling/glitchy first phoneme. Prepending 300–500ms of silence covers this. |

### Why noise_w_scale Matters Most

Piper generates each phoneme with a variable duration controlled by
`noise_w_scale`. At the default of 0.8, adjacent phonemes can vary wildly in
length, producing jerky, unnatural rhythm. For narration (sustained, flowing
speech), setting it to **0.333** gives the most natural cadence.

> Source: Piper's own `TRAINING.md` documents `noise_w` as "phoneme width
> variation (default: 0.8)". Home Assistant community reports confirm "values
> above 1.0 produce extreme stutters and pauses", with recommended narration
> settings of 0.333.

## Voices

Piper voices are .onnx model files cached under
`E:\hermes\cache\piper-voices\` (or `~/.hermes/cache/piper-voices/`).

### Currently Configured

| Voice | Quality | Notes |
|-------|---------|-------|
| `en_US-bryce-medium` | Medium (22kHz) | Deep, gruff male voice. Current default (user prefers deeper voices). |

### Changing Voice

```bash
# Switch to a different voice
hermes config set tts.piper.voice en_US-<voice_name>

# Voice takes effect on next text_to_speech call — no restart required.
```

### Downloading New Voices

Piper voices auto-download on first use from HuggingFace
(`rhasspy/piper-voices`). If a voice fails to download, grab it manually:

```bash
# Download a specific voice .onnx + .json config
curl -L -o ~/.hermes/cache/piper-voices/en_US-<voice_name>.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/<voice_name>/medium/en_US-<voice_name>-medium.onnx
curl -L -o ~/.hermes/cache/piper-voices/en_US-<voice_name>-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/<voice_name>/medium/en_US-<voice_name>-medium.onnx.json
```

Available en_US male voices for deep narration:
- `en_US-bryce-medium` — deep, gruff (current favourite)
- `en_US-joe-medium` — deep, mid-range male
- `en_US-john-medium` — rich, older male
- `en_US-norman-medium` — deeper male
- `en_US-sam-medium` — male, slightly lighter
- `en_US-ryan-medium` — deep, resonant
- `en_US-ryan-high` — higher quality but larger model
- `en_US-kusal-medium` — male
- `en_US-hfc_male-medium` — male (high-quality foundation corpus)
- `en_GB-northern_english_male-medium` — deep British male accent
- `en_GB-alan-medium` — classic British male

## Multi-Character Voice Switching

For stories with multiple POV characters (e.g., male MC + female POV), switch
Piper voices mid-production:

```bash
# Switch to male voice for male MC scenes
hermes config set tts.piper.voice en_US-ryan-medium
text_to_speech(text="...", output_path="...")

# Switch to different voice for female POV scenes
hermes config set tts.piper.voice en_US-<female-voice>
text_to_speech(text="...", output_path="...")
```

Voice changes take effect on the next `text_to_speech` call — no restart
required.

## Troubleshooting

### Warbling / Glitch at Start of Audio
**Cause:** Piper's initial synthesis sometimes produces a garbled first phoneme.
**Fix:** Increase `buffer_ms` (300–500ms typically works).

### Speech is Jerky / Awkward Timing
**Cause:** `noise_w_scale` too high. Default is 0.8 which creates stuttery timing.
**Fix:** Set `noise_w_scale: 0.333` for smooth narration flow.

### Speech Sounds Stretched / Unnatural
**Cause:** `length_scale` too high. Values above 1.3 make speech sound
stretched rather than comfortably slow.
**Fix:** Lower `length_scale`. User prefers **0.85–0.95** for natural pacing.
If you want slower speech, improve timing (`noise_w_scale`) first.

### Voice Doesn't Change
The provider and voice are read from config at TTS call time. Verify:
1. `hermes config get tts.provider` returns `piper`
2. `hermes config get tts.piper.voice` returns the expected voice name
3. The voice model file exists in the cache directory

## Related Skills

- `animated-storytelling` — uses Piper TTS for story narration voiceover
