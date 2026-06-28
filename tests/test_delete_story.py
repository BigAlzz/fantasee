from __future__ import annotations

import unittest

from tests._helpers import temp_dir


class TestDeleteStoryProgress(unittest.TestCase):
    def test_delete_with_backup_reuses_report_and_emits_progress(self):
        import delete_story

        with temp_dir() as tmp:
            story_dir = tmp / "story-to-delete"
            nested = story_dir / "final"
            nested.mkdir(parents=True)
            (story_dir / "story-to-delete.json").write_text("{}", encoding="utf-8")
            (nested / "story-to-delete_full.mp4").write_bytes(b"video")

            original_trash = delete_story.TRASH_DIR
            delete_story.TRASH_DIR = tmp / ".trash"
            events = []
            try:
                report = delete_story.delete_story_with_progress(
                    story_dir,
                    backup=True,
                    progress_callback=events.append,
                )
            finally:
                delete_story.TRASH_DIR = original_trash

            self.assertFalse(story_dir.exists())
            self.assertEqual(report["story_id"], "story-to-delete")
            self.assertEqual(report["files_deleted"], 2)
            self.assertEqual(report["bytes_freed"], 7)
            self.assertEqual(report["errors"], [])
            self.assertIsNotNone(report["backup_path"])
            backup_dir = tmp / ".trash"
            self.assertTrue(backup_dir.exists())

            stages = [event["stage"] for event in events]
            self.assertIn("discover", stages)
            self.assertIn("backup", stages)
            self.assertIn("delete", stages)
            self.assertEqual(stages[-1], "complete")
            self.assertEqual(events[-1]["progress"], 1.0)
            self.assertEqual(events[-1]["report"]["files_deleted"], 2)


if __name__ == "__main__":
    unittest.main()
