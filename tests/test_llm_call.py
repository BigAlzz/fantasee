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

    result = generate_story.call_llm("system", "prompt", max_tokens=64)

    assert result == "READY"
    assert len(calls) == 2
