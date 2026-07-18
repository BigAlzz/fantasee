r"""Seed-suggestion parser.

The LLM is asked to emit a JSON array of distinct story seeds
(``{title, description, style, tone, characters}``) for a given
concept. The actual networking lives in the ``/api/seed-suggestions``
route; this module just normalizes whatever the LLM returned.

Common LLM quirks handled:

* Markdown fences (``\`\`\`json ... \`\`\``) — stripped.
* Surrounding prose ("Here you go: [...] Enjoy!") — the outermost
  ``[`` / ``]`` are taken as the real array.
* Trailing commas in JSON objects / arrays — a permissive
  ``re.sub`` cleans them up before the second parse attempt.
"""

from __future__ import annotations

import json
import re


SEED_SYSTEM = """You are a creative writing assistant specializing in generating
distinct story seed ideas.

Given a concept, generate exactly N distinct story seeds. Each seed must have:

- "title": an evocative 2-6 word title (no quotes, no numbering)
- "description": a 1-2 sentence pitch — the hook that makes this story
  unique compared to the other seeds
- "style": visual style. Use one of: "fantasy painterly", "anime",
  "comic book panels", "dark fantasy", "cinematic", "illustration". Vary across seeds when
  natural — don't repeat the same one for all N.
- "tone": one of: "dramatic", "dark", "epic", "mysterious", "lighthearted",
  "romantic", "melancholic", "hopeful", "suspenseful", "whimsical",
  "epic-fantasy", "noir", "lyrical", "gritty", "manhwa", "tense",
  "emotional". Vary across seeds.
- "characters": 1-2 sentence character list (comma-separated names +
  one-clause descriptors). Omit if the story doesn't need named
  characters.

Keep the seeds distinct — different angles, different settings, different
protagonists. Don't just rephrase the same idea N times.

Output a JSON array only. No prose before or after, no markdown fences."""


def _coerce_seed_item(raw: dict) -> dict:
    """Normalize one parsed seed into the shape the frontend expects."""
    title = (raw.get("title") or "").strip().strip('"').strip("'")
    description = (raw.get("description") or "").strip()
    style = (raw.get("style") or "fantasy painterly").strip().lower()
    tone = (raw.get("tone") or "dramatic").strip().lower()
    characters = (raw.get("characters") or "").strip()
    # Clamp to a reasonable title length so the picker cards stay readable
    if len(title) > 80:
        title = title[:77].rstrip() + "…"
    if len(description) > 320:
        description = description[:317].rstrip() + "…"
    return {
        "title": title or "Untitled Seed",
        "description": description,
        "style": style,
        "tone": tone,
        "characters": characters,
    }


def _parse_seed_response(text: str, expected: int) -> list[dict]:
    """Parse the LLM's JSON array response, with a couple of fallbacks
    for common formatting hiccups (trailing commas, fenced blocks, etc.).
    """
    candidate = (text or "").strip()

    # Strip markdown fences if present
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)

    # Find the outermost JSON array
    arr_start = candidate.find("[")
    arr_end = candidate.rfind("]")
    if arr_start >= 0 and arr_end > arr_start:
        candidate = candidate[arr_start:arr_end + 1]

    # Try strict parse, then a permissive fallback
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        # Drop trailing commas inside arrays/objects — common LLM quirk
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        data = json.loads(candidate)

    if not isinstance(data, list):
        raise ValueError("Seed response is not a list")

    seeds = [_coerce_seed_item(item) for item in data if isinstance(item, dict)]
    # Pad/trim to expected count so the picker always has N cards (even
    # if the LLM returned fewer).
    while len(seeds) < expected:
        idx = len(seeds)
        seeds.append({
            "title": f"Seed {idx + 1}",
            "description": "Auto-generated fallback seed.",
            "style": "fantasy painterly",
            "tone": "dramatic",
            "characters": "",
        })
    return seeds[:expected]
