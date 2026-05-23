# Batch Story Image Pipeline

Pattern for generating a multi-scene story with ComfyUI: one workflow JSON per scene, batch-run via a Python script.

## Architecture

```
workflows/
├── siege_scene01.json      # Scene 1, seed 7201
├── siege_scene02.json      # Scene 2, seed 7202
├── siege_scene2b.json      # Scene 2b (variant), seed 7226
└── ...

batch_gen.py                # Iterates scene_order → runs run_workflow.py per scene
```

Each workflow is a self-contained ComfyUI API-format JSON with prompt, seed, dimensions, and model baked in.

## Scene Order

Define a `scene_order` list in the batch script. Supports integer and string scene IDs:

```python
scene_order = [
    1, 2, '2b', 3, 4, 5, 6, 7, 8, 9, 10, '10b',
    11, 12, '12b', 13, 14, '14b', 15, 16,
    17, 18, 19, '19b', 20, 21, '21b',
    22, '22b', 23, 24, 25
]
```

Filename generation:
```python
fn = f'siege_scene{n:02d}.json' if isinstance(n, int) else f'siege_scene{n}.json'
```

## Seed Conventions

| Pass | Offset | Example |
|------|--------|---------|
| Original | base | 7201 → 7225 (main), 7226→7233 (b-scenes) |
| Polish (pass 2) | +100 | 7301 → 7333 |
| Polish (pass 3) | +200 | 7401 → 7433 |

Seeds are deterministic per scene — each scene always gets the same seed per pass for reproducibility. The b-scene variants get seeds in a separate sub-range after the main scenes.

## Polish Runs (Multi-pass Iteration)

When the user asks for a "polish run" (refined prompts + new seeds):

### Step 1: Deploy parallel subagents for prompt refinement

```python
# Split scene order across N subagents (~10 scenes each)
delegate_task(tasks=[
    {"goal": f"Create polished workflows for scenes {batch}", ...},
    ...
])
```

Each subagent **reads the original workflow** from disk, then writes a `_polished` variant with:

- **Polished positive prompt** — enriched with specific lighting/color, texture details, composition cues (angle, perspective, framing), stronger emotional tone indicators. Still ends with `"High quality anime illustration."`
- **New seed** — original + offset (e.g. +200)
- **Updated filename_prefix** — original prefix with `_P` suffix (e.g. `siege_scene01_First_Watch_P`)
- **Everything else unchanged** — model, dimensions, sampler, steps, CFG, negative prompt

### Step 2: Batch runner

```python
# batch_polished.py
scene_order = [...]  # same order
for n in scene_order:
    fn = f'siege_scene{n:02d}_polished.json' if isinstance(n, int) else f'siege_scene{n}_polished.json'
    subprocess.run(['python', script, '--workflow', path, ...])
```

### Prompt Polishing Guidelines

Write refined prompts as natural language sentences with:

- **Shot type** — low angle / high angle / extreme close-up / split-focus / wide / medium
- **Lighting & color** — warm amber dusk light, cold grey-blue dawn, crimson torchlight, harsh mid-day shadows, ultramarine night, golden sunrise glow
- **Texture details** — dust motes in shaft of light, smoke haze, weathered oak grain, blood-slicked stone, worn leather creases, sweat-glistening skin, fur, rusted iron
- **Emotional tone** — haunted exhaustion, primal defiance, quiet devastation, calculating resolve, weary pride
- **Action specifics** — sweat beads, splinters mid-flight, spear inches from eye, bowstring vibrating, cloak streaming

## Output Management

- **Original files stay untouched** — all variants get `_polished` suffix in filename
- **Output filenames** use the changed `filename_prefix` from the workflow so they sort alongside originals
- **Keep all output directories** — every pass produces unique files due to different seeds

## Pitfalls

1. **Windows/MSYS path mangling** — in Python subprocess calls, use `E:/` (forward slashes, Windows-style) not `/e/` (MSYS-style). MSYS paths get mangled by Windows Python to `E:\\e\\hermes\\...`.
2. **b-scene seeds** — the b-scenes (variants of main scenes like 2b, 10b) are NOT in sequence 7201-7225. They use separate seed slots (7226-7233). Track these carefully in the seed map.
3. **Subagent lack of context** — each subagent has zero knowledge of other scenes. Pass the full original prompt text and seed mapping in the context so they can produce consistent refinement quality across the whole story.
4. **Prompt length** — keep polished prompts under ~450 chars (Counterfeit V3 can truncate or ignore very long prompts at the CLIP level).
