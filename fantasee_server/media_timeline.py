"""Canonical narration/subtitle timeline for scene media."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fantasee_server.shot_planning import ShotSpec


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
        if not isinstance(segments, list) or not segments:
            raise ValueError(f"Scene {scene_id} subtitles are empty")
        previous_end = 0.0
        for raw in segments:
            text = str(raw.get("text") or "").strip()
            start = float(raw.get("start"))
            end = float(raw.get("end"))
            if not text or start < 0 or end <= start or start < previous_end:
                raise ValueError(f"Scene {scene_id} contains invalid subtitle timing")
            if end > duration + 1.0:
                raise ValueError(f"Scene {scene_id} subtitles exceed audio duration")
            timeline.append(TimelineSegment(scene_id, text, offset + start, offset + end))
            previous_end = end
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
    temporary.write_text(
        json.dumps(
            {
                "story_id": story_id,
                "segments": [asdict(segment) for segment in timeline],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
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
    payload: dict[str, Any] = {"story_id": story_id, "segments": [asdict(item) for item in segments]}
    try:
        canonical = json.loads((story_dir / "working" / "timeline.json").read_text(encoding="utf-8"))
        if isinstance(canonical, dict):
            canonical["shot_segments"] = payload["segments"]
            payload = canonical
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    canonical_target = story_dir / "working" / "timeline.json"
    canonical_tmp = canonical_target.with_suffix(".json.tmp")
    canonical_tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(canonical_tmp, canonical_target)
    return target
