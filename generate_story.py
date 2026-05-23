r"""
Hermes Story Generation Pipeline
==================================
Takes a story concept, generates a scene-by-scene outline via OpenCode API,
optionally renders each scene through ComfyUI, and saves results to outputs.

Usage:
  python generate_story.py --concept "A lone ranger..." --scenes 5 --style "fantasy painterly"

Outputs:
  - Writes PNG frames to E:\hermes\workspace\outputs\
  - Writes story metadata JSON to E:\hermes\workspace\outputs\_stories\
  - Prints a JSON manifest to stdout for the backend to consume
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

# ── Config ─────────────────────────────────────────────────────────────
OUTPUTS = Path(r"E:\hermes\workspace\outputs")
STORY_META_DIR = OUTPUTS / "_stories"

OPFNFILE_BASE = "https://api.opencode.ai"
# Use Go tier for generation
OPFNFILE_API_KEY = os.environ.get("OPENCODE_GO_API_KEY", "")
# Models from: https://opencode.ai/zen/go/v1/models
OPFNFILE_MODEL = "deepseek-v4-flash"  # Fast, capable model

# ComfyUI config
COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188
COMFYUI_BASE = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"

DEFAULT_WORKFLOW = r"E:\hermes\workspace\siege_story\workflows\siege_scene01_polished.json"

# ── Emit progress updates (read by the backend) ────────────────────────


def emit(status: str, message: str, progress: float = None):
    """Emit a progress message as a JSON line to stdout."""
    msg = {"status": status, "message": message}
    if progress is not None:
        msg["progress"] = progress
    print(f"__PROGRESS__:{json.dumps(msg)}", flush=True)


# ── LLM-based Scene Generation (via OpenCode Go) ──────────────────────


def call_llm(system: str, prompt: str, temperature: float = 0.7) -> Optional[str]:
    """Call the OpenCode Go API for story generation."""
    if not OPFNFILE_API_KEY:
        emit("error", "OPENCODE_GO_API_KEY not set in environment")
        return None

    payload = {
        "model": OPFNFILE_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": 4096,
    }
    try:
        resp = requests.post(
            f"{OPFNFILE_BASE}/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {OPFNFILE_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        emit("error", f"LLM call failed: {e}")
        return None


STORY_OUTLINE_SYSTEM = """You are a creative writing assistant specializing in visual storytelling. 
Your task is to generate a detailed scene-by-scene breakdown for an illustrated story.

For each scene, provide:
1. Scene title (short, evocative)
2. Visual prompt (detailed description for image generation — include character descriptions, lighting, composition, mood, color palette)
3. Narrative description (what happens in this scene)

Format each scene as:

--- SCENE 1
Title: <title>
Visual Prompt: <detailed image generation prompt — 80-150 words covering subject, setting, lighting, composition, mood>
Narrative: <what happens — 30-60 words>

Match tone and style requested. For fantasy/painterly style, use vivid, atmospheric language in prompts."""


def generate_story_outline(concept: str, num_scenes: int, style: str,
                           characters: str, tone: str) -> Optional[dict]:
    """Generate a complete story outline using the local LLM."""
    emit("running", "Generating story outline with LLM...", 0.05)

    char_section = f"\nCharacters: {characters}" if characters else ""

    user_prompt = f"""Create a {num_scenes}-scene story outline based on this concept:

Concept: {concept}
Style: {style}
Tone: {tone}{char_section}

Generate exactly {num_scenes} scenes. Each scene should flow naturally from the last.
Make each visual prompt detailed enough for AI image generation — include character
appearance, lighting, camera angle, colors, and atmosphere."""

    response = call_llm(STORY_OUTLINE_SYSTEM, user_prompt)
    if not response:
        return None

    # Parse the response into structured scenes
    scenes = []
    current = None
    for line in response.strip().split("\n"):
        line = line.strip()
        if re.match(r"^---\s*SCENE\s*(\d+)", line, re.IGNORECASE):
            if current:
                scenes.append(current)
            current = {"title": "", "prompt": "", "narrative": ""}
        elif current:
            low = line.lower()
            if low.startswith("title:"):
                current["title"] = line.split(":", 1)[1].strip()
            elif low.startswith("visual prompt:"):
                current["prompt"] = line.split(":", 1)[1].strip()
            elif low.startswith("narrative:"):
                current["narrative"] = line.split(":", 1)[1].strip()
            else:
                # Append continuation to the most recently set field
                if current["narrative"] and not current["prompt"].endswith(line):
                    if current["prompt"] and not current["narrative"]:
                        current["prompt"] += " " + line
                    else:
                        current["narrative"] += " " + line
                elif current["prompt"]:
                    current["prompt"] += " " + line

    if current:
        scenes.append(current)

    # Clean up: ensure every scene has a prompt
    for s in scenes:
        if not s["prompt"] or len(s["prompt"]) < 20:
            s["prompt"] = s.get("narrative", s["title"])

    if not scenes:
        # Fallback: parse as paragraphs
        paragraphs = [p.strip() for p in response.split("\n\n") if p.strip()]
        for i, p in enumerate(paragraphs[:num_scenes]):
            scenes.append({
                "title": f"Scene {i + 1}",
                "prompt": p,
                "narrative": p[:100],
            })

    emit("running", f"Generated {len(scenes)} scene prompts.", 0.15)
    return scenes


# ── ComfyUI Image Generation ───────────────────────────────────────────


def generate_scene_image(scene: dict, scene_num: int, story_id: str,
                         seed: int = None) -> Optional[str]:
    """Render a scene prompt through ComfyUI. Returns the output filename."""
    emit("running", f"Generating scene {scene_num}: {scene['title']}...",
         0.15 + (scene_num * 0.75 / 30))

    prompt_text = scene.get("prompt", "")
    if not prompt_text:
        emit("warning", f"Scene {scene_num} has no prompt, skipping image generation.")
        return None

    # Load the base workflow and inject the prompt + seed
    try:
        with open(DEFAULT_WORKFLOW, "r", encoding="utf-8") as f:
            workflow = json.load(f)
    except Exception as e:
        emit("error", f"Failed to load workflow: {e}")
        return None

    # Inject prompt into CLIPTextEncode node (node 2 = positive prompt)
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") == "CLIPTextEncode":
            node["inputs"]["text"] = prompt_text
            break

    # Set seed in KSampler node
    use_seed = seed or (hash(story_id + str(scene_num)) % (2**32 - 1))
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") == "KSampler":
            node["inputs"]["seed"] = use_seed
            break

    # Set filename prefix in SaveImage
    scene_padded = f"{scene_num:02d}"
    safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene["title"]).strip("_")[:30]
    prefix = f"{story_id}_scene{scene_padded}_{safe_title}"
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") == "SaveImage":
            node["inputs"]["filename_prefix"] = prefix
            break

    # Submit to ComfyUI
    try:
        # Check if ComfyUI is running
        resp = requests.get(f"{COMFYUI_BASE}/internal/queue", timeout=5)
        if resp.status_code != 200:
            emit("warning", "ComfyUI not available, saving prompt for later rendering.")
            return None

        # Submit workflow
        payload = {"prompt": workflow}
        resp = requests.post(f"{COMFYUI_BASE}/prompt", json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        prompt_id = result.get("prompt_id", "")

        # Poll for completion
        timeout = 180  # 3 minutes per scene
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                history_resp = requests.get(
                    f"{COMFYUI_BASE}/history/{prompt_id}", timeout=5)
                if history_resp.status_code == 200:
                    history = history_resp.json()
                    if prompt_id in history:
                        # Find output images
                        outputs = history[prompt_id].get("outputs", {})
                        for node_out in outputs.values():
                            for img_list in node_out.values():
                                if isinstance(img_list, list):
                                    for img in img_list:
                                        if isinstance(img, dict) and img.get("filename"):
                                            return img["filename"]
                        return f"{prefix}_00001_.png"
                time.sleep(3)
            except Exception:
                time.sleep(3)
        emit("warning", f"Scene {scene_num} timed out waiting for ComfyUI.")
        return None

    except requests.ConnectionError:
        emit("warning", "ComfyUI not running. Image generation deferred.")
        return None
    except Exception as e:
        emit("error", f"ComfyUI error on scene {scene_num}: {e}")
        return None


# ── Story ID Generation ────────────────────────────────────────────────


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text[:40] or "untitled"


# ── Manifest ───────────────────────────────────────────────────────────


def save_story_manifest(story_id: str, title: str, subtitle: str,
                        description: str, tags: list, scenes: list):
    """Save the story manifest to the outputs/_stories/ directory."""
    STORY_META_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": story_id,
        "title": title,
        "subtitle": subtitle,
        "description": description,
        "tags": tags,
        "hero_image": scenes[0].get("image_filenames", [None])[0] if scenes else None,
        "scene_count": len(scenes),
        "scenes": scenes,
    }
    path = STORY_META_DIR / f"{story_id}.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    emit("running", f"Saved story manifest to {path}", 1.0)


# ── Main Pipeline ──────────────────────────────────────────────────────


def run_pipeline(concept: str, num_scenes: int = 10, style: str = "fantasy painterly",
                 characters: str = "", tone: str = "dramatic",
                 skip_images: bool = False):
    """Run the full story generation pipeline."""
    emit("queued", "Starting generation pipeline...")

    # 1. Generate story title & ID
    title_prompt = f"Generate a short, evocative story title for: {concept}\n\nTitle only, no quotes, max 6 words."
    title_result = call_llm(
        "You are a title generator. Output only the title, no quotes, no commentary.",
        title_prompt, temperature=0.8)
    story_title = (title_result or "Untitled Story").strip().strip('"').strip("'")
    story_id = slugify(story_title)
    emit("running", f"Story: \"{story_title}\" (id: {story_id})", 0.02)

    # 2. Generate story description
    desc_prompt = f"""Write a 2-3 sentence description for a story titled "{story_title}" with this concept:
{concept}
Style: {style}
Tone: {tone}
Be evocative but concise."""
    desc_result = call_llm(
        "You write compelling story descriptions. 2-3 sentences only.", desc_prompt)
    description = desc_result or concept[:200]

    # 3. Generate scene outline
    scenes = generate_story_outline(concept, num_scenes, style, characters, tone)
    if not scenes:
        emit("error", "Failed to generate scene outline.")
        return None

    # 4. (Optional) Render images via ComfyUI
    output_scenes = []
    for i, scene in enumerate(scenes):
        s = {
            "scene": f"{i + 1:02d}",
            "title": scene.get("title", f"Scene {i + 1}"),
            "prompt": scene.get("prompt", ""),
            "narrative": scene.get("narrative", ""),
            "seed": hash(story_id + str(i)) % (2**32 - 1),
            "image_filenames": [],
        }

        if not skip_images:
            img = generate_scene_image(scene, i + 1, story_id, s["seed"])
            if img:
                s["image_filenames"] = [img]

        output_scenes.append(s)

    # 5. Determine tags from style + tone
    tags = [style, tone, "generated"]

    # 6. Save manifest
    save_story_manifest(story_id, story_title, concept[:60],
                        description, tags, output_scenes)

    emit("done", "Story generation complete!", 1.0)

    # 7. Output final manifest to stdout for the backend
    manifest = {
        "id": story_id,
        "title": story_title,
        "scene_count": len(output_scenes),
        "status": "complete",
    }
    print(f"__RESULT__:{json.dumps(manifest)}")

    return manifest


# ── CLI Entry Point ────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a story via Hermes pipeline")
    parser.add_argument("--concept", required=True, help="Story concept description")
    parser.add_argument("--scenes", type=int, default=10, help="Number of scenes")
    parser.add_argument("--style", default="fantasy painterly", help="Art style")
    parser.add_argument("--characters", default="", help="Character descriptions")
    parser.add_argument("--tone", default="dramatic", help="Story tone")
    parser.add_argument("--skip-images", action="store_true", help="Skip ComfyUI rendering")
    args = parser.parse_args()

    try:
        result = run_pipeline(
            concept=args.concept,
            num_scenes=args.scenes,
            style=args.style,
            characters=args.characters,
            tone=args.tone,
            skip_images=args.skip_images,
        )
        if result:
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        emit("error", f"Pipeline failed: {e}")
        print(f"__RESULT__:{{\"status\":\"error\",\"message\":\"{e}\"}}", file=sys.stderr)
        sys.exit(1)
