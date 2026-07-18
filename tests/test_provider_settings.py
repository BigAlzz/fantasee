from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import fantasee_server.api.settings as settings_api


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(settings_api.router)
    return TestClient(app)


def test_provider_settings_persist_and_apply_independent_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_api, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(settings_api, "GEN_OUTPUTS", tmp_path / "stories")
    monkeypatch.setattr(settings_api, "LEGACY_GEN_OUTPUTS", tmp_path / "legacy")
    monkeypatch.setattr(
        settings_api,
        "validate_provider_url",
        lambda url, **_kwargs: url.rstrip("/"),
    )
    for name in (
        "XIAOMI_BASE_URL",
        "XIAOMI_API_KEY",
        "FANTASEE_LLM_MODEL",
        "FANTASEE_TTS_BASE_URL",
        "FANTASEE_TTS_API_KEY",
        "FANTASEE_TTS_MODEL",
        "FANTASEE_UNSPLASH_BASE_URL",
        "FANTASEE_UNSPLASH_ACCESS_KEY",
    ):
        monkeypatch.setenv(name, "before-test")

    response = _client().put(
        "/api/settings",
        json={
            "llm_base_url": "https://llm.example/v1/",
            "llm_api_key": "llm-secret-value",
            "llm_model": "writer-large",
            "tts_base_url": "https://voice.example/v1/",
            "tts_api_key": "voice-secret-value",
            "tts_model": "voice-natural",
            "unsplash_base_url": "https://api.unsplash.com/",
            "unsplash_access_key": "unsplash-secret-value",
        },
    )

    assert response.status_code == 200
    saved = response.json()["settings"]
    assert saved["llm_base_url"] == "https://llm.example/v1"
    assert saved["llm_model"] == "writer-large"
    assert saved["tts_base_url"] == "https://voice.example/v1"
    assert saved["tts_model"] == "voice-natural"
    assert saved["unsplash_base_url"] == "https://api.unsplash.com"
    assert saved["llm_api_key"] == "llm-...alue"
    assert saved["tts_api_key"] == "voic...alue"
    assert saved["unsplash_access_key"] == "unsp...alue"

    assert settings_api.os.environ["FANTASEE_LLM_MODEL"] == "writer-large"
    assert settings_api.os.environ["FANTASEE_TTS_BASE_URL"] == "https://voice.example/v1"
    assert settings_api.os.environ["FANTASEE_TTS_API_KEY"] == "voice-secret-value"
    assert settings_api.os.environ["FANTASEE_TTS_MODEL"] == "voice-natural"
    assert settings_api.os.environ["FANTASEE_UNSPLASH_BASE_URL"] == "https://api.unsplash.com"
    assert settings_api.os.environ["FANTASEE_UNSPLASH_ACCESS_KEY"] == "unsplash-secret-value"


def test_llm_models_are_discovered_from_the_draft_provider(monkeypatch):
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"data": [{"id": "writer-small"}, {"id": "writer-large"}]}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(
        settings_api,
        "validate_provider_url",
        lambda url, **_kwargs: url.rstrip("/"),
    )
    monkeypatch.setattr("requests.get", fake_get)

    response = _client().post(
        "/api/settings/llm-models",
        json={"base_url": "https://draft-provider.example/v1/", "api_key": "draft-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "models": ["writer-small", "writer-large"]}
    assert seen["url"] == "https://draft-provider.example/v1/models"
    assert seen["headers"]["Authorization"] == "Bearer draft-key"
    assert seen["allow_redirects"] is False


def test_settings_update_preserves_provider_fields_omitted_by_older_clients(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_api, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(settings_api, "GEN_OUTPUTS", tmp_path / "stories")
    monkeypatch.setattr(settings_api, "LEGACY_GEN_OUTPUTS", tmp_path / "legacy")
    monkeypatch.setattr(settings_api, "validate_provider_url", lambda url, **_kwargs: url.rstrip("/"))
    for name in (
        "XIAOMI_BASE_URL",
        "XIAOMI_API_KEY",
        "FANTASEE_LLM_MODEL",
        "FANTASEE_TTS_BASE_URL",
        "FANTASEE_TTS_API_KEY",
        "FANTASEE_TTS_MODEL",
        "FANTASEE_UNSPLASH_BASE_URL",
        "FANTASEE_UNSPLASH_ACCESS_KEY",
    ):
        monkeypatch.setenv(name, "before-test")
    settings_api._save_settings({
        **settings_api.DEFAULTS,
        "tts_base_url": "https://voice.example/v1",
        "tts_api_key": "voice-secret-value",
        "unsplash_access_key": "unsplash-secret-value",
    })

    response = _client().put("/api/settings", json={"default_tone": "mysterious"})

    assert response.status_code == 200
    saved = settings_api._load_settings()
    assert saved["default_tone"] == "mysterious"
    assert saved["tts_base_url"] == "https://voice.example/v1"
    assert saved["tts_api_key"] == "voice-secret-value"
    assert saved["unsplash_access_key"] == "unsplash-secret-value"


def test_settings_update_never_replaces_short_secrets_with_their_mask(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_api, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(settings_api, "GEN_OUTPUTS", tmp_path / "stories")
    monkeypatch.setattr(settings_api, "LEGACY_GEN_OUTPUTS", tmp_path / "legacy")
    monkeypatch.setattr(settings_api, "validate_provider_url", lambda url, **_kwargs: url.rstrip("/"))
    for name in (
        "XIAOMI_BASE_URL",
        "XIAOMI_API_KEY",
        "FANTASEE_LLM_MODEL",
        "FANTASEE_TTS_BASE_URL",
        "FANTASEE_TTS_API_KEY",
        "FANTASEE_TTS_MODEL",
        "FANTASEE_UNSPLASH_BASE_URL",
        "FANTASEE_UNSPLASH_ACCESS_KEY",
    ):
        monkeypatch.setenv(name, "before-test")
    settings_api._save_settings({
        **settings_api.DEFAULTS,
        "llm_api_key": "12345678",
        "tts_api_key": "abcdefgh",
        "unsplash_access_key": "87654321",
    })
    client = _client()
    masked = client.get("/api/settings").json()

    response = client.put("/api/settings", json=masked)

    assert response.status_code == 200
    saved = settings_api._load_settings()
    assert saved["llm_api_key"] == "12345678"
    assert saved["tts_api_key"] == "abcdefgh"
    assert saved["unsplash_access_key"] == "87654321"
