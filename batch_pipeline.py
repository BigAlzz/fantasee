#!/usr/bin/env python3
"""
Fantasee Batch Pipeline — Extend stories to target scene count and improve quality.

Usage:
  python batch_pipeline.py                        # Process all stories
  python batch_pipeline.py --target-scenes 20     # Extend to 20 scenes
  python batch_pipeline.py --target-stars 4.5     # Target critic rating
  python batch_pipeline.py --story <id>           # Process single story
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

OUTPUTS_DIR = Path(__file__).parent / "outputs"
SCRIPT_DIR = Path(__file__).parent


def atomic_write_json(path: Path, data) -> None:
    """Write JSON to disk atomically: write to .tmp, then os.replace."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def resolve_env():
    """Build environment with Xiaomi API keys."""
    env = dict(os.environ)
    # Unmask from auth.json
    hermes_home = Path(os.environ.get("HERMES_HOME", "E:\\hermes"))
    auth_path = hermes_home / "auth.json"
    try:
        with open(auth_path) as f:
            auth = json.load(f)
        for provider_creds in auth.get("credential_pool", {}).values():
            for cred in provider_creds:
                label = cred.get("label", "")
                token = cred.get("access_token", "")
                if token and not token.startswith("***"):
                    env[label] = token
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    # Ensure Xiaomi vars are set
    if "XIAOMI_API_KEY" not in env or env.get("XIAOMI_API_KEY", "").startswith("***"):
        # Try .env files
        for p in [Path("E:/hermes/.env"), Path.home() / ".env"]:
            if p.exists():
                for line in p.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("XIAOMI_API_KEY=") and not line.startswith("#"):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val and not val.startswith("***"):
                            env["XIAOMI_API_KEY"] = val
    if "XIAOMI_BASE_URL" not in env:
        env["XIAOMI_BASE_URL"] = "https://token-plan-sgp.xiaomimimo.com/v1"
    return env


def llm_call(messages, model="mimo-v2.5-pro", temperature=0.7, max_tokens=2048, timeout=120):
    """Call Xiaomi LLM API."""
    env = resolve_env()
    api_key = env.get("XIAOMI_API_KEY", "")
    base_url = env.get("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
    if not api_key:
        print("[pipeline] ERROR: No XIAOMI_API_KEY", file=sys.stderr)
        return None

    for attempt in range(3):
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            elif resp.status_code >= 500:
                # Try alternate header
                resp2 = requests.post(
                    f"{base_url}/chat/completions",
                    json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                    headers={"api-key": api_key, "Content-Type": "application/json"},
                    timeout=timeout,
                )
                if resp2.status_code == 200:
                    return resp2.json()["choices"][0]["message"]["content"]
            print(f"[pipeline] LLM error {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        except Exception as e:
            print(f"[pipeline] LLM exception: {e}", file=sys.stderr)
        time.sleep(2 * (attempt + 1))
    return None


def extract_json(text):
    """Extract JSON from LLM response, handling code blocks."""
    # Try code block first
    for pattern in [r"```json\s*([\s\S]*?)```", r"```\s*([\s\S]*?)```"]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                continue
    # Try array FIRST (handles [{...}] responses correctly)
    start = text.find("[")
    if start >= 0:
        depth = 0
        for end in range(start, len(text)):
            if text[end] == "[":
                depth += 1
            elif text[end] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:end + 1])
                    except json.JSONDecodeError:
                        continue
    # Try raw JSON object
    start = text.find("{")
    if start >= 0:
        depth = 0
        for end in range(start, len(text)):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:end + 1])
                    except json.JSONDecodeError:
                        continue
    return None


def generate_continuation_scenes(story_id, manifest, target_total):
    """Generate new scenes to reach target_total count."""
    scenes = manifest.get("scenes", [])
    current_count = len(scenes)
    if current_count >= target_total:
        print(f"  Already at {current_count} scenes (target: {target_total})")
        return False

    needed = target_total - current_count
    print(f"  Generating {needed} continuation scenes ({current_count} -> {target_total})...")

    # Get context from last 3 scenes
    context_scenes = scenes[-3:] if len(scenes) >= 3 else scenes
    context_text = ""
    for s in context_scenes:
        title = s.get("title", "Untitled")
        narr = s.get("narration", s.get("narration_text", ""))[:300]
        prompt = s.get("prompt", "")[:200]
        context_text += f"\nScene: {title}\nNarration: {narr}\nImage prompt: {prompt}\n"

    # Extract character info from existing scenes
    all_narrations = " ".join(s.get("narration", s.get("narration_text", "")) for s in scenes)
    all_prompts = " ".join(s.get("prompt", "") for s in scenes)

    concept = manifest.get("title", story_id) + ". " + (manifest.get("description", "")[:500])
    style = ", ".join(manifest.get("tags", []))

    system_prompt = f"""You are a story continuation writer for an interactive visual story.
Write exactly {needed} new scenes that continue from where the story left off.
The story style is: {style}

Each scene MUST have:
- "title": A evocative scene title (2-5 words)
- "prompt": A detailed image generation prompt (80-150 words, natural language prose, describing the visual scene in detail — characters, setting, lighting, mood, action). Include specific visual details like camera angle, lighting, and character positions.
- "narration": Narration text (60-120 words, dramatic storytelling tone)
- "narration_text": Same as narration (for compatibility)

Output ONLY a JSON array of scene objects. No other text."""

    user_prompt = f"""Story concept: {concept}

Previous scenes for context:
{context_text}

Write {needed} continuation scenes. Continue the story naturally — don't repeat what's happened. Raise the stakes, develop characters, build toward a climax.

Output as a JSON array."""

    response = llm_call([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ], temperature=0.8, max_tokens=4096, timeout=120)

    if not response:
        print("  ERROR: LLM call failed", file=sys.stderr)
        return False

    new_scenes = extract_json(response)
    if not isinstance(new_scenes, list):
        print(f"  ERROR: Could not parse LLM response as JSON array", file=sys.stderr)
        print(f"  Response preview: {response[:300]}", file=sys.stderr)
        return False

    # Normalize scene format
    for s in new_scenes:
        if "narration" not in s and "narration_text" in s:
            s["narration"] = s["narration_text"]
        if "narration_text" not in s and "narration" in s:
            s["narration_text"] = s["narration"]
        s.setdefault("image_filenames", [])
        s.setdefault("audio_filename", "")

    # Append to manifest
    manifest["scenes"].extend(new_scenes)
    print(f"  Added {len(new_scenes)} continuation scenes")
    return True


def generate_tts_for_scene(scene, scene_num, story_dir, story_id, voice="Dean"):
    """Generate TTS for a single scene if not already cached."""
    from tts_utils import generate_tts, get_audio_duration

    narration = scene.get("narration", scene.get("narration_text", ""))
    if not narration or len(narration.strip()) < 10:
        return False

    padded = f"{scene_num:02d}"
    audio_filename = f"tts_{story_id}_s{padded}.wav"
    audio_path = story_dir / audio_filename

    if audio_path.exists() and audio_path.stat().st_size > 1000:
        scene["audio_filename"] = audio_filename
        scene["audio_duration"] = get_audio_duration(str(audio_path))
        return True

    print(f"    [TTS] Scene {scene_num}: generating...", file=sys.stderr)
    ok = generate_tts(narration, str(audio_path), voice=voice)
    if ok:
        scene["audio_filename"] = audio_filename
        scene["audio_duration"] = get_audio_duration(str(audio_path))
        return True
    return False


def generate_image_for_scene(scene, scene_num, story_dir, story_id, image_index=1):
    """Generate an image for a scene via ComfyUI."""
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from comfyui_utils import generate_image, is_running
    except ImportError:
        print("    WARNING: comfyui_utils not available", file=sys.stderr)
        return None

    status = is_running()
    if not status.get("running", False):
        print("    WARNING: ComfyUI not running, skipping image generation", file=sys.stderr)
        return None

    prompt = scene.get("prompt", "")
    if not prompt:
        return None

    padded = f"{scene_num:02d}"
    safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", "")).strip("_")[:30]
    prefix = f"{story_id}_s{padded}_{safe_title}_{image_index:02d}"
    seed = hash(story_id + str(scene_num) + str(image_index)) % (2**32 - 1)

    print(f"    [IMG] Scene {scene_num}, image {image_index}...", file=sys.stderr)
    filename = generate_image(
        prompt=prompt,
        output_prefix=prefix,
        output_dir=str(story_dir),
        seed=seed,
        timeout=120,
    )
    return filename


def run_critic(story_id):
    """Run critic and return parsed result."""
    env = resolve_env()
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "critic.py"), story_id, "--json"],
            capture_output=True, text=True, timeout=300,
            cwd=str(SCRIPT_DIR), env=env,
        )
        if proc.returncode != 0:
            print(f"  Critic error: {proc.stderr[:300]}", file=sys.stderr)
            return None

        stdout = proc.stdout.strip()
        # Strip trailing non-JSON
        json_end = stdout.rfind("}")
        if json_end >= 0:
            stdout = stdout[:json_end + 1]
        return json.loads(stdout)
    except Exception as e:
        print(f"  Critic exception: {e}", file=sys.stderr)
        return None


def render_video(story_id):
    """Re-render the full story video."""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "render_video.py"), story_id],
            capture_output=True, text=True, timeout=600,
            cwd=str(SCRIPT_DIR),
        )
        return proc.returncode == 0
    except Exception as e:
        print(f"  Render error: {e}", file=sys.stderr)
        return False


def process_story(story_id, target_scenes=20, target_stars=4.5, voice="Dean", skip_images=False):
    """Full pipeline for a single story: extend -> TTS -> images -> critic -> improve."""
    story_dir = OUTPUTS_DIR / story_id
    manifest_path = story_dir / f"{story_id}.json"

    if not manifest_path.exists():
        print(f"ERROR: No manifest for {story_id}", file=sys.stderr)
        return False

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    current_count = len(scenes)

    print(f"\n{'='*60}")
    print(f"  Story: {story_id}")
    print(f"  Current: {current_count} scenes")
    print(f"  Target: {target_scenes} scenes, {target_stars}+ stars")
    print(f"{'='*60}")

    # Step 1: Extend to target scene count
    if current_count < target_scenes:
        print(f"\n[Step 1] Extending from {current_count} to {target_scenes} scenes...")
        # Generate scenes in batches of 5 to avoid LLM token limits
        while len(manifest["scenes"]) < target_scenes:
            batch_size = min(5, target_scenes - len(manifest["scenes"]))
            ok = generate_continuation_scenes(story_id, manifest, len(manifest["scenes"]) + batch_size)
            if not ok:
                print(f"  WARNING: Could not generate more scenes, stopping at {len(manifest['scenes'])}", file=sys.stderr)
                break
            # Save after each batch (atomic)
            atomic_write_json(manifest_path, manifest)
            time.sleep(1)  # Rate limit

    scenes = manifest.get("scenes", [])
    print(f"\n  Scene count: {len(scenes)}")

    # Step 2: Generate TTS for all scenes without audio
    print(f"\n[Step 2] Generating TTS for scenes...")
    tts_count = 0
    for i, scene in enumerate(scenes):
        if not scene.get("audio_filename") or not (story_dir / scene["audio_filename"]).exists():
            if generate_tts_for_scene(scene, i + 1, story_dir, story_id, voice=voice):
                tts_count += 1
                # Save after each TTS (atomic)
                atomic_write_json(manifest_path, manifest)
    print(f"  Generated {tts_count} new TTS files")

    # Step 3: Generate images for scenes without images
    if not skip_images:
        print(f"\n[Step 3] Generating images for scenes...")
        img_count = 0
        for i, scene in enumerate(scenes):
            existing = len(scene.get("image_filenames", []))
            if existing < 2:  # Ensure at least 2 images per scene
                for img_idx in range(existing + 1, 3):  # Add up to 2 images
                    filename = generate_image_for_scene(scene, i + 1, story_dir, story_id, image_index=img_idx)
                    if filename:
                        scene.setdefault("image_filenames", []).append(filename)
                        img_count += 1
                        atomic_write_json(manifest_path, manifest)
                    else:
                        break  # ComfyUI might be down
        print(f"  Generated {img_count} new images")

    # Step 4: Save manifest (atomic)
    atomic_write_json(manifest_path, manifest)

    # Step 5: Run critic loop
    print(f"\n[Step 5] Running critic improvement loop...")
    for round_num in range(1, 4):  # Max 3 rounds
        print(f"\n  --- Round {round_num} ---")
        review = run_critic(story_id)
        if not review:
            print("  Critic failed, skipping improvement", file=sys.stderr)
            break

        rating = review.get("review", {}).get("overall_score", 0)
        stars = review.get("review", {}).get("stars", 0)
        badge = review.get("review", {}).get("badge", "")
        print(f"  Rating: {rating}/10 ({stars}* {badge})")

        if stars >= target_stars:
            print(f"  Target reached: {stars}* >= {target_stars}*")
            break

        # Improve weak scenes
        scene_reviews = review.get("scene_reviews", [])
        if not scene_reviews:
            print("  No per-scene reviews, skipping improvement", file=sys.stderr)
            break

        # Sort by score, improve weakest
        weak = sorted(enumerate(scene_reviews), key=lambda x: x[1].get("score", 10))
        improve_count = min(3, len(weak))

        for idx, _ in weak[:improve_count]:
            if idx >= len(scenes):
                continue
            scene = scenes[idx]
            print(f"  Improving scene {idx + 1}: {scene.get('title', '?')}...")

            # Refine prompt via LLM
            old_prompt = scene.get("prompt", "")
            new_prompt = llm_call([
                {"role": "system", "content": ("Improve this image generation prompt. "
                                               "Be more vivid and detailed. "
                                               "Output ONLY the improved prompt. "
                                               "80-150 words, natural language prose. "
                                               "When the framing shows a character's face, "
                                               "explicitly include 'a well-defined human nose' "
                                               "and 'natural human facial features' to prevent "
                                               "the model defaulting to a deformed / animalistic "
                                               "nose on DreamShaper-class checkpoints.")},
                {"role": "user", "content": old_prompt},
            ], temperature=0.7, max_tokens=512)
            if new_prompt:
                scene["prompt"] = new_prompt.strip().strip('"')

            # Add another image
            if not skip_images:
                existing = len(scene.get("image_filenames", []))
                filename = generate_image_for_scene(scene, idx + 1, story_dir, story_id, image_index=existing + 1)
                if filename:
                    scene.setdefault("image_filenames", []).append(filename)

            atomic_write_json(manifest_path, manifest)

    # Step 6: Render video
    print(f"\n[Step 6] Rendering video...")
    render_ok = render_video(story_id)
    print(f"  Render: {'OK' if render_ok else 'Failed'}")

    # Final state
    final_review = run_critic(story_id)
    final_stars = final_review.get("review", {}).get("stars", 0) if final_review else 0
    final_rating = final_review.get("review", {}).get("overall_score", 0) if final_review else 0
    final_badge = final_review.get("review", {}).get("badge", "") if final_review else ""

    print(f"\n{'='*60}")
    print(f"  FINAL: {len(scenes)} scenes, {final_rating}/10 ({final_stars}* {final_badge})")
    print(f"{'='*60}")

    return final_stars >= target_stars


def main():
    parser = argparse.ArgumentParser(description="Fantasee Batch Pipeline")
    parser.add_argument("--target-scenes", type=int, default=20, help="Target scene count")
    parser.add_argument("--target-stars", type=float, default=4.5, help="Target critic star rating")
    parser.add_argument("--voice", default="Dean", help="TTS voice")
    parser.add_argument("--story", help="Process single story ID")
    parser.add_argument("--skip-images", action="store_true", help="Skip image generation (ComfyUI may be off)")
    args = parser.parse_args()

    # Find all stories
    if args.story:
        stories = [args.story]
    else:
        stories = []
        for d in OUTPUTS_DIR.iterdir():
            if d.is_dir() and (d / f"{d.name}.json").exists():
                stories.append(d.name)
        stories.sort()

    print(f"Processing {len(stories)} stories: {', '.join(stories)}")
    print(f"Target: {args.target_scenes} scenes, {args.target_stars}+ stars")
    print(f"Voice: {args.voice}")
    print()

    results = {}
    for story_id in stories:
        ok = process_story(
            story_id,
            target_scenes=args.target_scenes,
            target_stars=args.target_stars,
            voice=args.voice,
            skip_images=args.skip_images,
        )
        results[story_id] = ok

    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    for sid, ok in results.items():
        status = "PASS" if ok else "NEEDS WORK"
        print(f"  {sid}: {status}")
    print()


if __name__ == "__main__":
    main()
