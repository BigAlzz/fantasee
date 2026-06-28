"""Background music selection, metadata, and looping helpers.

Background tracks live in ``Background/`` (sibling of the project root). The
selector picks a track based on the story's tone and visual style so the
music mood matches the narration pacing and the visual atmosphere.

The track list is also a static ``BACKGROUND_TRACKS`` table — the first hit
wins, so adding a new track to ``Background/`` does not require a code change
*unless* the filename does not contain a recognizable tone tag.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional


# ── Config ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent
BACKGROUND_DIR = PROJECT_ROOT / "Background"

# Default background volume for new stories. Plex users expect the music to
# sit well under the narration — 5% is a good default that's audible but
# never competes with the voiceover.
DEFAULT_BACKGROUND_VOLUME = 0.05

# Tone → tag order. The first tag found in a filename wins. Tags are
# matched case-insensitively against substrings of the filename stem.
TONE_TAGS: list[tuple[str, tuple[str, ...]]] = [
    # (tone, (matching substrings))
    ("dark",            ("cinematic-atmosphere",)),
    ("noir",            ("cinematic-atmosphere",)),
    ("epic",            ("cinematic-atmosphere",)),
    ("epic-fantasy",    ("cinematic-atmosphere",)),
    ("mysterious",      ("cinematic-atmosphere",)),
    ("suspenseful",     ("cinematic-atmosphere",)),
    ("manhwa",          ("cinematic-atmosphere",)),
    ("tense",           ("cinematic-atmosphere",)),
    ("gritty",          ("cinematic-atmosphere",)),
    ("hopeful",         ("light-and-sweet",)),
    ("romantic",        ("light-and-reflective", "light-and-sweet")),
    ("melancholic",     ("light-and-reflective",)),
    ("lyrical",         ("light-and-reflective", "light-and-sweet")),
    ("emotional",       ("light-and-reflective", "light-and-sweet")),
    ("calm",            ("light-and-reflective", "light-and-sweet")),
    ("whisper",         ("light-and-reflective",)),
    ("lighthearted",    ("light-and-sweet",)),
    ("whimsical",       ("light-and-sweet",)),
    ("comedic",         ("light-and-sweet",)),
    ("excited",         ("light-and-sweet",)),
    ("heroic",          ("light-and-reflective",)),
    ("dramatic",        ("cinematic-atmosphere",)),
    ("normal",          ("light-and-reflective",)),
]

# Acceptable audio extensions.
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


# ── Track dataclass ─────────────────────────────────────────────────────


@dataclass
class BackgroundTrack:
    """Metadata for a single background track."""

    filename: str
    path: str
    duration_seconds: float
    tags: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


# ── Public API ──────────────────────────────────────────────────────────


def list_background_tracks(background_dir: Path = BACKGROUND_DIR) -> list[Path]:
    """Return every audio file in ``background_dir`` (sorted, stable order)."""
    if not background_dir.is_dir():
        return []
    tracks = [
        p for p in background_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _AUDIO_EXTS
    ]
    return sorted(tracks, key=lambda p: p.name)


def _tags_for_filename(stem: str) -> list[str]:
    """Pull human-readable tags out of a filename stem."""
    tags: list[str] = []
    lower = stem.lower()
    if "cinematic" in lower:
        tags.append("cinematic")
    if "atmosphere" in lower or "score" in lower:
        tags.append("atmosphere")
    if "no-melody" in lower or "no_melody" in lower:
        tags.append("no-melody")
    if "piano" in lower:
        tags.append("piano")
    if "orchestra" in lower:
        tags.append("orchestra")
    if "reflective" in lower:
        tags.append("reflective")
    if "light" in lower:
        tags.append("light")
    if "sweet" in lower:
        tags.append("sweet")
    return tags


def _match_score(track: BackgroundTrack, tone: str) -> int:
    """Higher score = better match. 0 = no match.

    ``track.filename`` is the clean basename without the directory, so
    it never picks up random substrings from a parent folder name.
    """
    stem = track.filename.lower()
    for candidate_tone, tag_substrings in TONE_TAGS:
        if candidate_tone != tone.lower():
            continue
        for tag in tag_substrings:
            if tag in stem:
                return 10
    return 0


def _read_duration(audio_path: Path) -> float:
    """Return duration in seconds using ffprobe (preferred) or mutagen.

    Returns 0.0 if neither tool can read the file.
    """
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

    try:
        from mutagen import File as MutagenFile
        mf = MutagenFile(str(audio_path))
        if mf is not None and getattr(mf.info, "length", None):
            return float(mf.info.length)
    except Exception:
        pass

    return 0.0


def build_track_index(background_dir: Path = BACKGROUND_DIR) -> list[BackgroundTrack]:
    """Build a stable index of background tracks with metadata.

    Cached internally per-directory so repeated lookups are cheap.
    Cache is invalidated when the directory modification time changes.
    """
    cache_attr = f"_index_cache_{background_dir}"
    mtime_attr = f"_index_mtime_{background_dir}"
    
    # Check if directory has been modified since last cache
    try:
        current_mtime = background_dir.stat().st_mtime
    except OSError:
        current_mtime = 0.0
    
    cached_mtime = getattr(build_track_index, mtime_attr, 0.0)
    cached = getattr(build_track_index, cache_attr, None)
    
    if cached is not None and current_mtime == cached_mtime:
        return cached

    tracks: list[BackgroundTrack] = []
    for p in list_background_tracks(background_dir):
        tracks.append(BackgroundTrack(
            filename=p.name,
            path=str(p),
            duration_seconds=_read_duration(p),
            tags=_tags_for_filename(p.stem),
        ))
    setattr(build_track_index, cache_attr, tracks)
    setattr(build_track_index, mtime_attr, current_mtime)
    return tracks


def select_background_track(
    tone: str = "dramatic",
    style: str = "",
    background_dir: Path = BACKGROUND_DIR,
    tracks: Optional[Iterable[BackgroundTrack]] = None,
) -> Optional[BackgroundTrack]:
    """Pick the best background track for a story.

    Selection rules:
    1. Score each track against the tone; highest score wins.
    2. If no tone-based match, fall back to the first track with the most
       "neutral" mood (``light-and-reflective``), then to any track.
    3. Style keyword is reserved for future use — currently only tone
       drives selection.
    """
    index = list(tracks) if tracks is not None else build_track_index(background_dir)
    if not index:
        return None

    scored = sorted(
        ((_match_score(t, tone), idx) for idx, t in enumerate(index)),
        key=lambda pair: (-pair[0], pair[1]),
    )
    if scored and scored[0][0] > 0:
        return index[scored[0][1]]

    # Tone didn't match. Try neutral-fallback keywords.
    for neutral in ("light-and-reflective", "light-and-sweet", "cinematic-atmosphere"):
        for t in index:
            if neutral in t.filename.lower():
                return t

    return index[0]


def _path_from_track(track: BackgroundTrack) -> Path:
    return Path(track.path)


def track_filename_for(tone: str, style: str = "") -> Optional[str]:
    """Return just the filename of the best match (or None)."""
    track = select_background_track(tone=tone, style=style)
    return track.filename if track else None


def ensure_chapter_titles(scenes: list[dict]) -> list[dict]:
    """Return a copy of ``scenes`` with every scene guaranteed to have a title.

    Used by the chapter generator so a missing title doesn't break FFmpeg
    chapter metadata (which rejects empty names).
    """
    fixed = []
    for i, s in enumerate(scenes):
        title = (s.get("title") or "").strip()
        if not title:
            title = f"Scene {s.get('scene') or i + 1}"
        clone = dict(s)
        clone["title"] = title
        fixed.append(clone)
    return fixed


def background_audio_payload(
    tone: str = "dramatic",
    style: str = "",
    background_dir: Path = BACKGROUND_DIR,
) -> dict:
    """Return a payload suitable for storing on the story manifest.

    Includes the picked track filename (or ``None``) and the defaults
    expected by the player. Volume and muted defaults are always present
    so the frontend has stable keys to read.
    """
    track = select_background_track(tone=tone, style=style, background_dir=background_dir)
    return {
        "background_audio": track.filename if track else None,
        "background_volume": DEFAULT_BACKGROUND_VOLUME,
        "background_muted": False,
        "background_track_duration": track.duration_seconds if track else 0.0,
        "background_track_tags": track.tags if track else [],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="List & select background tracks")
    parser.add_argument("--list", action="store_true", help="List all discovered tracks")
    parser.add_argument("--tone", default="dramatic", help="Story tone to match")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if args.list:
        for t in build_track_index():
            print(f"  {t.filename}  ({t.duration_seconds:.1f}s)  tags={t.tags}")
    else:
        payload = background_audio_payload(tone=args.tone)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Selected background: {payload['background_audio']}")
            print(f"  duration: {payload['background_track_duration']:.1f}s")
            print(f"  default volume: {payload['background_volume']}")
