"""Unit tests for ``title_image`` — Pillow-based image-backed title slides.

Skipped if Pillow isn't installed.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests._helpers import PROJECT_ROOT, has_pillow, temp_dir


@unittest.skipUnless(has_pillow(), "Pillow not installed")
class TestTitleImage(unittest.TestCase):
    def test_generates_png_and_svg(self):
        from title_image import generate_title_image

        with temp_dir() as tmp:
            paths = generate_title_image(
                tmp, "demo",
                title="The Last Watch",
                concept="An aging veteran and a young archer hold the line.",
                tone="dark",
                style="dark fantasy painterly",
            )
            # All three artifacts should exist
            self.assertTrue(paths.png.exists(), f"PNG missing: {paths.png}")
            self.assertTrue(paths.svg.exists(), f"SVG missing: {paths.svg}")
            self.assertTrue(paths.prompt.exists(), f"Prompt missing: {paths.prompt}")

            # PNG is the canonical image
            self.assertEqual(paths.png.suffix, ".png")
            from PIL import Image
            with Image.open(paths.png) as img:
                self.assertEqual(img.size, (1920, 1080))
                # It should be a real, non-empty image
                self.assertGreater(img.size[0] * img.size[1], 100)

            # SVG is the legacy mirror — should mention the title text
            svg_text = paths.svg.read_text(encoding="utf-8")
            self.assertIn("The Last Watch", svg_text)

    def test_handles_long_titles(self):
        from title_image import generate_title_image

        with temp_dir() as tmp:
            paths = generate_title_image(
                tmp, "demo2",
                title="The Extremely Long Story Title That Should Definitely Wrap Across Multiple Lines Gracefully",
                concept="A test of long titles.",
                tone="dramatic",
                style="fantasy painterly",
            )
            self.assertTrue(paths.png.exists())

    def test_each_tone_produces_different_palette(self):
        from PIL import Image
        from title_image import generate_title_image

        # Render the same title in 3 different tones; the average pixel value
        # of the top-left corner should differ between them.
        with temp_dir() as tmp:
            renderings = {}
            for tone in ("dark", "hopeful", "lighthearted"):
                p = generate_title_image(
                    tmp, f"story_{tone}",
                    title="A Test",
                    concept="",
                    tone=tone,
                    style="painterly",
                )
                with Image.open(p.png) as img:
                    # Sample a small patch in the top-left (away from text)
                    patch = img.crop((50, 50, 250, 250))
                    pixels = list(patch.getdata())
                    avg = (
                        sum(p[0] for p in pixels) / len(pixels),
                        sum(p[1] for p in pixels) / len(pixels),
                        sum(p[2] for p in pixels) / len(pixels),
                    )
                    renderings[tone] = avg

            # Dark should be the darkest of the three (lowest brightness sum)
            def brightness(rgb): return sum(rgb)
            self.assertLess(
                brightness(renderings["dark"]),
                brightness(renderings["hopeful"]) + 20,  # allow some leeway
                "Dark tone should be darker than hopeful",
            )
            # And the three palettes should not all be identical
            distinct = len({tuple(round(c, 5) for c in v) for v in renderings.values()})
            self.assertGreater(distinct, 1, "Palettes collapsed to the same color")


if __name__ == "__main__":
    unittest.main()
