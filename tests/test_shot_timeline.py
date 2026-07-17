import pytest

import json

from fantasee_server.media_timeline import build_shot_timeline, build_story_shot_timeline, write_shot_timeline
from fantasee_server.shot_planning import ShotSpec


def test_shot_timeline_uses_approved_assets_and_scene_offsets():
    shots = [
        ShotSpec("scene-01-shot-01", "scene-01", 1, "establish", "wide", 4.0, "road"),
        ShotSpec("scene-01-shot-02", "scene-01", 2, "reveal", "close", 6.0, "compass"),
    ]

    timeline = build_shot_timeline(
        scene_id="scene-01",
        scene_start=12.0,
        scene_duration=10.0,
        shots=shots,
        approved_assets={
            "scene-01-shot-01": "first.png",
            "scene-01-shot-02": "second.png",
        },
    )

    assert timeline[0].start == 12.0
    assert timeline[0].end == 16.0
    assert timeline[1].start == 16.0
    assert timeline[1].end == 22.0
    assert timeline[1].asset_path == "second.png"


def test_shot_timeline_rejects_unapproved_visual_assets():
    shot = ShotSpec("scene-01-shot-01", "scene-01", 1, "establish", "wide", 4.0, "road")

    with pytest.raises(ValueError, match="approved image"):
        build_shot_timeline(
            scene_id="scene-01",
            scene_start=0,
            scene_duration=4,
            shots=[shot],
            approved_assets={},
        )


def test_story_shot_timeline_offsets_each_scene_from_audio_duration():
    first = ShotSpec("scene-01-shot-01", "scene-01", 1, "establish", "wide", 2.0, "road")
    second = ShotSpec("scene-02-shot-01", "scene-02", 1, "reveal", "close", 3.0, "door")

    timeline = build_story_shot_timeline(
        [{"scene": "01", "audio_duration": 4}, {"scene": "02", "audio_duration": 6}],
        {"scene-01": [first], "scene-02": [second]},
        {first.id: "first.png", second.id: "second.png"},
    )

    assert timeline[0].start == 0
    assert timeline[0].end == 4
    assert timeline[1].start == 4
    assert timeline[1].end == 10


def test_writing_shot_timeline_merges_into_canonical_timeline(tmp_path):
    working = tmp_path / "working"
    working.mkdir()
    (working / "timeline.json").write_text(json.dumps({
        "story_id": "demo",
        "segments": [{"scene_id": "01", "text": "hello", "start": 0, "end": 1}],
    }), encoding="utf-8")
    shot = ShotSpec("scene-01-shot-01", "scene-01", 1, "establish", "wide", 4.0, "road")
    segment = build_shot_timeline(
        scene_id="scene-01", scene_start=0, scene_duration=4,
        shots=[shot], approved_assets={shot.id: "approved.png"},
    )[0]

    target = write_shot_timeline("demo", tmp_path, [segment])

    assert target.exists()
    shot_payload = json.loads(target.read_text(encoding="utf-8"))
    assert shot_payload["segments"][0]["shot_id"] == shot.id
    canonical = json.loads((working / "timeline.json").read_text(encoding="utf-8"))
    assert canonical["segments"][0]["text"] == "hello"
    assert canonical["shot_segments"][0]["shot_id"] == shot.id
