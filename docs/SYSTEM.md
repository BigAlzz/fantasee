# Fantasee System Documentation

## Overview

Fantasee is a local AI story generation and viewing system. It takes a story concept, writes a multi-scene narrated story, generates scene images through ComfyUI, generates narration audio, aligns subtitles, and presents the result in a Netflix-style browser/player.

The app is intentionally file-based. There is no application database. Story state lives in JSON manifests under `stories/<story-id>/`, with generated assets stored beside the manifest.

## Runtime Components

| Component | Role | Default |
|---|---|---|
| FastAPI server | Web app, API, WebSocket progress, generation orchestration | `http://127.0.0.1:8765` |
| ComfyUI | Image generation workers | `8188+` |
| LLM provider | Title, description, outline, seed suggestions | OpenAI-compatible API via `generate_story.py` |
| TTS provider | Narration WAV generation | `tts_utils.py` |
| Whisper/subtitle path | Subtitle alignment | `generate_subtitles.py` |
| FFmpeg | Video render and Plex export | local executable |

## Storage Layout

New stories live in `stories/`. The legacy `outputs/` tree is still read as a fallback by `story_storage.existing_story_dir()`.

```text
stories/
  <story-id>/
    <story-id>.json              story manifest
    <story-id>_s01_...png        scene images
    tts_<story-id>_s01.wav       narration audio
    subs_<story-id>_s01.json     subtitle segments
    assets/title/                title slide assets
    working/                     drafts, prompts, logs, workflows
    final/plex/                  Plex export package
```

Important paths:

| Path | Purpose |
|---|---|
| `stories/.trash/` | Backups from destructive story actions |
| `Background/` | Background music library |
| `workflow.json` | Default ComfyUI API workflow used by image generation |
| `docs/` | System and architecture documentation |

## Story Manifest

Each story has a single JSON manifest named `<story-id>.json`. A typical scene contains:

```json
{
  "scene": "01",
  "title": "The Fading Light",
  "prompt": "Visual prompt sent to ComfyUI...",
  "narrative": "Short scene summary...",
  "narration": "Voiceover text...",
  "narration_text": "Voiceover text...",
  "seed": 123456,
  "image_filenames": ["story_s01_01_00001_.png"],
  "audio_filename": "tts_story_s01.wav",
  "audio_duration": 40.96,
  "subtitle_file": "subs_story_s01.json"
}
```

## Generation Pipeline

`generate_story.run_pipeline()` is the full-story pipeline:

1. Resolve API key and generation parameters.
2. Generate title and story id.
3. Create title slide and early manifest.
4. Generate story description.
5. Generate scene outline and narration.
6. Generate scene images through ComfyUI.
7. Generate TTS narration per scene.
8. Generate subtitle timing per scene.
9. Save final manifest.

The server starts generation in the background and streams progress over `WS /ws` as `task_update` events.

### Visual continuity and completion supervision

The final image prompt is commissioned separately from the story-writing call. It receives one concrete visual sentence, bounded continuity anchors, and the previous scene's visual reference. The visual director must preserve recurring characters, clothing, vehicles, devices, buildings, rooms, and landscapes without adding unrelated subjects.

After draft generation, the durable completion worker runs bounded maintenance iterations. Each iteration scans the completion contract, repairs only the missing dependency, and verifies the result again. An unchanged completion signature stops the loop as a terminal no-progress failure. Optional critic-driven improvement runs only after structural completion and marks affected renders and releases stale before the supervisor rebuilds them.

Supervisor settings:

- `FANTASEE_SUPERVISOR_MAX_ITERATIONS` — maximum completion iterations, default `3`.
- `FANTASEE_AUTO_CRITIC` — enable the post-completion critic loop, default disabled.
- `FANTASEE_CRITIC_MAX_ROUNDS` and `FANTASEE_CRITIC_MAX_SCENES` — bound critic work when enabled.

## Seed Suggestions

When the Create modal seed slider is set above `1`, clicking **Generate N Seeds** calls `POST /api/seed-suggestions`. That endpoint asks the LLM for distinct story ideas, shows a picker, and only starts generation after the user chooses one or more seeds.

This is intentionally a two-step flow:

1. LLM brainstorms N seeds.
2. User chooses one seed for one story, or multiple seeds for a sequential queue.

## ComfyUI Workflow

Image generation requires a ComfyUI API-format workflow. Fantasee resolves it in this order:

1. Explicit `workflow_path` passed by a caller.
2. `FANTASEE_WORKFLOW_PATH` environment variable.
3. `stories/<story-id>/working/workflows/*.json` when `FANTASEE_CURRENT_STORY_DIR` is set.
4. `workflow.json` beside `comfyui_utils.py`.

The workflow must contain these node types:

| Node type | Used for |
|---|---|
| `CheckpointLoaderSimple` | Checkpoint selection |
| `CLIPTextEncode` | Positive and negative prompt injection |
| `EmptyLatentImage` | Width and height injection |
| `KSampler` | Seed, sampler, scheduler, steps, CFG injection |
| `VAEDecode` | Decode samples to image |
| `SaveImage` | Filename prefix injection |

The negative `CLIPTextEncode` node is detected by placeholder text containing at least one of `ugly`, `blurry`, `deformed`, or `low quality`. The bundled `workflow.json` includes these words in the negative placeholder so `inject_prompt()` can identify it reliably.

## Image Quality Defaults

Image settings are controlled in `comfyui_utils.QUALITY_SETTINGS`:

```python
sampler = "dpmpp_2m"
scheduler = "karras"
steps = 30
cfg = 7.5
width = 896
height = 512
```

Every prompt also receives `DEFAULT_POSITIVE_GUARD_SUFFIX`, which strongly biases SD 1.5 toward detailed faces, eyes, portrait lighting, medium-shot focus, and high-detail output. `DEFAULT_NEGATIVE` includes anatomy, face, eye, nose, watermark, and artifact blockers.

## ComfyUI Workers

Fantasee can use multiple ComfyUI workers. Worker selection happens in `comfyui_utils.py`.

Priority order:

1. Healthy GPU workers.
2. Healthy CPU workers.
3. Healthy manual workers of unknown kind.

Unconstrained image work prefers healthy GPU workers and round-robins across the healthy pool for throughput. Jobs with an explicit capability requirement are strict: a GPU job can only use a GPU worker, and a CPU job can only use a CPU worker. Startup and first-run generation require only one healthy worker; extra configured workers are optional throughput and are used only after their health checks pass.

### Worker Commands

| Command | Behavior |
|---|---|
| `start.bat server` | Start only Fantasee server |
| `start.bat gpu1` | Start DirectML ComfyUI on `8188` |
| `start.bat gpu2` | Start DirectML ComfyUI on `8189` |
| `start.bat cpu <port>` | Start CPU ComfyUI at below-normal priority |
| `start.bat max [N]` | Start N CPU workers plus server |
| `start.bat all` | Start gpu1, gpu2, and server |
| `kill_workers.bat` | Kill Fantasee and ComfyUI worker processes on standard ports |

### ComfyUI Database Files

Modern ComfyUI uses SQLite. Multiple ComfyUI instances cannot share `user/comfyui.db`. Every Fantasee worker command passes a per-port SQLAlchemy URL:

```text
sqlite:///C:/Users/alist/Documents/comfy/ComfyUI/user/comfyui_<port>.db
```

This avoids `Could not acquire lock on database` and `Unsupported database URL` startup failures.

### Auto-Spawn

If the server starts and no ComfyUI worker is detected, Fantasee auto-spawns one DirectML GPU worker on `8189`. The startup wait is satisfied as soon as one worker is healthy; second and later workers can keep booting in the background. Use the Studio worker console to spawn an explicit CPU worker or additional GPU worker. Disable auto-spawn with:

```bat
set FANTASEE_AUTO_SPAWN_CPU=0
```

The variable name is historical; the auto-spawn now uses the GPU path.

## Story Actions

`story_actions.py` implements the story-level maintenance actions used by the detail page.

| Action | Endpoint | Behavior |
|---|---|---|
| Re-generate | `POST /api/stories/<id>/regenerate` | Back up, wipe story dir, rerun full pipeline |
| Repair | `GET/POST /api/stories/<id>/repair` | Preview missing assets, then regenerate missing images/audio/subtitles |
| Extend | `POST /api/stories/<id>/extend` | Add more scenes from existing story context |

Repair is two-phase. `GET` returns a plan for the confirmation modal. `POST` starts a background repair task. Image repair calls `generate_image()`, so it uses the same workflow, prompt guards, and worker priority logic as full story generation.

## Delete Behavior

Delete currently runs synchronously through `DELETE /api/stories/<id>` and `delete_story.delete_story()`, which calls `shutil.rmtree()`. On Windows, deleting large story folders can feel stuck because the modal blocks the UI until the operation finishes.

If this becomes a frequent workflow, convert delete to a background task like repair/regenerate so the UI can close immediately and report progress in the task panel.

## Plex Export

`plex_export.py` renders a Plex-ready package under:

```text
stories/<story-id>/final/plex/
```

Outputs include:

| File | Purpose |
|---|---|
| `<story-id>.mp4` | H.264/AAC MP4 with `+faststart` |
| `<story-id>.en.srt` | SRT sidecar |
| `<story-id>.en.vtt` | WebVTT sidecar |
| `<story-id>-poster.png/svg` | Poster image |
| `chapters.ffmeta` | Chapter metadata for FFmpeg |

## Testing

Run all tests:

```bat
python -m unittest discover -s tests -v
```

Run a focused test module:

```bat
python -m pytest tests/test_story_actions.py
```

The suite covers story actions, background music, title images, Plex export helpers, and smoke coverage for FFmpeg-backed export when dependencies are installed.

## Operational Checklist

For a clean GPU-first run:

1. `kill_workers.bat`
2. `start.bat gpu1`
3. `start.bat server`
4. Open `http://127.0.0.1:8765`
5. Confirm workers in the ComfyUI badge/modal.
6. Generate, repair, or extend a story.

For CPU fallback without freezing the desktop:

1. `start.bat cpu 8189`
2. Confirm Task Manager shows the CPU worker as below-normal priority.
3. Keep GPU workers running whenever possible; the picker uses GPU first.

## Known Caveats

- The pipeline still depends on external LLM/TTS services. Seed suggestions and outline generation can hang or fail if the provider/API key is unavailable.
- Plain SD 1.5 checkpoints produce weaker faces than DreamShaper, Counterfeit, or other tuned checkpoints.
- Delete is synchronous and modal-blocking.
- Function names around auto-spawn still contain `cpu` for compatibility, even though auto-spawn now uses DirectML GPU.
- `start.bat max` is CPU-worker mode. It is useful for fallback or CPU-only systems, not for a responsive GPU-first desktop workflow.
