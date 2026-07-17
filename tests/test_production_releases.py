from fantasee_server.production_store import ProductionStore


def test_record_release_supersedes_previous_current_release(tmp_path):
    with ProductionStore(tmp_path / "production.db") as store:
        first = store.record_release(
            "story", release_type="plex", fingerprint="one", path="one",
        )
        second = store.record_release(
            "story", release_type="plex", fingerprint="two", path="two",
        )

        assert first.status == "current"
        assert second.status == "current"
        assert store.get_current_release("story", "plex").id == second.id
        assert [release.status for release in store.list_releases("story")] == ["current", "superseded"]
