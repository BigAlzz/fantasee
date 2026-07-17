import pytest

from fantasee_server.media_timeline import build_shot_timeline
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
