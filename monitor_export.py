#!/usr/bin/env python3
"""
Fantasee Post-Generation Monitor — watches the queue for completed stories,
renders video + exports to Plex for each. 30-minute master timeout.
"""
import json
import subprocess
import sys
import time
import requests

BASE = "http://127.0.0.1:8765"
QUEUE_ID = "q-23b3fd"
MASTER_TIMEOUT = 30 * 60
POLL_INTERVAL = 30
TOTAL_STORIES = 8

start = time.time()
exported = set()
rendered = set()

def elapsed():
    return time.time() - start

def log(msg):
    m, s = divmod(int(elapsed()), 60)
    print(f"[{m:02d}:{s:02d}] {msg}", flush=True)

log(f"Monitor started. Queue: {QUEUE_ID}. Timeout: {MASTER_TIMEOUT}s")

while True:
    if elapsed() >= MASTER_TIMEOUT:
        log(f"MASTER TIMEOUT ({MASTER_TIMEOUT}s). Stopping.")
        break

    # Check queue status
    try:
        qr = requests.get(f"{BASE}/api/generate/tasks/{QUEUE_ID}", timeout=10)
        qtask = qr.json()
        qstatus = qtask.get("status", "unknown")
        qprogress = qtask.get("progress", 0)
        qmsg = qtask.get("message", "")
        log(f"Queue: {qstatus} ({qprogress*100:.0f}%) — {qmsg}")
    except Exception as e:
        log(f"Queue poll error: {e}")
        time.sleep(POLL_INTERVAL)
        continue

    # Check each sub-task
    for idx in range(TOTAL_STORIES):
        sub_id = f"{QUEUE_ID}-{idx:02d}"
        try:
            sr = requests.get(f"{BASE}/api/generate/tasks/{sub_id}", timeout=5)
            sub = sr.json()
        except Exception:
            continue

        sub_status = sub.get("status", "missing")
        sub_msg = sub.get("message", "")
        story_id = None

        # Extract story_id from the message if available
        if "Complete:" in sub_msg:
            story_id = sub_msg.split("Complete:", 1)[1].strip()

        if sub_status == "done" and story_id and story_id not in rendered and story_id not in exported:
            log(f"  Story {idx+1} done: {story_id}")

            # Step 1: Render video
            log(f"  Rendering video for {story_id}...")
            try:
                proc = subprocess.run(
                    [sys.executable, "render_video.py", story_id],
                    capture_output=True, text=True, timeout=600,
                    cwd="C:/dev/fantasee",
                )
                if proc.returncode == 0:
                    log(f"  Render OK for {story_id}")
                    rendered.add(story_id)
                else:
                    log(f"  Render FAILED for {story_id}: {proc.stderr[-200:]}")
                    continue
            except Exception as e:
                log(f"  Render error: {e}")
                continue

            # Step 2: Export to Plex
            log(f"  Exporting {story_id} to Plex...")
            try:
                er = requests.post(
                    f"{BASE}/api/stories/{story_id}/export-plex",
                    json={},
                    timeout=600,
                )
                if er.ok:
                    export_task = er.json()
                    export_tid = export_task.get("task_id", "")
                    # Poll export
                    for _ in range(120):
                        time.sleep(5)
                        try:
                            et = requests.get(f"{BASE}/api/generate/tasks/{export_tid}", timeout=5).json()
                            if et.get("status") == "done":
                                log(f"  Plex export OK: {story_id}")
                                exported.add(story_id)
                                break
                            elif et.get("status") == "error":
                                log(f"  Plex export FAILED: {et.get('message','')}")
                                break
                        except Exception:
                            pass
                else:
                    log(f"  Plex export request failed: {er.status_code}")
            except Exception as e:
                log(f"  Plex export error: {e}")

    # If queue is done, do one final pass
    if qstatus in ("done", "error"):
        log("Queue finished. Final export pass...")
        # Check all stories for any we missed
        try:
            sr = requests.get(f"{BASE}/api/stories", timeout=10)
            for s in sr.json().get("stories", []):
                sid = s["id"]
                if "manhwa" in s.get("tags", []) and s.get("scene_count", 0) >= 10:
                    if sid not in exported:
                        # Render if needed
                        if sid not in rendered:
                            log(f"  Final render: {sid}")
                            try:
                                proc = subprocess.run(
                                    [sys.executable, "render_video.py", sid],
                                    capture_output=True, text=True, timeout=600,
                                    cwd="C:/dev/fantasee",
                                )
                                if proc.returncode == 0:
                                    rendered.add(sid)
                                else:
                                    log(f"  Render FAILED: {proc.stderr[-200:]}")
                                    continue
                            except Exception as e:
                                log(f"  Render error: {e}")
                                continue

                        log(f"  Final export: {sid}")
                        try:
                            er = requests.post(f"{BASE}/api/stories/{sid}/export-plex", json={}, timeout=600)
                            if er.ok:
                                export_tid = er.json().get("task_id", "")
                                for _ in range(120):
                                    time.sleep(5)
                                    et = requests.get(f"{BASE}/api/generate/tasks/{export_tid}", timeout=5).json()
                                    if et.get("status") in ("done", "error"):
                                        if et["status"] == "done":
                                            exported.add(sid)
                                            log(f"  Plex OK: {sid}")
                                        else:
                                            log(f"  Plex FAIL: {et.get('message','')}")
                                        break
                        except Exception as e:
                            log(f"  Export error: {e}")
        except Exception as e:
            log(f"Final pass error: {e}")
        break

    time.sleep(POLL_INTERVAL)

log(f"\n=== COMPLETE ===")
log(f"Exported to Plex: {len(exported)} stories")
log(f"Rendered: {len(rendered)} stories")
log(f"Elapsed: {int(elapsed())}s")
