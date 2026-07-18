from __future__ import annotations

import json


def test_discovery_prefers_scene_art_over_title_slide(tmp_path, monkeypatch):
    from fantasee_server import discovery

    story_id = "scene-cover-story"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    (story_dir / "assets" / "title").mkdir(parents=True)
    (story_dir / "assets" / "title" / "title_slide.png").write_bytes(b"title")
    (story_dir / "scene.png").write_bytes(b"scene")
    (story_dir / f"{story_id}.json").write_text(json.dumps({
        "id": story_id,
        "title": "Scene cover",
        "title_image": "assets/title/title_slide.png",
        "scenes": [{"image_filenames": ["scene.png"]}],
    }), encoding="utf-8")
    monkeypatch.setattr(discovery, "GEN_OUTPUTS", tmp_path)
    monkeypatch.setattr(discovery, "LEGACY_GEN_OUTPUTS", tmp_path / "missing-legacy")
    monkeypatch.setattr(discovery, "generated_story_dir", lambda story: tmp_path / story)
    monkeypatch.setattr(discovery, "atomic_write_json", lambda *args, **kwargs: None)
    monkeypatch.setattr("fantasee_server.library.story_completion_report", lambda *args, **kwargs: {})

    result = discovery.discover_generated_stories()

    assert result[0]["hero_image"] == "scene.png"
    assert result[0]["cover_image_url"] == "/generated/scene-cover-story/scene.png"


def test_discovery_prefers_explicit_story_thumbnail_over_scene_art(tmp_path, monkeypatch):
    from fantasee_server import discovery

    story_id = "thumbnail-cover-story"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    (story_dir / "thumbnail.png").write_bytes(b"thumbnail")
    (story_dir / "scene.png").write_bytes(b"scene")
    (story_dir / f"{story_id}.json").write_text(json.dumps({
        "id": story_id,
        "title": "Thumbnail cover",
        "story_thumbnail": "thumbnail.png",
        "scenes": [{"image_filenames": ["scene.png"]}],
    }), encoding="utf-8")
    monkeypatch.setattr(discovery, "GEN_OUTPUTS", tmp_path)
    monkeypatch.setattr(discovery, "LEGACY_GEN_OUTPUTS", tmp_path / "missing-legacy")
    monkeypatch.setattr(discovery, "generated_story_dir", lambda story: tmp_path / story)
    monkeypatch.setattr(discovery, "atomic_write_json", lambda *args, **kwargs: None)
    monkeypatch.setattr("fantasee_server.library.story_completion_report", lambda *args, **kwargs: {})

    result = discovery.discover_generated_stories()

    assert result[0]["hero_image"] == "thumbnail.png"
    assert result[0]["cover_image_url"] == "/generated/thumbnail-cover-story/thumbnail.png"


def test_discovery_does_not_publish_missing_scene_art(tmp_path, monkeypatch):
    from fantasee_server import discovery

    story_id = "missing-art-story"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    (story_dir / f"{story_id}.json").write_text(json.dumps({
        "id": story_id,
        "title": "Missing art",
        "scenes": [{"image_filenames": ["removed.png"]}],
    }), encoding="utf-8")
    monkeypatch.setattr(discovery, "GEN_OUTPUTS", tmp_path)
    monkeypatch.setattr(discovery, "LEGACY_GEN_OUTPUTS", tmp_path / "missing-legacy")
    monkeypatch.setattr("fantasee_server.library.story_completion_report", lambda *args, **kwargs: {})

    result = discovery.discover_generated_stories()

    assert result[0]["scenes"][0]["image_urls"] == []
    assert result[0].get("cover_image_url") is None
