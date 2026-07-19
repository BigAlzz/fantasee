#!/usr/bin/env python3
"""Nightly steward for FantaSee Studio.
Uses the studio API to regenerate all stories that need work.
Non-destructive. Monitors progress. Generates SVG placeholders.
"""

import json, time, requests
from collections import Counter
from pathlib import Path

BASE = "http://127.0.0.1:8765"
STORIES_DIR = Path("C:/dev/fantasee/stories")

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def api(method, path, data=None):
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            r = requests.get(url, timeout=15)
        else:
            r = requests.post(url, json=data or {}, timeout=15)
        return r.json() if r.status_code == 200 else {"error": r.text[:200]}
    except Exception as e:
        return {"error": str(e)[:200]}

def get_stories():
    d = api("GET", "/api/stories")
    return d.get("stories", []) if isinstance(d, dict) else []

def get_tasks():
    d = api("GET", "/api/generate/tasks")
    return d if isinstance(d, list) else (d or {}).get("tasks", [])

def count_tasks(tasks):
    return Counter(t.get("status") for t in tasks)

def needs_work(story):
    """Check if a story needs generation/finishing."""
    status = story.get("status", "")
    scenes = story.get("scene_count", 0)
    if status in ("needs_story", "") and scenes == 0:
        return True
    if status == "needs_finishing":
        return True
    return False

def regenerate_story(story_id):
    """Trigger regeneration through the studio API."""
    result = api("POST", f"/api/stories/{story_id}/regenerate", {"backup": True})
    if "task_id" in result:
        log(f"   ✅ {story_id} → task {result['task_id']}")
        return result["task_id"]
    else:
        log(f"   ❌ {story_id} failed: {result.get('error', result.get('message', '?'))}")
        return None

def generate_placeholders():
    """Generate SVG placeholders for stories with scenes but no images."""
    try:
        spec = __import__("importlib").util.spec_from_file_location(
            "stock_images", "C:/dev/fantasee/stock_images.py")
        mod = __import__("importlib").util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        total = 0
        for d in STORIES_DIR.iterdir():
            if not d.is_dir() or d.name == ".trash":
                continue
            manifests = list(d.glob(d.name + ".json"))
            if not manifests:
                continue
            with open(manifests[0]) as f:
                data = json.load(f)
            scenes = data.get("scenes", [])
            if not scenes:
                continue
            has_images = any(len(s.get("image_filenames", [])) > 0 for s in scenes)
            if not has_images:
                n = mod.fill_story_images(d)
                if n > 0:
                    log(f"   🎨 {d.name}: {n} placeholders")
                    total += n
        return total
    except Exception as e:
        log(f"   ⚠️ Placeholder error: {e}")
        return 0

def main():
    log("🌙 Nightly Steward starting")
    log(f"   Server: {api('GET', '/api/settings') is not None}")

    # Phase 1: Identify stories that need work
    stories = get_stories()
    needs_gen = [s for s in stories if needs_work(s)]
    log(f"   {len(stories)} total stories, {len(needs_gen)} need generation")

    # Phase 2: Regenerate stories (one at a time to avoid overloading)
    active_regen = []
    for s in needs_gen:
        task_id = regenerate_story(s["id"])
        if task_id:
            active_regen.append(task_id)
            time.sleep(2)  # small delay between requests

    if not active_regen:
        log("   No stories need regeneration")
    else:
        log(f"   Queued {len(active_regen)} regenerations")

    # Phase 3: Monitor progress
    round_num = 0
    max_rounds = 360  # ~6 hours at 1-min intervals
    while round_num < max_rounds:
        round_num += 1
        tasks = get_tasks()
        c = count_tasks(tasks)
        running = c.get("running", 0)
        queued = c.get("queued", 0)
        done = c.get("done", 0)
        errored = c.get("error", 0)

        log(f"Round {round_num} — run:{running} que:{queued} done:{done} err:{errored}")

        # Generate placeholders for any new stories
        if round_num % 5 == 0:
            generate_placeholders()

        # Check if everything is done
        if running == 0 and queued == 0:
            log(f"✅ All tasks settled. Done:{done} Error:{errored}")

            if errored > 0:
                log("   Some tasks errored — checking if retryable...")
                stories = get_stories()
                needs_gen = [s for s in stories if needs_work(s)]
                if needs_gen:
                    log(f"   {len(needs_gen)} stories still need work — re-queuing in 5min...")
                    time.sleep(300)
                    for s in needs_gen:
                        task_id = regenerate_story(s["id"])
                        if task_id:
                            active_regen.append(task_id)
                            time.sleep(2)
                    continue

            log("   All stories complete! 🎉")
            break

        time.sleep(60)

    log("🌙 Steward finished")

if __name__ == "__main__":
    main()
