import json


def test_voice_contract_change_invalidates_narration_and_release_outputs(tmp_path, monkeypatch):
    import fantasee_server.api.settings as settings

    story_dir = tmp_path / "story-one"
    story_dir.mkdir()
    manifest_path = story_dir / "story-one.json"
    manifest_path.write_text(json.dumps({
        "id": "story-one",
        "voice_preset": "Dean",
        "tts_speed": 1.3,
        "status": "complete",
        "pipeline": {"status": "complete", "next_stage": "plex"},
        "scenes": [{"scene": "01", "stale_outputs": []}],
    }), encoding="utf-8")
    monkeypatch.setattr(settings, "GEN_OUTPUTS", tmp_path)
    monkeypatch.setattr(settings, "LEGACY_GEN_OUTPUTS", tmp_path / "legacy")

    changed = settings._invalidate_narration_outputs(
        {"tts_voice_preset": "Dean", "tts_speed": 1.3},
        {"tts_voice_preset": "Milo", "tts_speed": 1.3},
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert changed == ["story-one"]
    assert manifest["voice_preset"] == "Milo"
    assert manifest["pipeline"]["next_stage"] == "audio"
    assert set(manifest["scenes"][0]["stale_outputs"]) == {
        "audio", "subtitles", "shot_timeline", "scene_video", "full_video", "plex"
    }
