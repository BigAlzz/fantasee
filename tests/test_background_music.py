"""Unit tests for ``background_music`` — auto-selection, payload, and metadata."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from background_music import (
    BackgroundTrack,
    DEFAULT_BACKGROUND_VOLUME,
    background_audio_payload,
    build_track_index,
    list_background_tracks,
    select_background_track,
    _match_score,
)
from tests._helpers import PROJECT_ROOT, temp_dir


class TestBackgroundListing(unittest.TestCase):
    def test_lists_real_background_tracks(self):
        """A configured background folder is indexed without bundled media."""
        # Operator-selected tracks are runtime data and are intentionally
        # ignored by git, so the clean-checkout test supplies a tiny fixture.
        with temp_dir() as tmp:
            (tmp / "cinematic-atmosphere-fixture.mp3").write_bytes(b"")
            tracks = list_background_tracks(tmp)
        self.assertGreater(len(tracks), 0, "background fixture was not indexed")
        for t in tracks:
            self.assertTrue(t.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".flac"})

    def test_listing_handles_missing_dir(self):
        """If the dir is missing we return [] rather than raising."""
        with temp_dir() as tmp:
            self.assertEqual(list_background_tracks(tmp / "nope"), [])

    def test_default_index_uses_operator_selected_folder(self):
        """The app can scan a private local music folder without bundling it."""
        with temp_dir() as tmp:
            track = tmp / "cinematic-atmosphere-private.mp3"
            track.write_bytes(b"")
            with patch.dict(os.environ, {"FANTASEE_BACKGROUND_DIR": str(tmp)}):
                indexed = build_track_index()
        self.assertEqual([item.filename for item in indexed], [track.name])


class TestToneScoring(unittest.TestCase):
    """Tone selection is a pure function of the filename — easy to test."""

    def test_dark_matches_atmosphere_track(self):
        # Build a synthetic track list so the test is deterministic and
        # doesn't depend on the shipped filenames.
        tracks = [
            BackgroundTrack(filename="cinematic-atmosphere-1.mp3", path="/x", duration_seconds=10, tags=[]),
            BackgroundTrack(filename="light-and-sweet-1.mp3", path="/x", duration_seconds=10, tags=[]),
            BackgroundTrack(filename="light-and-reflective-1.mp3", path="/x", duration_seconds=10, tags=[]),
        ]
        # Dark → atmosphere
        self.assertGreater(_match_score(tracks[0], "dark"), 0)
        # The same track should match both dark and epic (both prefer atmosphere)
        self.assertEqual(_match_score(tracks[0], "dark"), _match_score(tracks[0], "epic"))

    def test_hopeful_matches_sweet(self):
        sweet = BackgroundTrack(filename="light-and-sweet-1.mp3", path="/x", duration_seconds=10, tags=[])
        self.assertGreater(_match_score(sweet, "hopeful"), 0)
        # But hopeful should NOT match atmosphere
        atmosphere = BackgroundTrack(filename="cinematic-atmosphere-1.mp3", path="/x", duration_seconds=10, tags=[])
        self.assertEqual(_match_score(atmosphere, "hopeful"), 0)

    def test_unknown_tone_does_not_match(self):
        no_match = BackgroundTrack(filename="totally-unrelated-filename.mp3", path="/x", duration_seconds=10, tags=[])
        self.assertEqual(_match_score(no_match, "mysterious"), 0)
        self.assertEqual(_match_score(no_match, "epic"), 0)


class TestSelectBackgroundTrack(unittest.TestCase):
    def test_selects_atmosphere_for_dark_tone(self):
        tracks = [
            BackgroundTrack(filename="light-and-sweet-1.mp3", path="/x", duration_seconds=10, tags=[]),
            BackgroundTrack(filename="cinematic-atmosphere-1.mp3", path="/x", duration_seconds=10, tags=[]),
        ]
        pick = select_background_track(tone="dark", tracks=tracks)
        self.assertIsNotNone(pick)
        self.assertIn("cinematic-atmosphere", pick.filename)

    def test_selects_sweet_for_hopeful(self):
        tracks = [
            BackgroundTrack(filename="cinematic-atmosphere-1.mp3", path="/x", duration_seconds=10, tags=[]),
            BackgroundTrack(filename="light-and-sweet-1.mp3", path="/x", duration_seconds=10, tags=[]),
        ]
        pick = select_background_track(tone="hopeful", tracks=tracks)
        self.assertIsNotNone(pick)
        self.assertIn("light-and-sweet", pick.filename)

    def test_no_tracks_returns_none(self):
        self.assertIsNone(select_background_track(tone="dark", tracks=[]))

    def test_unknown_tone_falls_back_to_neutral(self):
        """When no track matches the tone, fall back to reflective/sweet/atmosphere."""
        tracks = [
            BackgroundTrack(filename="random-noise-1.mp3", path="/x", duration_seconds=10, tags=[]),
            BackgroundTrack(filename="light-and-reflective-1.mp3", path="/x", duration_seconds=10, tags=[]),
        ]
        pick = select_background_track(tone="absurdly-obscure", tracks=tracks)
        self.assertIsNotNone(pick)
        # The neutral fallback should be reflective
        self.assertIn("light-and-reflective", pick.filename)


class TestBackgroundAudioPayload(unittest.TestCase):
    """The payload is what gets written to the story manifest."""

    def test_payload_has_required_keys(self):
        with temp_dir() as tmp:
            # Use a tiny synthetic directory with one track
            (tmp / "cinematic-atmosphere-1.mp3").write_bytes(b"")
            payload = background_audio_payload(tone="dark", background_dir=tmp)
        self.assertIn("background_audio", payload)
        self.assertIn("background_volume", payload)
        self.assertIn("background_muted", payload)
        # Defaults
        self.assertEqual(payload["background_volume"], DEFAULT_BACKGROUND_VOLUME)
        self.assertFalse(payload["background_muted"])
        # Selected track should match the tone
        self.assertIn("cinematic-atmosphere", payload["background_audio"])

    def test_payload_serializes_to_json(self):
        """Manifest writers call ``json.dumps`` — make sure the payload is JSON-safe."""
        with temp_dir() as tmp:
            (tmp / "cinematic-atmosphere-1.mp3").write_bytes(b"")
            payload = background_audio_payload(tone="epic", background_dir=tmp)
        # Must not raise
        encoded = json.dumps(payload)
        self.assertIn("background_volume", encoded)


if __name__ == "__main__":
    unittest.main()
