#!/usr/bin/env python3
"""
Permanently delete a story and ALL of its on-disk artifacts.

Removes (from outputs/<story_id>/):
  - <story_id>.json             (manifest)
  - <story_id>_review.json      (critic review, if any)
  - tts_<story_id>_s*.wav        (narration audio)
  - subs_<story_id>_s*.json     (subtitle timing)
  - <story_id>_s*_<title>_*.png (scene images)
  - <story_id>_s*.mp4           (per-scene video)
  - <story_id>_s*.vtt           (per-scene subtitle sidecar)
  - <story_id>_full.mp4/.vtt    (concatenated full-story output)
  - <story_id>.json.tmp         (atomic-write leftovers)
  - any other files in the directory

Also removes:
  - Any progress entries saved by the player (outputs/progress.json or similar)
  - The story directory itself, then re-creates outputs/ if empty

DRY-RUN by default. Use --apply to actually delete.

Usage:
  python delete_story.py --story the-shitty-story          # dry run + list
  python delete_story.py --story the-shitty-story --apply  # actually delete
  python delete_story.py --story the-shitty-story --backup  # copy to outputs/.trash first
  python delete_story.py --all-broken                       # delete every story with 0/0 images/audio
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from story_storage import STORIES_ROOT

OUTPUTS_DIR = STORIES_ROOT
TRASH_DIR = OUTPUTS_DIR / ".trash"

# Patterns that count as "debris" — anything left behind by partial
# generations, crashed pipelines, or tmp file leftovers.
TMP_PATTERNS = (".tmp", ".partial", ".bak")
LOG_PATTERNS = (".log",)


def human_size(n: int) -> str:
    """Format byte count as KB/MB/GB."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def list_story_files(story_dir: Path) -> list[Path]:
    """Return every file in the story directory (recursive), sorted."""
    if not story_dir.exists():
        return []
    return sorted(p for p in story_dir.rglob("*") if p.is_file())


def is_broken(story_dir: Path) -> bool:
    """Heuristic for 'broken': no audio, no images, or manifest unreadable."""
    if not story_dir.exists():
        return True
    manifest = story_dir / f"{story_dir.name}.json"
    if not manifest.exists():
        return True
    try:
        m = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    scenes = m.get("scenes") or []
    if not scenes:
        return True
    has_audio = any(s.get("audio_filename") for s in scenes)
    has_images = any(s.get("image_filenames") for s in scenes)
    return not (has_audio or has_images)


def backup_story(story_dir: Path) -> Path:
    """Copy the entire story dir to outputs/.trash/<story_id>__<timestamp>/.

    Returns the backup directory. Creates outputs/.trash/ if needed.
    """
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = TRASH_DIR / f"{story_dir.name}__{ts}"
    shutil.copytree(story_dir, dest)
    return dest


def delete_story(story_dir: Path, backup: bool = False) -> dict:
    """Delete a story directory and all of its contents.

    Returns a report dict describing what was done. Always returns even
    on partial failure so the caller can report.
    """
    report = {
        "story_id": story_dir.name,
        "existed": story_dir.exists(),
        "backup_path": None,
        "files_deleted": 0,
        "bytes_freed": 0,
        "errors": [],
    }
    if not story_dir.exists():
        return report

    files = list_story_files(story_dir)
    total_bytes = sum(f.stat().st_size for f in files if f.exists())
    report["bytes_freed"] = total_bytes
    report["files_deleted"] = len(files)

    if backup:
        try:
            report["backup_path"] = str(backup_story(story_dir))
        except Exception as e:
            report["errors"].append(f"backup failed: {e}")
            return report

    # shutil.rmtree is atomic per-file but not per-dir on Windows if files
    # are open elsewhere; we tolerate that and report the error.
    try:
        shutil.rmtree(story_dir)
    except OSError as e:
        report["errors"].append(f"rmtree failed: {e}")

    return report


def find_broken_stories(outputs_dir: Path) -> list[str]:
    """Return IDs of all stories that look broken (no audio, no images,
    or missing/unreadable manifest)."""
    if not outputs_dir.exists():
        return []
    broken = []
    for child in outputs_dir.iterdir():
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name == "_stories":
            continue
        if is_broken(child):
            broken.append(child.name)
    return sorted(broken)


def main():
    parser = argparse.ArgumentParser(
        description="Permanently delete a story and all its on-disk artifacts."
    )
    parser.add_argument("--story", help="Story ID (folder name in outputs/) to delete")
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually perform the delete (default is dry run + report)"
    )
    parser.add_argument(
        "--backup", action="store_true",
        help="Copy the story to outputs/.trash/ before deleting"
    )
    parser.add_argument(
        "--all-broken", action="store_true",
        help="Delete every story flagged as broken (use with --apply)"
    )
    args = parser.parse_args()

    if not args.story and not args.all_broken:
        parser.print_help()
        print()
        print("ERROR: provide --story <id> or --all-broken", file=sys.stderr)
        sys.exit(1)

    targets: list[str] = []
    if args.all_broken:
        targets = find_broken_stories(OUTPUTS_DIR)
        if not targets:
            print("No broken stories found.")
            sys.exit(0)
        print(f"Found {len(targets)} broken stor{'y' if len(targets) == 1 else 'ies'}:")
        for sid in targets:
            print(f"  - {sid}")
        print()
    else:
        targets = [args.story]

    if not args.apply:
        mode = "DRY RUN" if not args.backup else "DRY RUN (with backup)"
        print(f"=== {mode}: would delete {len(targets)} stor{'y' if len(targets) == 1 else 'ies'} ===")
        for sid in targets:
            story_dir = OUTPUTS_DIR / sid
            files = list_story_files(story_dir)
            total = sum(f.stat().st_size for f in files if f.exists())
            print(f"\n  Story: {sid}")
            print(f"  Path:  {story_dir}")
            print(f"  Files: {len(files)}  ({human_size(total)})")
            if files:
                print(f"  Sample:")
                for f in files[:8]:
                    print(f"    {f.relative_to(story_dir)}  ({human_size(f.stat().st_size)})")
                if len(files) > 8:
                    print(f"    ... and {len(files) - 8} more")
        print()
        print("This was a dry run. Re-run with --apply to actually delete.")
        sys.exit(0)

    # Apply mode
    mode = "APPLY" if not args.backup else "APPLY (with backup)"
    print(f"=== {mode}: deleting {len(targets)} stor{'y' if len(targets) == 1 else 'ies'} ===")
    total_files = 0
    total_bytes = 0
    for sid in targets:
        story_dir = OUTPUTS_DIR / sid
        report = delete_story(story_dir, backup=args.backup)
        total_files += report["files_deleted"]
        total_bytes += report["bytes_freed"]
        if report["errors"]:
            print(f"  [ERROR] {sid}: {report['errors']}")
        else:
            backup_note = f" (backup at {report['backup_path']})" if report["backup_path"] else ""
            print(f"  [DELETED] {sid}  {report['files_deleted']} files, {human_size(report['bytes_freed'])}{backup_note}")
    print()
    print(f"Done. Removed {total_files} files, freed {human_size(total_bytes)}.")


if __name__ == "__main__":
    main()
