import generate_story


def test_call_llm_retries_empty_content_before_returning(monkeypatch):
    responses = iter([
        {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": "READY"}, "finish_reason": "stop"}]},
    ])
    calls = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return next(responses)

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()

    monkeypatch.setattr(generate_story.requests, "post", fake_post)
    monkeypatch.setattr(generate_story.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(generate_story, "MIIMO_API_KEY", "test-key")
    monkeypatch.setattr(generate_story, "MIIMO_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr(generate_story, "validate_provider_url", lambda url, kind: url)
    monkeypatch.setenv("FANTASEE_LLM_LENGTH_RETRY_FLOOR", "128")

    result = generate_story.call_llm("system", "prompt", max_tokens=64)

    assert result == "READY"
    assert len(calls) == 2
    assert calls[0][1]["json"]["max_completion_tokens"] == 64
    assert calls[1][1]["json"]["max_completion_tokens"] == 128


def test_call_llm_raises_length_retry_to_8000_tokens(monkeypatch):
    responses = iter([
        {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": "READY"}, "finish_reason": "stop"}]},
    ])
    calls = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return next(responses)

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()

    monkeypatch.delenv("FANTASEE_LLM_LENGTH_RETRY_FLOOR", raising=False)
    monkeypatch.setattr(generate_story.requests, "post", fake_post)
    monkeypatch.setattr(generate_story.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(generate_story, "MIIMO_API_KEY", "test-key")
    monkeypatch.setattr(generate_story, "MIIMO_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr(generate_story, "validate_provider_url", lambda url, kind: url)

    assert generate_story.call_llm("system", "prompt", max_tokens=1000) == "READY"
    assert [call[1]["json"]["max_completion_tokens"] for call in calls] == [1000, 8000]


def test_call_llm_uses_the_runtime_selected_model(monkeypatch):
    seen = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "READY"}, "finish_reason": "stop"}]}

    def fake_post(*_args, **kwargs):
        seen.update(kwargs)
        return FakeResponse()

    monkeypatch.setenv("FANTASEE_LLM_MODEL", "operator-selected-model")
    monkeypatch.setattr(generate_story.requests, "post", fake_post)
    monkeypatch.setattr(generate_story, "MIIMO_API_KEY", "test-key")
    monkeypatch.setattr(generate_story, "MIIMO_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr(generate_story, "validate_provider_url", lambda url, kind: url)

    assert generate_story.call_llm("system", "prompt", max_tokens=64) == "READY"
    assert seen["json"]["model"] == "operator-selected-model"
