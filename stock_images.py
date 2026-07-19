#!/usr/bin/env python3
"""Generate placeholder scene images for stories that have no images yet.
Uses SVG clipart-style images with text overlays — instant, no ComfyUI needed.
Non-destructive: only fills in missing images.

Usage:
  python stock_images.py                          # fill all stories missing images
  python stock_images.py --story the-last-crossing # fill one story
  python stock_images.py --all                    # force replace even existing images
"""

import json, os, sys, textwrap, math, random
from pathlib import Path
from xml.sax.saxutils import escape

STORIES_ROOT = Path(__file__).parent / "stories"

# ── Color palettes per style ───────────────────────────────────────
PALETTES = {
    "dark gothic":      ["#1a0a0a", "#2d1b1b", "#401010", "#5c2020", "#2a0f0f"],
    "cinematic realism":["#1a1a2e", "#16213e", "#0f3460", "#27374d", "#1e293b"],
    "fantasy painterly":["#1a1a2e", "#241a38", "#2d1f4a", "#3d2a5e", "#1f1430"],
    "anime manga":      ["#1e1e2e", "#2a2a3e", "#36364e", "#42425e", "#1a1a28"],
    "default":          ["#1a1a2e", "#20203a", "#262646", "#2c2c52", "#141424"],
}

# ── Scene type icons (SVG path data) ───────────────────────────────
ICONS = {
    "wide":     '<path d="M4 8l4-4h16l4 4v12H4V8z" fill="rgba(255,255,255,0.08)" stroke="rgba(255,255,255,0.2)" stroke-width="1"/>',
    "closeup":  '<circle cx="20" cy="16" r="10" fill="rgba(255,255,255,0.08)" stroke="rgba(255,255,255,0.2)" stroke-width="1"/><circle cx="20" cy="14" r="4" fill="rgba(255,255,255,0.05)"/><circle cx="20" cy="22" r="5" fill="rgba(255,255,255,0.05)"/>',
    "action":   '<path d="M12 4l2 4h5l-3 3 1 5-4-2-4 2 1-5-3-3h5l2-4z" fill="rgba(255,255,255,0.08)" stroke="rgba(255,255,255,0.2)" stroke-width="1"/>',
    "dialogue": '<rect x="6" y="12" rx="2" width="8" height="10" fill="rgba(255,255,255,0.06)"/><rect x="18" y="12" rx="2" width="8" height="10" fill="rgba(255,255,255,0.06)"/><circle cx="10" cy="9" r="3" fill="rgba(255,255,255,0.05)"/><circle cx="22" cy="9" r="3" fill="rgba(255,255,255,0.05)"/>',
    "landscape":'<path d="M4 20l6-8 4 4 4-6 6 10H4z" fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.15)" stroke-width="1"/><circle cx="28" cy="8" r="2" fill="rgba(255,255,255,0.05)"/>',
}

def guess_icon(title, prompt):
    t = (title + " " + prompt).lower()
    if any(w in t for w in ["wide", "landscape", "establish", "vast", "panoramic", "extreme"]):
        return "landscape"
    if any(w in t for w in ["close", "face", "eyes", "tight", "portrait"]):
        return "closeup"
    if any(w in t for w in ["fight", "battle", "charge", "run", "chase", "explosion", "attack"]):
        return "action"
    if any(w in t for w in ["talk", "speak", "conversation", "dialogue", "meeting"]):
        return "dialogue"
    return "wide"

def generate_placeholder(story_title, scene_title, scene_num, total_scenes, prompt, style):
    """Generate an SVG placeholder image."""
    palette = PALETTES.get(style, PALETTES["default"])
    bg = palette[scene_num % len(palette)]
    accent = palette[(scene_num + 3) % len(palette)]

    # Strip shot type prefix from prompt for display
    display_prompt = prompt
    for prefix in ["extreme wide shot", "wide shot", "long shot", "medium shot",
                    "medium close-up", "close-up", "extreme close-up",
                    "over-the-shoulder shot", "low angle", "high angle", "dutch angle"]:
        if prompt.lower().startswith(prefix):
            display_prompt = prompt[len(prefix):].strip().lstrip(",.:; ")
            break
    display_prompt = display_prompt[:80] + "..." if len(display_prompt) > 80 else display_prompt

    icon_svg = ICONS.get(guess_icon(scene_title, prompt), ICONS["wide"])
    wrapped_title = "\n".join(textwrap.wrap(scene_title, 20))

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="896" height="512" viewBox="0 0 896 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{bg}"/>
      <stop offset="100%" stop-color="{accent}"/>
    </linearGradient>
    <linearGradient id="glow" x1="0.5" y1="0" x2="0.5" y2="1">
      <stop offset="0%" stop-color="rgba(255,255,255,0.03)"/>
      <stop offset="100%" stop-color="rgba(0,0,0,0.1)"/>
    </linearGradient>
  </defs>
  <rect width="896" height="512" fill="url(#bg)"/>
  <rect width="896" height="512" fill="url(#glow)"/>

  <!-- Grid pattern -->
  <g stroke="rgba(255,255,255,0.02)" stroke-width="0.5">
    {''.join(f'<line x1="{x}" y1="0" x2="{x}" y2="512"/>' for x in range(0, 897, 64))}
    {''.join(f'<line x1="0" y1="{y}" x2="896" y2="{y}"/>' for y in range(0, 513, 64))}
  </g>

  <!-- Icon -->
  <g transform="translate(448, 200) scale(3.5) translate(-24, -16)">
    {icon_svg}
  </g>

  <!-- Scene number badge -->
  <rect x="24" y="24" rx="4" width="80" height="28" fill="rgba(0,0,0,0.4)"/>
  <text x="64" y="43" text-anchor="middle" fill="rgba(255,255,255,0.5)" font-family="sans-serif" font-size="12" font-weight="600">SCENE {scene_num}/{total_scenes}</text>

  <!-- Story title at bottom -->
  <rect x="0" y="340" width="896" height="172" fill="rgba(0,0,0,0.3)"/>
  <rect x="0" y="340" width="896" height="1" fill="rgba(255,255,255,0.06)"/>

  <text x="40" y="380" fill="rgba(255,255,255,0.3)" font-family="sans-serif" font-size="10" font-weight="500" letter-spacing="1">STORY</text>
  <text x="40" y="398" fill="#fff" font-family="sans-serif" font-size="16" font-weight="600">{escape(story_title[:60])}</text>

  <text x="40" y="430" fill="rgba(255,255,255,0.3)" font-family="sans-serif" font-size="10" font-weight="500" letter-spacing="1">SCENE</text>
  <text x="40" y="448" fill="rgba(255,255,255,0.85)" font-family="sans-serif" font-size="14" font-weight="500">{escape(wrapped_title[:60])}</text>

  <text x="40" y="480" fill="rgba(255,255,255,0.25)" font-family="sans-serif" font-size="9" font-weight="400">{escape(display_prompt[:120])}</text>

  <!-- Style badge -->
  <rect x="788" y="432" rx="3" width="84" height="20" fill="rgba(255,255,255,0.06)"/>
  <text x="830" y="446" text-anchor="middle" fill="rgba(255,255,255,0.35)" font-family="sans-serif" font-size="8" font-weight="500">{escape(style[:20])}</text>
</svg>'''
    return svg.encode("utf-8")


def fill_story_images(story_dir, force=False):
    """Generate placeholder images for a single story directory."""
    manifests = list(story_dir.glob(story_dir.name + ".json"))
    if not manifests:
        return 0

    with open(manifests[0]) as f:
        data = json.load(f)

    story_title = data.get("title", story_dir.name)
    style = data.get("style", "default")
    scenes = data.get("scenes", [])
    if not scenes:
        return 0

    generated = 0
    for i, scene in enumerate(scenes):
        scene_num = i + 1
        scene_title = scene.get("title", f"Scene {scene_num}")
        prompt = scene.get("prompt", scene.get("narrative", ""))
        existing = scene.get("image_filenames", [])

        # Check scene's own images
        scene_dir = story_dir
        scene_imgs = []
        for fname in existing:
            p = story_dir / fname
            if p.exists():
                scene_imgs.append(p)

        if scene_imgs and not force:
            continue  # Already has images

        # Generate placeholder
        scene_prefix = f"{story_dir.name}_s{scene_num:02d}_{scene_title[:20]}"
        safe_prefix = "".join(c if c.isalnum() or c in "-_." else "_" for c in scene_prefix)[:80]
        img_name = f"{safe_prefix}_placeholder.png"
        img_path = story_dir / img_name

        svg_data = generate_placeholder(
            story_title, scene_title, scene_num, len(scenes), prompt, style
        )

        # Write SVG as PNG (we can't easily convert SVG to PNG without PIL,
        # so we write the SVG and use it directly)
        svg_path = img_path.with_suffix(".svg")
        svg_path.write_bytes(svg_data)

        # Update manifest to include the placeholder
        if "image_filenames" not in scene:
            scene["image_filenames"] = []
        scene["image_filenames"].append(svg_path.name)

        generated += 1

    # Write updated manifest
    if generated > 0:
        with open(manifests[0], "w") as f:
            json.dump(data, f, indent=2)

    return generated


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate placeholder scene images")
    parser.add_argument("--story", help="Specific story ID (directory name)")
    parser.add_argument("--all", action="store_true", help="Force replace all images")
    args = parser.parse_args()

    if args.story:
        dirs = [STORIES_ROOT / args.story]
    else:
        dirs = sorted([d for d in STORIES_ROOT.iterdir() if d.is_dir() and d.name != ".trash"])

    total = 0
    for d in dirs:
        n = fill_story_images(d, force=args.all)
        if n > 0:
            print(f"  {d.name}: {n} placeholders")
            total += n

    print(f"\nDone: {total} placeholder images generated")
    if total > 0:
        print("(SVG files — open in browser or convert to PNG with cairosvg)")


if __name__ == "__main__":
    main()
