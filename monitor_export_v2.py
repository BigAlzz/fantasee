#!/usr/bin/env python3
"""
Fantasee Render+Export Monitor v2 — watches for completed stories,
renders video and exports to Plex. Handles slug truncation.
30-minute master timeout.
"""
import json
import subprocess
import sys
import time
import requests
from pathlib import Path

BASE = "http://127.0.0.1:8765"
QUEUE_ID = "q-23b3fd"
CWD = Path("C:/dev/fantasee")
STORIES_DIR = CWD / "stories"
MASTER_TIMEOUT = 30 * 60
POLL_INTERVAL = 30
TOTAL_STORIES = 8

start = time.time()
done_set = set()  # stories already exported

def elapsed():
    return time.time() - start

def log(msg):
    m, s = divmod(int(elapsed()), 60)
    print(f"[{m:02d}:{s:02d}] {msg}", flush=True)

def find_story_dir(story_id):
    """Find the actual story dir, handling slug truncation."""
    candidate = STORIES_DIR / story_id
    if candidate.exists():
        return candidate
    # Try partial matches
    for d in STORIES_DIR.iterdir():
        if d.is_dir() and d.name.startswith(story_id[:15]):
            return d
    return None

log(f"Monitor v2 started. Queue: {QUEUE_ID}. Timeout: {MASTER_TIMEOUT}s")

while True:
    if elapsed() >= MASTER_TIMEOUT:
        log(f"MASTER TIMEOUT ({MASTER_TIMEOUT}s). Stopping.")
        break

    # Check queue
    try:
        qr = requests.get(f"{BASE}/api/generate/tasks/{QUEUE_ID}", timeout=10)
        qtask = qr.json()
        qstatus = qtask.get("status", "unknown")
        log(f"Queue: {qstatus} ({qtask.get('progress',0)*100:.0f}%) — {qtask.get('message','')}")
    except Exception as e:
        log(f"Queue poll error: {e}")
        time.sleep(POLL_INTERVAL)
        continue

    # Check sub-tasks for completed stories
    for idx in range(TOTAL_STORIES):
        sub_id = f"{QUEUE_ID}-{idx:02d}"
        try:
            sr = requests.get(f"{BASE}/api/generate/tasks/{sub_id}", timeout=5)
            sub = sr.json()
        except Exception:
            continue

        if sub.get("status") != "done":
            continue

        msg = sub.get("message", "")
        if "Complete:" not in msg:
            continue
        story_id = msg.split("Complete:", 1)[1].strip()

        if story_id in done_set:
            continue

        # Find actual story dir
        story_dir = find_story_dir(story_id)
        if not story_dir:
            log(f"  WARNING: No story dir for {story_id}")
            continue

        actual_id = story_dir.name
        log(f"  Processing: {actual_id} ({sub.get('message','')})")

        # Step 1: Check if video already rendered
        full_mp4 = story_dir / f"{actual_id}_full.mp4"
        if not full_mp4.exists():
            log(f"  Rendering video for {actual_id}...")
            try:
                proc = subprocess.run(
                    [sys.executable, "render_video.py", actual_id],
                    capture_output=True, text=True, timeout=600,
                    cwd=str(CWD),
                )
                if proc.returncode == 0:
                    log(f"  Render OK: {actual_id}")
                else:
                    log(f"  Render FAILED: {(proc.stderr or '')[-200:]}")
                    continue
            except Exception as e:
                log(f"  Render error: {e}")
                continue
        else:
            log(f"  Video already exists for {actual_id}")

        # Step 2: Export to Plex
        log(f"  Exporting {actual_id} to Plex...")
        try:
            er = requests.post(
                f"{BASE}/api/stories/{actual_id}/export-plex",
                json={}, timeout=600,
            )
            if er.ok:
                export_tid = er.json().get("task_id", "")
                for _ in range(120):
                    time.sleep(5)
                    try:
                        et = requests.get(f"{BASE}/api/generate/tasks/{export_tid}", timeout=5).json()
                        if et.get("status") == "done":
                            log(f"  Plex OK: {actual_id}")
                            done_set.add(story_id)
                            break
                        elif et.get("status") == "error":
                            log(f"  Plex FAILED: {et.get('message','')[:200]}")
                            done_set.add(story_id)  # Don't retry
                            break
                    except Exception:
                        pass
            else:
                log(f"  Plex request failed: {er.status_code} {er.text[:200]}")
        except Exception as e:
            log(f"  Plex error: {e}")

    if qstatus in ("done", "error"):
        log("Queue finished!")
        break

    time.sleep(POLL_INTERVAL)

log(f"\n=== DONE === Exported: {len(done_set)} stories")
