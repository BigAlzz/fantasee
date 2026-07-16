# Fantasee

Fantasee is a local AI story generation and viewing app. It writes narrated multi-scene stories from a text concept, generates images through ComfyUI, creates narration audio and synced subtitles, then presents the result in a Netflix-style browser/player.

The app is file-based: story manifests and assets live under `stories/<story-id>/`. There is no application SQLite database. ComfyUI itself may create per-worker SQLite files under its own `user/` directory.

## Quick Start

```bat
pip install fastapi uvicorn pillow requests
python server.py
```

Open `http://127.0.0.1:8765`.

For the normal GPU-first local workflow:

```bat
start.bat gpu1
start.bat server
```

If no ComfyUI worker is detected when the server starts, Fantasee auto-spawns one DirectML GPU worker on port `8189`. Startup and first-run generation only require one healthy GPU worker; additional workers are optional throughput.

## Features

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
