# Unified Story Format Template

Use this markdown format to write all scene data for an animated story in a
single file. The `execute_code` parser extracts scene number, title, seed,
narration, and image prompt using this regex:

```
### Scene (\d+) — "([^"]+)" \(Seed: (\d+)\)\n
\*\*Narration:\*\* (.+?)\n\n
\*\*Image Prompt:\*\* (.+?)(?=\n\n### Scene|\n---|\Z)
```

## Template

```markdown
# Story Title — Subtitle (N Scenes)

## Character Bible

### Character Name — Role (POV Character)
- **Hair:** description
- **Eyes:** description
- **Face:** description
- **Build:** description
- **Outfit:** description
- **Personality:** description

### Location: Setting Name
- description

---

## ACT N: ACT TITLE (Scenes X-Y)

### Scene N — "Scene Title" (Seed: NNNN)
**Narration:** Narration text here. Write in prose, ~150 words/minute target.
For 25-scene density, aim for 60-90 words per scene (~15-25s spoken).

**Image Prompt:** Natural language prompt describing exactly what the image
should show at this narrated moment. Include: shot type, character descriptors
(from bible), action/pose, setting, lighting, mood. End with "High quality
anime illustration."

---

...repeat for all scenes...

---
```

## Rules

1. **Seeds**: Use `7000 + (project_number * 100) + scene_number`. For project 1:
   7101-7125. For project 2: 7201-7225. For project 3: 7301-7325. For project 4:
   7401-7425. Increment project_number for each new story to prevent seed
   collisions.
2. **Character bible**: Copy-paste character descriptors verbatim into every
   prompt that features that character.
3. **One scene per ### block**: The parser depends on this structure.
4. **Narration text**: No markdown inside the narration block. Just plain
   prose text between `**Narration:**` and the next blank line.
5. **Image prompt**: Natural language only. NO Danbooru tag lists.
6. **File naming**: Save as `story.md` inside a per-story directory under
   `E:\hermes\workspace\<story_slug>\`.
