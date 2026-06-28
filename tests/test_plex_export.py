"""Unit tests for ``plex_export`` — SRT, VTT, chapter metadata, and scene discovery.

These tests do not need ffmpeg — they only exercise the text-based
serialization helpers, so they run anywhere Python does.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from plex_export import (
    SceneChapter,
    _ffmpeg_escape_title,
    _plex_movie_folder_name,
    _sanitize_for_plex,
    _seconds_to_srt_time,
    _seconds_to_vtt_time,
    _resolve_year,
    build_chapters,
    chapters_to_ffmetadata,
    segments_to_srt,
    segments_to_vtt,
)
from tests._helpers import PROJECT_ROOT


class TestTimeHelpers(unittest.TestCase):
    def test_srt_zero(self):
        self.assertEqual(_seconds_to_srt_time(0), "00:00:00,000")

    def test_srt_seconds_only(self):
        self.assertEqual(_seconds_to_srt_time(7.5), "00:00:07,500")

    def test_srt_minutes(self):
        self.assertEqual(_seconds_to_srt_time(125.0), "00:02:05,000")

    def test_srt_hours(self):
        self.assertEqual(_seconds_to_srt_time(3723.250), "01:02:03,250")

    def test_srt_negative_clamps_to_zero(self):
        self.assertEqual(_seconds_to_srt_time(-1.0), "00:00:00,000")

    def test_vtt_uses_period_separator(self):
        self.assertEqual(_seconds_to_vtt_time(1.5), "00:00:01.500")


class TestSrtGeneration(unittest.TestCase):
    def test_simple_srt(self):
        segs = [
            {"text": "Hello world.", "start": 0.0, "end": 1.5},
            {"text": "Second line.", "start": 1.5, "end": 3.0},
        ]
        out = segments_to_srt(segs)
        self.assertIn("1\n00:00:00,000 --> 00:00:01,500\nHello world.\n", out)
        self.assertIn("2\n00:00:01,500 --> 00:00:03,000\nSecond line.\n", out)
        # SRT requires Windows line endings or LF? Plex accepts both; we emit LF.
        self.assertTrue(out.endswith("\n"))

    def test_srt_collapses_newlines(self):
        segs = [{"text": "Line one.\nLine two.", "start": 0.0, "end": 1.0}]
        out = segments_to_srt(segs)
        # Embedded newlines in a single cue should be flattened
        self.assertIn("Line one. Line two.", out)
        self.assertNotIn("Line one.\nLine two.", out)

    def test_srt_skips_empty_segments(self):
        segs = [
            {"text": "", "start": 0.0, "end": 1.0},
            {"text": "real", "start": 1.0, "end": 2.0},
        ]
        out = segments_to_srt(segs)
        # Only the second segment should be present
        self.assertIn("real", out)
        self.assertNotIn("00:00:00,000", out)


class TestVttGeneration(unittest.TestCase):
    def test_vtt_header(self):
        out = segments_to_vtt([{"text": "Hi", "start": 0, "end": 1}])
        self.assertTrue(out.startswith("WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHi\n"))

    def test_vtt_period_separator(self):
        out = segments_to_vtt([{"text": "x", "start": 1.5, "end": 2.5}])
        self.assertIn("00:00:01.500 --> 00:00:02.500", out)
        # Should NOT have a comma separator (that's SRT)
        self.assertNotIn("00:00:01,500", out)


class TestChapterMetadata(unittest.TestCase):
    def test_simple_chapter_block(self):
        chapters = [SceneChapter("First", 0.0, 5.0)]
        out = chapters_to_ffmetadata(chapters)
        self.assertTrue(out.startswith(";FFMETADATA1"))
        self.assertIn("[CHAPTER]", out)
        self.assertIn("TIMEBASE=1/1000", out)
        self.assertIn("START=0", out)
        self.assertIn("END=5000", out)
        self.assertIn("title=First", out)

    def test_multiple_chapters(self):
        chapters = [
            SceneChapter("Cold Open", 0.0, 5.0),
            SceneChapter("The Reveal", 5.5, 12.0),
            SceneChapter("Credits", 12.5, 14.0),
        ]
        out = chapters_to_ffmetadata(chapters)
        # All three title lines should appear
        self.assertIn("title=Cold Open", out)
        self.assertIn("title=The Reveal", out)
        self.assertIn("title=Credits", out)
        # 0.5s gaps encoded as expected
        self.assertIn("START=0", out)
        self.assertIn("START=5500", out)
        self.assertIn("START=12500", out)

    def test_escape_removes_unsafe_chars(self):
        # FFmpeg metadata rejects '=' and ';' in values
        self.assertEqual(_ffmpeg_escape_title("A=B"), "A-B")
        self.assertEqual(_ffmpeg_escape_title("A;B"), "A,B")
        # Leading '#' is a comment marker
        self.assertEqual(_ffmpeg_escape_title("# secret"), "secret")
        # Newlines collapse
        self.assertEqual(_ffmpeg_escape_title("a\nb"), "a b")
        # Empty after cleanup → placeholder
        self.assertEqual(_ffmpeg_escape_title(""), "Chapter")
        self.assertEqual(_ffmpeg_escape_title("==="), "Chapter")


class TestBuildChaptersFromScenes(unittest.TestCase):
    """``build_chapters`` should produce zero-length-free chapter records."""

    def test_chapter_offsets(self):
        # Build a fake scene asset list with plain dicts so we don't need to
        # touch the filesystem here.
        from plex_export import SceneAsset

        scenes = [
            SceneAsset(scene_key="01", title="First", narration="", subs=[],
                       audio=Path("/tmp/a.wav"), duration=10.0),
            SceneAsset(scene_key="02", title="Second", narration="", subs=[],
                       audio=Path("/tmp/b.wav"), duration=8.0),
            SceneAsset(scene_key="03", title="Third", narration="", subs=[],
                       audio=Path("/tmp/c.wav"), duration=5.0),
        ]
        chapters = build_chapters(scenes, gap_between_scenes=0.5)
        self.assertEqual([c.title for c in chapters], ["First", "Second", "Third"])
        self.assertAlmostEqual(chapters[0].start, 0.0)
        self.assertAlmostEqual(chapters[0].end, 10.0)
        self.assertAlmostEqual(chapters[1].start, 10.5)
        self.assertAlmostEqual(chapters[1].end, 18.5)
        self.assertAlmostEqual(chapters[2].start, 19.0)
        self.assertAlmostEqual(chapters[2].end, 24.0)

    def test_chapter_skips_zero_duration(self):
        from plex_export import SceneAsset

        scenes = [
            SceneAsset(scene_key="01", title="Alive", narration="", subs=[],
                       audio=Path("/tmp/a.wav"), duration=10.0),
            SceneAsset(scene_key="02", title="Dead", narration="", subs=[],
                       audio=None, duration=0.0),
            SceneAsset(scene_key="03", title="Alive2", narration="", subs=[],
                       audio=Path("/tmp/b.wav"), duration=4.0),
        ]
        chapters = build_chapters(scenes)
        self.assertEqual([c.title for c in chapters], ["Alive", "Alive2"])

    def test_chapter_fills_missing_title(self):
        from plex_export import SceneAsset

        scenes = [
            SceneAsset(scene_key="07", title="", narration="", subs=[],
                       audio=Path("/tmp/a.wav"), duration=2.0),
        ]
        chapters = build_chapters(scenes)
        self.assertEqual(chapters[0].title, "Scene 07")


class TestChapterEdgeCases(unittest.TestCase):
    def test_chapter_metadata_round_trip_via_regex(self):
        """Spot-check that the produced ffmetadata can be parsed by a simple regex,
        so we know FFmpeg's parser will accept it too."""
        chapters = [
            SceneChapter("Chapter 1", 0.0, 5.0),
            SceneChapter("Chapter 2", 5.5, 12.0),
        ]
        out = chapters_to_ffmetadata(chapters)
        # Each chapter block: [CHAPTER]\nTIMEBASE=...\nSTART=...\nEND=...\ntitle=...
        chapter_blocks = re.findall(
            r"\[CHAPTER\]\nTIMEBASE=1/1000\nSTART=(\d+)\nEND=(\d+)\ntitle=([^\n]+)",
            out,
        )
        self.assertEqual(len(chapter_blocks), 2)
        starts, ends, titles = zip(*chapter_blocks)
        self.assertEqual(list(map(int, starts)), [0, 5500])
        self.assertEqual(list(map(int, ends)), [5000, 12000])
        self.assertEqual(list(titles), ["Chapter 1", "Chapter 2"])


class TestPlexFilenameSanitize(unittest.TestCase):
    """Cover the Windows + Plex blacklist + whitespace collapse rules."""

    def test_plain_title_passes_through(self):
        self.assertEqual(
            _sanitize_for_plex("Fragile Truce of Bone and Spirit"),
            "Fragile Truce of Bone and Spirit",
        )

    def test_strips_invalid_chars(self):
        self.assertEqual(
            _sanitize_for_plex('What: "Iron" / Pursuit?'),
            "What Iron Pursuit",
        )

    def test_collapses_whitespace(self):
        self.assertEqual(
            _sanitize_for_plex("Foo   bar\t\tbaz"),
            "Foo bar baz",
        )

    def test_strips_trailing_dots_and_spaces(self):
        # Windows refuses trailing dots/spaces in filenames.
        self.assertEqual(
            _sanitize_for_plex("Title...  "),
            "Title",
        )

    def test_falls_back_on_garbage(self):
        # Only punctuation → use the fallback instead of an empty string.
        self.assertEqual(_sanitize_for_plex("***"), "Untitled")
        self.assertEqual(_sanitize_for_plex(""), "Untitled")
        self.assertEqual(_sanitize_for_plex("   "), "Untitled")

    def test_strips_control_chars(self):
        self.assertEqual(
            _sanitize_for_plex("Title\x00\x1f with \nnewline"),
            "Title with newline",
        )

    def test_caps_length(self):
        long = "A" * 500
        out = _sanitize_for_plex(long)
        self.assertLessEqual(len(out), 200)


class TestPlexFolderName(unittest.TestCase):
    def test_title_with_year(self):
        self.assertEqual(
            _plex_movie_folder_name({"title": "Iron Pursuit", "year": 2024}),
            "Iron Pursuit (2024)",
        )

    def test_falls_back_to_current_year(self):
        import datetime
        year = datetime.datetime.now().year
        self.assertEqual(
            _plex_movie_folder_name({"title": "Iron Pursuit"}),
            f"Iron Pursuit ({year})",
        )

    def test_strips_invalid_title_chars(self):
        self.assertEqual(
            _plex_movie_folder_name({"title": "What: Iron? / Pursuit", "year": 2025}),
            "What Iron Pursuit (2025)",
        )

    def test_rejects_garbage_year(self):
        import datetime
        year = datetime.datetime.now().year
        # Bogus year strings should fall back to the current year
        self.assertEqual(
            _plex_movie_folder_name({"title": "Foo", "year": "not-a-year"}),
            f"Foo ({year})",
        )


class TestResolveYear(unittest.TestCase):
    def test_int_year(self):
        self.assertEqual(_resolve_year({"year": 2024}), 2024)

    def test_numeric_string_year(self):
        self.assertEqual(_resolve_year({"year": "2024"}), 2024)

    def test_missing_year_falls_back_to_current(self):
        import datetime
        self.assertEqual(_resolve_year({}), datetime.datetime.now().year)
        self.assertEqual(_resolve_year({"year": "junk"}), datetime.datetime.now().year)


if __name__ == "__main__":
    unittest.main()
