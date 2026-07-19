import json

import pytest


def test_completion_supervisor_stops_when_repair_evidence_does_not_change(monkeypatch):
    from fantasee_server import library

    monkeypatch.setenv("FANTASEE_SUPERVISOR_MAX_ITERATIONS", "3")
    calls = []
    report = {
        "complete": False,
        "missing": ["subtitles"],
        "issues": [{"kind": "subtitles", "scene": "01", "message": "overlap"}],
    }

    def fake_iteration(_story_id, _progress):
        calls.append("iteration")
        raise RuntimeError("subtitle repair failed")

    monkeypatch.setattr(library, "_complete_story_iteration", fake_iteration)
    monkeypatch.setattr(library, "story_completion_report", lambda _story_id: report)

    with pytest.raises(RuntimeError, match="no progress"):
        library._complete_story_for_library("story", lambda *_args: None)

    assert calls == ["iteration", "iteration"]


def test_critic_hook_runs_after_structural_completion_and_marks_outputs_stale(monkeypatch, tmp_path):
    from fantasee_server import library

    story_id = "story"
    manifest_path = tmp_path / f"{story_id}.json"
    manifest_path.write_text(json.dumps({
        "status": "complete",
        "scenes": [{"prompt": "old prompt", "narration": "same"}],
    }), encoding="utf-8")
    monkeypatch.setenv("FANTASEE_AUTO_CRITIC", "1")
    monkeypatch.setattr(library, "generated_story_dir", lambda _story_id: tmp_path)

    def fake_critic(_story_id, _body, progress=None):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["scenes"][0]["prompt"] = "new prompt"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return {"status": "target_reached"}

    monkeypatch.setattr("fantasee_server.improver._run_improve_loop_sync", fake_critic)

    result = library._run_quality_improvement_for_library(story_id, lambda *_args: None)
    assert result["changed_outputs"] is True
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "draft"
    assert set(manifest["scenes"][0]["stale_outputs"]) == {"scene_video", "full_video", "plex"}
