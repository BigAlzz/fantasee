import json

from fantasee_server.api import shots as shots_api
from fantasee_server.production_runtime import production_database_path
from fantasee_server.production_store import ProductionStore
from fantasee_server.shot_planning import ShotSpec


def test_story_timeline_api_helper_builds_absolute_offsets(tmp_path, monkeypatch):
    story_id = "api-timeline"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    (story_dir / f"{story_id}.json").write_text(json.dumps({
        "scenes": [{"scene": "01", "audio_duration": 5}],
    }), encoding="utf-8")
    monkeypatch.setattr(shots_api, "generated_story_dir", lambda _story_id: story_dir)
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))
    image = story_dir / "approved.png"
    image.write_bytes(b"image")
    shot = ShotSpec("scene-01-shot-01", "scene-01", 1, "establish", "wide", 2, "road")
    with ProductionStore(production_database_path()) as store:
        store.save_shot_plan(story_id, "scene-01", [shot])
        candidate = store.register_asset(
            story_id=story_id, scene_id=shot.id, asset_type="image", path=str(image),
            generation_fingerprint="approved",
        )
        store.approve_asset(candidate.id)

    _, _, segments = shots_api._story_shot_timeline(story_id)

    assert segments[0].start == 0
    assert segments[0].end == 5
