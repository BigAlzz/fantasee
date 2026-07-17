def test_production_events_endpoint_returns_events_after_cursor(tmp_path, monkeypatch):
    from fantasee_server.api import production
    from fantasee_server.production_store import ProductionStore

    database = tmp_path / "production.db"
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(database))
    with ProductionStore(database) as store:
        store.create_run(run_id="run-events", story_id="story", command="generate", input_fingerprint="fingerprint")
        store.append_event("run-events", "task.started", {"stage": "queue"})
        store.append_event("run-events", "task.progress", {"progress": 0.5})

    result = production.list_production_events("run-events", after_sequence=1)

    assert result["run_id"] == "run-events"
    assert [event["sequence"] for event in result["events"]] == [2]
    assert result["next_sequence"] == 2
