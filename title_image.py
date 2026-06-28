"""Image-backed story title slides.

The viewer used to render a text-only SVG title slide (``assets/title/title_slide.svg``).
That worked but the visual was flat compared to the per-scene ComfyUI art, so the
hero, cards, and the first frame of the rendered video all looked like a different
app.

This module renders a richer 1920x1080 PNG that:

* draws a procedural gradient + soft-glow background tuned to the story tone,
* lays out the title and concept with a readable scrim behind the text,
* embeds the tone / style metadata as a header strip,
* keeps the same output filename convention so all existing references
  (``assets/title/title_slide.png``) continue to work.

We deliberately use Pillow only — no ComfyUI dependency — so a title image is
*always* available the moment the LLM title is known, well before any image
generation has finished.
"""

from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError as e:  # pragma: no cover
    raise SystemExit("Pillow is required for title_image.py: pip install pillow") from e


# ── Config ──────────────────────────────────────────────────────────────

WIDTH = 1920
HEIGHT = 1080

# Tone → (top-left color, mid color, bottom-right color). All RGB tuples.
TONE_PALETTES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = {
    "dramatic":      ((0x09, 0x0b, 0x12), (0x18, 0x16, 0x2a), (0x2a, 0x10, 0x15)),
    "dark":          ((0x05, 0x07, 0x0d), (0x10, 0x10, 0x18), (0x1a, 0x08, 0x0a)),
    "epic":          ((0x0a, 0x0f, 0x1f), (0x1d, 0x1b, 0x33), (0x4a, 0x1c, 0x10)),
    "heroic":        ((0x08, 0x12, 0x14), (0x1b, 0x2a, 0x2a), (0x4a, 0x2a, 0x10)),
    "mysterious":    ((0x05, 0x07, 0x14), (0x14, 0x0f, 0x28), (0x10, 0x08, 0x1f)),
    "lighthearted":  ((0xff, 0xf6, 0xdd), (0xe6, 0xc2, 0x8a), (0x8a, 0x4a, 0x10)),
    "comedic":       ((0xfd, 0xe2, 0x6c), (0xee, 0x9b, 0x50), (0x67, 0x2a, 0x10)),
    "romantic":      ((0x4a, 0x10, 0x18), (0x8a, 0x14, 0x44), (0x1a, 0x06, 0x18)),
    "melancholic":   ((0x12, 0x14, 0x20), (0x22, 0x2a, 0x3f), (0x4a, 0x4f, 0x70)),
    "hopeful":       ((0x06, 0x14, 0x28), (0x14, 0x2a, 0x4a), (0x6a, 0x8a, 0x6a)),
    "suspenseful":   ((0x02, 0x04, 0x08), (0x10, 0x14, 0x22), (0x2a, 0x10, 0x10)),
    "whimsical":     ((0x18, 0x0e, 0x28), (0x4a, 0x18, 0x4a), (0x18, 0x4a, 0x4a)),
    "epic-fantasy":  ((0x0c, 0x0a, 0x18), (0x1f, 0x18, 0x10), (0x4a, 0x2a, 0x08)),
    "noir":          ((0x06, 0x06, 0x06), (0x12, 0x10, 0x10), (0x22, 0x1a, 0x18)),
    "lyrical":       ((0x10, 0x08, 0x18), (0x3a, 0x1a, 0x3a), (0x4a, 0x3a, 0x6a)),
    "gritty":        ((0x08, 0x08, 0x08), (0x20, 0x1a, 0x10), (0x3a, 0x22, 0x10)),
    "manhwa":        ((0x10, 0x06, 0x10), (0x4a, 0x10, 0x2a), (0x8a, 0x4a, 0x18)),
    "tense":         ((0x06, 0x0a, 0x10), (0x10, 0x14, 0x22), (0x22, 0x18, 0x10)),
    "emotional":     ((0x10, 0x10, 0x20), (0x2a, 0x1a, 0x2a), (0x4a, 0x2a, 0x3a)),
    "whisper":       ((0x0a, 0x10, 0x14), (0x14, 0x20, 0x2a), (0x28, 0x3a, 0x4a)),
    "urgent":        ((0x10, 0x06, 0x06), (0x2a, 0x10, 0x0a), (0x4a, 0x18, 0x10)),
    "excited":       ((0x14, 0x0a, 0x10), (0x4a, 0x18, 0x10), (0x6a, 0x4a, 0x10)),
    "calm":          ((0x06, 0x10, 0x14), (0x14, 0x22, 0x2a), (0x4a, 0x4f, 0x70)),
    "normal":        ((0x0c, 0x0c, 0x14), (0x1f, 0x1f, 0x2a), (0x2a, 0x1a, 0x2a)),
}

# Style keyword → highlight color (RGB) for the inner glow ring
STYLE_HIGHLIGHTS: dict[str, tuple[int, int, int]] = {
    "fantasy":      (0xc8, 0xa8, 0x6a),
    "dark":         (0x8a, 0x2a, 0x2a),
    "anime":        (0xea, 0x6a, 0x9a),
    "cinematic":    (0xc8, 0xc0, 0xa0),
    "realistic":    (0xb0, 0xa8, 0x90),
    "painterly":    (0xe8, 0xc8, 0x8a),
    "illustration": (0xea, 0xc8, 0xa0),
    "storybook":    (0xea, 0xc8, 0xa0),
    "manhwa":       (0xea, 0x6a, 0x6a),
    "noir":         (0xa0, 0x9a, 0x90),
}


# ── Font discovery ──────────────────────────────────────────────────────


def _find_default_font(size: int) -> ImageFont.ImageFont:
    """Return a sensible system font. Falls back to PIL's default bitmap font."""
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf",     # Segoe UI Semibold
        "C:/Windows/Fonts/segoeui.ttf",      # Segoe UI
        "C:/Windows/Fonts/arial.ttf",        # Arial
        "C:/Windows/Fonts/calibrib.ttf",     # Calibri Bold
        "C:/Windows/Fonts/calibri.ttf",
        "/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except (OSError, FileNotFoundError):
            continue
    return ImageFont.load_default()


def _find_serif_font(size: int) -> ImageFont.ImageFont:
    """Find a serif font for the title. Falls back to the default sans."""
    candidates = [
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/GARA.ttf",
        "/Library/Fonts/Georgia.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except (OSError, FileNotFoundError):
            continue
    return _find_default_font(size)


# ── Layout helpers ──────────────────────────────────────────────────────


def _wrap_title(text: str, max_chars_per_line: int = 18, max_lines: int = 3) -> list[str]:
    """Greedy word-wrap; never breaks inside a word."""
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        proposed = " ".join(current + [word])
        if current and len(proposed) > max_chars_per_line:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines[:max_lines] or ["Untitled Story"]


def _truncate(text: str, max_chars: int) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _pick_palette(tone: str, style: str) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    base = TONE_PALETTES.get(tone.lower(), TONE_PALETTES["dramatic"])
    style_key = (style or "").lower().split()
    highlight = (0xe8, 0xd7, 0xa2)
    for key, color in STYLE_HIGHLIGHTS.items():
        if any(key in s for s in style_key):
            highlight = color
            break
    return (*base, highlight)


# ── Drawing primitives ─────────────────────────────────────────────────


def _draw_gradient(img: Image.Image, top: tuple[int, int, int], mid: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    """Diagonal 3-stop gradient using numpy for performance."""
    import numpy as np
    w, h = img.size
    
    # Create coordinate grids
    x = np.linspace(0, 1, w)
    y = np.linspace(0, 1, h)
    xx, yy = np.meshgrid(x, y)
    
    # Diagonal t-value in [0, 1]
    t = (xx + yy) / 2.0
    
    # Create output array
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    
    # top → mid region (t < 0.5)
    mask1 = t < 0.5
    a1 = t * 2.0
    for c in range(3):
        arr[:, :, c] = np.where(
            mask1,
            top[c] * (1 - a1) + mid[c] * a1,
            mid[c] * (1 - (t - 0.5) * 2.0) + bottom[c] * (t - 0.5) * 2.0
        ).astype(np.uint8)
    
    img.paste(Image.fromarray(arr))


def _draw_radial_glow(img: Image.Image, color: tuple[int, int, int], radius_factor: float = 0.6, alpha: float = 0.18) -> None:
    """Add a soft radial highlight near the top of the image.

    Uses additive compositing via a separate layer, so the gradient underneath
    is preserved.
    """
    w, h = img.size
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    cx, cy = w // 2, int(h * 0.42)
    r = int(min(w, h) * radius_factor)
    for i in range(r, 0, -4):
        a = int(alpha * 255 * (1 - i / r) ** 2)
        draw.ellipse(
            (cx - i, cy - i, cx + i, cy + i),
            fill=(color[0], color[1], color[2], a),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=64))
    img.paste(glow, (0, 0), glow)


def _draw_text_with_shadow(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
                           font: ImageFont.ImageFont, fill, shadow,
                           shadow_offset=(0, 6), stroke_width=0) -> None:
    x, y = xy
    if shadow:
        ox, oy = shadow_offset
        draw.text((x + ox, y + oy), text, font=font, fill=shadow, stroke_width=stroke_width)
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width)


def _fit_font_size(text: str, max_width: int, start_size: int, font_candidate: str = "serif",
                   min_size: int = 36) -> int:
    """Shrink ``start_size`` until the widest wrapped line fits ``max_width``."""
    size = start_size
    while size > min_size:
        font = _find_serif_font(size) if font_candidate == "serif" else _find_default_font(size)
        lines = _wrap_title(text, max_chars_per_line=max(8, int(max_width / (size * 0.5))))
        widest = max(_text_width(line, font) for line in lines)
        if widest <= max_width:
            return size
        size -= 4
    return min_size


def _text_width(text: str, font: ImageFont.ImageFont) -> int:
    """Width of a string in the given font. Works on Pillow <10 and >=10."""
    try:
        left, top, right, bottom = font.getbbox(text)
        return right - left
    except AttributeError:
        return font.getsize(text)[0]


def _text_height(font: ImageFont.ImageFont) -> int:
    try:
        _, top, _, bottom = font.getbbox("Ag")
        return bottom - top
    except AttributeError:
        return font.getsize("Ag")[1]


# ── Public API ──────────────────────────────────────────────────────────


@dataclass
class TitleSlidePaths:
    """Where the generated artifacts live relative to the story dir."""

    png: Path
    svg: Path
    prompt: Path

    def as_dict(self) -> dict:
        return {
            "png": str(self.png).replace("\\", "/"),
            "svg": str(self.svg).replace("\\", "/"),
            "prompt": str(self.prompt).replace("\\", "/"),
        }


def generate_title_image(
    story_dir: Path,
    story_id: str,
    title: str,
    concept: str,
    tone: str = "dramatic",
    style: str = "",
) -> TitleSlidePaths:
    """Render the story's image-backed title slide.

    Returns the on-disk paths (absolute) for the PNG, the legacy SVG mirror,
    and the working/prompts/txt file. The PNG is the canonical asset; the
    SVG is regenerated too so any code that still references the SVG
    keeps working.
    """
    story_dir = Path(story_dir)
    title_dir = story_dir / "assets" / "title"
    title_dir.mkdir(parents=True, exist_ok=True)
    working_prompts = story_dir / "working" / "prompts"
    working_prompts.mkdir(parents=True, exist_ok=True)

    png_path = title_dir / "title_slide.png"
    svg_path = title_dir / "title_slide.svg"
    prompt_path = working_prompts / "title_slide_prompt.txt"

    top, mid, bottom, highlight = _pick_palette(tone, style)

    img = Image.new("RGB", (WIDTH, HEIGHT), top)
    _draw_gradient(img, top, mid, bottom)
    _draw_radial_glow(img, highlight, radius_factor=0.55, alpha=0.22)
    # Add a soft vignette for contrast at the edges
    _draw_radial_glow(img, (0, 0, 0), radius_factor=0.95, alpha=0.35)

    draw = ImageDraw.Draw(img)

    # Inner frame
    draw.rectangle(
        (108, 92, WIDTH - 108, HEIGHT - 92),
        outline=(255, 255, 255),
        width=2,
    )

    # Header strip — tone / style
    header_font = _find_default_font(28)
    header = f"{tone.upper()}  /  {style.upper()[:48] or 'CINEMATIC'}"
    _draw_text_with_shadow(
        draw, (WIDTH // 2 - _text_width(header, header_font) // 2, 230),
        header, header_font,
        fill=(0xd8, 0xca, 0xa7),
        shadow=(0, 0, 0),
    )

    # Title — serif, big. Auto-shrink if it doesn't fit.
    title_max_width = WIDTH - 360
    title_size = _fit_font_size(title, title_max_width, start_size=104, min_size=48)
    title_font = _find_serif_font(title_size)
    title_lines = _wrap_title(title, max_chars_per_line=max(8, int(title_max_width / (title_size * 0.5))))
    line_h = int(title_size * 1.05)
    total_h = line_h * len(title_lines)
    y = (HEIGHT - total_h) // 2 - 30
    for line in title_lines:
        x = (WIDTH - _text_width(line, title_font)) // 2
        _draw_text_with_shadow(
            draw, (x, y),
            line, title_font,
            fill=(0xff, 0xf8, 0xe8),
            shadow=(0, 0, 0),
            shadow_offset=(0, 8),
        )
        y += line_h

    # Subtitle / concept
    subtitle = _truncate(concept or "", 140)
    sub_font = _find_default_font(30)
    x = (WIDTH - _text_width(subtitle, sub_font)) // 2
    sub_y = min(HEIGHT - 220, y + 24)
    _draw_text_with_shadow(
        draw, (x, sub_y),
        subtitle, sub_font,
        fill=(0xd6, 0xd2, 0xdc),
        shadow=(0, 0, 0),
    )

    # Footer / brand mark
    brand_font = _find_default_font(22)
    brand = "FANTASEE"
    x = (WIDTH - _text_width(brand, brand_font)) // 2
    _draw_text_with_shadow(
        draw, (x, HEIGHT - 150),
        brand, brand_font,
        fill=(0xa9, 0xa3, 0xb7),
        shadow=(0, 0, 0),
    )

    img.save(png_path, "PNG", optimize=True)

    # Re-emit the SVG too so any code still pointing at .svg keeps working.
    _emit_legacy_svg(svg_path, title, concept, tone, style)

    prompt_path.write_text(
        f"Title: {title}\nTone: {tone}\nStyle: {style}\nConcept: {concept}\n",
        encoding="utf-8",
    )

    return TitleSlidePaths(png=png_path, svg=svg_path, prompt=prompt_path)


def _emit_legacy_svg(svg_path: Path, title: str, concept: str, tone: str, style: str) -> None:
    """Re-emit the legacy SVG mirror so older references still work."""
    title_lines = _wrap_title(title, max_chars_per_line=18, max_lines=3)
    line_count = len(title_lines)
    start_y = 418 - (line_count - 1) * 48
    tspans = [
        f'<tspan x="960" y="{start_y + i * 96}">{html.escape(line)}</tspan>'
        for i, line in enumerate(title_lines)
    ]
    subtitle = _truncate(concept or "", 118)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#090b12"/>
      <stop offset="52%" stop-color="#18162a"/>
      <stop offset="100%" stop-color="#2a1015"/>
    </linearGradient>
  </defs>
  <rect width="1920" height="1080" fill="url(#bg)"/>
  <text x="960" y="242" text-anchor="middle" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="26" fill="#d8caa7" letter-spacing="8">{html.escape(tone.upper())} / {html.escape(style.upper()[:38])}</text>
  <text text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-size="92" font-weight="700" fill="#fff8e8">
    {"".join(tspans)}
  </text>
  <text x="960" y="720" text-anchor="middle" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="30" fill="#d6d2dc" opacity="0.86">{html.escape(subtitle)}</text>
  <text x="960" y="842" text-anchor="middle" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="22" fill="#a9a3b7" letter-spacing="4">FANTASEE</text>
</svg>
'''
    svg_path.write_text(svg, encoding="utf-8")


def relative_title_paths(story_dir: Path) -> dict:
    """The standard asset paths stored on the manifest, relative to the story dir."""
    return {
        "title_image": "assets/title/title_slide.png",
        "title_slide": "assets/title/title_slide.png",   # legacy alias
        "title_slide_svg": "assets/title/title_slide.svg",
    }


if __name__ == "__main__":
    import argparse
    import shutil
    import tempfile

    parser = argparse.ArgumentParser(description="Render a title slide PNG")
    parser.add_argument("--title", required=True)
    parser.add_argument("--concept", default="")
    parser.add_argument("--tone", default="dramatic")
    parser.add_argument("--style", default="fantasy painterly")
    parser.add_argument("--out", default="title_slide.png", help="Output PNG path")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="fantasee_title_"))
    try:
        paths = generate_title_image(tmp, "demo", args.title, args.concept, args.tone, args.style)
        shutil.copy(paths.png, args.out)
        print(f"Wrote {args.out}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
