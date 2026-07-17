"""Canonical narration/subtitle timeline for scene media."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TimelineSegment:
    scene_id: str
    text: str
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
