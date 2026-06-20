"""Story-level actions: re-generate, repair, extend.

These are the "fix my story" tools exposed on the story detail page.
Each function is pure-data (no FastAPI, no HTTP) so it's easy to unit
test and so the server endpoints are thin wrappers around it.

The three actions:

* :func:`regenerate_story` — wipe everything in the story directory
  (optionally backing up to ``.trash/``) and re-run the generation
  pipeline from scratch using the manifest's saved concept/style/tone.

* :func:`plan_repair` + :func:`apply_repair` — two-phase. The first
  walks the manifest and decides which assets are missing; the second
  does the work. Splitting them lets the UI show a "preview" modal
  ("scene 4: regenerating TTS, scene 7: regenerating subtitles, …")
  before the user commits.

* :func:`plan_extend` / :func:`apply_extend` — also two-phase. Adds N
  new scenes to an existing story by asking the LLM to continue from
  the last few scenes, then generating images + TTS for each.

The perceptual-hash duplicate check (used by ``plan_repair`` when
looking for "image present but visually identical to a previous
generation") lives in :func:`_phash_hamming` and uses a 16x16 average
hash computed via Pillow — no extra dependency.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from story_storage import STORIES_ROOT, ensure_story_layout, existing_story_dir


# ── Constants ──────────────────────────────────────────────────────────

# Backup directory for "destructive" actions. ``regenerate_story``
# copies the whole story dir here before wiping, unless the caller
# passes ``backup=False``.
TRASH_DIR = STORIES_ROOT / ".trash"

# Default number of scenes to add for the "extend" action when the
# UI doesn't override it. Matches the "Extend (5 scenes)" button.
DEFAULT_EXTEND_SCENES = 5

# Hamming-distance threshold for the perceptual-hash check. Smaller =
# stricter (fewer false positives, more near-duplicates slip through).
# 16x16 average hashes have ~256 bits of information so distance 5 is
# well within the "near-duplicate" zone.
PHASH_DUPLICATE_THRESHOLD = 5


# ── Result dataclasses ────────────────────────────────────────────────


@dataclass
class SceneRepair:
    scene_idx: int
    scene_key: str
    title: str
    missing: list[str] = field(default_factory=list)   # ["image", "audio", "subs", "narration"]
    duplicate_image: bool = False                      # image exists but looks like a previous gen
    actions: list[str] = field(default_factory=list)   # what we'd do: ["regen_image", "regen_tts", ...]


@dataclass
class RepairPlan:
    scenes: list[SceneRepair] = field(default_factory=list)
    skipped_complete: int = 0

    @property
    def has_work(self) -> bool:
        return any(s.actions for s in self.scenes)


@dataclass
class RepairResult:
    scenes_checked: int
    scenes_repaired: int
    scenes_skipped: int
    actions_taken: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scenes_checked": self.scenes_checked,
            "scenes_repaired": self.scenes_repaired,
            "scenes_skipped": self.scenes_skipped,
            "actions_taken": self.actions_taken,
            "errors": self.errors,
        }


@dataclass
class ExtendPlan:
    will_add: int
    current_scene_count: int
    current_minutes: float
    style: str
    tone: str

    def to_dict(self) -> dict:
        return {
            "will_add": self.will_add,
            "current_scene_count": self.current_scene_count,
            "current_minutes": round(self.current_minutes, 1),
            "style": self.style,
            "tone": self.tone,
        }


# ── Helpers ───────────────────────────────────────────────────────────


def _safe_unlink(path: Path) -> bool:
    """Unlink a file if it exists. Returns True if a file was removed."""
    try:
        if path.exists() and path.is_file():
            path.unlink()
            return True
    except OSError:
        pass
    return False


def _is_audio_path(path: Path) -> bool:
    return path.suffix.lower() in {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


def _audio_duration(path: Path) -> float:
    """Get audio duration in seconds using ffprobe, falling back to wave."""
    if not path.exists():
        return 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as wf:
                rate = wf.getframerate()
                if rate > 0:
                    return wf.getnframes() / float(rate)
        except Exception:
            pass
    return 0.0


def _phash_hamming(path_a: Path, path_b: Path) -> int:
    """Hamming distance between two 16x16 perceptual hashes (avg-hash).

    Returns a large number on any error so the caller treats the images
    as "not duplicates" rather than silently marking them as dupes.

    Pillow-only — no imagehash dependency required.
    """
    try:
        from PIL import Image
    except ImportError:
        return 999

    def _avg_hash(p: Path) -> Optional[bytes]:
        try:
            with Image.open(p) as img:
                img = img.convert("L").resize((16, 16), Image.Resampling.LANCZOS)
                pixels = list(img.tobytes())
                avg = sum(pixels) / len(pixels)
                # Use `>=` so a uniform-color image (avg == pixel value)
                # still produces a hash. Strict `>` would yield an
                # all-zeros hash for any solid color, making every
                # "duplicate of solid color" indistinguishable from
                # every other one.
                return bytes(1 if px >= avg else 0 for px in pixels)
        except Exception:
            return None

    h1 = _avg_hash(path_a)
    h2 = _avg_hash(path_b)
    if h1 is None or h2 is None or len(h1) != len(h2):
        return 999
    return sum(bin(a ^ b).count("1") for a, b in zip(h1, h2))


# ── Manifest I/O ──────────────────────────────────────────────────────


def _resolve_story_dir(story_id: str, story_dir: Optional[Path] = None) -> Path:
    """Resolve a story directory.

    Tests pass an explicit ``story_dir`` to target a temp folder; in
    production the helper falls back to ``existing_story_dir`` which
    looks under ``STORIES_ROOT`` and the legacy ``outputs/`` tree.
    """
    if story_dir is not None:
        return Path(story_dir)
    return existing_story_dir(story_id)


def _load_manifest(story_dir: Path) -> dict:
    manifest_path = story_dir / f"{story_dir.name}.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Story manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _save_manifest(story_dir: Path, manifest: dict) -> None:
    manifest_path = story_dir / f"{story_dir.name}.json"
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, manifest_path)


# ── Re-generate ───────────────────────────────────────────────────────


def regenerate_story(
    story_id: str,
    *,
    backup: bool = True,
    story_dir: Optional[Path] = None,
) -> dict:
    """Wipe a story and re-run the generation pipeline from scratch.

    Reads the existing manifest to recover the original concept, style,
    tone, voice, etc., then deletes everything in the story dir and
    re-runs :func:`generate_story.run_pipeline` with the same params.

    The optional ``story_dir`` parameter is a test hook: in production
    the helper resolves the dir from ``story_id`` via
    :func:`existing_story_dir`; tests pass an explicit path so they
    can target a temp folder without touching the real ``stories/``.

    Returns a dict with ``status`` and a ``result`` payload from
    ``run_pipeline``. Raises on any error.
    """
    story_dir = _resolve_story_dir(story_id, story_dir)
    if not story_dir.is_dir():
        raise FileNotFoundError(f"Story directory not found: {story_dir}")

    manifest = _load_manifest(story_dir)
    if not manifest.get("story_concept") and not manifest.get("description"):
        # Older manifests stored the concept in `description`; fall back
        # to that if the explicit `story_concept` field is missing.
        manifest["story_concept"] = manifest.get("description", "")

    # Recover the original generation params from the manifest so we
    # don't have to re-prompt the user. `style` and `tone` live in two
    # places for back-compat — `tags[0]` is the legacy position.
    tags = manifest.get("tags") or []
    style = manifest.get("style") or (tags[0] if tags else "fantasy painterly")
    tone = manifest.get("tone") or (tags[1] if len(tags) > 1 else "dramatic")
    voice = manifest.get("voice_preset") or "Dean"
    concept = (manifest.get("story_concept") or manifest.get("description") or "").strip()
    if not concept:
        raise ValueError("Manifest has no concept — cannot re-generate.")

    # Read the existing scene count from the manifest (preferred) or
    # fall back to whatever the user originally picked. Re-running with
    # the same number of scenes is the most predictable default.
    num_scenes = int(manifest.get("num_scenes") or len(manifest.get("scenes") or []) or 10)
    images_per_scene = int(manifest.get("images_per_scene") or 1)

    # ── Backup to .trash/ ───────────────────────────────────────────
    backup_path = None
    if backup:
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        # Use a unique name so multiple regens don't clobber each other
        import time as _time
        stamp = _time.strftime("%Y%m%d-%H%M%S")
        backup_path = TRASH_DIR / f"{story_id}-{stamp}"
        shutil.copytree(story_dir, backup_path)

    # ── Wipe everything in the story dir except the dir itself ────
    for child in list(story_dir.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass

    # Re-create the standard subfolders
    ensure_story_layout(story_dir)

    # ── Re-run the pipeline in-process ─────────────────────────────
    sys.path.insert(0, str(Path(__file__).parent))
    from generate_story import run_pipeline

    # `run_pipeline` derives a new slug from the concept, but we want
    # to keep the original slug so URLs / saved-progress / Plex
    # packages all keep working. The easiest path is to call
    # `run_pipeline` and then move the new story into the old dir.
    # That wastes the title-LLM call though — and we already have the
    # original title in the manifest.
    # So we pass the title and slug overrides through the manifest
    # rather than re-running the LLM title step.
    manifest = {
        "id": story_id,
        "title": manifest.get("title", story_id),
        "subtitle": manifest.get("subtitle", concept[:60]),
        "description": concept,
        "tags": [style, tone, "generated"],
        "tone": tone,
        "voice_preset": voice,
        "generated": True,
        "status": "regenerating",
        "hero_image": "assets/title/title_slide.png",
        "title_image": "assets/title/title_slide.png",
        "title_slide": "assets/title/title_slide.png",
        "background_audio": manifest.get("background_audio"),
        "background_volume": manifest.get("background_volume", 0.05),
        "background_muted": manifest.get("background_muted", False),
        "chapters": [],
        "storage_root": "stories",
        "scenes": [],
    }
    _save_manifest(story_dir, manifest)

    # Re-run in a background task by delegating to the existing pipeline.
    # The caller (server endpoint) wraps this in a thread so the event
    # loop stays responsive.
    result = run_pipeline(
        concept=concept,
        num_scenes=num_scenes,
        style=style,
        tone=tone,
        voice_preset=voice,
        images_per_scene=images_per_scene,
    )

    return {
        "status": "ok" if result else "error",
        "story_id": story_id,
        "backup_path": str(backup_path) if backup_path else None,
        "scenes_generated": (result or {}).get("scene_count", 0),
        "result": result,
    }


# ── Repair ────────────────────────────────────────────────────────────


def plan_repair(story_id: str, story_dir: Optional[Path] = None) -> RepairPlan:
    """Walk the manifest and decide what needs to be regenerated."""
    story_dir = _resolve_story_dir(story_id, story_dir)
    manifest = _load_manifest(story_dir)
    scenes = manifest.get("scenes") or []

    plan = RepairPlan()
    for i, sc in enumerate(scenes):
        scene_key = str(sc.get("scene") or (i + 1))
        title = sc.get("title") or f"Scene {scene_key}"
        sr = SceneRepair(scene_idx=i, scene_key=scene_key, title=title)

        # ── Image check ──────────────────────────────────────────
        img_files = [story_dir / f for f in (sc.get("image_filenames") or []) if f]
        image_present = bool(img_files) and all(p.exists() for p in img_files)
        if not image_present:
            sr.missing.append("image")
            sr.actions.append("regen_image")
        else:
            # Perceptual-hash duplicate check: compare the current
            # image against the "previous" image (any earlier scene's
            # image). If they're near-identical, the generation likely
            # got stuck on the same seed/style and produced a near-copy.
            if i > 0:
                prev = scenes[i - 1]
                prev_imgs = [story_dir / f for f in (prev.get("image_filenames") or []) if f]
                prev_imgs = [p for p in prev_imgs if p.exists()]
                if prev_imgs and img_files:
                    dist = min(_phash_hamming(cur, prev) for cur in img_files for prev in prev_imgs)
                    if dist <= PHASH_DUPLICATE_THRESHOLD:
                        sr.duplicate_image = True
                        sr.actions.append("regen_image")

        # ── Audio check ──────────────────────────────────────────
        audio_name = sc.get("audio_filename") or ""
        audio_path = story_dir / audio_name if audio_name else None
        if not audio_name or not audio_path.exists() or audio_path.stat().st_size < 1000:
            sr.missing.append("audio")
            sr.actions.append("regen_tts")

        # ── Subtitles check ──────────────────────────────────────
        subs_name = sc.get("subtitle_file") or f"subs_{story_id}_s{scene_key}.json"
        subs_path = story_dir / subs_name
        subs_present = False
        if subs_path.exists():
            try:
                segs = json.loads(subs_path.read_text(encoding="utf-8"))
                if segs and isinstance(segs, list) and len(segs) > 0:
                    subs_present = True
            except (json.JSONDecodeError, OSError):
                pass
        if not subs_present:
            sr.missing.append("subs")
            sr.actions.append("regen_subs")

        # ── Narration check ──────────────────────────────────────
        narration = (sc.get("narration") or sc.get("narration_text") or "").strip()
        if not narration:
            sr.missing.append("narration")
            # Can't auto-regenerate narration without the LLM — flag
            # it so the UI can show the scene as needing manual input.
            sr.actions.append("needs_narration")

        if sr.actions and not all(a == "needs_narration" for a in sr.actions):
            plan.scenes.append(sr)
        elif sr.actions:
            # Only "needs_narration" → still surface it so the user
            # sees the scene is broken, but it won't be auto-repaired.
            sr.actions = []  # drop the unfixable flag
            plan.scenes.append(sr)
        else:
            plan.skipped_complete += 1

    return plan


def apply_repair(story_id: str, plan: RepairPlan, *, progress: Optional[Callable[[str, str, float], None]] = None,
                story_dir: Optional[Path] = None) -> RepairResult:
    """Execute the actions planned by :func:`plan_repair`.

    Runs image / TTS / Whisper regeneration for the scenes that need it.
    The optional ``progress`` callback is ``(stage, message, pct)`` so
    the server endpoint can mirror progress to the WebSocket.
    """
    story_dir = _resolve_story_dir(story_id, story_dir)
    manifest = _load_manifest(story_dir)

    def _emit(stage: str, msg: str, pct: float) -> None:
        if progress:
            try:
                progress(stage, msg, pct)
            except Exception:
                pass

    result = RepairResult(
        scenes_checked=len(plan.scenes) + plan.skipped_complete,
        scenes_repaired=0,
        scenes_skipped=plan.skipped_complete,
    )

    sys.path.insert(0, str(Path(__file__).parent))

    total_actions = sum(len(sr.actions) for sr in plan.scenes
                        if any(a != "needs_narration" for a in sr.actions))
    actions_done = 0
    for sr in plan.scenes:
        scene_obj = manifest.get("scenes", [])[sr.scene_idx]
        scene_key = sr.scene_key
        padded = f"{int(scene_key):02d}" if scene_key.isdigit() else scene_key
        safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', sr.title).strip("_")[:30] or f"Scene{padded}"
        scene_repaired = False

        for action in sr.actions:
            if action == "needs_narration":
                continue
            actions_done += 1
            pct = actions_done / max(1, total_actions)
            try:
                if action == "regen_image":
                    _emit("repair", f"Regenerating image for scene {scene_key}", pct)
                    _regen_scene_image(story_dir, story_id, padded, safe_title, scene_obj, manifest)
                    scene_repaired = True
                elif action == "regen_tts":
                    _emit("repair", f"Regenerating audio for scene {scene_key}", pct)
                    _regen_scene_audio(story_dir, story_id, padded, scene_obj, manifest)
                    scene_repaired = True
                elif action == "regen_subs":
                    _emit("repair", f"Re-aligning subtitles for scene {scene_key}", pct)
                    _regen_scene_subs(story_dir, story_id, padded, scene_obj, manifest)
                    scene_repaired = True
                result.actions_taken.append({
                    "scene": sr.scene_idx,
                    "scene_key": scene_key,
                    "action": action,
                })
            except Exception as e:
                result.errors.append(f"scene {scene_key} {action}: {e}")
        if scene_repaired:
            result.scenes_repaired += 1

    # Persist any manifest changes from the per-scene regen helpers
    _save_manifest(story_dir, manifest)
    _emit("repair", "Repair complete", 1.0)
    return result


def _regen_scene_image(story_dir, story_id, padded, safe_title, scene_obj, manifest) -> None:
    """Regenerate the image(s) for one scene, in-place."""
    from comfyui_utils import generate_image, is_running
    if not is_running().get("running", False):
        # Surface a clear error to the caller instead of silently
        # doing nothing. The endpoint translates this to a 503.
        raise RuntimeError("ComfyUI is not running — start a worker first")

    # Drop any existing images so the new prefix starts fresh
    for old in scene_obj.get("image_filenames", []):
        _safe_unlink(story_dir / old)

    prompt = scene_obj.get("prompt") or ""
    if not prompt:
        raise RuntimeError("Scene has no prompt — cannot regenerate image")

    seed_base = hash(f"{story_id}{padded}repair") % (2**32 - 1)
    new_imgs = []
    for i in range(max(1, len(scene_obj.get("image_filenames") or [None]))):
        prefix = f"{story_id}_s{padded}_{safe_title}_{(i + 1):02d}"
        filename = generate_image(
            prompt=prompt,
            output_prefix=prefix,
            output_dir=str(story_dir),
            seed=seed_base + i,
            timeout=300,
        )
        if filename:
            new_imgs.append(filename)
    scene_obj["image_filenames"] = new_imgs


def _regen_scene_audio(story_dir, story_id, padded, scene_obj, manifest) -> None:
    """Regenerate the TTS audio for one scene."""
    from tts_utils import generate_tts, get_audio_duration
    narration = (scene_obj.get("narration") or scene_obj.get("narration_text") or "").strip()
    if not narration:
        raise RuntimeError("Scene has no narration — cannot regenerate audio")

    # Drop the old audio file (any extension) so the .wav we write is
    # the only thing on disk
    old = scene_obj.get("audio_filename")
    if old:
        _safe_unlink(story_dir / old)
    audio_filename = f"tts_{story_id}_s{padded}.wav"
    audio_path = str(story_dir / audio_filename)
    tone = (manifest.get("tone") or (manifest.get("tags") or ["", "dramatic"])[1] or "dramatic")
    voice = manifest.get("voice_preset") or "Dean"
    ok = generate_tts(narration, audio_path, voice=voice, tone=tone)
    if not ok:
        raise RuntimeError(f"TTS generation failed for scene {padded}")
    scene_obj["audio_filename"] = audio_filename
    scene_obj["audio_duration"] = get_audio_duration(audio_path)


def _regen_scene_subs(story_dir, story_id, padded, scene_obj, manifest) -> None:
    """Re-align the subtitles for one scene via Whisper."""
    audio_name = scene_obj.get("audio_filename")
    if not audio_name:
        raise RuntimeError("Scene has no audio — cannot generate subtitles")
    audio_path = story_dir / audio_name
    if not audio_path.exists():
        raise RuntimeError(f"Audio file missing: {audio_path}")

    narration = (scene_obj.get("narration") or scene_obj.get("narration_text") or "").strip()
    if not narration:
        raise RuntimeError("Scene has no narration — cannot generate subtitles")

    sub_path = story_dir / f"subs_{story_id}_s{padded}.json"
    # Drop the old subs file so we always write a fresh one
    _safe_unlink(sub_path)

    try:
        from generate_subtitles import generate_subtitles
        segs = generate_subtitles(str(audio_path), narration)
    except Exception as e:
        raise RuntimeError(f"Subtitle generation failed: {e}")

    sub_path.write_text(json.dumps(segs, indent=2), encoding="utf-8")
    scene_obj["subtitle_file"] = sub_path.name


# ── Extend ────────────────────────────────────────────────────────────


def plan_extend(
    story_id: str,
    scenes: int = DEFAULT_EXTEND_SCENES,
    story_dir: Optional[Path] = None,
) -> ExtendPlan:
    """Decide what the "Add N scenes" action will do."""
    story_dir = _resolve_story_dir(story_id, story_dir)
    manifest = _load_manifest(story_dir)
    current = manifest.get("scenes") or []

    # Total current minutes (sum of audio durations)
    total_seconds = 0.0
    for sc in current:
        af = sc.get("audio_filename")
        if af and (story_dir / af).exists():
            d = _audio_duration(story_dir / af)
            if d > 0:
                total_seconds += d
        elif sc.get("audio_duration"):
            total_seconds += float(sc["audio_duration"])

    tags = manifest.get("tags") or []
    style = manifest.get("style") or (tags[0] if tags else "fantasy painterly")
    tone = manifest.get("tone") or (tags[1] if len(tags) > 1 else "dramatic")

    return ExtendPlan(
        will_add=max(1, int(scenes)),
        current_scene_count=len(current),
        current_minutes=total_seconds / 60.0 if total_seconds else 0.0,
        style=style,
        tone=tone,
    )


def apply_extend(
    story_id: str,
    scenes: int = DEFAULT_EXTEND_SCENES,
    *,
    progress: Optional[Callable[[str, str, float], None]] = None,
    story_dir: Optional[Path] = None,
) -> dict:
    """Add N new scenes to the end of the story.

    Mirrors the existing ``/api/stories/{id}/extend`` endpoint but
    accepts a scene count instead of target minutes, and runs the
    per-scene work in-process so we can stream progress.
    """
    from generate_story import call_llm, STORY_OUTLINE_SYSTEM
    from tts_utils import generate_tts, get_audio_duration

    story_dir = _resolve_story_dir(story_id, story_dir)
    manifest = _load_manifest(story_dir)
    existing = manifest.get("scenes") or []
    if not existing:
        raise RuntimeError("Story has no scenes to extend from")

    tags = manifest.get("tags") or []
    style = manifest.get("style") or (tags[0] if tags else "fantasy painterly")
    tone = manifest.get("tone") or (tags[1] if len(tags) > 1 else "dramatic")
    voice = manifest.get("voice_preset") or "Dean"
    images_per_scene = int(manifest.get("images_per_scene") or 1)

    plan = plan_extend(story_id, scenes)

    def _emit(stage: str, msg: str, pct: float) -> None:
        if progress:
            try:
                progress(stage, msg, pct)
            except Exception:
                pass

    # Build a short context from the last 3 scenes so the LLM
    # continues the story coherently
    context_parts = []
    for cs in existing[-3:]:
        context_parts.append(
            f"Scene {cs.get('scene', '?')}: {cs.get('title', 'Untitled')}\n"
            f"Narration: {(cs.get('narration') or cs.get('narration_text') or '')[:200]}"
        )
    context_text = "\n\n".join(context_parts)

    _emit("extend", f"Writing {plan.will_add} new scene(s) with the LLM…", 0.05)
    user_prompt = f"""Continue this story. The previous scenes were:

{context_text}

Write exactly {plan.will_add} more scenes that continue from where the story left off.
Maintain the same characters, tone, and visual style.
Each scene MUST have a Narration field (voiceover text for TTS — 80-150 words, dramatic, present tense).
Make each visual prompt detailed enough for AI image generation (80-150 words).

Style: {style}
Tone: {tone}"""

    raw = call_llm(STORY_OUTLINE_SYSTEM, user_prompt)
    if not raw:
        raise RuntimeError("LLM did not return continuation scenes")

    # Parse the LLM response (same format as `generate_story_outline`)
    new_scenes_raw = []
    current = None
    for line in raw.strip().split("\n"):
        line = line.strip()
        if re.match(r"^---\s*SCENE\s*\d+", line, re.IGNORECASE):
            if current:
                new_scenes_raw.append(current)
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
                if current["narration"]:
                    current["narration"] += " " + line
                elif current["prompt"]:
                    current["prompt"] += " " + line
    if current:
        new_scenes_raw.append(current)

    # Materialize the new scenes
    base_idx = len(existing)
    added = []
    from comfyui_utils import generate_image, is_running as comfyui_running
    use_comfyui = comfyui_running().get("running", False) and images_per_scene > 0
    n_workers = 1  # extend doesn't dispatch in parallel; that's a future
    # optimization if image-gen is the bottleneck

    _emit("extend", f"Rendering {len(new_scenes_raw)} new scene(s)…", 0.30)
    for i, scene in enumerate(new_scenes_raw):
        scene_num = base_idx + i + 1
        padded = f"{scene_num:02d}"
        safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", "")).strip("_")[:30] or f"Scene{padded}"
        seed = hash(story_id + padded + "extend") % (2**32 - 1)

        new_scene = {
            "scene": padded,
            "title": scene.get("title", f"Scene {scene_num}"),
            "prompt": scene.get("prompt", ""),
            "narrative": scene.get("narrative", ""),
            "narration": scene.get("narration", scene.get("narrative", "")),
            "narration_text": scene.get("narration", scene.get("narrative", "")),
            "seed": seed,
            "image_filenames": [],
        }

        # Images (only if ComfyUI is running)
        if use_comfyui:
            for img_idx in range(images_per_scene):
                prefix = f"{story_id}_s{padded}_{safe_title}_{img_idx + 1:02d}"
                try:
                    filename = generate_image(
                        prompt=scene.get("prompt", ""),
                        output_prefix=prefix,
                        output_dir=str(story_dir),
                        seed=seed + img_idx,
                        timeout=300,
                    )
                    if filename:
                        new_scene["image_filenames"].append(filename)
                except Exception as img_err:
                    print(f"[extend] image {scene_num}/{img_idx + 1} failed: {img_err}", file=sys.stderr)

        # TTS
        narration = new_scene["narration"]
        if narration:
            audio_filename = f"tts_{story_id}_s{padded}.wav"
            audio_path = str(story_dir / audio_filename)
            try:
                if generate_tts(narration, audio_path, voice=voice):
                    new_scene["audio_filename"] = audio_filename
                    new_scene["audio_duration"] = get_audio_duration(audio_path)
            except Exception as tts_err:
                print(f"[extend] TTS scene {scene_num} failed: {tts_err}", file=sys.stderr)

        existing.append(new_scene)
        added.append(new_scene["title"])

        # Persist after every successful scene so a partial extension
        # is always recoverable
        manifest["scenes"] = existing
        _save_manifest(story_dir, manifest)

        pct = 0.30 + 0.65 * ((i + 1) / max(1, len(new_scenes_raw)))
        _emit("extend", f"Added scene {scene_num}: {new_scene['title']}", pct)

    _emit("extend", "Extend complete", 1.0)
    return {
        "status": "ok" if added else "all_failed",
        "new_scenes_added": len(added),
        "titles": added,
        "total_scenes": len(existing),
    }
