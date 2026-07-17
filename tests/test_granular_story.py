from generate_story import refine_scenes_granular
from fantasee_server.llm_adapter import GranularLLMAdapter, TokenBudget


def test_scene_refinement_is_bounded_and_rejects_malformed_revision():
    responses = iter([
        "Title: Revised\nVisual Prompt: wide shot of a ruined gate\n"
        "Narrative: The gate opens.\nNarration: The gate opens over the valley.",
        "not a scene",
    ])

    def fake_call(_system, _prompt, temperature=0.7, max_tokens=None):
        assert max_tokens == 1000
        return next(responses)

    scenes = [
        {"title": "Old", "prompt": "old prompt", "narrative": "old", "narration": "old"},
        {"title": "Keep", "prompt": "keep prompt", "narrative": "keep", "narration": "keep"},
    ]
    refined = refine_scenes_granular(
        scenes,
        concept="A gate in a valley",
        style="fantasy",
        tone="quiet",
        characters="one traveler",
        adapter=GranularLLMAdapter(fake_call, budget=TokenBudget(limit=3000)),
    )

    assert refined[0]["title"] == "Revised"
    assert refined[1] == scenes[1]
