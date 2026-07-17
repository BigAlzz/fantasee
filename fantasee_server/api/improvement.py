"""Per-scene improvement + full render endpoints.

The "improvement" endpoints operate on a single scene of an existing
story: regenerate its images, add an additional image, or refine its
visual prompt via the LLM. The full-render endpoint re-runs
``render_video.py`` for the whole story (or a single scene).

All endpoints are synchronous — they read the manifest, do the work,
write the manifest back, and return. For long-running improvements
that span the whole story see ``api/actions`` (improve / improve-loop).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

from fastapi import APIRouter, Body, HTTPException

from fantasee_server.discovery import ensure_title_slide_for_manifest
from fantasee_server.library import story_completion_report
from fantasee_server.paths import (
    GEN_OUTPUTS,
    STORY_VIEWER_DIR,
    generated_story_dir,
)
from fantasee_server.security import validate_provider_url
from fantasee_server.state import (
    _resolve_env_var,
    atomic_write_json,
    requests,
)


router = APIRouter(tags=["improvement"])


@router.post("/api/stories/{story_id}/scenes/{scene_idx}/regenerate")
async def regenerate_scene(story_id: str, scene_idx: int):
    """Regenerate images and TTS for a single scene."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")

    scene = scenes[scene_idx]
    scene_num = scene_idx + 1
    padded = f"{scene_num:02d}"
    safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", "")).strip("_")[:30]

    # Delete old images
    for old_img in scene.get("image_filenames", []):
        old_path = story_dir / old_img
        if old_path.exists():
            old_path.unlink()

    # Generate new image
    sys.path.insert(0, str(STORY_VIEWER_DIR))
    from comfyui_utils import generate_image, is_running
    status = is_running()
    new_filename = None
    if status.get("running", False):
        seed = hash(story_id + str(scene_num)) % (2**32 - 1)
        prefix = f"{story_id}_s{padded}_{safe_title}_01"
        new_filename = generate_image(
            prompt=scene["prompt"],
            output_prefix=prefix,
            output_dir=str(story_dir),
            seed=seed,
            timeout=600,
        )
    scene["image_filenames"] = [new_filename] if new_filename else []

    # Regenerate TTS
    from tts_utils import generate_tts, get_audio_duration
    narration = scene.get("narration", scene.get("narration_text", ""))
    if narration:
        old_audio = scene.get("audio_filename", "")
        if old_audio:
            old_path = story_dir / old_audio
            if old_path.exists():
                old_path.unlink()
            audio_filename = f"tts_{story_id}_s{padded}.wav"
            audio_path = str(story_dir / audio_filename)
            # Prefer the explicit "tone" field on the manifest, fall back
            # to the legacy position in tags ([style, tone, "generated"]).
            story_tone = manifest.get("tone") or ""
            if not story_tone:
                tags = manifest.get("tags", [])
                story_tone = tags[1] if len(tags) >= 2 else ""
            ok = generate_tts(narration, audio_path, voice="Dean", tone=story_tone or "normal")
            if ok:
                scene["audio_filename"] = audio_filename
                scene["audio_duration"] = get_audio_duration(audio_path)

    atomic_write_json(manifest_path, manifest)
    return {"status": "ok", "scene": scene}


@router.post("/api/stories/{story_id}/scenes/{scene_idx}/add-image")
async def add_scene_image(story_id: str, scene_idx: int):
    """Add an additional image to a scene for more visual variety."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")

    scene = scenes[scene_idx]
    scene_num = scene_idx + 1
    padded = f"{scene_num:02d}"
    safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", "")).strip("_")[:30]

    sys.path.insert(0, str(STORY_VIEWER_DIR))
    from comfyui_utils import generate_image, is_running
    status = is_running()
    if not status.get("running", False):
        raise HTTPException(status_code=503, detail="ComfyUI not running")

    existing = len(scene.get("image_filenames", []))
    seed = hash(story_id + str(scene_num) + str(existing)) % (2**32 - 1)
    prefix = f"{story_id}_s{padded}_{safe_title}_{existing + 1:02d}"

    filename = generate_image(
        prompt=scene["prompt"],
        output_prefix=prefix,
        output_dir=str(story_dir),
        seed=seed,
        timeout=600,
    )

    if filename:
        scene.setdefault("image_filenames", []).append(filename)
        atomic_write_json(manifest_path, manifest)
        return {"status": "ok", "filename": filename, "total_images": len(scene["image_filenames"])}

    raise HTTPException(status_code=500, detail="Image generation failed")


@router.post("/api/stories/{story_id}/scenes/{scene_idx}/refine-prompt")
async def refine_prompt(story_id: str, scene_idx: int, body: dict = Body(default=None)):
    """Use LLM to improve a scene's visual prompt, then auto-regenerate the image.

    The refinement flow:
    1. LLM rewrites the scene's visual prompt (more vivid + specific).
    2. The new prompt replaces the old one in the manifest.
    3. If ComfyUI is running, the scene's images are regenerated in-place
       so the user sees the visual change immediately.
    4. TTS is left alone — the narration is unchanged so the audio stays
       in sync with the title slide + subtitles.
    """
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")

    scene = scenes[scene_idx]
    instruction = (body or {}).get("instruction", "")

    system = ("You are an expert at writing image generation prompts. "
              "Improve the given prompt to be more detailed, vivid, and visually specific. "
              "Keep the same scene and characters. Output ONLY the improved prompt, nothing else. "
              "80-150 words, natural language prose, not tag lists. "
              "Whenever a character's face is in frame (medium shot, close-up, "
              "portrait, three-quarter, profile, or any framing where the face "
              "is visible at all), explicitly describe their facial features "
              "with a well-defined human nose, natural human facial structure, "
              "and clear skin — otherwise the model will default to a "
              "deformed / animalistic nose. Include a phrase such as 'a "
              "well-defined human nose' and 'natural human facial features'.")
    user_prompt = f"Improve this image generation prompt:\n\n{scene['prompt']}"
    if instruction:
        user_prompt += f"\n\nSpecific direction: {instruction}"

    api_key = _resolve_env_var("XIAOMI_API_KEY")
    base_url = _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
    try:
        base_url = validate_provider_url(base_url, kind="llm")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resp = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": "mimo-v2.5-pro",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_completion_tokens": 512,
        },
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=120,
        allow_redirects=False,
    )
    resp.raise_for_status()
    new_prompt = resp.json()["choices"][0]["message"]["content"].strip().strip('"')

    old_prompt = scene["prompt"]
    scene["prompt"] = new_prompt

    # Auto-regenerate the image so the user actually sees the result.
    # If ComfyUI isn't running, we still save the new prompt and the
    # user can run "Re-render" later. We do NOT touch TTS — the
    # narration hasn't changed so the audio stays in sync.
    image_regenerated = False
    image_error = None
    new_filenames = []
    try:
        sys.path.insert(0, str(STORY_VIEWER_DIR))
        from comfyui_utils import generate_image, is_running
        if is_running().get("running", False):
            # Drop the old images so the new prefix starts fresh
            for old in scene.get("image_filenames", []):
                try:
                    (story_dir / old).unlink(missing_ok=True)
                except OSError:
                    pass

            scene_num = scene_idx + 1
            padded = f"{scene_num:02d}"
            safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", "")).strip("_")[:30]
            # Use a fresh seed so the new prompt actually produces
            # something different from the cached image.
            seed = hash(f"{story_id}{padded}refine") % (2**32 - 1)
            n_imgs = max(1, len(scene.get("image_filenames") or [None]))
            for i in range(n_imgs):
                prefix = f"{story_id}_s{padded}_{safe_title}_{(i + 1):02d}"
                filename = generate_image(
                    prompt=new_prompt,
                    output_prefix=prefix,
                    output_dir=str(story_dir),
                    seed=seed + i,
                    timeout=300,
                )
                if filename:
                    new_filenames.append(filename)
            if new_filenames:
                scene["image_filenames"] = new_filenames
                image_regenerated = True
        else:
            image_error = "ComfyUI not running — image not regenerated"
    except Exception as e:
        image_error = f"Image regen failed: {e}"

    atomic_write_json(manifest_path, manifest)

    return {
        "status": "ok",
        "old_prompt": old_prompt,
        "new_prompt": new_prompt,
        "image_regenerated": image_regenerated,
        "image_error": image_error,
        "image_filenames": scene.get("image_filenames", []),
    }


@router.post("/api/stories/{story_id}/render")
async def render_story(story_id: str, body: dict = Body(default=None)):
    """Re-render video. Pass scene_idx for single scene, or omit for full story."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")
    completion = story_completion_report(story_id, story_dir=story_dir)
    blocking = {"story_text", "audio", "subtitles", "shot_image", "shot_timeline"}
    blocked = sorted(blocking.intersection(completion.get("missing") or []))
    if blocked:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Rendering is blocked until the approved timeline inputs are ready",
                "missing": blocked,
                "issues": [issue for issue in completion.get("issues", []) if issue.get("kind") in blocked][:20],
            },
        )
    try:
        ensure_title_slide_for_manifest(
            story_dir,
            json.loads(manifest_path.read_text(encoding="utf-8")),
        )
    except (json.JSONDecodeError, OSError):
        pass

    scene_idx = (body or {}).get("scene_idx")
    cmd = [sys.executable, str(STORY_VIEWER_DIR / "render_video.py"), story_id]
    if scene_idx is not None:
        cmd += ["--scene-only", str(scene_idx + 1)]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          cwd=str(STORY_VIEWER_DIR))
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    # Parse the "Done! N scenes rendered" footer so the caller can distinguish
    # a real render from a silent no-op (story has no images / no audio).
    # Without this check a 4-second "Done! 0 scenes rendered" looked identical
    # to a successful 5-minute render.
    rendered_count = 0
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("Done!"):
            # "Done! 0 scenes rendered in 4s" / "Done! 5 scenes rendered in 312s"
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                rendered_count = int(parts[1])
            break

    if proc.returncode not in (0, 2):
        raise HTTPException(
            status_code=500,
            detail=f"Render failed (exit {proc.returncode}): {stderr[-500:] or stdout[-500:]}",
        )

    if proc.returncode == 2 or rendered_count == 0:
        # render_video.py exits 2 ("nothing to do") when 0 scenes had both
        # images and audio. Return 200 with status=no_op so the GUI can
        # surface a clear message instead of "Render complete!".
        return {
            "status": "no_op",
            "message": (
                "No scenes rendered — story has no images and/or audio on disk. "
                "Run improve-loop (with ComfyUI running) to generate images first."
            ),
            "scene_idx": scene_idx,
            "scenes_rendered": 0,
            "render_output_tail": stdout[-400:],
        }

    return {
        "status": "ok",
        "message": f"Render complete ({rendered_count} scene(s))",
        "scene_idx": scene_idx,
        "scenes_rendered": rendered_count,
    }
