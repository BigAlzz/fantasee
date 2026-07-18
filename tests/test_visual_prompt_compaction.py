"""Regression tests for scene prompt preservation before ComfyUI submission."""

from copy import deepcopy
import json
from pathlib import Path

import comfyui_utils


def _workflow():
    return {
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "positive prompt"},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "ugly, blurry, deformed"},
        },
    }


def test_visual_prompt_keeps_action_and_setting_when_compacted():
    prompt = (
        "wide shot of Mira, a scarred woman in a dark coat with cropped black hair "
        "and a chipped sword, framed by storm clouds, ruined towers, smoke, and "
        "cold blue light on a wet road; she fights three armored raiders in a "
        "burning city street, sword raised, "
        "with civilians running behind her and sparks crossing the frame. "
        + "Additional atmospheric background detail. " * 40
    )

    result = comfyui_utils.inject_prompt(
        deepcopy(_workflow()),
        positive_prompt=(prompt + ". " + comfyui_utils.DEFAULT_POSITIVE_GUARD_SUFFIX),
    )
    submitted = result["6"]["inputs"]["text"].lower()

    assert "fights three armored raiders" in submitted
    assert "burning city street" in submitted
    assert "head and shoulders" not in submitted
    assert "looking at viewer" not in submitted


def test_default_workflow_routes_text_through_checkpoint_clip():
    workflow = json.loads((Path(__file__).parents[1] / "workflow.json").read_text())

    assert not any(node.get("class_type") == "SeaArtLongClip" for node in workflow.values())
    assert workflow["6"]["inputs"]["clip"] == ["4", 1]
    assert workflow["7"]["inputs"]["clip"] == ["4", 1]


def test_default_workflow_compacts_prompt_to_standard_clip_limit():
    workflow = json.loads((Path(__file__).parents[1] / "workflow.json").read_text())
    prompt = "wide shot of Mira fighting raiders in a burning city street. " + (
        "Specific environmental detail remains visible. " * 30
    )

    result = comfyui_utils.inject_prompt(workflow, prompt)
    submitted = result["6"]["inputs"]["text"]

    assert "Specific environmental detail remains visible" in submitted
    assert comfyui_utils._approx_token_count(submitted) <= 77


def test_comic_book_preset_adds_dynamic_panel_direction_without_text():
    prompt = "wide shot of Mira vaulting over a ruined barricade as blue fire erupts"

    styled = comfyui_utils.apply_image_style(prompt, "comic book panels")
    negative = comfyui_utils.negative_prompt_for_style(
        comfyui_utils.DEFAULT_NEGATIVE,
        "comic book panels",
    )

    assert styled.startswith("dynamic comic-book action panel")
    assert "bold ink contours" in styled
    assert "comic, manga lineart" not in negative
    assert "speech bubble" in negative
