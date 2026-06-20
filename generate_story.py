"""
Fantasee Story Generation Pipeline (v2)
==========================================
Full-pipeline story generation using:
  - MiMo-V2.5-Pro LLM for story writing
  - MiMo-V2.5-TTS for narration audio
  - ComfyUI (AMD DirectML) for scene images
  - Whisper for subtitle alignment

Usage:
  python generate_story.py --concept "A lone ranger..." --scenes 10 --style "fantasy painterly"
  python generate_story.py --concept "A lone ranger..." --scenes 5 --skip-images
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from story_storage import STORIES_ROOT, ensure_story_layout

# ── Config ─────────────────────────────────────────────────────────────
OUTPUTS = STORIES_ROOT

# MiMo LLM config (same API as Hermes provider)
MIIMO_API_KEY = os.environ.get("XIAOMI_API_KEY", "")
MIIMO_BASE_URL = os.environ.get("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
MIIMO_MODEL = "mimo-v2.5-pro"

# ── Emit progress updates (read by the backend) ────────────────────────


def emit(status: str, message: str, progress: float = None):
    """Emit a progress message as a JSON line to stdout."""
    msg = {"status": status, "message": message}
    if progress is not None:
        msg["progress"] = progress
    print(f"__PROGRESS__:{json.dumps(msg)}", flush=True)


# ── Resolve API keys from Hermes auth.json ──────────────────────────────


def _resolve_api_key():
    """Resolve MiMo API key from env or Hermes auth.json."""
    global MIIMO_API_KEY, MIIMO_BASE_URL
    if MIIMO_API_KEY and not MIIMO_API_KEY.startswith("***"):
        return
    # Try auth.json
    auth_path = Path(os.environ.get("HERMES_HOME", "E:\\hermes")) / "auth.json"
    try:
        auth = json.loads(auth_path.read_text())
        # Check .env file directly
        env_path = Path(os.environ.get("HERMES_HOME", "E:\\hermes")) / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("XIAOMI_API_KEY=") and not stripped.startswith("#"):
                    MIIMO_API_KEY = stripped.split("=", 1)[1].strip()
                elif stripped.startswith("XIAOMI_BASE_URL=") and not stripped.startswith("#"):
                    MIIMO_BASE_URL = stripped.split("=", 1)[1].strip()
    except Exception:
        pass


# ── LLM-based Scene Generation (via MiMo API) ──────────────────────────


def call_llm(system: str, prompt: str, temperature: float = 0.7) -> Optional[str]:
    """Call the MiMo LLM API."""
    _resolve_api_key()
    if not MIIMO_API_KEY:
        emit("error", "XIAOMI_API_KEY not set — cannot call LLM")
        return None

    payload = {
        "model": MIIMO_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": 4096,
    }
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{MIIMO_BASE_URL}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {MIIMO_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=600,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            if attempt < 2:
                wait = 10 * (attempt + 1)
                emit("warning", f"LLM call failed (attempt {attempt+1}/3), retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                emit("error", f"LLM call failed after 3 attempts: {e}")
                return None


# ── Story outline generation ───────────────────────────────────────────

STORY_OUTLINE_SYSTEM = """You are a creative writing assistant specializing in visual storytelling.
Your task is to generate a detailed scene-by-scene breakdown for an illustrated story.

CRITICAL — CHARACTER BIBLE RULE:
If specific characters are provided in the prompt, every single scene MUST include
those characters by name in both the visual prompt and narrative, maintaining
consistent appearances (hairstyle, clothing, distinguishing features) across all scenes.
Characters are the anchor of the story — never drop them from a scene description.

For each scene, provide:
1. Scene title (short, evocative, 2-5 words)
2. Visual prompt (DETAILED natural language paragraph for image generation — never a tag list.
   Write it as descriptive prose. Include: character appearances, setting, lighting, camera
   angle/position, composition, color palette, mood, atmosphere. 80-150 words.)
3. Narrative (what happens in this scene — 40-80 words, purely in prose)
4. Narration (voiceover text that will be read aloud by a narrator whose
   voice and delivery style match the requested TONE. The TTS model uses
   the [Character / Scene / Guidance] director-mode structure to set delivery,
   so write narration that reads naturally when spoken aloud in that voice
   and mood — e.g. for tone "dark" lean into dread and shadow; for tone "epic"
   lean into grandeur; for tone "lyrical" lean into poetic cadence. 80-150
   words, present tense, evocative. This will be converted to speech, so
   write naturally — no visual descriptions, no camera directions, no stage
   directions in brackets. Just story and feeling.)

QUALITY STANDARDS for visual prompts:
- Write in FULL SENTENCES, not comma-separated tags or keyword lists
- ALWAYS mention the main character(s) by name and describe their appearance
- Include lighting direction and quality
- Include camera perspective
- Describe color palette explicitly
- Use vivid, atmospheric language matching the requested tone
- NEVER use tag-list format
- FACIAL FEATURES (critical for medium / close-up shots): whenever the
  framing shows a character's face — medium shot, close-up, portrait,
  three-quarter, profile, or any framing where the face is visible at
  all — explicitly describe a well-defined human nose, natural human
  facial features, and clear skin. Without this, DreamShaper-class
  checkpoints (SD 1.5) default to a deformed / pig-snout nose on
  medium and close-up shots. Include a phrase such as "a well-defined
  human nose" and "natural human facial features" in the prompt.

TONE GUIDE — match the narration and visual style to the requested tone:
- dramatic:    weight on key moments, controlled intensity, never stage-acting
- dark:        dread and shadow, slow deliberate pacing, longer pauses
- epic:        grandeur with restraint, pause for gravitas
- heroic:      quiet strength, rising energy at moments of courage
- mysterious:  trailing off, half-revealed secrets, lowered volume
- lighthearted: light smile in the voice, playful, never cynical
- comedic:     punchy timing, (slight pause) before the kicker
- romantic:    breathy intimacy, tender slowdowns
- melancholic: wistful, slower, controlled, never wallow
- hopeful:     lift toward the end, brightness in the voice
- suspenseful: hold tension, (beat) before the twist
- whimsical:   sing-song cadence, (giggles softly) at absurd moments
- epic-fantasy: bardic reverence for ancient names, grandeur with restraint
- noir:        world-weary, sardonic, short clipped sentences
- lyrical:     poetic cadence, rhythmic pauses, sung quality on description
- gritty:      raw, short punchy, in-the-mud, no flourishes
- manhwa:      Korean webtoon energy — punchy present-tense, rapid action
               bursts broken by gut-punch character beats. (sharp inhale)
               before twist reveals, then short short short for action
               sequences, then full stop. Internal-monologue beats drop
               into spoken-word register. Show, then cut. End beats on
               cliffhanger lines that beg the next panel.
- tense:       taut, alert, short sentences, hold tension
- emotional:   thicken on emotional beats, (pause) before vulnerable moments
- whisper:     (whispers) through intimate passages
- urgent:      controlled urgency, (sharp inhale) at key turns
- excited:     gentle warmth, (laughs) at happy moments
- calm:        unhurried, like a steady hand on a shoulder

Format each scene exactly as:

--- SCENE 1
Title: <title>
Visual Prompt: <detailed natural language image generation prompt — 80-150 words>
Narrative: <what happens — 40-80 words>
Narration: <voiceover text — 80-150 words, dramatic, present tense>

Scene transitions must feel natural — each scene should flow from the previous one.
Maintain consistent character appearances across ALL scenes."""


def generate_story_outline(concept: str, num_scenes: int, style: str,
                           characters: str, tone: str) -> Optional[list]:
    """Generate a complete story outline using MiMo LLM."""
    emit("running", "Generating story outline with MiMo LLM...", 0.05)

    char_section = f"\nCharacters: {characters}" if characters else ""

    user_prompt = f"""Create a {num_scenes}-scene story outline based on this concept:

Concept: {concept}
Style: {style}
Tone: {tone}{char_section}

Generate exactly {num_scenes} scenes. Each scene MUST have a Narration field
(voiceover text for TTS — 80-150 words, dramatic, present tense).
Make each visual prompt detailed enough for AI image generation."""

    response = call_llm(STORY_OUTLINE_SYSTEM, user_prompt)
    if not response:
        return None

    # Parse the response into structured scenes
    scenes = []
    current = None
    for line in response.strip().split("\n"):
        line = line.strip()
        if re.match(r"^---\s*SCENE\s*(\d+)", line, re.IGNORECASE):
            if current:
                scenes.append(current)
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
                # Append continuation
                if current["narration"]:
                    current["narration"] += " " + line
                elif current["narrative"]:
                    current["narrative"] += " " + line
                elif current["prompt"]:
                    current["prompt"] += " " + line

    if current:
        scenes.append(current)

    # Ensure every scene has a prompt and narration
    for s in scenes:
        if not s["prompt"] or len(s["prompt"]) < 20:
            s["prompt"] = s.get("narrative", s["title"])
        if not s["narration"]:
            s["narration"] = s.get("narrative", s["title"])

    if not scenes:
        # Fallback: parse as paragraphs
        paragraphs = [p.strip() for p in response.split("\n\n") if p.strip()]
        for i, p in enumerate(paragraphs[:num_scenes]):
            scenes.append({
                "title": f"Scene {i + 1}",
                "prompt": p,
                "narrative": p[:200],
                "narration": p,
            })

    emit("running", f"Generated {len(scenes)} scenes with narration.", 0.15)
    return scenes


# ── Story ID Generation ────────────────────────────────────────────────


def slugify(text: str, max_len: int = 30) -> str:
    """Convert text to a URL-safe slug, capped at max_len characters.

    Stops at the first word boundary that fits, so we never chop a word in half.
    """
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    if len(text) <= max_len:
        return text or "untitled"
    # Trim at the last hyphen within the cap to keep a word boundary
    trimmed = text[:max_len]
    last_hyphen = trimmed.rfind('-')
    if last_hyphen > max_len // 2:
        trimmed = trimmed[:last_hyphen]
    return trimmed.rstrip('-') or "untitled"


def first_title_from_response(raw: str) -> str:
    """Extract the first clean title from an LLM response that may include
    alternatives, bullets, or surrounding prose.

    The title generator sometimes returns things like:
        The Emerald's Fading Cure
        The Ironwood's Last Secret
        Wings of Embers and Bone
    We just want the first line, stripped of numbering, quotes, and bullets.
    """
    if not raw:
        return "Untitled Story"
    for line in raw.splitlines():
        cleaned = line.strip().strip("\"'`*>#-").strip()
        # Skip empty / header lines
        if not cleaned or len(cleaned) < 2:
            continue
        # Skip if it looks like a sentence (has a period in the middle, etc.)
        if cleaned.endswith(".") and len(cleaned.split()) > 6:
            continue
        return cleaned
    return "Untitled Story"


def unique_story_id(base: str, outputs_dir: Path, concept: str = "") -> str:
    """Return a unique story ID. Uses the first N chars of base + a concept-hash
    suffix on collision (deterministic for the same concept) so re-runs produce
    the same ID and we don't end up with truncated multi-title concatenations.
    """
    base = slugify(base)
    candidate = base
    if not (outputs_dir / candidate).exists():
        return candidate

    # Hash the full concept (or the base title) for a stable short suffix
    seed = concept or base
    suffix = re.sub(r'[^a-z0-9]', '', hashlib.md5(seed.encode("utf-8")).hexdigest()[:6])
    candidate = f"{base}-{suffix}"
    if not (outputs_dir / candidate).exists():
        return candidate

    # Final fallback: append a numeric counter
    counter = 2
    while (outputs_dir / f"{base}-{suffix}-{counter}").exists():
        counter += 1
    return f"{base}-{suffix}-{counter}"


# ── Duration Estimation ────────────────────────────────────────────────

def estimate_scenes_for_duration(target_minutes: float, avg_scene_seconds: float = 120) -> int:
    """Estimate scene count for a target total audio duration.
    
    Default avg_scene_seconds=120 assumes ~120 words narration at 150 wpm
    plus ~10s pause between scenes.
    """
    target_seconds = target_minutes * 60
    scenes = max(1, round(target_seconds / avg_scene_seconds))
    return scenes


def estimate_duration_for_scenes(num_scenes: int, avg_scene_seconds: float = 120) -> dict:
    """Estimate total duration for a given scene count."""
    total = num_scenes * avg_scene_seconds
    return {
        "estimated_minutes": round(total / 60, 1),
        "estimated_seconds": total,
        "scene_count": num_scenes,
    }


def calculate_actual_duration(story_dir: Path, story_id: str, scenes: list[dict]) -> float:
    """Calculate actual duration from audio files."""
    total = 0.0
    for scene in scenes:
        audio_file = scene.get("audio_filename", "")
        if audio_file:
            audio_path = story_dir / audio_file
            if audio_path.exists():
                try:
                    import wave
                    with wave.open(str(audio_path), "rb") as wf:
                        total += wf.getnframes() / wf.getframerate()
                except Exception:
                    total += scene.get("audio_duration", 0.0)
    return total


def _wrap_title_lines(text: str, max_chars: int = 18) -> list[str]:
    """Wrap a short title into SVG-friendly lines."""
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        proposed = " ".join(current + [word])
        if current and len(proposed) > max_chars:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines[:3] or ["Untitled Story"]


def write_title_slide(story_dir: Path, story_id: str, title: str,
                      concept: str, tone: str, style: str) -> str:
    """Create a lightweight title-card SVG before the expensive pipeline work."""
    title_dir = story_dir / "assets" / "title"
    title_dir.mkdir(parents=True, exist_ok=True)
    rel_path = Path("assets") / "title" / "title_slide.svg"
    path = story_dir / rel_path

    title_lines = _wrap_title_lines(title)
    subtitle = concept.strip().replace("\n", " ")
    if len(subtitle) > 118:
        subtitle = subtitle[:115].rstrip() + "..."

    line_count = len(title_lines)
    start_y = 418 - (line_count - 1) * 48
    tspans = []
    for i, line in enumerate(title_lines):
        tspans.append(
            f'<tspan x="960" y="{start_y + i * 96}">{html.escape(line)}</tspan>'
        )

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#090b12"/>
      <stop offset="52%" stop-color="#18162a"/>
      <stop offset="100%" stop-color="#2a1015"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="44%" r="62%">
      <stop offset="0%" stop-color="#e8d7a2" stop-opacity="0.20"/>
      <stop offset="55%" stop-color="#b43b3f" stop-opacity="0.10"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
    </radialGradient>
    <filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="12" stdDeviation="18" flood-color="#000000" flood-opacity="0.55"/>
    </filter>
  </defs>
  <rect width="1920" height="1080" fill="url(#bg)"/>
  <rect width="1920" height="1080" fill="url(#glow)"/>
  <rect x="108" y="92" width="1704" height="896" rx="10" fill="none" stroke="#ffffff" stroke-opacity="0.14"/>
  <text x="960" y="242" text-anchor="middle" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="26" fill="#d8caa7" letter-spacing="8">{html.escape(tone.upper())} / {html.escape(style.upper()[:38])}</text>
  <text text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-size="92" font-weight="700" fill="#fff8e8" filter="url(#softShadow)">
    {"".join(tspans)}
  </text>
  <text x="960" y="720" text-anchor="middle" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="30" fill="#d6d2dc" opacity="0.86">{html.escape(subtitle)}</text>
  <text x="960" y="842" text-anchor="middle" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="22" fill="#a9a3b7" letter-spacing="4">FANTASEE</text>
</svg>
'''
    path.write_text(svg, encoding="utf-8")

    working_title = story_dir / "working" / "prompts" / "title_slide_prompt.txt"
    working_title.parent.mkdir(parents=True, exist_ok=True)
    working_title.write_text(
        f"Title: {title}\nTone: {tone}\nStyle: {style}\nConcept: {concept}\n",
        encoding="utf-8",
    )
    emit("running", f"Title slide ready: {rel_path.as_posix()}", 0.04)
    return rel_path.as_posix()


# ── Main Pipeline ──────────────────────────────────────────────────────


def run_pipeline(concept: str, num_scenes: int = 10, style: str = "fantasy painterly",
                 characters: str = "", tone: str = "dramatic",
                 skip_images: bool = False, images_per_scene: int = 5,
                 voice_preset: str = "Dean"):
    """Run the full story generation pipeline."""
    _resolve_api_key()
    emit("queued", "Starting full-pipeline generation...")

    # Lazy imports — only load when needed
    from tts_utils import generate_tts, get_audio_duration
    from comfyui_utils import generate_image, is_running as comfyui_running

    # ── Step 1: Generate story title & ID ──────────────────────────────
    emit("running", "Step 1/6: Generating title...", 0.02)
    title_prompt = f"Generate a short, evocative story title for: {concept}\n\nTitle only, no quotes, max 6 words."
    title_result = call_llm(
        "You are a title generator. Output only the title, no quotes, no commentary.",
        title_prompt, temperature=0.8)
    story_title = first_title_from_response(title_result or "Untitled Story")
    story_id = unique_story_id(story_title, OUTPUTS, concept=concept)
    story_dir = OUTPUTS / story_id
    layout = ensure_story_layout(story_dir)

    emit("running", f"Story: \"{story_title}\" (id: {story_id})", 0.03)
    emit("running", "Generating title slide first...", 0.035)
    title_slide = write_title_slide(story_dir, story_id, story_title, concept, tone, style)

    # ── Step 2: Generate description ───────────────────────────────────
    emit("running", "Step 2/6: Writing description...", 0.05)
    desc_prompt = f"""Write a 2-3 sentence description for a story titled "{story_title}" with this concept:
{concept}
Style: {style}
Tone: {tone}
Be evocative but concise."""
    description = call_llm(
        "You write compelling story descriptions. 2-3 sentences only.", desc_prompt)
    description = description or concept[:200]
    (layout["drafts"] / "description.txt").write_text(description, encoding="utf-8")

    # ── Step 3: Generate scene outline + narration ─────────────────────
    emit("running", "Step 3/6: Generating scenes and narration...", 0.08)
    scenes = generate_story_outline(concept, num_scenes, style, characters, tone)
    if not scenes:
        emit("error", "Failed to generate scene outline.")
        return None

    if len(scenes) > num_scenes:
        scenes = scenes[:num_scenes]

    # ── Step 4: Generate images via ComfyUI ────────────────────────────
    emit("running", f"Step 4/6: Generating {len(scenes)} scene images...", 0.15)
    comfyui_status = comfyui_running()
    use_comfyui = comfyui_status.get("running", False) and not skip_images

    # Lazy import of the parallel helper; falls back to single-instance serial
    # if COMFYUI_URLS is not set, so behavior is unchanged for single-GPU setups.
    from comfyui_utils import generate_images_parallel
    comfyui_bases = os.environ.get("COMFYUI_URLS", "").strip()
    n_workers = len([b for b in comfyui_bases.split(",") if b.strip()]) if comfyui_bases else 1
    parallel_images = use_comfyui and n_workers > 1
    if parallel_images:
        emit("running", f"  Using {n_workers} ComfyUI instances in parallel")

    output_scenes = []
    # Pre-build scene shells so we can collect all image jobs up front and dispatch in parallel
    scene_shells = []
    for i, scene in enumerate(scenes):
        scene_num = i + 1
        padded = f"{scene_num:02d}"
        safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene["title"]).strip("_")[:30]
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
        output_scenes.append(s)

    if use_comfyui and parallel_images:
        # Build the full job list across all scenes
        jobs = []
        job_owners = []  # (scene_index, img_index) for each job
        for s_idx, (s, padded, safe_title, seed) in enumerate(scene_shells):
            for img_idx in range(images_per_scene):
                prefix = f"{story_id}_s{padded}_{safe_title}_{img_idx + 1:02d}"
                jobs.append({
                    "prompt": s["prompt"],
                    "output_prefix": prefix,
                    "seed": seed + img_idx,
                })
                job_owners.append((s_idx, img_idx))

        total = len(jobs)
        emit("running", f"  Dispatching {total} image jobs across {n_workers} workers")
        filenames = generate_images_parallel(jobs, output_dir=str(story_dir), timeout=600)

        for (s_idx, img_idx), filename in zip(job_owners, filenames):
            if filename:
                output_scenes[s_idx].setdefault("image_filenames", []).append(filename)

        # Emit one summary per scene
        for i, s in enumerate(output_scenes):
            img_progress = 0.15 + (i * 0.35 / max(len(scenes), 1))
            n = len(s.get("image_filenames", []))
            emit("running", f"  Scene {i + 1}/{len(scenes)}: {n} image(s) ready", img_progress)
    elif use_comfyui:
        # Serial path: one ComfyUI instance — preserved exactly as before
        for i, scene in enumerate(scenes):
            scene_num = i + 1
            padded = f"{scene_num:02d}"
            safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene["title"]).strip("_")[:30]
            seed = hash(story_id + str(scene_num)) % (2**32 - 1)
            s = output_scenes[i]

            img_progress = 0.15 + (i * 0.35 / max(len(scenes), 1))
            emit("running", f"Scene {scene_num}/{len(scenes)}: Generating image...", img_progress)
            for img_idx in range(images_per_scene):
                prefix = f"{story_id}_s{padded}_{safe_title}_{img_idx + 1:02d}"
                try:
                    filename = generate_image(
                        prompt=scene["prompt"],
                        output_prefix=prefix,
                        output_dir=str(story_dir),
                        seed=seed + img_idx,
                        timeout=600,
                    )
                    if filename:
                        s["image_filenames"].append(filename)
                except Exception as img_err:
                    emit("warning", f"Scene {scene_num} image {img_idx + 1} failed: {img_err}")
    elif skip_images:
        for i, s in enumerate(output_scenes):
            img_progress = 0.15 + (i * 0.35 / max(len(scenes), 1))
            emit("running", f"Scene {i + 1}/{len(scenes)}: Image skipped.", img_progress)

    # ── Step 5: Generate TTS audio for each scene ──────────────────────
    emit("running", f"Step 5/6: Generating narration audio ({voice_preset})...", 0.55)
    for i, s in enumerate(output_scenes):
        scene_num = i + 1
        padded = s["scene"]
        narration = s.get("narration", "")
        if not narration:
            emit("warning", f"Scene {scene_num}: No narration text, skipping TTS.")
            continue

        tts_progress = 0.55 + (i * 0.25 / max(len(output_scenes), 1))
        emit("running", f"Scene {scene_num}/{len(output_scenes)}: Generating audio...", tts_progress)

        audio_filename = f"tts_{story_id}_s{padded}.wav"
        audio_path = str(story_dir / audio_filename)
        # Pass the story tone so the TTS director-mode prompt layers in
        # the matching delivery modifier (dark / epic / mysterious / ...).
        ok = generate_tts(narration, audio_path, voice=voice_preset, tone=tone)
        if ok:
            s["audio_filename"] = audio_filename
            s["audio_duration"] = get_audio_duration(audio_path)
            emit("running", f"  ✓ {audio_filename} ({s['audio_duration']:.1f}s)", tts_progress)
        else:
            emit("warning", f"Scene {scene_num}: TTS generation failed.")

    # ── Step 5b: Generate subtitles via Whisper ────────────────────────
    emit("running", "Step 5b: Aligning subtitles with Whisper...", 0.78)
    whisper_model = None
    whisper_missing = False
    subtitle_failures = []
    subtitles_generated = 0
    for i, s in enumerate(output_scenes):
        audio_file = s.get("audio_filename", "")
        if not audio_file:
            continue
        audio_path = story_dir / audio_file
        if not audio_path.exists():
            continue

        if whisper_missing:
            continue

        try:
            if whisper_model is None:
                import whisper
                whisper_model = whisper.load_model("base")
            # fp16=False on CPU — avoids the "FP16 is not supported on CPU;
            # using FP32 instead" warning on every scene.
            result = whisper_model.transcribe(
                str(audio_path), word_timestamps=True, fp16=False,
            )

            subs = []
            for seg in result["segments"]:
                subs.append({
                    "text": seg["text"].strip(),
                    "start": round(seg["start"], 2),
                    "end": round(seg["end"], 2),
                })

            sub_filename = f"subs_{story_id}_s{s['scene']}.json"
            sub_path = story_dir / sub_filename
            sub_path.write_text(json.dumps(subs, indent=2), encoding="utf-8")
            s["subtitle_file"] = sub_filename
            subtitles_generated += 1
            emit("running", f"  + {sub_filename}: {len(subs)} segments")
        except ImportError:
            whisper_missing = True
            emit("warning", "Whisper not installed — skipping remaining subtitle alignment.")
        except Exception as e:
            subtitle_failures.append((s.get("scene", "?"), str(e)))
            emit("warning", f"Subtitle alignment failed for scene {s.get('scene', '?')}: {e}")

    if subtitles_generated:
        emit("running", f"  Generated subtitles for {subtitles_generated} scenes")
    if subtitle_failures:
        emit("warning", f"  {len(subtitle_failures)} scene(s) had subtitle errors")

    # ── Step 6: Save manifest ──────────────────────────────────────────
    emit("running", "Step 6/6: Saving manifest...", 0.95)
    tags = [style, tone, "generated"]

    manifest = {
        "id": story_id,
        "title": story_title,
        "subtitle": concept[:60],
        "description": description,
        "tags": tags,
        "tone": tone,           # explicit top-level field for TTS lookups
        "voice_preset": voice_preset,
        "generated": True,
        "scenes": output_scenes,
    }
    manifest_path = story_dir / f"{story_id}.json"
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, manifest_path)

    emit("done", f"Story generation complete: {story_title}", 1.0)

    # Output final manifest to stdout for the backend
    result = {
        "id": story_id,
        "title": story_title,
        "scene_count": len(output_scenes),
        "status": "complete",
    }
    print(f"__RESULT__:{json.dumps(result)}")

    return result


# ── CLI Entry Point ────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a story via Fantasee pipeline v2")
    parser.add_argument("--concept", required=True, help="Story concept description")
    parser.add_argument("--scenes", type=int, default=10, help="Number of scenes")
    parser.add_argument("--images-per-scene", type=int, default=1, help="Images per scene")
    parser.add_argument("--style", default="fantasy painterly", help="Art style")
    parser.add_argument("--characters", default="", help="Character descriptions")
    parser.add_argument("--tone", default="dramatic", help="Story tone")
    parser.add_argument("--voice", default="Dean", help="Xiaomi voice: Mia, Chloe, Milo, Dean (default: Dean)")
    parser.add_argument("--skip-images", action="store_true", help="Skip ComfyUI rendering")
    parser.add_argument("--target-duration", type=float, help="Target total duration in minutes (overrides --scenes)")
    args = parser.parse_args()

    try:
        # Calculate scene count from target duration if provided
        num_scenes = args.scenes
        if args.target_duration:
            num_scenes = estimate_scenes_for_duration(args.target_duration)
            print(f"Target {args.target_duration}min → {num_scenes} scenes")
        result = run_pipeline(
            concept=args.concept,
            num_scenes=num_scenes,
            style=args.style,
            characters=args.characters,
            tone=args.tone,
            skip_images=args.skip_images,
            images_per_scene=args.images_per_scene,
            voice_preset=args.voice,
        )
        if result:
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        traceback.print_exc()
        emit("error", f"Pipeline failed: {e}")
        sys.exit(1)
