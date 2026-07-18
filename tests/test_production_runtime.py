from fantasee_server.production_runtime import (
    enqueue_task_job,
    finish_task,
    get_persisted_task,
    list_persisted_tasks,
    start_task,
    update_task,
)


def test_task_progress_is_persisted_for_restart_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))

    start_task("task-1", story_id="story-1", kind="library_maintenance")
    enqueue_task_job(
        "task-1",
        job_id="task-1-00",
        job_type="story.generate",
        payload={"concept": "A test story"},
    )
    update_task("task-1", stage="render", progress=0.6, message="Rendering video")

    persisted = get_persisted_task("task-1")

    assert persisted["run"]["id"] == "task-1"
    assert persisted["run"]["status"] == "running"
    assert persisted["events"][-1]["payload"]["progress"] == 0.6
    assert persisted["jobs"][0]["id"] == "task-1-00"
    assert persisted["jobs"][0]["story_id"] == "story-1"
    assert persisted["jobs"][0]["story_name"] == "A test story"

    finish_task("task-1", status="succeeded", message="Complete")
    assert get_persisted_task("task-1")["run"]["status"] == "succeeded"
    summary = next(task for task in list_persisted_tasks() if task["id"] == "task-1")
    assert summary["status"] == "done"
    assert summary["progress"] == 1
