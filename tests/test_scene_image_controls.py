import asyncio
import json
from pathlib import Path


def test_manual_scene_image_addition_inserts_requested_count(tmp_path, monkeypatch):
    from fantasee_server.api import improvement
    import comfyui_utils

    story_id = "scene-image-controls"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    manifest_path = story_dir / f"{story_id}.json"
    manifest_path.write_text(json.dumps({
        "id": story_id,
        "status": "complete",
        "scenes": [{"title": "Arrival", "prompt": "A ruined station at dawn", "image_filenames": ["old.png"]}],
    }), encoding="utf-8")
    monkeypatch.setattr(improvement, "generated_story_dir", lambda _story_id: story_dir)
    monkeypatch.setattr(comfyui_utils, "is_running", lambda: {"running": True})
    counter = {"value": 0}

    def fake_generate_image(**kwargs):
        counter["value"] += 1
        filename = f"new-{counter['value']}.png"
        Path(kwargs["output_dir"], filename).write_bytes(b"image")
        return filename

    monkeypatch.setattr(comfyui_utils, "generate_image", fake_generate_image)
    result = asyncio.run(improvement.add_scene_image(story_id, 0, {"mode": "manual", "count": 2, "position": 0}))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["filenames"] == ["new-1.png", "new-2.png"]
    assert manifest["scenes"][0]["image_filenames"] == ["new-1.png", "new-2.png", "old.png"]
    assert "scene_video" in manifest["scenes"][0]["stale_outputs"]
