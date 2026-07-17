import asyncio
from unittest.mock import patch

from fantasee_server.production_runtime import start_task


def test_library_maintenance_uses_durable_worker_job(tmp_path, monkeypatch):
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))

    from fantasee_server import library

    old_tasks = dict(library._generation_tasks)
    old_running = library._library_maintenance_running
    library._generation_tasks.clear()
    library._generation_tasks["maintenance-1"] = {
        "id": "maintenance-1",
        "kind": "library_maintenance",
        "status": "running",
        "progress": 0,
    }
    start_task("maintenance-1", story_id="library", kind="library_maintenance")

    def fake_complete(story_id, progress):
        progress("render", f"Rendering {story_id}", 0.7)
        return {"completion": {"complete": True}}

    async def run():
        with patch.object(library, "_complete_story_for_library", side_effect=fake_complete), \
             patch.object(library._paths, "load_stories", return_value=[]):
            await library._run_library_maintenance_queue(
                "maintenance-1", [{"id": "story-1", "title": "Story 1"}]
            )

    try:
        asyncio.run(run())
    finally:
        library._generation_tasks.clear()
        library._generation_tasks.update(old_tasks)
        library._library_maintenance_running = old_running

    from fantasee_server.production_runtime import get_persisted_task

    persisted = get_persisted_task("maintenance-1")
    assert persisted["jobs"][0]["job_type"] == "library.complete"
    assert persisted["jobs"][0]["status"] == "succeeded"
