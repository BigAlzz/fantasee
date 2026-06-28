#!/usr/bin/env python3
"""
Fantasee Batch Monitor — watches the generation queue, exports to Plex,
and self-terminates after a 30-minute master timeout.
"""
import json
import sys
import time
import requests

BASE = "http://127.0.0.1:8765"
QUEUE_ID = "q-23b3fd"
MASTER_TIMEOUT = 30 * 60  # 30 minutes
POLL_INTERVAL = 15  # seconds

start = time.time()
exported = set()

def elapsed():
    return time.time() - start

def remaining():
    return max(0, MASTER_TIMEOUT - elapsed())

def log(msg):
    m, s = divmod(int(elapsed()), 60)
    print(f"[{m:02d}:{s:02d}] {msg}", flush=True)

log(f"Monitor started. Queue: {QUEUE_ID}. Timeout: {MASTER_TIMEOUT}s")

while True:
    # Master timeout check
    if elapsed() >= MASTER_TIMEOUT:
        log(f"MASTER TIMEOUT reached ({MASTER_TIMEOUT}s). Stopping.")
        break

    try:
        r = requests.get(f"{BASE}/api/generate/tasks/{QUEUE_ID}", timeout=10)
        task = r.json()
    except Exception as e:
        log(f"Poll error: {e}")
        time.sleep(POLL_INTERVAL)
        continue

    status = task.get("status", "unknown")
    progress = task.get("progress", 0)
    message = task.get("message", "")

    log(f"Queue: {status} ({progress*100:.0f}%) — {message}")

    # Try to export any completed stories
    try:
        stories_r = requests.get(f"{BASE}/api/stories", timeout=10)
        stories = stories_r.json().get("stories", [])
        for s in stories:
            sid = s["id"]
            if sid not in exported and any(t in s.get("tags", []) for t in ["manhwa"]):
                # Check if story has enough scenes to export
                sc = s.get("scene_count", 0)
                if sc >= 10:
                    log(f"  Exporting to Plex: {s['title']} ({sc} scenes)")
                    try:
                        export_r = requests.post(
                            f"{BASE}/api/stories/{sid}/export-plex",
                            json={},
                            timeout=600,
                        )
                        if export_r.ok:
                            data = export_r.json()
                            log(f"  Plex export OK: {data.get('output_path', 'done')}")
                            exported.add(sid)
                        else:
                            log(f"  Plex export failed: {export_r.status_code} {export_r.text[:200]}")
                    except Exception as e:
                        log(f"  Plex export error: {e}")
    except Exception as e:
        log(f"Story list error: {e}")

    if status in ("done", "error"):
        log(f"Queue finished with status: {status}")
        # Give a moment for any last exports
        time.sleep(5)
        # Final export pass
        try:
            stories_r = requests.get(f"{BASE}/api/stories", timeout=10)
            stories = stories_r.json().get("stories", [])
            for s in stories:
                sid = s["id"]
                if sid not in exported and any(t in s.get("tags", []) for t in ["manhwa"]):
                    sc = s.get("scene_count", 0)
                    if sc >= 10:
                        log(f"  Final Plex export: {s['title']} ({sc} scenes)")
                        try:
                            export_r = requests.post(
                                f"{BASE}/api/stories/{sid}/export-plex",
                                json={},
                                timeout=600,
                            )
                            if export_r.ok:
                                data = export_r.json()
                                log(f"  Plex export OK: {data.get('output_path', 'done')}")
                                exported.add(sid)
                            else:
                                log(f"  Plex export failed: {export_r.status_code}")
                        except Exception as e:
                            log(f"  Plex export error: {e}")
        except Exception:
            pass
        break

    # Also check sub-tasks for individual story progress
    items = task.get("items", [])
    for idx, item in enumerate(items):
        sub_id = f"{QUEUE_ID}-{idx:02d}"
        try:
            sub_r = requests.get(f"{BASE}/api/generate/tasks/{sub_id}", timeout=5)
            sub = sub_r.json()
            sub_status = sub.get("status", "unknown")
            sub_msg = sub.get("message", "")
            if sub_status in ("running", "done", "error"):
                log(f"  Story {idx+1}: {sub_status} — {sub_msg[:80]}")
        except Exception:
            pass

    time.sleep(POLL_INTERVAL)

log(f"Monitor complete. Exported {len(exported)} stories to Plex.")
log("Remaining time: " + f"{remaining():.0f}s")
