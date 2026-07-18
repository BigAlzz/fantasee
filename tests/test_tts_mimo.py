from __future__ import annotations

import base64
import json
import wave
from io import BytesIO

import pytest

import tts_utils
from fantasee_server.api.tts import _validate_voice_sample


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload=None, lines=None):
        self._payload = payload or {}
        self._lines = lines or []

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)

    def close(self):
        return None


def _audio_payload() -> dict:
    audio = base64.b64encode(b"RIFF fake wav bytes").decode("ascii")
    return {"choices": [{"message": {"audio": {"data": audio}}}]}


def test_voice_design_payload_uses_description_and_option(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(kwargs)
        return FakeResponse(_audio_payload())

    monkeypatch.setenv("XIAOMI_API_KEY", "test-key")
    monkeypatch.setattr(tts_utils.requests, "post", fake_post)

    result = tts_utils.synthesize(
        "The door opens.",
        model="design",
        style="A tired but kind alto with a close, intimate delivery.",
        optimize_text_preview=False,
    )

    assert result == b"RIFF fake wav bytes"
    assert seen["json"]["model"] == "mimo-v2.5-tts-voicedesign"
    assert seen["json"]["messages"][0]["role"] == "user"
    assert seen["json"]["audio"]["optimize_text_preview"] is False
    assert seen["json"]["audio"]["format"] == "wav"


def test_preset_tts_uses_its_independent_runtime_provider(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return FakeResponse(_audio_payload())

    monkeypatch.setenv("XIAOMI_API_KEY", "shared-llm-key")
    monkeypatch.setenv("XIAOMI_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("FANTASEE_TTS_API_KEY", "tts-only-key")
    monkeypatch.setenv("FANTASEE_TTS_BASE_URL", "https://voice.example/v1")
    monkeypatch.setenv("FANTASEE_TTS_MODEL", "voice-natural")
    monkeypatch.setattr(tts_utils, "validate_provider_url", lambda url, kind: url)
    monkeypatch.setattr(tts_utils.requests, "post", fake_post)

    result = tts_utils.synthesize("The door opens.", model="preset")

    assert result == b"RIFF fake wav bytes"
    assert seen["url"] == "https://voice.example/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer tts-only-key"
    assert seen["json"]["model"] == "voice-natural"


def test_voice_clone_payload_requires_and_forwards_data_uri(monkeypatch):
    seen = {}
    sample = "data:audio/wav;base64," + base64.b64encode(b"sample").decode("ascii")

    def fake_post(url, **kwargs):
        seen.update(kwargs)
        return FakeResponse(_audio_payload())

    monkeypatch.setenv("XIAOMI_API_KEY", "test-key")
    monkeypatch.setattr(tts_utils.requests, "post", fake_post)

    result = tts_utils.synthesize("Stay close.", model="clone", voice_sample=sample)

    assert result == b"RIFF fake wav bytes"
    assert seen["json"]["model"] == "mimo-v2.5-tts-voiceclone"
    assert seen["json"]["audio"]["voice"] == sample


def test_streaming_pcm_is_collected_as_24khz_mono_wav():
    pcm = (100).to_bytes(2, "little", signed=True) * 4
    event = {"choices": [{"delta": {"audio": {"data": base64.b64encode(pcm).decode("ascii")}}}]}
    result = tts_utils._decode_streaming_pcm(FakeResponse(lines=[f"data: {json.dumps(event)}", "data: [DONE]"]))

    with wave.open(BytesIO(result), "rb") as audio:
        assert audio.getframerate() == 24000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.readframes(4) == pcm


def test_clone_sample_validation_rejects_wrong_format_and_size():
    with pytest.raises(Exception, match="MP3 or WAV"):
        _validate_voice_sample("data:text/plain;base64,Zm9v")

    oversized = "data:audio/wav;base64," + ("A" * (10 * 1024 * 1024 + 1))
    with pytest.raises(Exception, match="10 MB"):
        _validate_voice_sample(oversized)
