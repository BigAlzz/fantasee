from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

from tests._helpers import temp_dir


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


class TestStoryDeleteTaskEndpoint(unittest.TestCase):
    def test_confirmed_delete_returns_before_slow_delete_finishes(self):
        asyncio.run(self._run_confirmed_delete_returns_task())

    async def _run_confirmed_delete_returns_task(self):
        import delete_story
        import server

        with temp_dir() as tmp:
            story_id = "slow-delete"
            story_dir = tmp / story_id
            story_dir.mkdir()
            (story_dir / f"{story_id}.json").write_text("{}", encoding="utf-8")

            fake_ws = FakeWebSocket()
            old_tasks = dict(server._generation_tasks)
            old_clients = list(server._websocket_clients)
            # _stories_cache lives in fantasee_server.state; reach it via the
            # module so the background task's updates are observable here.
            from fantasee_server import state as fs_state
            old_cache = fs_state._stories_cache
            server._generation_tasks.clear()
            server._websocket_clients[:] = [fake_ws]
            fs_state._stories_cache = [{"id": story_id, "scenes": []}]

            def slow_delete(path, backup=False, progress_callback=None):
                time.sleep(0.2)
                report = {
                    "story_id": path.name,
                    "existed": True,
                    "backup_path": None,
                    "files_deleted": 1,
                    "bytes_freed": 2,
                    "errors": [],
                }
                if progress_callback:
                    progress_callback({
                        "stage": "delete",
                        "message": "Deleting 1 file(s)...",
                        "progress": 0.65,
                        "report": report,
                    })
                return report

            try:
                with patch("fantasee_server.api.delete.generated_story_dir", return_value=story_dir), \
                     patch("fantasee_server.paths.load_stories", return_value=[]), \
                     patch.object(delete_story, "delete_story_with_progress", side_effect=slow_delete):
                    started = time.perf_counter()
                    response = await server.delete_story_endpoint(
                        story_id,
                        {"confirm": True, "backup": False},
                    )
                    elapsed = time.perf_counter() - started

                    self.assertLess(elapsed, 0.1)
                    self.assertEqual(response["status"], "running")
                    self.assertEqual(response["story_id"], story_id)
                    self.assertTrue(response["task_id"].startswith("delete-"))

                    task_id = response["task_id"]
                    for _ in range(60):
                        if server._generation_tasks[task_id]["status"] == "done":
                            break
                        await asyncio.sleep(0.01)

                    task = server._generation_tasks[task_id]
                    self.assertEqual(task["kind"], "delete_story")
                    self.assertEqual(task["status"], "done")
                    self.assertEqual(task["result"]["files_deleted"], 1)
                    self.assertEqual(fs_state._stories_cache, [])

                    await asyncio.sleep(0.02)
                    task_updates = [
                        m for m in fake_ws.messages
                        if m.get("type") == "task_update" and m.get("task_id") == task_id
                    ]
                    self.assertTrue(task_updates)
                    self.assertTrue(any(m.get("kind") == "delete_story" for m in task_updates))
                    self.assertTrue(any(m.get("status") == "done" for m in task_updates))
                    self.assertTrue(any(m.get("type") == "story_deleted" for m in fake_ws.messages))
            finally:
                server._generation_tasks.clear()
                server._generation_tasks.update(old_tasks)
                server._websocket_clients[:] = old_clients
                fs_state._stories_cache = old_cache


if __name__ == "__main__":
    unittest.main()
