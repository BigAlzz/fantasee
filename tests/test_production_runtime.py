from fantasee_server.production_runtime import (
    enqueue_task_job,
    find_active_task,
    finish_task,
    get_persisted_task,
    list_persisted_tasks,
    start_task,
    update_task,
)
from fantasee_server.production_store import ProductionStore


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


def test_persisted_task_exposes_current_worker_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))

    start_task("task-1", story_id="story-1", kind="library_maintenance")
    enqueue_task_job(
        "task-1",
        job_id="task-1-00",
        job_type="story.generate",
        payload={"concept": "A test story"},
    )
    with ProductionStore(tmp_path / "production.db") as store:
        store.register_worker("gpu-1", ("gpu",))
        leased = store.lease_next_job("gpu-1", capabilities=("gpu",), run_id="task-1")
        assert leased is not None
        store.start_job(leased.id, leased.lease_token)
        store.update_worker("gpu-1", status="running", current_job_id=leased.id)

    persisted = get_persisted_task("task-1")

    assert persisted["jobs"][0]["worker_id"] == "gpu-1"
    assert persisted["jobs"][0]["worker_status"] == "running"
    summary = next(task for task in list_persisted_tasks() if task["id"] == "task-1")
    assert summary["worker_ids"] == ["gpu-1"]


def test_find_active_task_deduplicates_identical_production_input(tmp_path, monkeypatch):
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))
    metadata = {"story_concept": "A duplicate-safe story", "num_scenes": 3}

    start_task("task-1", story_id=metadata["story_concept"], kind="generate", metadata=metadata)

    assert find_active_task(story_id=metadata["story_concept"], kind="generate", metadata=metadata) == {
        "id": "task-1",
        "status": "running",
    }
    assert find_active_task(story_id="another story", kind="generate", metadata=metadata) is None


def test_list_persisted_tasks_does_not_duplicate_durable_child_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))

    start_task("queue-1", story_id="queue", kind="generation_queue")
    start_task("queue-1-00", story_id="story-1", kind="generate")
    enqueue_task_job(
        "queue-1",
        job_id="queue-1-00",
        job_type="story.generate",
        payload={"story_id": "story-1", "story_name": "A durable story"},
    )

    tasks = list_persisted_tasks()

    assert [task["id"] for task in tasks].count("queue-1-00") == 1
