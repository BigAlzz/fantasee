import time

from fantasee_server.production_store import ProductionStore
from fantasee_server.shot_planning import ShotSpec


def test_run_and_events_survive_store_restart(tmp_path):
    database_path = tmp_path / "production.db"

    store = ProductionStore(database_path)
    run = store.create_run(
        story_id="story-1",
        command="repair",
        input_fingerprint="fingerprint-1",
    )
    store.append_event(run.id, "run.created", {"message": "queued"})
    store.close()

    reopened = ProductionStore(database_path)
    persisted_run = reopened.get_run(run.id)
    persisted_events = reopened.list_events(run.id)

    assert persisted_run is not None
    assert persisted_run.status == "queued"
    assert persisted_events[0].event_type == "run.created"
    assert persisted_events[0].payload == {"message": "queued"}
    reopened.close()


def test_enqueue_job_is_idempotent_for_a_run(tmp_path):
    store = ProductionStore(tmp_path / "production.db")
    run = store.create_run(
        story_id="story-1",
        command="repair",
        input_fingerprint="fingerprint-1",
    )

    first = store.enqueue_job(
        run.id,
        job_type="generate.narration",
        payload={"scene": 1},
        idempotency_key="scene-1-narration",
    )
    duplicate = store.enqueue_job(
        run.id,
        job_type="generate.narration",
        payload={"scene": 1},
        idempotency_key="scene-1-narration",
    )

    assert duplicate.id == first.id
    assert store.get_job(first.id).status == "queued"
    store.close()


def test_job_lease_is_exclusive_and_expired_leases_are_recovered(tmp_path):
    database_path = tmp_path / "production.db"
    store = ProductionStore(database_path)
    run = store.create_run(
        story_id="story-1",
        command="repair",
        input_fingerprint="fingerprint-1",
    )
    job = store.enqueue_job(
        run.id,
        job_type="generate.image",
        payload={"scene": 1},
        idempotency_key="scene-1-image",
    )

    now = time.time()
    first_lease = store.lease_next_job("cpu-1", lease_seconds=10, now=now)
    second_lease = store.lease_next_job("gpu-1", lease_seconds=10, now=now)

    assert first_lease is not None
    assert first_lease.id == job.id
    assert second_lease is None

    store.close()
    reopened = ProductionStore(database_path)
    recovered = reopened.lease_next_job("gpu-1", lease_seconds=10, now=now + 11)

    assert recovered is not None
    assert recovered.id == job.id
    assert recovered.attempts == 2
    reopened.complete_job(recovered.id, recovered.lease_token)
    assert reopened.get_job(job.id).status == "succeeded"
    reopened.close()


def test_worker_capabilities_route_gpu_jobs(tmp_path):
    store = ProductionStore(tmp_path / "production.db")
    run = store.create_run(
        story_id="story-1",
        command="repair",
        input_fingerprint="fingerprint-1",
    )
    job = store.enqueue_job(
        run.id,
        job_type="generate.image",
        payload={"scene": 1},
        idempotency_key="scene-1-image",
        required_capabilities=("gpu",),
    )

    now = time.time()
    assert store.lease_next_job("cpu-1", capabilities=("cpu",), now=now) is None
    lease = store.lease_next_job("gpu-1", capabilities=("cpu", "gpu"), now=now)

    assert lease is not None
    assert lease.id == job.id
    store.close()


def test_cancel_and_retry_job_are_explicit_state_transitions(tmp_path):
    store = ProductionStore(tmp_path / "production.db")
    run = store.create_run(
        story_id="story-1", command="repair", input_fingerprint="fingerprint-1"
    )
    job = store.enqueue_job(
        run.id,
        job_id="job-1",
        job_type="repair",
        payload={},
        idempotency_key="job-1",
    )

    cancelled = store.cancel_job(job.id)
    assert cancelled.status == "cancelled"
    retried = store.retry_job(job.id)
    assert retried.status == "queued"
    assert retried.lease_token is None
    store.close()


def test_queue_admission_pause_and_priority_are_durable(tmp_path):
    database_path = tmp_path / "production.db"
    store = ProductionStore(database_path)
    run = store.create_run(
        story_id="story-1", command="repair", input_fingerprint="fingerprint-1"
    )
    low = store.enqueue_job(
        run.id, job_type="low", payload={}, idempotency_key="low", priority=1
    )
    high = store.enqueue_job(
        run.id, job_type="high", payload={}, idempotency_key="high", priority=9
    )

    assert [job.id for job in store.list_runnable_jobs()] == [high.id, low.id]
    store.set_admission_paused(True)
    assert store.admission_paused() is True
    assert store.lease_next_job("worker-1", now=time.time()) is None

    store.set_admission_paused(False)
    assert store.lease_next_job("worker-1", now=time.time()).id == high.id
    store.close()

    reopened = ProductionStore(database_path)
    assert reopened.admission_paused() is False
    reopened.close()


def test_rendering_mode_is_durable_and_validated(tmp_path):
    database_path = tmp_path / "production.db"
    store = ProductionStore(database_path)

    assert store.rendering_mode() == "gpu"
    assert store.set_rendering_mode("basic") == "basic"
    store.close()

    reopened = ProductionStore(database_path)
    assert reopened.rendering_mode() == "basic"
    try:
        reopened.set_rendering_mode("turbo")
    except ValueError as exc:
        assert "basic, gpu, or max" in str(exc)
    else:
        raise AssertionError("unsupported rendering modes must be rejected")
    reopened.close()


def test_semantic_shot_plan_survives_store_restart(tmp_path):
    database_path = tmp_path / "production.db"
    shots = [
        ShotSpec("scene-01-shot-01", "scene-01", 1, "establish (1)", "wide", 5.0, "A flooded road"),
        ShotSpec("scene-01-shot-02", "scene-01", 2, "reveal detail (2)", "close", 5.0, "A flooded road"),
    ]

    store = ProductionStore(database_path)
    revision = store.save_shot_plan("story-1", "scene-01", shots)
    store.close()

    reopened = ProductionStore(database_path)
    persisted = reopened.list_shots("story-1", "scene-01")

    assert revision == 1
    assert [shot.id for shot in persisted] == ["scene-01-shot-01", "scene-01-shot-02"]
    assert persisted[1].purpose == "reveal detail (2)"
    assert persisted[0].revision == 1
    reopened.close()


def test_revising_one_shot_preserves_the_previous_plan_revision(tmp_path):
    store = ProductionStore(tmp_path / "production.db")
    original = [
        ShotSpec("scene-01-shot-01", "scene-01", 1, "establish (1)", "wide", 5.0, "Old road"),
        ShotSpec("scene-01-shot-02", "scene-01", 2, "reveal detail (2)", "close", 5.0, "Old road"),
    ]
    store.save_shot_plan("story-1", "scene-01", original)

    revision = store.revise_shot(
        "story-1", "scene-01", "scene-01-shot-02", visual_context="A cracked brass compass in rain"
    )

    previous = store.list_shots("story-1", "scene-01", revision=1)
    latest = store.list_shots("story-1", "scene-01")
    assert revision == 2
    assert previous[1].visual_context == "Old road"
    assert latest[0].visual_context == "Old road"
    assert latest[1].visual_context == "A cracked brass compass in rain"
    store.close()


def test_worker_can_lease_only_its_declared_job_type(tmp_path):
    store = ProductionStore(tmp_path / "production.db")
    run = store.create_run(story_id="story-1", command="repair", input_fingerprint="test")
    store.enqueue_job(run.id, job_type="library.complete", payload={}, idempotency_key="library")
    shot_job = store.enqueue_job(run.id, job_type="shot.generate", payload={}, idempotency_key="shot")

    lease = store.lease_next_job("shot-gpu", capabilities=("gpu",), job_types=("shot.generate",))

    assert lease is not None
    assert lease.id == shot_job.id
    store.close()


def test_restoring_a_shot_plan_revision_creates_a_new_current_revision(tmp_path):
    store = ProductionStore(tmp_path / "production.db")
    original = [ShotSpec("scene-01-shot-01", "scene-01", 1, "establish (1)", "wide", 5.0, "Original context")]
    store.save_shot_plan("story-1", "scene-01", original)
    store.revise_shot("story-1", "scene-01", "scene-01-shot-01", visual_context="Unwanted revision")

    restored_revision = store.restore_shot_plan_revision("story-1", "scene-01", revision=1)

    assert restored_revision == 3
    assert store.list_shots("story-1", "scene-01")[0].visual_context == "Original context"
    assert store.list_shots("story-1", "scene-01", revision=2)[0].visual_context == "Unwanted revision"
    store.close()


def test_reordering_shots_creates_revision_without_changing_visual_context(tmp_path):
    store = ProductionStore(tmp_path / "production.db")
    shots = [
        ShotSpec("scene-01-shot-01", "scene-01", 1, "first", "wide", 4.0, "Road"),
        ShotSpec("scene-01-shot-02", "scene-01", 2, "second", "close", 4.0, "Compass"),
    ]
    store.save_shot_plan("story-1", "scene-01", shots)

    revision = store.reorder_shots(
        "story-1", "scene-01", ["scene-01-shot-02", "scene-01-shot-01"]
    )

    latest = store.list_shots("story-1", "scene-01")
    previous = store.list_shots("story-1", "scene-01", revision=1)
    assert revision == 2
    assert [shot.id for shot in latest] == ["scene-01-shot-02", "scene-01-shot-01"]
    assert [shot.order for shot in latest] == [1, 2]
    assert previous[0].visual_context == "Road"
    assert latest[0].visual_context == "Compass"
    store.close()
