"""Library maintenance: per-story completion reports + auto-repair queue.

The "library" is the collection of generated story directories on
disk. A story is "incomplete" when one of these pieces is missing:

* the manifest itself or its ``status`` field
* scene text (prompt / narration)
* scene images (PNGs over 1KB)
* scene audio (WAVs over 1KB)
* scene subtitles (Whisper-aligned JSON)
* per-scene MP4 (rendered by ``render_video.py``)
* the full-story MP4
* the Plex package (``final/plex/*.mp4``)

``story_completion_report`` walks one story and returns a structured
report listing what's missing. ``incomplete_story_summaries`` uses
that to find every story that still needs work, and the library
maintenance queue runs each one through the full repair pipeline
(``regenerate → repair → render → plex export``) until it's
complete.

The agent loop (``_library_agent_loop``) periodically scans for
incomplete stories and queues them — only when the user hasn't
manually started a maintenance pass already.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from fantasee_server.discovery import discover_generated_stories
from fantasee_server.paths import STORY_VIEWER_DIR, generated_story_dir
import fantasee_server.paths as _paths
import fantasee_server.state as _state
from fantasee_server.state import (
    LIBRARY_AGENT_MAX_FAILURES,
    _broadcast_ws_json,
    _broadcast_ws_json_from_thread,
    _generation_tasks,
    _library_agent_failures,
    _library_maintenance_running,
    _story_sort_ts,
    atomic_write_json,
    new_uuid,
    now,
)
from story_pipeline import sync_from_completion, update_stage


# ── Per-story completion report ────────────────────────────────────

def story_completion_report(story_id: str, *, story: Optional[dict] = None,
                            story_dir: Optional[Path] = None) -> dict:
    """Return a file-backed completion report for one story."""
    story_dir = story_dir or generated_story_dir(story_id)
    if story is None:
        manifest_path = story_dir / f"{story_id}.json"
        try:
            story = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {
                "complete": False,
                "missing": ["story", "status"],
                "issues": [{"kind": "story", "message": "Story manifest is missing or unreadable"}],
                "issue_count": 1,
                "counts": {
                    "scenes": 0,
                    "scenes_with_text": 0,
                    "scenes_with_images": 0,
                    "scenes_with_audio": 0,
                    "scenes_with_subtitles": 0,
                    "scene_videos": 0,
                },
                "full_video_ok": False,
                "plex_video_ok": False,
            }

    scenes = story.get("scenes") or []
    issues: list[dict] = []
    counts = {
        "scenes": len(scenes),
        "scenes_with_text": 0,
        "scenes_with_images": 0,
        "scenes_with_audio": 0,
        "scenes_with_subtitles": 0,
        "scene_videos": 0,
    }

    def add_issue(kind: str, message: str, *, scene: Optional[str] = None) -> None:
        issue = {"kind": kind, "message": message}
        if scene is not None:
            issue["scene"] = scene
        issues.append(issue)

    if story.get("status") not in (None, "", "complete", "draft", "generating", "incomplete"):
        add_issue("status", f"Manifest status is {story.get('status')}")
    if not scenes:
        add_issue("story", "No generated scenes found")

    for i, scene in enumerate(scenes):
        scene_key = str(scene.get("scene") or f"{i + 1:02d}")
        padded_key = f"{int(scene_key):02d}" if scene_key.isdigit() else scene_key
        text_ok = bool((scene.get("prompt") or "").strip()) and bool(
            (scene.get("narration") or scene.get("narration_text") or "").strip()
        )
        if text_ok:
            counts["scenes_with_text"] += 1
        else:
            add_issue("story_text", "Scene is missing prompt or narration", scene=scene_key)

        image_files = [story_dir / f for f in (scene.get("image_filenames") or []) if f]
        if image_files and all(p.exists() and p.stat().st_size > 1000 for p in image_files):
            counts["scenes_with_images"] += 1
        else:
            add_issue("image", "Scene is missing generated image files", scene=scene_key)

        audio_name = scene.get("audio_filename") or ""
        audio_path = story_dir / audio_name if audio_name else None
        if audio_path and audio_path.exists() and audio_path.stat().st_size > 1000:
            counts["scenes_with_audio"] += 1
        else:
            add_issue("audio", "Scene is missing narration audio", scene=scene_key)

        subs_names = [scene.get("subtitle_file") or "", f"subs_{story_id}_s{scene_key}.json"]
        if padded_key != scene_key:
            subs_names.append(f"subs_{story_id}_s{padded_key}.json")
        subs_ok = False
        subs_error = "Scene is missing subtitle alignment"
        for subs_name in [name for name in subs_names if name]:
            subs_path = story_dir / subs_name
            if not subs_path.exists():
                continue
            try:
                subs = json.loads(subs_path.read_text(encoding="utf-8"))
                if not isinstance(subs, list) or not subs:
                    subs_error = "Subtitle alignment file is empty"
                    continue
                previous_end = 0.0
                valid_segments = True
                for segment in subs:
                    if not isinstance(segment, dict) or not (segment.get("text") or "").strip():
                        valid_segments = False
                        subs_error = "Subtitle alignment contains an empty segment"
                        break
                    try:
                        start = float(segment["start"])
                        end = float(segment["end"])
                    except (KeyError, TypeError, ValueError):
                        valid_segments = False
                        subs_error = "Subtitle alignment contains invalid timestamps"
                        break
                    audio_duration = float(scene.get("audio_duration") or 0.0)
                    if start < 0 or end <= start or start < previous_end - 0.05:
                        valid_segments = False
                        subs_error = "Subtitle alignment contains overlapping or invalid timestamps"
                        break
                    if audio_duration > 0 and end > audio_duration + 1.0:
                        valid_segments = False
                        subs_error = "Subtitle alignment extends beyond the narration audio"
                        break
                    previous_end = end
                subs_ok = valid_segments
            except (json.JSONDecodeError, OSError):
                subs_error = "Subtitle alignment file is unreadable"
            if subs_ok:
                break
        if subs_ok:
            counts["scenes_with_subtitles"] += 1
        else:
            add_issue("subtitles", subs_error, scene=scene_key)

        scene_mp4s = [story_dir / f"{story_id}_s{scene_key}.mp4"]
        if padded_key != scene_key:
            scene_mp4s.append(story_dir / f"{story_id}_s{padded_key}.mp4")
        if any(p.exists() and p.stat().st_size > 1000 for p in scene_mp4s):
            counts["scene_videos"] += 1
        else:
            add_issue("scene_video", "Scene MP4 has not been rendered", scene=scene_key)

    full_mp4_candidates = [
        story_dir / f"{story_id}_full.mp4",
        story_dir / "final" / f"{story_id}_full.mp4",
    ]
    full_video_ok = bool(scenes) and (
        len(scenes) == 1 or any(p.exists() and p.stat().st_size > 1000 for p in full_mp4_candidates)
    )
    if not full_video_ok:
        add_issue("full_video", "Full story MP4 has not been rendered")

    plex_dir = story_dir / "final" / "plex"
    plex_video_ok = plex_dir.is_dir() and any(p.stat().st_size > 1000 for p in plex_dir.glob("*.mp4"))
    if not plex_video_ok:
        add_issue("plex", "Plex-ready MP4 package is missing")

    stage_order = ["story", "status", "story_text", "image", "audio", "subtitles",
                   "scene_video", "full_video", "plex"]
    missing = []
    for kind in stage_order:
        if any(issue["kind"] == kind for issue in issues):
            missing.append(kind)

    return {
        "complete": len(issues) == 0,
        "missing": missing,
        "issues": issues[:80],
        "issue_count": len(issues),
        "counts": counts,
        "full_video_ok": full_video_ok,
        "plex_video_ok": plex_video_ok,
    }


def incomplete_story_summaries(*, include_failed: bool = True,
                               limit: Optional[int] = None) -> list[dict]:
    """Return newest-first summaries for stories that still need work."""
    stories = discover_generated_stories()
    incomplete = []
    for story in stories:
        completion = story.get("completion") or {}
        if completion.get("complete"):
            continue
        story_id = story.get("id", "")
        if not include_failed and _library_agent_failures.get(story_id, 0) >= LIBRARY_AGENT_MAX_FAILURES:
            continue
        incomplete.append({
            "id": story_id,
            "title": story.get("title") or story_id,
            "description": story.get("description", ""),
            "scene_count": story.get("scene_count", len(story.get("scenes", []))),
            "created_at": story.get("created_at"),
            "updated_at": story.get("updated_at"),
            "sort_ts": story.get("sort_ts", 0),
            "completion": completion,
            "failure_count": _library_agent_failures.get(story_id, 0),
        })
    incomplete.sort(key=_story_sort_ts, reverse=True)
    return incomplete[:limit] if limit else incomplete


# ── One-shot per-story completion worker ───────────────────────────

def _run_render_for_library(story_id: str) -> dict:
    """Run render_video.py and return a compact result."""
    proc = subprocess.run(
        [sys.executable, str(STORY_VIEWER_DIR / "render_video.py"), story_id],
        capture_output=True,
        text=True,
        timeout=1800,
        cwd=str(STORY_VIEWER_DIR),
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    rendered_count = 0
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("Done!"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                rendered_count = int(parts[1])
            break
    if proc.returncode not in (0, 2):
        raise RuntimeError(f"Render failed (exit {proc.returncode}): {stderr[-500:] or stdout[-500:]}")
    return {
        "status": "no_op" if proc.returncode == 2 or rendered_count == 0 else "ok",
        "scenes_rendered": rendered_count,
        "stdout_tail": stdout[-500:],
    }


def _complete_story_for_library(story_id: str, progress) -> dict:
    """Regenerate/repair/render/export one story until it is complete."""
    sys.path.insert(0, str(STORY_VIEWER_DIR))
    import story_actions
    from plex_export import export_plex_package

    result: dict = {"story_id": story_id, "steps": []}

    def emit(stage: str, msg: str, pct: float) -> None:
        progress(stage, msg, max(0.0, min(1.0, float(pct))))

    emit("scan", f"Scanning {story_id}", 0.02)
    report = story_completion_report(story_id)
    story_dir = generated_story_dir(story_id)
    sync_from_completion(story_dir, report)
    missing = set(report.get("missing") or [])

    if "story" in missing or "status" in missing:
        emit("regenerate", f"Re-generating {story_id}", 0.05)
        regen = story_actions.regenerate_story(story_id, backup=True)
        result["steps"].append({"step": "regenerate", "result": regen})
        if regen.get("status") not in ("ok",):
            raise RuntimeError(regen.get("error") or f"Regenerate returned {regen.get('status')}")
        report = story_completion_report(story_id)
        sync_from_completion(story_dir, report)
        missing = set(report.get("missing") or [])

    if missing.intersection({"story_text", "image", "audio", "subtitles"}):
        emit("repair", f"Repairing generated assets for {story_id}", 0.25)
        plan = story_actions.plan_repair(story_id)
        repair = story_actions.apply_repair(
            story_id,
            plan,
            progress=lambda stage, msg, pct: emit(stage, msg, 0.25 + pct * 0.30),
        )
        result["steps"].append({"step": "repair", "result": repair.to_dict()})
        if repair.errors:
            raise RuntimeError("; ".join(repair.errors[:3]))
        report = story_completion_report(story_id)
        sync_from_completion(story_dir, report)
        missing = set(report.get("missing") or [])

    if missing.intersection({"scene_video", "full_video"}):
        emit("render", f"Rendering MP4 files for {story_id}", 0.62)
        update_stage(story_dir, "render", "running", message="Rendering scene and full-story MP4 files")
        render = _run_render_for_library(story_id)
        result["steps"].append({"step": "render", "result": render})
        report = story_completion_report(story_id)
        sync_from_completion(story_dir, report)
        missing = set(report.get("missing") or [])

    if "plex" in missing:
        emit("plex", f"Exporting Plex package for {story_id}", 0.78)
        update_stage(story_dir, "plex", "running", message="Exporting Plex-ready package")
        plex = export_plex_package(
            story_id,
            progress_callback=lambda stage, msg, pct: emit(stage, msg, 0.78 + pct * 0.20),
        )
        result["steps"].append({"step": "plex", "result": plex.to_dict()})

    final_report = story_completion_report(story_id)
    result["completion"] = final_report
    if not final_report.get("complete"):
        sync_from_completion(story_dir, final_report)
        missing_final = ", ".join(final_report.get("missing") or ["unknown"])
        raise RuntimeError(f"Story still incomplete after maintenance: {missing_final}")
    manifest_path = story_dir / f"{story_id}.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "complete"
        pipeline = manifest.get("pipeline")
        if not isinstance(pipeline, dict):
            pipeline = {}
        pipeline.update({
            "status": "complete",
            "next_stage": "complete",
            "completion_verified_at": now(),
        })
        manifest["pipeline"] = pipeline
        atomic_write_json(manifest_path, manifest)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not persist completion status: {exc}") from exc
    sync_from_completion(story_dir, final_report)
    emit("complete", f"{story_id} complete", 1.0)
    return result


# ── Library maintenance queue (multi-story) ────────────────────────

async def _start_library_maintenance_queue(*, story_ids: Optional[list[str]] = None,
                                           limit: Optional[int] = None,
                                           include_failed: bool = True,
                                           auto: bool = False) -> dict:
    """Start the one-at-a-time library maintenance queue."""
    global _library_maintenance_running
    if _library_maintenance_running:
        active = next(
            (t for t in _generation_tasks.values()
             if t.get("kind") == "library_maintenance" and t.get("status") == "running"),
            None,
        )
        return {
            "status": "running",
            "task_id": active.get("id") if active else None,
            "message": "Library maintenance is already running.",
        }

    incomplete = incomplete_story_summaries(include_failed=include_failed, limit=limit)
    selected = [s for s in incomplete if not story_ids or s["id"] in set(story_ids)]
    if limit:
        selected = selected[:limit]
    if not selected:
        return {
            "status": "done",
            "count": 0,
            "message": "No incomplete stories found.",
        }

    task_id = f"library-{new_uuid()[:6]}"
    _generation_tasks[task_id] = {
        "id": task_id,
        "kind": "library_maintenance",
        "status": "running",
        "progress": 0,
        "message": f"Queued {len(selected)} incomplete story/stories",
        "item_count": len(selected),
        "created_at": now(),
        "auto": auto,
    }
    _library_maintenance_running = True
    await _broadcast_ws_json({
        "type": "task_update",
        "task_id": task_id,
        "kind": "library_maintenance",
        "status": "running",
        "progress": 0,
        "message": f"Queued {len(selected)} incomplete story/stories",
        "item_count": len(selected),
    })
    asyncio.create_task(_run_library_maintenance_queue(task_id, selected))
    return {
        "status": "running",
        "task_id": task_id,
        "count": len(selected),
        "stories": selected,
        "message": "Library maintenance queue started.",
    }


async def _run_library_maintenance_queue(task_id: str, stories: list[dict]) -> None:
    """Run library maintenance sequentially and stream parent/child progress."""
    global _library_maintenance_running
    loop = asyncio.get_running_loop()
    total = len(stories)
    completed: list[str] = []
    failed: list[dict] = []

    try:
        for idx, story in enumerate(stories):
            story_id = story["id"]
            sub_id = f"{task_id}-{idx:02d}"
            _generation_tasks[sub_id] = {
                "id": sub_id,
                "parent": task_id,
                "kind": "library_story",
                "story_id": story_id,
                "title": story.get("title") or story_id,
                "status": "running",
                "progress": 0,
                "message": f"Starting {story_id}",
                "created_at": now(),
            }
            await _broadcast_ws_json({
                "type": "task_update",
                "task_id": sub_id,
                "parent": task_id,
                "kind": "library_story",
                "story_id": story_id,
                "title": story.get("title") or story_id,
                "status": "running",
                "progress": 0,
                "message": f"Starting {story_id}",
            })

            def progress(stage: str, msg: str, pct: float) -> None:
                overall = (idx + pct) / max(1, total)
                _generation_tasks[sub_id].update({
                    "stage": stage,
                    "progress": pct,
                    "message": msg,
                    "status": "running",
                })
                _generation_tasks[task_id].update({
                    "stage": stage,
                    "progress": overall,
                    "message": f"{idx + 1}/{total}: {msg}",
                    "status": "running",
                })
                _broadcast_ws_json_from_thread(loop, {
                    "type": "task_update",
                    "task_id": sub_id,
                    "parent": task_id,
                    "kind": "library_story",
                    "story_id": story_id,
                    "stage": stage,
                    "status": "running",
                    "progress": pct,
                    "message": msg,
                })
                _broadcast_ws_json_from_thread(loop, {
                    "type": "task_update",
                    "task_id": task_id,
                    "kind": "library_maintenance",
                    "stage": stage,
                    "status": "running",
                    "progress": overall,
                    "message": f"{idx + 1}/{total}: {msg}",
                    "item_count": total,
                })

            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: _complete_story_for_library(story_id, progress),
                )
                completed.append(story_id)
                _library_agent_failures.pop(story_id, None)
                _generation_tasks[sub_id].update({
                    "status": "done",
                    "stage": "complete",
                    "progress": 1.0,
                    "message": f"{story_id} complete",
                    "result": result,
                })
                await _broadcast_ws_json({
                    "type": "task_update",
                    "task_id": sub_id,
                    "parent": task_id,
                    "kind": "library_story",
                    "story_id": story_id,
                    "status": "done",
                    "stage": "complete",
                    "progress": 1.0,
                    "message": f"{story_id} complete",
                    "result": result,
                })
            except Exception as e:
                _library_agent_failures[story_id] = _library_agent_failures.get(story_id, 0) + 1
                failed.append({"story_id": story_id, "error": str(e)})
                _generation_tasks[sub_id].update({
                    "status": "error",
                    "stage": "error",
                    "progress": 1.0,
                    "message": f"{story_id} failed: {e}",
                })
                await _broadcast_ws_json({
                    "type": "task_update",
                    "task_id": sub_id,
                    "parent": task_id,
                    "kind": "library_story",
                    "story_id": story_id,
                    "status": "error",
                    "stage": "error",
                    "progress": 1.0,
                    "message": f"{story_id} failed: {e}",
                })

        _state._stories_cache = _paths.load_stories()
        _generation_tasks[task_id].update({
            "status": "done",
            "stage": "complete",
            "progress": 1.0,
            "message": f"Library maintenance complete: {len(completed)} complete, {len(failed)} failed",
            "completed": completed,
            "failed": failed,
        })
        await _broadcast_ws_json({
            "type": "task_update",
            "task_id": task_id,
            "kind": "library_maintenance",
            "status": "done",
            "stage": "complete",
            "progress": 1.0,
            "message": f"Library maintenance complete: {len(completed)} complete, {len(failed)} failed",
            "completed": completed,
            "failed": failed,
        })
    finally:
        _library_maintenance_running = False


# ── Library agent loop ─────────────────────────────────────────────

async def _library_agent_loop() -> None:
    """Periodically queue incomplete stories while the server is running."""
    await asyncio.sleep(float(os.environ.get("FANTASEE_LIBRARY_AGENT_START_DELAY", "20") or "20"))
    interval = float(os.environ.get("FANTASEE_LIBRARY_AGENT_INTERVAL", "600") or "600")
    while True:
        try:
            if not _library_maintenance_running:
                incomplete = incomplete_story_summaries(include_failed=False)
                if incomplete:
                    await _start_library_maintenance_queue(
                        story_ids=[s["id"] for s in incomplete],
                        include_failed=False,
                        auto=True,
                    )
        except Exception as e:
            print(f"[library-agent] scan failed: {e}", file=sys.stderr)
        await asyncio.sleep(interval)
