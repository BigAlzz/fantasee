# Fantasee — Hermes Agent Content Generation Skills

These are the Hermes Agent skills used to generate stories, images, narration,
and assembled video for the Fantasee browser viewer. Each `.SKILL.md` file is
a self-contained skill that Hermes loads to perform a specific part of the
pipeline.

## Pipeline Overview

```
           Writing Phase                Asset Generation           Assembly & Playback
  ┌──────────────────────────┐    ┌──────────────────────────┐    ┌─────────────────────────┐
  │                          │    │                          │    │                         │
  │  animated-storytelling   │───►│  comfyui (image gen)     │───►│  story-viewer            │
  │  .SKILL.md               │    │  .SKILL.md               │    │  (server.py + viewer)    │
  │                          │    │  scripts/run_workflow.py │    │                         │
  │  story-scene-gen         │    │                          │    │  viewer.html plays       │
  │  .SKILL.md               │    │  piper-tts.SKILL.md      │    │  story.json → images     │
  │                          │    │  (local TTS narration)   │    │  + audio + subtitles      │
  │  humanizer.SKILL.md      │    │                          │    │                         │
  │  (strip AI-isms)         │    │  animated-storytelling/  │    │  references/              │
  │                          │    │  scripts/build_clips.py  │    │  subtitle-sync.md         │
  │  local-subagent-         │    │  (MP4 assembly)          │    │  architecture.md          │
  │  story-generation        │    │                          │    │                         │
  │  .SKILL.md               │    │                          │    │                         │
  └──────────────────────────┘    └──────────────────────────┘    └─────────────────────────┘
```

## Skills Directory

| File | Purpose |
|------|---------|
| `animated-storytelling.SKILL.md` | **The main pipeline** — writes a story outline (scene-by-scene via LLM), generates ComfyUI work flows, renders images, runs TTS, assembles MP4 clips, and exports a `story.json` manifest for the viewer. This is the one skill to load for end-to-end story generation. |
| `comfyui.SKILL.md` | Configure, launch, and use ComfyUI for image/video generation. Includes all scripts for running workflows, checking deps, batching, and monitoring. The reference docs cover the REST API, workflow format, and DirectML setup (AMD GPU). |
| `piper-tts.SKILL.md` | Local neural VITS text-to-speech using Piper. Configure voices, tune narration parameters (length scale, noise w scale, buffer ms for anti-warbling). |
| `humanizer.SKILL.md` | Post-processing to strip AI writing patterns from narration text — removes 29 categories of tells (significance inflation, -ing phrases, copula avoidance, em dash overuse, passive voice, etc.) and adds natural voice. |
| `story-scene-generation.SKILL.md` | Add new scenes to existing stories — identify gaps, delegate to subagents, humanize, insert at correct positions with unique seeds. |
| `local-subagent-story-generation.SKILL.md` | Delegate story/script writing to a local LM Studio model while the main agent stays on a fast cloud model. Keeps subagent context tiny (300-500 tokens) to avoid GPU lockup. |

## Scripts & References

### `comfyui/scripts/`

These are the core ComfyUI interaction scripts. All require the ComfyUI server
to be running (local or cloud).

| Script | Purpose |
|--------|---------|
| `run_workflow.py` | **The main workhorse** — inject params into a workflow JSON, submit to ComfyUI, monitor progress, download outputs. Supports local (`--host 127.0.0.1:8188`) and cloud (`--host https://cloud.comfy.org` + `$COMFY_CLOUD_API_KEY`). |
| `run_batch.py` | Submit a workflow N times with seed sweeps or param variations. Parallel up to your cloud tier limit. |
| `_common.py` | Shared utilities — HTTP helpers, cloud routing, safe path handling. Not run directly. |
| `extract_schema.py` | Read a workflow JSON and list all controllable parameters, model deps, and embedding refs. |
| `check_deps.py` | Check if all nodes/models/embeddings a workflow needs are installed on the running ComfyUI instance. |
| `auto_fix_deps.py` | Run `check_deps` then auto-install missing nodes and download missing models. |
| `health_check.py` | Full health check: CLI on PATH? server reachable? checkpoints installed? smoke test passes? |
| `hardware_check.py` | Probe GPU/VRAM/disk to recommend local vs Comfy Cloud install. |
| `ws_monitor.py` | Real-time WebSocket viewer for executing jobs (live progress). |
| `fetch_logs.py` | Pull traceback/status messages for a given ComfyUI prompt ID. |

### `animated-storytelling/scripts/`

| Script | Purpose |
|--------|---------|
| `generate_workflows.py` | Read a story markdown file → produce one ComfyUI API-format workflow JSON per scene, with prompt, seed, dimensions baked in. |
| `build_clips.py` | Assemble individual images + TTS audio → MP4 per scene, then concatenate into final video. Uses ffmpeg. |

### Reference Docs

| Path | Purpose |
|------|---------|
| `comfyui/references/batch-story-pipeline.md` | Multi-scene story image batch generation: scene order, seed conventions (+100/+200 for polish passes), prompt refinement via subagents. |
| `comfyui/references/anime-sd15-prompting.md` | Counterfeit V3 prompt guide: natural language style, shot types, character bible technique. |
| `comfyui/references/rest-api.md` | ComfyUI REST + WebSocket API reference: endpoints, payload schemas, cloud differences. |
| `comfyui/references/workflow-format.md` | API-format workflow JSON structure, node types, param mapping. |
| `comfyui/references/windows-amd-directml-setup.md` | Step-by-step DirectML setup log for AMD GPUs on Windows (Python 3.11, DirectML venv, torch-directml). |
| `comfyui/references/template-integrity.md` | Converting official ComfyUI workflow templates to API format (Reroute bypass, Cloud quirks). |
| `animated-storytelling/references/fantasy-prompting.md` | DreamShaper V8 fantasy illustration prompting: shot types, artistic style terms, negative prompt boilerplate. |
| `animated-storytelling/references/prompting-guide.md` | Counterfeit V3 natural language prompt guide (why tag lists fail). |
| `animated-storytelling/references/story-structure-25.md` | 4-act, 25-scene story structure template with per-scene purpose, seed conventions (7000 + project*100 + scene). |
| `animated-storytelling/references/workflow-structure.md` | Canonical ComfyUI 7-node layout for Counterfeit V3 / SD 1.5 (CheckpointLoaderSimple → KSampler → SaveImage). |
| `animated-storytelling/references/extending-existing-stories.md` | Guidelines for adding scenes to existing stories without breaking the existing arc. |
| `animated-storytelling/templates/story-format.md` | The markdown story format template that all scripts expect: `### Scene N — "Title" (Seed: NNNN)` with `**Narration:**` and `**Image Prompt:**` blocks. |
| `references/architecture.md` | The subprocess streaming architecture: backend spawns a pipeline, reads `__PROGRESS__:` markers from stdout, pushes live updates to the frontend via WebSocket. |
| `references/subtitle-sync.md` | Sentence-level subtitle sync without SRT files: character-length-weighted time estimation for Web Audio API. |

## How to Use

### Prerequisites

- **Hermes Agent** (v0.14+) — loads skills with `skill_view(name)` and follows their instructions
- **Hermes skills directory** — clone this repo's `skills/` into your `$HERMES_HOME/skills/` directory
- **ComfyUI** — local (see `comfyui.SKILL.md` for setup) or Comfy Cloud API key
- **Piper TTS** — local install (see `piper-tts.SKILL.md`)
- **Python 3.10+** with `requests`, `PIL/Pillow`, `ffmpeg-python` (or just `ffmpeg` on PATH)

### End-to-End Pipeline

1. Load the `animated-storytelling` skill in Hermes
2. Give it a story concept (e.g., "a lone ranger in a dying forest")
3. It generates a scene outline → ComfyUI workflows → renders images → runs TTS → assembles MP4 → exports `story.json`
4. Drop the output into the Fantasee viewer and reload

### Manual Steps

```bash
# 1. Write a story in the markdown format
cp templates/story-format.md my_story/story.md
# edit my_story/story.md ...

# 2. Generate ComfyUI workflows per scene
python3 animated-storytelling/scripts/generate_workflows.py \
  --story my_story/story.md \
  --output my_story/workflows/

# 3. Render images (requires running ComfyUI)
python3 comfyui/scripts/run_workflow.py \
  --workflow my_story/workflows/scene01.json \
  --output-dir my_story/images/

# 4. Generate TTS narration
# Use text_to_speech tool in Hermes for each scene's narration

# 5. Build MP4 clips
python3 animated-storytelling/scripts/build_clips.py \
  --story my_story/story.md \
  --images my_story/images/ \
  --audio my_story/audio/ \
  --output my_story/clips/

# 6. Export viewer manifest and film
python3 server.py --static my_story/final/
```
