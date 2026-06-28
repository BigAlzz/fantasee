"""Tests for story chrome art selection."""

from __future__ import annotations

import unittest


class TestStoryDisplayArt(unittest.TestCase):
    def test_first_scene_art_url_prefers_real_scene_images(self):
        from server import _first_scene_art_url

        scenes = [
            {"scene": "01", "image_filenames": []},
            {"scene": "02", "image_filenames": ["story_s02_00001_.png"]},
            {"scene": "03", "image_filenames": ["story_s03_00001_.png"]},
        ]

        self.assertEqual(
            _first_scene_art_url("story", scenes),
            "/generated/story/story_s02_00001_.png",
        )

    def test_first_scene_art_url_returns_none_when_no_art_exists(self):
        from server import _first_scene_art_url

        scenes = [
            {"scene": "01", "image_filenames": []},
            {"scene": "02"},
        ]

        self.assertIsNone(_first_scene_art_url("story", scenes))


if __name__ == "__main__":
    unittest.main()
