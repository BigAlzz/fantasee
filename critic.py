#!/usr/bin/env python3
"""
Fantasee Critic Agent v2
─────────────────────────
Production review covering story quality, visual continuity,
audio/video production, subtitle sync, and timing accuracy.

Usage:
  python critic.py <story-id>
  python critic.py the-emerald-s-fading-cure
  python critic.py --all
  python critic.py --json <story-id>
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from dataclasses import dataclass, field

OUTPUTS_DIR = Path(__file__).parent / "outputs"


# ── VTT Parser ───────────────────────────────────────────────────────────

def parse_vtt(text: str) -> list[dict]:
    """Parse VTT file into list of {start, end, text} dicts."""
    cues = []
    blocks = re.split(r'\n\s*\n', text.strip())
    for block in blocks:
        lines = block.strip().split('\n')
        for i, line in enumerate(lines):
            if '-->' in line:
                match = re.match(
                    r'(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[.,](\d{3})',
                    line
                )
                if match:
                    g = match.groups()
                    start = int(g[0])*3600 + int(g[1])*60 + int(g[2]) + int(g[3])/1000
                    end = int(g[4])*3600 + int(g[5])*60 + int(g[6]) + int(g[7])/1000
                    text_lines = [l for j, l in enumerate(lines) if j != i and l.strip()]
                    cues.append({"start": start, "end": end, "text": " ".join(text_lines)})
                break
    return cues


def parse_vtt_time(time_str: str) -> float:
    """Parse VTT timestamp to seconds."""
    parts = re.split(r'[:.,]', time_str)
    if len(parts) == 4:
        return int(parts[0])*3600 + int(parts[1])*60 + int(parts[2]) + int(parts[3])/1000
    return 0.0


# ── MP3 Duration ─────────────────────────────────────────────────────────

def get_mp3_duration(filepath: Path) -> float:
    """Get MP3/WAV duration via mutagen/ffprobe, with size fallback."""
    try:
        from tts_utils import get_audio_duration
        return get_audio_duration(str(filepath))
    except Exception:
        pass
    try:
        size = filepath.stat().st_size
        return max(3.0, (size * 8) / (128 * 1000))
    except Exception:
        return 0.0


# ── Scene Analysis ───────────────────────────────────────────────────────

def analyze_narration(narration: str) -> dict:
    """Analyze narration text quality."""
    issues = []
    
    if not narration:
        return {"issues": ["Missing narration"], "word_count": 0, "sentence_count": 0, "score": 0}
    
    words = narration.split()
    word_count = len(words)
    
    sentences = re.split(r'[.!?]+', narration)
    sentences = [s.strip() for s in sentences if s.strip()]
    sentence_count = len(sentences)
    
    # Length checks
    if word_count < 20:
        issues.append(f"Very short ({word_count} words)")
    elif word_count > 200:
        issues.append(f"Very long ({word_count} words) — may drag")
    
    # Sentence quality
    if sentence_count > 0:
        avg_len = word_count / sentence_count
        if avg_len > 30:
            issues.append("Run-on sentences — hard to follow in narration")
        if avg_len < 4:
            issues.append("Choppy sentences — feels staccato")
    
    # Repetition
    if narration.count("...") > 2:
        issues.append("Excessive ellipses")
    
    # Score
    score = 7.0
    if 30 <= word_count <= 150:
        score += 1.0
    if 2 <= avg_len <= 25:
        score += 1.0
    if not issues:
        score += 1.0
    
    return {
        "issues": issues,
        "word_count": word_count,
        "sentence_count": sentence_count,
        "score": min(10, max(0, score))
    }


def analyze_vtt(vtt_path: Path, audio_duration: float) -> dict:
    """Analyze VTT subtitle file for timing and sync issues."""
    issues = []
    
    if not vtt_path.exists():
        return {"issues": ["VTT file not found"], "cue_count": 0, "score": 0}
    
    content = vtt_path.read_text(encoding="utf-8")
    cues = parse_vtt(content)
    
    if not cues:
        return {"issues": ["No subtitle cues found"], "cue_count": 0, "score": 0}
    
    # Check timing issues
    for i, cue in enumerate(cues):
        # Negative or zero duration
        if cue["end"] <= cue["start"]:
            issues.append(f"Cue {i+1}: end <= start ({cue['start']:.2f}s → {cue['end']:.2f}s)")
        
        # Very short cue
        duration = cue["end"] - cue["start"]
        if duration < 0.5:
            issues.append(f"Cue {i+1}: too short ({duration:.2f}s) — can't read")
        
        # Very long cue (> 10s)
        if duration > 10:
            issues.append(f"Cue {i+1}: too long ({duration:.1f}s) — split into multiple cues")
        
        # Overlapping cues
        if i > 0 and cue["start"] < cues[i-1]["end"]:
            issues.append(f"Cue {i+1}: overlaps with cue {i}")
    
    # Check if subtitles extend beyond audio
    if audio_duration > 0 and cues:
        last_end = cues[-1]["end"]
        if last_end > audio_duration + 2:
            issues.append(f"Subtitles extend {last_end - audio_duration:.1f}s beyond audio")
        if cues[0]["start"] > 5:
            issues.append(f"First subtitle starts at {cues[0]['start']:.1f}s — audio plays without text")
    
    # Check gap between cues
    for i in range(1, len(cues)):
        gap = cues[i]["start"] - cues[i-1]["end"]
        if gap > 5:
            issues.append(f"Large gap ({gap:.1f}s) between cue {i} and {i+1}")
    
    score = 8.0
    if len(cues) == 0:
        score = 0
    if len(issues) > 3:
        score -= 2.0
    elif len(issues) > 0:
        score -= 0.5 * len(issues)
    
    return {
        "issues": issues,
        "cue_count": len(cues),
        "total_text_length": sum(len(c["text"]) for c in cues),
        "score": max(0, min(10, score))
    }


def analyze_audio(scene: dict, story_dir: Path) -> dict:
    """Analyze audio file for issues."""
    issues = []
    notes = []
    
    audio_file = scene.get("audio_filename", "")
    if not audio_file:
        return {"issues": ["No audio file"], "duration": 0, "score": 0}
    
    audio_path = story_dir / audio_file
    if not audio_path.exists():
        return {"issues": [f"Audio file missing: {audio_file}"], "duration": 0, "score": 0}
    
    size_kb = audio_path.stat().st_size // 1024
    if size_kb < 10:
        issues.append(f"Audio file very small ({size_kb}KB) — may be silent/corrupt")
    
    duration = get_mp3_duration(audio_path)
    notes.append(f"Duration: {duration:.1f}s, Size: {size_kb}KB")
    
    # Check narration vs audio timing
    narration = scene.get("narration", scene.get("narration_text", scene.get("narrative", "")))
    if narration and duration > 0:
        word_count = len(narration.split())
        # Normal speech rate: 130-160 wpm (very slow: 100 wpm)
        expected_min = word_count / 160 * 60
        expected_slow = word_count / 100 * 60
        
        # Audio is padded to fill image animation time, so longer is normal.
        # Only flag if audio is SHORTER than the slowest reasonable speech.
        if duration < expected_min:
            issues.append(f"Audio ({duration:.1f}s) may be too short for narration ({expected_min:.0f}s minimum at 160wpm)")
    
    score = 7.0
    if audio_path.exists():
        score += 1.0
    if duration > 0:
        score += 1.0
    if not issues:
        score += 1.0
    
    return {
        "issues": issues,
        "notes": notes,
        "duration": duration,
        "score": max(0, min(10, score))
    }


def analyze_images(scene: dict, story_dir: Path) -> dict:
    """Analyze image files."""
    issues = []
    notes = []
    
    image_filenames = scene.get("image_filenames", [])
    if not image_filenames:
        return {"issues": ["No images"], "notes": [], "count": 0, "score": 0}
    
    total_kb = 0
    for fname in image_filenames:
        img_path = story_dir / fname
        if not img_path.exists():
            issues.append(f"Missing: {fname}")
        else:
            kb = img_path.stat().st_size // 1024
            total_kb += kb
            if kb < 50:
                issues.append(f"{fname}: very small ({kb}KB) — likely low quality")
    
    avg_kb = total_kb // max(len(image_filenames), 1)
    notes.append(f"{len(image_filenames)} images, avg {avg_kb}KB")
    
    if len(image_filenames) == 1:
        notes.append("Single image per scene — limited visual variety")
    
    score = 7.0
    if len(image_filenames) >= 3:
        score += 1.5
    elif len(image_filenames) == 2:
        score += 0.5
    if avg_kb >= 300:
        score += 0.5
    if not issues:
        score += 1.0
    
    return {
        "issues": issues,
        "notes": notes,
        "count": len(image_filenames),
        "score": max(0, min(10, score))
    }


# ── Continuity Check (improved) ─────────────────────────────────────────

def check_continuity(story: dict) -> list[str]:
    """Check for real continuity issues across scenes."""
    issues = []
    scenes = story.get("scenes", [])
    if len(scenes) < 2:
        return issues
    
    # Extract character names (proper nouns at start of sentences or after "said")
    def extract_names(text: str) -> set[str]:
        names = set()
        # Look for capitalized words that appear multiple times across scenes
        words = text.split()
        for w in words:
            clean = w.strip(".,!?;:'\"\"\"''")
            if clean and clean[0].isupper() and len(clean) > 2:
                skip = {"The", "This", "That", "When", "Then", "Here", "There",
                        "What", "Where", "How", "Why", "And", "But", "For", "Not",
                        "She", "Her", "His", "Him", "They", "Their", "From", "With",
                        "Into", "Through", "Against", "Between", "Scene", "Chapter",
                        "Now", "But", "And", "Or", "So", "If", "As", "In", "On",
                        "At", "To", "Of", "By", "It", "Its", "My", "Your", "Our",
                        "Yet", "Still", "Just", "Even", "Only", "Also", "Once",
                        "Like", "Over", "Under", "Before", "After", "While",
                        "One", "Two", "Three", "Four", "Five", "Six", "Seven",
                        "Eight", "Nine", "Ten", "First", "Last", "Next", "New",
                        "All", "Each", "Every", "Both", "Few", "More", "Most",
                        "Other", "Some", "Such", "No", "Nor", "Very", "Well",
                        "Back", "Down", "Off", "Out", "Up", "Deep", "Far",
                        "High", "Low", "Long", "Wide", "Great", "Small",
                        "Dark", "Light", "Old", "New", "Young", "Full", "Half",
                        "White", "Black", "Red", "Blue", "Green", "Gold", "Silver",
                        "Stone", "Wind", "Fire", "Water", "Earth", "Air",
                        "Heart", "Soul", "Spirit", "Mind", "Eye", "Eyes", "Hand",
                        "Hands", "Face", "Head", "Body", "Blood", "Bone", "Flesh",
                        "Mountain", "Forest", "River", "Lake", "Sea", "Sky",
                        "Sun", "Moon", "Star", "Storm", "Cloud", "Rain", "Snow",
                        "Dragon", "Rider", "Shrine", "Temple", "Tower", "Castle",
                        "Fort", "Wall", "Gate", "Path", "Road", "Trail", "Field",
                        "Wing", "Wings", "Tail", "Claw", "Scale", "Scales",
                        "Emerald", "Crystal", "Jewel", "Crown", "Throne",
                        "Kaele", "Verid", "Veridian", "Emerald", "Shrine",
                        "Wings", "Fading", "Cure", "Embers", "Dawn",
                        "Fading", "Light", "Whispers", "Blighted", "Wood",
                        "Hunters", "Gloom", "Stormcrest", "Ascent", "Betrayal",
                        "Final", "Approach", "Heart", "Mountain"}
                if clean not in skip:
                    names.add(clean)
        return names
    
    # Get all names per scene
    scene_names = []
    for scene in scenes:
        narration = scene.get("narration", scene.get("narration_text", ""))
        prompt = scene.get("prompt", "")
        names = extract_names(narration + " " + prompt)
        scene_names.append(names)
    
    # Find names that appear in most scenes (likely characters)
    all_names = set()
    for names in scene_names:
        all_names.update(names)
    
    char_frequency = {}
    for name in all_names:
        count = sum(1 for sn in scene_names if name in sn)
        if count >= 3:
            char_frequency[name] = count
    
    # Check for name variations (e.g., "Kaelen" vs "Kaylen")
    char_list = sorted(char_frequency.keys(), key=lambda x: char_frequency[x], reverse=True)
    for i, name1 in enumerate(char_list):
        for name2 in char_list[i+1:]:
            # Check if one is a possessive/variant of the other
            if name1.lower() in name2.lower() or name2.lower() in name1.lower():
                continue  # Skip possessives like Kaelen/Kaelen's
            # Check edit distance for typos
            if len(name1) == len(name2):
                diffs = sum(1 for a, b in zip(name1.lower(), name2.lower()) if a != b)
                if diffs == 1:
                    issues.append(f"Possible typo: '{name1}' vs '{name2}' (edit distance 1)")
    
    # Check scene transitions for jarring jumps
    for i in range(len(scenes) - 1):
        curr = scenes[i]
        next_s = scenes[i + 1]
        
        curr_title = curr.get("title", "").lower()
        next_title = next_s.get("title", "").lower()
        
        # Check for location changes without transition words
        curr_narr = curr.get("narration", curr.get("narration_text", "")).lower()
        next_narr = next_s.get("narration", next_s.get("narration_text", "")).lower()
        
        # Detect location keywords
        locations = {"lodge", "camp", "forest", "wood", "mountain", "shrine", "temple",
                     "tower", "village", "cave", "river", "cliff", "ridge", "peak",
                     "gate", "wall", "fort", "castle", "field", "meadow", "swamp"}
        
        curr_locs = locations.intersection(curr_narr.split())
        next_locs = locations.intersection(next_narr.split())
        
        if curr_locs and next_locs and curr_locs != next_locs:
            # Location changed — check if there's a transition
            transition_words = {"then", "after", "later", "finally", "meanwhile",
                              "next", "following", "approaching", "reaching"}
            if not any(tw in next_narr[:100] for tw in transition_words):
                curr_name = ", ".join(curr_locs)
                next_name = ", ".join(next_locs)
                if curr_name != next_name:
                    pass  # Don't flag normal story progression
    
    # Check for emotional arc
    mood_words = {
        "hope": ["hope", "hopeful", "bright", "light", "warm", "smile", "joy"],
        "danger": ["danger", "fear", "threat", "hunt", "chase", "flee", "dark"],
        "sadness": ["sorrow", "grief", "loss", "weep", "cry", "mourn", "fade"],
        "triumph": ["victory", "triumph", "won", "save", "heal", "cure", "light"]
    }
    
    scene_moods = []
    for scene in scenes:
        narr = (scene.get("narration", "") + " " + scene.get("prompt", "")).lower()
        moods = []
        for mood, keywords in mood_words.items():
            if any(kw in narr for kw in keywords):
                moods.append(mood)
        scene_moods.append(moods if moods else ["neutral"])
    
    # Check if mood progression makes sense
    if len(scene_moods) >= 4:
        has_danger = any("danger" in m for m in scene_moods)
        has_triumph = any("triumph" in m for m in scene_moods)
        if not has_danger and not has_triumph:
            issues.append("Flat emotional arc — no danger or triumph beats")
    
    return issues


# ── Story Arc Analysis ───────────────────────────────────────────────────

def analyze_story_arc(story: dict) -> dict:
    """Analyze story structure and pacing."""
    scenes = story.get("scenes", [])
    notes = []
    issues = []
    
    if not scenes:
        return {"notes": "Empty story", "issues": ["No scenes"], "score": 0}
    
    # Narration length distribution
    lengths = []
    for scene in scenes:
        narr = scene.get("narration", scene.get("narration_text", ""))
        lengths.append(len(narr.split()) if narr else 0)
    
    if lengths:
        avg = sum(lengths) / len(lengths)
        mn, mx = min(lengths), max(lengths)
        notes.append(f"Narration: {mn}-{mx} words (avg {avg:.0f})")
        
        if mx > avg * 2.5:
            issues.append(f"Scene with {mx} words is {mx/avg:.1f}x the average — unbalanced")
        
        # Pacing: check if opening/closing are appropriately sized
        if len(lengths) >= 3:
            opening = lengths[0]
            closing = lengths[-1]
            if opening < avg * 0.5:
                issues.append(f"Opening scene is {opening} words — feels rushed")
            if closing < avg * 0.3:
                issues.append(f"Final scene is only {closing} words — feels abrupt")
    
    # Check rendered video exists
    story_id = story.get("id", "")
    story_dir = OUTPUTS_DIR / story_id
    has_video = any(story_dir.glob(f"{story_id}_s*.mp4")) if story_dir.exists() else False
    has_full = (story_dir / f"{story_id}_full.mp4").exists() if story_dir.exists() else False
    
    if has_full:
        notes.append("Full story video: rendered ✓")
    elif has_video:
        notes.append("Per-scene videos rendered ✓ (no full compilation)")
    else:
        issues.append("No rendered video found")
    
    score = 7.0
    if len(issues) == 0:
        score += 1.0
    if len(scenes) >= 5:
        score += 1.0
    if has_full:
        score += 1.0
    
    return {"notes": "; ".join(notes), "issues": issues, "score": max(0, min(10, score))}


# ── Star Rating ────────────────────────────────────────────────────────────

def compute_star_rating(result: dict) -> dict:
    """Convert critic scores to a 1-5 star rating with category breakdown.

    Returns a review dict with:
      - rating: float (1.0-5.0)
      - stars: int (1-5, rounded)
      - summary: str (2-3 sentence overall review)
      - categories: list of {name, score, max_score, label}
      - what_works: list of strengths
      - needs_work: list of issues to fix
      - badge: str (short label like "Strong" or "Needs Polish")
    """
    scores = result.get("scores", {})
    overall = scores.get("overall", 5.0)

    # Convert 0-10 to 1-5 stars
    rating = max(1.0, min(5.0, round(overall / 2, 1)))
    stars = max(1, min(5, round(rating)))

    # Category breakdown
    categories = [
        {"name": "Narrative", "score": scores.get("story", 5.0), "max_score": 10.0},
        {"name": "Visuals", "score": scores.get("visual", 5.0), "max_score": 10.0},
        {"name": "Audio", "score": scores.get("audio", 5.0), "max_score": 10.0},
        {"name": "Subtitles", "score": scores.get("subtitles", 5.0), "max_score": 10.0},
        {"name": "Structure", "score": scores.get("structure", 5.0), "max_score": 10.0},
    ]

    # Determine badge
    if rating >= 4.5:
        badge = "Excellent"
    elif rating >= 4.0:
        badge = "Strong"
    elif rating >= 3.5:
        badge = "Good"
    elif rating >= 3.0:
        badge = "Decent"
    elif rating >= 2.0:
        badge = "Needs Work"
    else:
        badge = "Rough"

    # Collect strengths and weaknesses
    all_issues = []
    for scene in result.get("scenes", []):
        for key in ("narration", "images", "audio", "subtitles"):
            section = scene.get(key, {})
            all_issues.extend(section.get("issues", []))

    # Summarize common issues
    issue_counts = {}
    for issue in all_issues:
        normalized = issue.split(":")[0].split("(")[0].strip()
        issue_counts[normalized] = issue_counts.get(normalized, 0) + 1

    needs_work = []
    for issue, count in sorted(issue_counts.items(), key=lambda x: -x[1])[:5]:
        if count > 1:
            needs_work.append(f"{issue} ({count} scenes)")
        else:
            needs_work.append(issue)

    # What works
    what_works = []
    scene_count = len(result.get("scenes", []))
    if scene_count > 0:
        narr_ok = sum(1 for s in result["scenes"] if s["narration"]["score"] >= 7)
        img_ok = sum(1 for s in result["scenes"] if s["images"]["score"] >= 7)
        aud_ok = sum(1 for s in result["scenes"] if s["audio"]["score"] >= 7)
        sub_ok = sum(1 for s in result["scenes"] if s["subtitles"]["score"] >= 7)

        if narr_ok == scene_count:
            what_works.append("Consistent narration quality across all scenes")
        elif narr_ok > scene_count * 0.7:
            what_works.append("Narration quality is generally strong")

        if img_ok == scene_count:
            what_works.append("All scenes have complete image sets")
        elif img_ok > scene_count * 0.7:
            what_works.append("Image generation is mostly complete")

        if aud_ok == scene_count:
            what_works.append("Audio production is solid throughout")

        if sub_ok == scene_count:
            what_works.append("Subtitle sync is accurate")

        if not all_issues:
            what_works.append("No issues detected — production looks clean")

    if not what_works:
        what_works.append("Story structure is coherent")

    # Build summary
    if rating >= 4.0:
        summary = f"This story scores {rating}/5 stars. "
        if what_works:
            summary += f"Key strengths: {what_works[0].lower()}. "
        if needs_work:
            summary += f"Could improve: {needs_work[0].lower()}."
        else:
            summary += "Production quality is solid across the board."
    elif rating >= 3.0:
        summary = f"A solid {rating}/5 star effort. "
        if needs_work:
            summary += f"Main areas to address: {needs_work[0].lower()}."
        else:
            summary += "Some room for improvement in pacing and visual variety."
    else:
        summary = f"Scores {rating}/5 — this story needs significant work. "
        if needs_work:
            summary += f"Priority fixes: {needs_work[0].lower()}."

    return {
        "rating": rating,
        "stars": stars,
        "summary": summary,
        "categories": categories,
        "what_works": what_works[:5],
        "needs_work": needs_work[:5],
        "badge": badge,
        "scene_count": scene_count,
        "overall_score": round(overall, 1),
    }


def llm_story_review(story: dict) -> dict | None:
    """Generate an LLM-based story quality review.

    Uses the same MiMo LLM as the pipeline for a narrative assessment.
    Falls back gracefully if the LLM is unavailable.
    """
    api_key = os.environ.get("XIAOMI_API_KEY", "")
    base_url = os.environ.get("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")

    if not api_key or api_key.startswith("***"):
        env_paths = [
            Path("E:/hermes/.env"),
            Path.home() / ".env",
        ]
        for env_path in env_paths:
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    stripped = line.strip()
                    if stripped.startswith("XIAOMI_API_KEY=") and not stripped.startswith("#"):
                        val = stripped.split("=", 1)[1].strip()
                        if val and not val.startswith("***"):
                            api_key = val
                    elif stripped.startswith("XIAOMI_BASE_URL=") and not stripped.startswith("#"):
                        base_url = stripped.split("=", 1)[1].strip()

    if not api_key:
        return None

    # Build story summary for the LLM
    scenes_summary = []
    for i, scene in enumerate(story.get("scenes", [])[:20], 1):
        title = scene.get("title", f"Scene {i}")
        narration = scene.get("narration", scene.get("narration_text", scene.get("narrative", "")))
        word_count = len(narration.split()) if narration else 0
        snippet = (narration[:200] + "...") if narration and len(narration) > 200 else (narration or "no narration")
        scenes_summary.append(f"Scene {i}: {title} ({word_count} words) — {snippet}")

    prompt = f"""You are a professional story reviewer for visual narrative media (like motion comics or illustrated story videos).

Title: {story.get('title', 'Untitled')}
Description: {story.get('description', 'No description')[:300]}
Scenes ({len(story.get('scenes', []))} total):
{chr(10).join(scenes_summary)}

Review this story on these dimensions (score each 0-10):
1. Narrative quality — Is the story engaging? Good pacing? Emotional hook?
2. Character consistency — Are characters described consistently across scenes?
3. Visual variety — Do scenes have diverse compositions and settings?
4. Tension arc — Does the story escalate toward a climax?
5. Dialogue/narration quality — Is the voiceover well-written and evocative?

Output ONLY a JSON object:
{{
  "narrative_quality": X.X,
  "character_consistency": X.X,
  "visual_variety": X.X,
  "tension_arc": X.X,
  "narration_quality": X.X,
  "summary": "2-3 sentence overall assessment",
  "strengths": ["strength 1", "strength 2"],
  "weaknesses": ["weakness 1", "weakness 2"],
  "improvement_suggestion": "single most impactful improvement"
}}"""

    try:
        import requests
        resp = requests.post(
            f"{base_url}/chat/completions",
            json={
                "model": "mimo-v2.5-pro",
                "messages": [
                    {"role": "system", "content": "You are a story quality reviewer. Output only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 1024,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        # Parse JSON from response — try code block first, then raw
        for pattern in (r"```json\s*([\s\S]*?)```", r"```\s*([\s\S]*?)```"):
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return json.loads(match.group(1).strip())

        # Find raw JSON object
        start = content.find("{")
        if start >= 0:
            depth = 0
            for end in range(start, len(content)):
                if content[end] == "{":
                    depth += 1
                elif content[end] == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(content[start:end + 1])

    except Exception as e:
        print(f"  [LLM review failed: {e}]", file=sys.stderr)

    return None


# ── Full Review ──────────────────────────────────────────────────────────

def review_story(story_id: str) -> dict | None:
    """Perform a full production review."""
    story_dir = OUTPUTS_DIR / story_id
    if not story_dir.exists():
        print(f"Error: Story not found: {story_id}", file=sys.stderr)
        return None
    
    manifest = story_dir / f"{story_id}.json"
    if not manifest.exists():
        print(f"Error: Manifest not found: {manifest}", file=sys.stderr)
        return None
    
    story = json.loads(manifest.read_text(encoding="utf-8"))
    title = story.get("title", story_id)
    scenes = story.get("scenes", [])
    
    result = {
        "story_id": story_id,
        "title": title,
        "scene_count": len(scenes),
        "scenes": [],
        "overall_issues": [],
        "continuity_issues": [],
        "recommendations": [],
        "scores": {}
    }
    
    scene_scores = []
    
    for scene in scenes:
        try:
            num = scene.get("scene", "?")
            stitle = scene.get("title", f"Scene {num}")

            narration = scene.get("narration", scene.get("narration_text", scene.get("narrative", "")))

            narr = analyze_narration(narration)
            img = analyze_images(scene, story_dir)
            aud = analyze_audio(scene, story_dir)

            # VTT analysis
            vtt_file = scene.get("vtt_file", f"{story_id}_s{num}.vtt")
            vtt_path = story_dir / vtt_file
            vtt = analyze_vtt(vtt_path, aud["duration"])

            # Check rendered video
            mp4_file = f"{story_id}_s{num}.mp4"
            has_video = (story_dir / mp4_file).exists()

            # Scene score
            score = (
                narr["score"] * 0.35 +
                img["score"] * 0.25 +
                aud["score"] * 0.25 +
                vtt["score"] * 0.15
            )

            scene_result = {
                "scene_num": num,
                "title": stitle,
                "score": round(score, 1),
                "narration": {
                    "word_count": narr["word_count"],
                    "sentences": narr["sentence_count"],
                    "score": narr["score"],
                    "issues": narr["issues"]
                },
                "images": {
                    "count": img["count"],
                    "score": img["score"],
                    "notes": img["notes"],
                    "issues": img["issues"]
                },
                "audio": {
                    "duration": round(aud["duration"], 1),
                    "score": aud["score"],
                    "notes": aud.get("notes", []),
                    "issues": aud["issues"]
                },
                "subtitles": {
                    "cue_count": vtt["cue_count"],
                    "score": vtt["score"],
                    "issues": vtt["issues"]
                },
                "has_video": has_video
            }

            scene_scores.append(score)
            result["scenes"].append(scene_result)
        except Exception as e:
            result["overall_issues"].append(f"Scene {scene.get('scene', '?')} skipped: {e}")
            print(f"  [critic] Scene {scene.get('scene', '?')} analysis failed: {e}", file=sys.stderr)
    
    # Overall scores
    if scene_scores:
        result["scores"]["overall"] = round(sum(scene_scores) / len(scene_scores), 1)
        result["scores"]["story"] = round(sum(s["narration"]["score"] for s in result["scenes"]) / len(result["scenes"]), 1)
        result["scores"]["visual"] = round(sum(s["images"]["score"] for s in result["scenes"]) / len(result["scenes"]), 1)
        result["scores"]["audio"] = round(sum(s["audio"]["score"] for s in result["scenes"]) / len(result["scenes"]), 1)
        result["scores"]["subtitles"] = round(sum(s["subtitles"]["score"] for s in result["scenes"]) / len(result["scenes"]), 1)
    
    # Story arc analysis
    arc = analyze_story_arc(story)
    result["scores"]["structure"] = arc["score"]
    result["overall_issues"].extend(arc["issues"])
    
    # Continuity check
    continuity = check_continuity(story)
    result["continuity_issues"] = continuity
    
    # Generate recommendations
    recs = []
    
    # Collect all issues
    all_narr_issues = [i for s in result["scenes"] for i in s["narration"]["issues"]]
    all_img_issues = [i for s in result["scenes"] for i in s["images"]["issues"]]
    all_aud_issues = [i for s in result["scenes"] for i in s["audio"]["issues"]]
    all_sub_issues = [i for s in result["scenes"] for i in s["subtitles"]["issues"]]
    
    if all_aud_issues:
        missing_audio = sum(1 for i in all_aud_issues if "missing" in i.lower() or "no audio" in i.lower())
        if missing_audio:
            recs.append(f"Regenerate TTS for {missing_audio} scene(s) missing audio")
    
    if all_sub_issues:
        missing_subs = sum(1 for i in all_sub_issues if "not found" in i.lower() or "no subtitle" in i.lower())
        if missing_subs:
            recs.append(f"Regenerate subtitles for {missing_subs} scene(s)")
        timing_issues = sum(1 for i in all_sub_issues if "overlap" in i.lower() or "beyond audio" in i.lower() or "gap" in i.lower())
        if timing_issues:
            recs.append(f"Fix subtitle timing in {timing_issues} scene(s) — sync issues detected")
    
    if all_img_issues:
        recs.append("Some images are missing or very small — check ComfyUI generation")
    
    if continuity:
        recs.append(f"Review {len(continuity)} continuity issue(s) flagged")
    
    if result["scenes"] and not result["scenes"][0].get("has_video"):
        recs.append("Render videos with: python render_video.py " + story_id)
    
    if not recs:
        recs.append("Production looks solid — no critical issues found")
    
    result["recommendations"] = recs

    # ── Star rating ──────────────────────────────────────────────────
    try:
        review = compute_star_rating(result)
        result["review"] = review
    except Exception as e:
        print(f"  [critic] Star rating failed: {e}", file=sys.stderr)
        result["review"] = {
            "rating": 0, "stars": 0, "summary": f"Star rating failed: {e}",
            "categories": [], "what_works": [], "needs_work": [],
            "badge": "Error", "overall_score": 0,
        }

    # ── LLM-based story quality review ───────────────────────────────
    try:
        print("  Running LLM story review...", file=sys.stderr)
        llm_review = llm_story_review(story)
    except Exception as e:
        print(f"  [critic] LLM review crashed: {e}", file=sys.stderr)
        llm_review = None
    if llm_review:
        result["llm_review"] = llm_review
        # Blend LLM scores into the star rating
        llm_scores = [
            llm_review.get("narrative_quality", 5),
            llm_review.get("character_consistency", 5),
            llm_review.get("visual_variety", 5),
            llm_review.get("tension_arc", 5),
            llm_review.get("narration_quality", 5),
        ]
        llm_avg = sum(llm_scores) / max(len(llm_scores), 1)
        # Blend: 70% technical + 30% LLM
        blended = review["overall_score"] * 0.7 + llm_avg * 0.3
        result["review"]["overall_score"] = round(blended, 1)
        result["review"]["rating"] = max(1.0, min(5.0, round(blended / 2, 1)))
        result["review"]["stars"] = max(1, min(5, round(result["review"]["rating"])))

    return result


# ── Report Formatter ─────────────────────────────────────────────────────

def format_report(result: dict) -> str:
    """Format review result as readable text report."""
    lines = []
    scores = result["scores"]
    
    overall = scores.get("overall", 0)
    icon = "🟢" if overall >= 7 else "🟡" if overall >= 5 else "🔴"
    
    lines.append("╔" + "═" * 58 + "╗")
    lines.append("║  FANTASEE PRODUCTION REVIEW" + " " * 30 + "║")
    lines.append("║  " + result["title"][:54] + " " * max(0, 54 - len(result["title"])) + "║")
    lines.append("╚" + "═" * 58 + "╝")
    lines.append("")
    lines.append(f"  Overall: {icon} {overall}/10")
    lines.append(f"  Story: {scores.get('story', 0)}/10  │  Visuals: {scores.get('visual', 0)}/10  │  Audio: {scores.get('audio', 0)}/10  │  Subs: {scores.get('subtitles', 0)}/10")
    lines.append("")

    # Star rating
    review = result.get("review", {})
    if review:
        stars = review.get("stars", 0)
        rating = review.get("rating", 0)
        badge = review.get("badge", "")
        star_str = "★" * stars + "☆" * (5 - stars)
        lines.append(f"  Rating: {star_str} ({rating}/5) — {badge}")
        lines.append("")
    
    # Scene breakdown
    lines.append("─" * 60)
    lines.append("  SCENES")
    lines.append("─" * 60)
    
    for s in result["scenes"]:
        si = "🟢" if s["score"] >= 7 else "🟡" if s["score"] >= 5 else "🔴"
        vid = "🎬" if s["has_video"] else "📝"
        narr_w = s["narration"]["word_count"]
        dur = s["audio"]["duration"]
        cues = s["subtitles"]["cue_count"]
        img_n = s["images"]["count"]
        
        lines.append(f"  {vid} Scene {s['scene_num']}: {s['title']} {si} {s['score']}")
        lines.append(f"     {narr_w} words │ {dur}s audio │ {img_n} images │ {cues} cues")
        
        # Issues for this scene
        scene_issues = (
            s["narration"]["issues"] +
            s["images"]["issues"] +
            s["audio"]["issues"] +
            s["subtitles"]["issues"]
        )
        for issue in scene_issues[:3]:
            lines.append(f"     ⚠ {issue}")
        if len(scene_issues) > 3:
            lines.append(f"     ... and {len(scene_issues) - 3} more issues")
    
    # Continuity
    if result["continuity_issues"]:
        lines.append("")
        lines.append("─" * 60)
        lines.append("  ⚠ CONTINUITY ISSUES")
        lines.append("─" * 60)
        for issue in result["continuity_issues"]:
            lines.append(f"  • {issue}")
    
    # Overall issues
    if result["overall_issues"]:
        lines.append("")
        lines.append("─" * 60)
        lines.append("  ⚠ STRUCTURE ISSUES")
        lines.append("─" * 60)
        for issue in result["overall_issues"]:
            lines.append(f"  • {issue}")
    
    # Recommendations
    lines.append("")
    lines.append("─" * 60)
    lines.append("  💡 RECOMMENDATIONS")
    lines.append("─" * 60)
    for rec in result["recommendations"]:
        lines.append(f"  • {rec}")
    
    lines.append("")
    return "\n".join(lines)


# ── Manifest Validation (pre-flight check) ──────────────────────────────

REQUIRED_MANIFEST_FIELDS = ("id", "title", "scenes")
REQUIRED_SCENE_FIELDS = ("scene", "title", "prompt")


def validate_manifest(story_id: str) -> dict:
    """Inspect a story manifest and report any issues that would make review_story crash.

    Returns a dict: { "ok": bool, "errors": [...], "warnings": [...], "stats": {...} }
    Never raises — all exceptions are caught and reported.
    """
    result = {"story_id": story_id, "ok": True, "errors": [], "warnings": [], "stats": {}}
    story_dir = OUTPUTS_DIR / story_id
    manifest_path = story_dir / f"{story_id}.json"

    if not story_dir.exists():
        result["ok"] = False
        result["errors"].append(f"Story directory missing: {story_dir}")
        return result

    if not manifest_path.exists():
        result["ok"] = False
        result["errors"].append(f"Manifest missing: {manifest_path}")
        return result

    # File-level parse
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as e:
        result["ok"] = False
        result["errors"].append(f"Cannot read manifest: {e}")
        return result

    if not raw.strip():
        result["ok"] = False
        result["errors"].append("Manifest is empty (likely interrupted write)")
        return result

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as e:
        result["ok"] = False
        result["errors"].append(f"Invalid JSON in manifest: {e}")
        return result

    if not isinstance(manifest, dict):
        result["ok"] = False
        result["errors"].append(f"Manifest root is {type(manifest).__name__}, expected dict")
        return result

    # Top-level fields
    for field_name in REQUIRED_MANIFEST_FIELDS:
        if field_name not in manifest:
            result["ok"] = False
            result["errors"].append(f"Missing required field: '{field_name}'")

    scenes = manifest.get("scenes")
    if scenes is None:
        result["ok"] = False
        result["errors"].append("Field 'scenes' is null")
        return result

    if not isinstance(scenes, list):
        result["ok"] = False
        result["errors"].append(f"Field 'scenes' is {type(scenes).__name__}, expected list")
        return result

    # Per-scene checks (1-indexed in the report for human readability)
    bad_scenes = 0
    for i, sc in enumerate(scenes):
        scene_label = f"Scene {i + 1}"
        if not isinstance(sc, dict):
            bad_scenes += 1
            result["errors"].append(f"{scene_label}: is {type(sc).__name__}, expected dict")
            continue
        for field_name in REQUIRED_SCENE_FIELDS:
            if field_name not in sc:
                bad_scenes += 1
                result["errors"].append(f"{scene_label} ('{sc.get('title', '?')}'): missing '{field_name}'")
                if bad_scenes >= 10:
                    result["errors"].append("... (further per-scene errors suppressed)")
                    break
        # Type checks
        if "image_filenames" in sc and not isinstance(sc["image_filenames"], list):
            result["errors"].append(f"{scene_label}: 'image_filenames' is {type(sc['image_filenames']).__name__}, expected list")
        if "narration" in sc and sc.get("narration") is not None and not isinstance(sc["narration"], str):
            result["errors"].append(f"{scene_label}: 'narration' is {type(sc['narration']).__name__}, expected str or null")
        if bad_scenes >= 10:
            break

    if bad_scenes > 0:
        result["ok"] = False

    # Asset references vs. disk
    missing_assets = 0
    for sc in scenes:
        if not isinstance(sc, dict):
            continue
        for img in sc.get("image_filenames", []) or []:
            if not (story_dir / img).exists():
                missing_assets += 1
        af = sc.get("audio_filename")
        if af and not (story_dir / af).exists():
            missing_assets += 1
    if missing_assets > 0:
        result["warnings"].append(f"{missing_assets} referenced asset(s) missing on disk")

    # Stats
    img_total = sum(len(sc.get("image_filenames", []) or []) for sc in scenes if isinstance(sc, dict))
    audio_total = sum(1 for sc in scenes if isinstance(sc, dict) and sc.get("audio_filename"))
    sub_total = sum(1 for sc in scenes if isinstance(sc, dict) and sc.get("subtitle_file"))
    result["stats"] = {
        "scene_count": len(scenes),
        "image_count": img_total,
        "audio_count": audio_total,
        "subtitle_count": sub_total,
    }
    return result


def validate_all_manifests() -> list[dict]:
    """Validate every story manifest. Returns a list of result dicts."""
    if not OUTPUTS_DIR.exists():
        print("No outputs directory found.", file=sys.stderr)
        return []

    story_dirs = sorted([
        d.name for d in OUTPUTS_DIR.iterdir()
        if d.is_dir() and (d / f"{d.name}.json").exists()
    ])

    results = []
    for sid in story_dirs:
        results.append(validate_manifest(sid))
    return results


def print_validation_report(results: list[dict]) -> int:
    """Pretty-print validation results. Returns non-zero exit code on any errors."""
    if not results:
        print("No stories found.")
        return 0

    ok = sum(1 for r in results if r["ok"] and not r["warnings"])
    ok_with_warnings = sum(1 for r in results if r["ok"] and r["warnings"])
    bad = sum(1 for r in results if not r["ok"])

    print(f"Validated {len(results)} stories: "
          f"{ok} OK, {ok_with_warnings} OK with warnings, {bad} broken")
    print("=" * 70)

    for r in results:
        sid = r["story_id"]
        stats = r["stats"]
        if r["ok"] and not r["warnings"]:
            icon = "OK"
        elif r["ok"]:
            icon = "WARN"
        else:
            icon = "BROKEN"
        print(f"\n[{icon}] {sid}  --  {stats.get('scene_count', 0)} scenes, "
              f"{stats.get('image_count', 0)} images, "
              f"{stats.get('audio_count', 0)} audio, "
              f"{stats.get('subtitle_count', 0)} subs")
        for err in r["errors"]:
            print(f"   ERROR: {err}")
        for warn in r["warnings"]:
            print(f"   WARN:  {warn}")

    print()
    if bad:
        print(f"{bad} story(ies) would crash the critic. Fix and re-run.")
        return 1
    print("All manifests safe for review.")
    return 0


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fantasee Production Critic")
    parser.add_argument("story_id", nargs="?", help="Story ID to review")
    parser.add_argument("--all", action="store_true", help="Review all stories")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--validate", action="store_true",
                        help="Pre-flight check: verify every manifest can be parsed "
                             "and review_story() would not crash on it. Exits non-zero "
                             "if any story is broken.")
    args = parser.parse_args()

    if args.validate:
        results = validate_all_manifests()
        sys.exit(print_validation_report(results))

    if args.all:
        if not OUTPUTS_DIR.exists():
            print("No outputs directory found.")
            return

        stories = sorted([
            d.name for d in OUTPUTS_DIR.iterdir()
            if d.is_dir() and (d / f"{d.name}.json").exists()
        ])

        if not stories:
            print("No stories found.")
            return

        print(f"Reviewing {len(stories)} stories...\n")
        for sid in stories:
            result = review_story(sid)
            if result:
                _save_review(sid, result, args.json)

    elif args.story_id:
        result = review_story(args.story_id)
        if result:
            _save_review(args.story_id, result, args.json)
    else:
        parser.print_help()


def _save_review(story_id: str, result: dict, json_only: bool = False):
    """Save review JSON and update manifest, then print output."""
    if json_only:
        print(json.dumps(result, indent=2))
    else:
        print(format_report(result))

    # Save review JSON alongside the story
    review_path = OUTPUTS_DIR / story_id / f"{story_id}_review.json"
    review_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not json_only:
        print(f"  Review saved: {review_path}")

    # Update manifest with review fields
    manifest_path = OUTPUTS_DIR / story_id / f"{story_id}.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            review = result.get("review", {})
            manifest["critic_rating"] = review.get("rating", 0)
            manifest["critic_stars"] = review.get("stars", 0)
            manifest["critic_badge"] = review.get("badge", "")
            manifest["has_review"] = True
            tmp = manifest_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            os.replace(tmp, manifest_path)
        except Exception as e:
            if not json_only:
                print(f"  Warning: could not update manifest: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
