from fantasee_server.production_runtime import (
    finish_task,
    get_persisted_task,
    start_task,
    update_task,
)


def test_task_progress_is_persisted_for_restart_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))

    start_task("task-1", story_id="story-1", kind="library_maintenance")
    update_task("task-1", stage="render", progress=0.6, message="Rendering video")

    persisted = get_persisted_task("task-1")

    assert persisted["run"]["id"] == "task-1"
    assert persisted["run"]["status"] == "running"
    assert persisted["events"][-1]["payload"]["progress"] == 0.6

    finish_task("task-1", status="succeeded", message="Complete")
    assert get_persisted_task("task-1")["run"]["status"] == "succeeded"
