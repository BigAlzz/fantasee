---
name: story-scene-generation
description: Generate new scenes for The Last Rampart (or similar narrative projects) using subagents + Humanizer pass
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [writing, scenes, story, the-last-rampart, humanizer, narrative]
    category: creative
---

# Story Scene Generation Pipeline

Generate new scenes for a narrative story project (designed for The Last Rampart but adaptable). The pipeline:

1. Load existing story file for context
2. Identify gaps / character moments / plot expansions
3. Delegate scene writing to subagents with strict formatting constraints
4. Humanize all generated narration to strip AI patterns
5. Insert scenes into the story file at correct positions

## When to use

- User asks to "add more scenes" or "fill in gaps" in The Last Rampart or similar sequential story files
- User wants new character POV moments (Lira, Korgath, Aldric interludes)
- User wants to expand an act with additional scenes between existing ones
- After generating, always offer to save the workflow if it was a new pattern

## Prerequisites

- Story file exists in a known path (e.g., `E:\hermes\workspace\siege_story\story.md`)
- File follows the established format:
  - `# Title — Story Name (N Scenes)`
  - `### Scene N — "Title" (Seed: NNNN)`
  - `**Narration:** ...` (80-120 words for standard scenes)
  - `**Image Prompt:** ...` (detailed, cinematic anime style)
  - Interleaved POV scenes use letter suffixes (5b, 10c, etc.)
  - Acts as H2 section breaks

## Scene Format Constraints

Each scene MUST follow this exact format:

```
### Scene N — "Title" (Seed: NNNN)
**Narration:** [80-120 words, single paragraph, third person or first person for POV scenes]
**Image Prompt:** [detailed visual description, 2-4 sentences, ends with "Anime style, painterly" or similar]
```

For POV scenes (letter suffix: 5b, 10c, 14b, 22b):
- Use first-person narration ("I")
- Keep raw and grounded — no poetic flourishes, no "carries a piece of me" style language
- Show interiority: physical sensations, specific memories, immediate reactions

## Workflow Steps

### 1. Load context
```
read_file(path="story.md")
```
Scan the entire file. Note:
- Current scene count (from title line)
- Where each act falls
- Which characters are underrepresented
- What plot beats could use expansion
- The exact text at each insertion point (you'll need it for patching)

### 2. Plan insertion points
Determine where new scenes go. Good opportunities:
- **Pre-battle character moments** — Lira POV before the fighting starts (after Scene 5)
- **Enemy-side perspective** — Korgath war council scenes (after Scene 10, Scene 21)
- **Humanity amid war** — Aldric with wounded soldiers, quiet moments between assaults (after Scene 14)
- **Aftermath/transition** — Korgath's decision to retreat (after Scene 21b)
- **Epilogue hooks** — What comes after the siege (after Scene 25)

### 3. Delegate scene generation to subagents
Use `delegate_task` for each scene. The subagent prompt MUST include:

```text
Context: [character bible excerpts, existing scenes for reference, tone guidance]

Goal: Write one scene for [story name] following this exact format:

### Scene N — "Title" (Seed: NNNN)
**Narration:** [80-120 words ONLY — this is strictly enforced]
**Image Prompt:** [detailed prompt for anime-style image generation]

Requirements:
- Narration must be 80-120 words. Count your words.
- For POV scenes, use first person. Raw, grounded voice — no poetic language.
- No em dashes in narration (use commas or periods instead).
- No "as if", "almost as though", "seemed to" constructions.
- No generic observations about "war" or "human nature" — stay in the character's head.
- Image prompts: describe framing, lighting, composition, character details.
  End with "Anime style, painterly" or "High quality anime illustration."
- Seed number: use [N+1 from highest existing seed]
```

CRITICAL: Subagents often generate 400-500 word narrations. You MUST:
- Include the word count constraint in the task
- Verify word count after generation
- Trim any that exceed ~130 words before humanizing

### 4. Humanize all narration
Load the Humanizer skill:
```
skill_view(name="humanizer")
```

For each scene's narration, apply the Humanizer patterns:
- Strip: -ing participial phrases ("highlighting...", "showcasing...", "ensuring...")
- Strip: copula avoidance ("serves as", "stands as", "marks a")
- Strip: negative parallelism ("It's not about X, it's about Y")
- Strip: rule of three
- Strip: em dashes (replace with commas or periods)
- Strip: elegant variation / synonym cycling
- Strip: hedging ("almost", "seemed", "perhaps")
- Strip: cliché similes ("like caged wolves", "face as pale as ash")
- Add: short punchy sentences
- Add: specific physical detail over abstract emotion
- Add: natural rhythm — vary sentence length

For image prompts, leave mostly as-is — they're technical instructions, not prose.

### 5. Generate unique seeds
Use seeds for each scene, starting from the highest existing seed + 1. For The Last Rampart, seeds are in the 7200-7300 range. Current highest: 7225, so new scenes use 7226-7230.

### 6. Insert into story file
Use `patch` for each insertion. Strategy:

For each insertion, find a unique string at the exact insertion point and replace it with itself + the new scene. Good anchor strings:

- **End of a scene's image prompt** — the last line before the next header
- **Act separators** — `---` between acts
- **The title line** — for updating scene count at the end

Pattern:
```python
old_string = "[unique text just before insertion point]"
new_string = old_string + "\n\n" + new_scene_text
```

After all insertions, update the title:
```
old_string = "# The Last Rampart — Siege Story (35 Scenes)"
new_string = "# The Last Rampart — Siege Story ({new_count} Scenes)"
```

### 7. Verify
Read the end of the file to confirm clean insertion. Check that:
- All new scenes render in the correct order
- No duplicate seeds
- Title reflects correct total count

## Pitfalls

- **Subagents over-write**: They almost always produce 300-500 word narrations despite being told 80-120. You MUST check word count and trim ruthlessly. The narration is meant to be a tight paragraph, not a full story beat with dialogue.
- **Code blocks**: Subagents sometimes wrap output in ```markdown code fences. Strip these before inserting.
- **Seed conflicts**: Keep a running tally of all seed numbers used. The file uses 7201-7225 + the new ones.
- **Delegation provider**: If testing locally, verify `delegation.provider` in config.yaml is set correctly. Subagents may still use the main provider if delegation config isn't properly inherited.
- **Patch uniqueness**: When inserting near similar text (e.g., two "High quality anime illustration" lines), include enough surrounding context to guarantee uniqueness.
- **Scene 26 + epilogue**: The last scene in the file is special — it's the emotional close. If adding a Scene 26 that extends past the original ending, make sure it earns its place. Don't add a meaningless extra scene just to hit a number.

## Verification

After insertion, do one final read of the file to confirm:
- All scenes are in order (numerically, chronologically by act)
- No duplicate content
- Narration is properly humanized — read a few lines aloud to check they sound like a person wrote them
