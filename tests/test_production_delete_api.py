import pytest
from fastapi import HTTPException

from fantasee_server.api import production
from fantasee_server.production_store import ProductionStore


def test_delete_production_run_removes_finished_run(tmp_path, monkeypatch):
    database = tmp_path / "production.db"
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(database))

    with ProductionStore(database) as store:
        run = store.create_run(
            story_id="story-1",
            command="repair",
            input_fingerprint="fingerprint-1",
        )
        store.update_run(run.id, status="failed")
        store.append_event(run.id, "task.finished", {"status": "failed", "message": "Done"})

    result = production.delete_production_run(run.id, body={"confirm": True})

    assert result["status"] == "ok"
    assert result["run_id"] == run.id
    with ProductionStore(database) as store:
        assert store.get_run(run.id) is None


def test_delete_production_run_rejects_active_jobs(tmp_path, monkeypatch):
    database = tmp_path / "production.db"
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(database))

    with ProductionStore(database) as store:
        run = store.create_run(
            story_id="story-1",
            command="repair",
            input_fingerprint="fingerprint-1",
        )
        job = store.enqueue_job(
            run.id,
            job_type="generate.scene_outline",
            payload={"scene": 1},
            idempotency_key="scene-1-outline",
        )
        store.set_job_status(job.id, status="running", progress=0.42, message="Building outline")

    with pytest.raises(HTTPException) as excinfo:
        production.delete_production_run(run.id, body={"confirm": True})

    assert excinfo.value.status_code == 409
