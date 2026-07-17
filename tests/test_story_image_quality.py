"""Regression coverage for blank images and images-per-scene targets."""

import json
from pathlib import Path

import pytest

from fantasee_server.library import story_completion_report


Image = pytest.importorskip("PIL.Image")


def _checkerboard(path: Path) -> None:
    image = Image.new("RGB", (128, 128), (20, 30, 40))
    for y in range(0, 128, 16):
        for x in range(0, 128, 16):
            if (x // 16 + y // 16) % 2 == 0:
                for yy in range(y, y + 16):
                    for xx in range(x, x + 16):
                        image.putpixel((xx, yy), (210, 150, 70))
    image.save(path)


def test_rejects_black_comfyui_output(tmp_path):
    from image_quality import inspect_story_image

    black = tmp_path / "black.png"
    Image.new("RGB", (896, 512), (0, 0, 0)).save(black)

    usable, reason = inspect_story_image(black)

    assert not usable
    assert "blank" in reason.lower()


def test_accepts_non_uniform_story_art(tmp_path):
    from image_quality import inspect_story_image

    art = tmp_path / "art.png"
    _checkerboard(art)

    usable, reason = inspect_story_image(art)

    assert usable, reason


def test_infers_seven_image_target_from_legacy_manifest():
    from image_quality import requested_images_per_scene

    manifest = {
        "scenes": [
            {"image_filenames": [f"scene-01-{index}.png" for index in range(7)]},
            {"image_filenames": [f"scene-02-{index}.png" for index in range(7)]},
        ]
    }

    assert requested_images_per_scene(manifest) == 7


def test_missing_legacy_images_still_requires_one_image():
    from image_quality import requested_images_per_scene

    assert requested_images_per_scene({"scenes": [{"image_filenames": []}]}) == 1


def test_completion_report_rejects_black_images_and_reports_target(tmp_path):
    slug = "blank-images"
    story_dir = tmp_path / slug
    story_dir.mkdir()
    image_names = []
    for index in range(7):
        name = f"{slug}_s01_blank_{index + 1:02d}_00001_.png"
        Image.new("RGB", (896, 512), (0, 0, 0)).save(story_dir / name)
        image_names.append(name)

    story = {
        "id": slug,
        "status": "draft",
        "images_per_scene": 7,
        "scenes": [{
            "scene": "01",
            "prompt": "A knight crosses a ruined bridge.",
            "narration": "The knight crosses the bridge while stones fall behind her.",
            "image_filenames": image_names,
        }],
    }
    (story_dir / f"{slug}.json").write_text(json.dumps(story), encoding="utf-8")

    report = story_completion_report(slug, story=story, story_dir=story_dir)

    image_issues = [issue for issue in report["issues"] if issue["kind"] == "image"]
    assert image_issues
    assert "0 of 7 usable" in image_issues[0]["message"]


def test_scene_repair_replaces_all_seven_images_and_invalidates_video(tmp_path, monkeypatch):
    import comfyui_utils
    import story_actions

    slug = "seven-image-repair"
    old_image = tmp_path / "old.png"
    _checkerboard(old_image)
    stale_scene_video = tmp_path / f"{slug}_s01.mp4"
    stale_full_video = tmp_path / f"{slug}_full.mp4"
    stale_plex_video = tmp_path / "final" / "plex" / "story.mp4"
    stale_plex_video.parent.mkdir(parents=True)
    for video in (stale_scene_video, stale_full_video, stale_plex_video):
        video.write_bytes(b"stale video")

    generated = []

    def fake_generate_image(**kwargs):
        name = f"{kwargs['output_prefix']}_00001_.png"
        generated.append(name)
        return name

    monkeypatch.setattr(comfyui_utils, "is_running", lambda: {"running": True})
    monkeypatch.setattr(comfyui_utils, "checkpoint_for_style", lambda _style: "test.safetensors")
    monkeypatch.setattr(comfyui_utils, "generate_image", fake_generate_image)
    scene = {"prompt": "A knight crosses a bridge.", "image_filenames": [old_image.name]}
    manifest = {"images_per_scene": 7, "tags": ["cinematic"]}

    story_actions._regen_scene_image(tmp_path, slug, "01", "Bridge", scene, manifest)

    assert len(generated) == 7
    assert scene["image_filenames"] == generated
    assert not old_image.exists()
    assert not stale_scene_video.exists()
    assert not stale_full_video.exists()
    assert not stale_plex_video.exists()


def test_partial_scene_repair_preserves_previous_artwork(tmp_path, monkeypatch):
    import comfyui_utils
    import story_actions

    old_image = tmp_path / "old.png"
    _checkerboard(old_image)
    calls = 0

    def incomplete_generation(**_kwargs):
        nonlocal calls
        calls += 1
        return "new.png" if calls == 1 else None

    monkeypatch.setattr(comfyui_utils, "is_running", lambda: {"running": True})
    monkeypatch.setattr(comfyui_utils, "checkpoint_for_style", lambda _style: "test.safetensors")
    monkeypatch.setattr(comfyui_utils, "generate_image", incomplete_generation)
    scene = {"prompt": "A knight crosses a bridge.", "image_filenames": [old_image.name]}

    with pytest.raises(RuntimeError, match="1 of 7 usable images"):
        story_actions._regen_scene_image(
            tmp_path,
            "partial-repair",
            "01",
            "Bridge",
            scene,
            {"images_per_scene": 7, "tags": ["cinematic"]},
        )

    assert old_image.exists()
    assert scene["image_filenames"] == [old_image.name]
