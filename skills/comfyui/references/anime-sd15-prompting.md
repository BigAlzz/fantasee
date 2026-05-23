# Anime SD 1.5 Prompting Guide (DirectML / Counterfeit V3)

## Model: Counterfeit V3.0

**File:** `models/checkpoints/Counterfeit-V3.0_fp16.safetensors` (~4.0 GB)
**Source:** `https://huggingface.co/gsdf/Counterfeit-V3.0/resolve/main/Counterfeit-V3.0_fp16.safetensors`
**Base:** SD 1.5 (works on DirectML, ~69s per 512×768 image on RX 5600 XT)
**License:** CreativeML Open RAIL-M

### Recommended Settings (Counterfeit V3)

- Steps: 30
- CFG: 7.0
- Sampler: euler
- Scheduler: normal
- Resolution: 512×768 (portrait), 768×512 (landscape), 512×512 (square)
- Negative prompt: always include quality anti-terms

## Prompting Style

Natural language descriptions work best — NOT tag lists. The model was trained on
captioned images, not Danbooru-style tags (despite common SD 1.5 lore).

### ✅ Good — Natural Language

> A young anime girl with long silver hair and golden eyes, wearing a traditional
> shrine maiden outfit with white haori and red hakama. She stands in a sunlit
> bamboo forest, cherry blossoms falling softly around her. Warm afternoon light
> filtering through the trees, detailed fabric shading, expressive face, calm
> serene expression, high quality anime illustration with fine line work.

### ❌ Avoid — Tag Lists

> `1girl, silver_hair, golden_eyes, shrine_maiden, bamboo, cherry_blossoms,
> warm_lighting, detailed, masterpiece`

## Cinematic Prompt Structure

For story-driven scenes, structure prompts with:

1. **Shot type** — `wide shot` / `medium shot` / `close-up` / `low angle` / `bird's eye`
2. **Subject description** — Character name, appearance, clothing, expression
3. **Setting** — Where and when (time of day, location)
4. **Lighting & atmosphere** — Mood, color palette, light source
5. **Art direction** — Cinematic composition, detail level, style qualifiers

### Scene Type Templates

**Establishing shots (landscapes/locations):**
> A wide establishing shot of [location] at [time of day]. [Visual details of
> architecture/nature]. [Lighting description]. [Atmosphere]. Beautiful
> background art, atmospheric perspective, cinematic composition, high quality
> anime illustration.

**Character portraits:**
> A medium character portrait of [name], [appearance details], wearing [outfit].
> [Setting details]. Soft rim lighting, expressive eyes with detailed
> reflections, fine hair strands, clean linework, high quality anime
> illustration.

**Action scenes:**
> A dynamic [wide/medium] shot of [scene] at [time of day]. [Action details,
> character movements, environmental effects]. Dramatic angle, motion energy,
> particle effects, cinematic composition, dramatic lighting, high quality
> anime art.

## Character Bible Technique

For multi-scene stories, define every character once in a **character bible**
and use the **exact same descriptive terms** in every scene prompt. This gives
the model the best chance of visual consistency (SD 1.5 cannot guarantee same
face across seeds, but consistent tags help).

### Example Character Bible Entry

```yaml
Kaelen:
  age: ~20s
  hair: short messy dark-brown hair
  eyes: sharp green eyes
  build: lean determined face
  outfit: grey wool messenger coat with brass buttons, leather satchel across chest
  role: ceasefire broker, cautious and observant
```

### Character Tagging Rules

- Use the same hair color, eye color, and clothing descriptors in every prompt
- Add a unique identifier (like "young man named Kaelen") in scene-appropriate context
- Avoid contradicting descriptors between scenes
- For the main subject, front-load their description in the prompt

## Fixed Seeds for Reproducibility

Always use fixed seeds (not random) when generating multi-scene stories. This
lets you regenerate any scene independently and keeps results stable across
re-runs. Choose sequential seeds (1001, 2002, 3003, etc.) for easy tracking.

## Known Working Anime Models on DirectML

| Model | Size | Notes |
|-------|------|-------|
| Counterfeit V3.0 fp16 | 4.0 GB | Excellent anime style, natural language prompts work best |
| Anything V5 (merged) | ~2 GB | Older but reliable — use full model, not Diffusers format |
| Pastel Mix | ~2 GB | Softer art style |
| v1-5-pruned-emaonly-fp16 | 1.6 GB | Generic, use with strong anime-style prompting |

All SD 1.5-based models work on DirectML. Models larger than 2 GB may load
slower but run at the same speed once in VRAM.

## Models That Do NOT Work on DirectML

| Model | Reason |
|-------|--------|
| Z-Anime GGUF (any quantization) | ComfyUI-GGUF dequantizer uses `.view(torch.int16)` which DirectML doesn't support |
| Z-Anime standard FP8/BF16 | 6.15 GB DiT + 4 GB text encoder exceeds 6 GB VRAM on RX 5600 XT |
| Any S3-DiT (6B) model | Both GGUF and standard variants fail on DirectML / 6 GB setups |
| Flux | Impractical on DirectML (huge model, CUDA-specific ops) |
| SDXL | May run at very low resolutions on 6 GB, but tight |
