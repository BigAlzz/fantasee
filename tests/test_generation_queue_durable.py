import asyncio

from fantasee_server.models import GenerateRequest


def test_generation_queue_persists_parent_and_child_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))

    from fantasee_server.api import generation
    from fantasee_server.production_runtime import start_task

    queue_id = "queue-test"
    item = GenerateRequest(story_concept="A small durable test story")
    old_tasks = dict(generation._generation_tasks)
    generation._generation_tasks.clear()
    generation._generation_tasks[queue_id] = {
        "id": queue_id,
        "kind": "queue",
        "status": "queued",
        "progress": 0,
    }
    start_task(queue_id, story_id="queue", kind="generation_queue")

    async def fake_run_generation(task_id, _request, _progress=None):
        generation._generation_tasks[task_id]["status"] = "done"
        generation._generation_tasks[task_id]["message"] = "Complete"

    async def run():
        original = generation._run_generation
        generation._run_generation = fake_run_generation
        try:
            await generation._run_queue(queue_id, [item])
        finally:
            generation._run_generation = original

    try:
        asyncio.run(run())
    finally:
        generation._generation_tasks.clear()
        generation._generation_tasks.update(old_tasks)

    from fantasee_server.production_runtime import get_persisted_task

    persisted = get_persisted_task(queue_id)
    assert persisted["run"]["status"] == "succeeded"
    assert persisted["jobs"][0]["id"] == f"{queue_id}-00"
    assert persisted["jobs"][0]["status"] == "succeeded"
