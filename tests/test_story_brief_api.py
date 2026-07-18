import asyncio
import json


def test_story_brief_update_persists_direction_and_marks_story_draft(tmp_path, monkeypatch):
    from fantasee_server.api import actions

    story_id = "brief-story"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    manifest_path = story_dir / f"{story_id}.json"
    manifest_path.write_text(json.dumps({
        "id": story_id,
        "title": "Brief story",
        "story_concept": "An old concept with enough length.",
        "tags": ["old style", "old tone"],
        "status": "complete",
    }), encoding="utf-8")
    monkeypatch.setattr(actions, "generated_story_dir", lambda _story_id: story_dir)
    monkeypatch.setattr(actions, "now", lambda: 1234)

    result = asyncio.run(actions.update_story_brief(story_id, {
        "story_concept": "A new concept that changes the ending.",
        "style": "cinematic grounded realism",
        "tone": "hopeful and strange",
        "world_context": "Universe: The Glass Valley",
    }))

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert saved["story_concept"] == "A new concept that changes the ending."
    assert saved["description"] == saved["story_concept"]
    assert saved["tags"][:2] == ["cinematic grounded realism", "hopeful and strange"]
    assert saved["world_context"] == "Universe: The Glass Valley"
    assert saved["status"] == "draft"
