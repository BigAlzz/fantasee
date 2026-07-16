"""Crash-safe stage checkpoints for the story production pipeline."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


PIPELINE_STAGES = (
    "story",
    "outline",
    "images",
    "audio",
    "subtitles",
    "render",
    "plex",
)


def _state_path(story_dir: Path) -> Path:
    return story_dir / "working" / "pipeline.json"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_pipeline(story_dir: Path) -> dict | None:
    path = _state_path(story_dir)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def initialize_pipeline(story_dir: Path, story_id: str) -> dict:
    """Create a new stage machine while preserving a prior run as history."""
    prior = load_pipeline(story_dir)
    state = {
        "version": "1.0",
        "story_id": story_id,
        "status": "running",
        "current_stage": "story",
        "started_at": _timestamp(),
        "updated_at": _timestamp(),
        "stages": {
            stage: {"status": "pending", "attempts": 0}
            for stage in PIPELINE_STAGES
        },
    }
    if prior and prior.get("status") in {"failed", "complete"}:
        state["previous_run"] = {
            "status": prior.get("status"),
            "updated_at": prior.get("updated_at"),
        }
    _write(_state_path(story_dir), state)
    return state


def update_stage(
    story_dir: Path,
    stage: str,
    status: str,
    *,
    message: str = "",
    details: dict | None = None,
) -> dict:
    """Record a stage transition and return the new pipeline state."""
    if stage not in PIPELINE_STAGES:
        raise ValueError(f"Unknown story pipeline stage: {stage}")
    state = load_pipeline(story_dir) or initialize_pipeline(story_dir, story_dir.name)
    record = state.setdefault("stages", {}).setdefault(stage, {"attempts": 0})
    if status == "running":
        record["attempts"] = int(record.get("attempts", 0)) + 1
    record["status"] = status
    record["updated_at"] = _timestamp()
    if message:
        record["message"] = message
    if details:
        record["details"] = details

    state["updated_at"] = _timestamp()
    state["current_stage"] = stage
    if status == "failed":
        state["status"] = "failed"
        state["last_error"] = message
    elif all(
        state.get("stages", {}).get(name, {}).get("status") == "complete"
        for name in PIPELINE_STAGES
    ):
        state["status"] = "complete"
        state["completed_at"] = _timestamp()
    else:
        state["status"] = "running"
    _write(_state_path(story_dir), state)
    return state


def sync_from_completion(story_dir: Path, report: dict) -> dict:
    """Project the file-backed completion report onto pipeline stages."""
    missing = set(report.get("missing") or [])
    state = load_pipeline(story_dir) or initialize_pipeline(story_dir, story_dir.name)
    mapping = {
        "story": "story",
        "status": "story",
        "story_text": "outline",
        "image": "images",
        "audio": "audio",
        "subtitles": "subtitles",
        "scene_video": "render",
        "full_video": "render",
        "plex": "plex",
    }
    for issue_kind, stage in mapping.items():
        if issue_kind in missing:
            state.setdefault("stages", {}).setdefault(stage, {})["status"] = "pending"
        elif state.setdefault("stages", {}).setdefault(stage, {}).get("status") != "failed":
            state["stages"][stage]["status"] = "complete"
    state["status"] = "complete" if report.get("complete") else "running"
    state["current_stage"] = next(
        (stage for stage in PIPELINE_STAGES
         if state.get("stages", {}).get(stage, {}).get("status") != "complete"),
        "complete",
    )
    state["updated_at"] = _timestamp()
    if report.get("complete"):
        state["completed_at"] = _timestamp()
    _write(_state_path(story_dir), state)
    return state
