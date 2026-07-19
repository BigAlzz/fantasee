from pathlib import Path


def test_character_portrait_generation_preserves_world_context(tmp_path, monkeypatch):
    from fantasee_server.api import world
    import comfyui_utils

    monkeypatch.setattr(world, "GEN_OUTPUTS", tmp_path)
    monkeypatch.setattr(comfyui_utils, "is_running", lambda: {"running": True})
    captured = {}

    def fake_generate_image(**kwargs):
        captured.update(kwargs)
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        (output / "world_character_nara.png").write_bytes(b"fake")
        return "world_character_nara.png"

    monkeypatch.setattr(comfyui_utils, "generate_image", fake_generate_image)
    result = world.generate_character_portrait({
        "character_id": "nara",
        "name": "Nara",
        "role": "Human scout",
        "appearance": "weathered braids and a blue stone pendant",
        "alignment": "rebellious good",
        "traits": "observant, protective",
        "world_context": "Humans and Neanderthals share an Ice Age valley.",
    })

    assert result["url"] == "/generated-images/world/characters/world_character_nara.png"
    assert "Ice Age valley" in captured["prompt"]
    assert captured["seed"] > 0
    assert captured["width"] == 256
    assert captured["height"] == 320


def test_character_portrait_batch_uses_small_parallel_jobs(tmp_path, monkeypatch):
    from fantasee_server.api import world
    import comfyui_utils

    monkeypatch.setattr(world, "GEN_OUTPUTS", tmp_path)
    captured = {}

    def fake_parallel(jobs, output_dir, **kwargs):
        captured["jobs"] = jobs
        captured["kwargs"] = kwargs
        return ["world_character_nara.png", "world_character_var.png"]

    monkeypatch.setattr(comfyui_utils, "generate_images_parallel", fake_parallel)
    result = world.generate_character_portraits({
        "world_context": "Ice Age valley",
        "characters": [
            {"character_id": "nara", "name": "Nara", "role": "scout"},
            {"character_id": "var", "name": "Var", "role": "toolmaker"},
        ],
    })

    assert [portrait["character_id"] for portrait in result["portraits"]] == ["nara", "var"]
    assert all(job["width"] == 256 and job["height"] == 320 for job in captured["jobs"])
    assert captured["kwargs"]["max_workers"] == 2


def test_story_thumbnail_updates_manifest_after_asset_generation(tmp_path, monkeypatch):
    import json
    from fantasee_server.api import world
    import comfyui_utils

    story_id = "thumbnail-story"
    story_dir = tmp_path / story_id
    story_dir.mkdir()
    manifest_path = story_dir / f"{story_id}.json"
    manifest_path.write_text(json.dumps({
        "id": story_id,
        "title": "The Winter Crossing",
        "description": "Two lineages share one impossible pass.",
    }), encoding="utf-8")
    monkeypatch.setattr(world, "generated_story_dir", lambda _story_id: story_dir)
    monkeypatch.setattr(comfyui_utils, "is_running", lambda: {"running": True})

    def fake_generate_image(**kwargs):
        (Path(kwargs["output_dir"]) / "thumbnail.png").write_bytes(b"fake")
        return "thumbnail.png"

    monkeypatch.setattr(comfyui_utils, "generate_image", fake_generate_image)
    result = world.generate_story_thumbnail(story_id)

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["url"] == f"/generated/{story_id}/thumbnail.png"
    assert saved["story_thumbnail"] == "thumbnail.png"
    assert saved["story_thumbnail_provenance"]["width"] == 384
