import asyncio
import json


def test_story_context_scan_recovers_editable_canon(tmp_path, monkeypatch):
    from fantasee_server.api import actions

    story_id = "context-scan-story"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    (story_dir / f"{story_id}.json").write_text(json.dumps({
        "id": story_id,
        "title": "The Ember Road",
        "story_concept": "Nara crosses the ashlands to find Var before the last beacon goes dark.",
        "style": "Painterly science fantasy",
        "tone": "Tense but hopeful",
        "scenes": [
            {"title": "The Crossing", "narration": "Nara reaches the broken gate and calls for Var."},
            {"title": "The Beacon", "prompt": "Nara and Var stand beneath an ancient signal tower."},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(actions, "generated_story_dir", lambda _story_id: story_dir)

    result = asyncio.run(actions.scan_story_context(story_id, {}))
    manifest = json.loads((story_dir / f"{story_id}.json").read_text(encoding="utf-8"))

    assert result["status"] == "scanned"
    assert result["summary"] == {"characters": 2, "scenes": 2, "scanned": True}
    assert "Universe: The Ember Road" in manifest["world_context"]
    assert "Nara (story character)" in manifest["characters"]
    assert "Var (story character)" in manifest["characters"]
    assert manifest["context_scan"]["method"] == "manifest-scene-scan"
