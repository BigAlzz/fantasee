import asyncio
import time

from fantasee_server.production_store import ProductionStore
from fantasee_server.production_worker import NonRetryableJobError, ProductionWorker


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


def test_retryable_job_can_be_claimed_again(tmp_path):
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

    attempts = []

    def handler(job, _progress):
        attempts.append(job.attempts)
        if len(attempts) == 1:
            raise RuntimeError("temporary failure")

    worker = ProductionWorker(database_path, worker_id="cpu-1", capabilities=("cpu",))
    assert asyncio.run(worker.run_once(handler)) is True
    with ProductionStore(database_path) as store:
        store.set_job_status("job-1", status="retryable", message="temporary failure")
    assert asyncio.run(worker.run_once(handler)) is True

    assert attempts == [1, 2]


def test_non_retryable_supervisor_failure_is_terminal(tmp_path):
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
        raise NonRetryableJobError("no progress")

    worker = ProductionWorker(database_path, worker_id="cpu-1", capabilities=("cpu",))
    assert asyncio.run(worker.run_once(handler)) is True

    with ProductionStore(database_path) as store:
        assert store.get_job("job-1").status == "failed"


def test_worker_registry_records_capabilities_and_heartbeat(tmp_path):
    database_path = tmp_path / "production.db"
    worker = ProductionWorker(
        database_path,
        worker_id="gpu-1",
        capabilities=("gpu", "image-generation"),
    )

    assert asyncio.run(worker.run_once(lambda _job, _progress: None)) is False

    with ProductionStore(database_path) as store:
        workers = store.list_workers()
        assert len(workers) == 1
        assert workers[0].id == "gpu-1"
        assert workers[0].status == "idle"
        assert workers[0].capabilities == ("gpu", "image-generation")
