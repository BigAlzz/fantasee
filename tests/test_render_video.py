"""Regression tests for visual image transitions in rendered scenes."""

from __future__ import annotations

import io
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from render_video import concatenate_scenes, concatenate_vtts, render_scene
from render_video import FPS


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg is required for the renderer regression test",
)


def test_motion_renderer_uses_a_smooth_default_frame_clock() -> None:
    assert FPS >= 60


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


def test_concatenate_scenes_uses_a_scene_fade_transition(tmp_path: Path) -> None:
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    for output, color in ((first, "red"), (second, "blue")):
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=10",
                "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "1.0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                str(output),
            ],
            capture_output=True,
            check=True,
        )

    rendered = concatenate_scenes([first, second], "scene-fade", tmp_path)

    assert rendered is not None
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(rendered)],
        capture_output=True,
        text=True,
        check=True,
    )
    # A crossfade overlaps the scene boundary instead of hard-cutting at 2s.
    assert float(probe.stdout.strip()) < 1.8


def test_concatenate_vtts_uses_the_scene_transition_clock(tmp_path: Path) -> None:
    first = tmp_path / "first.vtt"
    second = tmp_path / "second.vtt"
    first.write_text("WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nFirst\n", encoding="utf-8")
    second.write_text("WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nSecond\n", encoding="utf-8")

    output = concatenate_vtts(
        [first, second],
        "subtitle-fade",
        tmp_path,
        scene_durations=[1.0, 1.0],
    )

    assert output is not None
    content = output.read_text(encoding="utf-8")
    assert "00:00:00.200 --> 00:00:01.200" in content
