from tts_utils import DEFAULT_TTS_SPEED, configured_tts_speed


def test_tts_speed_reads_runtime_setting(monkeypatch):
    monkeypatch.setenv("FANTASEE_TTS_SPEED", "1.65")
    assert configured_tts_speed() == 1.65


def test_tts_speed_clamps_invalid_runtime_setting(monkeypatch):
    monkeypatch.setenv("FANTASEE_TTS_SPEED", "9")
    assert configured_tts_speed() == 3.0
    monkeypatch.setenv("FANTASEE_TTS_SPEED", "not-a-number")
    assert configured_tts_speed() == DEFAULT_TTS_SPEED
