"""Regression tests for visual image transitions in rendered scenes."""

from __future__ import annotations

import io
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from render_video import render_scene


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg is required for the renderer regression test",
)


def _write_wav(path: Path, seconds: float = 2.0) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * int(8000 * seconds))


def _frame_mean(path: Path, seconds: float) -> tuple[float, float, float]:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", str(seconds), "-i", str(path),
            "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    from PIL import Image

    with Image.open(io.BytesIO(result.stdout)) as image:
        sample = image.convert("RGB").resize((1, 1))
        return tuple(float(value) for value in sample.getpixel((0, 0)))


def test_render_scene_encodes_each_input_image(tmp_path: Path) -> None:
    from PIL import Image

    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (320, 180), (220, 20, 20)).save(first)
    Image.new("RGB", (320, 180), (20, 20, 220)).save(second)
    audio = tmp_path / "audio.wav"
    _write_wav(audio)

    rendered = render_scene(
        tmp_path,
        "transition-test",
        {
            "scene_key": "01",
            "images": [first, second],
            "audio": audio,
            "subs": None,
            "duration": 2.0,
            "image_durations": None,
        },
        tmp_path,
        320,
        180,
        10,
        30,
    )

    assert rendered is not None
    early = _frame_mean(rendered, 0.2)
    late = _frame_mean(rendered, 1.5)
    assert early[0] > early[2] * 2
    assert late[2] > late[0] * 2
