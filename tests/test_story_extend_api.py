import asyncio
import json


def test_extend_api_accepts_duration_and_ending_instruction(tmp_path, monkeypatch):
    from fantasee_server.api import actions
    import story_actions

    story_id = "extend-api"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    (story_dir / f"{story_id}.json").write_text(json.dumps({"id": story_id, "scenes": [{"scene": "01"}]}), encoding="utf-8")
    monkeypatch.setattr(actions, "generated_story_dir", lambda _story_id: story_dir)
    seen = {}

    def fake_apply(story_id, scenes, *, duration_minutes, prompt, progress):
        seen.update(story_id=story_id, scenes=scenes, duration_minutes=duration_minutes, prompt=prompt)
        return {"status": "ok", "new_scenes_added": 2, "total_scenes": 3, "titles": ["The End"], "errors": []}

    monkeypatch.setattr(story_actions, "apply_extend", fake_apply)
    result = asyncio.run(actions.extend_story(story_id, {
        "duration_minutes": 4.5,
        "prompt": "The commander dies saving the city, then conclude the story with a quiet dawn.",
    }))

    assert result["status"] == "ok"
    assert seen == {
        "story_id": story_id,
        "scenes": 5,
        "duration_minutes": 4.5,
        "prompt": "The commander dies saving the city, then conclude the story with a quiet dawn.",
    }
