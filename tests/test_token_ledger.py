from fantasee_server.llm_adapter import GranularLLMAdapter, TokenBudget
from fantasee_server.production_store import ProductionStore


def test_bounded_llm_call_can_persist_attributed_token_usage(tmp_path):
    with ProductionStore(tmp_path / "production.db") as store:
        store.create_run(
            run_id="run-1", story_id="story", command="generate",
            input_fingerprint="fingerprint",
        )

        def record(result):
            store.record_token_usage(
                "run-1", call_name=result.name,
                estimated_tokens=result.estimated_tokens,
                reserved_tokens=result.reserved_tokens,
                actual_tokens=result.actual_tokens,
                retries=result.retries,
            )

        adapter = GranularLLMAdapter(
            lambda *_args, **_kwargs: "bounded answer",
            budget=TokenBudget(limit=100),
            usage_sink=record,
        )
        adapter.complete(
            name="scene.01.narration", system="Write one scene.",
            prompt="A short bounded passage.", max_tokens=30,
        )

        totals = store.token_usage_totals("run-1")
        calls = store.list_token_usage("run-1")

    assert totals["reserved"] == 60
    assert totals["actual"] > 0
    assert calls[0].call_name == "scene.01.narration"
