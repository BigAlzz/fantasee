"""Plex-ready MP4 export with subtitles, chapters, and mixed background audio.

Produces a single ``<story-title>.mp4`` (H.264 / AAC, ``+faststart``) with:

* embedded FFmpeg chapter metadata using scene titles as chapter names,
* external ``<story-title>.en.srt`` and ``<story-title>.en.vtt`` sidecar
  subtitles (Plex officially supports both — SRT and WebVTT are the
  recommended local-subtitle formats),
* narration at full volume mixed with a low-volume, looped background track,
* an optional poster image (``<story-title>-poster.jpg``) alongside the
  video so Plex / Infuse / MrMC can pick it up.

Final files land in ``<story-dir>/final/plex/`` so the working dir and
``final/`` (which already holds the basic full MP4 + VTT from
``render_video.py``) stay separate from the polished deliverable.

References used for the design:
* Plex local subtitles: https://support.plex.tv/articles/200471133-adding-local-subtitles-to-your-media/
* Plex chapter handling: https://forums.plex.tv/t/plex-handling-of-chapter-markers-when-the-file-already-has-them/476625
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from story_storage import ensure_story_layout, existing_story_dir, STORIES_ROOT
from background_music import (
    BACKGROUND_DIR,
    DEFAULT_BACKGROUND_VOLUME,
    background_audio_payload,
    select_background_track,
)


# ── Config ──────────────────────────────────────────────────────────────

# Match the existing render_video.py defaults so the output looks the same
# regardless of which pipeline produced it.
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 30
VIDEO_CRF = 20
AUDIO_BITRATE = "192k"
DEFAULT_BACKGROUND_LOOP_FADE = 0  # seconds of crossfade between loop iterations (0 = hard cut)

# Default Plex library root. Overridable per-call via the `destination`
# kwarg or per-environment via FANTASEE_PLEX_DEST. The Movies/<Title>
# (<Year>)/ folder layout is the Plex-recommended convention for
# auto-detection of title + year.
DEFAULT_PLEX_DEST = r"D:\Downloads\Plex"

# Windows + Plex filename blacklist. Plex follows the OS for path
# validity, so we strip everything that Windows can't store.
_PLEX_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_PLEX_TRAILING_DOTS = re.compile(r'[\s.]+$')
_PLEX_COLLAPSE_WS = re.compile(r'\s+')


# ── Time helpers ───────────────────────────────────────────────────────


def _seconds_to_srt_time(t: float) -> str:
    """HH:MM:SS,mmm — SRT's mandated format."""
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s_int = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s_int:02d},{ms:03d}"


def _seconds_to_vtt_time(t: float) -> str:
    """HH:MM:SS.mmm — WebVTT uses a period separator."""
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s_int = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s_int:02d}.{ms:03d}"


# ── Segment dataclass ───────────────────────────────────────────────────


@dataclass
class SubtitleSegment:
    text: str
    start: float
    end: float

    @classmethod
    def from_dict(cls, d: dict) -> "SubtitleSegment":
        return cls(
            text=str(d.get("text", "")).strip(),
            start=float(d.get("start", 0.0)),
            end=float(d.get("end", 0.0)),
        )


@dataclass
class SceneChapter:
    title: str
    start: float
    end: float

    @classmethod
    def from_scene(cls, scene: dict, start: float, end: float) -> "SceneChapter":
        title = (scene.get("title") or "").strip()
        if not title:
            title = f"Scene {scene.get('scene') or '?'}"
        return cls(title=title, start=start, end=end)


# ── SRT / VTT serialization ────────────────────────────────────────────


def segments_to_srt(segments: Iterable[dict]) -> str:
    """Serialize subtitle segments as SRT.

    Used both by the per-scene SRT writer and the combined SRT. Times in
    seconds; text is collapsed to a single line.
    """
    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        s = SubtitleSegment.from_dict(seg)
        if not s.text:
            continue
        text = s.text.replace("\n", " ").strip()
        lines.append(str(i))
        lines.append(f"{_seconds_to_srt_time(s.start)} --> {_seconds_to_srt_time(s.end)}")
        lines.append(text)
        lines.append("")  # blank separator
    return "\n".join(lines).rstrip() + "\n"


def segments_to_vtt(segments: Iterable[dict]) -> str:
    """Serialize subtitle segments as WebVTT (with header)."""
    lines: list[str] = ["WEBVTT", ""]
    for i, seg in enumerate(segments, start=1):
        s = SubtitleSegment.from_dict(seg)
        if not s.text:
            continue
        text = s.text.replace("\n", " ").strip()
        lines.append(str(i))
        lines.append(f"{_seconds_to_vtt_time(s.start)} --> {_seconds_to_vtt_time(s.end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ── Chapter metadata (FFmpeg format) ──────────────────────────────────


def _ffmpeg_escape_title(title: str) -> str:
    """FFmpeg metadata values can't contain '=' or ';' or newlines or leading '#'."""
    cleaned = re.sub(r"[\r\n]+", " ", title).strip()
    # FFmpeg treats '=' and ';' specially in metadata blocks; replace with safe chars.
    cleaned = cleaned.replace("=", "-").replace(";", ",")
    if cleaned.startswith("#"):
        cleaned = cleaned.lstrip("#").lstrip()
    # After replacements, we may have ended up with only punctuation (e.g. "==="
    # becomes "---"). If there's no alphanumeric content left, return the
    # placeholder so the chapter still has a meaningful name.
    if not any(c.isalnum() for c in cleaned):
        return "Chapter"
    return cleaned


def chapters_to_ffmetadata(chapters: Iterable[SceneChapter]) -> str:
    """Render chapters in FFmpeg's ``ffmetadata`` format with ``[CHAPTER]`` blocks.

    Times are in milliseconds (FFmpeg convention). See:
    https://ffmpeg.org/ffmpeg-formats.html#Metadata-1
    """
    blocks: list[str] = [";FFMETADATA1"]
    for ch in chapters:
        start_ms = max(0, int(round(ch.start * 1000)))
        end_ms = max(start_ms + 1, int(round(ch.end * 1000)))
        blocks.append("")
        blocks.append("[CHAPTER]")
        blocks.append("TIMEBASE=1/1000")
        blocks.append(f"START={start_ms}")
        blocks.append(f"END={end_ms}")
        blocks.append(f"title={_ffmpeg_escape_title(ch.title)}")
    return "\n".join(blocks) + "\n"


# ── Scene helpers ──────────────────────────────────────────────────────


def _slug_from_manifest(story_dir: Path, manifest_id: Optional[str] = None) -> str:
    if manifest_id:
        return manifest_id
    return story_dir.name


def _read_subs_for_scene(story_dir: Path, slug: str, scene_key: str) -> list[dict]:
    """Load the per-scene subtitle JSON written by ``generate_story.py``.

    Returns an empty list if the file does not exist.
    """
    path = story_dir / f"subs_{slug}_s{scene_key}.json"
    if not path.exists():
        # Some scenes have un-padded keys — try the alternate form.
        for cand in (
            story_dir / f"subs_{slug}_s{int(scene_key):02d}.json",
            story_dir / f"subs_{slug}_s{scene_key.lstrip('0')}.json",
        ):
            if cand.exists():
                path = cand
                break
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _read_audio_duration(audio_path: Path) -> float:
    """Return the audio's duration in seconds (used to size chapter end times)."""
    if not audio_path.exists():
        return 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return 0.0


@dataclass
class SceneAsset:
    """Resolved per-scene asset info used by the exporter."""

    scene_key: str
    title: str
    narration: str
    subs: list[dict]
    audio: Optional[Path]
    duration: float


def _discover_scenes(story_dir: Path, slug: str) -> list[SceneAsset]:
    """Find every scene with on-disk audio + subtitles, in scene-number order."""
    assets: list[SceneAsset] = []
    seen: set[str] = set()
    # Prefer the manifest's scene list when available, so titles stay in sync
    # with whatever the player shows.
    manifest_path = story_dir / f"{slug}.json"
    manifest_scenes: list[dict] = []
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_scenes = data.get("scenes", []) or []
        except (json.JSONDecodeError, OSError):
            manifest_scenes = []

    if manifest_scenes:
        for s in manifest_scenes:
            key = str(s.get("scene") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            audio = _find_audio_for_scene(story_dir, slug, key)
            duration = _read_audio_duration(audio) if audio else float(s.get("audio_duration") or 0.0)
            assets.append(SceneAsset(
                scene_key=key,
                title=str(s.get("title") or f"Scene {key}"),
                narration=str(s.get("narration") or s.get("narration_text") or ""),
                subs=_read_subs_for_scene(story_dir, slug, key),
                audio=audio,
                duration=duration,
            ))

    # Backfill any scenes that have on-disk audio/sub files but no manifest entry
    # (e.g. legacy / manually-built stories). This keeps the exporter forgiving.
    for audio_path in sorted(story_dir.glob(f"tts_{slug}_s*.wav")):
        m = re.search(r"_s(\d+[a-z]?)", audio_path.stem)
        if not m:
            continue
        key = m.group(1)
        if key in seen:
            continue
        seen.add(key)
        subs = _read_subs_for_scene(story_dir, slug, key)
        assets.append(SceneAsset(
            scene_key=key,
            title=f"Scene {key}",
            narration="",
            subs=subs,
            audio=audio_path,
            duration=_read_audio_duration(audio_path),
        ))

    return assets


def _find_audio_for_scene(story_dir: Path, slug: str, scene_key: str) -> Optional[Path]:
    candidates = [
        story_dir / f"tts_{slug}_s{scene_key}.wav",
        story_dir / f"tts_{slug}_s{int(scene_key):02d}.wav" if scene_key.isdigit() else None,
        story_dir / f"tts_{slug}_s{scene_key.lstrip('0')}.wav",
    ]
    for c in candidates:
        if c and c.exists():
            return c
    return None


# ── Per-scene / combined subtitle writers ─────────────────────────────


def write_scene_srt(scenes: list[SceneAsset], out_dir: Path) -> list[Path]:
    """Write per-scene SRT files (one per scene)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for sc in scenes:
        if not sc.subs:
            continue
        path = out_dir / f"{sc.scene_key}.srt"
        path.write_text(segments_to_srt(sc.subs), encoding="utf-8")
        written.append(path)
    return written


def write_combined_subtitles(
    scenes: list[SceneAsset],
    slug: str,
    out_dir: Path,
    gap_between_scenes: float = 0.5,
) -> tuple[Optional[Path], Optional[Path]]:
    """Combine per-scene subtitles into a single story-wide SRT + VTT.

    Returns ``(srt_path, vtt_path)``. Either may be ``None`` if no subtitles
    were found anywhere.
    """
    if not any(sc.subs for sc in scenes):
        return None, None

    combined: list[dict] = []
    cursor = 0.0
    for sc in scenes:
        if not sc.subs:
            # No subs for this scene — still pad the cursor with its duration
            # so subsequent scenes stay aligned to the timeline.
            cursor += max(0.0, sc.duration) + gap_between_scenes
            continue
        max_end = 0.0
        for seg in sc.subs:
            new_start = float(seg.get("start", 0.0)) + cursor
            new_end = float(seg.get("end", 0.0)) + cursor
            combined.append({
                "text": seg.get("text", ""),
                "start": new_start,
                "end": new_end,
            })
            max_end = max(max_end, float(seg.get("end", 0.0)))
        cursor += max_end + gap_between_scenes

    if not combined:
        return None, None

    out_dir.mkdir(parents=True, exist_ok=True)
    srt_path = out_dir / f"{slug}.en.srt"
    vtt_path = out_dir / f"{slug}.en.vtt"
    srt_path.write_text(segments_to_srt(combined), encoding="utf-8")
    vtt_path.write_text(segments_to_vtt(combined), encoding="utf-8")
    return srt_path, vtt_path


# ── Chapter assembly ───────────────────────────────────────────────────


def build_chapters(
    scenes: list[SceneAsset],
    gap_between_scenes: float = 0.5,
) -> list[SceneChapter]:
    """Convert a list of ``SceneAsset`` into ordered chapter records.

    A chapter's start is the running audio cursor; its end is start + the
    scene's audio duration. Empty scenes are skipped so we never produce
    a zero-length chapter.
    """
    chapters: list[SceneChapter] = []
    cursor = 0.0
    for sc in scenes:
        dur = max(0.0, sc.duration)
        if dur <= 0:
            continue
        chapters.append(SceneChapter.from_scene(
            {"title": sc.title, "scene": sc.scene_key},
            start=cursor,
            end=cursor + dur,
        ))
        cursor += dur + gap_between_scenes
    return chapters


# ── Background audio mix ──────────────────────────────────────────────


def _resolve_background_track(story_dir: Path, manifest: dict) -> Optional[Path]:
    """Pick the manifest's named track if it exists, otherwise auto-select."""
    bg_name = manifest.get("background_audio")
    if bg_name:
        direct = BACKGROUND_DIR / bg_name
        if direct.exists():
            return direct
    tone = manifest.get("tone") or ""
    style = (manifest.get("tags") or [""])[0]
    track = select_background_track(tone=tone, style=style)
    return Path(track.path) if track else None


def mix_audio_into_video(
    video_path: Path,
    narration_path: Path,
    background_path: Optional[Path],
    background_volume: float = DEFAULT_BACKGROUND_VOLUME,
    background_muted: bool = False,
    out_path: Path = None,
) -> Path:
    """Mix narration + (optional looped background) into the given video.

    Returns the path of the muxed video. Uses the same H.264/AAC settings as
    ``render_video.py`` so the two pipelines produce interchangeable output.

    The background is looped to match the narration's duration via the
    ``-stream_loop -1`` input option, then volume is reduced with ``-af
    volume=...``. If ``background_muted`` is True the background is omitted
    entirely (cleaner than zeroing it).
    """
    if out_path is None:
        out_path = video_path.with_name(video_path.stem + ".with_audio.mp4")

    narration_dur = _read_audio_duration(narration_path)
    if narration_dur <= 0:
        raise ValueError(f"Could not determine narration duration: {narration_path}")

    inputs: list[str] = ["-y", "-i", str(video_path), "-i", str(narration_path)]
    filter_complex_parts: list[str] = []
    map_args: list[str] = ["-map", "0:v:0", "-map", "1:a:0"]

    if background_path and background_path.exists() and not background_muted and background_volume > 0:
        # Loop background infinitely so the amix can take what it needs and
        # the atrim keeps only narration_dur seconds of the mix.
        inputs.extend(["-stream_loop", "-1", "-i", str(background_path)])
        # Background volume via the `volume` filter (clamp to a safe range).
        vol = max(0.0, min(1.0, float(background_volume)))
        filter_complex_parts.append(
            f"[2:a]volume={vol:.4f},aresample=44100[bg]"
        )
        # Mix narration and background. The narration gets weight 1, the
        # background weight 1 too — we already scaled its volume above so
        # the mix produces the right final loudness.
        filter_complex_parts.append(
            "[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        map_args = ["-map", "0:v:0", "-map", "[aout]"]

    if filter_complex_parts:
        filter_complex = ";\n".join(filter_complex_parts)
    else:
        filter_complex = None

    cmd: list[str] = [
        "ffmpeg", *inputs,
        "-t", f"{narration_dur:.3f}",
    ]
    if filter_complex:
        cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(map_args)
    cmd.extend([
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-shortest",
        "-movflags", "+faststart",
        str(out_path),
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Re-raise with the tail of stderr so the caller can log/display it.
        tail = (result.stderr or "")[-500:]
        raise RuntimeError(f"ffmpeg audio mix failed: {tail}")

    return out_path


# ── Plex library destination copy ─────────────────────────────────────

# Plex's official Movies library layout is:
#   <Library>/Movies/<Title> (<Year>)/<Title> (<Year>).mp4
# The folder name is the source of truth for both the title and the year
# that Plex shows in the UI. We follow that convention exactly so the
# library scanner picks up the new file with no metadata sidecars.


def _sanitize_for_plex(value: str, fallback: str = "Untitled") -> str:
    """Make a string safe to use as a Windows folder / file name.

    Strips the characters Windows + Plex reject, collapses whitespace,
    drops trailing dots/spaces (which Windows would refuse), and falls
    back to ``fallback`` if the result is empty.
    """
    cleaned = _PLEX_INVALID_CHARS.sub(" ", value or "").strip()
    cleaned = _PLEX_COLLAPSE_WS.sub(" ", cleaned)
    cleaned = _PLEX_TRAILING_DOTS.sub("", cleaned).rstrip()
    if not cleaned or not any(c.isalnum() for c in cleaned):
        return fallback
    # Plex folders max out around 255 chars on most filesystems; cap well
    # below that so the year suffix and any extension still fit.
    return cleaned[:200]


def _resolve_year(manifest: dict) -> int:
    """Best-effort story year. Manifest, then manifest's created_at, then now."""
    raw = manifest.get("year")
    if isinstance(raw, int) and 1900 < raw < 3000:
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        y = int(raw.strip())
        if 1900 < y < 3000:
            return y
    created = manifest.get("created_at")
    if isinstance(created, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(float(created)).year
        except (OSError, ValueError, OverflowError):
            pass
    return datetime.datetime.now().year


def _plex_movie_folder_name(manifest: dict) -> str:
    """Return ``<Title> (<Year>)`` for the Movies subfolder."""
    title = _sanitize_for_plex(
        manifest.get("title") or manifest.get("id") or "Untitled",
        fallback="Untitled",
    )
    year = _resolve_year(manifest)
    return f"{title} ({year})"


def _plex_file_stem(manifest: dict, slug: str) -> str:
    """Return the on-disk file stem (without extension) used in the Plex folder.

    Matches the folder name so Plex sees ``Title (Year).mp4`` /
    ``Title (Year).en.srt`` etc., which is what the scanner expects.
    """
    return _plex_movie_folder_name(manifest)


def _copy_to_plex_destination(
    plex_dir: Path,
    manifest: dict,
    slug: str,
    *,
    destination_root: str,
) -> dict:
    """Copy the finished package into the user's Plex library.

    Creates ``<destination_root>/Movies/<Title> (<Year>)/`` if missing and
    copies the MP4 + subtitle + poster files into it. Raises on any IO
    failure (caller decides whether to fail the whole export).

    Returns a dict with ``root`` (the library root as the caller passed
    it), ``dir`` (the created folder), and ``files`` (list of names
    actually copied).
    """
    root = Path(destination_root).expanduser()
    if not root.exists():
        # Best-effort create — Plex users sometimes forget to mkdir
        # the root the first time.
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise RuntimeError(
                f"Plex destination {root} does not exist and could not be created: {e}"
            ) from e

    folder_name = _plex_movie_folder_name(manifest)
    target_dir = root / "Movies" / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    file_stem = _plex_file_stem(manifest, slug)

    # What to copy: the final MP4, the .en.srt / .en.vtt sidecars, the
    # poster (any extension), and the chapters file. We skip the
    # chapters.ffmeta by default — Plex reads chapters from inside the
    # MP4's ffmpeg metadata, not from a sidecar — but copy it too so
    # the user can re-mux without losing the data.
    candidates: list[tuple[Path, str]] = []
    mp4 = plex_dir / f"{slug}.mp4"
    if mp4.exists():
        candidates.append((mp4, f"{file_stem}.mp4"))
    srt = plex_dir / f"{slug}.en.srt"
    if srt.exists():
        candidates.append((srt, f"{file_stem}.en.srt"))
    vtt = plex_dir / f"{slug}.en.vtt"
    if vtt.exists():
        candidates.append((vtt, f"{file_stem}.en.vtt"))
    chapters = plex_dir / "chapters.ffmeta"
    if chapters.exists():
        candidates.append((chapters, "chapters.ffmeta"))
    # Poster can be png/jpg/jpeg/svg — keep the same extension.
    for poster_path in plex_dir.glob(f"{slug}-poster.*"):
        suffix = poster_path.suffix.lower()
        candidates.append((poster_path, f"{file_stem}-poster{suffix}"))

    copied: list[str] = []
    for src, dst_name in candidates:
        dst = target_dir / dst_name
        shutil.copy2(src, dst)
        copied.append(dst_name)

    return {
        "root": str(root).replace("\\", "/"),
        "dir": str(target_dir).replace("\\", "/"),
        "files": copied,
    }


# ── Top-level export ──────────────────────────────────────────────────


@dataclass
class PlexExportResult:
    story_id: str
    plex_dir: Path
    mp4: Optional[Path] = None
    srt: Optional[Path] = None
    vtt: Optional[Path] = None
    poster: Optional[Path] = None
    chapters_file: Optional[Path] = None
    background_used: Optional[str] = None
    background_volume: float = DEFAULT_BACKGROUND_VOLUME
    background_muted: bool = False
    duration_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)
    # Fields populated by the optional "copy to Plex library" step.
    destination_root: Optional[str] = None
    destination_dir: Optional[str] = None
    destination_files: list[str] = field(default_factory=list)
    destination_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "story_id": self.story_id,
            "plex_dir": str(self.plex_dir).replace("\\", "/"),
            "mp4": str(self.mp4).replace("\\", "/") if self.mp4 else None,
            "srt": str(self.srt).replace("\\", "/") if self.srt else None,
            "vtt": str(self.vtt).replace("\\", "/") if self.vtt else None,
            "poster": str(self.poster).replace("\\", "/") if self.poster else None,
            "chapters_file": str(self.chapters_file).replace("\\", "/") if self.chapters_file else None,
            "background_used": self.background_used,
            "background_volume": self.background_volume,
            "background_muted": self.background_muted,
            "duration_seconds": self.duration_seconds,
            "notes": self.notes,
            "destination_root": self.destination_root,
            "destination_dir": self.destination_dir,
            "destination_files": self.destination_files,
            "destination_error": self.destination_error,
        }


def export_plex_package(
    story_id: str,
    *,
    background_volume: Optional[float] = None,
    background_muted: Optional[bool] = None,
    background_audio: Optional[str] = None,
    destination: Optional[str] = None,
    scenes: Optional[list[SceneAsset]] = None,
    progress_callback=None,
) -> PlexExportResult:
    """Render a Plex-ready MP4 + sidecar subtitles for a story.

    The function is callable from both the API endpoint and the CLI. It
    discovers scenes on disk (or accepts a pre-built list), then:

    1. discovers scenes,
    2. writes combined SRT + VTT sidecars,
    3. builds FFmpeg chapter metadata,
    4. concatenates per-scene MP4s (using ``render_video.py``'s concat,
       copied to a working file),
    5. mixes narration + (looped) background into the final MP4 with
       embedded chapters and ``+faststart``,
    6. copies the poster image next to the MP4,
    7. copies everything into ``<story-dir>/final/plex/``,
    8. if ``destination`` (or env ``FANTASEE_PLEX_DEST``) is set, also
       copies the package into ``<destination>/Movies/<Title> (<Year>)/``
       so it can be picked up by a Plex library scan.

    ``progress_callback`` is an optional callable taking ``(stage, message,
    progress)`` where ``progress`` is in [0, 1]. The stages are:
    ``"discover"``, ``"subtitles"``, ``"chapters"``, ``"audio_mix"``,
    ``"finalize"``, ``"plex_copy"``.
    """
    story_dir = existing_story_dir(story_id)
    if not story_dir.is_dir():
        raise FileNotFoundError(f"Story directory not found: {story_dir}")
    layout = ensure_story_layout(story_dir)

    manifest_path = story_dir / f"{story_id}.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            manifest = {}

    slug = story_id
    result = PlexExportResult(
        story_id=story_id,
        plex_dir=layout["final"] / "plex",
        background_volume=(
            background_volume
            if background_volume is not None
            else float(manifest.get("background_volume", DEFAULT_BACKGROUND_VOLUME))
        ),
        background_muted=(
            background_muted
            if background_muted is not None
            else bool(manifest.get("background_muted", False))
        ),
    )

    # Resolve the Plex destination root once. Per-call arg wins, then env,
    # then the default. The "no destination" case is `None`, in which
    # step 8 below is a no-op.
    plex_destination = (
        destination
        or os.environ.get("FANTASEE_PLEX_DEST")
        or DEFAULT_PLEX_DEST
    )

    def _progress(stage: str, msg: str, pct: float) -> None:
        if progress_callback:
            try:
                progress_callback(stage, msg, pct)
            except Exception:
                pass

    # ── 1. Discover scenes ──────────────────────────────────────────
    _progress("discover", "Discovering scenes...", 0.05)
    discovered = scenes if scenes is not None else _discover_scenes(story_dir, slug)
    if not discovered:
        raise RuntimeError("No scenes found for story. Generate images and TTS first.")
    result.notes.append(f"discovered {len(discovered)} scene(s)")

    # ── 2. Write combined SRT + VTT sidecars ────────────────────────
    _progress("subtitles", "Writing SRT and VTT sidecars...", 0.20)
    srt_path, vtt_path = write_combined_subtitles(discovered, slug, result.plex_dir)
    if srt_path:
        result.srt = srt_path
        result.vtt = vtt_path
    else:
        result.notes.append("no subtitle segments found; skipped SRT/VTT")

    # ── 3. Build chapter metadata ──────────────────────────────────
    _progress("chapters", "Generating chapter metadata...", 0.35)
    chapters = build_chapters(discovered)
    if not chapters:
        raise RuntimeError("No chapters produced (every scene is empty or missing audio).")
    chapters_file = result.plex_dir / "chapters.ffmeta"
    chapters_file.parent.mkdir(parents=True, exist_ok=True)
    chapters_file.write_text(chapters_to_ffmetadata(chapters), encoding="utf-8")
    result.chapters_file = chapters_file

    # ── 4. Concatenate per-scene MP4s ───────────────────────────────
    _progress("audio_mix", "Concatenating per-scene MP4s...", 0.50)
    scene_videos = _discover_scene_videos(story_dir, slug, discovered)
    if not scene_videos:
        raise RuntimeError(
            "No per-scene MP4 files found. Run `python render_video.py <story-id>` first."
        )
    concat_path = result.plex_dir / "_concat.mp4"
    concat_path.parent.mkdir(parents=True, exist_ok=True)
    _concat_videos(scene_videos, concat_path)

    # ── 5. Concatenate narration into a single audio track ──────────
    narration_path = result.plex_dir / "_narration.wav"
    narration_dur = _concat_narration(discovered, narration_path)
    if narration_dur <= 0:
        raise RuntimeError("Narration concat produced 0 seconds of audio.")
    result.duration_seconds = narration_dur

    # ── 6. Mix narration + background, add chapters, faststart ──────
    _progress("audio_mix", "Mixing narration + background audio...", 0.70)
    bg_name = background_audio or manifest.get("background_audio")
    if bg_name:
        bg_path = BACKGROUND_DIR / bg_name
        if not bg_path.exists():
            result.notes.append(f"background track '{bg_name}' not found in Background/")
            bg_path = None
    else:
        bg_path = _resolve_background_track(story_dir, manifest)
        if bg_path:
            bg_name = bg_path.name
    result.background_used = bg_name

    final_mp4 = result.plex_dir / f"{slug}.mp4"
    with_chapters_path = result.plex_dir / "_with_chapters.mp4"
    _mix_and_chapter(
        concat_path,
        narration_path,
        bg_path,
        background_volume=result.background_volume,
        background_muted=result.background_muted,
        chapters_file=chapters_file,
        out_path=with_chapters_path,
    )
    # Final rename: ensure the .mp4 file uses the user-facing name.
    if with_chapters_path.exists():
        if final_mp4.exists():
            final_mp4.unlink()
        with_chapters_path.rename(final_mp4)
        result.mp4 = final_mp4
    else:
        raise RuntimeError("Final MP4 was not produced.")

    # ── 7. Copy poster image next to the video ─────────────────────
    _progress("finalize", "Copying poster image...", 0.90)
    poster = _copy_poster(story_dir, slug, result.plex_dir)
    result.poster = poster

    # ── 8. Clean up working files ──────────────────────────────────
    for tmp_name in ("_concat.mp4", "_narration.wav"):
        tmp = result.plex_dir / tmp_name
        if tmp.exists():
            tmp.unlink()

    # ── 9. Copy to Plex library destination (best-effort) ──────────
    if plex_destination:
        _progress("plex_copy", f"Copying to {plex_destination}...", 0.95)
        try:
            copied = _copy_to_plex_destination(
                result.plex_dir, manifest, slug,
                destination_root=plex_destination,
            )
            result.destination_root = copied["root"]
            result.destination_dir = copied["dir"]
            result.destination_files = copied["files"]
        except Exception as e:
            # Don't fail the whole export if the Plex copy fails (e.g.
            # the D: drive is offline). Surface it in the result so the
            # UI can show a warning.
            result.destination_error = str(e)
            result.notes.append(f"Plex copy failed: {e}")

    _progress("finalize", "Plex export complete.", 1.0)
    return result


# ── Internal helpers used by export_plex_package ──────────────────────


def _discover_scene_videos(
    story_dir: Path, slug: str, scenes: list[SceneAsset]
) -> list[Path]:
    """Find the rendered per-scene MP4 (from ``render_video.py``)."""
    found: list[Path] = []
    for sc in scenes:
        candidates = [
            story_dir / f"{slug}_s{sc.scene_key}.mp4",
            story_dir / f"{slug}_s{int(sc.scene_key):02d}.mp4" if sc.scene_key.isdigit() else None,
        ]
        for c in candidates:
            if c and c.exists():
                found.append(c)
                break
    return found


def _concat_videos(scene_videos: list[Path], out_path: Path) -> None:
    """Concatenate MP4 clips with ``-c copy`` (no re-encode) for speed."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_path.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in scene_videos) + "\n",
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy", "-movflags", "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"Concat failed: {(result.stderr or '')[-500:]}")


def _concat_narration(scenes: list[SceneAsset], out_path: Path) -> float:
    """Concatenate per-scene TTS audio with a 0.5s gap between scenes.

    Returns the total duration in seconds.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_path.with_suffix(".txt")
    # 0.5s silence between scenes
    silence = out_path.with_name("_silence.wav")
    _make_silence(silence, 0.5)

    lines: list[str] = []
    last_added = False
    for i, sc in enumerate(scenes):
        if not sc.audio or not sc.audio.exists():
            continue
        lines.append(f"file '{sc.audio.as_posix()}'")
        # Only add silence between two consecutive scenes that both have audio
        if last_added and i < len(scenes) - 1:
            lines.append(f"file '{silence.as_posix()}'")
        last_added = True
    if not lines:
        return 0.0
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)
    silence.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"Narration concat failed: {(result.stderr or '')[-500:]}")
    return _read_audio_duration(out_path)


def _make_silence(out_path: Path, seconds: float) -> None:
    """Write a short silence WAV via ffmpeg's lavfi source."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=mono:sample_rate=44100",
        "-t", f"{seconds:.3f}",
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Could not create silence: {(result.stderr or '')[-300:]}")


def _mix_and_chapter(
    video_path: Path,
    narration_path: Path,
    background_path: Optional[Path],
    background_volume: float,
    background_muted: bool,
    chapters_file: Path,
    out_path: Path,
) -> None:
    """Run the final FFmpeg pass: mix audio, embed chapters, faststart."""
    inputs: list[str] = ["-y", "-i", str(video_path), "-i", str(narration_path)]
    filter_parts: list[str] = []

    if background_path and background_path.exists() and not background_muted and background_volume > 0:
        vol = max(0.0, min(1.0, float(background_volume)))
        inputs.extend(["-stream_loop", "-1", "-i", str(background_path)])
        filter_parts.append(f"[2:a]volume={vol:.4f},aresample=44100[bg]")
        filter_parts.append("[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]")
        audio_map = ["-map", "0:v:0", "-map", "[aout]"]
    else:
        audio_map = ["-map", "0:v:0", "-map", "1:a:0"]

    narration_dur = _read_audio_duration(narration_path)
    # Chapters file input index: 2 when no background, 3 when background is present
    chapters_input_idx = 3 if (background_path and background_path.exists() and not background_muted and background_volume > 0) else 2
    cmd: list[str] = [
        "ffmpeg", *inputs,
        "-i", str(chapters_file),
        "-map_metadata", str(chapters_input_idx),
        "-t", f"{narration_dur:.3f}",
    ]
    if filter_parts:
        cmd.extend(["-filter_complex", ";\n".join(filter_parts)])
    cmd.extend(audio_map)
    cmd.extend([
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-shortest",
        "-movflags", "+faststart",
        str(out_path),
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Final mux failed: {(result.stderr or '')[-600:]}")


def _copy_poster(story_dir: Path, slug: str, plex_dir: Path) -> Optional[Path]:
    """Copy a poster/title image next to the final MP4.

    Prefers the image-backed title PNG, falls back to the legacy SVG, then
    to the first scene image.
    """
    candidates = [
        story_dir / "assets" / "title" / "title_slide.png",
        story_dir / "assets" / "title" / "title_slide.svg",
        story_dir / f"{slug}.json",  # used below for hero_image / first scene fallback
    ]
    poster: Optional[Path] = None
    for c in candidates[:2]:
        if c.exists():
            poster = c
            break
    if not poster:
        # Last-resort: first scene image
        for c in sorted(story_dir.glob(f"{slug}_s*_00001_.png")):
            poster = c
            break
    if not poster:
        return None
    suffix = poster.suffix.lower()
    target = plex_dir / f"{slug}-poster{suffix}"
    shutil.copy2(poster, target)
    return target


# ── CLI ────────────────────────────────────────────────────────────────


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Render a Plex-ready MP4 + sidecars for a story")
    parser.add_argument("story_id", help="Story ID (folder name in stories/)")
    parser.add_argument("--background-volume", type=float, default=None,
                        help="Override background volume (0-1)")
    parser.add_argument("--background-muted", action="store_true",
                        help="Skip the background track entirely")
    parser.add_argument("--background-audio", default=None,
                        help="Override the background track filename")
    parser.add_argument("--json", action="store_true", help="Output JSON summary")
    args = parser.parse_args()

    def _cb(stage: str, msg: str, pct: float) -> None:
        print(f"[{stage:<10}] {pct*100:5.1f}%  {msg}", flush=True)

    result = export_plex_package(
        args.story_id,
        background_volume=args.background_volume,
        background_muted=args.background_muted,
        background_audio=args.background_audio,
        progress_callback=_cb,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("\nPlex package ready:")
        for k, v in result.to_dict().items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
