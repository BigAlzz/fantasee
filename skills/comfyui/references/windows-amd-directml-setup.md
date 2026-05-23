# Windows AMD + DirectML ComfyUI Setup (Alistair's machine)

**Host:** Windows 10 (git-bash/MSYS)
**GPU:** AMD Radeon RX 5600 XT (~4 GB VRAM detected via WMI, 6 GB actual)
**User:** alist
**Workspace:** `C:/Users/alist/Documents/comfy/ComfyUI`
**DirectML venv:** `C:/Users/alist/Documents/comfy/venv/` (Python 3.11.15)

## Python situation

- System Python 3.14.4 at `C:\Python314\python.exe` — too new for torch-directml
- Python 3.11.15 at `C:/Users/alist/AppData/Roaming/uv/python/cpython-3.11.15-windows-x86_64-none/python.exe` — installed via `uv`, works with torch-directml

## Setup commands

```bash
# Install comfy-cli
/C/Python314/python -m pip install comfy-cli

# Install base ComfyUI (CPU deps, skip torch)
comfy --skip-prompt tracking disable
comfy --skip-prompt install --cpu --skip-torch-or-directml --restore --fast-deps

# Create DirectML venv with Python 3.11
/c/Users/alist/AppData/Roaming/uv/python/cpython-3.11.15-windows-x86_64-none/python.exe -m venv ~/Documents/comfy/venv

# Install DirectML torch
~/Documents/comfy/venv/Scripts/python -m pip install torch-directml
~/Documents/comfy/venv/Scripts/python -m pip install -r ~/Documents/comfy/ComfyUI/requirements.txt
~/Documents/comfy/venv/Scripts/python -m pip install "torchaudio==2.4.1"  # match torch 2.4.1
```

## Launch

```bash
cd ~/Documents/comfy/ComfyUI
~/Documents/comfy/venv/Scripts/python main.py --directml --listen 127.0.0.1 --port 8188
```

## Verified generation

- SD 1.5 model: `v1-5-pruned-emaonly.safetensors` (3.97 GB)
- Workflow: skill's `workflows/sd15_txt2img.json`
- Generation: 512×512, 20 steps, seed 42 → ~69 seconds
- Output: `C:\Users\alist\Documents\comfy\ComfyUI\output\sd15_00001_.png`

## Known issues

1. **`_comment` key must be stripped** from workflow JSON before submitting via API
2. **torchaudio version mismatch** if ComfyUI requirements installed a different version than torch
3. **`comfy --skip-prompt install --amd` fails on Windows** (tries ROCm, Linux-only)
4. **Port 8188 conflict** — the CPU-based system Python ComfyUI may auto-start and block the port
5. **VRAM incorrectly reported as 1 GB** — DirectML allocates default 1 GB; actual card has 6 GB
