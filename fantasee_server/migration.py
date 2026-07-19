"""Read-only migration inventory for the legacy-to-Studio transition."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fantasee_server.discovery import discover_generated_stories, iter_generated_story_dirs
from fantasee_server.paths import GEN_OUTPUTS


def _manifest_fingerprint(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    try:
        digest.update(path.read_bytes())
    except OSError:
        return ""
    return digest.hexdigest()


def migration_readiness() -> dict:
    """Inventory every discovered story without changing its files."""
    directories = {path.name: path for path in iter_generated_story_dirs()}
    rows: list[dict] = []
    for story in discover_generated_stories():
        story_id = str(story.get("id") or "")
        story_dir = directories.get(story_id)
        completion = story.get("completion") or {}
        storage_root = str(story.get("storage_root") or "unknown")
        risks: list[str] = []
        if storage_root == "outputs":
            risks.append("legacy_read_only")
        if not completion.get("complete"):
            risks.append("incomplete_outputs")
        if story_dir is None:
            risks.append("story_directory_not_found")
        manifest_path = story_dir / f"{story_id}.json" if story_dir else None
        if manifest_path is None or not manifest_path.is_file():
            risks.append("manifest_missing")
        backup_root = story_dir / ".backup" if story_dir else None
        rollback_ready = bool(backup_root and backup_root.is_dir() and any(backup_root.iterdir()))
        if not rollback_ready:
            risks.append("no_local_backup_detected")
        rows.append({
            "id": story_id,
            "title": story.get("title") or story_id,
            "storage_root": storage_root,
            "path": str(story_dir) if story_dir else "",
            "scene_count": int(story.get("scene_count") or 0),
            "complete": bool(completion.get("complete")),
            "missing": list(completion.get("missing") or []),
            "issue_count": int(completion.get("issue_count") or 0),
            "manifest_fingerprint": _manifest_fingerprint(manifest_path) if manifest_path else "",
            "rollback_ready": rollback_ready,
            "migration_ready": storage_root == "stories" and not risks,
            "risks": risks,
        })
    rows.sort(key=lambda row: (row["storage_root"] != "stories", row["title"].lower()))
    return {
        "stories": rows,
        "summary": {
            "total": len(rows),
            "migration_ready": sum(1 for row in rows if row["migration_ready"]),
            "legacy_read_only": sum(1 for row in rows if row["storage_root"] == "outputs"),
            "incomplete": sum(1 for row in rows if not row["complete"]),
            "rollback_ready": sum(1 for row in rows if row["rollback_ready"]),
        },
        "destructive_actions_performed": False,
    }
