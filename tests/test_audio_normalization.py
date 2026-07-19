from __future__ import annotations

from tts_utils import NARRATION_LOUDNORM_FILTER


def test_narration_loudness_target_is_explicit_and_safe():
    assert "I=-16" in NARRATION_LOUDNORM_FILTER
    assert "TP=-1.5" in NARRATION_LOUDNORM_FILTER
    assert "LRA=11" in NARRATION_LOUDNORM_FILTER
