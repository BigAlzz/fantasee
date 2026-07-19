import asyncio
from unittest.mock import patch

from fantasee_server.production_runtime import enqueue_task_job, start_task


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


def test_library_recovery_holds_maintenance_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))
    monkeypatch.setenv("FANTASEE_GENERATION_RECOVERY_DELAY", "0")

    from fantasee_server import library

    old_running = library._library_maintenance_running
    start_task("maintenance-1", story_id="library", kind="library_maintenance")
    enqueue_task_job(
        "maintenance-1",
        job_id="maintenance-1-00",
        job_type="library.complete",
        payload={"story_id": "story-1"},
    )

    async def no_sleep(_delay):
        return None

    class FailingWorker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def run_once(self, _handler):
            assert library._library_maintenance_running is True
            raise RuntimeError("stop after lock assertion")

    monkeypatch.setattr(library.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(library, "ProductionWorker", FailingWorker)

    try:
        with patch.object(library, "_complete_story_for_library"):
            try:
                asyncio.run(library.recover_library_jobs())
            except RuntimeError as exc:
                assert str(exc) == "stop after lock assertion"
            else:
                raise AssertionError("recovery should have raised from the failing worker")
        assert library._library_maintenance_running is False
    finally:
        library._library_maintenance_running = old_running
