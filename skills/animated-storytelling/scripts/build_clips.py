#!/usr/bin/env python3
"""Build individual scene video clips as ComfyUI images land.

Usage: python build_clips.py <output_dir> <story_prefix> <tts_prefix> <clip_prefix>

Scans the output directory for images matching <story_prefix>_sceneNN_*.png.
For each image found without a corresponding clip, builds a clip via ffmpeg
(image looped + TTS audio).

This enables incremental assembly: clips are built as images arrive, so the
final ffmpeg concat takes seconds when the last image lands.

Example:
  python build_clips.py E:/hermes/workspace/outputs flood_tide tts_flood clip_flood
"""

import os
import subprocess
import sys


def build_clips(output_dir: str, story_prefix: str, tts_prefix: str, clip_prefix: str) -> int:
    built = 0
    for i in range(1, 31):  # support up to 30 scenes
        # Check for any image matching this scene
        imgs = [f for f in os.listdir(output_dir)
                if f.startswith(f"{story_prefix}_scene{i:02d}") and f.endswith(".png")]
        if not imgs:
            continue

        clip_path = os.path.join(output_dir, f"{clip_prefix}_{i:02d}.mp4")
        if os.path.exists(clip_path):
            continue

        # Use the first matching image (ComfyUI may save _00001_, _00002_, etc.)
        img_path = os.path.join(output_dir, imgs[0]).replace("\\", "/")
        tts_path = os.path.join(output_dir, f"{tts_prefix}_s{i:02d}.mp3").replace("\\", "/")
        clip_path_msys = clip_path.replace("\\", "/")

        cmd = (
            f'ffmpeg -y -loop 1 -i "{img_path}" -i "{tts_path}" '
            f'-c:v libx264 -c:a aac -pix_fmt yuv420p -r 24 -shortest '
            f'"{clip_path_msys}"'
        )

        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            built += 1
            print(f"  Clip {i:02d} ✓")
        else:
            # Print just the last line of ffmpeg output for diagnostics
            err_lines = result.stderr.strip().split("\n")
            last = err_lines[-1] if err_lines else "unknown error"
            print(f"  Clip {i:02d} FAILED: {last}")

    return built


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python build_clips.py <output_dir> <story_prefix> <tts_prefix> <clip_prefix>")
        print("Example: python build_clips.py E:/hermes/workspace/outputs siege tts_siege clip_siege")
        sys.exit(1)

    output_dir = sys.argv[1]
    story_prefix = sys.argv[2]
    tts_prefix = sys.argv[3]
    clip_prefix = sys.argv[4]

    if not os.path.isdir(output_dir):
        print(f"ERROR: Output directory not found: {output_dir}")
        sys.exit(1)

    built = build_clips(output_dir, story_prefix, tts_prefix, clip_prefix)
    print(f"Built {built} new clip(s) for {story_prefix}")
