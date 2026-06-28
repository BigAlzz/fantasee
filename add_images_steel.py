#!/usr/bin/env python3
"""Add images to bring Steel and Stratagem to 5 per scene."""
import hashlib, json, os, re, sys, time
from pathlib import Path

CWD = Path("C:/dev/fantasee")
sys.path.insert(0, str(CWD))
from comfyui_utils import generate_image, is_running, checkpoint_for_style

story_id = "steel-and-stratagem"
d = CWD / "stories" / story_id
mf = d / f"{story_id}.json"
m = json.loads(mf.read_text(encoding="utf-8"))

style = m.get("style", "manhwa")
checkpoint = checkpoint_for_style(style)
print(f"Story: {story_id} | checkpoint: {checkpoint}", flush=True)

total = 0
failures = 0

for si, s in enumerate(m["scenes"]):
    scene_key = s.get("scene", f"{si+1:02d}")
    existing = s.get("image_filenames", [])
    need = 5 - len(existing)
    if need <= 0:
        continue

    prompt = s.get("prompt", "")
    if not prompt:
        print(f"  Scene {scene_key}: no prompt", flush=True)
        continue

    safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', s.get("title", "")).strip("_")[:30] or f"Scene{scene_key}"

    for img_idx in range(len(existing) + 1, 6):
        seed = int(hashlib.md5(f"{story_id}{scene_key}{img_idx}x5".encode()).hexdigest()[:8], 16) % (2**32 - 1)
        prefix = f"{story_id}_s{scene_key}_{safe_title}_{img_idx:02d}"

        print(f"  [{time.strftime('%H:%M:%S')}] Scene {scene_key} img {img_idx}/5...", flush=True)
        try:
            filename = generate_image(
                prompt=prompt,
                output_prefix=prefix,
                output_dir=str(d),
                seed=seed,
                checkpoint=checkpoint,
                timeout=300,
            )
            if filename:
                existing.append(filename)
                s["image_filenames"] = existing
                total += 1
                m["scenes"] = m["scenes"]
                tmp = mf.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(m, indent=2), encoding="utf-8")
                os.replace(str(tmp), str(mf))
                print(f"    OK ({total}/30)", flush=True)
            else:
                print(f"    NO FILE returned", flush=True)
                failures += 1
                break
        except Exception as e:
            print(f"    FAILED: {e}", flush=True)
            failures += 1
            if not is_running().get("running", False):
                print("    ComfyUI went down!", flush=True)
                break
            break

print(f"\n=== Steel and Stratagem DONE ===", flush=True)
print(f"Generated: {total} images", flush=True)
print(f"Failed: {failures}", flush=True)
