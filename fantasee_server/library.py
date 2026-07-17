"""Library maintenance: per-story completion reports + auto-repair queue.

The "library" is the collection of generated story directories on
disk. A story is "incomplete" when one of these pieces is missing:

* the manifest itself or its ``status`` field
* scene text (prompt / narration)
* the requested number of usable, non-blank scene images
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
from fantasee_server.production_runtime import finish_task, start_task, update_task
from fantasee_server.production_runtime import production_database_path, enqueue_task_job, finalize_run_from_jobs
from fantasee_server.production_store import ProductionStore
from fantasee_server.production_worker import ProductionWorker
from fantasee_server.asset_registry import AssetRegistry
from fantasee_server.media_timeline import build_story_shot_timeline, write_shot_timeline, write_story_timeline
from fantasee_server.shot_planning import ShotSpec
from story_pipeline import sync_from_completion, update_stage
from image_quality import is_usable_story_image, requested_images_per_scene


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
    target_images = requested_images_per_scene(story)
    issues: list[dict] = []
    counts = {
        "scenes": len(scenes),
        "scenes_with_text": 0,
        "scenes_with_images": 0,
        "scenes_with_audio": 0,
        "scenes_with_subtitles": 0,
        "scene_videos": 0,
        "planned_shots": 0,
        "approved_shots": 0,
    }

    # New editor-managed stories must pass the approved-shot gate. Legacy
    # stories have no semantic plan yet, so they continue using their
    # manifest-backed image contract during migration.
    with ProductionStore(production_database_path()) as production:
        planned_shots = {}
        for scene_index in range(1, len(scenes) + 1):
            scene_id = f"scene-{scene_index:02d}"
            shots = production.list_shots(story_id, scene_id)
            if shots:
                planned_shots[scene_id] = shots
        counts["planned_shots"] = sum(len(shots) for shots in planned_shots.values())
        approved_shots = {
            shot.id: production.get_current_asset(story_id, shot.id, "image")
            for shots in planned_shots.values()
            for shot in shots
        }
        counts["approved_shots"] = sum(
            1 for asset in approved_shots.values()
            if asset is not None and Path(asset.path).is_file() and Path(asset.path).stat().st_size > 0
        )

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
        usable_images = [path for path in image_files if is_usable_story_image(path)]
        if len(usable_images) >= target_images:
            counts["scenes_with_images"] += 1
        else:
            add_issue(
                "image",
                f"Scene has {len(usable_images)} of {target_images} usable generated images",
                scene=scene_key,
            )

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

        stale_messages = {
            "images": "Scene artwork is stale after an editorial revision",
            "audio": "Narration audio is stale after an editorial revision",
            "subtitles": "Subtitles are stale after an editorial revision",
            "shot_timeline": "Shot timeline is stale after an editorial revision",
            "scene_video": "Scene video is stale after an editorial revision",
            "full_video": "Full story video is stale after an editorial revision",
            "plex": "Plex package is stale after an editorial revision",
        }
        existing_kinds = {issue["kind"] for issue in issues if issue.get("scene") == scene_key}
        for stale_kind in scene.get("stale_outputs") or []:
            if stale_kind in stale_messages and stale_kind not in existing_kinds:
                add_issue(stale_kind, stale_messages[stale_kind], scene=scene_key)

        scene_mp4s = [story_dir / f"{story_id}_s{scene_key}.mp4"]
        if padded_key != scene_key:
            scene_mp4s.append(story_dir / f"{story_id}_s{padded_key}.mp4")
        if any(p.exists() and p.stat().st_size > 1000 for p in scene_mp4s):
            counts["scene_videos"] += 1
        else:
            add_issue("scene_video", "Scene MP4 has not been rendered", scene=scene_key)

        semantic_shots = planned_shots.get(f"scene-{int(scene_key):02d}", []) if scene_key.isdigit() else []
        for shot in semantic_shots:
            asset = approved_shots.get(shot.id)
            if asset is None or not Path(asset.path).is_file() or Path(asset.path).stat().st_size <= 0:
                add_issue("shot_image", f"Shot {shot.id} has no approved usable image", scene=scene_key)

    if planned_shots:
        shot_timeline_path = story_dir / "working" / "shot_timeline.json"
        if not shot_timeline_path.is_file():
            add_issue("shot_timeline", "Approved shot timeline has not been built")
        else:
            try:
                shot_timeline = json.loads(shot_timeline_path.read_text(encoding="utf-8"))
                shot_segments = shot_timeline.get("shot_segments") or shot_timeline.get("segments") or []
                segment_ids = {segment.get("shot_id") for segment in shot_segments}
                timeline_by_shot = {
                    segment.get("shot_id"): segment for segment in shot_segments
                }
                missing_timeline_shots = {
                    shot.id for shots in planned_shots.values() for shot in shots
                    if shot.id not in segment_ids
                    or approved_shots.get(shot.id) is None
                    or timeline_by_shot.get(shot.id, {}).get("asset_path") != approved_shots[shot.id].path
                }
                if missing_timeline_shots:
                    add_issue("shot_timeline", "Shot timeline is missing planned shots")
            except (OSError, json.JSONDecodeError, AttributeError):
                add_issue("shot_timeline", "Approved shot timeline is unreadable")

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

    stage_order = ["story", "status", "story_text", "image", "shot_image", "shot_timeline",
                   "audio", "subtitles", "scene_video", "full_video", "plex"]
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


def _build_approved_shot_timeline_for_library(story_id: str, story_dir: Path) -> Optional[Path]:
    """Build the release timeline when every planned shot is approved."""
    manifest = json.loads((story_dir / f"{story_id}.json").read_text(encoding="utf-8"))
    scenes = manifest.get("scenes") or []
    shot_plans = {}
    approved_assets = {}
    with ProductionStore(production_database_path()) as store:
        for index in range(1, len(scenes) + 1):
            scene_id = f"scene-{index:02d}"
            stored = store.list_shots(story_id, scene_id)
            if not stored:
                continue
            shot_plans[scene_id] = [ShotSpec(
                id=shot.id, scene_id=shot.scene_id, order=shot.order,
                purpose=shot.purpose, shot_type=shot.shot_type,
                duration_seconds=shot.duration_seconds,
                visual_context=shot.visual_context,
            ) for shot in stored]
            for shot in stored:
                asset = store.get_current_asset(story_id, shot.id, "image")
                if asset is not None and Path(asset.path).is_file():
                    approved_assets[shot.id] = asset.path
    if not shot_plans:
        return None
    segments = build_story_shot_timeline(scenes, shot_plans, approved_assets)
    return write_shot_timeline(story_id, story_dir, segments)


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

    if "shot_timeline" in missing:
        try:
            timeline_path = _build_approved_shot_timeline_for_library(story_id, story_dir)
        except ValueError:
            timeline_path = None
        if timeline_path is not None:
            result["steps"].append({"step": "shot_timeline", "result": str(timeline_path)})
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
        pre_plex_manifest = json.loads(
            (story_dir / f"{story_id}.json").read_text(encoding="utf-8")
        )
        write_story_timeline(story_id, story_dir, pre_plex_manifest.get("scenes", []))
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
    manifest_for_timeline = json.loads(manifest_path.read_text(encoding="utf-8"))
    timeline_path = write_story_timeline(
        story_id,
        story_dir,
        manifest_for_timeline.get("scenes", []),
    )
    result["timeline"] = str(timeline_path)
    with AssetRegistry(production_database_path()) as registry:
        registered_assets = registry.sync_story_directory(story_id, story_dir, approve=True)
    result["assets_registered"] = len(registered_assets)
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
    try:
        start_task(
            task_id,
            story_id="library",
            kind="library_maintenance",
            metadata={"story_ids": [story["id"] for story in selected], "auto": auto},
        )
    except Exception as exc:
        print(f"[library] durable task start failed: {exc}", file=sys.stderr)
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
    capabilities = tuple(
        value.strip()
        for value in os.environ.get("FANTASEE_WORKER_CAPABILITIES", "cpu,gpu").split(",")
        if value.strip()
    )
    worker = ProductionWorker(
        production_database_path(),
        worker_id=f"maintenance-{os.getpid()}",
        capabilities=capabilities,
    )

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
            try:
                start_task(
                    sub_id,
                    story_id=story_id,
                    kind="library_story",
                    metadata={"parent": task_id},
                )
                enqueue_task_job(
                    task_id,
                    job_id=sub_id,
                    job_type="library.complete",
                    payload={"story_id": story_id},
                )
            except Exception as exc:
                print(f"[library] durable child start failed: {exc}", file=sys.stderr)
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
                try:
                    update_task(
                        task_id,
                        stage=stage,
                        progress=overall,
                        message=f"{idx + 1}/{total}: {msg}",
                        payload={"story_id": story_id, "story_index": idx + 1, "story_count": total},
                    )
                except Exception as exc:
                    print(f"[library] durable progress update failed: {exc}", file=sys.stderr)
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
                def complete_library_job(_job, job_progress):
                    def combined_progress(stage: str, msg: str, pct: float) -> None:
                        progress(stage, msg, pct)
                        job_progress(stage, msg, pct)

                    return _complete_story_for_library(story_id, combined_progress)

                await worker.run_once(complete_library_job)
                with ProductionStore(production_database_path()) as store:
                    job_state = store.get_job(sub_id)
                if not job_state or job_state.status != "succeeded":
                    raise RuntimeError(job_state.message if job_state else "Maintenance job was not completed")
                result = {"status": "complete", "story_id": story_id}
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
                finalize_run_from_jobs(task_id)
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
        try:
            finish_task(
                task_id,
                status="succeeded" if not failed else "failed",
                message=f"Library maintenance complete: {len(completed)} complete, {len(failed)} failed",
                payload={"completed": completed, "failed": failed},
            )
        except Exception as exc:
            print(f"[library] durable task finish failed: {exc}", file=sys.stderr)
    finally:
        _library_maintenance_running = False


# ── Library agent loop ─────────────────────────────────────────────

async def recover_library_jobs() -> None:
    """Resume durable repair jobs left by a previous server process."""
    await asyncio.sleep(float(os.environ.get("FANTASEE_GENERATION_RECOVERY_DELAY", "5") or "5"))
    capabilities = tuple(
        value.strip()
        for value in os.environ.get("FANTASEE_WORKER_CAPABILITIES", "cpu,gpu").split(",")
        if value.strip()
    )
    worker = ProductionWorker(
        production_database_path(),
        worker_id=f"maintenance-recovery-{os.getpid()}",
        capabilities=capabilities,
    )

    while True:
        with ProductionStore(production_database_path()) as store:
            job = next(
                (item for item in store.list_runnable_jobs() if item.job_type == "library.complete"),
                None,
            )
        if job is None:
            return
        story_id = job.payload["story_id"]
        _generation_tasks.setdefault(job.run_id, {
            "id": job.run_id,
            "kind": "library_maintenance",
            "status": "running",
            "progress": 0,
            "message": "Recovered library maintenance",
            "created_at": now(),
        })
        _generation_tasks.setdefault(job.id, {
            "id": job.id,
            "parent": job.run_id,
            "kind": "library_story",
            "story_id": story_id,
            "status": "running",
            "progress": 0,
            "message": f"Recovering {story_id}",
            "created_at": now(),
        })

        def complete_recovered_job(_job, job_progress):
            def progress(stage: str, message: str, pct: float) -> None:
                _generation_tasks[job.id].update({
                    "stage": stage,
                    "progress": pct,
                    "message": message,
                    "status": "running",
                })
                _generation_tasks[job.run_id].update({
                    "stage": stage,
                    "progress": pct,
                    "message": message,
                    "status": "running",
                })
                job_progress(stage, message, pct)

            return _complete_story_for_library(story_id, progress)

        await worker.run_once(complete_recovered_job)
        with ProductionStore(production_database_path()) as store:
            finished = store.get_job(job.id)
        _generation_tasks[job.id].update({
            "status": "done" if finished and finished.status == "succeeded" else "error",
            "progress": 1.0,
            "message": finished.message if finished and finished.message else story_id,
        })
        finalize_run_from_jobs(job.run_id)


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
