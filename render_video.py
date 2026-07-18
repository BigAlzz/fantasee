#!/usr/bin/env python3
"""
Fantasee Video Renderer — converts raw story assets into MP4 videos.

Takes images, TTS audio, and subtitle JSONs per scene and produces:
  - Per-scene MP4 (Ken Burns image slideshow + narration audio)
  - Per-scene VTT subtitle sidecar files
  - Full story MP4 (all scenes concatenated)
  - Full story VTT (all subtitles combined)

Usage:
    python render_video.py the-emerald-s-fading-cure
    python render_video.py the-emerald-s-fading-cure --resolution 1280x720
    python render_video.py the-emerald-s-fading-cure --burn-subs
    python render_video.py the-emerald-s-fading-cure --scene-only 5
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from story_storage import STORIES_ROOT, existing_story_dir, ensure_story_layout
from image_quality import is_usable_story_image

# ── Defaults ────────────────────────────────────────────────────────────
OUTPUTS = STORIES_ROOT
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
CROSSFADE_DURATION = 0.8       # seconds of crossfade between images
ZOOM_MAX = 1.08                # max zoom factor (8% zoom in)
FPS = 30
AUDIO_BITRATE = "192k"
VIDEO_CRF = 20                 # quality (lower = better, 18-23 typical)


def get_scene_assets(story_dir: Path, slug: str, scene_num: int) -> dict:
    """Find all assets for a given scene."""
    scene_key = f"{scene_num:02d}"
    image_durations: list[float] | None = None

    # An approved editorial timeline wins over the legacy manifest glob. This
    # prevents rejected candidates or unrelated scene artwork from entering
    # the release render.
    shot_segments: list[dict] = []
    for timeline_name in ("timeline.json", "shot_timeline.json"):
        try:
            timeline = json.loads((story_dir / "working" / timeline_name).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            continue
        shot_segments = [
            segment for segment in (timeline.get("shot_segments") or timeline.get("segments") or [])
            if segment.get("scene_id") in {f"scene-{scene_key}", scene_key, f"s{scene_key}"}
            and segment.get("asset_path")
        ]
        if shot_segments:
            break

    if shot_segments:
        shot_segments.sort(key=lambda segment: (float(segment.get("start", 0)), segment.get("shot_id", "")))
        images = []
        image_durations = []
        for segment in shot_segments:
            path = Path(str(segment["asset_path"]))
            if not path.is_absolute():
                path = story_dir / path
            if is_usable_story_image(path):
                images.append(path)
                image_durations.append(max(0.01, float(segment.get("end", 0)) - float(segment.get("start", 0))))
    else:
        # Legacy stories remain supported until their shot plans are migrated.
        images = sorted(story_dir.glob(f"{slug}_s{scene_key}_*_00001_.png"))
        if not images:
            images = sorted(story_dir.glob(f"{slug}_s{scene_key}_*.png"))
        images = [path for path in images if is_usable_story_image(path)]
    
    # Find audio
    audio = None
    for pattern in [
        f"tts_{slug}_s{scene_key}.wav",
    ]:
        candidate = story_dir / pattern
        if candidate.exists():
            audio = candidate
            break
    
    # Find subtitles
    subs = None
    candidate = story_dir / f"subs_{slug}_s{scene_key}.json"
    if candidate.exists():
        subs = candidate
    
    # Get audio duration
    duration = 0.0
    if audio:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
             str(audio)],
            capture_output=True, text=True
        )
        duration = float(probe.stdout.strip()) if probe.stdout.strip() else 0.0
    
    return {
        "scene_key": scene_key,
        "images": images,
        "audio": audio,
        "subs": subs,
        "duration": duration,
        "image_durations": image_durations,
    }


def subs_json_to_vtt(segments: list, vtt_path: Path):
    """Convert Fantasee subtitle segments to WebVTT format."""
    lines = ["WEBVTT", ""]
    
    def fmt_time(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    
    for i, seg in enumerate(segments):
        text = seg.get("text", "").replace("\n", " ").strip()
        lines.append(f"{i + 1}")
        lines.append(f"{fmt_time(seg['start'])} --> {fmt_time(seg['end'])}")
        lines.append(text)
        lines.append("")
    
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def render_scene(story_dir: Path, slug: str, assets: dict,
                 output_dir: Path, width: int, height: int,
                 fps: int, crf: int,
                 burn_subs: bool = False) -> Optional[Path]:
    """
    Render a single scene to MP4 with Ken Burns zoompan + crossfade + audio.
    
    Strategy:
    1. Each image → zoompan clip (slow zoom, d=1 with -loop 1)
    2. Chain clips with xfade crossfade
    3. Add audio, trim to exact duration
    """
    scene_key = assets["scene_key"]
    images = assets["images"]
    audio = assets["audio"]
    subs = assets["subs"]
    duration = assets["duration"]
    
    if not images:
        print(f"  SKIP scene {scene_key}: no images found")
        return None
    if not audio:
        print(f"  SKIP scene {scene_key}: no audio found")
        return None
    
    n_images = len(images)
    n_crossfades = max(0, n_images - 1)

    requested_durations = assets.get("image_durations")
    if requested_durations and len(requested_durations) == n_images:
        requested_total = sum(requested_durations)
        scale = duration / requested_total if requested_total > 0 else 1.0
        segment_durations = [value * scale for value in requested_durations]
        clip_durations = [
            segment + (CROSSFADE_DURATION if index < n_images - 1 else 0.0)
            for index, segment in enumerate(segment_durations)
        ]
        clip_label = "approved shot timing"
    else:
        # Legacy behavior: distribute the scene evenly across its images.
        clip_dur = (duration + n_crossfades * CROSSFADE_DURATION) / n_images
        segment_durations = [clip_dur - CROSSFADE_DURATION] * n_images
        segment_durations[-1] += CROSSFADE_DURATION
        clip_durations = [clip_dur] * n_images
        clip_label = f"clip={clip_dur:.2f}s"

    print(f"  Scene {scene_key}: {n_images} images, {duration:.1f}s, "
          f"{clip_label}")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        clip_paths = []
        
        # Ken Burns zoom increment per frame
        # Total zoom range: 1.0 → ZOOM_MAX over clip_dur * fps frames
        # Generate individual image clips with zoompan
        # Alternating directions: zoom-in, pan-right, zoom-out, pan-left
        directions = ["zoom_in", "pan_right", "zoom_out", "pan_left"]
        
        for i, img_path in enumerate(images):
            clip_dur = clip_durations[i]
            total_frames = int(clip_dur * fps)
            zoom_per_frame = (ZOOM_MAX - 1.0) / max(total_frames, 1)
            direction = directions[i % len(directions)]
            clip_path = tmpdir / f"clip_{i:02d}.mp4"
            
            # Build zoompan expression based on direction
            if direction == "zoom_in":
                z_expr = f"min(zoom+{zoom_per_frame:.8f},{ZOOM_MAX})"
                x_expr = "iw/2-(iw/zoom/2)"
                y_expr = "ih/2-(ih/zoom/2)"
            elif direction == "zoom_out":
                z_expr = f"max({ZOOM_MAX}-on*{zoom_per_frame:.8f},1.0)"
                x_expr = "iw/2-(iw/zoom/2)"
                y_expr = "ih/2-(ih/zoom/2)"
            elif direction == "pan_right":
                z_expr = str(ZOOM_MAX)
                x_expr = f"(iw-iw/zoom)*on/{total_frames}"
                y_expr = "ih/2-(ih/zoom/2)"
            else:  # pan_left
                z_expr = str(ZOOM_MAX)
                x_expr = f"(iw-iw/zoom)*(1-on/{total_frames})"
                y_expr = "ih/2-(ih/zoom/2)"
            
            # zoompan with d=1: outputs 1 frame per input frame
            # -loop 1 provides infinite frames, -t limits duration
            zp_filter = (
                f"zoompan=z='{z_expr}':d=1:"
                f"x='{x_expr}':y='{y_expr}':"
                f"s={width}x{height}:fps={fps},"
                f"format=yuv420p"
            )
            
            cmd = [
                "ffmpeg", "-y",
                "-r", str(fps),
                "-loop", "1", "-t", f"{clip_dur:.3f}",
                "-i", str(img_path),
                "-vf", zp_filter,
                "-c:v", "libx264", "-preset", "fast",
                "-crf", str(crf),
                "-an",
                str(clip_path)
            ]
            
            t0 = _time()
            result = subprocess.run(cmd, capture_output=True, text=True)
            elapsed = _time() - t0
            
            if result.returncode != 0:
                print(f"  ERROR clip {i} ({direction}): {result.stderr[-300:]}")
                return None
            
            clip_paths.append(clip_path)
            sz_mb = clip_path.stat().st_size / 1024 / 1024
            print(f"    clip {i+1}/{n_images} ({direction}) {sz_mb:.1f}MB {elapsed:.1f}s")
        
        # ── Chain clips with xfade ──────────────────────────────────────
        if n_images == 1:
            # Single image — just use the clip directly
            concat_video = clip_paths[0]
        else:
            # Build xfade chain: [c0][c1]xfade→[xf0], [xf0][c2]xfade→[xf1], ...
            # Each input needs its own -i
            filter_inputs = []
            filter_parts = []
            
            for i, cp in enumerate(clip_paths):
                filter_inputs.extend(["-i", str(cp)])
            
            # Input pads are addressed by their ffmpeg stream labels.  The
            # previous implementation used ``v0``, ``v1``, ... for the
            # inputs, which are output-link labels rather than input stream
            # labels.  ffmpeg consequently kept the first stream as the
            # effective video throughout the xfade chain.
            prev_label = "0:v"
            for i in range(1, n_images):
                # With explicit shot timing, each transition starts at the
                # next approved segment boundary. Legacy clips retain their
                # equivalent evenly-spaced offsets.
                xfade_off = sum(segment_durations[:i])
                
                if i < n_images - 1:
                    out_label = f"xf{i}"
                else:
                    out_label = "vout"
                
                filter_parts.append(
                    f"[{prev_label}][{i}:v]xfade=transition=fade:"
                    f"duration={CROSSFADE_DURATION}:"
                    f"offset={xfade_off:.3f}[{out_label}]"
                )
                prev_label = out_label
            
            # Optional subtitle burn-in
            vout_label = "vout"
            if burn_subs and subs:
                with open(subs, "r", encoding="utf-8") as f:
                    sub_segs = json.load(f)
                vtt_path = tmpdir / f"scene_{scene_key}.vtt"
                subs_json_to_vtt(sub_segs, vtt_path)
                vtt_esc = str(vtt_path).replace("\\", "/").replace(":", "\\:")
                filter_parts.append(
                    f"[vout]subtitles='{vtt_esc}':"
                    f"force_style='FontSize=22,PrimaryColour=&H00FFFFFF,"
                    f"OutlineColour=&H00000000,Outline=2,MarginV=40'[vfinal]"
                )
                vout_label = "vfinal"
            
            filter_complex = ";\n".join(filter_parts)
            
            xfade_video = tmpdir / "xfade_output.mp4"
            cmd = [
                "ffmpeg", "-y",
                *filter_inputs,
                "-filter_complex", filter_complex,
                "-map", f"[{vout_label}]",
                "-c:v", "libx264", "-preset", "fast",
                "-crf", str(crf),
                "-an",
                str(xfade_video)
            ]
            
            t0 = _time()
            result = subprocess.run(cmd, capture_output=True, text=True)
            elapsed = _time() - t0
            
            if result.returncode != 0:
                print(f"  ERROR xfade: {result.stderr[-500:]}")
                print(f"  Filter:\n{filter_complex[:500]}")
                return None
            
            print(f"    xfade chain: {xfade_video.stat().st_size/1024/1024:.1f}MB {elapsed:.1f}s")
            concat_video = xfade_video
        
        # ── Add audio + trim ────────────────────────────────────────────
        out_path = output_dir / f"{slug}_s{scene_key}.mp4"
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(concat_video),
            "-i", str(audio),
            "-af", "dynaudnorm=f=150:g=15",
            "-map", "0:v", "-map", "1:a",
            "-t", f"{duration:.3f}",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-shortest",
            "-movflags", "+faststart",
            str(out_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR add audio: {result.stderr[-300:]}")
            return None
        
        size_mb = out_path.stat().st_size / 1024 / 1024
        print(f"  -> {out_path.name} ({size_mb:.1f} MB, {duration:.1f}s)")
        
        # Save VTT subtitle sidecar
        if subs:
            vtt_out = output_dir / f"{slug}_s{scene_key}.vtt"
            with open(subs, "r", encoding="utf-8") as f:
                sub_segs = json.load(f)
            subs_json_to_vtt(sub_segs, vtt_out)
            print(f"  -> {vtt_out.name}")
        
        return out_path


def concatenate_scenes(scene_videos: list[Path], slug: str,
                       output_dir: Path) -> Optional[Path]:
    """Concatenate per-scene MP4s into a full story video."""
    if not scene_videos:
        return None
    
    with tempfile.TemporaryDirectory() as tmpdir:
        concat_list = Path(tmpdir) / "concat.txt"
        with open(concat_list, "w") as f:
            for sv in scene_videos:
                f.write(f"file '{sv}'\n")
        
        out_path = output_dir / f"{slug}_full.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-movflags", "+faststart",
            str(out_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR concat: {result.stderr[-500:]}")
            return None
        
        size_mb = out_path.stat().st_size / 1024 / 1024
        
        # Get total duration
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", str(out_path)],
            capture_output=True, text=True
        )
        total_dur = float(probe.stdout.strip()) if probe.stdout.strip() else 0
        
        print(f"\n  Full story: {out_path.name} ({size_mb:.1f} MB, "
              f"{total_dur:.0f}s = {total_dur/60:.1f}min)")
        return out_path


def concatenate_vtts(scene_vtts: list[Path], slug: str,
                     output_dir: Path) -> Optional[Path]:
    """Combine per-scene VTT files into one with adjusted timestamps."""
    if not scene_vtts:
        return None
    
    all_cues = []
    time_offset = 0.0
    
    def vtt_time_to_seconds(ts: str) -> float:
        parts = ts.strip().split(":")
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return float(m) * 60 + float(s)
        return float(parts[0])
    
    def seconds_to_vtt_time(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    
    for vtt_path in scene_vtts:
        with open(vtt_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        blocks = content.strip().split("\n\n")
        max_end = 0.0
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue
            for j, line in enumerate(lines):
                if "-->" in line:
                    ts_parts = line.split("-->")
                    start = vtt_time_to_seconds(ts_parts[0]) + time_offset
                    end = vtt_time_to_seconds(ts_parts[1]) + time_offset
                    text = " ".join(lines[j+1:])
                    all_cues.append((start, end, text))
                    max_end = max(max_end, end - time_offset)
                    break
        
        # Add gap between scenes (0.5s)
        time_offset += max_end + 0.5
    
    lines = ["WEBVTT", ""]
    for i, (start, end, text) in enumerate(all_cues):
        lines.append(f"{i + 1}")
        lines.append(f"{seconds_to_vtt_time(start)} --> {seconds_to_vtt_time(end)}")
        lines.append(text)
        lines.append("")
    
    out_path = output_dir / f"{slug}_full.vtt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    print(f"  Full subtitles: {out_path.name} ({len(all_cues)} cues)")
    return out_path


def _time():
    """Simple timer."""
    import time
    return time.time()


def main():
    parser = argparse.ArgumentParser(description="Fantasee Video Renderer")
    parser.add_argument("slug", help="Story slug (folder name in stories/)")
    parser.add_argument("--outputs-dir", type=Path, default=OUTPUTS,
                        help="Base outputs directory")
    parser.add_argument("--resolution", default=f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}",
                        help="Output resolution (e.g. 1920x1080)")
    parser.add_argument("--fps", type=int, default=FPS, help="Output FPS")
    parser.add_argument("--crf", type=int, default=VIDEO_CRF,
                        help="Video quality (lower=better, 18-28)")
    parser.add_argument("--burn-subs", action="store_true",
                        help="Burn subtitles into video (hardcoded)")
    parser.add_argument("--scene-only", type=int, metavar="N",
                        help="Render only scene N")
    parser.add_argument("--no-full", action="store_true",
                        help="Skip full story concatenation")
    args = parser.parse_args()
    
    w, h = args.resolution.split("x")
    width, height = int(w), int(h)
    
    story_dir = args.outputs_dir / args.slug
    if args.outputs_dir == OUTPUTS:
        story_dir = existing_story_dir(args.slug)
    if not story_dir.is_dir():
        print(f"ERROR: Story directory not found: {story_dir}")
        sys.exit(1)
    layout = ensure_story_layout(story_dir)
    
    # Read story metadata
    meta_path = story_dir / f"{args.slug}.json"
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        scenes = meta.get("scenes", [])
    else:
        scene_nums = set()
        for p in story_dir.glob(f"subs_{args.slug}_s*.json"):
            key = p.stem.split("_s")[-1]
            scene_nums.add(int(key))
        scenes = [{"scene": str(n)} for n in sorted(scene_nums)]
    
    if args.scene_only:
        scene_range = [args.scene_only]
    else:
        scene_range = [int(s["scene"]) for s in scenes]
    
    print("=" * 60)
    print(f"  Fantasee Video Renderer")
    print(f"  Story:     {args.slug}")
    print(f"  Resolution: {width}x{height} @ {args.fps}fps")
    print(f"  CRF:       {args.crf}")
    print(f"  Scenes:    {scene_range}")
    print(f"  Burn subs: {args.burn_subs}")
    print("=" * 60 + "\n")
    
    t_start = _time()
    scene_videos = []
    scene_vtts = []
    
    for scene_num in scene_range:
        assets = get_scene_assets(story_dir, args.slug, scene_num)
        
        if not assets["images"] or not assets["audio"]:
            print(f"  SKIP scene {scene_num:02d}: missing assets")
            continue
        
        result = render_scene(story_dir, args.slug, assets, story_dir,
                             width, height, args.fps, args.crf, args.burn_subs)
        
        if result:
            scene_videos.append(result)
            vtt_path = story_dir / f"{args.slug}_s{scene_num:02d}.vtt"
            if vtt_path.exists():
                scene_vtts.append(vtt_path)
        
        print()
    
    # Concatenate all scenes
    if not args.no_full and len(scene_videos) > 1:
        print("Concatenating scenes...")
        concatenate_scenes(scene_videos, args.slug, story_dir)
        if scene_vtts:
            concatenate_vtts(scene_vtts, args.slug, story_dir)
        for suffix in (".mp4", ".vtt"):
            full_path = story_dir / f"{args.slug}_full{suffix}"
            if full_path.exists():
                shutil.copy2(full_path, layout["final"] / full_path.name)
    
    elapsed = _time() - t_start
    print("\n" + "=" * 60)
    print(f"  Done! {len(scene_videos)} scenes rendered in {elapsed:.0f}s")
    print(f"  Output: {story_dir}")
    print("=" * 60)

    # Exit non-zero when nothing was rendered, so the server endpoint and
    # any caller can detect the silent no-op (story has no images / no
    # audio on disk) instead of reporting "success". Use a dedicated code
    # (2) so callers can distinguish "ffmpeg failed" (1) from "nothing to do".
    if len(scene_videos) == 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
