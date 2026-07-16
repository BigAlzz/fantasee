"""Iterative improvement workers.

Two background workers that operate on existing stories:

* ``_run_improve_loop_sync`` — runs the critic, identifies the
  weakest scenes, and rotates through them, applying a combination
  of: prompt refinement, TTS regeneration, image addition,
  subtitle regeneration, and story-level typo fixes. Loops until
  the target star rating is hit or ``max_rounds`` is reached.

* ``_run_auto_improve_sync`` — a single-pass version: critic → pick
  the N weakest scenes → refine prompt + regenerate image → re-render.
  Used by the ``/api/stories/{id}/improve`` endpoint.

Both run in an executor (synchronous subprocess + LLM calls) and
stream progress through a callback supplied by the caller.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fantasee_server.paths import STORY_VIEWER_DIR, generated_story_dir
from fantasee_server.security import validate_provider_url
from fantasee_server.state import _resolve_env_var, atomic_write_json


# ── Generic helpers used by both workers ──────────────────────────

def _classify_scene_issues(issues: list[str]) -> dict:
    """Map a list of critic issue strings to the actions that can fix them.

    Returns a dict with action flags and a list of human-readable reasons.
    """
    actions = {
        "refine_narration": False,
        "regen_tts": False,
        "regen_subtitles": False,
        "add_images": False,
    }
    reasons = []
    for issue in issues:
        low = issue.lower()
        if any(kw in low for kw in ("run-on", "choppy", "ellipses", "very short", "very long",
                                     "rushed", "abrupt", "unbalanced", "no narration")):
            actions["refine_narration"] = True
            reasons.append(f"narration: {issue}")
        if any(kw in low for kw in ("too short", "very small", "silent", "missing audio", "no audio")):
            actions["regen_tts"] = True
            reasons.append(f"audio: {issue}")
        if any(kw in low for kw in ("missing:", "very small", "no images", "low quality")) and ".png" in low:
            actions["add_images"] = True
            reasons.append(f"image: {issue}")
        if any(kw in low for kw in ("subtitle", "vtt", "cue", "overlap", "beyond audio",
                                     "large gap")):
            actions["regen_subtitles"] = True
            reasons.append(f"subtitles: {issue}")
    return actions, reasons


def _extract_typo_pairs(continuity_issues: list[str]) -> list[tuple[str, str]]:
    """Pull (variant_a, variant_b) pairs from continuity 'Possible typo' lines."""
    pairs = []
    pattern = re.compile(r"Possible typo:\s*'([^']+)'\s*vs\s*'([^']+)'")
    for issue in continuity_issues:
        m = pattern.search(issue)
        if m:
            pairs.append((m.group(1), m.group(2)))
    return pairs


def _llm_call_text(api_key: str, base_url: str, system: str, user: str,
                   temperature: float = 0.7, max_tokens: int = 512, timeout: int = 120) -> Optional[str]:
    """Single-shot LLM call returning the response text or None on failure."""
    from fantasee_server.state import requests
    try:
        base_url = validate_provider_url(base_url, kind="llm")
        resp = requests.post(
            f"{base_url}/chat/completions",
            json={
                "model": "mimo-v2.5-pro",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
            },
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
            allow_redirects=False,
        )
        if resp.ok:
            return resp.json()["choices"][0]["message"]["content"].strip().strip('"')
    except Exception as e:
        print(f"[improve] LLM call failed: {e}", file=sys.stderr)
    return None


def _apply_typo_fix(scenes: list[dict], pairs: list[tuple[str, str]]) -> int:
    """Replace misspelled character names with the most-frequent variant across all scenes.

    Picks the longer/more-common variant for each pair (the one the critic flagged
    less often) and rewrites narration/narration_text/prompt in every scene.
    """
    if not pairs:
        return 0
    fixed = 0
    for wrong, right in pairs:
        # Apply to all scenes in the manifest
        for sc in scenes:
            for key in ("narration", "narration_text", "narrative", "prompt"):
                val = sc.get(key, "")
                if isinstance(val, str) and wrong in val:
                    sc[key] = val.replace(wrong, right)
                    fixed += 1
    return fixed


def _progress_noop(stage: str, msg: str, pct: float) -> None:
    """Default progress callback for sync helpers."""
    return None


def _clamp_progress(pct) -> float:
    try:
        return max(0.0, min(1.0, float(pct)))
    except (TypeError, ValueError):
        return 0.0


# ── Iterative improve loop ─────────────────────────────────────────

def _run_improve_loop_sync(story_id: str, body: dict | None = None, progress=None) -> dict:
    """Run iterative critic→improve cycles until target quality is reached.

    Each round:
    1. Run critic to score the story
    2. If score >= target, stop
    3. Identify weakest scenes (by critic score) and rotate targets
    4. Classify the critic's per-scene issues and act on them:
       - refine narration for run-on / choppy / length issues
       - regenerate TTS for too-short / corrupt audio
       - add more images for missing / low-quality images
       - regenerate subtitles for timing / cue issues
       - story-level typo fix from continuity_issues
    5. Re-render
    6. Repeat
    """
    progress = progress or _progress_noop
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise FileNotFoundError("Story not found")

    target_stars = (body or {}).get("target_stars", 4.0)
    max_rounds = (body or {}).get("max_rounds", 3)
    max_scenes_per_round = (body or {}).get("max_scenes_per_round", 3)
    images_per_scene = (body or {}).get("images_per_scene", 2)
    voice = (body or {}).get("voice", "Dean")

    env = {
        **os.environ,
        "XIAOMI_API_KEY": _resolve_env_var("XIAOMI_API_KEY"),
        "XIAOMI_BASE_URL": _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
    }

    sys.path.insert(0, str(STORY_VIEWER_DIR))
    from comfyui_utils import generate_image, is_running as comfyui_running
    from tts_utils import generate_tts, get_audio_duration
    from story_actions import _regen_scene_subs

    api_key = _resolve_env_var("XIAOMI_API_KEY")
    base_url = _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
    base_url = validate_provider_url(base_url, kind="llm")

    history = []
    previously_improved = set()

    for round_num in range(1, max_rounds + 1):
        round_base = (round_num - 1) / max_rounds
        round_span = 1 / max_rounds
        progress("critic", f"Round {round_num}/{max_rounds}: running critic", round_base + round_span * 0.05)
        # Step 1: Run critic
        try:
            proc = subprocess.run(
                [sys.executable, str(STORY_VIEWER_DIR / "critic.py"), story_id, "--json"],
                capture_output=True, text=True, timeout=180,
                cwd=str(STORY_VIEWER_DIR), env=env,
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError("Critic timed out after 180s")
        if proc.returncode != 0:
            raise RuntimeError(f"Critic failed: {proc.stderr[:300]}")

        stdout = proc.stdout.strip()
        json_end = stdout.rfind("}")
        if json_end >= 0:
            stdout = stdout[:json_end + 1]
        try:
            review = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Critic returned invalid JSON: {e}")
        stars = review.get("review", {}).get("stars", 0)
        rating = review.get("review", {}).get("overall_score", 0)

        # Step 2: Check if we've hit target
        if stars >= target_stars:
            progress("complete", f"Target reached at {stars} stars", 1.0)
            history.append({"round": round_num, "stars": stars, "rating": rating, "improved": 0})
            return {
                "status": "target_reached",
                "rounds_completed": round_num,
                "final_stars": stars,
                "final_rating": rating,
                "history": history,
            }

        progress("plan", f"Round {round_num}/{max_rounds}: choosing scenes to improve", round_base + round_span * 0.15)
        # Step 3: Identify weakest scenes using the critic's own per-scene scores.
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        scenes = manifest.get("scenes", [])
        critic_scenes = review.get("scenes", [])
        continuity_issues = review.get("continuity_issues", [])

        scored = []
        for i, sc in enumerate(scenes):
            critic_scene = None
            for cs in critic_scenes:
                if str(cs.get("scene_num", "")) == str(sc.get("scene", "")):
                    critic_scene = cs
                    break
            if critic_scene and "score" in critic_scene:
                scene_score = float(critic_scene["score"])
            else:
                img_count = len(sc.get("image_filenames", []))
                prompt_len = len(sc.get("prompt", "").split())
                has_audio = bool(sc.get("audio_filename"))
                scene_score = img_count * 3 + prompt_len / 10 + (5 if has_audio else 0)

            issues = []
            if critic_scene:
                for key in ("narration", "images", "audio", "subtitles"):
                    issues.extend(critic_scene.get(key, {}).get("issues", []))

            scored.append({"idx": i, "score": scene_score, "issues": issues})

        scored.sort(key=lambda x: (x["score"], x["idx"]))

        # Rotate: skip scenes improved in a previous round, then refill
        fresh = [s for s in scored if s["idx"] not in previously_improved]
        if len(fresh) < max_scenes_per_round:
            fresh = scored
        targets = fresh[:max_scenes_per_round]
        round_improved_idx = set()

        # Step 3a: Story-level typo fix from continuity_issues
        typo_pairs = _extract_typo_pairs(continuity_issues)
        typo_fixes = _apply_typo_fix(scenes, typo_pairs)
        if typo_fixes:
            print(f"[improve] round {round_num}: applied {typo_fixes} typo fix(es) across story", file=sys.stderr)

        improved = []
        total_targets = max(1, len(targets))
        for target_num, target in enumerate(targets, start=1):
            idx = target["idx"]
            sc = scenes[idx]
            progress(
                "improve",
                f"Round {round_num}/{max_rounds}: improving scene {idx + 1}",
                round_base + round_span * (0.25 + 0.45 * ((target_num - 1) / total_targets)),
            )
            scene_issues = target["issues"]
            actions, reasons = _classify_scene_issues(scene_issues)
            scene_changed = False

            # ── Action 1: Refine narration if flagged ────────────────────
            if actions["refine_narration"] and sc.get("narration"):
                from generate_story import load_story_style_prompt

                new_narration = _llm_call_text(
                    api_key, base_url,
                    system=("You are a narration editor. Fix the given voiceover text: "
                            "tighten run-on sentences, vary sentence length, remove excessive "
                            "ellipses. Keep the same content, tone, and approximate length. "
                            "Use the mandatory canonical narration style below. "
                            "Keep third person and never use first-person internal monologue. "
                            "Output ONLY the revised narration, no commentary. "
                            "Target 80-150 words.\n\n"
                            + load_story_style_prompt()),
                    user=sc["narration"],
                    temperature=0.6, max_tokens=512,
                )
                if new_narration and len(new_narration.split()) >= 20:
                    sc["narration"] = new_narration
                    sc["narration_text"] = new_narration
                    scene_changed = True

            # ── Action 2: Refine visual prompt (always) ──────────────────
            if sc.get("prompt"):
                new_prompt = _llm_call_text(
                    api_key, base_url,
                    system=("Improve this image generation prompt. Be more vivid, detailed, "
                            "and visually specific. Output ONLY the improved prompt. "
                            "80-150 words, natural language prose, not tag lists. "
                            "When the scene framing shows a character's face (medium shot, "
                            "close-up, portrait, three-quarter, profile, or any framing "
                            "where the face is visible), explicitly include a phrase like "
                            "'a well-defined human nose' and 'natural human facial features' "
                            "— without this the model defaults to a deformed / animalistic "
                            "nose on DreamShaper-class checkpoints."),
                    user=sc["prompt"],
                    temperature=0.7, max_tokens=512,
                )
                if new_prompt and len(new_prompt.split()) >= 20:
                    sc["prompt"] = new_prompt
                    scene_changed = True

            # ── Action 3: Add more images if flagged or below target ─────
            needs_images = actions["add_images"] or len(sc.get("image_filenames", [])) < images_per_scene
            if needs_images and comfyui_running().get("running", False):
                scene_num = idx + 1
                padded = f"{scene_num:02d}"
                safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', sc.get("title", "")).strip("_")[:30]
                current_images = len(sc.get("image_filenames", []))

                for img_idx in range(current_images, images_per_scene):
                    seed = hash(story_id + str(scene_num) + str(img_idx) + round_num) % (2**32 - 1)
                    prefix = f"{story_id}_s{padded}_{safe_title}_{img_idx + 1:02d}"
                    try:
                        filename = generate_image(
                            prompt=sc["prompt"],
                            output_prefix=prefix,
                            output_dir=str(story_dir),
                            seed=seed,
                            timeout=120,
                        )
                        if filename:
                            sc.setdefault("image_filenames", []).append(filename)
                            scene_changed = True
                    except Exception as img_err:
                        print(f"[improve] image scene {idx + 1}/{img_idx + 1} failed: {img_err}", file=sys.stderr)

            # ── Action 4: Regenerate TTS if missing or flagged ──────────
            if actions["regen_tts"] or not sc.get("audio_filename"):
                narration = sc.get("narration", sc.get("narration_text", ""))
                if narration:
                    scene_num = idx + 1
                    padded = f"{scene_num:02d}"
                    audio_filename = f"tts_{story_id}_s{padded}.wav"
                    audio_path = str(story_dir / audio_filename)
                    try:
                        ok = generate_tts(narration, audio_path, voice=voice)
                        if ok:
                            sc["audio_filename"] = audio_filename
                            sc["audio_duration"] = get_audio_duration(audio_path)
                            scene_changed = True
                    except Exception as tts_err:
                        print(f"[improve] TTS scene {idx + 1} failed: {tts_err}", file=sys.stderr)

            # ── Action 5: Regenerate subtitles if flagged ───────────────
            if actions["regen_subtitles"] and sc.get("audio_filename"):
                scene_num = idx + 1
                padded = f"{scene_num:02d}"
                try:
                    _regen_scene_subs(story_dir, story_id, padded, sc, manifest)
                    scene_changed = True
                except Exception as sub_err:
                    print(f"[improve] subs scene {idx + 1} failed: {sub_err}", file=sys.stderr)

            if scene_changed:
                improved.append({
                    "scene_idx": idx,
                    "title": sc.get("title", ""),
                    "actions": actions,
                    "reasons": reasons[:3],
                })
                round_improved_idx.add(idx)
        atomic_write_json(manifest_path, manifest)

        # Re-render
        progress("render", f"Round {round_num}/{max_rounds}: re-rendering story", round_base + round_span * 0.82)
        try:
            subprocess.run(
                [sys.executable, str(STORY_VIEWER_DIR / "render_video.py"), story_id],
                capture_output=True, text=True, timeout=600,
                cwd=str(STORY_VIEWER_DIR),
            )
        except subprocess.TimeoutExpired:
            print(f"[improve] render timed out in round {round_num}", file=sys.stderr)

        previously_improved.update(round_improved_idx)
        history.append({
            "round": round_num,
            "stars": stars,
            "rating": rating,
            "improved": len(improved),
            "improved_indices": sorted(round_improved_idx),
            "typo_fixes": typo_fixes,
        })

    # Final check after all rounds
    progress("critic", "Running final critic check", 0.96)
    final_stars = 0
    final_rating = 0
    try:
        proc = subprocess.run(
            [sys.executable, str(STORY_VIEWER_DIR / "critic.py"), story_id, "--json"],
            capture_output=True, text=True, timeout=180,
            cwd=str(STORY_VIEWER_DIR), env=env,
        )
        if proc.returncode == 0:
            stdout = proc.stdout.strip()
            json_end = stdout.rfind("}")
            if json_end >= 0:
                stdout = stdout[:json_end + 1]
            final_review = json.loads(stdout)
            final_stars = final_review.get("review", {}).get("stars", 0)
            final_rating = final_review.get("review", {}).get("overall_score", 0)
    except Exception as e:
        print(f"[improve] final critic run failed: {e}", file=sys.stderr)

    return {
        "status": "max_rounds_reached",
        "rounds_completed": max_rounds,
        "final_stars": final_stars,
        "final_rating": final_rating,
        "history": history,
    }


# ── One-pass auto-improve worker ──────────────────────────────────

def _run_auto_improve_sync(story_id: str, body: dict | None = None, progress=None) -> dict:
    """Auto-improve: critic → identify weak scenes → refine → regenerate → re-render."""
    progress = progress or _progress_noop
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise FileNotFoundError("Story not found")

    max_scenes = (body or {}).get("max_scenes", 3)

    # Step 1: Run critic
    progress("critic", "Running critic to identify weak scenes", 0.05)
    env = {
        **os.environ,
        "XIAOMI_API_KEY": _resolve_env_var("XIAOMI_API_KEY"),
        "XIAOMI_BASE_URL": _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
    }
    proc = subprocess.run(
        [sys.executable, str(STORY_VIEWER_DIR / "critic.py"), story_id, "--json"],
        capture_output=True, text=True, timeout=180,
        cwd=str(STORY_VIEWER_DIR), env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Critic failed: {proc.stderr[:300]}")

    stdout = proc.stdout.strip()
    json_end = stdout.rfind("}")
    if json_end >= 0:
        stdout = stdout[:json_end + 1]
    review = json.loads(stdout)

    # Step 2: Identify weakest scenes
    progress("plan", "Choosing scenes to improve", 0.15)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    targets = []
    for i, sc in enumerate(scenes):
        img_count = len(sc.get("image_filenames", []))
        prompt_len = len(sc.get("prompt", "").split())
        score = img_count * 2 + prompt_len / 10
        targets.append((i, score))
    targets.sort(key=lambda x: x[1])
    targets = targets[:max_scenes]

    sys.path.insert(0, str(STORY_VIEWER_DIR))
    from comfyui_utils import generate_image, is_running as comfyui_running
    from tts_utils import generate_tts, get_audio_duration

    api_key = _resolve_env_var("XIAOMI_API_KEY")
    base_url = _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
    base_url = validate_provider_url(base_url, kind="llm")

    improved = []
    total_targets = max(1, len(targets))
    for target_num, (idx, _score) in enumerate(targets, start=1):
        sc = scenes[idx]
        progress(
            "improve",
            f"Improving scene {idx + 1}",
            0.2 + 0.6 * ((target_num - 1) / total_targets),
        )

        # Refine prompt via LLM
        try:
            from fantasee_server.state import requests
            resp = requests.post(
                f"{base_url}/chat/completions",
                json={
                    "model": "mimo-v2.5-pro",
                    "messages": [
                        {"role": "system", "content": ("Improve this image generation prompt. "
                                                        "Be more vivid and detailed. "
                                                        "Output ONLY the improved prompt. "
                                                        "80-150 words. "
                                                        "When the framing shows a character's "
                                                        "face, explicitly include 'a well-defined "
                                                        "human nose' and 'natural human facial "
                                                        "features' to prevent the model defaulting "
                                                        "to a deformed / animalistic nose.")},
                        {"role": "user", "content": sc["prompt"]},
                    ],
                    "temperature": 0.7,
                    "max_completion_tokens": 512,
                },
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=120,
                allow_redirects=False,
            )
            if resp.ok:
                sc["prompt"] = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
        except Exception:
            pass  # keep original prompt on failure

        # Regenerate image
        if comfyui_running().get("running", False):
            for old_img in sc.get("image_filenames", []):
                old_path = story_dir / old_img
                if old_path.exists():
                    old_path.unlink()

            scene_num = idx + 1
            padded = f"{scene_num:02d}"
            safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', sc.get("title", "")).strip("_")[:30]
            seed = hash(story_id + str(scene_num)) % (2**32 - 1)
            prefix = f"{story_id}_s{padded}_{safe_title}_01"
            filename = generate_image(
                prompt=sc["prompt"],
                output_prefix=prefix,
                output_dir=str(story_dir),
                seed=seed,
                timeout=600,
            )
            sc["image_filenames"] = [filename] if filename else []

        improved.append({"scene_idx": idx, "title": sc.get("title", "")})

    atomic_write_json(manifest_path, manifest)

    # Step 3: Re-render full story
    progress("render", "Re-rendering story", 0.88)
    render_proc = subprocess.run(
        [sys.executable, str(STORY_VIEWER_DIR / "render_video.py"), story_id],
        capture_output=True, text=True, timeout=600,
        cwd=str(STORY_VIEWER_DIR),
    )

    return {
        "status": "ok",
        "review_stars": review.get("review", {}).get("stars", 0),
        "improved_scenes": improved,
        "render_ok": render_proc.returncode == 0,
    }
