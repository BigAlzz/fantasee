---
name: animated-storytelling
description: "Generate narrated animated story slideshow videos from a title — write story scenes, generate anime images via ComfyUI, add TTS voiceover, assemble with ffmpeg into a playable MP4."
version: 1.0.0
author: Hermes
platforms: [windows]
prerequisites:
  commands: ["ffmpeg"]
  running_services: ["ComfyUI on http://127.0.0.1:8188"]
  models: ["DreamShaper_8_pruned.safetensors (fantasy/painterly — DEFAULT)", "Counterfeit-V3.0_fp16.safetensors (anime)", "Realistic_Vision_V5.1_fp16-no-ema.safetensors (photorealistic) — see references/photorealistic-prompting.md", "DreamShaper V8 fantasy settings: DPM++ 2M Karras, 25 steps, CFG 7, see references/fantasy-prompting.md"]
---

# Animated Storytelling

Generate a fully narrated animated story video from a user-chosen title. The
pipeline writes a script, generates anime-style images per scene, adds TTS
voiceover, and assembles everything into an MP4 with fade transitions.

## Pipeline Overview

```
User picks title
    ↓
Agent writes story broken into 5-25 scenes
    ↓
Character bible created (consistent descriptors across scenes)
    ↓
Natural language prompts crafted per scene (shot type / subject / setting / lighting / art direction)
    ↓
ComfyUI generates one image per scene (fixed seeds)
    ↓
TTS generates narration audio per scene
    ↓
ffmpeg creates individual scene videos → concat with fades → final MP4
```

## When to Use

- User says "make a story" or "animated slideshow"
- User wants images + narration + video from a prompt
- User wants illustrated storytelling with their local ComfyUI setup
- Combining image gen, TTS, and video assembly into one output
- User wants more images / faster cuts — scale scene count up to 25-30

## Execution Philosophy

When the user asks for animated stories, **do not ask permission or clarifying
questions**. Write the stories, generate the images, produce the TTS, and
assemble the videos autonomously. The user wants results, not discussion. If
they want multiple stories, batch them.

**Cost optimization:** The user prefers keeping API costs low. DeepSeek is
expensive for large creative writing tasks. For story writing, use LM Studio
with a local model (e.g. `hermes-2-pro-mistral-7b`) when available — the
user has it configured at `http://192.168.50.10:1234/v1`. If the current
session is already on DeepSeek, just write the stories directly rather than
losing context switching mid-session; the image generation and TTS dominate
cost anyway. But for future sessions, default to the local model for creative
writing tasks.

## Before You Start

This host uses **Piper TTS** (local neural VITS) as the default TTS provider,
not Edge TTS. All TTS voice switching uses `tts.piper.*` config keys. See the
`piper-tts` skill for full tuning reference.

Default narration voice: `en_US-ryan-medium` (deep male). If you need a female
voice for multi-POV stories, download a female Piper voice model first.

## Step-by-Step

### Step 0: Determine scene count

Default is 10 scenes (~7-10 min). Scale based on user request:
- **5 scenes** = ~3-4 minutes (short story)
- **10 scenes** = ~7-10 minutes (standard episode)
- **25 scenes** = ~10-18 minutes (250% density, faster cuts)
- **30+ scenes** = ~15-25 minutes (short film)

More scenes = shorter narration per scene (~10-18s each instead of 30-50s).

### Step 1: Write story scenes

Write N scenes (per scene count above) with:
- **Scene number and title** (used for filenames, e.g. `arc_siege1`)
- **Narration text** (to be spoken by TTS — shorter for high-density stories)
- **Image prompt** (natural language, per comfyui skill prompting rules — MUST show the exact narrated moment, not a generic establishing shot)
- **Shot type** (wide/medium/close-up/cinematic)

### Step 2: Character bible

Before writing prompts, define all characters with exact descriptors:

| Field | Example |
|-------|---------|
| Hair | `short messy dark-brown hair` |
| Eyes | `sharp green eyes` |
| Outfit | `grey wool messenger coat with brass buttons, leather satchel` |
| Build | `lean determined face` |

Reuse these exact terms in every scene prompt.

### Step 3: Generate images (background batch)

Create a ComfyUI API-format workflow JSON per scene. Use the Counterfeit V3 checkpoint 
and natural-language prompts (NEVER Danbooru tag lists). See `references/prompting-guide.md`.

**Automatic workflow generation:** Use `scripts/generate_workflows.py` to parse your
`story.md` and generate all workflow JSONs + narration files in one shot. This
eliminates manual JSON creation, avoids the CLIP node reference bug, and builds
scene-appropriate negative prompts automatically:

```bash
python /e/hermes/skills/creative/animated-storytelling/scripts/generate_workflows.py <story_dir>
```

**Seed convention:** Use `seed = 7000 + (project_index * 100) + scene_number`.
Example: project 1 = 7101-7125, project 2 = 7201-7225, project 3 = 7301-7325,
project 4 = 7401-7425. Increment project_index for each new story to prevent
seed collisions.

**Seed registry** (what's been used — pick the next available):
| Index | Seeds | Story |
|--------|-------|-------|
| 1 | 7101–7110 | Ironwood Covenant (10 scenes) |
| 2 | 7201–7225 | The Last Rampart |
| 3 | 7301–7325 | The Bone Road |
| 4 | 7401–7425 | The Frost Grave |
| 5 | 7501–7525 | The Flood Tide |
| 6 | 7601–7625 | The Star Watchers |
| **7** | **7701–7725** | **NEXT STORY** |

**Batch via background terminal:** Write all workflow JSONs, then run generation 
as a single background shell command that calls `run_workflow.py` for each:

```bash
cd /e/hermes/workspace/<story_name> && for f in workflows/<prefix>_scene*.json; do
  echo "=== $(basename $f) ===" && \
  python /e/hermes/skills/creative/comfyui/scripts/run_workflow.py \
    --workflow "$f" \
    --host http://127.0.0.1:8188 \
    --output-dir /e/hermes/workspace/outputs \
    --timeout 600
done && echo "ALL DONE - <story_name> 25 scenes generated"
```

Key: `run_workflow.py` lives in the **comfyui skill's scripts directory**, not in the
workspace. Always use `--host`, `--output-dir`, and `--timeout 600` flags — without
`--output-dir` images land in ComfyUI's own output folder and won't be found by
the clip builder.

Use `terminal(background=true, notify_on_complete=true)` so you can write 
narrations and TTS while images generate. On RX 5600 XT / DirectML: 
~69s per image. A 25-scene story = ~29 minutes total gen time.

**Do NOT** generate images one at a time in foreground calls — you'll be stuck 
waiting. Batch them and use the wait time for narration writing + TTS.

### Step 4: TTS narration

Use `text_to_speech` tool for each scene's narration. Save with named output
paths like `E:\\hermes\\workspace\\outputs\\tts_storyname_s01.mp3`.

**Voice selection by MC gender (user rule):** Match the narrator voice to the
main character's gender. The default Piper voice is `en_US-ryan-medium` (male).
For female POV scenes, switch to a female Piper voice:

```bash
# Switch to female Piper voice (for female MC scenes)
hermes config set tts.piper.voice en_US-<female-voice>

# Switch back to male after TTS generation
hermes config set tts.piper.voice en_US-ryan-medium
```

Voice changes take effect on the next `text_to_speech` call — no restart
required.

**Narration audio quality tip:** If the speech sounds jerky or too fast, refer
to the `piper-tts` skill for tuning `noise_w_scale` (smooth timing) and
`length_scale` (speaking speed). Key fix: `noise_w_scale: 0.333` eliminates
the stuttery timing that Piper's default (0.8) produces.

### Step 5: Assemble video

**Phase A — Build clips as images land (incremental):** Use `scripts/build_clips.py`
periodically during image generation so the final concat is instant:

```bash
python /e/hermes/skills/creative/animated-storytelling/scripts/build_clips.py \
  <output_dir> <story_prefix> <tts_prefix> <clip_prefix>
```

Run this via `execute_code` each time you check image progress. When all 25
images + clips are ready, proceed to concat.

**Phase B — Concat all clips:** The simplest and most reliable approach on Windows:

```bash
# 1. Create a concat file with WINDOWS forward-slash paths (CRITICAL — see pitfall #12)
for i in $(seq -w 1 25); do
  echo "file 'E:/hermes/workspace/outputs/clip_NAME_${i}.mp4'"
done > concat_list.txt

# 2. Concat all clips (fast — stream copy, no re-encode)
ffmpeg -y -f concat -safe 0 -i concat_list.txt -c copy concat_raw.mp4

# 3. Add global fade-in/fade-out (re-encode only once)
ffmpeg -y -i concat_raw.mp4 \
  -vf "fade=t=in:d=1,fade=t=out:d=2:start_time=TOTAL_DURATION_MINUS_2" \
  -af "afade=t=in:d=1,afade=t=out:d=2:start_time=TOTAL_DURATION_MINUS_2" \
  -c:v libx264 -c:a aac final_video.mp4
```

This two-pass approach (concat copy + single fade pass) is FAR simpler than
building per-clip filter_complex chains for 25+ clips.

**Alternative — filter_complex with per-clip fades:** If crossfades between clips
are needed (not just fade-in/out), get each audio duration via `ffprobe`, then:

```bash
ffmpeg -y \
  -i clip1.mp4 -i clip2.mp4 ... \
  -filter_complex "\
    [0:v]fade=t=in:st=0:d=0.8,fade=t=out:st=END-0.8:d=0.8[v0];\
    [1:v]fade=t=in:st=0:d=0.8,fade=t=out:st=END-0.8:d=0.8[v1];\
    ...\
    [v0][a0][v1][a1]...concat=n=N:v=1:a=1[outv][outa]" \
  -map "[outv]" -map "[outa]" \
  -c:v libx264 -preset medium -crf 23 -c:a aac -b:a 128k -pix_fmt yuv420p \
  output.mp4
```

Where END = audio_duration - 0.8, and N = number of scenes. This is reliable on
Linux/macOS but the filter string becomes unwieldy beyond ~10 clips.

## Scene Templates

### Establishing shot (landmarks/locations)
> A wide establishing shot of [location] at [time of day]. [Visual details of
> architecture/nature]. [Lighting description]. [Atmosphere, mood]. Beautiful
> background art, atmospheric perspective, cinematic composition, high quality
> anime illustration.

### Character portrait
> A medium character portrait of [name], [hair] and [eyes], wearing [outfit].
> [Setting details]. Soft rim lighting, expressive eyes with detailed
> reflections, fine hair strands, clean linework, high quality anime
> illustration.

### Action scene
> A dynamic [wide/medium] shot of [scene] at [time of day]. [Action details —
> character movements, environmental effects, chaos]. Dramatic angle, motion
> energy, particle effects, cinematic composition, dramatic lighting, high
> quality anime art.

## Prompting Rules (CRITICAL)

**Default art style: Fantasy / painterly** with DreamShaper V8. The user prefers
this over photorealistic or anime. Only use anime (Counterfeit V3) or
photorealistic (Realistic Vision) if explicitly requested.

### Fantasy style (DreamShaper V8 — DEFAULT)
Prompt prefix: `"digital painting of "` followed by natural language.
Sampler: DPM++ 2M Karras, 25 steps, CFG 7, 512×768.
Negative prompt: `ugly, blurry, low quality, deformed, bad anatomy, watermark, text, signature, distorted, photograph, realistic photo, anime, cartoon, manga, 3d render, plastic, doll`

### Anime style (Counterfeit V3)
```
A medium portrait shot of [character name], a [age/build descriptor] with [hair] and [eyes], wearing [outfit details]. [Character] [specific action or pose -- show the narrated moment]. [Setting with lighting details]. [Mood/atmosphere]. High quality anime illustration with clean linework.
```

### Each image MUST illustrate the specific narrated moment
Read the narration for the scene. What is happening at that exact beat? Show it. Not a generic establishing shot, not a different moment. If the narration says "he discovered documents in an underground tunnel," the image shows him holding a lantern, looking at documents, in an underground tunnel.

### Shot types
- **Wide establishing shot** — landscapes, cityscapes, full battlefields
- **Medium shot** — character action, two-character interactions
- **Close-up / portrait** — emotional beats, character introductions
- **Low angle** — power, awe, menace
- **Cinematic wide** — epic moments, covenant scenes

### Negative prompts
Tailor per scene. Add scene-specific negation:
- Battle scenes: `peaceful, quiet, calm, daytime, sunny`
- Dark/tension scenes: `bright daylight, cheerful, sunny, outdoor`
- Nature scenes: `technology, metal, modern buildings, cars`
- Hope scenes: `night, dark, gloomy, despair`

### Reference
Full guide with examples: `references/prompting-guide.md`

## Narrative Structure

### Three-Act Arcs (5-10+ scenes)
For longer stories, use a three-act structure:
- **Act 1 (2-4 scenes):** Establish both worlds / characters separately
- **Act 2 (3-5 scenes):** Conflict escalates through encounters
- **Act 3 (2-4 scenes):** Cooperation, understanding, resolution

### Four-Act Structure (25 scenes)
For high-density 25-scene stories, use the four-act template in
`references/story-structure-25.md` — battle-tested across 4 stories:
- **Act 1 (Scenes 1-6):** The Setup — protagonist, inciting incident, commitment
- **Act 2 (Scenes 7-14):** The Journey — escalation, allies, setback, lowest point
- **Act 3 (Scenes 15-21):** The Turning Point — recovery, transformation, confrontation
- **Act 4 (Scenes 22-25):** Resolution & Legacy — climax, new order, hope, final shot

Each scene in a 25-scene story gets ~10-25s narration. Cut faster between visuals;
let images carry more storytelling weight than narration.

### Scene count guidelines
- 5 scenes = ~3-4 min (short story) — narrations 20-45s each
- 10 scenes = ~7-10 min (episode) — narrations 15-40s each
- 25 scenes = ~10-18 min (high-density) — narrations 10-25s each, faster cuts
- 30+ scenes = ~15-25 min (short film) — narrations 10-20s each

For high-density stories (25+ scenes): write shorter, punchier narration. 
Each scene image needs ~10-20s of audio. Let images carry more storytelling 
weight — characters get more screen time, events get more visual beats.

Write narrations at ~150 words per minute of spoken time. Each scene image supplements ~10-35 seconds of audio depending on density.

## Pitfalls

1. **DirectML limitation** — S3-DiT models (Z-Anime, Z-Image) do NOT work on
   DirectML. Use SD 1.5-based anime models (Counterfeit V3, Anything V5) only.
2. **Character consistency** — SD 1.5 cannot guarantee the same face across
   seeds. The character bible technique gives the best chance but is not
   perfect. True consistency requires IP-Adapter or LoRA.
3. **Negative prompt noise** — scene-specific negative terms help. Add `modern
   buildings, cars` for fantasy; `peaceful, quiet` for battle; `bright daylight`
   for dark scenes.
4. **Fade timing precision** — xfade filter in ffmpeg is unreliable with looped
   image inputs. Use individual clips with fade-in/fade-out + concat instead.
5. **Total generation time** — each image takes ~69s on RX 5600 XT / DirectML.
   A 5-scene story = ~6 minutes image gen + ~30s TTS + ~10s ffmpeg.
   A 10-scene story = ~12 minutes image gen + ~60s TTS + ~15s ffmpeg.
   Use background generation (`terminal(background=true, notify_on_complete=true)`)
   and write narrations during the wait.
6. **CLIP node reference (CRITICAL)** — `CheckpointLoaderSimple` outputs are
   `[MODEL, CLIP, VAE]` at array indices `[0, 1, 2]`. Both positive AND
   negative `CLIPTextEncode` nodes MUST reference the CLIP output at index 1
   (`clip: ["1", 1]`). Using index 0 (`["1", 0]`) references MODEL and causes
   a `return_type_mismatch` validation error. Always verify: positive encode
   uses `["1", 1]`, negative encode uses `["1", 1]`, VAE uses `["1", 2]`.
   See `references/workflow-structure.md` for the canonical node layout.
7. **Batch submission resilience** — if a batch run fails early (e.g. validation
   error on the first JSON), all remaining scenes are lost. Verify one workflow
   manually before submitting the full batch, or wrap the loop so errors are
   non-fatal (continue on failure, log the failing scenes).
8. **Silent batch truncation** — background ComfyUI batches can exit early with
   partial results (e.g., 7/25 images generated, exit code 0, no error visible).
   The process looks complete but images are missing. ALWAYS verify image count
   after batch completion: count `.png` files matching each story prefix. If
   count < expected, find the gap and resubmit only the missing scenes. Never
   assume a completed batch produced all images.
9. **Workflow generation at scale** — for multi-story / 25+ scene projects, use
   `execute_code` to parse the unified story markdown and generate all workflow
   JSONs + narration files programmatically (see `templates/story-format.md` for
   the parseable markdown format). This avoids hand-writing 50+ JSONs and
   eliminates copy-paste errors like the CLIP node bug. The parser uses regex to
   extract scene number, title, seed, narration, and prompt from each scene
   block, then generates workflow JSONs with correct node references.
10. **Incremental clip building** — build individual scene clips as images land,
    don't wait for all 25. Use `execute_code` to periodically scan for new
    images, build the corresponding ffmpeg clip, and track progress. When the
    final image arrives, the concat step takes seconds. This turns a 2-minute
    post-batch assembly into near-instant final video creation.
11. **ComfyUI DirectML VRAM limitations** — on RX 5600 XT (6 GB), only 1 image
    can generate at a time. The queue processes sequentially. `run_workflow.py`
    submits one job, polls for completion, then submits the next — this is
    correct and expected. Do not try to submit multiple concurrent jobs; they
    will just sit in the queue.
11b. **System crash risk on AMD DirectML** — long image generation sessions
     (50+ images) have caused complete system crashes on this host (RX 5600 XT,
     DirectML). The GPU driver can time out or the system can freeze entirely
     during extended DirectML workloads. Mitigations: (a) submit images in
     batches of 25 rather than 100+ at once; (b) if the PC reboots mid-batch,
     ComfyUI auto-recovers but in-progress images are lost — resubmit only the
     missing scenes; (c) the incremental clip-building approach (pitfall #10)
     ensures previously-completed work is never lost even if the system crashes
     at image 19 of 25.
12. **Windows ffmpeg concat path format (CRITICAL)** — The ffmpeg concat demuxer
    requires Windows forward-slash paths in the concat file (e.g.,
    `file 'E:/hermes/workspace/outputs/clip_01.mp4'`). MSYS-style paths
    (e.g., `file '/e/hermes/workspace/outputs/clip_01.mp4'`) cause
    \"Error opening input file\". Always write concat lists with
    Windows forward-slash paths on this host. Test with a single-clip concat
    before attempting 25+ clip assemblies.
13. **Multi-story orchestration** — when generating 3+ stories simultaneously,
    use incremental clip building (scripts/build_clips.py) to avoid a pile-up
    at the end. As each story's images complete, immediately build any remaining
    clips and assemble the final video. Do not let completed stories sit
    unassembled while waiting for other stories' images.
14. **Model-specific settings are NOT interchangeable** — anime (Counterfeit V3),
    fantasy (DreamShaper V8), and photorealistic (Realistic Vision V5.1) models
    require completely different sampler, scheduler, step count, prompt structure,
    and negative prompts. Do NOT reuse workflow JSONs across model families.
    See the reference docs for each style's full config:
    • `references/fantasy-prompting.md` — DreamShaper V8 (default)
    • `references/prompting-guide.md` — Counterfeit V3 (anime)
    • `references/photorealistic-prompting.md` — Realistic Vision V5.1
    Key diffs: DreamShaper uses `dpmpp_2m` + `karras` + 25 steps + CFG 7 + prefix
    `"digital painting of"`; Counterfeit uses `euler` + `normal` + 30 steps +
    CFG 5 + natural language; Realistic Vision uses `dpmpp_2m` + `karras` +
    25 steps + CFG 7 + prefix `"RAW photo, "`.

## Multi-Character Voice Switching (within one story)

When a story has multiple POV characters of different genders (e.g., male MC
Aldric + female POV Lira), switch voices mid-story. This host uses **Piper TTS**
by default (see `piper-tts` skill). Example with gender-matched Piper voices:

```bash
# Generate male MC scenes with male Piper voice
hermes config set tts.piper.voice en_US-ryan-medium
text_to_speech(text=...)

# Switch to female Piper voice for female POV scenes
hermes config set tts.piper.voice en_US-<female-voice>
text_to_speech(text=...)

# Switch back for remaining male scenes
hermes config set tts.piper.voice en_US-ryan-medium
text_to_speech(text=...)
```

Voice changes take effect on the next `text_to_speech` call — no restart needed.
The final concat ordering must interleave the files correctly by scene sequence.

> **Note:** If you need a female Piper voice, it must be downloaded first.
> See the `piper-tts` skill for downloading new voice models.

## Extending Existing Stories

When adding new scenes to an already-complete story (e.g., inserting 5 Lira POV 
scenes into a 25-scene siege story):

### Procedure
1. **Read the existing story.md** — find logical insertion points (after character 
   report scenes, during lulls between action beats, etc.)
2. **Generate new scenes via subagent** — send all new scenes in one `delegate_task` 
   with context about existing characters, tone, and insertion points
3. **Patch story.md** — use `patch` with the exact surrounding block text to insert 
   new scene blocks. Update the scene count in the header.
4. **Extend seed range** — use the next available seeds within the project's existing 
   range (e.g., project 2 = 7201-7225 → new scenes = 7226-7230)
5. **Generate workflow JSONs for new scenes** — write a Python script to create 
   workflow JSONs. Use irregular indices matching the insertion positions 
   (e.g., `scene2b`, `scene10b` during post-processing rename). The existing 
   `scripts/generate_workflows.py` expects sequential `(Seed: NNNN)` markers — 
   for inserted scenes with non-sequential IDs, write the JSONs manually via 
   `execute_code`.
6. **Generate TTS** — switch voice per-POV as needed (see Multi-Character Voice 
   Switching above). Save with matching filenames.
7. **Build assembly script** — the final concat order must interleave old and new 
   clips by scene sequence. Example order for 30 scenes: 
   `1,2,2b,3,4,5,6,7,8,9,10,10b,11,12,12b,13,14,...`
8. **Batch generate images** — run all 30 (old + new) workflows together via 
   `run_workflow.py` in a loop. The old workflows regenerate with the same seeds, 
   producing the same images.

### Concat ordering for non-sequential indices
The concat list must be sorted by scene sequence, not alphabetically or 
numerically. For idx-based sorting, map each scene to a float index:
- scene 1 = 1.0, scene 2 = 2.0, scene 2b = 2.5
- scene 10 = 10.0, scene 10b = 10.5

Then sort by this float index for correct playback order.

Full reference: `references/extending-existing-stories.md`

## Related Skills

- `comfyui` — engine for image generation (load this before running)
- `birthday-card` — single-image generation variant
- `local-subagent-story-generation` — delegate scene writing to local LM Studio
- `piper-tts` — Piper TTS configuration and narration tuning

## References & Templates

- `references/workflow-structure.md` — canonical ComfyUI node layout with output
  indices (MODEL=0, CLIP=1, VAE=2). Use this when generating workflow JSONs to
  avoid the CLIP node reference bug.
- `references/prompting-guide.md` — full natural-language prompting guide for
  Counterfeit V3 (anime).
- `references/fantasy-prompting.md` — settings, prompt structure, and negative prompt for DreamShaper V8 (fantasy/painterly). DEFAULT style — use this unless the user asks for anime or photorealistic.
- `references/photorealistic-prompting.md` — settings, prompt structure, and
  negative prompt for Realistic Vision V5.1 (photorealistic). Use this when
  the user asks for photorealistic art instead of anime.
- `references/story-structure-25.md` — 4-act structure template for 25-scene
  stories with character bible format and narration pacing.
- `templates/story-format.md` — unified markdown template for writing all scene
  data (narration + prompts + seeds) in one parseable file.

## Scripts

- `scripts/generate_workflows.py` — parse a `story.md` and generate all workflow
  JSONs + narration files in one shot. Usage:
  `python scripts/generate_workflows.py <story_dir> [seed_fallback]`.
  Run this after writing the story — it handles the CLIP node references
  correctly and builds scene-appropriate negative prompts automatically.
- `scripts/build_clips.py` — scan the output directory for new images and build
  individual scene video clips (image + TTS audio via ffmpeg). Usage:
  `python scripts/build_clips.py <output_dir> <story_prefix> <tts_prefix> <clip_prefix>`.
  Run this periodically while images generate to build clips incrementally —
  when the last image lands, the final ffmpeg concat takes seconds.
