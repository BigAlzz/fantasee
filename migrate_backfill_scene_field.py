#!/usr/bin/env python3
"""
One-shot migration: backfill the 'scene' field on scenes that are missing it.

Background: the old extend_story code didn't set the 'scene' key on continuation
scenes, so manifests produced before that fix have scenes whose only identifier
is their position in the list. Audio filenames, image prefixes, and the critic
all assume scenes are zero-padded numbered ("01", "02", ...) — when the field
is missing, audio/image lookups break.

Run with --dry-run to preview, --apply to write changes (atomic).

Usage:
    python migrate_backfill_scene_field.py            # dry run by default
    python migrate_backfill_scene_field.py --apply    # actually write
    python migrate_backfill_scene_field.py --story the-shrine-of-embers
"""

import argparse
import json
import sys
from pathlib import Path

OUTPUTS_DIR = Path(__file__).parent / "outputs"


def _atomic_write_json(path: Path, data) -> None:
    """Write JSON to disk atomically: write to .tmp, then os.replace."""
    import os
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def needs_backfill(manifest: dict) -> tuple[list[int], list[int]]:
    """Return (all_scene_indices, indices_missing_field) for a manifest."""
    scenes = manifest.get("scenes", [])
    all_idx = list(range(len(scenes)))
    missing = [i for i, sc in enumerate(scenes) if isinstance(sc, dict) and "scene" not in sc]
    return all_idx, missing


def backfill_story(story_id: str, dry_run: bool = True) -> dict:
    """Backfill missing 'scene' fields in a single story. Returns a report dict."""
    story_dir = OUTPUTS_DIR / story_id
    manifest_path = story_dir / f"{story_id}.json"

    report = {
        "story_id": story_id,
        "manifest_exists": manifest_path.exists(),
        "scenes_total": 0,
        "missing_count": 0,
        "fixed_count": 0,
        "would_fix": False,
        "applied": False,
        "samples": [],
        "errors": [],
    }

    if not manifest_path.exists():
        report["errors"].append(f"manifest not found: {manifest_path}")
        return report

    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as e:
        report["errors"].append(f"read error: {e}")
        return report

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as e:
        report["errors"].append(f"JSON parse error: {e}")
        return report

    if not isinstance(manifest, dict):
        report["errors"].append("manifest root is not a dict")
        return report

    scenes = manifest.get("scenes", [])
    if not isinstance(scenes, list):
        report["errors"].append("scenes field is not a list")
        return report

    report["scenes_total"] = len(scenes)
    _, missing = needs_backfill(manifest)
    report["missing_count"] = len(missing)

    if not missing:
        return report

    # Backfill: for each scene missing the field, assign the 1-indexed
    # zero-padded string based on its position in the list. The 0-indexed
    # existing scenes that already have 'scene' (e.g. "01".."10") still work
    # because the field is preserved.
    report["would_fix"] = True
    for i in missing:
        sc = scenes[i]
        if not isinstance(sc, dict):
            report["errors"].append(f"scene at index {i} is not a dict, skipping")
            continue
        old_key = sc.get("scene", "<missing>")
        new_value = f"{i + 1:02d}"
        # Don't overwrite an existing valid value (we already filtered, but be safe)
        if "scene" in sc:
            continue
        if len(report["samples"]) < 5:
            report["samples"].append({
                "index": i,
                "title": sc.get("title", "?"),
                "old": old_key,
                "new": new_value,
            })
        sc["scene"] = new_value
        report["fixed_count"] += 1

    if not dry_run and report["fixed_count"] > 0:
        try:
            _atomic_write_json(manifest_path, manifest)
            report["applied"] = True
        except OSError as e:
            report["errors"].append(f"write error: {e}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Backfill missing 'scene' fields in story manifests")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write changes (default is dry run)")
    parser.add_argument("--story", help="Only process this story ID (default: all)")
    args = parser.parse_args()

    if not OUTPUTS_DIR.exists():
        print(f"Outputs directory not found: {OUTPUTS_DIR}", file=sys.stderr)
        sys.exit(1)

    if args.story:
        story_ids = [args.story]
    else:
        story_ids = sorted([
            d.name for d in OUTPUTS_DIR.iterdir()
            if d.is_dir() and (d / f"{d.name}.json").exists()
        ])

    if not story_ids:
        print("No story manifests found.", file=sys.stderr)
        sys.exit(1)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== {mode}: backfilling missing 'scene' fields ===")
    print(f"  Outputs: {OUTPUTS_DIR}")
    print(f"  Stories to scan: {len(story_ids)}")
    print()

    total_fixed = 0
    stories_with_issues = 0
    errors = 0

    for sid in story_ids:
        report = backfill_story(sid, dry_run=not args.apply)
        if report["errors"]:
            errors += 1
            print(f"[ERROR] {sid}")
            for e in report["errors"]:
                print(f"   {e}")
            continue

        if not report["would_fix"]:
            print(f"[OK]    {sid}  --  {report['scenes_total']} scenes, all have 'scene' field")
            continue

        stories_with_issues += 1
        total_fixed += report["fixed_count"]
        action = "APPLIED" if report["applied"] else "would fix"
        print(f"[FIX]   {sid}  --  {report['scenes_total']} scenes, "
              f"{report['missing_count']} missing ({action})")
        for s in report["samples"]:
            print(f"   scene[{s['index']}] '{s['title'][:40]}': '{s['old']}' -> '{s['new']}'")
        if report["missing_count"] > len(report["samples"]):
            print(f"   ... and {report['missing_count'] - len(report['samples'])} more")

    print()
    print("=" * 60)
    print(f"Stories scanned:      {len(story_ids)}")
    print(f"Stories needing fix:  {stories_with_issues}")
    print(f"Total scenes fixed:   {total_fixed}")
    if errors:
        print(f"Stories with errors:  {errors}")

    if not args.apply:
        if total_fixed > 0:
            print()
            print("This was a dry run. Re-run with --apply to write changes.")
            sys.exit(0)
        else:
            print("All stories are clean — no fix needed.")
            sys.exit(0)

    if errors:
        print("Some stories had errors — review above.", file=sys.stderr)
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
