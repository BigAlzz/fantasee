#!/usr/bin/env python3
"""Generate subtitles for all manhwa stories missing subtitle_segments/subtitle_file.
Uses faster_whisper (which is installed) instead of openai-whisper (which isn't)."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from generate_subtitles import generate_subtitles
from story_storage import STORIES_ROOT

def update_manifest(manifest_path, scenes):
    """Atomic JSON write."""
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest_path.read_json(), indent=2), encoding="utf-8")
    # Actually need to update in-memory then write
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    m["scenes"] = scenes
    tmp.write_text(json.dumps(m, indent=2), encoding="utf-8")
    import os
    os.replace(str(tmp), str(manifest_path))

total_generated = 0
total_failed = 0

for d in sorted(STORIES_ROOT.iterdir()):
    if not d.is_dir(): continue
    jf = d / f"{d.name}.json"
    if not jf.exists(): continue
    try:
        m = json.loads(jf.read_text(encoding="utf-8"))
    except: continue
    tags = m.get("tags", [])
    if "manhwa" not in tags: continue
    scenes = m.get("scenes", [])
    if len(scenes) < 5: continue

    print(f"\n=== {d.name} ({len(scenes)} scenes) ===", flush=True)
    changed = False

    for s in scenes:
        # Skip if already has subtitles
        if s.get("subtitle_segments") or s.get("subtitle_file"):
            continue

        af = s.get("audio_filename", "")
        if not af:
            print(f"  Scene {s.get('scene','?')}: no audio, skipping", flush=True)
            continue
        audio_path = d / af
        if not audio_path.exists():
            print(f"  Scene {s.get('scene','?')}: audio file missing, skipping", flush=True)
            continue

        narration = s.get("narration", s.get("narration_text", ""))
        if not narration:
            print(f"  Scene {s.get('scene','?')}: no narration text, skipping", flush=True)
            continue

        try:
            segments = generate_subtitles(str(audio_path), narration)
            if segments:
                # Save subtitle file
                sub_filename = f"subs_{d.name}_s{s['scene']}.json"
                sub_path = d / sub_filename
                sub_path.write_text(json.dumps(segments, indent=2), encoding="utf-8")
                s["subtitle_file"] = sub_filename
                s["subtitle_segments"] = segments
                changed = True
                total_generated += 1
                print(f"  Scene {s.get('scene','?')}: {len(segments)} subtitle segments", flush=True)
            else:
                total_failed += 1
                print(f"  Scene {s.get('scene','?')}: empty result", flush=True)
        except Exception as e:
            total_failed += 1
            print(f"  Scene {s.get('scene','?')}: FAILED — {e}", flush=True)

    if changed:
        # Save manifest
        manifest_path = d / f"{d.name}.json"
        m["scenes"] = scenes
        tmp = manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(m, indent=2), encoding="utf-8")
        import os
        os.replace(str(tmp), str(manifest_path))
        print(f"  Manifest saved.", flush=True)

print(f"\n=== DONE === Generated: {total_generated}, Failed: {total_failed}", flush=True)
