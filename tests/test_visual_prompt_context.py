from generate_story import build_visual_prompt_request, extract_visual_sentence


def test_visual_prompt_uses_one_visual_sentence_and_compact_continuity_pack():
    scene = {
        "title": "The Garage Door",
        "narrative": (
            "Mara lifts the dented garage door and finds the radio glowing inside. "
            "A storm rolls over the roofs while the old generator coughs awake."
        ),
        "narration": "This is a long narration passage that should not be sent to the image prompt.",
        "prompt": "An old garage in a storm",
    }

    visual_sentence = extract_visual_sentence(scene)
    request = build_visual_prompt_request(
        scene,
        scene_index=2,
        total_scenes=5,
        characters="Mara wears a red raincoat; the brass radio and dented generator recur.",
        previous_scene={
            "prompt": "Mara crosses the same row of low Johannesburg roofs in her red raincoat.",
        },
    )

    assert visual_sentence == "Mara lifts the dented garage door and finds the radio glowing inside."
    assert "Visual sentence:" in request
    assert visual_sentence in request
    assert "red raincoat" in request
    assert "dented generator" in request
    assert "same row of low Johannesburg roofs" in request
    assert "long narration passage" not in request
    assert "old garage in a storm" not in request

