"""Tests for story_actions: repair plan + apply, extend plan + apply, regenerate.

The full regeneration flow goes through ``generate_story.run_pipeline``
which spawns an LLM — out of scope for unit tests. We cover:

* ``plan_repair`` decision logic with a synthetic manifest + on-disk
  assets (no ComfyUI / TTS / Whisper calls).
* The perceptual-hash duplicate detector.
* ``plan_extend`` with a manifest that has audio durations and one
  without (should still work).
* The end-to-end shape of ``apply_extend``'s return value (no LLM call).
* The backup-and-wipe flow of ``regenerate_story`` using a monkey-patched
  ``run_pipeline`` so we never hit the network.

The tests build their own synthetic story directories in a temp dir
and clean up afterwards, so they don't touch the real ``stories/`` tree.
Each test passes the temp dir explicitly via the ``story_dir`` parameter
on the action functions — that override was added so the action
module doesn't need to know about ``STORIES_ROOT`` swapping.
"""

from __future__ import annotations

import json
import shutil
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from tests._helpers import has_pillow, temp_dir


def _wav(path: Path, seconds: float = 1.0, rate: int = 22050) -> None:
    """Write a short silent WAV at ``path``."""
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * n)


def _png_solid(path: Path, color: tuple = (128, 64, 32), size: tuple = (32, 32)) -> None:
    """Write a solid-color PNG at ``path`` using Pillow (test-only).

    NOTE: Solid colors produce identical avg-hashes for any two colors
    (because the mean IS the pixel value, so the threshold comparison
    is the same for every pixel). Use :func:`_png_pattern` for tests
    that need the perceptual hash to actually distinguish the images.
    """
    if not has_pillow():
        raise unittest.SkipTest("Pillow required for test fixture")
    from PIL import Image
    Image.new("RGB", size, color).save(path, "PNG")


def _png_pattern(path: Path, *, fg: tuple, bg: tuple, size: tuple = (32, 32),
                 orientation: str = "horizontal") -> None:
    """Write a PNG with alternating bright/dark stripes.

    Two images with different orientations have very different
    perceptual-hash signatures, so the duplicate detector can
    distinguish them. Used by tests that need the phash to behave
    realistically.
    """
    if not has_pillow():
        raise unittest.SkipTest("Pillow required for test fixture")
    from PIL import Image, ImageDraw
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    if orientation == "horizontal":
        d.rectangle([(0, 0), (size[0], size[1] // 2)], fill=fg)
    elif orientation == "vertical":
        d.rectangle([(0, 0), (size[0] // 2, size[1])], fill=fg)
    elif orientation == "checkerboard":
        half = 8
        for y in range(0, size[1], half):
            for x in range(0, size[0], half):
                if ((x // half) + (y // half)) % 2 == 0:
                    d.rectangle([(x, y), (x + half, y + half)], fill=fg)
    else:
        raise ValueError(f"Unknown orientation: {orientation}")
    img.save(path, "PNG")


def _build_synthetic_story(root: Path, slug: str, scenes: list[dict]) -> Path:
    """Create a story dir with a manifest + per-scene assets on disk.

    ``scenes`` is a list of dicts with the keys:
      - ``key`` (str): scene number, e.g. "01"
      - ``title`` (str)
      - ``prompt`` (str)
      - ``narration`` (str)
      - ``image`` (bool): write a PNG. Each scene gets a unique color
        so the perceptual-hash duplicate detector doesn't fire
        between scenes in a single test.
      - ``audio`` (bool): write a WAV
      - ``subs``  (bool): write a subs JSON
    Returns the story directory.
    """
    story_dir = root / slug
    story_dir.mkdir(parents=True)
    manifest = {
        "id": slug,
        "title": "Test Story",
        "subtitle": "A test",
        "description": "A test story for repair / extend / regenerate tests.",
        "tags": ["fantasy painterly", "dramatic", "generated"],
        "tone": "dramatic",
        "voice_preset": "Dean",
        "story_concept": "A test concept for the repair/extend/regenerate tests.",
        "scenes": [],
    }
    # Each scene's image is a *different orientation* of stripes so
    # the perceptual-hash duplicate detector can tell them apart. Solid
    # colors (even with different RGB values) all hash to the same
    # uniform pattern under the avg-hash technique, so they make for
    # a useless test fixture.
    stripe_styles = [
        ("horizontal", (240, 240, 240), (20, 20, 20)),
        ("vertical",   (240, 240, 240), (20, 20, 20)),
        ("checkerboard", (200, 50, 50), (10, 10, 30)),
        ("horizontal", (60, 200, 80), (10, 30, 10)),
        ("vertical",   (80, 60, 200), (10, 10, 30)),
        ("checkerboard", (220, 200, 60), (40, 30, 10)),
    ]
    for idx, s in enumerate(scenes):
        scene_obj = {
            "scene": s["key"],
            "title": s.get("title", f"Scene {s['key']}"),
            "prompt": s.get("prompt", f"A scene prompt for {s['key']}."),
            "narrative": "",
            "narration": s.get("narration", f"Narration for scene {s['key']}."),
            "narration_text": s.get("narration", f"Narration for scene {s['key']}."),
        }
        if s.get("image"):
            img = story_dir / f"{slug}_s{s['key']}_test_01_00001_.png"
            style_idx = idx % len(stripe_styles)
            orient, fg, bg = stripe_styles[style_idx]
            _png_pattern(img, fg=fg, bg=bg, orientation=orient)
            scene_obj["image_filenames"] = [img.name]
        if s.get("audio"):
            audio = story_dir / f"tts_{slug}_s{s['key']}.wav"
            _wav(audio)
            scene_obj["audio_filename"] = audio.name
            scene_obj["audio_duration"] = 1.0
        if s.get("subs"):
            subs = story_dir / f"subs_{slug}_s{s['key']}.json"
            subs.write_text(json.dumps([
                {"text": "line one", "start": 0.0, "end": 0.5},
                {"text": "line two", "start": 0.5, "end": 1.0},
            ]), encoding="utf-8")
            scene_obj["subtitle_file"] = subs.name
        manifest["scenes"].append(scene_obj)

    (story_dir / f"{slug}.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8",
    )
    return story_dir


# ── plan_repair ───────────────────────────────────────────────────────


class TestPlanRepair(unittest.TestCase):
    def test_finds_missing_image(self):
        with temp_dir() as tmp:
            slug = "missing-image"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": False, "audio": True, "subs": True},
            ])
            import story_actions
            plan = story_actions.plan_repair(slug, story_dir=story)
            self.assertEqual(plan.scenes[0].missing, ["image"])
            self.assertIn("regen_image", plan.scenes[0].actions)

    def test_finds_missing_audio(self):
        with temp_dir() as tmp:
            slug = "missing-audio"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": False, "subs": True},
            ])
            import story_actions
            plan = story_actions.plan_repair(slug, story_dir=story)
            self.assertEqual(plan.scenes[0].missing, ["audio"])
            self.assertIn("regen_tts", plan.scenes[0].actions)

    def test_finds_missing_subs(self):
        with temp_dir() as tmp:
            slug = "missing-subs"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": False},
            ])
            import story_actions
            plan = story_actions.plan_repair(slug, story_dir=story)
            self.assertEqual(plan.scenes[0].missing, ["subs"])
            self.assertIn("regen_subs", plan.scenes[0].actions)

    def test_detects_empty_subs_file(self):
        with temp_dir() as tmp:
            slug = "empty-subs"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True},
            ])
            (story / f"subs_{slug}_s01.json").write_text("[]", encoding="utf-8")
            import story_actions
            plan = story_actions.plan_repair(slug, story_dir=story)
            actions = plan.scenes[0].actions
            self.assertIn("regen_subs", actions)

    def test_finds_empty_narration(self):
        with temp_dir() as tmp:
            slug = "no-narration"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True,
                 "narration": ""},
            ])
            import story_actions
            plan = story_actions.plan_repair(slug, story_dir=story)
            self.assertIn("narration", plan.scenes[0].missing)
            self.assertEqual(plan.scenes[0].actions, ["regen_narration"])

    def test_missing_narration_without_scene_text_stays_blocked(self):
        with temp_dir() as tmp:
            slug = "no-narration-context"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True,
                 "narration": "", "prompt": "", "title": "Scene 01"},
            ])
            manifest_path = story / f"{slug}.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["scenes"][0]["prompt"] = ""
            data["scenes"][0]["narrative"] = ""
            manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

            import story_actions
            plan = story_actions.plan_repair(slug, story_dir=story)
            self.assertEqual(plan.scenes[0].actions, ["needs_narration"])

    def test_flags_parser_metadata_as_regenerate_required(self):
        with temp_dir() as tmp:
            slug = "parser-junk"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True,
                 "narration": "## SCENE 1 **Title: The Dying Grove**",
                 "prompt": "**Visual Prompt:** A wide shot that should not be stored with labels."},
            ])
            import story_actions
            plan = story_actions.plan_repair(slug, story_dir=story)
            self.assertIn("story_text", plan.scenes[0].missing)
            self.assertEqual(plan.scenes[0].actions, ["needs_regenerate"])

    def test_skips_complete_scenes(self):
        with temp_dir() as tmp:
            slug = "all-complete"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True},
                {"key": "02", "image": True, "audio": True, "subs": True},
            ])
            import story_actions
            plan = story_actions.plan_repair(slug, story_dir=story)
            self.assertEqual(plan.skipped_complete, 2)
            self.assertEqual(plan.scenes, [])

    def test_detects_near_duplicate_image(self):
        if not has_pillow():
            self.skipTest("Pillow required for phash test")
        with temp_dir() as tmp:
            slug = "dup-image"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True},
                {"key": "02", "image": True, "audio": True, "subs": True},
            ])
            # Force scene 2 to have the SAME image as scene 1 so the
            # phash detector finds a near-duplicate. The synthetic
            # helper gives each scene a distinct color by default.
            src = story / f"{slug}_s01_test_01_00001_.png"
            dst = story / f"{slug}_s02_test_01_00001_.png"
            shutil.copyfile(src, dst)
            import story_actions
            plan = story_actions.plan_repair(slug, story_dir=story)
            scenes_checked = len(plan.scenes) + plan.skipped_complete
            self.assertEqual(scenes_checked, 2)
            dup = [s for s in plan.scenes if s.duplicate_image]
            self.assertEqual(len(dup), 1, "should detect the duplicate")


# ── apply_repair ──────────────────────────────────────────────────────


class TestApplyRepair(unittest.TestCase):
    def test_apply_repair_regenerates_narration_only(self):
        with temp_dir() as tmp:
            slug = "repair-narration-only"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True,
                 "narration": ""},
            ])

            import generate_story
            import story_actions

            repaired = (
                "The lantern rises in the quiet hall, and every shadow seems to "
                "draw a breath as the hidden door remembers the hand that sealed it."
            )

            with patch.object(generate_story, "call_llm", return_value=f"Narration: {repaired}"):
                plan = story_actions.plan_repair(slug, story_dir=story)
                result = story_actions.apply_repair(slug, plan, story_dir=story)

            self.assertEqual(result.errors, [])
            self.assertEqual(result.scenes_repaired, 1)
            self.assertEqual([a["action"] for a in result.actions_taken], ["regen_narration"])

            manifest = json.loads((story / f"{slug}.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["scenes"][0]["narration"], repaired)
            self.assertEqual(manifest["scenes"][0]["narration_text"], repaired)

    def test_apply_repair_regenerates_narration_before_audio_and_subs(self):
        with temp_dir() as tmp:
            slug = "repair-narration-audio-subs"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": False, "subs": False,
                 "narration": ""},
            ])

            import generate_story
            import generate_subtitles
            import story_actions
            import tts_utils

            repaired = (
                "The bridge answers with a low groan, and the traveler steps "
                "forward while blue fire gathers beneath each ancient stone."
            )
            seen_tts_text = []

            def fake_generate_tts(text: str, audio_path: str, voice: str = "Dean",
                                  tone: str = "dramatic") -> bool:
                seen_tts_text.append(text)
                _wav(Path(audio_path), seconds=1.0)
                return True

            def fake_generate_subtitles(audio_path: str, narration: str):
                return [{"text": narration, "start": 0.0, "end": 1.0}]

            with patch.object(generate_story, "call_llm", return_value=repaired), \
                 patch.object(tts_utils, "generate_tts", side_effect=fake_generate_tts), \
                 patch.object(tts_utils, "get_audio_duration", return_value=1.0), \
                 patch.object(generate_subtitles, "generate_subtitles", side_effect=fake_generate_subtitles):
                plan = story_actions.plan_repair(slug, story_dir=story)
                self.assertEqual(plan.scenes[0].actions, ["regen_narration", "regen_tts", "regen_subs"])
                result = story_actions.apply_repair(slug, plan, story_dir=story)

            self.assertEqual(result.errors, [])
            self.assertEqual([a["action"] for a in result.actions_taken],
                             ["regen_narration", "regen_tts", "regen_subs"])
            self.assertEqual(seen_tts_text, [repaired])
            self.assertTrue((story / f"tts_{slug}_s01.wav").exists())
            self.assertTrue((story / f"subs_{slug}_s01.json").exists())


# ── plan_extend ───────────────────────────────────────────────────────


class TestPlanExtend(unittest.TestCase):
    def test_plans_five_scenes(self):
        with temp_dir() as tmp:
            slug = "extend-five"
            _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True},
            ])
            import story_actions
            plan = story_actions.plan_extend(slug, scenes=5, story_dir=tmp / slug)
            self.assertEqual(plan.will_add, 5)
            self.assertEqual(plan.current_scene_count, 1)

    def test_recovers_style_tone_from_manifest(self):
        with temp_dir() as tmp:
            slug = "extend-style"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True},
            ])
            # Override style/tone via the manifest
            manifest_path = story / f"{slug}.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["style"] = "cinematic"
            data["tone"] = "noir"
            manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            import story_actions
            plan = story_actions.plan_extend(slug, scenes=3, story_dir=story)
            self.assertEqual(plan.style, "cinematic")
            self.assertEqual(plan.tone, "noir")


# ── regenerate_story (mocked pipeline) ──────────────────────────────


class TestParserAndExtend(unittest.TestCase):
    def test_parse_scene_response_handles_fences_and_numbered_headings(self):
        from generate_story import parse_scene_response

        raw = """
```text
SCENE 1
Title: First Light
Visual Prompt: A wide shot of a lantern-lit bridge in the rain.
Narrative: The heroine steps onto the bridge.
Narration: The heroine steps onto the bridge, and the world goes quiet.

2. Second Signal
Title: Second Signal
Visual Prompt: A low angle view of a sealed door glowing faintly.
Narrative: The seal begins to crack.
Narration: The seal begins to crack, and dust spills into the hall.
```
"""
        scenes = parse_scene_response(raw, expected_scenes=2)
        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0]["title"], "First Light")
        self.assertIn("lantern-lit bridge", scenes[0]["prompt"])
        self.assertEqual(scenes[1]["title"], "Second Signal")
        self.assertIn("sealed door", scenes[1]["prompt"])

    def test_parse_scene_response_handles_bold_markdown_scene_blocks(self):
        from generate_story import parse_scene_response

        raw = """
# Clash of Ancient Minds — Scene Breakdown

**CHARACTERS:**
- **Kael** — Human shaman.
- **Brennok** — Neanderthal mystic.

---

## SCENE 1
**Title: The Dying Grove**
**Visual Prompt:** A wide shot of a sacred forest grove at twilight, with black sap bleeding from split bark while Kael kneels beside a cracked stone altar.
**Narrative:** Kael reaches the grove and discovers the land has gone silent.
**Narration:** The grove was not supposed to look like this. Kael kneels at the altar and listens for spirits that no longer answer.

---

## SCENE 2 **Title: Smoke on the Ridge**
**Visual Prompt:** A low angle shot behind Brennok on a high ridge, his mammoth-hide cloak whipping in the wind as blackness advances across the valley.
**Narrative:** Brennok sees the corruption crossing toward his settlement.
**Narration:** Smoke moves across the valley before the fires begin. Brennok raises his staff and understands that this darkness is hunting them all.
"""
        scenes = parse_scene_response(raw, expected_scenes=2)
        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0]["title"], "The Dying Grove")
        self.assertIn("sacred forest grove", scenes[0]["prompt"])
        self.assertEqual(scenes[1]["title"], "Smoke on the Ridge")
        self.assertIn("Brennok raises his staff", scenes[1]["narration"])
        self.assertNotIn("CHARACTERS", scenes[0]["prompt"])

    def test_parse_scene_response_does_not_paragraph_fallback_malformed_scene_headers(self):
        from generate_story import parse_scene_response

        raw = """
## SCENE 1
**Title: Empty Header Only**

---

## SCENE 2
**Title: Also Empty**
"""
        scenes = parse_scene_response(raw, expected_scenes=2)
        self.assertEqual(scenes, [])

    def test_apply_extend_writes_subtitles_for_new_scenes(self):
        with temp_dir() as tmp:
            slug = "extend-subs"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True},
            ])

            import comfyui_utils
            import generate_story
            import story_actions
            import tts_utils

            raw = """
```text
SCENE 2
Title: The Hidden Door
Visual Prompt: A wide shot of a lantern-lit corridor opening into an ancient vault.
Narrative: The hero follows the sound into the dark.
Narration: The hero follows the sound into the dark, lantern held high.

3. The Broken Seal
Title: The Broken Seal
Visual Prompt: A close-up of a cracked seal glowing with blue light.
Narrative: The seal finally gives way.
Narration: The seal finally gives way, and cold air spills from below.
```
"""

            def fake_call_llm(system: str, prompt: str, temperature: float = 0.7) -> str:
                return raw

            def fake_generate_tts(text: str, audio_path: str, voice: str = "Dean", tone: str = "dramatic") -> bool:
                _wav(Path(audio_path), seconds=1.0)
                return True

            def fake_get_audio_duration(audio_path: str) -> float:
                return 1.0

            def fake_regen_scene_subs(story_dir, story_id, padded, scene_obj, manifest) -> None:
                sub_path = story_dir / f"subs_{story_id}_s{padded}.json"
                sub_path.write_text(json.dumps([
                    {"text": "line one", "start": 0.0, "end": 0.5},
                    {"text": "line two", "start": 0.5, "end": 1.0},
                ]), encoding="utf-8")
                scene_obj["subtitle_file"] = sub_path.name

            with patch.object(generate_story, "call_llm", side_effect=fake_call_llm), \
                 patch.object(comfyui_utils, "is_running", return_value={"running": False}), \
                 patch.object(tts_utils, "generate_tts", side_effect=fake_generate_tts), \
                 patch.object(tts_utils, "get_audio_duration", side_effect=fake_get_audio_duration), \
                 patch.object(story_actions, "_regen_scene_subs", side_effect=fake_regen_scene_subs):
                result = story_actions.apply_extend(slug, scenes=2, story_dir=story)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["new_scenes_added"], 2)

            manifest = json.loads((story / f"{slug}.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["scenes"][1]["title"], "The Hidden Door")
            self.assertEqual(manifest["scenes"][1]["subtitle_file"], f"subs_{slug}_s02.json")
            self.assertEqual(manifest["scenes"][2]["title"], "The Broken Seal")
            self.assertEqual(manifest["scenes"][2]["subtitle_file"], f"subs_{slug}_s03.json")
            self.assertTrue((story / f"subs_{slug}_s02.json").exists())
            self.assertTrue((story / f"subs_{slug}_s03.json").exists())
            self.assertEqual(result["errors"], [])

            appended = manifest["scenes"][1:]
            self.assertTrue(all(scene.get("audio_filename") for scene in appended))
            self.assertTrue(all(scene.get("subtitle_file") for scene in appended))

    def test_apply_extend_does_not_persist_scene_when_subtitles_fail(self):
        with temp_dir() as tmp:
            slug = "extend-subs-fail"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True},
            ])

            import comfyui_utils
            import generate_story
            import story_actions
            import tts_utils

            raw = """
SCENE 2
Title: The Uncaptioned Door
Visual Prompt: A wide shot of a lantern-lit corridor opening into an ancient vault.
Narrative: The hero follows the sound into the dark.
Narration: The hero follows the sound into the dark, lantern held high.
"""

            def fake_generate_tts(text: str, audio_path: str, voice: str = "Dean", tone: str = "dramatic") -> bool:
                _wav(Path(audio_path), seconds=1.0)
                return True

            with patch.object(generate_story, "call_llm", return_value=raw), \
                 patch.object(comfyui_utils, "is_running", return_value={"running": False}), \
                 patch.object(tts_utils, "generate_tts", side_effect=fake_generate_tts), \
                 patch.object(tts_utils, "get_audio_duration", return_value=1.0), \
                 patch.object(story_actions, "_regen_scene_subs", side_effect=RuntimeError("Whisper unavailable")):
                result = story_actions.apply_extend(slug, scenes=1, story_dir=story)

            self.assertEqual(result["status"], "all_failed")
            self.assertEqual(result["new_scenes_added"], 0)
            self.assertEqual(len(result["errors"]), 1)
            self.assertIn("Whisper unavailable", result["errors"][0])

            manifest = json.loads((story / f"{slug}.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["scenes"]), 1)


class TestRegenerate(unittest.TestCase):
    def test_stale_story_dir_falls_back_to_existing_story_dir(self):
        with temp_dir() as tmp:
            slug = "stale-dir"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True},
            ])
            stale = tmp / "missing" / slug

            import story_actions
            from story_storage import ensure_story_layout

            with patch.object(story_actions, "existing_story_dir", return_value=story), \
                 patch.object(story_actions, "TRASH_DIR", tmp / "trash"):
                from generate_story import run_pipeline as _real_run_pipeline

                def _fake_run_pipeline(**kwargs):
                    ensure_story_layout(story)
                    (story / f"{slug}.json").write_text(
                        json.dumps({
                            "id": slug, "scenes": [{"scene": "01"}],
                            "status": "complete",
                        }, indent=2),
                        encoding="utf-8",
                    )
                    return {"id": slug, "scene_count": 1, "status": "complete"}

                import generate_story
                generate_story.run_pipeline = _fake_run_pipeline
                try:
                    result = story_actions.regenerate_story(
                        slug, backup=True, story_dir=stale,
                    )
                    self.assertEqual(result["status"], "ok")
                    self.assertTrue((story / "working").is_dir())
                finally:
                    generate_story.run_pipeline = _real_run_pipeline

    def test_backup_then_wipe_clears_old_files(self):
        """Re-generate should back the story up to .trash/ and wipe
        everything in the story dir before re-running the pipeline."""
        with temp_dir() as tmp:
            slug = "to-regen"
            story = _build_synthetic_story(tmp, slug, [
                {"key": "01", "image": True, "audio": True, "subs": True},
            ])

            # The regenerator uses TRASH_DIR which is a module-level
            # constant pointing at STORIES_ROOT/.trash. For this test
            # we patch it so the backup lands in our temp dir.
            import story_actions
            from story_storage import ensure_story_layout
            original_trash = story_actions.TRASH_DIR
            story_actions.TRASH_DIR = tmp / "trash"
            try:
                # Monkey-patch generate_story.run_pipeline so we don't
                # hit the LLM. The regenerator imports the symbol
                # lazily, so we patch the module attribute it resolves
                # to at call time.
                from generate_story import run_pipeline as _real_run_pipeline

                def _fake_run_pipeline(**kwargs):
                    ensure_story_layout(story)
                    (story / f"{slug}.json").write_text(
                        json.dumps({
                            "id": slug, "scenes": [{"scene": "01"}],
                            "status": "complete",
                        }, indent=2),
                        encoding="utf-8",
                    )
                    return {"id": slug, "scene_count": 1, "status": "complete"}
                import generate_story
                generate_story.run_pipeline = _fake_run_pipeline

                result = story_actions.regenerate_story(
                    slug, backup=True, story_dir=story,
                )

                self.assertEqual(result["status"], "ok")
                self.assertIsNotNone(result["backup_path"])
                backup_path = Path(result["backup_path"])
                self.assertTrue(backup_path.is_dir(),
                                "backup directory was not created")
                # The original WAV should still be in the backup
                self.assertTrue((backup_path / f"tts_{slug}_s01.wav").exists())

                # The live story dir should have been wiped and
                # re-built with the standard subfolders.
                self.assertTrue((story / "working").is_dir())
                self.assertTrue((story / "assets" / "title").is_dir())
            finally:
                story_actions.TRASH_DIR = original_trash
                # Restore the real run_pipeline so other tests don't break
                generate_story.run_pipeline = _real_run_pipeline


# ── perceptual hash ───────────────────────────────────────────────────


class TestPerceptualHash(unittest.TestCase):
    def test_identical_images_have_zero_distance(self):
        if not has_pillow():
            self.skipTest("Pillow required")
        with temp_dir() as tmp:
            p1 = tmp / "a.png"
            p2 = tmp / "b.png"
            _png_pattern(p1, fg=(200, 50, 50), bg=(10, 10, 30), orientation="horizontal")
            _png_pattern(p2, fg=(200, 50, 50), bg=(10, 10, 30), orientation="horizontal")
            import story_actions
            self.assertEqual(story_actions._phash_hamming(p1, p2), 0)

    def test_completely_different_images_have_large_distance(self):
        if not has_pillow():
            self.skipTest("Pillow required")
        with temp_dir() as tmp:
            p1 = tmp / "a.png"
            p2 = tmp / "b.png"
            # Horizontal stripes vs vertical stripes → very different
            # avg-hash signatures because the brightness distribution
            # along rows vs columns is inverted.
            _png_pattern(p1, fg=(240, 240, 240), bg=(20, 20, 20), orientation="horizontal")
            _png_pattern(p2, fg=(240, 240, 240), bg=(20, 20, 20), orientation="vertical")
            import story_actions
            d = story_actions._phash_hamming(p1, p2)
            # The two patterns have very different brightness distributions
            # → most of the 256 hash bits should differ.
            self.assertGreater(d, 64)

    def test_missing_file_returns_large_distance(self):
        if not has_pillow():
            self.skipTest("Pillow required")
        with temp_dir() as tmp:
            p1 = tmp / "exists.png"
            p2 = tmp / "missing.png"
            _png_pattern(p1, fg=(200, 50, 50), bg=(10, 10, 30), orientation="horizontal")
            import story_actions
            self.assertEqual(story_actions._phash_hamming(p1, p2), 999)


# ── apply_extend (no-LLM path) ───────────────────────────────────────


class TestApplyExtendNoLLM(unittest.TestCase):
    def test_apply_extend_refuses_with_no_existing_scenes(self):
        """If the manifest has no scenes, apply_extend should raise."""
        with temp_dir() as tmp:
            slug = "empty-story"
            story = _build_synthetic_story(tmp, slug, [])  # no scenes
            import story_actions
            with self.assertRaises(RuntimeError):
                story_actions.apply_extend(slug, scenes=3, story_dir=story)


if __name__ == "__main__":
    unittest.main()
