# ComfyUI Workflow Node Layout (Counterfeit V3 / SD 1.5)

Canonical 7-node layout used for all animated storytelling workflows. Copy
this structure and substitute only the prompt text, negative prompt, seed,
and filename_prefix.

## Node Map

```
[1] CheckpointLoaderSimple          → [MODEL, CLIP, VAE]
       ckpt_name: Counterfeit-V3.0_fp16.safetensors
       Outputs: slot 0=MODEL, slot 1=CLIP, slot 2=VAE

[2] CLIPTextEncode (positive)       ← ["1", 1]  (CLIP)
       text: <natural language prompt>

[3] CLIPTextEncode (negative)       ← ["1", 1]  (CLIP) ← CRITICAL: NOT [0]
       text: <scene-specific negative prompt>

[4] EmptyLatentImage
       width: 512, height: 768, batch_size: 1

[5] KSampler
       seed: <scene seed>, steps: 30, cfg: 7.0
       sampler_name: euler, scheduler: normal, denoise: 1.0
       model ← ["1", 0], positive ← ["2", 0], negative ← ["3", 0]
       latent_image ← ["4", 0]

[6] VAEDecode                       ← ["5", 0], vae ← ["1", 2]
       samples ← ["5", 0], vae ← ["1", 2]  (VAE at slot 2)

[7] SaveImage                       ← ["6", 0]
       filename_prefix: <story>_scene<N>_<title>
       images ← ["6", 0]
```

## Output Indices (CheckpointLoaderSimple)

| Index | Type  | Used by               |
|-------|-------|-----------------------|
| 0     | MODEL | KSampler.model        |
| 1     | CLIP  | CLIPTextEncode (+ and −) |
| 2     | VAE   | VAEDecode.vae         |

## Common Bug: Negative Encode CLIP Reference

**WRONG (will fail with return_type_mismatch):**
```json
"3": {
  "inputs": {"text": "...", "clip": ["1", 0]},   // ← MODEL, not CLIP!
  "class_type": "CLIPTextEncode"
}
```

**CORRECT:**
```json
"3": {
  "inputs": {"text": "...", "clip": ["1", 1]},   // ← CLIP at index 1
  "class_type": "CLIPTextEncode"
}
```

Both positive and negative CLIPTextEncode nodes use `["1", 1]`. Only KSampler
uses `["1", 0]` (for the model input). Only VAEDecode uses `["1", 2]` (for the
VAE input).

## Generation Parameters (RX 5600 XT / DirectML)

| Parameter     | Value                                      |
|---------------|--------------------------------------------|
| Checkpoint    | Counterfeit-V3.0_fp16.safetensors          |
| Resolution    | 512×768 (portrait)                         |
| Steps         | 30                                         |
| CFG           | 7.0                                        |
| Sampler       | euler                                      |
| Scheduler     | normal                                     |
| Time per img  | ~69 seconds                                |
| VRAM          | ~4.2 GB (checkpoint) + ~1-2 GB (inference) |
