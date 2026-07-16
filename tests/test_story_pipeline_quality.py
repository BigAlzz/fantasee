from __future__ import annotations

import unittest
from pathlib import Path

from story_pipeline import load_pipeline, initialize_pipeline, sync_from_completion, update_stage
from story_quality import review_scene_outline
from tests._helpers import temp_dir


def _narration() -> str:
    return " ".join(
        "The path narrows beneath the fading light, and every careful step reveals another piece of the danger ahead."
        for _ in range(4)
    )


class TestStoryQuality(unittest.TestCase):
    def test_canonical_style_file_is_loaded_by_generation_prompt(self):
        from generate_story import STORY_OUTLINE_SYSTEM, load_story_style_prompt

        style = load_story_style_prompt()
        self.assertIn('"Finn" Isekai Realism', style)
        self.assertIn("MANDATORY NARRATION STYLE OVERRIDE", STORY_OUTLINE_SYSTEM)
        self.assertIn("Dialogue tags are forbidden", STORY_OUTLINE_SYSTEM)

    def test_review_accepts_complete_varied_outline(self):
        scenes = []
        shots = ["wide shot", "medium shot", "low angle", "over-the-shoulder shot"]
        for index, shot in enumerate(shots, start=1):
            scenes.append({
                "title": f"Beat {index}",
                "prompt": f"{shot}, Kael crosses the moonlit ruins with a lantern and a clear view of the distant gate.",
                "narrative": "Kael reaches the next landmark and discovers a new danger in the ruins.",
                "narration": _narration(),
            })

        report = review_scene_outline(
            scenes, 4, characters="Kael - a lantern keeper", tone="dramatic",
        )
        self.assertTrue(report["valid"])
        self.assertGreaterEqual(report["score"], 0.65)
        self.assertEqual(len(report["shot_types"]), 4)

    def test_review_blocks_missing_required_scene_fields(self):
        report = review_scene_outline([{"title": "Only a title"}], 1)
        self.assertFalse(report["valid"])
        self.assertEqual(report["blocking_issues"], 1)

    def test_review_flags_style_breaks(self):
        report = review_scene_outline([{
            "title": "Bad Voice",
            "prompt": "wide shot, a muddy road under cold rain.",
            "narrative": "She walks toward the village.",
            "narration": "Sadly, she felt afraid. Suddenly he said the road was dangerous. I knew it.",
        }], 1)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertTrue({"editorializing", "internal_feeling", "dialogue_tag", "banned_transition", "first_person"} <= codes)


class TestStoryPipeline(unittest.TestCase):
    def test_checkpoints_resume_and_sync_from_completion(self):
        with temp_dir() as tmp:
            story_dir = Path(tmp) / "checkpoint-story"
            state = initialize_pipeline(story_dir, "checkpoint-story")
            self.assertEqual(state["current_stage"], "story")
            update_stage(story_dir, "story", "complete", message="Metadata ready")
            update_stage(story_dir, "outline", "complete", message="Outline ready")

            state = sync_from_completion(story_dir, {
                "complete": False,
                "missing": ["image", "audio", "subtitles", "scene_video", "full_video", "plex"],
            })
            self.assertEqual(state["status"], "running")
            self.assertEqual(state["current_stage"], "images")
            self.assertEqual(load_pipeline(story_dir)["stages"]["outline"]["status"], "complete")

            state = sync_from_completion(story_dir, {"complete": True, "missing": []})
            self.assertEqual(state["status"], "complete")
            self.assertEqual(state["current_stage"], "complete")


if __name__ == "__main__":
    unittest.main()
