"""Small, shared validity checks for generated story artwork."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from PIL import Image, ImageStat, UnidentifiedImageError


def requested_images_per_scene(manifest: Mapping) -> int:
    """Return the saved target, inferring it for manifests created before it was saved."""
    explicit = manifest.get("images_per_scene")
    try:
        if explicit is not None and int(explicit) > 0:
            return min(int(explicit), 50)
    except (TypeError, ValueError):
        pass

    listed_counts = [
        len([name for name in (scene.get("image_filenames") or []) if name])
        for scene in (manifest.get("scenes") or [])
        if isinstance(scene, Mapping)
    ]
    return min(max(1, max(listed_counts, default=1)), 50)


def inspect_story_image(path: Path | str) -> tuple[bool, str]:
    """Reject missing, unreadable, empty, and visually blank image outputs."""
    image_path = Path(path)
    try:
        if not image_path.is_file():
            return False, "Image file is missing"
        if image_path.stat().st_size <= 0:
            return False, "Image file is empty"

        with Image.open(image_path) as source:
            source.verify()
        with Image.open(image_path) as source:
            sample = source.convert("RGB")
            sample.thumbnail((64, 64))
            extrema = sample.getextrema()
            stats = ImageStat.Stat(sample)

        darkest = min(low for low, _ in extrema)
        brightest = max(high for _, high in extrema)
        channel_span = max(high - low for low, high in extrema)
        max_variance = max(stats.var)

        if brightest <= 8:
            return False, "Generated image is blank black"
        if darkest >= 247 and channel_span <= 4:
            return False, "Generated image is blank white"
        if channel_span <= 2 and max_variance <= 1.0:
            return False, "Generated image is visually blank"
        return True, ""
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        return False, f"Image is unreadable: {exc}"


def is_usable_story_image(path: Path | str) -> bool:
    return inspect_story_image(path)[0]
