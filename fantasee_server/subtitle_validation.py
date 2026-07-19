"""Shared validation for narration subtitle segments."""

from __future__ import annotations

from typing import Any


def validate_subtitle_segments(
    segments: Any,
    audio_duration: float = 0.0,
    *,
    end_tolerance: float = 1.0,
) -> None:
    """Validate ordered, non-overlapping subtitle cues against narration audio.

    The validator is intentionally strict about overlaps so completion checks,
    timeline construction, and repair decisions agree on the same contract.
    """
    if not isinstance(segments, list) or not segments:
        raise ValueError("subtitle alignment is empty")

    previous_end = 0.0
    try:
        duration = float(audio_duration or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("audio duration is invalid") from exc

    for segment in segments:
        if not isinstance(segment, dict) or not str(segment.get("text") or "").strip():
            raise ValueError("subtitle alignment contains an empty segment")
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("subtitle alignment contains invalid timestamps") from exc
        if start < 0 or end <= start or start < previous_end:
            raise ValueError("subtitle alignment contains overlapping or invalid timestamps")
        if duration > 0 and end > duration + end_tolerance:
            raise ValueError("subtitle alignment extends beyond the narration audio")
        previous_end = end
