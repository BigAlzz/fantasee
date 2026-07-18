from fantasee_server.production_store import ProductionStore
from fantasee_server.api import production


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


def test_release_asset_resolves_only_recorded_story_artifact(tmp_path, monkeypatch):
    database = tmp_path / "production.db"
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    video = release_dir / "story.mp4"
    video.write_bytes(b"video")
    with ProductionStore(database) as store:
        release = store.record_release("story", release_type="plex", fingerprint="one", path=str(release_dir))
    monkeypatch.setattr(production, "production_database_path", lambda: database)
    assert production._release_asset("story", release.id, (".mp4",)) == video.resolve()


def test_release_asset_rejects_release_from_another_story(tmp_path, monkeypatch):
    database = tmp_path / "production.db"
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "story.mp4").write_bytes(b"video")
    with ProductionStore(database) as store:
        release = store.record_release("story", release_type="plex", fingerprint="one", path=str(release_dir))
    monkeypatch.setattr(production, "production_database_path", lambda: database)
    try:
        production._release_asset("other-story", release.id, (".mp4",))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 404
    else:
        raise AssertionError("cross-story release lookup should fail")
