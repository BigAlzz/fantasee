"""Smoke test: end-to-end Plex export with ffmpeg + ffprobe.

Skipped if ffmpeg isn't available. Generates a tiny synthetic story
(two short silent WAVs, two small PNGs) and walks it through the full
Plex export pipeline, then validates the output with ``ffprobe``.

The synthetic story is small enough to run in a few seconds so the test
can be part of CI.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

import pytest

from tests._helpers import build_plex_smoke_story, has_ffmpeg


@pytest.mark.media
@unittest.skipUnless(has_ffmpeg(), "ffmpeg/ffprobe not available")
class TestPlexExportSmoke(unittest.TestCase):
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
                result.returncode,
                0,
                f"per-scene render failed: {(result.stderr or '')[-300:]}",
            )

    def test_full_plex_export(self):
        from plex_export import export_plex_package
        from story_storage import STORIES_ROOT

        slug = "smoke-test-plex-export"
        story_dir = STORIES_ROOT / slug
        if story_dir.exists():
            shutil.rmtree(story_dir)
        story_dir.mkdir(parents=True)

        try:
            build_plex_smoke_story(story_dir, slug)
            self._build_per_scene_mp4(story_dir, slug)

            progress_stages: list[str] = []

            def _cb(stage, msg, pct):
                progress_stages.append(stage)

            result = export_plex_package(slug, progress_callback=_cb)

            self.assertTrue(result.mp4.exists(), f"MP4 missing: {result.mp4}")
            self.assertTrue(result.srt.exists(), f"SRT missing: {result.srt}")
            self.assertTrue(result.vtt.exists(), f"VTT missing: {result.vtt}")
            self.assertTrue(result.chapters_file.exists(), f"Chapters missing: {result.chapters_file}")
            self.assertIsNotNone(result.poster, "poster not detected")

            ffprobe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration:stream=codec_type,codec_name",
                    "-show_chapters",
                    "-of",
                    "default",
                    str(result.mp4),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(ffprobe.returncode, 0, ffprobe.stderr)

            output = ffprobe.stdout
            self.assertIn("codec_type=video", output)
            self.assertIn("codec_type=audio", output)
            self.assertGreaterEqual(output.count("[CHAPTER]"), 2, "expected at least 2 chapters")

            self.assertEqual(result.srt.stem, f"{slug}.en")
            self.assertEqual(result.vtt.stem, f"{slug}.en")

            srt_text = result.srt.read_text(encoding="utf-8")
            self.assertIn("Scene 01 line one.", srt_text)
            self.assertIn("Scene 02 line two.", srt_text)
            self.assertEqual(result.srt.parent, result.mp4.parent)
            self.assertEqual(result.srt.stem, result.mp4.stem + ".en")

            vtt_text = result.vtt.read_text(encoding="utf-8")
            self.assertTrue(vtt_text.startswith("WEBVTT"))
            self.assertIn("Scene 01 line one.", vtt_text)

            format_dur = None
            for line in output.splitlines():
                if line.startswith("duration="):
                    format_dur = float(line.split("=", 1)[1])
                    break
            self.assertIsNotNone(format_dur, "ffprobe did not return a duration")
            self.assertGreater(format_dur, 1.5)
            self.assertLess(format_dur, 4.0)

            expected_stages = {"discover", "subtitles", "chapters", "audio_mix", "finalize"}
            self.assertTrue(
                expected_stages.issubset(set(progress_stages)),
                f"progress callback missed stages: {expected_stages - set(progress_stages)}",
            )
        finally:
            shutil.rmtree(story_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
