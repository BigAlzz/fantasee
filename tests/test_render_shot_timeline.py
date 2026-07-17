import json

from PIL import Image, ImageDraw

import render_video


def test_scene_assets_use_approved_shot_timeline_instead_of_manifest_images(tmp_path, monkeypatch):
    slug = "timeline-story"
    story_dir = tmp_path / slug
    working = story_dir / "working"
    working.mkdir(parents=True)
    legacy = story_dir / f"{slug}_s01_legacy_00001_.png"
    approved_a = story_dir / "approved-a.png"
    approved_b = story_dir / "approved-b.png"
    for path in (legacy, approved_a, approved_b):
        Image.new("RGB", (896, 512), (80, 90, 100)).save(path)
    audio = story_dir / f"tts_{slug}_s01.wav"
    audio.write_bytes(b"audio")
    for index, path in enumerate((legacy, approved_a, approved_b)):
        image = Image.open(path)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 448, 512), fill=(20 + index * 30, 40, 80))
        draw.rectangle((448, 0, 896, 512), fill=(180, 120 + index * 20, 60))
        image.save(path)
    (working / "timeline.json").write_text(json.dumps({
        "shot_segments": [
            {"scene_id": "scene-01", "shot_id": "shot-2", "asset_path": str(approved_b), "start": 4, "end": 7},
            {"scene_id": "scene-01", "shot_id": "shot-1", "asset_path": str(approved_a), "start": 0, "end": 4},
        ]
    }), encoding="utf-8")
    monkeypatch.setattr(render_video.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"stdout": "7", "returncode": 0})())

    assets = render_video.get_scene_assets(story_dir, slug, 1)

    assert assets["images"] == [approved_a, approved_b]
    assert assets["image_durations"] == [4.0, 3.0]
