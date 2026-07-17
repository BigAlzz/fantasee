import json

from generate_story import generate_story_outline_granular


def test_granular_ladder_commissions_context_and_one_scene_at_a_time(monkeypatch):
    calls = []
    responses = iter([
        json.dumps({"cast": "traveler", "world": "valley", "rules": "water matters", "conflicts": "storm", "continuity": "wet coat"}),
        json.dumps({"beats": [{"scene_number": 1, "purpose": "crossing", "turning_point": "bridge breaks", "continuity": "wet coat"}]}),
        "Title: Crossing\nVisual Prompt: wide shot of a traveler crossing a broken bridge in rain\nNarrative: The bridge gives way.\nNarration: The traveler steps onto the bridge. The planks split beneath her feet.",
        "Title: Crossing\nVisual Prompt: wide shot of a traveler crossing a broken bridge in rain\nNarrative: The bridge gives way.\nNarration: The traveler steps onto the bridge. The planks split beneath her feet.",
    ])

    def fake_call(system, prompt, temperature=0.7, max_tokens=None):
        calls.append((system, prompt, max_tokens))
        return next(responses)

    monkeypatch.setattr("generate_story.call_llm", fake_call)
    scenes = generate_story_outline_granular(
        "A traveler crosses a storm valley", 1, "realist", "one traveler", "tense"
    )

    assert len(scenes) == 1
    assert scenes[0]["title"] == "Crossing"
    assert [call[2] for call in calls] == [1400, 1000, 1200, 1000]
    assert calls[0][0].startswith("You are the story bible editor")
    assert calls[1][0].startswith("You are a story architect")
    assert calls[2][0].startswith("You are a scene writer")
