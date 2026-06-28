#!/usr/bin/env python3
"""Pre-flight check: verify all dependencies and services before a batch run."""
import json, os, sys, time
from pathlib import Path

CWD = Path("C:/dev/fantasee")
sys.path.insert(0, str(CWD))

def check(label, ok, detail=""):
    icon = "✅" if ok else "❌"
    print(f"  {icon} {label}" + (f" — {detail}" if detail else ""))
    return ok

print("=== Fantasee Pre-flight Check ===\n")

all_ok = True

# 1. ComfyUI
print("[1] ComfyUI")
try:
    from comfyui_utils import is_running
    status = is_running()
    running = status.get("running", False)
    url = status.get("url", "?")
    all_ok &= check("ComfyUI running", running, url)
except Exception as e:
    all_ok &= check("ComfyUI", False, str(e))

# 2. LLM API (MiMo)
print("\n[2] LLM API (MiMo)")
try:
    import requests
    env_path = Path(os.environ.get("HERMES_HOME", "E:\\hermes")) / ".env"
    api_key = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith("XIAOMI_API_KEY=") and not line.strip().startswith("#"):
                api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not api_key:
        api_key = os.environ.get("XIAOMI_API_KEY", "")
    base_url = os.environ.get("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
    if api_key and not api_key.startswith("***"):
        resp = requests.post(
            f"{base_url}/chat/completions",
            json={"model": "mimo-v2.5-pro", "messages": [{"role": "user", "content": "Say OK"}], "max_completion_tokens": 10},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30,
        )
        all_ok &= check("MiMo API reachable", resp.status_code == 200, f"HTTP {resp.status_code}")
    else:
        all_ok &= check("MiMo API key", False, "Not set or masked")
except Exception as e:
    all_ok &= check("MiMo API", False, str(e))

# 3. faster-whisper (subtitles)
print("\n[3] Subtitle generation (faster-whisper)")
try:
    from faster_whisper import WhisperModel
    all_ok &= check("faster_whisper importable", True)
except ImportError as e:
    all_ok &= check("faster_whisper", False, "Not installed")

# 4. TTS (MiMo TTS)
print("\n[4] TTS")
try:
    from tts_utils import generate_tts
    test_path = str(CWD / "_tts_test.wav")
    ok = generate_tts("Test.", test_path, voice="Dean")
    if ok and os.path.exists(test_path):
        size = os.path.getsize(test_path)
        os.remove(test_path)
        all_ok &= check("TTS generate", size > 1000, f"{size} bytes")
    else:
        all_ok &= check("TTS generate", False, "Failed or empty output")
except Exception as e:
    all_ok &= check("TTS", False, str(e))

# 5. FFmpeg
print("\n[5] FFmpeg")
try:
    import subprocess
    r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
    all_ok &= check("ffmpeg available", r.returncode == 0, r.stdout[:50].strip())
except FileNotFoundError:
    all_ok &= check("ffmpeg", False, "Not found in PATH")
except Exception as e:
    all_ok &= check("ffmpeg", False, str(e))

# 6. Disk space
print("\n[6] Disk space")
try:
    import shutil
    total, used, free = shutil.disk_usage("C:/")
    free_gb = free / (1024**3)
    all_ok &= check("Free disk", free_gb > 10, f"{free_gb:.1f} GB free")
except Exception as e:
    all_ok &= check("Disk space", False, str(e))

# 7. Pillow (title slides, poster)
print("\n[7] Image processing (Pillow)")
try:
    from PIL import Image
    all_ok &= check("Pillow importable", True)
except ImportError:
    all_ok &= check("Pillow", False, "Not installed")

# 8. Stories summary
print("\n[8] Stories inventory")
from story_storage import STORIES_ROOT
manhwa = []
for d in sorted(STORIES_ROOT.iterdir()):
    if not d.is_dir(): continue
    jf = d / f"{d.name}.json"
    if not jf.exists(): continue
    try:
        m = json.loads(jf.read_text(encoding="utf-8"))
    except: continue
    if "manhwa" not in m.get("tags", []): continue
    scenes = m.get("scenes", [])
    if len(scenes) < 5: continue
    total_imgs = sum(len(s.get("image_filenames", [])) for s in scenes)
    has_subs = sum(1 for s in scenes if s.get("subtitle_segments") or s.get("subtitle_file"))
    has_video = (d / f"{d.name}_full.mp4").exists()
    manhwa.append({
        "id": d.name,
        "title": m.get("title", d.name),
        "scenes": len(scenes),
        "images": total_imgs,
        "target_imgs": len(scenes) * 5,
        "subs": has_subs,
        "video": has_video,
    })

print(f"  Manhwa stories: {len(manhwa)}")
for s in manhwa:
    img_pct = (s["images"] / s["target_imgs"] * 100) if s["target_imgs"] else 0
    sub_str = f"{s['subs']}/{s['scenes']}" if s['subs'] != s['scenes'] else "all"
    print(f"  {s['title'][:40]:40s} | {s['scenes']:2d} scenes | {s['images']:3d}/{s['target_imgs']:3d} imgs ({img_pct:.0f}%) | subs:{sub_str} | vid:{'Y' if s['video'] else 'N'}")

# Summary
print(f"\n{'='*50}")
if all_ok:
    print("✅ ALL CHECKS PASSED — ready to generate")
else:
    print("❌ SOME CHECKS FAILED — fix issues before batch run")
print(f"{'='*50}")
