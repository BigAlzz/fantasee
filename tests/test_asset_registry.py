from fantasee_server.asset_registry import AssetRegistry


def test_same_generation_fingerprint_is_reused(tmp_path):
    registry = AssetRegistry(tmp_path / "production.db")

    first = registry.put_candidate(
        story_id="story-1",
        scene_id="scene-1",
        asset_type="image",
        path="working/image-a.png",
        generation_fingerprint="prompt-hash",
        metadata={"worker": "gpu-1"},
    )
    duplicate = registry.put_candidate(
        story_id="story-1",
        scene_id="scene-1",
        asset_type="image",
        path="working/image-b.png",
        generation_fingerprint="prompt-hash",
    )

    assert duplicate.id == first.id
    assert registry.get_current("story-1", "scene-1", "image") is None
    registry.close()


def test_approving_replacement_preserves_previous_asset(tmp_path):
    registry = AssetRegistry(tmp_path / "production.db")
    old = registry.put_candidate(
        story_id="story-1",
        scene_id="scene-1",
        asset_type="audio",
        path="audio-old.wav",
        generation_fingerprint="old",
    )
    registry.approve(old.id)
    replacement = registry.put_candidate(
        story_id="story-1",
        scene_id="scene-1",
        asset_type="audio",
        path="audio-new.wav",
        generation_fingerprint="new",
        supersedes=old.id,
    )
    registry.approve(replacement.id)

    assert registry.get_current("story-1", "scene-1", "audio").id == replacement.id
    assets = {asset.id: asset for asset in registry.list_assets("story-1")}
    assert assets[old.id].status == "superseded"
    assert assets[replacement.id].status == "approved"
    registry.close()
