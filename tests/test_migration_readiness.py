from __future__ import annotations

import json


def test_migration_readiness_is_read_only_and_classifies_legacy_stories(tmp_path, monkeypatch):
    from fantasee_server import discovery, migration

    canonical = tmp_path / "stories" / "new-story"
    legacy = tmp_path / "outputs" / "old-story"
    for story_dir, story_id in ((canonical, "new-story"), (legacy, "old-story")):
        story_dir.mkdir(parents=True)
        (story_dir / f"{story_id}.json").write_text(json.dumps({
            "id": story_id,
            "title": story_id,
            "scenes": [],
        }), encoding="utf-8")

    monkeypatch.setattr(discovery, "GEN_OUTPUTS", tmp_path / "stories")
    monkeypatch.setattr(discovery, "LEGACY_GEN_OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(migration, "GEN_OUTPUTS", tmp_path / "stories")
    monkeypatch.setattr("fantasee_server.library.story_completion_report", lambda *args, **kwargs: {
        "complete": False,
        "missing": ["story"],
        "issue_count": 1,
    })

    result = migration.migration_readiness()

    assert result["destructive_actions_performed"] is False
    assert result["summary"]["total"] == 2
    old = next(row for row in result["stories"] if row["id"] == "old-story")
    assert old["storage_root"] == "outputs"
    assert "legacy_read_only" in old["risks"]
