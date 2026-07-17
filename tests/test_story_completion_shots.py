import json

from fantasee_server.library import story_completion_report
from fantasee_server.production_runtime import production_database_path
from fantasee_server.production_store import ProductionStore
from fantasee_server.shot_planning import ShotSpec


def test_semantic_shot_plan_requires_approved_image_and_timeline(tmp_path, monkeypatch):
    story_id = "semantic-gate"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    story = {
        "id": story_id,
        "status": "draft",
        "scenes": [{"scene": "01", "prompt": "A road.", "narration": "A road."}],
    }
    (story_dir / f"{story_id}.json").write_text(json.dumps(story), encoding="utf-8")
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))
    shot = ShotSpec("scene-01-shot-01", "scene-01", 1, "establish", "wide", 4.0, "a road")
    with ProductionStore(production_database_path()) as store:
        store.save_shot_plan(story_id, "scene-01", [shot])

    report = story_completion_report(story_id, story=story, story_dir=story_dir)

    assert "shot_image" in report["missing"]
    assert "shot_timeline" in report["missing"]
    assert report["counts"]["planned_shots"] == 1


def test_semantic_shot_plan_is_satisfied_by_approved_image_and_timeline(tmp_path, monkeypatch):
    story_id = "semantic-ready"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    story = {
        "id": story_id,
        "status": "draft",
        "scenes": [{"scene": "01", "prompt": "A road.", "narration": "A road."}],
    }
    (story_dir / f"{story_id}.json").write_text(json.dumps(story), encoding="utf-8")
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))
    image = story_dir / "approved.png"
    image.write_bytes(b"approved")
    shot = ShotSpec("scene-01-shot-01", "scene-01", 1, "establish", "wide", 4.0, "a road")
    with ProductionStore(production_database_path()) as store:
        store.save_shot_plan(story_id, "scene-01", [shot])
        candidate = store.register_asset(
            story_id=story_id, scene_id=shot.id, asset_type="image", path=str(image),
            generation_fingerprint="approved-shot",
        )
        store.approve_asset(candidate.id)
    (story_dir / "working").mkdir()
    (story_dir / "working" / "shot_timeline.json").write_text(json.dumps({
        "segments": [{"shot_id": shot.id, "scene_id": "scene-01", "start": 0, "end": 4,
                      "asset_path": str(image)}]
    }), encoding="utf-8")

    report = story_completion_report(story_id, story=story, story_dir=story_dir)

    assert "shot_image" not in report["missing"]
    assert "shot_timeline" not in report["missing"]
    assert report["counts"]["approved_shots"] == 1


def test_semantic_gate_rejects_timeline_for_superseded_approved_image(tmp_path, monkeypatch):
    story_id = "semantic-stale-timeline"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    story = {
        "id": story_id,
        "status": "draft",
        "scenes": [{"scene": "01", "prompt": "A road.", "narration": "A road."}],
    }
    (story_dir / f"{story_id}.json").write_text(json.dumps(story), encoding="utf-8")
    monkeypatch.setenv("FANTASEE_PRODUCTION_DB", str(tmp_path / "production.db"))
    old_image = story_dir / "old.png"
    new_image = story_dir / "new.png"
    old_image.write_bytes(b"old")
    new_image.write_bytes(b"new")
    shot = ShotSpec("scene-01-shot-01", "scene-01", 1, "establish", "wide", 4.0, "a road")
    with ProductionStore(production_database_path()) as store:
        store.save_shot_plan(story_id, "scene-01", [shot])
        old_asset = store.register_asset(
            story_id=story_id, scene_id=shot.id, asset_type="image", path=str(old_image),
            generation_fingerprint="old",
        )
        store.approve_asset(old_asset.id)
        store.save_shot_plan(story_id, "scene-01", [shot])
        new_asset = store.register_asset(
            story_id=story_id, scene_id=shot.id, asset_type="image", path=str(new_image),
            generation_fingerprint="new",
        )
        store.approve_asset(new_asset.id)
    (story_dir / "working").mkdir()
    (story_dir / "working" / "shot_timeline.json").write_text(json.dumps({
        "segments": [{"shot_id": shot.id, "scene_id": "scene-01", "start": 0, "end": 4,
                      "asset_path": str(old_image)}]
    }), encoding="utf-8")

    report = story_completion_report(story_id, story=story, story_dir=story_dir)

    assert "shot_timeline" in report["missing"]
