import asyncio

from fantasee_server.models import GenerateRequest
from fantasee_server.production_runtime import enqueue_task_job, start_task


def test_recovery_worker_resumes_queued_generation_job(tmp_path, monkeypatch):
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))
    monkeypatch.setenv("FANTASEE_GENERATION_RECOVERY_DELAY", "0")

    from fantasee_server.api import generation

    old_tasks = dict(generation._generation_tasks)
    generation._generation_tasks.clear()
    start_task("queue-1", story_id="queue", kind="generation_queue")
    start_task("queue-1-00", story_id="story-1", kind="generate")
    enqueue_task_job(
        "queue-1",
        job_id="queue-1-00",
        job_type="story.generate",
        payload=GenerateRequest(story_concept="A recovered story").model_dump(),
    )

    async def fake_run_generation(task_id, _request, _progress=None):
        generation._generation_tasks[task_id]["status"] = "done"
        generation._generation_tasks[task_id]["message"] = "Recovered complete"

    async def run():
        original = generation._run_generation
        generation._run_generation = fake_run_generation
        try:
            await generation.recover_generation_jobs()
        finally:
            generation._run_generation = original

    try:
        asyncio.run(run())
    finally:
        generation._generation_tasks.clear()
        generation._generation_tasks.update(old_tasks)

    from fantasee_server.production_runtime import get_persisted_task

    persisted = get_persisted_task("queue-1")
    assert persisted["run"]["status"] == "succeeded"
    assert persisted["jobs"][0]["status"] == "succeeded"
