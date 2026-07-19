"""Shared helpers for the test suite.

The tests intentionally avoid pytest to keep the test infra a single
stdlib import — this lets CI run them with no extra install step.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


# Make the project root importable when tests are run from anywhere
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def has_pillow() -> bool:
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


def write_silent_wav(path: Path, seconds: float, rate: int = 22050) -> None:
    """Write a deterministic mono silent WAV for smoke fixtures."""
    samples = int(seconds * rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * samples)


def write_test_png(path: Path, color: tuple[int, int, int] = (32, 64, 128)) -> None:
    """Write a deterministic tiny PNG for smoke fixtures."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise unittest.SkipTest("Pillow is required to build the smoke test fixtures") from exc

    Image.new("RGB", (64, 64), color).save(path, "PNG")


def build_plex_smoke_story(story_dir: Path, slug: str) -> None:
    """Create the synthetic two-scene Plex smoke story fixture."""
    for scene_key, label in (("01", "The Opening"), ("02", "The Reveal")):
        write_silent_wav(story_dir / f"tts_{slug}_s{scene_key}.wav", 1.0)
        write_test_png(
            story_dir / f"{slug}_s{scene_key}_00001_.png",
            color=(32 + int(scene_key) * 32, 64, 128),
        )
        subs = [
            {"text": f"Scene {scene_key} line one.", "start": 0.0, "end": 0.5},
            {"text": f"Scene {scene_key} line two.", "start": 0.5, "end": 1.0},
        ]
        (story_dir / f"subs_{slug}_s{scene_key}.json").write_text(
            json.dumps(subs), encoding="utf-8"
        )

    manifest = {
        "id": slug,
        "title": "Test Story",
        "subtitle": "A test",
        "description": "Synthetic story for testing.",
        "tags": ["fantasy", "dramatic"],
        "tone": "dramatic",
        "background_audio": None,
        "background_volume": 0.05,
        "background_muted": False,
        "scenes": [
            {
                "scene": "01",
                "title": "The Opening",
                "narration": "The first line.",
                "narration_text": "The first line.",
                "audio_filename": f"tts_{slug}_s01.wav",
                "audio_duration": 1.0,
                "image_filenames": [f"{slug}_s01_00001_.png"],
            },
            {
                "scene": "02",
                "title": "The Reveal",
                "narration": "The second line.",
                "narration_text": "The second line.",
                "audio_filename": f"tts_{slug}_s02.wav",
                "audio_duration": 1.0,
                "image_filenames": [f"{slug}_s02_00001_.png"],
            },
        ],
    }
    (story_dir / f"{slug}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


@contextmanager
def temp_dir(prefix: str = "fantasee_test_") -> Iterator[Path]:
    """Yield a temporary directory that is cleaned up on exit."""
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)
