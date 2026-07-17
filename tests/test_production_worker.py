import asyncio
import time

from fantasee_server.production_store import ProductionStore
from fantasee_server.production_worker import ProductionWorker


def test_worker_claims_runs_and_completes_job(tmp_path):
    database_path = tmp_path / "production.db"
    with ProductionStore(database_path) as store:
        run = store.create_run(
            story_id="story-1",
            command="generate",
            input_fingerprint="fingerprint-1",
        )
        store.enqueue_job(
            run.id,
            job_id="job-1",
            job_type="story.generate",
            payload={"concept": "A test story"},
            idempotency_key="job-1",
        )

    seen = []

    def handler(job, progress):
        seen.append(job.id)
        progress("generate", "Generating", 0.5)
        return {"story_id": "story-1"}

    worker = ProductionWorker(database_path, worker_id="cpu-1", capabilities=("cpu",))
    assert asyncio.run(worker.run_once(handler)) is True

    with ProductionStore(database_path) as store:
        job = store.get_job("job-1")
        assert seen == ["job-1"]
        assert job.status == "succeeded"
        assert job.progress == 1


def test_worker_heartbeats_during_long_job(tmp_path):
    database_path = tmp_path / "production.db"
    with ProductionStore(database_path) as store:
        run = store.create_run(
            story_id="story-1",
            command="generate",
            input_fingerprint="fingerprint-1",
        )
        store.enqueue_job(
            run.id,
            job_id="job-1",
            job_type="story.generate",
            payload={},
            idempotency_key="job-1",
        )

    def handler(_job, _progress):
        time.sleep(0.12)

    worker = ProductionWorker(
        database_path,
        worker_id="cpu-1",
        capabilities=("cpu",),
        lease_seconds=0.04,
        heartbeat_seconds=0.01,
    )
    assert asyncio.run(worker.run_once(handler)) is True

    with ProductionStore(database_path) as store:
        assert store.get_job("job-1").status == "succeeded"


def test_worker_failure_is_recorded_without_losing_the_job(tmp_path):
    database_path = tmp_path / "production.db"
    with ProductionStore(database_path) as store:
        run = store.create_run(
            story_id="story-1",
            command="generate",
            input_fingerprint="fingerprint-1",
        )
        store.enqueue_job(
            run.id,
            job_id="job-1",
            job_type="story.generate",
            payload={},
            idempotency_key="job-1",
        )

    def handler(_job, _progress):
        raise RuntimeError("render failed")

    worker = ProductionWorker(database_path, worker_id="cpu-1", capabilities=("cpu",))
    assert asyncio.run(worker.run_once(handler)) is True

    with ProductionStore(database_path) as store:
        job = store.get_job("job-1")
        assert job.status == "retryable"
        assert job.message == "render failed"
