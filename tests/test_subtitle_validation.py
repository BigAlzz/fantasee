import pytest

from fantasee_server.subtitle_validation import validate_subtitle_segments


def test_subtitle_validation_rejects_even_small_overlaps():
    with pytest.raises(ValueError, match="overlapping"):
        validate_subtitle_segments(
            [
                {"text": "First", "start": 0.0, "end": 1.0},
                {"text": "Second", "start": 0.99, "end": 2.0},
            ],
            audio_duration=2.0,
        )


def test_subtitle_validation_accepts_monotonic_segments_inside_audio():
    validate_subtitle_segments(
        [
            {"text": "First", "start": 0.0, "end": 1.0},
            {"text": "Second", "start": 1.0, "end": 2.0},
        ],
        audio_duration=2.0,
    )

