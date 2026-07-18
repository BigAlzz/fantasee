"""Regression tests for truthful subtitle alignment."""

from types import SimpleNamespace

import generate_subtitles


class _FakeModel:
    def transcribe(self, *_args, **_kwargs):
        words = [
            SimpleNamespace(word="unrelated", start=0.0, end=0.5),
            SimpleNamespace(word="recognition", start=0.6, end=1.2),
            SimpleNamespace(word="drift", start=1.3, end=2.0),
        ]
        return [SimpleNamespace(words=words)], SimpleNamespace(
            language="en", language_probability=1.0,
        )


def test_alignment_falls_back_to_approved_script_when_recognition_drifts(monkeypatch):
    monkeypatch.setattr(generate_subtitles, "_get_whisper_model", lambda: _FakeModel())

    subtitles = generate_subtitles._generate_subtitles_word_aligned(
        "ignored.wav",
        "The red gate opens. The city holds its breath.",
    )

    assert [segment["text"] for segment in subtitles] == [
        "The red gate opens.",
        "The city holds its breath.",
    ]
    assert subtitles[0]["start"] == 0.0
    assert subtitles[-1]["end"] >= 1.9
