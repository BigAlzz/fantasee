import asyncio
import json
from unittest.mock import patch


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
    assert scene["audio_filename"] == "old.wav"
    assert scene["subtitle_file"] == "old.json"
    assert scene["image_filenames"] == ["old.png"]
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


def test_visual_regeneration_preserves_audio_and_subtitles_when_not_requested(tmp_path, monkeypatch):
    from fantasee_server.api import improvement

    story_id = "editor-visual-only"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    manifest_path = story_dir / f"{story_id}.json"
    manifest_path.write_text(json.dumps({
        "id": story_id,
        "scenes": [{
            "title": "First Light",
            "prompt": "A quiet road",
            "narration": "The road waits.",
            "audio_filename": "old.wav",
            "subtitle_file": "old.json",
            "image_filenames": ["old.png"],
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(improvement, "generated_story_dir", lambda _story_id: story_dir)

    with patch("comfyui_utils.is_running", return_value={"running": False}):
        result = asyncio.run(improvement.regenerate_scene(story_id, 0, {
            "regenerate_images": True,
            "regenerate_audio": False,
        }))

    assert result["regenerated"] == []
    assert result["scene"]["audio_filename"] == "old.wav"
    assert result["scene"]["subtitle_file"] == "old.json"
    assert result["scene"]["image_filenames"] == ["old.png"]


def test_shot_revisions_literal_route_is_registered_before_shot_id_route():
    from fantasee_server.api import shots

    routes = [route.path for route in shots.router.routes]
    assert routes.index("/api/stories/{story_id}/scenes/{scene_idx}/shots/revisions") < routes.index("/api/stories/{story_id}/scenes/{scene_idx}/shots/{shot_id}")
