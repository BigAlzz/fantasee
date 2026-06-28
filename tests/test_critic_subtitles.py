import json


def test_analyze_subtitles_accepts_source_json_when_vtt_is_missing(tmp_path):
    from critic import analyze_subtitles

    story_id = "json-only-story"
    subs = tmp_path / f"subs_{story_id}_s01.json"
    subs.write_text(json.dumps([
        {"text": "First line.", "start": 0.0, "end": 1.2},
        {"text": "Second line.", "start": 1.2, "end": 2.4},
    ]), encoding="utf-8")

    scene = {"scene": "01", "subtitle_file": subs.name}
    result = analyze_subtitles(scene, tmp_path, story_id, audio_duration=2.5)

    assert result["cue_count"] == 2
    assert result["score"] > 0
    assert "VTT file not found" not in result["issues"]
    assert result["source"] == subs.name


def test_analyze_subtitles_reports_missing_only_when_no_sidecar_exists(tmp_path):
    from critic import analyze_subtitles

    result = analyze_subtitles({"scene": "01"}, tmp_path, "missing-story", audio_duration=1.0)

    assert result["cue_count"] == 0
    assert result["score"] == 0
    assert result["issues"] == ["Subtitle file not found"]
