---
name: comfyui
description: "Generate images, video, and audio with ComfyUI — install, launch, manage nodes/models, run workflows with parameter injection. Uses the official comfy-cli for lifecycle and direct REST/WebSocket API for execution."
version: 5.1.0
author: [kshitijk4poor, alt-glitch, purzbeats]
license: MIT
platforms: [macos, linux, windows]
compatibility: "Requires ComfyUI (local, Comfy Desktop, or Comfy Cloud) and comfy-cli (auto-installed via pipx/uvx by the setup script)."
prerequisites:
  commands: ["python3"]
setup:
  help: "Run scripts/hardware_check.py FIRST to decide local vs Comfy Cloud; then scripts/comfyui_setup.sh auto-installs locally (or use Cloud API key for platform.comfy.org)."
metadata:
  hermes:
    tags:
      - comfyui
      - image-generation
      - stable-diffusion
      - flux
      - sd3
      - s3-dit
      - z-image
      - diffusion-transformer
      - wan-video
      - hunyuan-video
      - creative
      - generative-ai
      - video-generation
    related_skills: [stable-diffusion-image-generation, image_gen]
    category: creative
---

# ComfyUI

Generate images, video, audio, and 3D content through ComfyUI using the
official `comfy-cli` for setup/lifecycle and direct REST/WebSocket API
for workflow execution.

## What's in this skill

**Reference docs (`references/`):**

- `batch-story-pipeline.md` — multi-scene story image pipeline: scene workflow layout, seed conventions (base/+100/+200), polish-run pattern using parallel subagents for prompt refinement, batch runner scripts, output management, Windows path pitfalls
- `official-cli.md` — every `comfy ...` command, with flags
- `rest-api.md` — REST + WebSocket endpoints (local + cloud), payload schemas
- `workflow-format.md` — API-format JSON, common node types, param mapping
- `template-integrity.md` — converting `comfyui-workflow-templates` from
  editor format to API format: Reroute bypass, dotted dynamic-input keys
  (`values.a`, `resize_type.width`), Cloud quirks (302 redirect, 1 concurrent
  free-tier job, 1080p VRAM ceiling), Discord-compatible ffmpeg stitch.
  Authored by [@purzbeats](https://github.com/purzbeats). Load this whenever
  you're starting from an official template.
- `windows-amd-directml-setup.md` — session-specific setup log for AMD on
  Windows via DirectML (known good paths, Python version workaround, errors
  encountered). Load this on Alistair's Windows machine when setting up or
  troubleshooting DirectML.
- `greeting-cards-and-text.md` — generating greeting cards and text-heavy
  images with SD 1.5: text-garbling limitation, aspect ratio recommendations,
  workarounds (text-free generation + PIL overlay, accepting calligraphy
  aesthetic, or switching models).
- `z-image-s3-dit-models.md` — Diffusion Transformer (S3-DiT) model family
- `anime-sd15-prompting.md` — Anime SD 1.5 prompting guide (Counterfeit V3, natural language style, character bible technique for cross-scene consistency, DirectML-compatible model list)
  (Z-Image, Z-Anime, and similar 6B-param DiTs): architecture overview, file
  placement in ComfyUI, required custom nodes, variant comparison, workflow
  differences from UNet models, and HuggingFace download patterns.

**Scripts (`scripts/`):**

| Script | Purpose |
|--------|---------|
| `_common.py` | Shared HTTP, cloud routing, node catalogs (don't run directly) |
| `hardware_check.py` | Probe GPU/VRAM/disk → recommend local vs Comfy Cloud |
| `comfyui_setup.sh` | Hardware check + comfy-cli + ComfyUI install + launch + verify |
| `extract_schema.py` | Read a workflow → list controllable params + model deps |
| `check_deps.py` | Check workflow against running server → list missing nodes/models |
| `auto_fix_deps.py` | Run check_deps then `comfy node install` / `comfy model download` |
| `run_workflow.py` | Inject params, submit, monitor, download outputs (HTTP or WS) |
| `run_batch.py` | Submit a workflow N times with sweeps, parallel up to your tier |
| `ws_monitor.py` | Real-time WebSocket viewer for executing jobs (live progress) |
| `health_check.py` | Verification checklist runner — comfy-cli + server + models + smoke test |
| `fetch_logs.py` | Pull traceback / status messages for a given prompt_id |

**Example workflows (`workflows/`):** SD 1.5, SDXL, Flux Dev, SDXL img2img,
SDXL inpaint, ESRGAN upscale, AnimateDiff video, Wan T2V. See
`workflows/README.md`.

## When to Use

- User asks to generate images with Stable Diffusion, SDXL, Flux, SD3, Z-Image/Z-Anime, etc.
- User wants to run a specific ComfyUI workflow file
- User wants to chain generative steps (txt2img → upscale → face restore)
- User needs ControlNet, inpainting, img2img, or other advanced pipelines
- User asks to manage ComfyUI queue, check models, or install custom nodes
- User wants video/audio/3D generation via AnimateDiff, Hunyuan, Wan, AudioCraft, etc.

## Architecture: Two Layers

```
┌─────────────────────────────────────────────────────┐
│ Layer 1: comfy-cli (official lifecycle tool)        │
│   Setup, server lifecycle, custom nodes, models     │
│   → comfy install / launch / stop / node / model    │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│ Layer 2: REST/WebSocket API + skill scripts         │
│   Workflow execution, param injection, monitoring   │
│   POST /api/prompt, GET /api/view, WS /ws           │
│   → run_workflow.py, run_batch.py, ws_monitor.py    │
└─────────────────────────────────────────────────────┘
```

**Why two layers?** The official CLI is excellent for installation and server
management but has minimal workflow execution support. The REST/WS API fills
that gap — the scripts handle param injection, execution monitoring, and
output download that the CLI doesn't do.

## Quick Start

### Detect environment

```bash
# What's available?
command -v comfy >/dev/null 2>&1 && echo "comfy-cli: installed"
curl -s http://127.0.0.1:8188/system_stats 2>/dev/null && echo "server: running"

# Can this machine run ComfyUI locally? (GPU/VRAM/disk check)
python3 scripts/hardware_check.py
```

If nothing is installed, see **Setup & Onboarding** below — but always run the
hardware check first.

### One-line health check

```bash
python3 scripts/health_check.py
# → JSON: comfy_cli on PATH? server reachable? at least one checkpoint? smoke-test passes?
```

## Core Workflow

### Step 1: Get a workflow JSON in API format

Workflows must be in API format (each node has `class_type`). They come from:

- ComfyUI web UI → **Workflow → Export (API)** (newer UI) or
  the legacy "Save (API Format)" button (older UI)
- This skill's `workflows/` directory (ready-to-run examples)
- Community downloads (civitai, Reddit, Discord) — usually editor format,
  must be loaded into ComfyUI then re-exported

Editor format (top-level `nodes` and `links` arrays) is **not directly
executable**. The scripts detect this and tell you to re-export.

### Step 2: See what's controllable

```bash
python3 scripts/extract_schema.py workflow_api.json --summary-only
# → {"parameter_count": 12, "has_negative_prompt": true, "has_seed": true, ...}

python3 scripts/extract_schema.py workflow_api.json
# → full schema with parameters, model deps, embedding refs
```

### Step 3: Run with parameters

```bash
# Local (defaults to http://127.0.0.1:8188)
python3 scripts/run_workflow.py \
  --workflow workflow_api.json \
  --args '{"prompt": "a beautiful sunset over mountains", "seed": -1, "steps": 30}' \
  --output-dir ./outputs

# Cloud (export API key once; uses correct /api routing automatically)
export COMFY_CLOUD_API_KEY="comfyui-..."
python3 scripts/run_workflow.py \
  --workflow workflow_api.json \
  --args '{"prompt": "..."}' \
  --host https://cloud.comfy.org \
  --output-dir ./outputs

# Real-time progress via WebSocket (requires `pip install websocket-client`)
python3 scripts/run_workflow.py \
  --workflow flux_dev.json \
  --args '{"prompt": "..."}' \
  --ws

# img2img / inpaint: pass --input-image to upload + reference automatically
python3 scripts/run_workflow.py \
  --workflow sdxl_img2img.json \
  --input-image image=./photo.png \
  --args '{"prompt": "make it watercolor", "denoise": 0.6}'

# Batch / sweep: 8 random seeds, parallel up to cloud tier limit
python3 scripts/run_batch.py \
  --workflow sdxl.json \
  --args '{"prompt": "abstract"}' \
  --count 8 --randomize-seed --parallel 3 \
  --output-dir ./outputs/batch
```

`-1` for `seed` (or omitting it with `--randomize-seed`) generates a fresh
random seed per run.

### Step 4: Present results

The scripts emit JSON to stdout describing every output file:

```json
{
  "status": "success",
  "prompt_id": "abc-123",
  "outputs": [
    {"file": "./outputs/sdxl_00001_.png", "node_id": "9",
     "type": "image", "filename": "sdxl_00001_.png"}
  ]
}
```

## Decision Tree

| User says | Tool | Command |
|-----------|------|---------|
| **Lifecycle (use comfy-cli)** | | |
| "install ComfyUI" | comfy-cli | `bash scripts/comfyui_setup.sh` |
| "start ComfyUI" | comfy-cli | `comfy launch --background` |
| "stop ComfyUI" | comfy-cli | `comfy stop` |
| "install X node" | comfy-cli | `comfy node install <name>` |
| "download X model" | comfy-cli | `comfy model download --url <url> --relative-path models/checkpoints` |
| "list installed models" | comfy-cli | `comfy model list` |
| "list installed nodes" | comfy-cli | `comfy node show installed` |
| **Execution (use scripts)** | | |
| "is everything ready?" | script | `health_check.py` (optionally with `--workflow X --smoke-test`) |
| "what can I change in this workflow?" | script | `extract_schema.py W.json` |
| "check if W's deps are met" | script | `check_deps.py W.json` |
| "fix missing deps" | script | `auto_fix_deps.py W.json` |
| "generate an image" | script | `run_workflow.py --workflow W --args '{...}'` |
| "use this image" (img2img) | script | `run_workflow.py --input-image image=./x.png ...` |
| "8 variations with random seeds" | script | `run_batch.py --count 8 --randomize-seed ...` |
| "show me live progress" | script | `ws_monitor.py --prompt-id <id>` |
| "fetch the error from job X" | script | `fetch_logs.py <prompt_id>` |
| **Direct REST** | | |
| "what's in the queue?" | REST | `curl http://HOST:8188/queue` (local) or `--host https://cloud.comfy.org` |
| "cancel that" | REST | `curl -X POST http://HOST:8188/interrupt` |
| "free GPU memory" | REST | `curl -X POST http://HOST:8188/free` |

## Prompting Guidelines (User Preference)

These rules apply when the user (Alistair) asks you to generate images via
ComfyUI. They encode corrections and preferences from past sessions.

### Rule 1: Natural language prompts always

Write prompts as full descriptive sentences, **not** comma-separated tag lists
like `1girl, silver_hair, anime`. Natural language produces better results with
the installed anime models (Counterfeit V3, Z-Anime, etc.).

Structure each prompt with these elements in order:
  1. **Shot type** — `wide shot` / `medium shot` / `close-up` / `low angle`
  2. **Subject** — Character appearance, clothing, expression, pose
  3. **Setting** — Location and time of day
  4. **Lighting and atmosphere** — Mood, color, light source, weather
  5. **Art direction** — `cinematic composition`, `masterpiece`, `best quality`,
     `high quality anime illustration`

### Rule 2: Track characters across scenes with a bible

When generating multiple images for a story, define a character bible first:

```yaml
Kaelen:
  hair: short messy dark-brown hair
  eyes: sharp green eyes
  outfit: grey wool messenger coat with brass buttons, leather satchel
```

Then reuse the **exact same descriptors** in every scene prompt. Use fixed
sequential seeds (1001, 2002, 3003, ...) for reproducibility.

### Rule 3: Negative prompt boilerplate

Always include: `ugly, blurry, low quality, deformed, bad anatomy, watermark,
text, letters, words, signature, distorted, extra limbs`

Adjust for scene: add `modern buildings, cars` for fantasy scenes, add
`peaceful, quiet` for battle scenes, etc.

### Rule 4: Keep old outputs when iterating

When the user asks to regenerate with improved prompts, do NOT delete or
overwrite previous outputs. Keep all versions so they can compare.

---

## Setup & Onboarding

When a user asks to set up ComfyUI, **the FIRST thing to do is ask whether
they want Comfy Cloud (hosted, zero install, API key) or Local (install
ComfyUI on their machine)**. Don't start running install commands or hardware
checks until they've answered.

**Official docs:** https://docs.comfy.org/installation
**CLI docs:** https://docs.comfy.org/comfy-cli/getting-started
**Cloud docs:** https://docs.comfy.org/get_started/cloud
**Cloud API:** https://docs.comfy.org/development/cloud/overview

### Step 0: Ask Local vs Cloud (ALWAYS FIRST)

Suggested script:

> "Do you want to run ComfyUI locally on your machine, or use Comfy Cloud?
>
> - **Comfy Cloud** — hosted on RTX 6000 Pro GPUs, all common models pre-installed,
>   zero setup. Requires an API key (paid subscription required to actually run
>   workflows; free tier is read-only). Best if you don't have a capable GPU.
> - **Local** — free, but your machine MUST meet the hardware requirements:
>   - NVIDIA GPU with **≥6 GB VRAM** (≥8 GB for SDXL, ≥12 GB for Flux/video), OR
>   - AMD GPU with ROCm support (Linux), OR
>   - Apple Silicon Mac (M1+) with **≥16 GB unified memory** (≥32 GB recommended).
>   - Intel Macs and machines with no GPU will NOT work — use Cloud instead.
>
> Which would you like?"

Routing:

- **Cloud** → skip to **Path A**.
- **Local** → run hardware check first, then pick a path from Paths B–E based on the verdict.
- **Unsure** → run the hardware check and let the verdict decide.

### Step 1: Verify Hardware (ONLY if user chose local)

```bash
python3 scripts/hardware_check.py --json
# Optional: also probe `torch` for actual CUDA/MPS:
python3 scripts/hardware_check.py --json --check-pytorch
```

| Verdict    | Meaning                                                       | Action |
|------------|---------------------------------------------------------------|--------|
| `ok`       | ≥8 GB VRAM (discrete) OR ≥32 GB unified (Apple Silicon)       | Local install — use `comfy_cli_flag` from report |
| `marginal` | SD1.5 works; SDXL tight; Flux/video unlikely                  | Local OK for light workflows, else **Path A (Cloud)** |
| `marginal` + AMD Windows | SD1.5 works with DirectML                                      | **Path F: AMD Windows + DirectML** |
| `cloud`    | No usable GPU, <6 GB VRAM, <16 GB Apple unified, Intel Mac, Rosetta Python | **Switch to Cloud** unless user explicitly forces local |

The script also surfaces `wsl: true` (WSL2 with NVIDIA passthrough) and
`rosetta: true` (x86_64 Python on Apple Silicon — must reinstall as ARM64).

If verdict is `cloud` but the user wants local, do not proceed silently.
Show the `notes` array verbatim and ask whether they want to (a) switch to
Cloud or (b) force a local install (will OOM or be unusably slow on modern models).

### Choosing an Installation Path

Use the hardware check first. The table below is the fallback for when the
user has already told you their hardware:

| Situation | Recommended Path |
|-----------|------------------|
| `verdict: cloud` from hardware check | **Path A: Comfy Cloud** |
| No GPU / want to try without commitment | **Path A: Comfy Cloud** |
| Windows + NVIDIA + non-technical | **Path B: ComfyUI Desktop** |
| Windows + NVIDIA + technical | **Path C: Portable** or **Path D: comfy-cli** |
| Linux + any GPU | **Path D: comfy-cli** (easiest) |
| macOS + Apple Silicon     | **Path B: Desktop** or **Path D: comfy-cli** |
| AMD + Windows (DirectML) | **Path F: AMD Windows + DirectML** |
| Headless / server / CI / agents | **Path D: comfy-cli** |

For the fully automated path (hardware check → install → launch → verify):

```bash
bash scripts/comfyui_setup.sh
# Or with overrides:
bash scripts/comfyui_setup.sh --m-series --port=8190 --workspace=/data/comfy
```

It runs `hardware_check.py` internally, refuses to install locally when the
verdict is `cloud` (unless `--force-cloud-override`), picks the right
`comfy-cli` flag, and prefers `pipx`/`uvx` over global `pip` to avoid polluting
system Python.

---

### Path A: Comfy Cloud (No Local Install)

For users without a capable GPU or who want zero setup. Hosted on RTX 6000 Pro.

**Docs:** https://docs.comfy.org/get_started/cloud

1. Sign up at https://comfy.org/cloud
2. Generate an API key at https://platform.comfy.org/login
3. Set the key:
   ```bash
   export COMFY_CLOUD_API_KEY="comfyui-xxxxxxxxxxxx"
   ```
4. Run workflows:
   ```bash
   python3 scripts/run_workflow.py \
     --workflow workflows/flux_dev_txt2img.json \
     --args '{"prompt": "..."}' \
     --host https://cloud.comfy.org \
     --output-dir ./outputs
   ```

**Pricing:** https://www.comfy.org/cloud/pricing
**Concurrent jobs:** Free/Standard 1, Creator 3, Pro 5. Free tier
**cannot run workflows via API** — only browse models. Paid subscription
required for `/api/prompt`, `/api/upload/*`, `/api/view`, etc.

---

### Path B: ComfyUI Desktop (Windows / macOS)

One-click installer for non-technical users. Currently Beta.

**Docs:** https://docs.comfy.org/installation/desktop
- **Windows (NVIDIA):** https://download.comfy.org/windows/nsis/x64
- **macOS (Apple Silicon):** https://comfy.org

Linux is **not supported** for Desktop — use Path D.

---

### Path C: ComfyUI Portable (Windows Only)

**Docs:** https://docs.comfy.org/installation/comfyui_portable_windows

Download from https://github.com/comfyanonymous/ComfyUI/releases, extract,
run `run_nvidia_gpu.bat`. Update via `update/update_comfyui_stable.bat`.

---

### Path D: comfy-cli (All Platforms — Recommended for Agents)

The official CLI is the best path for headless/automated setups.

**Docs:** https://docs.comfy.org/comfy-cli/getting-started

#### Install comfy-cli

```bash
# Recommended:
pipx install comfy-cli
# Or use uvx without installing:
uvx --from comfy-cli comfy --help
# Or (if pipx/uvx unavailable):
pip install --user comfy-cli
```

Disable analytics non-interactively:
```bash
comfy --skip-prompt tracking disable
```

#### Install ComfyUI

```bash
comfy --skip-prompt install --nvidia              # NVIDIA (CUDA)
comfy --skip-prompt install --amd                 # AMD (ROCm, Linux)
comfy --skip-prompt install --m-series            # Apple Silicon (MPS)
comfy --skip-prompt install --cpu                 # CPU only (slow)
comfy --skip-prompt install --nvidia --fast-deps  # uv-based dep resolution
```

Default location: `~/comfy/ComfyUI` (Linux), `~/Documents/comfy/ComfyUI`
(macOS/Win). Override with `comfy --workspace /custom/path install`.

#### Launch / verify

```bash
comfy launch --background                       # background daemon on :8188
comfy launch -- --listen 0.0.0.0 --port 8190    # LAN-accessible custom port
curl -s http://127.0.0.1:8188/system_stats      # health check
```

---

### Path E: Manual Install (Advanced / Unsupported Hardware)

For Ascend NPU, Cambricon MLU, Intel Arc, or other unsupported hardware.

**Docs:** https://docs.comfy.org/installation/manual_install

```bash
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu130
pip install -r requirements.txt
python main.py
```

---

### Path F: AMD Windows + DirectML (Windows-only, AMD GPUs)

For Windows users with AMD/Radeon GPUs. Uses Microsoft's DirectML backend
(DirectX 12 ML acceleration) since AMD's ROCm does not support Windows.

**Requirements:**
- AMD Radeon RX 5000 series or newer (6 GB VRAM recommended for SD 1.5)
- Windows 10/11 with recent AMD drivers from amd.com
- **Python 3.10–3.12** (torch-directml has no wheels for Python 3.13+).
  Use `py -3.11 -c "import sys; print(sys.executable)"` to check availability,
  or install via `uv python install 3.11`.

```bash
# 1. Install comfy-cli
pipx install comfy-cli

# 2. Disable analytics & install ComfyUI without PyTorch/DirectML
comfy --skip-prompt tracking disable
# Use --restore if ComfyUI is already installed:
comfy --skip-prompt install --skip-torch-or-directml --restore

# 3. Create a Python 3.11 venv for DirectML (3.10–3.12)
#    comfy-cli does NOT create a DirectML venv — you must make one.
#    Locate Python 3.11 first; the default workspace is ~/Documents/comfy/ComfyUI
cd ~/Documents/comfy/ComfyUI
# Replace the path below with your Python 3.11 exe:
"/c/Users/YourUser/AppData/Roaming/uv/python/cpython-3.11.15-windows-x86_64-none/python.exe" -m venv ../directml-venv

# 4. Install torch-directml + torchvision-directml + ComfyUI deps
../directml-venv/Scripts/python -m pip install --upgrade pip setuptools wheel
../directml-venv/Scripts/python -m pip install torch-directml torchvision-directml
# Load ComfyUI requirements (from workspace):
cd ~/Documents/comfy/ComfyUI
../directml-venv/Scripts/python -m pip install -r requirements.txt
# Ensure torchaudio version matches the DirectML torch:
../directml-venv/Scripts/python -m pip install "torchaudio==$(../directml-venv/Scripts/python -c 'import torch; print(torch.__version__)')"

# 5. Launch with DirectML backend (use venv Python, NOT comfy launch)
../directml-venv/Scripts/python main.py --directml --listen 127.0.0.1 --port 8188

# 6. Verify
curl -s http://127.0.0.1:8188/system_stats
# The "devices" list should show "type": "privateuseone" (DirectML device)
```

**Which Python version to use:** If the system Python is 3.13+, download an
older compatible version. On Windows, `uv` manages co-installed Pythons:
```bash
uv python install 3.11
# Then find the path:
uv python list | grep "3\.11"
```

**Verify DirectML works:**
```bash
../directml-venv/Scripts/python -c "
import torch, torch_directml
dml = torch_directml.device()
t = torch.tensor([1.0, 2.0]).to(dml)
print(f'DirectML device: {dml}, tensor: {t}')
"
```

**Known limitations:**
- DirectML is generally slower than CUDA (expect 2–3× longer generation times).
- SD 1.5 (512×512) works on 4–6 GB cards. SDXL is tight on ≤6 GB.
- Flux and video generation are impractical via DirectML.
- Some custom nodes with CUDA-specific ops won't work.
- ComfyUI reports VRAM as only 1 GB via DirectML (it's the default allocation,
  not the actual VRAM; generation still works).
- The built-in `--amd` comfy-cli flag attempts ROCm (Linux-only) and will fail
  on Windows — always use `--skip-torch-or-directml` then manual DirectML setup.
- **S3-DiT models (Z-Image, Z-Anime) are NOT viable on DirectML.** The
  ComfyUI-GGUF dequantizer fails with "Cannot access storage of OpaqueTensorImpl"
  (uses `.view()` ops unsupported by DirectML), and even the FP8 standard variant
  (~6.15 GB DiT + 4 GB text encoder) crashes during model load on 6 GB VRAM.
  Use SD 1.5-based anime models (Counterfeit V3.0, Anything V5) instead;
  download via `curl -L -o models/checkpoints/Counterfeit-V3.0_fp16.safetensors
  "https://huggingface.co/gsdf/Counterfeit-V3.0/resolve/main/Counterfeit-V3.0_fp16.safetensors"`.

**Download SD 1.5 checkpoint:**
```bash
comfy model download \
  --url "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors" \
  --relative-path models/checkpoints
```

---

### Post-Install: Download Models

```bash
# SDXL (general purpose, ~6.5 GB)
comfy model download \
  --url "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" \
  --relative-path models/checkpoints

# SD 1.5 (lighter, ~4 GB, good for 6 GB cards)
comfy model download \
  --url "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors" \
  --relative-path models/checkpoints

# Flux Dev fp8 (smaller variant, ~12 GB)
comfy model download \
  --url "https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors" \
  --relative-path models/checkpoints

# CivitAI (set token first):
comfy model download \
  --url "https://civitai.com/api/download/models/128713" \
  --relative-path models/checkpoints \
  --set-civitai-api-token "YOUR_TOKEN"

# Z-Anime (S3-DiT model — separate text encoder & VAE needed):
comfy model download \
  --url "https://huggingface.co/SeeSee21/Z-Anime/resolve/main/diffusion_models/z-anime-distill-8step-fp8.safetensors" \
  --relative-path models/diffusion_models
comfy model download \
  --url "https://huggingface.co/SeeSee21/Z-Anime/resolve/main/text_encoder/qwen_3_4b-fp8.safetensors" \
  --relative-path models/clip
comfy model download \
  --url "https://huggingface.co/SeeSee21/Z-Anime/resolve/main/vae/ae.safetensors" \
  --relative-path models/vae

# Or Z-Anime GGUF (smallest, but NOT DirectML-compatible — see Known Issues):
comfy model download \
  --url "https://huggingface.co/SeeSee21/Z-Anime/resolve/main/gguf/z-anime-base-q4_k_s.gguf" \
  --relative-path models/unet
```

List installed: `comfy model list`.

### Post-Install: Install Custom Nodes

```bash
comfy node install comfyui-impact-pack             # popular utility pack
comfy node install comfyui-animatediff-evolved     # video generation
comfy node install comfyui-controlnet-aux          # ControlNet preprocessors
comfy node install comfyui-essentials              # common helpers
comfy node install rgthree-comfy                   # Z-Image/S3-DiT workflows (required)
comfy node install ComfyUI-Lora-Manager            # LoRA management (recommended)
comfy node install ComfyUI-GGUF                    # GGUF model support (Z-Image GGUF only)
comfy node update all
comfy node install-deps --workflow=workflow.json   # install everything a workflow needs
```

### Post-Install: Verify

```bash
python3 scripts/health_check.py
# → comfy_cli on PATH? server reachable? checkpoints? smoke test?

python3 scripts/check_deps.py my_workflow.json
# → are this workflow's nodes/models/embeddings installed?

python3 scripts/run_workflow.py \
  --workflow workflows/sd15_txt2img.json \
  --args '{"prompt": "test", "steps": 4}' \
  --output-dir ./test-outputs
```

---

## Z-Image / S3-DiT (Diffusion Transformer) Models

Z-Image (Alibaba Tongyi Lab) and its fine-tunes (Z-Anime, etc.) use the
**S3-DiT (Single-Stream Diffusion Transformer, 6B parameters)** architecture.
These are **not** UNet-based models — they use different ComfyUI nodes and
file placement.

### Key Differences from SD / SDXL / Flux

| Aspect | UNet models (SD, SDXL, Flux) | S3-DiT models (Z-Image, Z-Anime) |
|--------|------------------------------|-----------------------------------|
| Model loader | `CheckpointLoaderSimple` or `UNetLoader` | `Load Diffusion Model` |
| Model directory | `models/checkpoints/` | `models/diffusion_models/` |
| Text encoder | Built into checkpoint (SD) or `models/clip/` (Flux) | **Required separately** in `models/clip/` |
| VAE | Built into checkpoint (SD) or `models/vae/` | **Required separately** in `models/vae/` |
| GGUF placement | `models/checkpoints/` | `models/unet/` |
| Prompt style | Tag lists work well | Natural language descriptions preferred |
| Negative prompt | Full support (SD, SDXL) | Full on Base; limited on distilled |

### File Placement

**Standard diffusion model (BF16 / FP8):**
```
ComfyUI/models/diffusion_models/
└── z-anime-base-fp8.safetensors        # the DiT model (~6.15 GB FP8)

ComfyUI/models/clip/
└── qwen_3_4b-fp8.safetensors           # text encoder (~4 GB FP8)

ComfyUI/models/vae/
└── ae.safetensors                      # VAE (~168 MB)
```

**AIO (All-in-One) variant — single file, no separate VAE/text encoder:**
```
ComfyUI/models/checkpoints/
└── z-anime-base-aio-fp8.safetensors     # DiT + VAE + TE bundled (~10.5 GB FP8)
```

**GGUF variant (low VRAM / AMD-friendly):**
```
ComfyUI/models/unet/
└── z-anime-base-q4_k_s.gguf            # quantized DiT only (~4.51 GB)

ComfyUI/models/clip/
└── qwen_3_4b-fp8.safetensors           # text encoder still required

ComfyUI/models/vae/
└── ae.safetensors                      # VAE still required
```

### Variant Guide

| Variant | Steps | CFG | File size (FP8) | Use case | DirectML? |
|---------|-------|-----|------------------|----------|-----------|
| **Base** | 28-50 | 3.0-5.0 | ~6.15 GB | Highest quality, negative prompt works fully | No (OOM) |
| **Distill-8-Step** | 8 | 1.0 | ~6.15 GB | Speed + quality balance | No (OOM) |
| **Distill-4-Step** | 4 | 1.0 | ~6.15 GB | Fast iteration, batch gen | No (OOM) |
| **GGUF Q4_K_S** | 28-50 | 3.0-5.0 | ~4.51 GB | Low VRAM / CPU | No (GGUF dequant) |
| **GGUF Q8_0** | 28-50 | 3.0-5.0 | ~7.22 GB | Better quality GGUF | No (GGUF dequant) |
| **AIO FP8** | per variant | per variant | ~10.5 GB | Single-file convenience | No (OOM) |

All variants aim for **8 GB VRAM**; on 6 GB cards use GGUF Q4_K_S or FP8
distill variants at lower resolutions (512×768 vs 1024×1024).

### Resolution Guide (all variants)

| Use Case | Resolution |
|----------|------------|
| Portrait / character art | 832 × 1216 |
| Landscape / scenes | 1216 × 832 |
| Square / general | 1024 × 1024 |
| Tall / full body | 768 × 1344 |
| Wide / cinematic | 1920 × 1088 |

Support range: ~512×512 up to 2048×2048, any aspect ratio.

### Required Custom Nodes

- `rgthree-comfy` — provides Reroute nodes and workflow utilities
- `ComfyUI-Lora-Manager` — for LoRA support (optional but common)
- `ComfyUI-GGUF` — **required** if using GGUF variants, loads from `models/unet/`
  **DirectML caveat:** GGUF dequantizer is incompatible with DirectML
  (see Known Issues item 4/5). Do not use GGUF on AMD Windows / DirectML setups.

### Workflow Notes

- The official Z-Anime workflow (`workflows/Z-Anime-Workflow-v1.json`) is in
  **editor format** (top-level `nodes`/`links` arrays, 50 kB). It must be
  converted to API format before use with `run_workflow.py`.
- For standard variants, use node types:
  - `Load Diffusion Model` (loads from `models/diffusion_models/`)
  - `CLIP Loader` (loads text encoder from `models/clip/`)
  - `VAE Loader` (loads from `models/vae/`)
  - `DualCLIPLoader` or `CLIPTextEncode` for encoding
  - `KSampler` with sampler `euler_ancestral` / scheduler `beta`
- For AIO variants, use standard `CheckpointLoaderSimple` — all components
  are bundled.
- Loading a 6B DiT + 4B text encoder into 6 GB VRAM is tight and NOT
  viable on AMD DirectML / 6 GB VRAM setups (see Known Issues below).
4. **DirectML compatibility:** The `ComfyUI-GGUF` node may have custom ops
   that use CUDA. Test with a 4-step small image first.

5. **GGUF dequantizer incompatible with DirectML:** The `ComfyUI-GGUF` node's
   dequantizer (`dequant.py`) uses `blocks.view(torch.int16)` which fails on
   DirectML because DML tensors use `OpaqueTensorImpl` — `.view()` type
   reinterpretation is unsupported. Error: `Cannot access storage of
   OpaqueTensorImpl`. This means **all GGUF variants are incompatible with
   DirectML**. Only SD 1.5-based models are reliable on DirectML.

### Download from HuggingFace

Use curl or `comfy model download`. URL pattern:
```
https://huggingface.co/{USER}/{REPO}/resolve/main/{FOLDER}/{FILENAME}
```

Example — Z-Anime (full repo at `SeeSee21/Z-Anime`):
```bash
# Standard FP8 model + text encoder + VAE
curl -L -o ~/Documents/comfy/ComfyUI/models/diffusion_models/z-anime-distill-8step-fp8.safetensors \
  "https://huggingface.co/SeeSee21/Z-Anime/resolve/main/diffusion_models/z-anime-distill-8step-fp8.safetensors"

curl -L -o ~/Documents/comfy/ComfyUI/models/clip/qwen_3_4b-fp8.safetensors \
  "https://huggingface.co/SeeSee21/Z-Anime/resolve/main/text_encoder/qwen_3_4b-fp8.safetensors"

curl -L -o ~/Documents/comfy/ComfyUI/models/vae/ae.safetensors \
  "https://huggingface.co/SeeSee21/Z-Anime/resolve/main/vae/ae.safetensors"

# Or GGUF Q4_K_S (smallest, best for 6 GB VRAM)
curl -L -o ~/Documents/comfy/ComfyUI/models/unet/z-anime-base-q4_k_s.gguf \
  "https://huggingface.co/SeeSee21/Z-Anime/resolve/main/gguf/z-anime-base-q4_k_s.gguf"
```

See `references/z-image-s3-dit-models.md` for per-model specifics
(fine-tune variants, recommended settings per model, known issues).

## Image Upload (img2img / Inpainting)

The simplest way is to use `--input-image` with `run_workflow.py`:

```bash
python3 scripts/run_workflow.py \
  --workflow workflows/sdxl_img2img.json \
  --input-image image=./photo.png \
  --args '{"prompt": "make it cyberpunk", "denoise": 0.6}'
```

The flag uploads `photo.png`, then injects its server-side filename into
whatever schema parameter is named `image`. For inpainting, pass both:

```bash
python3 scripts/run_workflow.py \
  --workflow workflows/sdxl_inpaint.json \
  --input-image image=./photo.png \
  --input-image mask_image=./mask.png \
  --args '{"prompt": "fill with flowers"}'
```

Manual upload via REST:
```bash
curl -X POST "http://127.0.0.1:8188/upload/image" \
  -F "image=@photo.png" -F "type=input" -F "overwrite=true"
# Returns: {"name": "photo.png", "subfolder": "", "type": "input"}

# Cloud equivalent:
curl -X POST "https://cloud.comfy.org/api/upload/image" \
  -H "X-API-Key: $COMFY_CLOUD_API_KEY" \
  -F "image=@photo.png" -F "type=input" -F "overwrite=true"
```

## Cloud Specifics

- **Base URL:** `https://cloud.comfy.org`
- **Auth:** `X-API-Key` header (or `?token=KEY` for WebSocket)
- **API key:** set `$COMFY_CLOUD_API_KEY` once and the scripts pick it up automatically
- **Output download:** `/api/view` returns a 302 to a signed URL; the scripts
  follow it and strip `X-API-Key` before fetching from the storage backend
  (don't leak the API key to S3/CloudFront).
- **Endpoint differences from local ComfyUI:**
  - `/api/object_info`, `/api/queue`, `/api/userdata` — **403 on free tier**;
    paid only.
  - `/history` is renamed to `/history_v2` on cloud (the scripts route
    automatically).
  - `/models/<folder>` is renamed to `/experiment/models/<folder>` on cloud
    (the scripts route automatically).
  - `clientId` in WebSocket is currently ignored — all connections for a
    user receive the same broadcast. Filter by `prompt_id` client-side.
  - `subfolder` is accepted on uploads but ignored — cloud has a flat namespace.
- **Concurrent jobs:** Free/Standard: 1, Creator: 3, Pro: 5. Extras queue
  automatically. Use `run_batch.py --parallel N` to saturate your tier.

## Queue & System Management

```bash
# Local
curl -s http://127.0.0.1:8188/queue | python3 -m json.tool
curl -X POST http://127.0.0.1:8188/queue -d '{"clear": true}'    # cancel pending
curl -X POST http://127.0.0.1:8188/interrupt                      # cancel running
curl -X POST http://127.0.0.1:8188/free \
  -H "Content-Type: application/json" \
  -d '{"unload_models": true, "free_memory": true}'

# Cloud — same paths under /api/, plus:
python3 scripts/fetch_logs.py --tail-queue --host https://cloud.comfy.org
```

## Pitfalls

1. **API format required** — every script and the `/api/prompt` endpoint expect
   API-format workflow JSON. The scripts detect editor format (top-level
   `nodes` and `links` arrays) and tell you to re-export via
   "Workflow → Export (API)" (newer UI) or "Save (API Format)" (older UI).

2. **Server must be running** — all execution requires a live server.
   `comfy launch --background` starts one. Verify with
   `curl http://127.0.0.1:8188/system_stats`.

3. **Model names are exact** — case-sensitive, includes file extension.
   `check_deps.py` does fuzzy matching (with/without extension and folder
   prefix), but the workflow itself must use the canonical name. Use
   `comfy model list` to discover what's installed.

4. **Missing custom nodes** — "class_type not found" means a required node
   isn't installed. `check_deps.py` reports which package to install;
   `auto_fix_deps.py` runs the install for you.

5. **Working directory** — `comfy-cli` auto-detects the ComfyUI workspace.
   If commands fail with "no workspace found", use
   `comfy --workspace /path/to/ComfyUI <command>` or
   `comfy set-default /path/to/ComfyUI`.

6. **Cloud free-tier API limits** — `/api/prompt`, `/api/view`, `/api/upload/*`,
   `/api/object_info` all return 403 on free accounts. `health_check.py` and
   `check_deps.py` handle this gracefully and surface a clear message.

7. **Timeout for video/audio workflows** — auto-detected when an output node
   is `VHS_VideoCombine`, `SaveVideo`, etc.; the default jumps from 300 s to
   900 s. Override explicitly with `--timeout 1800`.

8. **Path traversal in output filenames** — server-supplied filenames are
   passed through `safe_path_join` to refuse anything escaping `--output-dir`.
   Keep this protection on — workflows with custom save nodes can produce
   arbitrary paths.

9. **Workflow JSON is arbitrary code** — custom nodes run Python, so
   submitting an unknown workflow has the same trust profile as `eval`.
   Inspect workflows from untrusted sources before running.

10. **Auto-randomized seed** — pass `seed: -1` in `--args` (or use
    `--randomize-seed` and omit the seed) to get a fresh seed per run.
    The actual seed is logged to stderr.

11. **`tracking` prompt** — first run of `comfy` may prompt for analytics.
    Use `comfy --skip-prompt tracking disable` to skip non-interactively.
    `comfyui_setup.sh` does this for you.

12. **`_comment` keys in workflow JSON cause 500 errors** — workflow files
    exported with a `_comment` top-level key (common in this skill's example
    workflows) break the API endpoint. The server iterates all keys and hits
    the string value for `_comment`, causing `AttributeError: 'str' object
    has no attribute 'get'`. **Always strip non-node keys before submitting:**
    ```python
    keys_to_remove = [k for k in workflow if k.startswith('_')]
    for k in keys_to_remove:
        del workflow[k]
    ```

13. **torchaudio version mismatch** — if you're using a custom venv with a
    different torch version from the system Python (common in DirectML setups),
    the wrong torchaudio version may have been installed. Symptoms: ComfyUI
    crashes on startup with `Windows fatal exception: code 0xc0000139` or a
    DLL load error. Fix: uninstall the mismatched torchaudio and install the
    version matching your torch:
    ```bash
    ../venv/Scripts/python -m pip uninstall -y torchaudio
    ../venv/Scripts/python -m pip install "torchaudio==$(../venv/Scripts/python -c 'import torch; print(torch.__version__)')"
    ```

14. **Workflows bundled with model repos are often in editor format** — many
    HuggingFace model pages include a `workflows/` folder, but these are
    usually in editor format (top-level `nodes`/`links` arrays, `id` field).
    They cannot be submitted directly via `/api/prompt`. Convert them in the
    ComfyUI GUI (Workflow → Export API), or build a minimal API-format
    workflow from scratch using the correct node types (e.g. `Load Diffusion
    Model` for S3-DiT models, not `CheckpointLoaderSimple`).

15. **CLIP node reference in `CheckpointLoaderSimple` (CRITICAL)** — the
    `CheckpointLoaderSimple` node outputs three values at array indices:
    `[0] = MODEL`, `[1] = CLIP`, `[2] = VAE`. Both positive and negative
    `CLIPTextEncode` nodes MUST reference the CLIP output at index 1, i.e.
    `"clip": ["N", 1]` where N is the loader node ID. Using index 0 (`["N", 0]`)
    references MODEL and causes a `return_type_mismatch` validation error
    (`received_type(MODEL) mismatch input_type(CLIP)`). Not a connection
    wiring error — the schema looks correct but the index is wrong. Always
    verify: positive encode → `["loader", 1]`, negative encode → `["loader", 1]`,
    VAEDecode → `["loader", 2]`. The `KSampler` model input uses `["loader", 0]`
    (MODEL), which is correct.

16. **Windows/MSYS path mangling in Python subprocess calls** — on Windows with
    git-bash, when calling `run_workflow.py` from another Python script via
    `subprocess.run(['python', script, ...])`, the script path must use
    **Windows-style forward-slash paths** (`E:/hermes/skills/...`).
    MSYS-style paths (`/e/hermes/skills/...`) get mangled to `E:\e\hermes\...`
    because Windows Python does not understand MSYS path expansion.
    Symptom: `python: can't open file 'E:\e\hermes\...'`. Fix: always write
    `E:/...` style paths in Python subprocess calls, not `/e/...`.

## Verification Checklist

Use `python3 scripts/health_check.py` to run the whole list at once. Manual:

- [ ] `hardware_check.py` verdict is `ok` OR the user explicitly chose Comfy Cloud
- [ ] `comfy --version` works (or `uvx --from comfy-cli comfy --help`)
- [ ] `curl http://HOST:PORT/system_stats` returns JSON
- [ ] `comfy model list` shows at least one checkpoint (local) OR
      `/api/experiment/models/checkpoints` returns models (cloud)
- [ ] Workflow JSON is in API format
- [ ] `check_deps.py` reports `is_ready: true` (or only `node_check_skipped`
      on cloud free tier)
- [ ] Test run with a small workflow completes; outputs land in `--output-dir`
