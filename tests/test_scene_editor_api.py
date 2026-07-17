import asyncio
import json


def test_scene_revision_updates_script_and_marks_media_stale(tmp_path, monkeypatch):
    from fantasee_server.api import actions

    story_id = "editor-story"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    manifest_path = story_dir / f"{story_id}.json"
    manifest_path.write_text(json.dumps({
        "id": story_id,
        "scenes": [{
            "scene": "01",
            "title": "First Light",
            "prompt": "A quiet road",
            "narration": "The road waits.",
            "narration_text": "The road waits.",
            "audio_filename": "old.wav",
            "audio_duration": 2.0,
            "subtitle_file": "old.json",
            "image_filenames": ["old.png"],
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(actions, "generated_story_dir", lambda _story_id: story_dir)

    result = asyncio.run(actions.update_story_scene(story_id, 0, {
        "narration": "The road answers.",
        "prompt": "A storm breaks over the road.",
    }))

    scene = result["scene"]
    assert scene["narration"] == "The road answers."
    assert scene["narration_text"] == "The road answers."
    assert scene["prompt"] == "A storm breaks over the road."
    assert set(scene["stale_outputs"]) == {"audio", "images", "subtitles", "scene_video", "full_video", "plex"}
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["status"] == "draft"


def test_scene_revision_rejects_unknown_or_empty_fields(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from fantasee_server.api import actions

    story_id = "editor-invalid"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    (story_dir / f"{story_id}.json").write_text(
        json.dumps({"id": story_id, "scenes": [{"narration": "A line."}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(actions, "generated_story_dir", lambda _story_id: story_dir)

    try:
        asyncio.run(actions.update_story_scene(story_id, 0, {"unknown": "value"}))
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("unknown scene fields should be rejected")
