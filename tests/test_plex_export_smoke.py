"""Smoke test: end-to-end Plex export with ffmpeg + ffprobe.

Skipped if ffmpeg isn't available. Generates a tiny synthetic story
(two short silent WAVs, two small PNGs) and walks it through the full
Plex export pipeline, then validates the output with ``ffprobe``.

The synthetic story is small enough to run in a few seconds so the test
can be part of CI.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import unittest
import wave
from pathlib import Path

from tests._helpers import has_ffmpeg, PROJECT_ROOT, temp_dir


@unittest.skipUnless(has_ffmpeg(), "ffmpeg/ffprobe not available")
class TestPlexExportSmoke(unittest.TestCase):
    def _write_silent_wav(self, path: Path, seconds: float, rate: int = 22050) -> None:
        """Write a mono silent WAV of the given length. ffmpeg would also work
        but writing the WAV directly is faster and avoids the subprocess.
        """
        n = int(seconds * rate)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(b"\x00\x00" * n)

    def _write_test_png(self, path: Path, color: tuple = (32, 64, 128)) -> None:
        """Write a tiny solid-color PNG using a minimal encoder.

        Avoids pulling in Pillow as a test dependency. We hand-roll a
        64x64 PNG of a single color.
        """
        try:
            from PIL import Image
            Image.new("RGB", (64, 64), color).save(path, "PNG")
            return
        except ImportError:
            pass

        # No Pillow: fall back to writing a placeholder text file with a .png
        # suffix. ffmpeg will reject it, so the test will fail loudly if
        # Pillow is missing — that's a clearer signal than a silent skip.
        raise unittest.SkipTest("Pillow is required to build the smoke test fixtures")

    def _build_story(self, story_dir: Path, slug: str) -> None:
        """Create a 2-scene synthetic story under ``story_dir``."""
        # Per-scene assets
        for scene_key, label in (("01", "The Opening"), ("02", "The Reveal")):
            # Audio
            audio = story_dir / f"tts_{slug}_s{scene_key}.wav"
            self._write_silent_wav(audio, 1.0)
            # Image
            image = story_dir / f"{slug}_s{scene_key}_00001_.png"
            self._write_test_png(image, color=(32 + int(scene_key) * 32, 64, 128))
            # Subtitles (a few synthetic segments)
            subs = [
                {"text": f"Scene {scene_key} line one.", "start": 0.0, "end": 0.5},
                {"text": f"Scene {scene_key} line two.", "start": 0.5, "end": 1.0},
            ]
            (story_dir / f"subs_{slug}_s{scene_key}.json").write_text(
                json.dumps(subs), encoding="utf-8"
            )
        # Manifest
        manifest = {
            "id": slug,
            "title": "Test Story",
            "subtitle": "A test",
            "description": "Synthetic story for testing.",
            "tags": ["fantasy", "dramatic"],
            "tone": "dramatic",
            "background_audio": None,
            "background_volume": 0.05,
            "background_muted": False,
            "scenes": [
                {
                    "scene": "01",
                    "title": "The Opening",
                    "narration": "The first line.",
                    "narration_text": "The first line.",
                    "audio_filename": f"tts_{slug}_s01.wav",
                    "audio_duration": 1.0,
                    "image_filenames": [f"{slug}_s01_00001_.png"],
                },
                {
                    "scene": "02",
                    "title": "The Reveal",
                    "narration": "The second line.",
                    "narration_text": "The second line.",
                    "audio_filename": f"tts_{slug}_s02.wav",
                    "audio_duration": 1.0,
                    "image_filenames": [f"{slug}_s02_00001_.png"],
                },
            ],
        }
        (story_dir / f"{slug}.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

    def _build_per_scene_mp4(self, story_dir: Path, slug: str) -> None:
        """Render a per-scene MP4 for each scene (1 second, with audio)."""
        for scene_key in ("01", "02"):
            image = story_dir / f"{slug}_s{scene_key}_00001_.png"
            audio = story_dir / f"tts_{slug}_s{scene_key}.wav"
            out = story_dir / f"{slug}_s{scene_key}.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(image),
                "-i", str(audio),
                "-t", "1.0",
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
                "-c:a", "aac", "-b:a", "64k",
                "-pix_fmt", "yuv420p",
                "-shortest",
                "-movflags", "+faststart",
                str(out),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(
                result.returncode, 0,
                f"per-scene render failed: {(result.stderr or '')[-300:]}",
            )

    def test_full_plex_export(self):
        from plex_export import export_plex_package

        with temp_dir() as tmp:
            # Build the synthetic story directly under the real STORIES_ROOT
            # so existing_story_dir() can find it without monkey-patching
            # every lookup site. The story is cleaned up at the end.
            from story_storage import STORIES_ROOT
            slug = "smoke-test-plex-export"
            story_dir = STORIES_ROOT / slug
            # Clean up any leftovers from a previous failed run
            if story_dir.exists():
                shutil.rmtree(story_dir)
            story_dir.mkdir(parents=True)

            try:
                self._build_story(story_dir, slug)
                self._build_per_scene_mp4(story_dir, slug)

                # Run the full export. The Background/ dir lives in the real
                # project root, so auto-selection will pick a real track.
                progress_stages: list[str] = []
                def _cb(stage, msg, pct):
                    progress_stages.append(stage)
                result = export_plex_package(
                    slug,
                    progress_callback=_cb,
                )

                # ── 1. All artifacts exist ─────────────────────────────
                self.assertTrue(result.mp4.exists(), f"MP4 missing: {result.mp4}")
                self.assertTrue(result.srt.exists(), f"SRT missing: {result.srt}")
                self.assertTrue(result.vtt.exists(), f"VTT missing: {result.vtt}")
                self.assertTrue(result.chapters_file.exists(), f"Chapters missing: {result.chapters_file}")
                # Poster might be missing if the story has no images, but we
                # provided them, so it should be there.
                self.assertIsNotNone(result.poster, "poster not detected")

                # ── 2. MP4 has faststart + chapters ────────────────────
                ffprobe = subprocess.run(
                    [
                        "ffprobe", "-v", "error",
                        "-show_entries", "format=duration:stream=codec_type,codec_name",
                        "-show_chapters",
                        "-of", "default",
                        str(result.mp4),
                    ],
                    capture_output=True, text=True,
                )
                self.assertEqual(ffprobe.returncode, 0, ffprobe.stderr)

                output = ffprobe.stdout
                # Should have at least one video + one audio stream
                self.assertIn("codec_type=video", output)
                self.assertIn("codec_type=audio", output)
                # Two chapter blocks
                chapter_count = output.count("[CHAPTER]")
                self.assertGreaterEqual(chapter_count, 2, "expected at least 2 chapters")

                # ── 3. SRT and VTT share the MP4 basename ─────────────
                self.assertEqual(result.srt.stem, f"{slug}.en")
                self.assertEqual(result.vtt.stem, f"{slug}.en")
                # Sidecar content sanity — the SRT pulls from subs_*.json,
                # which our fixture populated with "Scene XX line one/two."
                srt_text = result.srt.read_text(encoding="utf-8")
                self.assertIn("Scene 01 line one.", srt_text)
                self.assertIn("Scene 02 line two.", srt_text)
                # SRT also implies the MP4 basename sidecar convention
                # (file exists next to the MP4 with the same root name)
                self.assertEqual(result.srt.parent, result.mp4.parent)
                self.assertEqual(result.srt.stem, result.mp4.stem + ".en")

                vtt_text = result.vtt.read_text(encoding="utf-8")
                self.assertTrue(vtt_text.startswith("WEBVTT"))
                self.assertIn("Scene 01 line one.", vtt_text)

                # ── 4. Audio duration matches video duration ──────────
                format_dur = None
                for line in output.splitlines():
                    if line.startswith("duration="):
                        format_dur = float(line.split("=", 1)[1])
                        break
                self.assertIsNotNone(format_dur, "ffprobe did not return a duration")
                # Both scenes are 1.0s + 0.5s gap = 2.5s total. Allow some slop.
                self.assertGreater(format_dur, 1.5)
                self.assertLess(format_dur, 4.0)

                # ── 5. Progress callback fired through all stages ─────
                expected_stages = {"discover", "subtitles", "chapters", "audio_mix", "finalize"}
                self.assertTrue(
                    expected_stages.issubset(set(progress_stages)),
                    f"progress callback missed stages: {expected_stages - set(progress_stages)}",
                )
            finally:
                # Clean up the synthetic story so the test is idempotent
                shutil.rmtree(story_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
