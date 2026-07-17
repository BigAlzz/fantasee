"""Immutable generated-asset provenance seam."""

from __future__ import annotations

import hashlib
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

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "AssetRegistry":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()
