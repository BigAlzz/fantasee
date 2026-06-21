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

# Patterns that should never appear in narration text. If the LLM leaks
# these into a scene's narration field, strip them so the TTS voiceover
# stays clean. Case-insensitive matching.
_NARRATION_BLOCKLIST = [
    re.compile(r"\bvisual\s+prompt\s*:", re.IGNORECASE),
    re.compile(r"\bnarration\s*:", re.IGNORECASE),
    re.compile(r"\bnarrative\s*:", re.IGNORECASE),
    re.compile(r"\btitle\s*:", re.IGNORECASE),
    re.compile(r"\bnavigation\s*:", re.IGNORECASE),
    re.compile(r"\bdescription\s*:", re.IGNORECASE),
    re.compile(r"\bscene\s+\d+\b", re.IGNORECASE),
    re.compile(r"^---\s*scene", re.IGNORECASE),
]


def _clean_narration_field(text: str) -> str:
    """Strip leaked field labels and metadata from narration text.

    The story outline parser is line-oriented: it starts a new field
    when it sees a known prefix like ``Visual Prompt:`` or
    ``Narration:``. If the LLM packs multiple fields into one line
    (or uses a slight prefix variation), the parser falls back to
    "append as continuation", which can leak the next field's content
    into the narration. This cleanup runs after parsing to catch
    anything that slipped through, so the TTS engine never reads
    "Navigation:" or a visual-prompt paragraph aloud.
    """
    if not text:
        return ""
    cleaned = text
    # Cut at the first blocklisted field marker — everything from that
    # point on is a different field that shouldn't be in narration.
    earliest = len(cleaned)
    for pattern in _NARRATION_BLOCKLIST:
        m = pattern.search(cleaned)
        if m and m.start() < earliest:
            earliest = m.start()
    if earliest < len(cleaned):
        cleaned = cleaned[:earliest]
    # Collapse repeated whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


STORY_OUTLINE_SYSTEM = """You are a creative writing assistant specializing in visual storytelling.
Your task is to generate a detailed scene-by-scene breakdown for an illustrated story.

CRITICAL — CHARACTER BIBLE RULE:
If specific characters are provided in the prompt, every single scene MUST include
those characters by name in both the visual prompt and narrative, maintaining
consistent appearances (hairstyle, clothing, distinguishing features) across all scenes.
Characters are the anchor of the story — never drop them from a scene description.

PACING — BACKGROUND-AWARE NARRATION:
A low-volume (5% by default) background music track will be looped under
the full story. The selected track's mood has already been matched to the
story tone. Write narration whose pacing feels natural over that loop:
- Aim for ~120-180 words per scene so narration breathes with the music.
- Use longer pauses (one-sentence paragraphs, em-dashes, ellipses) before
  big reveals so the music has space to swell.
- Don't cram the entire beat into a single run-on sentence — split
  moments of stillness into their own short sentence so the music can
  breathe.
- Tone-specific pacing hint (the background track has been tuned to this):
  dramatic → measured and weighty, dark → slow with longer silences,
  epic → broad strokes with gravitas, hopeful → lift toward the end of
  scenes, mysterious → trailing off, lighthearted → upbeat, melancholic
  → wistful with (sighs) at the end of long sentences.

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
- Prefer cinematic action compositions over static face portraits whenever the story beat allows it: characters moving, reaching, running, fighting, climbing, discovering, reacting, carrying tools, crossing terrain, or interacting with the environment. Use dynamic poses, visible hands/body language, foreground/background depth, and a clear story action in the frame.
- Avoid making every scene a head-and-shoulders portrait. Use a mix of wide shots, over-the-shoulder shots, three-quarter medium action shots, low-angle hero shots, chase/combat/discovery frames, and environmental storytelling. Faces can be visible, but the image should show what the characters are doing.
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

SHOT VARIETY (CRITICAL — read carefully):
Each scene's Visual Prompt MUST explicitly name ONE shot type from the
list below as the very first phrase after the framing word. Do NOT
default to "close-up portrait" or "head-and-shoulders" for every scene.
Mix the shot types across the story so the player feels like a real
film with a working cinematographer, not a slideshow of mugshots.

SHOT TYPES (pick ONE per scene, name it explicitly in the prompt):

  1. EXTREME WIDE SHOT — establishing shot, landscape or environment
     dominates, characters tiny or absent. Use for chapter openings,
     world reveals, "we see the battlefield" moments, or any scene
     where the setting IS the story.
     Keywords: "extreme wide shot", "establishing shot", "vast
     landscape", "tiny figures in", "bird's-eye view", "panoramic".

  2. WIDE / LONG SHOT — full body visible head to toe, plenty of
     room around the character, environment prominent. Use when the
     character is moving through a space, or when their body language
     matters as much as their face.
     Keywords: "wide shot", "long shot", "full body", "head to toe",
     "kneeling in", "standing in", "entire figure visible".

  3. MEDIUM SHOT — waist-up framing. The workhorse of any film;
     shows hands, gesture, and expression together. Use for
     conversation, action, discovery, and most "talking head"
     moments where the character is also DOING something.
     Keywords: "medium shot", "waist up", "from the waist up",
     "torso visible", "hands visible".

  4. MEDIUM CLOSE-UP — chest-up. More emotional than medium but
     still shows the shoulders and arms. Use for reactions, reveals,
     emotional pivots.
     Keywords: "medium close-up", "chest up", "from the chest up".

  5. CLOSE-UP — face fills most of the frame. Reserve for the most
     important emotional beats. NEVER use close-up for more than 2
     consecutive scenes — it loses impact.
     Keywords: "close-up", "face filling the frame", "tight on
     the face", "eyes dominate".

  6. EXTREME CLOSE-UP — just eyes, or just hands gripping something.
     Use for shock, focus, or micro-detail moments.
     Keywords: "extreme close-up", "macro shot", "tight on the eyes",
     "tight on the hands".

  7. OVER-THE-SHOULDER — foreground shoulder frames the shot of the
     subject. Use for conversations, reveals, watching someone from
     behind. Always name whose shoulder is in the foreground.
     Keywords: "over-the-shoulder shot", "OTS", "seen from over
     the shoulder of", "foreground shoulder frames".

  8. LOW ANGLE — camera below subject looking up. Makes the subject
     powerful, heroic, threatening. Use for villain reveals, heroic
     moments, monumental scale.
     Keywords: "low angle", "from below", "looking up at", "worm's
     eye view", "ground-level camera".

  9. HIGH ANGLE — camera above looking down. Makes the subject
     vulnerable, small, observed. Use for defeat, surveillance,
     loneliness, or to show the character as one dot in a big world.
     Keywords: "high angle", "from above", "looking down at", "bird's
     eye view", "overhead shot".

  10. DUTCH ANGLE / TILT — camera rolled. Use sparingly for tension,
      madness, unease, dream sequences.
      Keywords: "dutch angle", "tilted frame", "tilted camera", "rolled
      horizon".

SHOT ROTATION RULE: For a 10-scene story, aim for a distribution like:
  1-2 extreme wide / wide
  1-2 medium
  1-2 medium close-up
  1 close-up
  1 over-the-shoulder or low/high angle
  1-2 medium or wide for action moments
No more than TWO close-ups in a row. No more than THREE medium shots
in a row. If you find yourself writing "close-up portrait" twice,
switch the next scene to a wide or over-the-shoulder.

COMPOSITION (in addition to the shot type): name a foreground element
(a tree trunk, a doorway, a weapon held close to the lens), a
midground subject (the character), and a background element (distant
mountains, a crowd, falling ash). This layered depth reads cinematic.
Example: "wide shot, low angle, a rusted greatsword in the foreground
out of focus, a lone warrior mid-stride in the center, distant
burning city in the background haze".

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
- manhwa:      Korean / Chinese webtoon energy. See the full MANHWA NARRATION
               block below — when this tone is selected, follow that block
               for the Narration field's voice, rhythm, and structure.
- tense:       taut, alert, short sentences, hold tension
- emotional:   thicken on emotional beats, (pause) before vulnerable moments
- whisper:     (whispers) through intimate passages
- urgent:      controlled urgency, (sharp inhale) at key turns
- excited:     gentle warmth, (laughs) at happy moments
- calm:        unhurried, like a steady hand on a shoulder

MANHWA NARRATION (only when tone includes "manhwa", "manhwa-style", "webtoon",
"isekai", "system", or "leveling"):
When the requested tone is manhwa, write the Narration field in the voice
and rhythm of an English-language Korean / Chinese web novel chapter
(think Solo Leveling, The Beginning After The End, Omniscient Reader's
Viewpoint translated to English). Use these rules:

VOICE & POINT OF VIEW
- First person, past tense for internal thoughts and feelings, present
  tense for the action happening RIGHT NOW. Mix them beat by beat.
  Example: "I almost cried in my kitchen because at the one moment it
  mattered I had no food saved. And right when humanity was teetering
  on the edge of giving up before everything got ugly, the new world
  showed up instead."
- The narrator is the protagonist. They are slightly self-deprecating,
  sharp, dry, and a little cocky. They notice the small absurdities of
  the situation and crack wise to themselves, but they are not a clown.
- Use the protagonist's name sparingly — they think in terms of "I",
  "my", "myself". The system / world refers to them by name.

RHYTHM
- Vary sentence length aggressively within a single paragraph. A
  barrage of 3-6 word sentences ("The dog understood me. He
  clamped the strap in his teeth. He ran.") is followed by a
  longer 30-50 word sentence that explains the consequence or
  inner reaction.
- Use short paragraphs (1-4 sentences). Single-sentence paragraphs
  are encouraged at emotional pivots.
- Sentence fragments for shock or emphasis: "Gone. All of it. Gone."
- Em-dashes for mid-thought pivots: "Which is also why I am not
  bringing him along — I would never admit I am scared to grab a
  rooster bare-handed."

SYSTEM / GAME MECHANICS (when the story is an isekai / system story)
- The world is a game. Surface stats, levels, item descriptions, and
  rewards in clean prose, not as raw JSON. Example: "The probe read
  it as a primary conscription camp recruiting level one spearman.
  Free conscription available, 10 out of 10, one free soldier per day."
- Status screens belong in their own short paragraphs, often after a
  moment of silence. One number per screen line, mixed with a
  one-sentence reaction from the protagonist.
- Items with flavor text read like the system is talking back: "Its
  description taunting me outright, 'If you want the island to run
  fast, do not take my wood.'"

ESCALATION & PUNCHLINES
- The protagonist is always slightly outmatched, then outsmarts
  the situation. The "win" is rarely a clean fight — it's a clever
  use of resources, a misread situation, or a borrowed tool.
- Enemies and rivals are introduced with a confident threat, then
  dismantled beat by beat until the protagonist is standing over
  them with a deadpan one-liner.
- End every scene with a turn: a new enemy spotted, a new item
  revealed, a system notification, or a cliffhanger line that makes
  the listener NEED the next scene. "And just as I go to set my
  things down beside the tank, my foot skids out from under me."

WHAT TO AVOID
- No "the end", "to be continued", or out-of-story meta asides
  inside the Narration field — those go in the system prompt
  elsewhere if used at all.
- No modern slang that breaks the setting (no "lol", "bruh", "yeet").
  Witty internal monologue is fine; cringe is not.
- No wooden "show, don't tell" moralizing. Show through the
  protagonist's specific reactions, not narrator commentary.

LENGTH
- Aim for 200-300 words per scene for manhwa tone (longer than
  other tones). The voice carries a lot of texture in web novels,
  and the listener should feel like they are inside a real chapter
  rather than a beat summary.

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
Make each visual prompt detailed enough for AI image generation.

CRITICAL: For each scene, the Visual Prompt MUST start by naming ONE
shot type from this list: extreme wide shot, wide shot, long shot,
medium shot, medium close-up, close-up, extreme close-up,
over-the-shoulder shot, low angle, high angle, or dutch angle.
Do NOT default to "close-up portrait" or "head-and-shoulders".
Rotate the shot types across the {num_scenes} scenes so the
player feels cinematic, not a slideshow of mugshots. Aim for a
mix dominated by wide and medium shots, with close-ups reserved
for the most important emotional beats. See the SHOT VARIETY
block in the system prompt for details and keywords."""

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
            elif re.match(r"^(visual\s+prompt|narrative|narration|title)\s*:", low):
                # New field starting with a known prefix but slight variation
                # (e.g. "Visual Prompt:" with extra space). Treat as new field
                # by checking which field it is.
                if low.startswith("visual"):
                    current["prompt"] = line.split(":", 1)[1].strip()
                elif low.startswith("narrative"):
                    current["narrative"] = line.split(":", 1)[1].strip()
                elif low.startswith("narration"):
                    current["narration"] = line.split(":", 1)[1].strip()
                elif low.startswith("title"):
                    current["title"] = line.split(":", 1)[1].strip()
            elif low.startswith("---") or low.startswith("===") or low.startswith("scene"):
                # Skip section dividers and stray "Scene N" markers
                continue
            else:
                # Append continuation. Check that the line doesn't look like
                # the start of a new field or navigation/metadata that leaked
                # into the LLM output.
                if not line:
                    continue
                if current["narration"]:
                    current["narration"] += " " + line
                elif current["narrative"]:
                    current["narrative"] += " " + line
                elif current["prompt"]:
                    current["prompt"] += " " + line

    if current:
        scenes.append(current)

    # Clean up narration text — strip leaked field labels and metadata
    # that sometimes bleed through from the LLM output (e.g. "Navigation:",
    # "Visual Prompt:", or stray "Scene N" markers that the parser missed).
    for s in scenes:
        s["narration"] = _clean_narration_field(s.get("narration", ""))

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
    """Create an image-backed title card before the expensive pipeline work.

    The new pipeline renders a 1920x1080 PNG with a tone-tinted gradient,
    soft glow, and a readable scrim behind the title text. A legacy SVG
    mirror is still emitted so any code that pointed at the .svg keeps
    working without modification.

    Returns the POSIX path (relative to ``story_dir``) of the canonical
    PNG asset. Falls back to the legacy SVG if Pillow is unavailable.
    """
    title_dir = story_dir / "assets" / "title"
    title_dir.mkdir(parents=True, exist_ok=True)

    rel_path = Path("assets") / "title" / "title_slide.png"

    try:
        from title_image import generate_title_image
        paths = generate_title_image(story_dir, story_id, title, concept, tone, style)
        rel_path = Path("assets") / "title" / "title_slide.png"
    except Exception as e:
        # Fall back to the old SVG-only path so the story still gets a
        # title asset if Pillow is missing or another error occurs.
        print(f"[title_image] PNG render failed ({e}), falling back to SVG", file=sys.stderr)
        paths = _write_legacy_title_svg(story_dir, title, concept, tone, style)
        rel_path = Path("assets") / "title" / "title_slide.svg"

    emit("running", f"Title slide ready: {rel_path.as_posix()}", 0.04)
    return rel_path.as_posix()


def _write_legacy_title_svg(story_dir: Path, title: str, concept: str,
                            tone: str, style: str):
    """Fallback title slide that produces only the legacy SVG (no PNG)."""
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
  </defs>
  <rect width="1920" height="1080" fill="url(#bg)"/>
  <text x="960" y="242" text-anchor="middle" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="26" fill="#d8caa7" letter-spacing="8">{html.escape(tone.upper())} / {html.escape(style.upper()[:38])}</text>
  <text text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-size="92" font-weight="700" fill="#fff8e8">
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

    class _Paths:
        pass
    p = _Paths()
    p.png = None
    p.svg = path
    p.prompt = working_title
    return p


# ── Main Pipeline ──────────────────────────────────────────────────────


def run_pipeline(concept: str, num_scenes: int = 10, style: str = "fantasy painterly",
                 characters: str = "", tone: str = "dramatic",
                 skip_images: bool = False, images_per_scene: int = 5,
                 voice_preset: str = "Dean",
                 background_audio: Optional[str] = None,
                 background_volume: Optional[float] = None,
                 background_muted: bool = False):
    """Run the full story generation pipeline.

    New optional parameters (all default to ``None``/``False`` which means
    "auto-pick from the background music folder"):
    - ``background_audio``: pin a specific track filename from Background/.
    - ``background_volume``: 0.0-1.0 mix level for the Plex export.
    - ``background_muted``: start with the background silent.
    """
    _resolve_api_key()
    emit("queued", "Starting full-pipeline generation...")

    # Lazy imports — only load when needed
    from tts_utils import generate_tts, get_audio_duration
    from comfyui_utils import checkpoint_for_style, generate_image, is_running as comfyui_running

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

    # Pick a background music track up-front so the LLM can pace narration
    # to its mood. The selection is auto from the Background/ folder
    # unless the caller pinned one in via the CLI / API.
    from background_music import background_audio_payload
    bg_payload = background_audio_payload(tone=tone, style=style)
    if background_audio:
        bg_payload["background_audio"] = background_audio
    if background_volume is not None:
        bg_payload["background_volume"] = max(0.0, min(1.0, float(background_volume)))
    if background_muted:
        bg_payload["background_muted"] = True
    if bg_payload.get("background_audio"):
        emit("running",
             f"Background track: {bg_payload['background_audio']} "
             f"(default {int(bg_payload['background_volume'] * 100)}%)",
             0.04)

    early_manifest = {
        "id": story_id,
        "title": story_title,
        "subtitle": concept[:60],
        "description": concept[:200],
        "tags": [style, tone, "generated"],
        "tone": tone,
        "voice_preset": voice_preset,
        "generated": True,
        "status": "generating",
        "hero_image": title_slide,
        "title_image": title_slide,    # canonical: image-backed PNG
        "title_slide": title_slide,    # legacy alias for older clients
        "title_slide_svg": "assets/title/title_slide.svg",
        "background_audio": bg_payload.get("background_audio"),
        "background_volume": bg_payload.get("background_volume", 0.05),
        "background_muted": bg_payload.get("background_muted", False),
        "background_track_duration": bg_payload.get("background_track_duration", 0.0),
        "background_track_tags": bg_payload.get("background_track_tags", []),
        "storage_root": "stories",
        "scenes": [],
    }
    early_manifest_path = story_dir / f"{story_id}.json"
    early_tmp = early_manifest_path.with_suffix(".json.tmp")
    early_tmp.write_text(json.dumps(early_manifest, indent=2), encoding="utf-8")
    os.replace(early_tmp, early_manifest_path)

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

    (layout["drafts"] / "scenes.json").write_text(
        json.dumps(scenes, indent=2),
        encoding="utf-8",
    )

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
    image_checkpoint = checkpoint_for_style(style)
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
                    "checkpoint": image_checkpoint,
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
                        checkpoint=image_checkpoint,
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

    # Build per-scene chapter metadata so the manifest already carries the
    # chapter boundaries. The Plex exporter can use them directly without
    # re-deriving from audio durations on disk.
    chapter_seconds = 0.0
    chapter_gap = 0.5
    chapters: list[dict] = []
    for s in output_scenes:
        dur = float(s.get("audio_duration") or 0.0)
        if dur <= 0:
            continue
        chapters.append({
            "scene": s.get("scene"),
            "title": s.get("title") or f"Scene {s.get('scene')}",
            "start": round(chapter_seconds, 3),
            "end": round(chapter_seconds + dur, 3),
        })
        chapter_seconds += dur + chapter_gap

    manifest = {
        "id": story_id,
        "title": story_title,
        "subtitle": concept[:60],
        "description": description,
        "tags": tags,
        "tone": tone,           # explicit top-level field for TTS lookups
        "voice_preset": voice_preset,
        "generated": True,
        "status": "complete",
        "hero_image": title_slide,
        "title_image": title_slide,    # canonical: image-backed PNG
        "title_slide": title_slide,    # legacy alias
        "title_slide_svg": "assets/title/title_slide.svg",
        "background_audio": early_manifest.get("background_audio"),
        "background_volume": early_manifest.get("background_volume", 0.05),
        "background_muted": early_manifest.get("background_muted", False),
        "background_track_duration": early_manifest.get("background_track_duration", 0.0),
        "background_track_tags": early_manifest.get("background_track_tags", []),
        "chapters": chapters,
        "storage_root": "stories",
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
    parser.add_argument("--background-audio", default=None,
                        help="Pin a specific background track filename (otherwise auto-selected by tone)")
    parser.add_argument("--background-volume", type=float, default=None,
                        help="Background volume 0.0-1.0 (default 0.05)")
    parser.add_argument("--background-muted", action="store_true",
                        help="Start the story with background audio muted")
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
            background_audio=args.background_audio,
            background_volume=args.background_volume,
            background_muted=args.background_muted,
        )
        if result:
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        traceback.print_exc()
        emit("error", f"Pipeline failed: {e}")
        sys.exit(1)
