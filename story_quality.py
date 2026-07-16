"""Quality checks for the creative part of story generation.

These checks are intentionally deterministic. They do not replace an editor,
but they catch the low-cost failures that make every downstream asset worse:
missing scene fields, narration that is too short to carry a scene, repeated
camera framing, and broken character continuity.
"""

from __future__ import annotations

import re
from collections import Counter


SHOT_TYPES = (
    "extreme wide shot",
    "wide shot",
    "long shot",
    "medium shot",
    "medium close-up",
    "close-up",
    "extreme close-up",
    "over-the-shoulder shot",
    "low angle",
    "high angle",
    "dutch angle",
)

STYLE_FORBIDDEN = (
    ("editorializing", re.compile(r"\b(?:sadly|fortunately|tragically|angrily|fearfully|hopefully)\b", re.I)),
    ("internal_feeling", re.compile(r"\b(?:he|she|they) felt\b|\b(?:he|she|they) thought\b", re.I)),
    ("dialogue_tag", re.compile(r"\b(?:he|she|they) (?:said|exclaimed|shouted|whispered|replied)\b", re.I)),
    ("banned_transition", re.compile(r"\b(?:suddenly|unexpectedly)\b", re.I)),
    ("first_person", re.compile(r"\b(?:I|me|my|mine)\b", re.I)),
)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text or ""))


def _shot_type(prompt: str) -> str | None:
    """Find the declared shot type near the start of a visual prompt."""
    prefix = (prompt or "").strip().lower()[:120]
    for shot in sorted(SHOT_TYPES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(shot)}\b", prefix):
            return shot
    return None


def _character_names(characters: str) -> list[str]:
    """Extract only explicitly labelled character names.

    Free-form character descriptions vary widely. Requiring names that are
    clearly followed by a colon or dash avoids treating ordinary adjectives
    as characters while still enforcing the common ``Name - description``
    format.
    """
    names: list[str] = []
    for line in (characters or "").splitlines():
        match = re.match(r"\s*(?:[-*]\s*)?([A-Z][A-Za-z0-9' -]{1,30})\s*(?:-|:)", line)
        if not match:
            continue
        name = re.sub(r"\s+", " ", match.group(1)).strip(" -:")
        if name and name.lower() not in {item.lower() for item in names}:
            names.append(name)
    return names


def review_scene_outline(
    scenes: list[dict],
    expected_scenes: int,
    *,
    characters: str = "",
    tone: str = "dramatic",
) -> dict:
    """Review a parsed outline and return a serializable quality report."""
    issues: list[dict] = []
    scene_count = len(scenes or [])
    if scene_count != expected_scenes:
        issues.append({
            "severity": "blocking",
            "code": "scene_count",
            "message": f"Expected {expected_scenes} scenes, received {scene_count}.",
        })

    titles: list[str] = []
    shot_types: list[str] = []
    character_names = _character_names(characters)
    min_words = 160 if "manhwa" in (tone or "").lower() else 60
    max_words = 360 if "manhwa" in (tone or "").lower() else 220

    for index, scene in enumerate(scenes or [], start=1):
        scene_label = f"scene_{index:02d}"
        title = (scene.get("title") or "").strip()
        prompt = (scene.get("prompt") or "").strip()
        narrative = (scene.get("narrative") or "").strip()
        narration = (scene.get("narration") or scene.get("narration_text") or "").strip()

        if not title or not prompt or not narrative or not narration:
            issues.append({
                "severity": "blocking",
                "code": "missing_field",
                "scene": scene_label,
                "message": "Every scene needs a title, visual prompt, narrative, and narration.",
            })
        if title:
            titles.append(title.casefold())
        words = _word_count(narration)
        if narration and words < min_words:
            issues.append({
                "severity": "warning",
                "code": "narration_short",
                "scene": scene_label,
                "message": f"Narration has {words} words; target is at least {min_words}.",
            })
        elif words > max_words:
            issues.append({
                "severity": "warning",
                "code": "narration_long",
                "scene": scene_label,
                "message": f"Narration has {words} words; target is at most {max_words}.",
            })
        for code, pattern in STYLE_FORBIDDEN:
            if pattern.search(narration):
                issues.append({
                    "severity": "warning",
                    "code": code,
                    "scene": scene_label,
                    "message": f"Narration violates the canonical style rule: {code.replace('_', ' ')}.",
                })
        for sentence in re.split(r"[.!?]+", narration):
            if _word_count(sentence) > 25:
                issues.append({
                    "severity": "warning",
                    "code": "long_sentence",
                    "scene": scene_label,
                    "message": "Keep narration sentences under 25 words except for deliberate reflective breaths.",
                })
                break

        shot = _shot_type(prompt)
        if shot:
            shot_types.append(shot)
        else:
            issues.append({
                "severity": "warning",
                "code": "shot_type_missing",
                "scene": scene_label,
                "message": "Visual prompt should begin with an explicit cinematography shot type.",
            })

        combined = f"{prompt} {narrative}".casefold()
        for name in character_names:
            if name.casefold() not in combined:
                issues.append({
                    "severity": "warning",
                    "code": "character_continuity",
                    "scene": scene_label,
                    "message": f"Character {name} is not named in the visual prompt or narrative.",
                })

    duplicates = [title for title, count in Counter(titles).items() if count > 1]
    for title in duplicates:
        issues.append({
            "severity": "warning",
            "code": "duplicate_title",
            "message": f"Scene title is repeated: {title}.",
        })

    if len(shot_types) >= 4 and len(set(shot_types)) < 3:
        issues.append({
            "severity": "warning",
            "code": "shot_variety",
            "message": "Use at least three shot types so the story does not become a static slideshow.",
        })

    run = 0
    previous = None
    for shot in shot_types:
        if shot == previous:
            run += 1
        else:
            run = 1
            previous = shot
        if shot in {"close-up", "extreme close-up"} and run > 2:
            issues.append({
                "severity": "warning",
                "code": "closeup_run",
                "message": "Do not use close-ups for more than two consecutive scenes.",
            })
            break

    blocking = [issue for issue in issues if issue["severity"] == "blocking"]
    score = max(0.0, round(1.0 - (len(issues) / max(8.0, expected_scenes * 2.0)), 2))
    return {
        "valid": not blocking,
        "score": score,
        "scene_count": scene_count,
        "shot_types": shot_types,
        "issues": issues,
        "blocking_issues": len(blocking),
    }


def outline_feedback(review: dict) -> str:
    """Turn a review into compact retry instructions for the LLM."""
    messages = [issue.get("message", "") for issue in review.get("issues", [])]
    messages = [message for message in messages if message]
    if not messages:
        return ""
    return "\n".join(f"- {message}" for message in messages[:8])
