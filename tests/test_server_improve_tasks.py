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


class TestStoryImproveTaskEndpoints(unittest.TestCase):
    def test_improve_returns_task_and_reports_progress_result(self):
        asyncio.run(self._run_improve_returns_task())

    async def _run_improve_returns_task(self):
        import server

        with temp_dir() as tmp:
            story_id = "task-improve"
            story_dir = tmp / story_id
            story_dir.mkdir()
            (story_dir / f"{story_id}.json").write_text(
                '{"id":"task-improve","scenes":[]}',
                encoding="utf-8",
            )

            fake_ws = FakeWebSocket()
            old_tasks = dict(server._generation_tasks)
            old_clients = list(server._websocket_clients)
            from fantasee_server import state as fs_state
            old_cache = fs_state._stories_cache
            server._generation_tasks.clear()
            server._websocket_clients[:] = [fake_ws]
            fs_state._stories_cache = [{"id": story_id, "scenes": []}]

            def fake_worker(worker_story_id, body, progress=None):
                self.assertEqual(worker_story_id, story_id)
                self.assertEqual(body["max_scenes"], 2)
                time.sleep(0.15)
                progress("critic", "critic running", 0.2)
                progress("render", "render running", 0.8)
                return {
                    "status": "ok",
                    "review_stars": 3,
                    "improved_scenes": [{"scene_idx": 0, "title": "One"}],
                    "render_ok": True,
                }

            try:
                with patch("fantasee_server.api.actions.generated_story_dir", return_value=story_dir), \
                     patch("fantasee_server.paths.load_stories", return_value=[{"id": story_id}]), \
                     patch("fantasee_server.api.actions._run_auto_improve_sync", side_effect=fake_worker):
                    started = time.perf_counter()
                    response = await server.auto_improve(story_id, {"max_scenes": 2})
                    elapsed = time.perf_counter() - started

                    self.assertLess(elapsed, 0.1)
                    self.assertEqual(response["status"], "running")
                    self.assertEqual(response["story_id"], story_id)
                    self.assertTrue(response["task_id"].startswith("improve-"))

                    task_id = response["task_id"]
                    for _ in range(80):
                        if server._generation_tasks[task_id]["status"] == "done":
                            break
                        await asyncio.sleep(0.01)

                    task = server._generation_tasks[task_id]
                    self.assertEqual(task["kind"], "improve")
                    self.assertEqual(task["status"], "done")
                    self.assertEqual(task["progress"], 1.0)
                    self.assertEqual(task["result"]["improved_scenes"][0]["title"], "One")

                    await asyncio.sleep(0.02)
                    updates = [
                        m for m in fake_ws.messages
                        if m.get("type") == "task_update" and m.get("task_id") == task_id
                    ]
                    self.assertTrue(any(m.get("stage") == "queued" for m in updates))
                    self.assertTrue(any(m.get("stage") == "critic" for m in updates))
                    self.assertTrue(any(m.get("stage") == "render" for m in updates))
                    self.assertTrue(any(m.get("status") == "done" for m in updates))
                    done = [m for m in updates if m.get("status") == "done"][-1]
                    self.assertEqual(done["result"]["render_ok"], True)
            finally:
                server._generation_tasks.clear()
                server._generation_tasks.update(old_tasks)
                server._websocket_clients[:] = old_clients
                fs_state._stories_cache = old_cache

    def test_improve_loop_returns_task_and_reports_progress_result(self):
        asyncio.run(self._run_improve_loop_returns_task())

    async def _run_improve_loop_returns_task(self):
        import server

        with temp_dir() as tmp:
            story_id = "task-improve-loop"
            story_dir = tmp / story_id
            story_dir.mkdir()
            (story_dir / f"{story_id}.json").write_text(
                '{"id":"task-improve-loop","scenes":[]}',
                encoding="utf-8",
            )

            fake_ws = FakeWebSocket()
            old_tasks = dict(server._generation_tasks)
            old_clients = list(server._websocket_clients)
            from fantasee_server import state as fs_state
            old_cache = fs_state._stories_cache
            server._generation_tasks.clear()
            server._websocket_clients[:] = [fake_ws]
            fs_state._stories_cache = [{"id": story_id, "scenes": []}]

            def fake_worker(worker_story_id, body, progress=None):
                self.assertEqual(worker_story_id, story_id)
                self.assertEqual(body["max_rounds"], 2)
                time.sleep(0.15)
                progress("critic", "round 1 critic", 0.1)
                progress("improve", "round 1 improve", 0.5)
                return {
                    "status": "target_reached",
                    "rounds_completed": 1,
                    "final_stars": 4,
                    "final_rating": 8.2,
                    "history": [{"round": 1, "stars": 4, "rating": 8.2, "improved": 0}],
                }

            try:
                with patch("fantasee_server.api.actions.generated_story_dir", return_value=story_dir), \
                     patch("fantasee_server.paths.load_stories", return_value=[{"id": story_id}]), \
                     patch("fantasee_server.api.actions._run_improve_loop_sync", side_effect=fake_worker):
                    started = time.perf_counter()
                    response = await server.improve_loop(story_id, {"max_rounds": 2})
                    elapsed = time.perf_counter() - started

                    self.assertLess(elapsed, 0.1)
                    self.assertEqual(response["status"], "running")
                    self.assertEqual(response["story_id"], story_id)
                    self.assertTrue(response["task_id"].startswith("improve-loop-"))

                    task_id = response["task_id"]
                    for _ in range(80):
                        if server._generation_tasks[task_id]["status"] == "done":
                            break
                        await asyncio.sleep(0.01)

                    task = server._generation_tasks[task_id]
                    self.assertEqual(task["kind"], "improve_loop")
                    self.assertEqual(task["status"], "done")
                    self.assertEqual(task["result"]["status"], "target_reached")
                    self.assertEqual(task["result"]["final_stars"], 4)

                    await asyncio.sleep(0.02)
                    updates = [
                        m for m in fake_ws.messages
                        if m.get("type") == "task_update" and m.get("task_id") == task_id
                    ]
                    self.assertTrue(any(m.get("stage") == "queued" for m in updates))
                    self.assertTrue(any(m.get("stage") == "critic" for m in updates))
                    self.assertTrue(any(m.get("stage") == "improve" for m in updates))
                    self.assertTrue(any(m.get("status") == "done" for m in updates))
                    done = [m for m in updates if m.get("status") == "done"][-1]
                    self.assertEqual(done["result"]["final_rating"], 8.2)
            finally:
                server._generation_tasks.clear()
                server._generation_tasks.update(old_tasks)
                server._websocket_clients[:] = old_clients
                fs_state._stories_cache = old_cache


if __name__ == "__main__":
    unittest.main()
