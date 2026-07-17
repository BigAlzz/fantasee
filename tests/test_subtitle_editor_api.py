import json


def test_scene_subtitles_are_loaded_from_the_current_manifest_audio_pair(tmp_path, monkeypatch):
    from fantasee_server.api import generated

    story_id = "subtitle-editor"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    (story_dir / f"{story_id}.json").write_text(json.dumps({
        "id": story_id,
        "scenes": [{"audio_filename": "scene.wav", "subtitle_file": "scene.json"}],
    }), encoding="utf-8")
    (story_dir / "scene.json").write_text(json.dumps([
        {"start": 0.0, "end": 1.4, "text": "The door opens."},
    ]), encoding="utf-8")
    monkeypatch.setattr(generated, "generated_story_dir", lambda _story_id: story_dir)

    result = generated.get_scene_subtitles(story_id, 0)

    assert result["audio_filename"] == "scene.wav"
    assert result["segments"][0]["text"] == "The door opens."
