from pathlib import Path

import story_actions


def test_subtitle_repair_preserves_last_valid_file_when_generation_fails(tmp_path, monkeypatch):
    story_id = "story"
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    subtitle = tmp_path / f"subs_{story_id}_s01.json"
    subtitle.write_text('[{"text": "old", "start": 0, "end": 1}]', encoding="utf-8")

    import generate_subtitles

    def fail_generation(*_args, **_kwargs):
        raise RuntimeError("Whisper unavailable")

    monkeypatch.setattr(generate_subtitles, "generate_subtitles", fail_generation)

    try:
        story_actions._regen_scene_subs(
            tmp_path,
            story_id,
            "01",
            {"audio_filename": audio.name, "narration": "A sentence."},
            {},
        )
    except RuntimeError as exc:
        assert "Whisper unavailable" in str(exc)
    else:
        raise AssertionError("subtitle repair should fail")

    assert subtitle.read_text(encoding="utf-8") == '[{"text": "old", "start": 0, "end": 1}]'

