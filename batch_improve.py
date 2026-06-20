#!/usr/bin/env python3
"""
Batch pipeline: Extend all Fantasee stories to 20 scenes, then run improve-loop
to hit 4.5+ critic rating. Runs sequentially since ComfyUI is single-threaded.
"""

import json
import os
import subprocess
import sys
import time
import requests
from pathlib import Path
from datetime import datetime

# Force UTF-8 on stdout/stderr so non-ASCII (em-dashes, arrows) don't get mangled
# when the script is run from PowerShell on Windows (default cp1252).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

BASE_URL = "http://127.0.0.1:8765"
OUTPUTS_DIR = Path(r"C:\dev\fantasee\outputs")
LOG_FILE = OUTPUTS_DIR.parent / "batch_improve.log"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def get_story_ids():
    """Get all valid story IDs (must have a manifest JSON)."""
    stories = []
    for d in sorted(OUTPUTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        manifest_path = d / f"{d.name}.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)
            scenes = manifest.get("scenes", [])
            stories.append({
                "id": d.name,
                "title": manifest.get("title", "Unknown").replace("\r\n", " / ").replace("\n", " / ")[:60],
                "scene_count": len(scenes),
                "critic_rating": manifest.get("critic_rating"),
                "critic_stars": manifest.get("critic_stars"),
            })
    return stories

def extend_story(story_id, scenes_needed, images_per_scene=3):
    """Extend a story to ~20 scenes via the API."""
    # target_minutes: each scene ~2 min of audio
    target_minutes = scenes_needed * 2
    log(f"  EXTENDING {story_id}: requesting {scenes_needed} new scenes (target_minutes={target_minutes})")
    
    try:
        resp = requests.post(
            f"{BASE_URL}/api/stories/{story_id}/extend",
            json={
                "target_minutes": target_minutes,
                "images_per_scene": images_per_scene,
                "voice": "Dean",
                "tone": "dramatic",
            },
            timeout=3600,  # 1 hour max per extension
        )
        if resp.ok:
            data = resp.json()
            log(f"  EXTEND result: {json.dumps(data)[:200]}")
            return data
        else:
            log(f"  EXTEND FAILED: {resp.status_code} {resp.text[:200]}")
            return None
    except Exception as e:
        log(f"  EXTEND ERROR: {e}")
        return None

def run_improve_loop(story_id, target_stars=4.5, max_rounds=3, images_per_scene=3):
    """Run the iterative improve-loop until target critic rating is hit."""
    log(f"  IMPROVE-LOOP {story_id}: target={target_stars} stars, max_rounds={max_rounds}")
    
    try:
        resp = requests.post(
            f"{BASE_URL}/api/stories/{story_id}/improve-loop",
            json={
                "target_stars": target_stars,
                "max_rounds": max_rounds,
                "max_scenes_per_round": 3,
                "images_per_scene": images_per_scene,
                "voice": "Dean",
            },
            timeout=7200,  # 2 hours max per improvement loop
        )
        if resp.ok:
            data = resp.json()
            log(f"  IMPROVE result: {json.dumps(data)[:300]}")
            return data
        else:
            log(f"  IMPROVE FAILED: {resp.status_code} {resp.text[:300]}")
            return None
    except Exception as e:
        log(f"  IMPROVE ERROR: {e}")
        return None

def run_critic(story_id):
    """Run critic directly and return the rating."""
    log(f"  Running critic on {story_id}...")
    env = {**os.environ}
    for key in ["XIAOMI_API_KEY", "XIAOMI_BASE_URL"]:
        val = os.environ.get(key, "")
        if val:
            env[key] = val
    
    try:
        proc = subprocess.run(
            [sys.executable, str(OUTPUTS_DIR.parent / "critic.py"), story_id, "--json"],
            capture_output=True, text=True, timeout=180,
            cwd=str(OUTPUTS_DIR.parent), env=env,
        )
        if proc.returncode == 0:
            stdout = proc.stdout.strip()
            json_end = stdout.rfind("}")
            if json_end >= 0:
                stdout = stdout[:json_end + 1]
            review = json.loads(stdout)
            stars = review.get("review", {}).get("stars", 0)
            rating = review.get("review", {}).get("overall_score", 0)
            log(f"  Critic result: {rating}/10 ({stars} stars)")
            return rating, stars
        else:
            log(f"  Critic failed: {proc.stderr[:200]}")
            return None, None
    except Exception as e:
        log(f"  Critic error: {e}")
        return None, None

def main():
    log("=" * 70)
    log("BATCH IMPROVE PIPELINE STARTED")
    log("=" * 70)
    
    stories = get_story_ids()
    log(f"Found {len(stories)} stories to process")
    
    results = []
    
    for story in stories:
        sid = story["id"]
        scene_count = story["scene_count"]
        current_stars = story.get("critic_stars")
        current_rating = story.get("critic_rating")
        
        log(f"\n{'='*60}")
        log(f"Processing: {story['title']}")
        log(f"  ID: {sid}")
        log(f"  Current: {scene_count} scenes, critic: {current_rating} ({current_stars} stars)")
        
        result = {"id": sid, "title": story["title"], "start_scenes": scene_count}
        
        # Step 1: Extend to 20 scenes if needed
        if scene_count < 20:
            scenes_needed = 20 - scene_count
            ext = extend_story(sid, scenes_needed, images_per_scene=3)
            if ext and ext.get("status") == "ok":
                new_total = ext.get("total_scenes", scene_count)
                result["extended_to"] = new_total
                log(f"  Extended to {new_total} scenes")
            elif ext and ext.get("status") == "already_at_target":
                result["extended_to"] = scene_count
                log(f"  Already at target")
            else:
                result["extended_to"] = scene_count
                result["extend_error"] = str(ext)[:200] if ext else "No response"
                log(f"  Extension may have failed, continuing with current scene count")
        else:
            result["extended_to"] = scene_count
            log(f"  Already at 20+ scenes, skipping extension")
        
        # Step 2: Run critic first to check current score
        rating, stars = run_critic(sid)
        result["pre_improve_rating"] = rating
        result["pre_improve_stars"] = stars
        
        # Step 3: Run improve-loop if below 4.5
        if stars is not None and stars >= 4.5:
            log(f"  Already at {stars} stars ({rating}/10), skipping improvement")
            result["final_stars"] = stars
            result["final_rating"] = rating
            result["improve_status"] = "already_at_target"
        else:
            imp = run_improve_loop(sid, target_stars=4.5, max_rounds=3, images_per_scene=3)
            if imp:
                result["final_stars"] = imp.get("final_stars")
                result["final_rating"] = imp.get("final_rating")
                result["improve_status"] = imp.get("status")
                result["improve_history"] = imp.get("history", [])
            else:
                # Try one more critic run
                rating, stars = run_critic(sid)
                result["final_stars"] = stars
                result["final_rating"] = rating
                result["improve_status"] = "improve_failed_ran_critic"
        
        results.append(result)
        log(f"  DONE: {result.get('final_stars', '?')} stars ({result.get('final_rating', '?')}/10)")
    
    # Summary
    log(f"\n{'='*70}")
    log("BATCH PIPELINE COMPLETE - SUMMARY")
    log("=" * 70)
    for r in results:
        log(f"  {r['title'][:50]}: {r.get('extended_to', '?')} scenes | "
            f"pre={r.get('pre_improve_stars', '?')}* -> "
            f"final={r.get('final_stars', '?')}* ({r.get('final_rating', '?')}/10) | "
            f"status={r.get('improve_status', '?')}")
    
    # Save results
    results_file = OUTPUTS_DIR.parent / "batch_improve_results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    log(f"\nResults saved to {results_file}")
    
    # Count successes
    success = sum(1 for r in results if (r.get("final_stars", 0) or 0) >= 4.5)
    log(f"\n{success}/{len(results)} stories reached 4.5+ stars")

if __name__ == "__main__":
    main()
