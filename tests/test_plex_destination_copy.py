"""End-to-end smoke test for the Plex destination copy.

Creates a temp story + temp destination tree, runs ``_copy_to_plex_destination``
directly (no ffmpeg needed), and verifies the layout matches what Plex expects.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plex_export import _copy_to_plex_destination


class TestPlexDestinationCopy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fantasee_plex_test_")
        self.plex_dir = Path(self.tmp) / "plex"
        self.plex_dir.mkdir()
        # Drop a fake MP4, SRT, VTT, poster PNG, and chapters file
        (self.plex_dir / "fragile-truce-of-bone-and.mp4").write_bytes(b"FAKE_MP4")
        (self.plex_dir / "fragile-truce-of-bone-and.en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
        (self.plex_dir / "fragile-truce-of-bone-and.en.vtt").write_text("WEBVTT\n")
        (self.plex_dir / "fragile-truce-of-bone-and-poster.png").write_bytes(b"\x89PNG")
        (self.plex_dir / "chapters.ffmeta").write_text(";FFMETADATA1\n")

        self.dest_root = Path(self.tmp) / "Plex"
        self.manifest = {
            "id": "fragile-truce-of-bone-and",
            "title": "Fragile Truce of Bone and Spirit",
            "year": 2026,
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_movies_subfolder(self):
        out = _copy_to_plex_destination(
            self.plex_dir, self.manifest, "fragile-truce-of-bone-and",
            destination_root=str(self.dest_root),
        )
        self.assertEqual(out["root"], str(self.dest_root).replace("\\", "/"))
        expected_dir = self.dest_root / "Movies" / "Fragile Truce of Bone and Spirit (2026)"
        self.assertTrue(expected_dir.is_dir(), f"missing {expected_dir}")
        self.assertEqual(out["dir"], str(expected_dir).replace("\\", "/"))

    def test_renames_files_to_plex_convention(self):
        out = _copy_to_plex_destination(
            self.plex_dir, self.manifest, "fragile-truce-of-bone-and",
            destination_root=str(self.dest_root),
        )
        target = Path(out["dir"])
        # All five files should land here, with the title-cased stem
        names = sorted(p.name for p in target.iterdir())
        self.assertIn("Fragile Truce of Bone and Spirit (2026).mp4", names)
        self.assertIn("Fragile Truce of Bone and Spirit (2026).en.srt", names)
        self.assertIn("Fragile Truce of Bone and Spirit (2026).en.vtt", names)
        self.assertIn("Fragile Truce of Bone and Spirit (2026)-poster.png", names)
        self.assertIn("chapters.ffmeta", names)
        self.assertEqual(len(out["files"]), 5)

    def test_creates_dest_root_if_missing(self):
        new_root = Path(self.tmp) / "new_plex_root"
        # Don't pre-create new_root — the helper should make it.
        out = _copy_to_plex_destination(
            self.plex_dir, self.manifest, "fragile-truce-of-bone-and",
            destination_root=str(new_root),
        )
        self.assertTrue((new_root / "Movies" / "Fragile Truce of Bone and Spirit (2026)").is_dir())

    def test_handles_invalid_title_chars(self):
        # Story with nasty title — should still produce a valid folder name
        manifest = {
            "id": "weird",
            "title": 'What: "Iron" / Pursuit?',
            "year": 2025,
        }
        out = _copy_to_plex_destination(
            self.plex_dir, manifest, "weird",
            destination_root=str(self.dest_root),
        )
        self.assertIn("What Iron Pursuit (2025)", out["dir"])

    def test_missing_year_falls_back(self):
        manifest = {"id": "foo", "title": "Foo Bar"}
        import datetime
        year = datetime.datetime.now().year
        out = _copy_to_plex_destination(
            self.plex_dir, manifest, "foo",
            destination_root=str(self.dest_root),
        )
        self.assertIn(f"Foo Bar ({year})", out["dir"])


if __name__ == "__main__":
    unittest.main()
