import json

from fantasee_server.media_timeline import build_story_timeline


def test_timeline_offsets_subtitles_by_accumulated_audio_duration(tmp_path):
    story_id = "story-1"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    (story_dir / "subs-01.json").write_text(
        json.dumps([{"text": "One", "start": 0, "end": 1}]), encoding="utf-8"
    )
    (story_dir / "subs-02.json").write_text(
        json.dumps([{"text": "Two", "start": 0.2, "end": 1.5}]), encoding="utf-8"
    )
    scenes = [
        {"scene": "01", "subtitle_file": "subs-01.json", "audio_duration": 2.0},
        {"scene": "02", "subtitle_file": "subs-02.json", "audio_duration": 3.0},
    ]

    timeline = build_story_timeline(story_id, story_dir, scenes)

    assert timeline[0].start == 0
    assert timeline[0].end == 1
    assert timeline[1].start == 2.2
    assert timeline[1].end == 3.5
    assert timeline[1].scene_id == "02"
