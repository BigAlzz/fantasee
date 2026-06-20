#!/usr/bin/env python3
"""Copy legacy generated stories from outputs/ into stories/.

This is intentionally non-destructive: existing outputs/ folders are left as
backups, and existing stories/<id>/ folders are skipped unless --force is used.
"""

import argparse
import shutil

from story_storage import LEGACY_OUTPUTS_ROOT, STORIES_ROOT, ensure_story_layout


def migrate(force: bool = False) -> list[dict]:
    STORIES_ROOT.mkdir(parents=True, exist_ok=True)
    reports = []
    if not LEGACY_OUTPUTS_ROOT.exists():
        return reports

    for child in sorted(LEGACY_OUTPUTS_ROOT.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name.startswith("_"):
            continue
        manifest = child / f"{child.name}.json"
        if not manifest.exists():
            continue

        dest = STORIES_ROOT / child.name
        if dest.exists():
            if not force:
                ensure_story_layout(dest)
                reports.append({"story_id": child.name, "status": "skipped", "path": str(dest)})
                continue
            shutil.rmtree(dest)

        shutil.copytree(child, dest)
        ensure_story_layout(dest)
        reports.append({"story_id": child.name, "status": "copied", "path": str(dest)})
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy outputs/<story> into stories/<story>.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing stories/<id> folders.")
    args = parser.parse_args()
    reports = migrate(force=args.force)
    if not reports:
        print("No legacy stories found to migrate.")
        return
    for report in reports:
        print(f"{report['status']:7} {report['story_id']} -> {report['path']}")


if __name__ == "__main__":
    main()
