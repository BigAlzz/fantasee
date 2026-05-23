# Extending Existing Stories

When adding new scenes to a story that already has generated images, TTS,
and workflows (e.g., inserting 5 Lira POV scenes into a 25-scene siege story).

## Why This Happens

- User wants more detail in a specific character's arc
- A secondary POV character needs screen time
- Missing emotional beats between action sequences
- Story feels too short — needs density

## Full Procedure

### 1. Read the Existing Story

Read the full `story.md` to understand:
- Current scene count and structure
- Logical gaps (after character introductions, during lulls, between acts)
- The scene format (narration + image prompt pattern)

**Good insertion points:**
- After a character's report/exposition scene (add POV reaction)
- Between major battle beats (add quiet character moment)
- At night (add tension/sleep scenes)
- During travel or regrouping sequences

### 2. Generate New Scenes

Send all new scenes in a single `delegate_task` with context including:
- Character names, descriptions, and existing voice
- Tone and style of the existing story
- Insertion positions and what happens before/after
- Desired word count per scene (~80-120 words for high-density stories)

### 3. Patch story.md

Use `patch` (mode='replace') to insert new scene blocks. The old_string must
include enough surrounding context for uniqueness:

```
old_string="""The Signal

Narration text...
```
(include the image prompt and adjacent content from the existing story)
```
new_string="""[existing content before insertion]
<!-- INSERT: Scene 2b — After the Report -->

### Scene 2b: After the Report

Narration text for the new scene...

*Image prompt: ...*

<!-- END INSERT -->
[existing content after insertion]"""
```

Then update the header's scene count (e.g., `25 Scenes` → `30 Scenes`).

### 4. Extend Seed Range

Use the next available seeds within the project's existing range:
- Original project range: 7201-7225 (25 scenes)
- New scenes: 7226-7230 (5 additional)

The seed convention is: `7000 + (project_index * 100) + scene_index`
where scene_index is the Nth scene within that project (1-indexed).

### 5. Generate Workflow JSONs

The existing `generate_workflows.py` expects sequential scene indices with
`(Seed: NNNN)` markers — it won't handle irregular indices like `2b`, `10b`.

Instead, write a Python script via `execute_code` that:
1. Reads a template workflow JSON (from an existing scene)
2. For each new scene, creates a copy with:
   - Updated `filename_prefix` (e.g., `siege_scene2b_After_the_Report`)
   - Updated seed
   - Updated positive prompt
   - Updated negative prompt (scene-appropriate)
3. Saves to `workflows/` with the irregular filename

Key workflow node IDs:
- Node `"1"` = `CheckpointLoaderSimple` (checkpoint name)
- Node `"4"` = positive `CLIPTextEncode` (text)
- Node `"5"` = negative `CLIPTextEncode` (text)
- Node `"6"` = `KSampler` (seed and batch settings)
- Node `"7"` = `SaveImage` (filename_prefix)
- Node `"3"` = empty latent (width/height)

**CLIP node reference (CRITICAL):** Both positive AND negative CLIPTextEncode
nodes MUST reference the CLIP output at array index 1: `["1", 1]`.
Index 0 references MODEL and causes a `return_type_mismatch` validation error.

### 6. Generate TTS with Multi-Voice

Switch voices between characters mid-story using `hermes config set tts.edge.voice`:

```
hermes config set tts.edge.voice en-US-GuyNeural  → male MC scenes
text_to_speech(scene_01.mp3)
text_to_speech(scene_02.mp3)

hermes config set tts.edge.voice en-US-AriaNeural → female POV scenes
text_to_speech(scene_2b.mp3)

hermes config set tts.edge.voice en-US-GuyNeural  → back to male
text_to_speech(scene_03.mp3)
...
```

Save each TTS file with a meaningful output path matching the scene index.

### 7. Concat Ordering (CRITICAL)

The concat list must sort scenes by narrative sequence, not alphabetically.
Map irregular indices to float sort keys:

```
scene 01  → 1.0    (Aldric — male)
scene 02  → 2.0    (Aldric — male)
scene 2b  → 2.5    (Lira — female, inserts between 2 and 3)
scene 03  → 3.0    (Aldric — male)
...
scene 10  → 10.0   (Aldric — male)
scene 10b → 10.5   (Lira — female)
scene 11  → 11.0   (Aldric — male)
```

Build the concat list in order of these sort keys. When creating the assembly
script, iterate the scenes in this float-sorted order.

### 8. Image Generation

Regenerate ALL scenes (not just new ones) — the old workflows produce the same
images with the same seeds. Batch all 30 workflows together:

```python
for f in sorted(workflow_jsons, key=scene_sort_key):
    subprocess.run(["python", run_wf, "--workflow", f, "--host", ...])
```

This ensures consistent aesthetic across old and new images (same batch, same
generation session).

### 9. Verification Checklist

After generation, verify:
- [ ] All workflow JSONs exist (old count + new count)
- [ ] All TTS MP3s exist matching scene indices
- [ ] Concat list has correct ordering (float-sorted)
- [ ] Image count matches expected total
- [ ] Multi-voice files are in correct POV positions
- [ ] Header in story.md reflects new total scene count
