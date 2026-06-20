"""
One-Scene Proof-of-Concept Pipeline
====================================
Tests the full Fantasee generation flow on a single scene:
  1. ComfyUI → scene image(s)
  2. MiMo TTS → narration audio
  3. Whisper → subtitle alignment
  4. Manifest → story.json for the viewer

Usage:
  python poc_pipeline.py
  python poc_pipeline.py --concept "A dragon attacks a medieval castle"
  python poc_pipeline.py --scene 0  (index into multi-scene concepts)
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from tts_utils import generate_tts, get_audio_duration, XIAOMI_VOICES
from comfyui_utils import generate_image, is_running as comfyui_running

# ── Config ──────────────────────────────────────────────────────────────
OUTPUT_BASE = Path(r"C:\dev\fantasee\outputs")
OUTPUT_BASE.mkdir(parents=True, exist_ok=True)

# Hardcoded scene for PoC — a dramatic siege moment
POC_SCENE = {
    "scene_num": 1,
    "title": "The Last Stand",
    "prompt": (
        "A weathered warrior in battered silver armor stands on a crumbling "
        "stone fortress wall at dusk, gripping a notched broadsword. Behind him, "
        "hundreds of flaming arrows streak across a blood-red sky toward a dark "
        "horizon. The warrior's face is illuminated by the warm amber glow of "
        "distant fires, his jaw set with grim determination. Below the wall, "
        "shadowy figures swarm through the mist. Shot from a low angle looking "
        "up, dramatic backlighting, deep indigos and crimson tones, cinematic "
        "composition, fantasy painterly style, masterpiece quality"
    ),
    "narration": (
        "The ancient fortress of Ravenhold stood alone against the encroaching "
        "darkness. High on the parapets, Commander Aldric watched the horizon "
        "with grim determination. His armor, battered by a hundred skirmishes, "
        "caught the last light of a dying sun. Behind him, the garrison prepared "
        "for what would be their final night. The enemy was relentless — ten "
        "thousand strong, their banners black as the void itself. But Aldric "
        "had made a vow, whispered to the ghosts of those who fell before him. "
        "Ravenhold would not fall. Not while he still drew breath."
    ),
}


def run_poc(scene: dict, voice_preset: str = "dramatic_male", skip_images: bool = False):
    """Run the full PoC pipeline on a single scene."""
    scene_num = scene["scene_num"]
    story_id = "poc-ravenhold"
    scene_dir = OUTPUT_BASE / story_id
    scene_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  FANTASEE PoC — Scene {scene_num}: {scene['title']}")
    print(f"{'='*60}\n")

    results = {
        "scene_num": scene_num,
        "title": scene["title"],
        "prompt": scene["prompt"],
        "narration": scene["narration"],
        "images": [],
        "audio": None,
        "subtitles": None,
        "duration": 0,
    }

    # ── Step 1: ComfyUI Image Generation ────────────────────────────
    print("━━━ Step 1: Image Generation (ComfyUI) ━━━")
    if skip_images:
        print("  [SKIP] --skip-images flag set")
    else:
        status = comfyui_running()
        if not status["running"]:
            print("  [WARN] ComfyUI not running — skipping image generation")
        else:
            prefix = f"{story_id}_s{scene_num:02d}"
            print(f"  Generating scene image with DreamShaper...")
            t0 = time.time()
            filename = generate_image(
                prompt=scene["prompt"],
                output_prefix=prefix,
                output_dir=str(scene_dir),
                seed=hash(story_id + str(scene_num)) % (2**32 - 1),
                checkpoint="fantasy",
                timeout=600,
            )
            elapsed = time.time() - t0
            if filename:
                results["images"].append(filename)
                print(f"  ✓ Generated in {elapsed:.1f}s: {filename}")
            else:
                print(f"  ✗ Image generation failed ({elapsed:.1f}s)")

    # ── Step 2: MiMo TTS ───────────────────────────────────────────
    print("\n━━━ Step 2: Narration Audio (MiMo TTS) ━━━")
    audio_file = f"tts_{story_id}_s{scene_num:02d}.wav"
    audio_path = scene_dir / audio_file

    print(f"  Generating narration with {voice_preset} voice...")
    t0 = time.time()
    ok = generate_tts(
        text=scene["narration"],
        output_path=str(audio_path),
        voice_preset=voice_preset,
    )
    elapsed = time.time() - t0
    if ok:
        duration = get_audio_duration(str(audio_path))
        results["audio"] = audio_file
        results["duration"] = duration
        print(f"  ✓ Generated in {elapsed:.1f}s: {audio_file} ({duration:.1f}s)")
    else:
        print(f"  ✗ TTS generation failed ({elapsed:.1f}s)")

    # ── Step 3: Subtitle Alignment ──────────────────────────────────
    print("\n━━━ Step 3: Subtitle Alignment (Whisper) ━━━")
    if results["audio"] and audio_path.exists():
        try:
            from generate_subtitles import generate_subtitles
            print("  Aligning subtitles with Whisper...")
            t0 = time.time()
            segments = generate_subtitles(str(audio_path), scene["narration"])
            elapsed = time.time() - t0

            if segments:
                sub_file = f"subs_{story_id}_s{scene_num:02d}.json"
                sub_path = scene_dir / sub_file
                with open(sub_path, "w", encoding="utf-8") as f:
                    json.dump(segments, f, indent=2)
                results["subtitles"] = sub_file
                print(f"  ✓ {len(segments)} subtitle segments in {elapsed:.1f}s")
                for seg in segments[:3]:
                    preview = seg["text"][:60]
                    print(f"    [{seg['start']:.1f}s-{seg['end']:.1f}s] {preview}...")
                if len(segments) > 3:
                    print(f"    ... and {len(segments) - 3} more")
            else:
                print(f"  ✗ No subtitle segments generated")
        except ImportError as e:
            print(f"  [WARN] Whisper not available: {e}")
        except Exception as e:
            print(f"  ✗ Subtitle generation error: {e}")
    else:
        print("  [SKIP] No audio to align against")

    # ── Step 4: Save Manifest ───────────────────────────────────────
    print("\n━━━ Step 4: Story Manifest ━━━")
    manifest = {
        "id": story_id,
        "title": "The Siege of Ravenhold (PoC)",
        "subtitle": "A proof-of-concept generated story",
        "description": "Commander Aldric makes his final stand at the fortress of Ravenhold as the darkness closes in.",
        "tags": ["fantasy", "dramatic", "poc", "generated"],
        "generated": True,
        "scenes": [
            {
                "scene": f"{scene_num:02d}",
                "title": scene["title"],
                "prompt": scene["prompt"],
                "narration": scene["narration"],
                "narration_text": scene["narration"],
                "image_filenames": results["images"],
                "audio_filename": results["audio"],
                "audio_duration": results["duration"],
                "subtitle_file": results["subtitles"],
                "seed": hash(story_id + str(scene_num)) % (2**32 - 1),
            }
        ],
    }

    manifest_path = scene_dir / f"{story_id}.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"  ✓ Manifest saved: {manifest_path}")

    # ── Summary ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  PoC Complete!")
    print(f"{'='*60}")
    print(f"  Story ID:  {story_id}")
    print(f"  Images:    {len(results['images'])}")
    print(f"  Audio:     {results['audio'] or 'none'} ({results['duration']:.1f}s)")
    print(f"  Subtitles: {results['subtitles'] or 'none'}")
    print(f"  Manifest:  {manifest_path}")
    print(f"  Output:    {scene_dir}")
    print(f"{'='*60}\n")

    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fantasee PoC — single scene pipeline")
    parser.add_argument("--voice", default="Dean",
                        choices=list(XIAOMI_VOICES.keys()) + list(["dramatic_male", "warm_male", "british_male"]),
                        help="Voice for TTS (Mia/Chloe/Milo/Dean or aliases)")
    parser.add_argument("--skip-images", action="store_true",
                        help="Skip ComfyUI image generation")
    args = parser.parse_args()

    result = run_poc(POC_SCENE, voice_preset=args.voice, skip_images=args.skip_images)
    print(json.dumps({"status": "complete", "story_id": result["id"]}, indent=2))
