# Fantasee 0.1 — Story Viewer

A Netflix-style browser for AI-generated stories with audio narration. Browse, play, and watch narrated visual stories in your browser.

## Quick Start

```
pip install fastapi uvicorn
python server.py
```

Open http://127.0.0.1:8765

## Features

- **Cinematic player** — full-screen image viewer with audio narration
- **Scene navigation** — scrub through scenes, auto-advance on audio end
- **Synced subtitles** — sentence-level captions synced to audio playback
- **Volume & playback controls** — play/pause, mute, keyboard shortcuts
- **Story library** — browse available stories via hero + card grid
- **Live generation** — create new stories from a prompt (WebSocket progress)

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` / `K` | Play / Pause |
| `→` | Next scene |
| `←` | Previous scene |
| `M` | Mute / Unmute |
| `C` | Toggle captions |
| `Esc` | Close player |

## API

- `GET /api/stories` — list all stories
- `GET /api/stories/:id` — get story with scenes
- `GET /images/:filename` — serve scene images
- `GET /audio/:filename` — serve audio narration
- `POST /api/generate` — generate a new story
- `WS /ws` — live generation status updates

## Tech

- **Backend:** Python + FastAPI + Uvicorn
- **Frontend:** Vanilla JS, Netflix-inspired dark theme
- **Data:** JSON-based story/scene storage

## Content Generation (Hermes Agent Skills)

This repo ships with the Hermes Agent skills needed to generate stories,
images, narration, and video for the viewer. Located in `skills/`:

| Skill | What it does |
|-------|-------------|
| `animated-storytelling.SKILL.md` | Full pipeline: write story, generate ComfyUI workflows, render images, TTS, assemble MP4 clips, export viewer manifest |
| `comfyui.SKILL.md` | ComfyUI setup + scripts (`run_workflow.py`, `run_batch.py`, `health_check.py`, etc.) |
| `piper-tts.SKILL.md` | Local neural TTS for narration audio |
| `humanizer.SKILL.md` | Strip AI writing patterns from narration text |
| `story-scene-generation.SKILL.md` | Add new scenes to existing stories |
| `local-subagent-story-generation.SKILL.md` | Offload story writing to a local LM Studio |

Full reference documentation, scripts, and prompting guides are in the
`skills/` subdirectories. See `skills/README.md` for the complete pipeline
walkthrough.

**To use:** clone this repo, symlink the `skills/` directory into your
`$HERMES_HOME/skills/` directory, and Hermes will recognize them as
loadable skills when you ask it to generate story content.
