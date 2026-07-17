import pytest

from fantasee_server.production_store import ProductionStore
from fantasee_server.shot_planning import ShotSpec


def test_locked_shot_rejects_revision_and_candidate_approval(tmp_path):
    image = tmp_path / "candidate.png"
    image.write_bytes(b"image")
    with ProductionStore(tmp_path / "production.db") as store:
        shot = ShotSpec("scene-01-shot-01", "scene-01", 1, "establish", "wide", 3, "road")
        store.save_shot_plan("story", "scene-01", [shot])
        candidate = store.register_asset(
            story_id="story", scene_id=shot.id, asset_type="image", path=str(image),
            generation_fingerprint="one",
        )
        store.set_lock("story", "shot", shot.id, True)

        with pytest.raises(ValueError, match="locked"):
            store.revise_shot("story", "scene-01", shot.id, visual_context="new road")
        with pytest.raises(ValueError, match="locked"):
            store.approve_asset(candidate.id)

        store.set_lock("story", "shot", shot.id, False)
        assert store.revise_shot("story", "scene-01", shot.id, visual_context="new road") == 2
