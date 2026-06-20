#!/usr/bin/env python3
"""
Regenerate TTS audio for a range of scenes in a story, using the current
tts_utils defaults (which now use the 'normal' calm style).

Run with --dry-run to preview, --apply to actually write.

Usage:
    python regen_tts.py --story the-shrine-of-embers --from 11 --to 20
    python regen_tts.py --story the-shrine-of-embers --from 11 --to 20 --apply
    python regen_tts.py --story the-shrine-of-embers --from 11 --to 20 --apply --voice Dean --style normal
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from story_storage import STORIES_ROOT, existing_story_dir

OUTPUTS_DIR = STORIES_ROOT


def _atomic_write_json(path: Path, data) -> None:
    """Write JSON to disk atomically: write to .tmp, then os.replace."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def regen_tts_for_scenes(
    story_id: str,
    scene_nums: list[int],
    voice: str = "Dean",
    style: str = "normal",
    dry_run: bool = True,
) -> dict:
    """Regenerate TTS for the given scene numbers in a story.

    scene_nums are 1-indexed (e.g. [11, 12, ..., 20] for scenes 11-20).
    """
    sys.path.insert(0, str(Path(__file__).parent))
    from tts_utils import generate_tts, get_audio_duration

    story_dir = existing_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    report = {
        "story_id": story_id,
        "voice": voice,
        "style": style,
        "dry_run": dry_run,
        "scenes_attempted": [],
        "scenes_succeeded": [],
        "scenes_failed": [],
        "duration_changes": [],
    }

    if not manifest_path.exists():
        report["scenes_failed"].append({"scene": None, "error": f"manifest not found: {manifest_path}"})
        return report

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report["scenes_failed"].append({"scene": None, "error": f"JSON parse error: {e}"})
        return report

    scenes = manifest.get("scenes", [])
    if not isinstance(scenes, list):
        report["scenes_failed"].append({"scene": None, "error": "'scenes' is not a list"})
        return report

    for scene_num in scene_nums:
        idx = scene_num - 1
        if idx < 0 or idx >= len(scenes):
            report["scenes_failed"].append({"scene": scene_num, "error": f"out of range (manifest has {len(scenes)} scenes)"})
            continue
        sc = scenes[idx]
        narration = sc.get("narration", "") or sc.get("narration_text", "")
        if not narration or len(narration.strip()) < 10:
            report["scenes_failed"].append({"scene": scene_num, "error": "no narration text"})
            continue

        # Build audio filename (zero-padded, matches existing pattern)
        padded = f"{scene_num:02d}"
        audio_filename = f"tts_{story_id}_s{padded}.wav"
        audio_path = story_dir / audio_filename

        old_duration = sc.get("audio_duration", 0)
        old_words = len(narration.split())
        old_wpm = (old_words / old_duration * 60) if old_duration else 0

        report["scenes_attempted"].append({
            "scene": scene_num,
            "title": sc.get("title", "?"),
            "words": old_words,
            "old_duration": round(old_duration, 1),
            "old_wpm": round(old_wpm, 0),
            "audio_file": audio_filename,
        })

        if dry_run:
            report["scenes_succeeded"].append(scene_num)
            continue

        # Actually generate
        print(f"  Scene {scene_num:02d} ({sc.get('title', '?')[:30]:30}) "
              f"words={old_words:3} old={old_duration:5.1f}s/{old_wpm:3.0f}wpm ... ", end="", flush=True)
        try:
            ok = generate_tts(narration, str(audio_path), voice=voice, style=style)
        except Exception as e:
            print(f"FAIL: {e}")
            report["scenes_failed"].append({"scene": scene_num, "error": str(e)})
            continue

        if not ok:
            print("FAIL: generate_tts returned False")
            report["scenes_failed"].append({"scene": scene_num, "error": "generate_tts returned False"})
            continue

        # Update manifest with new duration
        new_duration = get_audio_duration(str(audio_path))
        new_wpm = (old_words / new_duration * 60) if new_duration else 0
        sc["audio_filename"] = audio_filename
        sc["audio_duration"] = new_duration
        print(f"new={new_duration:5.1f}s/{new_wpm:3.0f}wpm OK")
        report["scenes_succeeded"].append(scene_num)
        report["duration_changes"].append({
            "scene": scene_num,
            "old_seconds": round(old_duration, 1),
            "new_seconds": round(new_duration, 1),
            "old_wpm": round(old_wpm, 0),
            "new_wpm": round(new_wpm, 0),
        })

    if not dry_run and report["scenes_succeeded"]:
        _atomic_write_json(manifest_path, manifest)

    return report


def main():
    parser = argparse.ArgumentParser(description="Regenerate TTS audio for a story's scenes")
    parser.add_argument("--story", required=True, help="Story ID (folder name in stories/)")
    parser.add_argument("--from", dest="from_scene", type=int, required=True,
                        help="First scene number (1-indexed, inclusive)")
    parser.add_argument("--to", dest="to_scene", type=int, required=True,
                        help="Last scene number (1-indexed, inclusive)")
    parser.add_argument("--voice", default="Dean", help="Voice name (default: Dean)")
    parser.add_argument("--style", default="normal",
                        help="Style key from STYLE_MAP (default: normal)")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write changes (default is dry run)")
    args = parser.parse_args()

    if args.from_scene > args.to_scene:
        print("ERROR: --from must be <= --to", file=sys.stderr)
        sys.exit(1)

    scene_nums = list(range(args.from_scene, args.to_scene + 1))
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== {mode}: regenerating TTS for {args.story} ===")
    print(f"  Scenes: {args.from_scene}..{args.to_scene} ({len(scene_nums)} scenes)")
    print(f"  Voice: {args.voice}")
    print(f"  Style: {args.style}")
    print()

    report = regen_tts_for_scenes(
        args.story, scene_nums,
        voice=args.voice, style=args.style,
        dry_run=not args.apply,
    )

    # Summary
    print()
    print("=" * 70)
    if args.apply:
        print(f"Succeeded: {len(report['scenes_succeeded'])}/{len(scene_nums)}")
        print(f"Failed:    {len(report['scenes_failed'])}")
        if report["scenes_failed"]:
            print()
            print("Failures:")
            for f in report["scenes_failed"]:
                print(f"  Scene {f.get('scene', '?')}: {f.get('error', '?')}")
        if report["duration_changes"]:
            print()
            print("Duration changes:")
            for d in report["duration_changes"]:
                delta = d["new_seconds"] - d["old_seconds"]
                print(f"  Scene {d['scene']:2}: "
                      f"{d['old_seconds']:5.1f}s/{d['old_wpm']:3.0f}wpm -> "
                      f"{d['new_seconds']:5.1f}s/{d['new_wpm']:3.0f}wpm "
                      f"({delta:+.1f}s)")
    else:
        print(f"Would regenerate {len(report['scenes_attempted'])} scenes")
        print()
        print("Scene details:")
        for s in report["scenes_attempted"]:
            print(f"  Scene {s['scene']:2} ({s['title'][:35]:35}) "
                  f"words={s['words']:3} current={s['old_duration']:5.1f}s @ {s['old_wpm']:3.0f}wpm")
        print()
        print("This was a dry run. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
