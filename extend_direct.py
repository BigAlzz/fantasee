#!/usr/bin/env python3
"""Extend 5 five-scene stories to 10, render video, export to Plex.
Calls story_actions.apply_extend directly (bypasses blocked server)."""
import json, subprocess, sys, time
from pathlib import Path

CWD = Path("C:/dev/fantasee")
sys.path.insert(0, str(CWD))

STORIES = [
    "steel-and-stratagem",
    "ley-lines-of-dark-code",
    "the-admiral-and-the-pirate",
    "divine-punishment-healer-s",
    "gunpowder-necromancy-cursed",
]

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

import story_actions

for sid in STORIES:
    log(f"=== {sid} ===")

    # Check scene count
    story_dir = CWD / "stories" / sid
    jf = story_dir / f"{sid}.json"
    if not jf.exists():
        log(f"  SKIP: no manifest")
        continue
    m = json.loads(jf.read_text(encoding="utf-8"))
    scenes = len(m.get("scenes", []))
    log(f"  Current: {scenes} scenes")

    # Extend to 10
    if scenes < 10:
        needed = 10 - scenes
        log(f"  Extending by {needed} scenes via story_actions.apply_extend...")
        try:
            result = story_actions.apply_extend(
                sid,
                scenes=needed,
                progress=lambda stage, msg, pct: log(f"  [{stage}] {msg} ({pct*100:.0f}%)"),
            )
            log(f"  Extended: +{result.get('new_scenes_added',0)} → {result.get('total_scenes',0)} total")
        except Exception as e:
            log(f"  Extend error: {e}")
            continue
    else:
        log(f"  Already has {scenes} scenes")

    # Render video
    log(f"  Rendering video...")
    try:
        proc = subprocess.run(
            [sys.executable, "render_video.py", sid],
            capture_output=True, text=True, timeout=600,
            cwd=str(CWD),
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().split("\n"):
                if "Done" in line:
                    log(f"  {line.strip()}")
                    break
        else:
            log(f"  Render FAILED: {(proc.stderr or '')[-200:]}")
            continue
    except Exception as e:
        log(f"  Render error: {e}")
        continue

    # Export to Plex
    log(f"  Exporting to Plex...")
    try:
        from plex_export import export_plex_package
        result = export_plex_package(sid, story_dir=story_dir)
        log(f"  Plex OK: {result.get('output_path', 'done')}")
    except Exception as e:
        log(f"  Plex error: {e}")

    log(f"  === {sid} COMPLETE ===")

log("\n=== ALL DONE ===")
plex_dest = Path(r"D:\Downloads\Plex\Movies")
if plex_dest.exists():
    folders = [d.name for d in plex_dest.iterdir() if d.is_dir()]
    log(f"Plex library ({len(folders)} items):")
    for f in sorted(folders):
        log(f"  {f}")
