"""Immutable generated-asset provenance seam."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fantasee_server.production_store import ProductionAsset, ProductionStore


class AssetRegistry:
    def __init__(self, database_path: str | Path):
        self.store = ProductionStore(database_path)

    def put_candidate(
        self,
        *,
        story_id: str,
        scene_id: str,
        asset_type: str,
        path: str,
        generation_fingerprint: str,
        content_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
        supersedes: str | None = None,
    ) -> ProductionAsset:
        return self.store.register_asset(
            story_id=story_id,
            scene_id=scene_id,
            asset_type=asset_type,
            path=path,
            content_hash=content_hash,
            generation_fingerprint=generation_fingerprint,
            metadata=metadata,
            supersedes=supersedes,
        )

    def put_file_candidate(self, **kwargs: Any) -> ProductionAsset:
        path = Path(kwargs["path"])
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        kwargs["path"] = str(path)
        kwargs["content_hash"] = content_hash
        return self.put_candidate(**kwargs)

    def approve(self, asset_id: str) -> ProductionAsset:
        return self.store.approve_asset(asset_id)

    def get_current(self, story_id: str, scene_id: str, asset_type: str) -> ProductionAsset | None:
        return self.store.get_current_asset(story_id, scene_id, asset_type)

    def list_assets(self, story_id: str) -> list[ProductionAsset]:
        return self.store.list_assets(story_id)

    def sync_story_directory(
        self, story_id: str, story_dir: str | Path, *, approve: bool = False
    ) -> list[ProductionAsset]:
        """Record files named by a story manifest without moving or deleting them."""
        story_dir = Path(story_dir)
        manifest_path = story_dir / f"{story_id}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records: list[ProductionAsset] = []

        def record(scene_id: str, asset_type: str, filename: str) -> None:
            path = story_dir / filename
            if not path.is_file() or path.stat().st_size <= 0:
                return
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            asset = self.put_candidate(
                story_id=story_id,
                scene_id=scene_id,
                asset_type=asset_type,
                path=str(path),
                content_hash=content_hash,
                generation_fingerprint=f"{asset_type}:{scene_id}:{content_hash}",
            )
            records.append(self.approve(asset.id) if approve else asset)

        for index, scene in enumerate(manifest.get("scenes") or [], start=1):
            scene_id = f"s{index:02d}"
            for filename in scene.get("image_filenames") or []:
                record(f"{scene_id}:{filename}", "image", filename)
            for field, asset_type in (("audio_filename", "audio"), ("subtitle_file", "subtitles")):
                filename = scene.get(field)
                if filename:
                    record(scene_id, asset_type, filename)
            for filename in (f"{story_id}_{scene_id}.mp4", f"{story_id}_{index}.mp4"):
                record(scene_id, "scene_video", filename)

        record("story", "full_video", f"{story_id}_full.mp4")
        for path in sorted((story_dir / "final" / "plex").glob("*.mp4")):
            record("story", "plex", str(path.relative_to(story_dir)))
        return records

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "AssetRegistry":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()
