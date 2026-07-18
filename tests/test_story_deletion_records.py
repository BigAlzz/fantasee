from fantasee_server.production_store import ProductionStore


def test_delete_story_records_removes_durable_story_state(tmp_path):
    database = tmp_path / "production.db"
    with ProductionStore(database) as store:
        run = store.create_run(story_id="delete-me", command="generate", input_fingerprint="fp")
        store.register_asset(
            story_id="delete-me",
            scene_id="scene-01",
            asset_type="image",
            path="delete-me/image.png",
            generation_fingerprint="image-fp",
        )
        store.record_release("delete-me", release_type="plex", fingerprint="release-fp", path="delete-me/plex")
        store.set_lock("delete-me", "shot", "scene-01-shot-01", True)

        counts = store.delete_story_records("delete-me")

        assert counts["production_runs"] == 1
        assert store.get_run(run.id) is None
        assert store.list_assets("delete-me") == []
        assert store.list_releases("delete-me") == []
        assert store.get_lock("delete-me", "shot", "scene-01-shot-01") is None
