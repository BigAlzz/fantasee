# Fantasee

Fantasee is a local-first AI animation studio. It turns a creative idea into an
inspectable production containing story text, scenes, semantic shots, artwork,
narration, synchronized subtitles, a canonical timeline, rendered video, and a
verified release that can be watched in Plex.

The current Studio rebuild combines a durable SQLite production ledger with
file-backed media assets. Existing legacy stories under `outputs/` remain
readable, while the managed Studio library can start clean and independent from
the archive.

## Quick Start

```bat
pip install fastapi uvicorn pillow requests
python server.py
```

Open `http://127.0.0.1:8765`.

The rebuild Studio is available at `http://127.0.0.1:8765/studio/`. To make
the Studio the default root experience while retaining the legacy fallback,
set `FANTASEE_STUDIO_DEFAULT=1` before starting the server. Remove the setting
or set it to `0` to return to the legacy root.

For the normal GPU-first local workflow:

```bat
start.bat gpu1
start.bat server
```

If no ComfyUI worker is detected when the server starts, Fantasee auto-spawns one DirectML GPU worker on port `8189`. Startup and first-run generation only require one healthy GPU worker; additional workers are optional throughput.

## Fantasee Studio

Open the rebuild at `http://127.0.0.1:8765/studio/`. It is organized around
the way a production is actually made:

| Desk | What it does |
|---|---|
| **Library** | Shows scene artwork, completion evidence, release state, and the current managed story collection. |
| **Production Desk** | Shows durable runs, current stages, queue state, retryable failures, worker ownership, and live activity lanes. |
| **Story Studio** | Edits the brief, scenes, shot plans, prompts, narration, image candidates, subtitles, and revisions. |
| **Voice Studio** | Auditions voices, sets performance direction and speed, and inspects narration/subtitle timing. |
| **Player** | Plays the canonical release timeline with scene changes, narration, music, captions, and release selection. |
| **Assets** | Inspects immutable generated media, provenance, validation state, and release history. |
| **Settings** | Configures providers, models, workers, audio, defaults, and the Plex destination. |

### From idea to watchable release

1. Start with a concept, style, tone, characters, and optional world context.
2. Use the seed picker to explore several directions before committing.
3. Generate a title, description, story bible, bounded outline, and scene cards.
4. Let the Director plan purposeful shots from narration, pacing, and scene intent.
5. Generate image candidates through ComfyUI and approve the shots you want.
6. Revise, reorder, lock, compare, or restore individual shot revisions without
   rewriting the whole story.
7. Generate narration, align subtitles to the exact approved audio, and review
   the waveform and cue coverage.
8. Build one canonical timeline used by the player, subtitles, FFmpeg renderer,
   chapters, and Plex publisher.
9. Render a release, run completion and media quality gates, then export the
   verified MP4 package to Plex.

### Production control and truthfulness

- **Durable runs and jobs** persist in `.fantasee/production.db`, including
  events, attempts, leases, progress, worker ownership, token usage, assets,
  timelines, and releases.
- **Live worker lanes** show which CPU/GPU worker is online, what it is doing,
  and whether a job is actually leased. Provider queue activity is not silently
  presented as an idle worker.
- **Safe retry and cancellation** support retrying a failed job, cancelling
  cooperatively, reprioritizing work, and recovering expired leases.
- **Idempotent production actions** avoid duplicate runs and conflicting
  releases when the same request is submitted again.
- **Completion gates** prevent a story or release from being called complete
  when scenes, shots, images, narration, subtitles, timeline inputs, video
  streams, chapters, or Plex metadata are missing or stale.
- **Provenance** records provider, model, workflow, prompt/text fingerprint,
  seed, settings, source revision, and validation evidence for generated assets.

### Creative and media capabilities

- Granular LLM commissioning for bible sections, arcs, scene cards, shot plans,
  prompts, continuity, and revisions instead of one opaque whole-story call.
- Configurable LLM model discovery: Settings queries the selected provider and
  returns its model list so a different model can be selected without editing
  source code.
- ComfyUI image generation with API workflow injection, GPU-first selection,
  capability-aware workers, alternate-worker retry, face-quality prompt guards,
  and scene-art-first library cards.
- **Comic book panels preset** with dynamic inked action, expressive poses,
  foreshortening, layered depth, high-contrast color blocking, and no generated
  speech bubbles or lettering. It is designed for the existing SD 1.5-class
  checkpoints, so it does not require a large-model upgrade.
- Semantic shot planning with shot purpose, framing, action, duration, visual
  context, candidate approval, locks, ordering, revision history, and targeted
  regeneration.
- TTS narration with voice presets, casting/performance direction, speed,
  auditioning, background music, loudness normalization, and subtitle alignment.
- Timeline-aware playback with multiple images per scene, timed transitions,
  narration, captions, chapters, music controls, fullscreen playback, and
  keyboard navigation.
- Release history with current-release selection, reversible previews, MP4
  playback, subtitle sidecars, poster artwork, chapters, and Plex packaging.

### Provider settings

Settings keeps credentials local and exposes the service seams needed for a
complete production:

| Setting | Purpose |
|---|---|
| LLM base URL, API key, and model | Story writing, shot planning, revisions, and model discovery. |
| TTS base URL, API key, model, voice, and speed | Narration generation and voice auditions. |
| Unsplash base URL and access key | Optional additional/reference imagery. |
| ComfyUI worker URLs and auto-spawn | Image generation workers and GPU/CPU fallback. |
| Whisper model size | Subtitle alignment quality/performance tradeoff. |
| Scenes, images per scene, style, tone, and narration style | New-production defaults. |
| Plex destination and background audio directory | Release publishing and music selection. |

Provider health checks validate the LLM model list, TTS endpoint, ComfyUI
workers, FFmpeg capabilities, and Plex destination before production work is
started.

## Core Features

- **Story generation** — title, description, scene outline, image prompts, narration, subtitles, and manifest output.
- **Seed picker** — ask the LLM for 2-6 story ideas before committing to generation.
- **ComfyUI image generation** — API-format workflow injection, GPU-first worker selection, per-worker SQLite databases.
- **Face-quality prompt guard** — automatic positive and negative prompt additions for better medium-shot human faces.
- **Cinematic player** — full-screen image player with narration, subtitles, keyboard controls, and background music.
- **Background music** — auto-selected mood track with separate volume and mute controls.
- **Story maintenance** — repair missing assets, re-generate a story, extend a story, delete old stories.
- **Plex export** — MP4 with chapters, SRT/VTT sidecars, poster, and mixed background audio.

## Launch Commands

| Command | Purpose |
|---|---|
| `start.bat server` | Start only the Fantasee web app on `8765` |
| `start.bat gpu1` | Start DirectML ComfyUI GPU worker on `8188` |
| `start.bat gpu2` | Start second DirectML ComfyUI worker on `8189` |
| `start.bat cpu <port>` | Start CPU ComfyUI worker at below-normal priority |
| `start.bat max [N]` | Start N CPU workers plus server |
| `start.bat all` | Start gpu1, gpu2, and server |
| `kill_workers.bat` | Kill Fantasee and ComfyUI worker processes on standard ports |

For desktop responsiveness, prefer `gpu1 + server`. Start `gpu2`, `all`, or `max` only when you want extra throughput; Fantasee will use healthy extra workers when they are ready, but it will not wait on them before the first image. CPU workers are fallback workers and run below normal priority when launched by Fantasee scripts.

## ComfyUI Setup

Fantasee needs a ComfyUI API-format workflow. The repository includes `workflow.json`, a minimal SD 1.5 workflow with these node types:

- `CheckpointLoaderSimple`
- `CLIPTextEncode` for positive prompt
- `CLIPTextEncode` for negative prompt
- `EmptyLatentImage`
- `KSampler`
- `VAEDecode`
- `SaveImage`

Workflow lookup order:

1. Explicit `workflow_path` argument.
2. `FANTASEE_WORKFLOW_PATH` environment variable.
3. `stories/<story-id>/working/workflows/*.json` when `FANTASEE_CURRENT_STORY_DIR` is set.
4. `workflow.json` in the project root.

The negative prompt node must contain one of `ugly`, `blurry`, `deformed`, or `low quality` in its placeholder text so `inject_prompt()` can identify it.

### Comic direction on low-end models

The Comic book panels director preset intentionally generates one readable
action panel per story image. This keeps the existing shot timeline and Ken
Burns renderer useful while giving each beat stronger graphic composition.
The preset adds style direction before the SD 1.5 CLIP compaction limit and
removes the house negative terms that would otherwise suppress comic linework.

For a more controlled ComfyUI setup, add ControlNet only when the hardware can
carry the extra model: lineart/HED or Canny for panel composition, OpenPose for
action poses, and depth for foreground-to-background staging. ControlNet's
official SD 1.5 implementation documents low-VRAM mode and composable controls;
ComfyUI's workflow examples and ControlNet tutorial show the model and
preprocessor wiring. IP-Adapter is a useful optional style/reference layer,
but keep it at low-to-medium strength on SD 1.5 so it does not flatten the
action into a sterile reference copy.

## Worker Databases

ComfyUI's built-in database cannot be shared by multiple processes. Fantasee launch scripts pass a per-port SQLAlchemy SQLite URL:

```text
sqlite:///C:/Users/alist/Documents/comfy/ComfyUI/user/comfyui_<port>.db
```

This prevents `Could not acquire lock on database` and `Unsupported database URL` errors when multiple workers run side by side.

## Story Storage

```text
stories/
  <story-id>/
    <story-id>.json
    <story-id>_s01_...png
    tts_<story-id>_s01.wav
    subs_<story-id>_s01.json
    assets/title/
    working/
    final/plex/
```

Legacy stories in `outputs/` remain readable through the fallback in `story_storage.py`.

## Story Actions

| Action | Endpoint | Behavior |
|---|---|---|
| Generate | `POST /api/generate` | Start a new story task |
| Queue | `POST /api/generate-queue` | Run multiple story concepts sequentially |
| Seed suggestions | `POST /api/seed-suggestions` | Ask the LLM for story seed ideas |
| Repair | `GET/POST /api/stories/<id>/repair` | Preview and repair missing images/audio/subtitles |
| Re-generate | `POST /api/stories/<id>/regenerate` | Back up, wipe, and rerun the story |
| Extend | `POST /api/stories/<id>/extend` | Add scenes from current story context |
| Delete | `DELETE /api/stories/<id>` | Delete a story directory, optionally with backup |
| Plex export | `POST /api/stories/<id>/export-plex` | Build Plex package in background |

Repair, regenerate, generation, queue generation, and Plex export report progress through `WS /ws` task updates.

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Space` / `K` | Play or pause |
| `Right` | Next scene |
| `Left` | Previous scene |
| `M` | Mute narration |
| `B` | Mute background music |
| `C` | Toggle captions |
| `F` | Toggle fullscreen |
| `Esc` | Close player |

## Plex Export

Each exported story writes a Plex-ready package to:

```text
stories/<story-id>/final/plex/
```

Outputs include:

- `<story-id>.mp4`
- `<story-id>.en.srt`
- `<story-id>.en.vtt`
- `<story-id>-poster.png`
- `<story-id>-poster.svg`
- `chapters.ffmeta`

CLI export:

```bat
python plex_export.py <story-id>
```

GUI export: open a story detail page and click **Export to Plex**.

## Tests

```bat
python -m unittest discover -s tests -v
python -m pytest tests/test_story_actions.py
```

The tests cover story repair/extend/regenerate planning, background music selection, Plex export helpers, seed suggestions, subtitles, and title images.

## Security Configuration

Fantasee is local-first. Loopback requests remain usable without a token by
default, but requests from another host are rejected unless the server has an
operator token. Set the FANTASEE_API_TOKEN environment variable to a long,
random value before using a LAN or public bind.

Set FANTASEE_REQUIRE_AUTH=1 when running behind a reverse proxy, container, or
LAN/public bind so loopback requests also require the token. Configure
additional trusted provider hosts explicitly with
FANTASEE_ALLOWED_PROVIDER_HOSTS; arbitrary URLs, private destinations, and
redirects are rejected. Set FANTASEE_CORS_ORIGINS to a comma-separated list of
exact browser origins that should be allowed.

Never commit fantasee_settings.json or provider credentials. If a credential
has ever been committed, revoke it and rotate it before publishing the
repository; deleting the file from the latest commit is not sufficient.

## Documentation

- `docs/SYSTEM.md` — current system architecture and operations guide.
- `docs/STORY_ENGINE_ARCHITECTURE.md` — older design-plan notes for future architecture work.

## Notes

- Delete is currently synchronous and modal-blocking on large story folders.
- LLM/TTS outages can block seed suggestions or story generation.
- Plain SD 1.5 checkpoints are weak for human faces. Tuned models such as DreamShaper for fantasy or Counterfeit for anime are better.
- `start.bat max` is CPU-worker mode. It is useful for fallback or CPU-only machines, not the preferred GPU-first desktop workflow.
