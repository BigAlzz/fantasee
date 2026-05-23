# Fantasy Prompting Guide — DreamShaper V8

Model: `DreamShaper_8_pruned.safetensors` (SD 1.5, ~2 GB)
Source: Lykon/DreamShaper on HuggingFace
Style target: Fantasy illustration, digital painting, concept art
VRAM on DirectML: ~2.1 GB — heads-up for 6 GB cards

## Quick Reference

| Parameter | Value |
|-----------|-------|
| Checkpoint | DreamShaper_8_pruned.safetensors |
| Resolution | 512×768 (portrait) or 768×512 (landscape) |
| Sampler | dpmpp_2m |
| Scheduler | karras |
| Steps | 25 |
| CFG | 7 |
| Prompt prefix | `digital painting of ` |
| Negative prefix | Standard + style exclusions |

## Prompt Structure

```
digital painting of <shot type> of <subject> wearing <outfit> in <setting>.
<lighting and atmosphere>. <artistic style details>.
```

### Shot types
Same as anime prompting: wide establishing shot, medium portrait, close-up,
low angle, cinematic wide.

### Artistic style terms (append to positive prompt)
```
concept art, fantasy illustration, dramatic lighting, intricate details,
volumetric lighting, painterly style, artstation trending, masterpiece,
high quality digital painting
```

## Full Negative Prompt

```
ugly, blurry, low quality, deformed, bad anatomy, watermark, text, letters,
words, signature, distorted, extra limbs, photograph, realistic photo,
hyperrealistic, anime, cartoon, manga, 3d render, cgi, plastic, doll, smooth,
airbrushed, oversaturated, lens flare, bokeh, chromatic aberration,
poorly drawn, bad proportions, lowres, jpeg artifacts
```

### Scene-specific additions
- Fantasy battle: `peaceful, quiet, calm, modern, technology, cars`
- Dark/dungeon: `bright daylight, sunny, cheerful, outdoor, blue sky`
- Nature/wilderness: `buildings, city, urban, technology, modern, machines`
- Hope/victory: `darkness, gloom, despair, night, horror, blood`

## Example Prompts

**Wide establishing shot (fantasy ruins):**
> digital painting of a wide establishing shot of ancient stone ruins half-swallowed by forest, moss-covered arches and fallen pillars. Golden hour sunlight filtering through dense canopy, atmospheric mist hanging low. Concept art, fantasy illustration, dramatic lighting, volumetric lighting, intricate details, painterly style, masterpiece, high quality digital painting.

**Medium character portrait (warrior):**
> digital painting of a medium character portrait of Aldric, a weathered veteran with grey-streaked dark hair and tired steel-blue eyes, wearing worn plate armour with a broken crest. Standing on a windswept ridge at dusk. Rim lighting from a dying sun, fine brushstrokes, evocative expression. Fantasy illustration, dramatic lighting, intricate details, masterpiece, high quality digital painting.

**Action scene:**
> digital painting of a dynamic medium shot of a battle in a burning fortress courtyard, warriors clashing amidst flames and smoke. Dramatic low angle, motion blur, embers swirling in the air. Volumetric lighting from fire, high contrast chiaroscuro. Concept art, fantasy illustration, dramatic lighting, masterpiece, high quality digital painting.

## On AMD DirectML (RX 5600 XT, 6 GB)

- Generation time: ~69s per 512×768 image at 25 steps
- DreamShaper V8 uses ~2.1 GB VRAM — fits comfortably on 6 GB
- Submit images sequentially via `run_workflow.py` (one at a time)
- See animated-storytelling pitfall #11b for crash risk mitigations
