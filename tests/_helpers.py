"""Shared helpers for the test suite.

The tests intentionally avoid pytest to keep the test infra a single
stdlib import — this lets CI run them with no extra install step.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
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


@contextmanager
def temp_dir(prefix: str = "fantasee_test_") -> Iterator[Path]:
    """Yield a temporary directory that is cleaned up on exit."""
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)
