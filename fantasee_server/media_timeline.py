"""Canonical narration/subtitle timeline for scene media."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fantasee_server.shot_planning import ShotSpec
from fantasee_server.subtitle_validation import validate_subtitle_segments


@dataclass(frozen=True)
class TimelineSegment:
    scene_id: str
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class ShotTimelineSegment:
    scene_id: str
    shot_id: str
    asset_path: str
    start: float
    end: float


def build_story_timeline(
    story_id: str, story_dir: str | Path, scenes: list[dict[str, Any]]
) -> list[TimelineSegment]:
    story_dir = Path(story_dir)
    timeline: list[TimelineSegment] = []
    offset = 0.0
    for index, scene in enumerate(scenes, start=1):
        scene_id = str(scene.get("scene") or f"{index:02d}")
        duration = float(scene.get("audio_duration") or 0)
        if duration <= 0:
            raise ValueError(f"Scene {scene_id} has no positive audio duration")
        subtitle_name = scene.get("subtitle_file")
        if not subtitle_name:
            subtitle_name = f"subs_{story_id}_s{scene_id}.json"
        subtitle_path = story_dir / subtitle_name
        try:
            segments = json.loads(subtitle_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Scene {scene_id} subtitles are unreadable") from exc
        try:
            validate_subtitle_segments(segments, duration)
        except ValueError as exc:
            raise ValueError(f"Scene {scene_id} {str(exc)}") from exc
        for raw in segments:
            text = str(raw.get("text") or "").strip()
            start = float(raw.get("start"))
            end = float(raw.get("end"))
            timeline.append(TimelineSegment(scene_id, text, offset + start, offset + end))
        offset += duration
    return timeline


def write_story_timeline(
    story_id: str, story_dir: str | Path, scenes: list[dict[str, Any]]
) -> Path:
    story_dir = Path(story_dir)
    timeline = build_story_timeline(story_id, story_dir, scenes)
    target = story_dir / "working" / "timeline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    payload: dict[str, Any] = {
        "story_id": story_id,
        "segments": [asdict(segment) for segment in timeline],
    }
    # Narration maintenance may rebuild this file after an editorial pass.
    # Preserve approved visual segments so the canonical timeline remains the
    # single source for both subtitle timing and shot selection.
    try:
        previous = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(previous, dict) and isinstance(previous.get("shot_segments"), list):
            payload["shot_segments"] = previous["shot_segments"]
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return target


def build_shot_timeline(
    *,
    scene_id: str,
    scene_start: float,
    scene_duration: float,
    shots: list[ShotSpec],
    approved_assets: dict[str, str],
) -> list[ShotTimelineSegment]:
    """Project approved semantic shots into the scene's canonical time range."""
    if scene_duration <= 0:
        raise ValueError("Scene duration must be positive")
    if not shots:
        raise ValueError("Scene has no semantic shots")
    if any(shot.id not in approved_assets for shot in shots):
        raise ValueError("Every shot needs an approved image before timeline construction")
    total = sum(float(shot.duration_seconds) for shot in shots)
    if total <= 0:
        raise ValueError("Shot durations must be positive")
    scale = scene_duration / total
    offset = float(scene_start)
    timeline: list[ShotTimelineSegment] = []
    for shot in sorted(shots, key=lambda item: (item.order, item.id)):
        duration = float(shot.duration_seconds) * scale
        timeline.append(
            ShotTimelineSegment(
                scene_id=scene_id,
                shot_id=shot.id,
                asset_path=approved_assets[shot.id],
                start=round(offset, 6),
                end=round(offset + duration, 6),
            )
        )
        offset += duration
    # Avoid accumulated floating point drift at the scene boundary.
    last = timeline[-1]
    timeline[-1] = ShotTimelineSegment(
        scene_id=last.scene_id,
        shot_id=last.shot_id,
        asset_path=last.asset_path,
        start=last.start,
        end=round(scene_start + scene_duration, 6),
    )
    return timeline


def build_story_shot_timeline(
    scenes: list[dict[str, Any]],
    shot_plans: dict[str, list[ShotSpec]],
    approved_assets: dict[str, str],
) -> list[ShotTimelineSegment]:
    """Build approved shot segments at absolute story time offsets."""
    segments: list[ShotTimelineSegment] = []
    story_offset = 0.0
    for index, scene in enumerate(scenes, start=1):
        scene_id = f"scene-{int(scene.get('scene') or index):02d}"
        duration = float(scene.get("audio_duration") or 0.0)
        shots = shot_plans.get(scene_id, [])
        if shots:
            segments.extend(build_shot_timeline(
                scene_id=scene_id,
                scene_start=story_offset,
                scene_duration=duration,
                shots=shots,
                approved_assets=approved_assets,
            ))
        story_offset += duration
    return segments


def write_shot_timeline(
    story_id: str,
    story_dir: str | Path,
    segments: list[ShotTimelineSegment],
) -> Path:
    """Persist the approved visual timeline as an atomic working artifact."""
    story_dir = Path(story_dir)
    target = story_dir / "working" / "shot_timeline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    new_segments = [asdict(item) for item in segments]
    previous_segments: list[dict[str, Any]] = []
    canonical: dict[str, Any] = {"story_id": story_id}
    try:
        loaded = json.loads((story_dir / "working" / "timeline.json").read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            canonical = loaded
            previous_segments = loaded.get("shot_segments") or []
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    scene_ids = {segment.get("scene_id") for segment in new_segments}
    merged_segments = [
        segment for segment in previous_segments
        if segment.get("scene_id") not in scene_ids
    ] + new_segments
    shot_payload = {"story_id": story_id, "segments": merged_segments}
    canonical["story_id"] = story_id
    canonical["shot_segments"] = merged_segments
    temporary.write_text(json.dumps(shot_payload, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    canonical_target = story_dir / "working" / "timeline.json"
    canonical_tmp = canonical_target.with_suffix(".json.tmp")
    canonical_tmp.write_text(json.dumps(canonical, indent=2), encoding="utf-8")
    os.replace(canonical_tmp, canonical_target)
    return target
