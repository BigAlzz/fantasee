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

import hashlib
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
from image_quality import is_usable_story_image, requested_images_per_scene
from fantasee_server.subtitle_validation import validate_subtitle_segments


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
UNFIXABLE_REPAIR_ACTIONS = {"needs_narration", "needs_prompt", "needs_regenerate"}

_PARSER_METADATA_RE = re.compile(
    r"""
    ^\s*(?:
        [-*_]{3,}\s*$ |
        \#{1,6}\s*.*scene\s+breakdown\b |
        \#{1,6}\s*scene\s*\d+\b |
        \*\*\s*(?:characters|title|visual\s+prompt|narrative|narration)\s*: |
        (?:title|visual\s+prompt|narrative|narration)\s*:
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _looks_like_parser_metadata(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    if _PARSER_METADATA_RE.search(text):
        return True
    return bool(re.fullmatch(r"[-=_#*\s]+", text))


def _has_scene_text_for_narration(scene: dict) -> bool:
    """Return True when a missing narration can be inferred safely."""
    for key in ("prompt", "narrative"):
        value = (scene.get(key) or "").strip()
        if value and not _looks_like_parser_metadata(value):
            return True
    return False


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
    duration_minutes: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "will_add": self.will_add,
            "current_scene_count": self.current_scene_count,
            "current_minutes": round(self.current_minutes, 1),
            "style": self.style,
            "tone": self.tone,
            "duration_minutes": round(self.duration_minutes, 1) if self.duration_minutes else None,
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
        candidate = Path(story_dir)
        if candidate.is_dir():
            return candidate
        fallback = existing_story_dir(story_id)
        if fallback.is_dir():
            return fallback
        return candidate
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
    progress_callback: Optional[Callable[[str, str, Optional[float]], None]] = None,
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

    if progress_callback:
        progress_callback("discover", "Reading the saved story direction and production inputs", 0.02)

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
    narration_style = manifest.get("narration_style") or ""
    world_context = manifest.get("world_context") or ""
    voice_assignments = manifest.get("voice_assignments") or ""
    characters = manifest.get("characters") or ""
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
        if progress_callback:
            progress_callback("backup", "Securing a backup before replacing the current production", 0.06)
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        # Use a unique name so multiple regens don't clobber each other
        import time as _time
        stamp = _time.strftime("%Y%m%d-%H%M%S")
        backup_path = TRASH_DIR / f"{story_id}-{stamp}"
        shutil.copytree(story_dir, backup_path)

    # ── Wipe everything in the story dir except the dir itself ────
    if progress_callback:
        progress_callback("reset", "Clearing stale generated assets while preserving the backup", 0.1)
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
        "narration_style": narration_style,
        "characters": characters,
        "world_context": world_context,
        "voice_assignments": voice_assignments,
        "generated": True,
        "status": "regenerating",
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
    try:
        if progress_callback:
            progress_callback("generate", "Starting the full story pipeline: script, scenes, images, narration, and subtitles", 0.12)
        result = run_pipeline(
            concept=concept,
            num_scenes=num_scenes,
            style=style,
            tone=tone,
            voice_preset=voice,
            images_per_scene=images_per_scene,
            characters=characters,
            narration_style=narration_style,
            world_context=world_context,
            progress_callback=progress_callback,
        )
    except Exception as pipeline_err:
        # Pipeline failed — restore from backup if we made one
        if backup_path and backup_path.exists():
            # Wipe the failed attempt
            for child in list(story_dir.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    try:
                        child.unlink()
                    except OSError:
                        pass
            # Restore from backup
            shutil.copytree(backup_path, story_dir)
            return {
                "status": "error_restored",
                "story_id": story_id,
                "backup_path": str(backup_path),
                "error": str(pipeline_err),
                "note": "Pipeline failed; story restored from backup",
            }
        raise

    # run_pipeline() derives its own slug from a fresh LLM title call,
    # so the generated content lands in stories/<new-slug>/ — not the
    # original story_dir we just wiped. Move it back so URLs, saved
    # progress, and Plex packages keep the original slug.
    if result and result.get("id") and result["id"] != story_id:
        new_dir = story_dir.parent / result["id"]
        if new_dir.exists() and new_dir != story_dir:
            # Clear the placeholder manifest we wrote in the original dir
            for child in list(story_dir.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    try:
                        child.unlink()
                    except OSError:
                        pass
            # Move all content from the new dir into the original dir
            for child in list(new_dir.iterdir()):
                target = story_dir / child.name
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink(missing_ok=True)
                shutil.move(str(child), str(target))
            # Rename the manifest file to match the original slug
            new_manifest = story_dir / f"{result['id']}.json"
            old_manifest = story_dir / f"{story_id}.json"
            if new_manifest.exists() and not old_manifest.exists():
                new_manifest.rename(old_manifest)
            # Update the id field inside the manifest
            if old_manifest.exists():
                try:
                    m = json.loads(old_manifest.read_text(encoding="utf-8"))
                    m["id"] = story_id
                    _save_manifest(story_dir, m)
                except Exception:
                    pass
            # Remove the now-empty new directory
            try:
                new_dir.rmdir()
            except OSError:
                pass
            result["id"] = story_id

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
    target_images = requested_images_per_scene(manifest)

    plan = RepairPlan()
    for i, sc in enumerate(scenes):
        scene_key = str(sc.get("scene") or (i + 1))
        title = sc.get("title") or f"Scene {scene_key}"
        sr = SceneRepair(scene_idx=i, scene_key=scene_key, title=title)

        # ── Image check ──────────────────────────────────────────
        img_files = [story_dir / f for f in (sc.get("image_filenames") or []) if f]
        usable_img_files = [path for path in img_files if is_usable_story_image(path)]
        image_present = len(usable_img_files) >= target_images
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
                prev_imgs = [path for path in prev_imgs if is_usable_story_image(path)]
                if prev_imgs and usable_img_files:
                    dist = min(
                        _phash_hamming(cur, prev)
                        for cur in usable_img_files
                        for prev in prev_imgs
                    )
                    if dist <= PHASH_DUPLICATE_THRESHOLD:
                        sr.duplicate_image = True
                        sr.actions.append("regen_image")

        narration = (sc.get("narration") or sc.get("narration_text") or "").strip()
        prompt = (sc.get("prompt") or "").strip()
        if _looks_like_parser_metadata(narration) or _looks_like_parser_metadata(prompt):
            sr.missing.append("story_text")
            sr.actions.append("needs_regenerate")
        elif not narration:
            sr.missing.append("narration")
            if _has_scene_text_for_narration(sc):
                sr.actions.append("regen_narration")
            else:
                sr.actions.append("needs_narration")

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

        if sr.actions and not all(a in UNFIXABLE_REPAIR_ACTIONS for a in sr.actions):
            plan.scenes.append(sr)
        elif sr.actions:
            # Only "needs_narration" → still surface it so the user
            # sees the scene is broken, but it won't be auto-repaired.
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

    total_actions = sum(
        len([a for a in sr.actions if a not in UNFIXABLE_REPAIR_ACTIONS])
        for sr in plan.scenes
    )
    actions_done = 0
    for sr in plan.scenes:
        scene_obj = manifest.get("scenes", [])[sr.scene_idx]
        scene_key = sr.scene_key
        padded = f"{int(scene_key):02d}" if scene_key.isdigit() else scene_key
        safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', sr.title).strip("_")[:30] or f"Scene{padded}"
        scene_repaired = False

        for action in sr.actions:
            if action in UNFIXABLE_REPAIR_ACTIONS:
                continue
            actions_done += 1
            pct = actions_done / max(1, total_actions)
            try:
                if action == "regen_image":
                    _emit("repair", f"Regenerating image for scene {scene_key}", pct)
                    _regen_scene_image(story_dir, story_id, padded, safe_title, scene_obj, manifest)
                    scene_repaired = True
                elif action == "regen_narration":
                    _emit("repair", f"Regenerating narration for scene {scene_key}", pct)
                    _regen_scene_narration(story_id, scene_obj, manifest)
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


def _regen_scene_narration(story_id: str, scene_obj: dict, manifest: dict) -> None:
    """Regenerate missing narration for one scene from existing scene text."""
    if not _has_scene_text_for_narration(scene_obj):
        raise RuntimeError("Scene has no prompt or narrative to regenerate narration from")

    from generate_story import _clean_narration_field, call_llm, load_story_style_prompt

    tags = manifest.get("tags") or []
    style = manifest.get("style") or (tags[0] if tags else "fantasy painterly")
    tone = manifest.get("tone") or (tags[1] if len(tags) > 1 else "dramatic")
    concept = (manifest.get("story_concept") or manifest.get("description") or "").strip()
    title = (scene_obj.get("title") or f"Scene {scene_obj.get('scene', '?')}").strip()
    prompt = (scene_obj.get("prompt") or "").strip()
    narrative = (scene_obj.get("narrative") or "").strip()

    system = (
        "You repair missing voiceover narration for an illustrated story. "
        "Return only the narration text, with no labels, markdown headings, or notes.\n\n"
        "Follow this mandatory narration style:\n"
        f"{load_story_style_prompt()}"
    )
    user_prompt = f"""Story ID: {story_id}
Story concept: {concept or "Unknown"}
Style: {style}
Tone: {tone}

Scene: {title}
Visual prompt:
{prompt or "(missing)"}

Narrative beat:
{narrative or "(missing)"}

Write one spoken narration passage for this scene, 80-150 words, in third person,
matching the canonical narration style and preserving the action described above.
Return only the narration text."""

    raw = call_llm(system, user_prompt, temperature=0.7)
    raw_text = re.sub(r"^\s*(?:\*\*)?\s*narration\s*:\s*", "", raw or "", flags=re.IGNORECASE).strip()
    narration = _clean_narration_field(raw_text)
    if len(narration.split()) < 8:
        raise RuntimeError("LLM did not return usable narration")

    scene_obj["narration"] = narration
    scene_obj["narration_text"] = narration


def _regen_scene_image(story_dir, story_id, padded, safe_title, scene_obj, manifest) -> None:
    """Regenerate the image(s) for one scene, in-place."""
    from comfyui_utils import checkpoint_for_style, generate_image, is_running
    if not is_running().get("running", False):
        # Surface a clear error to the caller instead of silently
        # doing nothing. The endpoint translates this to a 503.
        raise RuntimeError("ComfyUI is not running — start a worker first")

    prompt = scene_obj.get("prompt") or ""
    if not prompt:
        raise RuntimeError("Scene has no prompt — cannot regenerate image")

    seed_base = int(hashlib.md5(f"{story_id}{padded}repair".encode()).hexdigest()[:8], 16) % (2**32 - 1)
    tags = manifest.get("tags") or []
    style = manifest.get("style") or (tags[0] if tags else "fantasy painterly")
    checkpoint = checkpoint_for_style(style)
    target_images = requested_images_per_scene(manifest)
    old_images = list(scene_obj.get("image_filenames") or [])
    new_imgs = []
    for i in range(target_images):
        prefix = f"{story_id}_s{padded}_{safe_title}_{(i + 1):02d}"
        filename = generate_image(
            prompt=prompt,
            output_prefix=prefix,
            output_dir=str(story_dir),
            seed=seed_base + i,
            checkpoint=checkpoint,
            style=style,
            timeout=300,
        )
        if filename:
            new_imgs.append(filename)
    if len(new_imgs) < target_images:
        raise RuntimeError(
            f"ComfyUI produced {len(new_imgs)} of {target_images} usable images for scene {padded}"
        )

    for old in old_images:
        if old not in new_imgs:
            _safe_unlink(story_dir / old)
    scene_obj["image_filenames"] = new_imgs

    # Any video built from the old artwork is now stale and must be rebuilt.
    _safe_unlink(story_dir / f"{story_id}_s{padded}.mp4")
    _safe_unlink(story_dir / f"{story_id}_full.mp4")
    _safe_unlink(story_dir / "final" / f"{story_id}_full.mp4")
    plex_dir = story_dir / "final" / "plex"
    if plex_dir.is_dir():
        for plex_video in plex_dir.glob("*.mp4"):
            _safe_unlink(plex_video)


def _regen_scene_audio(story_dir, story_id, padded, scene_obj, manifest) -> None:
    """Regenerate the TTS audio for one scene."""
    from tts_utils import generate_tts, get_audio_duration
    from comfyui_utils import checkpoint_for_style
    narration = (scene_obj.get("narration") or scene_obj.get("narration_text") or "").strip()
    if not narration:
        raise RuntimeError("Scene has no narration — cannot regenerate audio")

    old = scene_obj.get("audio_filename")
    audio_filename = f"tts_{story_id}_s{padded}.wav"
    audio_path = str(story_dir / audio_filename)
    target_path = Path(audio_path)
    temporary_path = target_path.with_name(f".{target_path.stem}.{os.getpid()}.replacement.wav")
    tone = (manifest.get("tone") or (manifest.get("tags") or ["", "dramatic"])[1] or "dramatic")
    voice = manifest.get("voice_preset") or "Dean"
    try:
        ok = generate_tts(narration, str(temporary_path), voice=voice, tone=tone)
        if not ok or not temporary_path.exists() or temporary_path.stat().st_size <= 1000:
            raise RuntimeError(f"TTS generation failed for scene {padded}")
        duration = get_audio_duration(str(temporary_path))
        if duration <= 0:
            raise RuntimeError(f"TTS output has no usable duration for scene {padded}")
        os.replace(temporary_path, target_path)
    finally:
        _safe_unlink(temporary_path)
    if old and old != audio_filename:
        _safe_unlink(story_dir / old)
    scene_obj["audio_filename"] = audio_filename
    scene_obj["audio_duration"] = duration


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

    try:
        from generate_subtitles import generate_subtitles
        segs = generate_subtitles(str(audio_path), narration)
    except Exception as e:
        raise RuntimeError(f"Subtitle generation failed: {e}")

    try:
        validate_subtitle_segments(segs, _audio_duration(audio_path))
    except ValueError as exc:
        raise RuntimeError(f"Subtitle generation produced invalid timing: {exc}") from exc

    temporary_path = sub_path.with_name(f".{sub_path.stem}.{os.getpid()}.replacement.json")
    try:
        temporary_path.write_text(json.dumps(segs, indent=2), encoding="utf-8")
        os.replace(temporary_path, sub_path)
    finally:
        _safe_unlink(temporary_path)
    scene_obj["subtitle_file"] = sub_path.name


# ── Extend ────────────────────────────────────────────────────────────


def plan_extend(
    story_id: str,
    scenes: Optional[int] = DEFAULT_EXTEND_SCENES,
    duration_minutes: Optional[float] = None,
    story_dir: Optional[Path] = None,
) -> ExtendPlan:
    """Decide how many scenes are needed for a scene or duration extension."""
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

    if duration_minutes is not None:
        requested_minutes = float(duration_minutes)
        if requested_minutes <= 0:
            raise ValueError("duration_minutes must be positive")
        average_seconds = total_seconds / len(current) if total_seconds and current else 45.0
        will_add = max(1, min(50, int((requested_minutes * 60 + average_seconds - 1) // average_seconds)))
    else:
        requested_minutes = None
        will_add = max(1, min(50, int(scenes or DEFAULT_EXTEND_SCENES)))

    return ExtendPlan(
        will_add=will_add,
        current_scene_count=len(current),
        current_minutes=total_seconds / 60.0 if total_seconds else 0.0,
        style=style,
        tone=tone,
        duration_minutes=requested_minutes,
    )


def apply_extend(
    story_id: str,
    scenes: Optional[int] = DEFAULT_EXTEND_SCENES,
    *,
    duration_minutes: Optional[float] = None,
    prompt: str = "",
    progress: Optional[Callable[[str, str, float], None]] = None,
    story_dir: Optional[Path] = None,
) -> dict:
    """Add N new scenes to the end of the story.

    Runs the per-scene work in-process so the existing story-action progress
    channel can report each generated scene. ``prompt`` is a creative
    instruction, including an optional requested ending or character fate.
    """
    from generate_story import call_llm, STORY_OUTLINE_SYSTEM, parse_scene_response
    from tts_utils import generate_tts, get_audio_duration
    from comfyui_utils import checkpoint_for_style

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
    image_checkpoint = checkpoint_for_style(style)

    plan = plan_extend(story_id, scenes, duration_minutes, story_dir=story_dir)

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
Director's continuation instruction: {prompt.strip() or "Continue naturally and leave a meaningful new turn at the end."}
Each scene MUST have a Narration field (voiceover text for TTS — 80-150 words, dramatic, present tense).
Make each visual prompt detailed enough for AI image generation (80-150 words).
Prefer cinematic action compositions over static portraits whenever possible: show characters moving, fighting, climbing, discovering, reacting, using tools, crossing terrain, or interacting with the environment. Use dynamic poses, visible hands/body language, depth, camera angle, and a clear story action in the frame. Do not make every image a face close-up.

Style: {style}
Tone: {tone}"""

    raw = call_llm(STORY_OUTLINE_SYSTEM, user_prompt)
    if not raw:
        raise RuntimeError("LLM did not return continuation scenes")

    new_scenes_raw = parse_scene_response(raw, expected_scenes=plan.will_add)

    # Materialize the new scenes
    base_idx = len(existing)
    added = []
    from comfyui_utils import generate_image, is_running as comfyui_running
    use_comfyui = comfyui_running().get("running", False) and images_per_scene > 0
    n_workers = 1  # extend doesn't dispatch in parallel; that's a future
    # optimization if image-gen is the bottleneck

    _emit("extend", f"Rendering {len(new_scenes_raw)} new scene(s)…", 0.30)
    errors = []
    for i, scene in enumerate(new_scenes_raw):
        scene_num = base_idx + i + 1
        padded = f"{scene_num:02d}"
        safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", "")).strip("_")[:30] or f"Scene{padded}"
        seed = int(hashlib.md5(f"{story_id}{padded}extend".encode()).hexdigest()[:8], 16) % (2**32 - 1)

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
                        checkpoint=image_checkpoint,
                        style=style,
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
                if not generate_tts(narration, audio_path, voice=voice):
                    raise RuntimeError("TTS generation failed")
                new_scene["audio_filename"] = audio_filename
                new_scene["audio_duration"] = get_audio_duration(audio_path)
                _regen_scene_subs(story_dir, story_id, padded, new_scene, manifest)
                sub_name = new_scene.get("subtitle_file")
                if not sub_name or not (story_dir / sub_name).exists():
                    raise RuntimeError("subtitle generation did not write a subtitle_file")
            except Exception as tts_err:
                msg = f"scene {scene_num}: {tts_err}"
                errors.append(msg)
                print(f"[extend] {msg}", file=sys.stderr)
                _emit("extend", f"Skipped scene {scene_num}: {tts_err}", 0.30)
                continue
        else:
            msg = f"scene {scene_num}: missing narration"
            errors.append(msg)
            print(f"[extend] {msg}", file=sys.stderr)
            _emit("extend", f"Skipped scene {scene_num}: missing narration", 0.30)
            continue

        existing.append(new_scene)
        added.append(new_scene["title"])

        # Persist after every successful scene so a partial extension
        # is always recoverable
        manifest["scenes"] = existing
        _save_manifest(story_dir, manifest)

        pct = 0.30 + 0.65 * ((i + 1) / max(1, len(new_scenes_raw)))
        _emit("extend", f"Added scene {scene_num}: {new_scene['title']}", pct)

    _emit("extend", "Extend complete", 1.0)
    status = "ok" if added and not errors else ("partial_failed" if added else "all_failed")
    return {
        "status": status,
        "new_scenes_added": len(added),
        "titles": added,
        "total_scenes": len(existing),
        "errors": errors,
    }
