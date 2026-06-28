#!/usr/bin/env python3
"""Extend 5 five-scene stories to 10, render video, export to Plex."""
import json, subprocess, sys, time, requests
from pathlib import Path

BASE = "http://127.0.0.1:8765"
CWD = Path("C:/dev/fantasee")

STORIES = [
    "steel-and-stratagem",
    "ley-lines-of-dark-code",
    "the-admiral-and-the-pirate",
    "divine-punishment-healer-s",
    "gunpowder-necromancy-cursed",
]

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

for sid in STORIES:
    log(f"=== {sid} ===")

    # Check scene count
    jf = CWD / "stories" / sid / f"{sid}.json"
    if not jf.exists():
        log(f"  SKIP: no manifest")
        continue
    m = json.loads(jf.read_text(encoding="utf-8"))
    scenes = len(m.get("scenes", []))
    log(f"  Current: {scenes} scenes")

    # Extend to 10
    if scenes < 10:
        needed = 10 - scenes
        log(f"  Extending by {needed} scenes...")
        try:
            r = requests.post(f"{BASE}/api/stories/{sid}/extend",
                              json={"scenes": needed, "images_per_scene": 2}, timeout=600)
            if r.ok:
                data = r.json()
                log(f"  Extended: +{data.get('new_scenes_added',0)} → {data.get('total_scenes',0)} total")
            else:
                log(f"  Extend FAILED: {r.status_code} {r.text[:200]}")
                continue
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
            # Extract last line with "Done!"
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
        r = requests.post(f"{BASE}/api/stories/{sid}/export-plex", json={}, timeout=600)
        if r.ok:
            tid = r.json().get("task_id", "")
            for _ in range(120):
                time.sleep(5)
                t = requests.get(f"{BASE}/api/generate/tasks/{tid}", timeout=10).json()
                if t.get("status") == "done":
                    log(f"  Plex OK!")
                    break
                elif t.get("status") == "error":
                    log(f"  Plex FAILED: {t.get('message','')[:200]}")
                    break
        else:
            log(f"  Plex request failed: {r.status_code}")
    except Exception as e:
        log(f"  Plex error: {e}")

    log(f"  === {sid} COMPLETE ===")

log("\n=== ALL DONE ===")
# Summary
plex_dest = Path(r"D:\Downloads\Plex\Movies")
if plex_dest.exists():
    folders = [d.name for d in plex_dest.iterdir() if d.is_dir()]
    log(f"Plex library ({len(folders)} items):")
    for f in sorted(folders):
        log(f"  {f}")
