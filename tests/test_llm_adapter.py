from fantasee_server.llm_adapter import GranularLLMAdapter, TokenBudget


def test_adapter_tracks_small_call_spend_and_rejects_budget_overrun():
    calls = []

    def fake_call(system, prompt, temperature=0.7, max_tokens=None):
        calls.append((system, prompt, temperature, max_tokens))
        return "structured result"

    budget = TokenBudget(limit=100)
    adapter = GranularLLMAdapter(fake_call, budget=budget)
    result = adapter.complete(
        name="scene.revise",
        system="Write one scene.",
        prompt="A compact bounded scene prompt.",
        max_tokens=40,
    )

    assert result.text == "structured result"
    assert result.estimated_tokens > 0
    assert result.actual_tokens > 0
    assert budget.actual_tokens == result.actual_tokens
    assert calls[0][3] == 40

    try:
        adapter.complete(name="too-large", system="x", prompt="y", max_tokens=200)
    except ValueError as exc:
        assert "budget" in str(exc).lower()
    else:
        raise AssertionError("expected budget enforcement")
