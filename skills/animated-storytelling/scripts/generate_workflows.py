#!/usr/bin/env python3
"""Generate ComfyUI workflow JSONs + narration text files from a story.md.

Usage: python generate_workflows.py <story_dir> <seed_start>

Parses story.md in the given directory, extracts all scenes (scene number, title,
seed, narration text, image prompt), and writes:
  - workflows/<prefix>_sceneNN.json   (ComfyUI API workflow)
  - narrations/narration_NN.txt       (plain text for TTS)

The story must follow the unified format (see templates/story-format.md):
  ### Scene N — "Title" (Seed: NNNN)
  **Narration:** text...
  **Image Prompt:** text...

Seeds are taken from the story file — seed_start is used as fallback.

Requires: Python 3.7+
"""

import json
import os
import re
import sys

CHECKPOINT = "Counterfeit-V3.0_fp16.safetensors"
RESOLUTION = (512, 768)
STEPS = 30
CFG = 7.0


def determine_negative(prompt_lower: str) -> list[str]:
    """Build scene-specific negative prompt based on prompt content."""
    neg = ["low quality", "blurry", "deformed", "bad anatomy"]

    has_time = False
    if any(w in prompt_lower for w in ["dawn", "sunrise", "morning", "golden", "daylight"]):
        neg.extend(["night", "darkness", "midnight"])
        has_time = True
    elif any(w in prompt_lower for w in ["night", "torchlight", "darkness", "moon"]):
        neg.extend(["daytime", "sunny", "bright", "cheerful"])
        has_time = True

    if any(w in prompt_lower for w in ["battle", "fight", "attack", "charge", "combat", "war", "surge"]):
        if not has_time:
            neg.extend(["peaceful", "quiet", "calm"])

    if any(w in prompt_lower for w in ["neanderthal", "warrior", "tribe", "fur", "pelt"]):
        neg.extend(["modern technology", "car", "city"])

    if any(w in prompt_lower for w in ["cave", "underground", "tunnel"]):
        neg.extend(["outdoor", "open sky", "sunny field"])

    if any(w in prompt_lower for w in ["sea", "ocean", "water", "flood", "wave", "raft"]):
        neg.extend(["desert", "dry", "arid"])

    return neg


def process_story(story_path: str, seed_fallback: int) -> int:
    """Parse story.md and generate all workflow JSONs + narration files.
    
    Returns number of scenes processed.
    """
    with open(story_path, "r", encoding="utf-8") as f:
        story = f.read()

    # Extract story slug from path for filename prefix
    story_dir = os.path.dirname(story_path)
    prefix_base = os.path.basename(story_dir)

    wf_dir = os.path.join(story_dir, "workflows")
    nar_dir = os.path.join(story_dir, "narrations")
    os.makedirs(wf_dir, exist_ok=True)
    os.makedirs(nar_dir, exist_ok=True)

    pattern = re.compile(
        r"### Scene (\d+) — \"([^\"]+)\" \(Seed: (\d+)\)\n"
        r"\*\*Narration:\*\* (.+?)\n\n"
        r"\*\*Image Prompt:\*\* (.+?)(?=\n\n### Scene|\n---|\Z)",
        re.DOTALL,
    )

    count = 0
    for match in pattern.finditer(story):
        num = int(match.group(1))
        title = match.group(2)
        seed = int(match.group(3))
        narration = match.group(4).strip()
        prompt = match.group(5).strip()

        neg_prompt = ", ".join(determine_negative(prompt.lower()))
        title_slug = title.replace(" ", "_").replace("'", "")
        prefix = f"{prefix_base}_scene{num:02d}_{title_slug}"

        workflow = {
            "1": {
                "inputs": {"ckpt_name": CHECKPOINT},
                "class_type": "CheckpointLoaderSimple",
            },
            "2": {
                "inputs": {"text": prompt, "clip": ["1", 1]},
                "class_type": "CLIPTextEncode",
            },
            "3": {
                "inputs": {"text": neg_prompt, "clip": ["1", 1]},
                "class_type": "CLIPTextEncode",
            },
            "4": {
                "inputs": {"width": RESOLUTION[0], "height": RESOLUTION[1], "batch_size": 1},
                "class_type": "EmptyLatentImage",
            },
            "5": {
                "inputs": {
                    "seed": seed,
                    "steps": STEPS,
                    "cfg": CFG,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                },
                "class_type": "KSampler",
            },
            "6": {
                "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
                "class_type": "VAEDecode",
            },
            "7": {
                "inputs": {"filename_prefix": prefix, "images": ["6", 0]},
                "class_type": "SaveImage",
            },
        }

        wf_path = os.path.join(wf_dir, f"{prefix_base}_scene{num:02d}.json")
        nar_path = os.path.join(nar_dir, f"narration_{num:02d}.txt")

        with open(wf_path, "w") as f:
            json.dump(workflow, f, indent=2)
        with open(nar_path, "w", encoding="utf-8") as f:
            f.write(narration)

        count += 1

    if count == 0:
        print(f"WARNING: No scenes parsed from {story_path}. Check format.")
        return 0

    print(f"Generated {count} workflow JSONs → {wf_dir}")
    print(f"Generated {count} narration files → {nar_dir}")
    return count


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_workflows.py <story_dir> [seed_fallback]")
        print("Example: python generate_workflows.py E:/hermes/workspace/bone_road 7301")
        sys.exit(1)

    story_dir = sys.argv[1]
    story_path = os.path.join(story_dir, "story.md")
    seed_fallback = int(sys.argv[2]) if len(sys.argv) > 2 else 7001

    if not os.path.isfile(story_path):
        print(f"ERROR: No story.md found in {story_dir}")
        sys.exit(1)

    process_story(story_path, seed_fallback)
