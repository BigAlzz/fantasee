# Story Engine - Technical Documentation & Architecture Plan

> Canticle Software | Alistair | 2026-06-16 | DRAFT

---

## Part 1: Current Systems

### 1.1 Fantasee (C:/dev/fantasee/)

**Purpose:** Monolithic story generation pipeline. Generates illustrated, narrated stories from a text concept.

**Stack:**
- LLM: MiMo-V2.5-Pro (Xiaomi API, OpenAI-compatible)
- Images: ComfyUI 0.22.0 (AMD DirectML, ~81s/image)
- TTS: MiMo-V2.5-TTS (Xiaomi API, voices: Mia, Chloe, Milo, Dean)
- Subtitles: OpenAI Whisper base (local, word timestamps)
- Video: FFmpeg (PNG to MP4 with audio + subtitle overlay)
- Server: FastAPI on port 8765, Netflix-style viewer
- Storage: Flat files in outputs/<story-id>/<story-id>.json

**File Map (5,899 LOC):**
```
server.py (1615)         - FastAPI server, all API routes, story viewer
generate_story.py (503)  - Main pipeline: outline, images, TTS, subtitles
critic.py (1060)         - Multi-dimension quality critic (5-star rating)
batch_pipeline.py (495)  - Extend scenes + quality improvement loop
comfyui_utils.py (452)   - ComfyUI prompt submission, polling, file copy
tts_utils.py (354)       - MiMo TTS with voice-design model fallback
render_video.py (520)    - FFmpeg video assembly with subtitle overlay
generate_subtitles.py (325) - Whisper transcription to JSON subtitles
batch_improve.py (225)   - Batch quality improvement across stories
batch_generate.py (111)  - Batch story generation from concepts
```

**Data Model (manifest.json):**
```json
{
  "id": "crown-of-steel",
  "title": "Crown of Steel",
  "description": "...",
  "tags": ["fantasy", "dramatic"],
  "scenes": [
    {
      "scene": "01",
      "title": "The Forge",
      "prompt": "80-150 word image generation prompt...",
      "narration": "80-150 word voiceover text...",
      "narration_text": "same as narration",
      "narrative": "40-80 word scene description...",
      "seed": 12345,
      "image_filenames": ["story_s01_The_Forge_01_00001_.png"],
      "audio_filename": "tts_story_s01.wav",
      "audio_duration": 24.5,
      "subtitle_file": "subs_story_s01.json"
    }
  ]
}
```

**Pipeline Steps:**
1. Title generation (LLM)
2. Description generation (LLM)
3. Scene outline generation (LLM, structured "--- SCENE N" format)
4. Image generation (ComfyUI, N per scene)
5. TTS generation (MiMo TTS per scene)
6. Subtitle alignment (Whisper per scene)
7. Manifest save

**Known Problems:**
- Monolithic: Changing one scene regenerates everything
- No incremental editing: Cannot modify a single prompt without re-running full pipeline
- Brittle JSON parsing: LLM output parsing fails silently
- No checkpointing: Pipeline failure at scene 15/20 loses all prior work
- Duplicate code: LLM calling, TTS, image gen logic duplicated across files
- No dependency tracking: Can't tell which images need regenerating after prompt edit
- Shallow critic: Quality improvement loop is max 3 rounds

---

### 1.2 Mindstream (E:/Lab/mindstream/)

**Purpose:** AI Course Factory. Originally for e-learning, extended to fiction stories with agent-based architecture.

**Stack:**
- LLM: LangChain + ChatOpenAI (Xiaomi, DeepSeek, LM Studio routing)
- Images: ComfyUI Agent (same ComfyUI instance)
- TTS: MiMo TTS (voice design + voice clone)
- DB: SQLite + SQLAlchemy (course_data stored as JSON blob)
- API: FastAPI on port 8000
- Frontend: React (web-player), Netflix-style viewer
- Agents: 20+ specialized agents extending BaseAgent

**Agent Architecture:**
```
Orchestrator (story_orchestrator.py)
  +-- StoryOutlineAgent       - Full scene-by-scene outline with beats
  +-- StoryBibleAgent         - Character bible, voice assignments, world rules
  +-- StoryVisualAgent        - Model selection, anatomy-aware negatives
  +-- StoryVisualDirectorAgent - Panel layout, motion direction, shot composition
  +-- ComfyUIAgent            - Image generation dispatch
  +-- StoryEditorAgent        - Continuity checking, pacing fixes
  +-- StoryVoiceDirectorAgent - Per-scene voice performance, emotion tags
  +-- StoryNarrationAgent     - TTS audio generation
  +-- StoryQAAgent            - Quality checks
  +-- StoryRatingAgent        - Multi-critic rating
  +-- RepairAgent             - Auto-fix broken outputs
```

**Pipeline Steps (STORY_STEP_ORDER):**
1. outline - Full outline with cinematic shot vocabulary
2. bible - Story bible, cast, voice assignments
3. visual - Model selection, anatomy-aware negatives
4. visual_director - Panel composition, motion direction
5. comfyui - Image generation
6. editor - Continuity and pacing
7. voice_director - Voice performance direction
8. narration - TTS audio
9. qa - Quality assurance
10. rate - Critic panel review

**Key Features (vs Fantasee):**
- Checkpoint/Resume: _last_step saved to DB, can resume from any step
- Scene editing: Individual scenes can be modified and re-processed
- Shot vocabulary: Cinematic shot types (close_up, wide, dutch_angle, etc.)
- Story mountain pacing: Setup > Rising > Crisis > Climax shot distribution
- Anatomy-aware negatives: Scene-specific negative prompts
- Multi-provider LLM: Automatic failover between Xiaomi, DeepSeek, LM Studio
- Voice design: Describe a voice in natural language, no preset needed

**Storage Model:**
```
Course(course_data = JSON blob)
  modules[]        = scenes
    lessons[]      = beats/images
      lesson_data  = { prompt, negative_prompt, model, image_path, audio_path }
  story_bible      = { characters[], world_rules[] }
  _last_step       = checkpoint for resume
```

**Known Problems:**
- Course model hack: Stories shoehorned into Course table
- JSON blob storage: All state in one course_data field, no relational structure
- Agent timeout fragility: Each step has hard timeouts, complex resume logic
- 20+ agents: Over-engineered, many agents do very little
- Duplicated with Fantasee: Same TTS, image gen, and LLM code in both projects

---

## Part 2: Unified Story Engine - Architecture Plan

### 2.1 Design Principles

1. **Atomic Scenes** - Each scene is an independent unit with its own prompts, assets, and metadata. Edit one scene without touching others.

2. **Asset Deduplication** - Content-addressed storage. Same prompt + seed + model = same image, generated once and referenced everywhere.

3. **Incremental Pipeline** - Only regenerate what changed. Edit scene 5's prompt? Only scene 5's images are regenerated.

4. **Versioned Manifests** - Every edit creates a version. Roll back any scene to any previous state.

5. **Functional Generation** - Same inputs always produce same outputs. Deterministic seeds, cached assets.

6. **Composable Pipeline** - Each step is a function: (scene_data) -> scene_data. Steps can be run independently, skipped, or reordered.

### 2.2 Storage Architecture

```
data/
  stories/
    <story-id>/
      story.json              - Story metadata + scene index
      scene-01.json           - Scene manifest (versioned)
      scene-02.json
      .versions/              - Version history
        scene-01-v1.json
        scene-01-v2.json
      assets/                 - Content-addressed assets
        sha256-abc123.png     - Image (hash = prompt+seed+model)
        sha256-def456.wav     - TTS audio (hash = text+voice+style)
        sha256-ghi789.json    - Subtitles (hash = audio hash)
  cache/
    images/                   - Global image cache (shared across stories)
    audio/                    - Global audio cache
    prompts/                  - LLM response cache
  config/
    engine.yaml               - Engine configuration
    voices.json               - Voice presets
```

**Scene Manifest (scene-01.json):**
```json
{
  "scene": "01",
  "title": "The Forge",
  "story_id": "crown-of-steel",
  "version": 3,
  "modified_at": "2026-06-16T14:30:00Z",
  "narrative": {
    "text": "The queen stands alone at the forge...",
    "tone": "dramatic",
    "pacing": "setup"
  },
  "narration": {
    "text": "In the dying light of the forge, Queen Elara...",
    "voice": "Dean",
    "style": "dramatic",
    "rate": "-3%",
    "audio_hash": "sha256-def456",
    "audio_duration": 24.5
  },
  "images": [
    {
      "prompt": "A majestic wide shot of Queen Elara...",
      "negative": "blurry, deformed, extra limbs...",
      "model": "sd_xl_base_1.0",
      "seed": 12345,
      "width": 1024,
      "height": 576,
      "image_hash": "sha256-abc123",
      "shot_type": "wide",
      "camera_angle": "low_angle"
    }
  ],
  "subtitles": {
    "segments": [
      {"text": "In the dying light", "start": 0.0, "end": 1.5}
    ]
  },
  "pipeline_state": {
    "outline": "done",
    "images": "done",
    "tts": "done",
    "subtitles": "done",
    "critic": "pending"
  }
}
```

### 2.3 Pipeline Architecture

```
+----------------------------------------------------------+
|                    STORY ENGINE                          |
+----------------------------------------------------------+
|                                                          |
|  OUTLINE --> BIBLE --> SCENES                            |
|                                                          |
|          +----------------------------+                  |
|          |      SCENE PROCESSOR       |                  |
|          |  (per-scene, independent)  |                  |
|          +----------------------------+                  |
|                    |                                      |
|    +-------+-------+-------+                            |
|    |       |       |       |                             |
|  VISUAL  TTS    SUBS      QA                            |
|  DIRECTOR       GENERATOR                                |
|    |       |       |       |                             |
|  COMFYUI  MiMo   WHISPER  CRITIC                        |
|  (image)  TTS    (subs)                                  |
|                                                          |
|  ASSET CACHE (content-addressed)                         |
|  prompt+seed+model -> image   text+voice -> audio        |
|                                                          |
|  CRITIC / IMPROVEMENT LOOP                               |
|  rate -> identify weak scenes -> edit -> re-generate     |
+----------------------------------------------------------+
```

### 2.4 Core Engine Code Structure

```
story-engine/
  engine/
    __init__.py
    core/
      config.py              - Engine configuration
      llm.py                 - LLM client (MiMo, DeepSeek, fallback)
      storage.py             - Story/scene/asset storage layer
      cache.py               - Content-addressed asset cache
      models.py              - Pydantic models for Story, Scene, etc.
    agents/
      base.py                - BaseAgent with LLM + timeout
      outline.py             - Story outline generation
      bible.py               - Character bible + voice assignment
      visual.py              - Image prompt engineering + negatives
      visual_director.py     - Shot composition + camera direction
      editor.py              - Continuity + pacing checks
      voice_director.py      - Voice performance direction
      critic.py              - Multi-dimension quality rating
      repair.py              - Auto-fix broken outputs
    generators/
      images.py              - ComfyUI image generation
      tts.py                 - MiMo TTS generation
      subtitles.py           - Whisper subtitle alignment
      video.py               - FFmpeg video assembly
    pipeline/
      orchestrator.py        - Full story pipeline
      scene_processor.py     - Per-scene pipeline (the key piece)
      incremental.py         - Diff-based regeneration
      improvement.py         - Quality improvement loop
    api/
      server.py              - FastAPI server
      routes_story.py        - Story CRUD + pipeline triggers
      routes_scene.py        - Scene edit + regenerate
      routes_asset.py        - Asset serving + cache info
  data/
  tests/
  engine.yaml
  cli.py
```

### 2.5 The Key Innovation: Scene Processor

The scene processor is the core of the incremental approach. Each scene is processed
independently, and only changed scenes are re-processed.

```python
class SceneProcessor:
    def process(self, scene, force_steps=None):
        """Process a single scene through the pipeline.
        Each step is a pure function: scene_data -> scene_data.
        Steps can be run independently, skipped, or re-run.
        """
        steps = [
            ("visual", self._step_visual),
            ("visual_director", self._step_visual_director),
            ("images", self._step_images),
            ("editor", self._step_editor),
            ("voice_director", self._step_voice_director),
            ("tts", self._step_tts),
            ("subtitles", self._step_subtitles),
        ]
        for step_name, step_fn in steps:
            if force_steps and step_name not in force_steps:
                continue
            if not self._needs_rerun(scene, step_name) and not force_steps:
                continue
            scene = step_fn(scene)
            scene.pipeline_state[step_name] = "done"
            self._save_scene(scene)
        return scene

    def _needs_rerun(self, scene, step_name):
        if step_name == "images":
            return any(img._prompt_changed for img in scene.images)
        if step_name == "tts":
            return scene.narration._text_changed
        return True
```

### 2.6 Content-Addressed Asset Cache

```python
class AssetCache:
    def get_image_key(self, prompt, seed, model, width, height, negative=""):
        content = f"{prompt}|{seed}|{model}|{width}|{height}|{negative}"
        return f"img-{sha256(content)[:16]}"

    def get_audio_key(self, text, voice, style, rate="-3%"):
        content = f"{text}|{voice}|{style}|{rate}"
        return f"aud-{sha256(content)[:16]}"

    def has(self, key):
        return self._resolve(key).exists()

    def store(self, key, source_path):
        cached = self._resolve(key)
        shutil.move(str(source_path), str(cached))
        return cached

    def link(self, key, dest_path):
        """Hard-link cached asset to destination (zero-copy)."""
        cached = self._resolve(key)
        if cached.exists():
            if dest_path.exists():
                dest_path.unlink()
            os.link(str(cached), str(dest_path))
            return True
        return False
```

### 2.7 Incremental Editing Workflow

**Scenario:** Change scene 5's image prompt from "a forge" to "a throne room".

```bash
# 1. Edit scene 5's prompt
story-engine scene edit crown-of-steel scene-05 \
    --set-image-prompt 0="A majestic throne room with golden light..."

# 2. Preview what will change
story-engine scene diff crown-of-steel scene-05
# Output:
#   IMAGE 0: prompt changed (will regenerate)
#   IMAGE 1: unchanged (cached)
#   TTS: unchanged (cached)
#   SUBS: unchanged (cached)

# 3. Apply changes - only generates 1 new image
story-engine scene apply crown-of-steel scene-05

# 4. Or edit narration text too
story-engine scene edit crown-of-steel scene-05 \
    --set-narration="The throne room fell silent..."
# Now both image AND TTS need regeneration
story-engine scene apply crown-of-steel scene-05
```

**Programmatic API:**
```python
from engine.pipeline.orchestrator import StoryOrchestrator

orch = StoryOrchestrator()

# Edit a scene
scene = orch.get_scene("crown-of-steel", "scene-05")
scene.images[0].prompt = "A majestic throne room..."
scene.narration.text = "The throne room fell silent..."
scene.save()  # Creates version snapshot

# Regenerate only changed assets
result = orch.process_scene("crown-of-steel", "scene-05")
# result.images_regenerated: 1
# result.images_cached: 1
# result.tts_regenerated: 1
# result.tts_cached: 0
# result.total_time: 85s (not 250s for full regen)
```

### 2.8 Critic and Improvement Loop

```
+----------------------------------------------+
|            IMPROVEMENT LOOP                   |
+----------------------------------------------+
|                                               |
|  1. Rate all scenes (critic agent)            |
|     -> Per-scene scores: story, visual,       |
|        audio, continuity, pacing              |
|                                               |
|  2. Identify weak scenes (score < threshold)  |
|     -> scene-05: visual=3.2, pacing=3.5       |
|     -> scene-12: story=3.8, visual=3.0        |
|                                               |
|  3. Targeted improvement (editor agent)       |
|     -> Rewrite scene-05's visual prompt       |
|     -> Rewrite scene-12's narrative           |
|                                               |
|  4. Regenerate only changed scenes            |
|     -> scene-05: new images (1 cached, 1 new) |
|     -> scene-12: new images + TTS             |
|                                               |
|  5. Re-rate improved scenes                   |
|     -> scene-05: 3.2 -> 4.1 (pass)           |
|     -> scene-12: 3.0 -> 4.3 (pass)           |
|                                               |
|  6. Repeat until all scenes >= threshold      |
|     or max rounds reached                     |
+----------------------------------------------+
```

### 2.9 CLI Interface

```bash
# Create a new story
story-engine create "A warrior queen reforges her crown" \
    --scenes 20 --style "fantasy painterly" --voice Dean

# Check status
story-engine status crown-of-steel
# crown-of-steel: 20 scenes | 18/20 images | 20/20 tts | critic: pending

# Generate full story (pipeline)
story-engine generate crown-of-steel --parallel

# Edit a specific scene
story-engine scene edit crown-of-steel scene-05 \
    --set-narration="New narration text..." \
    --set-image-prompt 0="New prompt..."

# Regenerate specific scene
story-engine scene regen crown-of-steel scene-05 --steps images,tts

# Extend story
story-engine extend crown-of-steel --add 5 --target 25

# Run critic
story-engine critic crown-of-steel

# Improve weak scenes
story-engine improve crown-of-steel --threshold 4.0 --max-rounds 3

# Render final video
story-engine render crown-of-steel --output final.mp4

# List all stories
story-engine list
```

### 2.10 Migration Path from Fantasee

1. **Import existing stories:** Convert outputs/<id>/<id>.json manifests to new scene-based format
2. **Asset migration:** Move existing images/TTS into content-addressed cache
3. **Keep the viewer:** Netflix-style viewer continues to work via new storage API
4. **Deprecate batch_pipeline.py:** Replaced by improvement.py with proper incremental processing

---

## Part 3: Why This Is the Right Approach

### 3.1 vs Fantasee (Current)

| Aspect                | Fantasee              | New Engine                     |
|-----------------------|-----------------------|--------------------------------|
| Edit one scene        | Regenerate everything | Only changed assets            |
| Rollback              | Not possible          | Version history per scene      |
| Reuse assets          | No                    | Content-addressed cache        |
| Pipeline failure      | Start over            | Resume from checkpoint         |
| Quality improvement   | Shallow (3 rounds)    | Deep (per-scene targeting)     |
| Code duplication      | 5 files for LLM calls | Single LLM client              |

### 3.2 vs Mindstream (Current)

| Aspect           | Mindstream            | New Engine                     |
|------------------|-----------------------|--------------------------------|
| Architecture     | 20+ agents, complex   | 8 focused agents               |
| Storage          | JSON blob in SQLite   | Separate scene files           |
| Story model      | Course table (hack)   | Native story model             |
| Complexity       | LangChain + SQLAlchemy| Pure Python + FastAPI           |
| Dependencies     | LangChain, SQLAlchemy | FastAPI, Pillow, requests       |

### 3.3 The "Edit Small Parts" Guarantee

The content-addressed cache is the key. When you edit scene 5:
- Scene 5's image prompt changes -> 1 new image generated
- Scene 5's TTS text unchanged -> 0 new audio files
- Scenes 1-4, 6-20 unchanged -> 0 work done
- Total time: ~81s (1 image) vs ~2500s (full 20-scene regen)

The cache means even regenerated assets are deduplicated. If scene 5's new prompt
happens to match scene 12's existing prompt, the cached image is reused instantly.

### 3.4 ComfyUI Integration

```python
class ComfyUIGenerator:
    def generate(self, prompt, negative, model, seed, width, height):
        cache_key = cache.get_image_key(prompt, seed, model, width, height, negative)
        if cache.has(cache_key):
            return cache.link(cache_key, output_path)
        filename = comfyui_submit(prompt, negative, model, seed, width, height)
        cached_path = cache.store(cache_key, filename)
        return cache.link(cache_key, output_path)
```

### 3.5 MiMo TTS Integration

```python
class MiMoTTS:
    def generate(self, text, voice="Dean", style="dramatic", rate="-3%"):
        cache_key = cache.get_audio_key(text, voice, style, rate)
        if cache.has(cache_key):
            return cache.link(cache_key, output_path)
        audio_data = mimo_tts_api(text, voice, style)
        cached_path = cache.store(cache_key, audio_data)
        return cache.link(cache_key, output_path)
```

---

## Part 4: Implementation Roadmap

### Phase 1: Core Engine (Week 1)
- engine/core/ -- config, LLM client, storage, cache, models
- engine/generators/ -- ComfyUI, MiMo TTS, Whisper wrappers
- engine/pipeline/scene_processor.py -- Per-scene pipeline
- cli.py -- Basic create/edit/regen commands

### Phase 2: Agents (Week 2)
- engine/agents/outline.py -- Story outline (from Mindstream's outline agent)
- engine/agents/bible.py -- Character bible (from Mindstream)
- engine/agents/visual.py -- Visual prompt engineering
- engine/agents/editor.py -- Continuity checking
- engine/agents/critic.py -- Quality rating

### Phase 3: Pipeline (Week 3)
- engine/pipeline/orchestrator.py -- Full story pipeline
- engine/pipeline/incremental.py -- Diff-based regeneration
- engine/pipeline/improvement.py -- Quality improvement loop
- cli.py -- generate, extend, improve, render commands

### Phase 4: API and Viewer (Week 4)
- engine/api/server.py -- FastAPI server
- engine/api/routes_scene.py -- Scene edit/regen API
- Viewer UI migration from Fantasee

### Phase 5: Migration (Week 5)
- Import existing Fantasee stories
- Asset cache population
- Deprecate old Fantasee/Mindstream code

---

## Appendix A: Environment Variables

```bash
# LLM
XIAOMI_API_KEY=...
XIAOMI_BASE_URL=https://token-plan-sgp.xiaomimimo.com/v1
XIAOMI_MODEL=mimo-v2.5-pro

# ComfyUI
COMFYUI_URL=http://127.0.0.1:8188

# TTS (same Xiaomi API)
TTS_PROVIDER=xiaomi
TTS_VOICE=Dean
TTS_STYLE=dramatic

# Storage
STORY_DATA_DIR=./data/stories
STORY_CACHE_DIR=./data/cache
```

## Appendix B: API Endpoints

```
POST   /api/stories                    - Create story
GET    /api/stories                    - List stories
GET    /api/stories/{id}               - Get story details
DELETE /api/stories/{id}               - Delete story

GET    /api/stories/{id}/scenes        - List scenes
GET    /api/stories/{id}/scenes/{n}    - Get scene details
PUT    /api/stories/{id}/scenes/{n}    - Edit scene
POST   /api/stories/{id}/scenes/{n}/regen - Regenerate scene

POST   /api/stories/{id}/generate      - Start full pipeline
POST   /api/stories/{id}/extend        - Add scenes
POST   /api/stories/{id}/critic        - Run quality review
POST   /api/stories/{id}/improve       - Run improvement loop
POST   /api/stories/{id}/render        - Render final video

GET    /api/stories/{id}/assets/{hash} - Serve cached asset
GET    /api/stories/{id}/status        - Pipeline status
```

## Appendix C: Scene Dependency Graph

```
Scene 1 -> Scene 2 -> Scene 3 -> ... -> Scene 20
   |           |           |
   v           v           v
Character   Character   Character
  State       State       State
   |           |           |
   v           v           v
 Image 1     Image 2     Image 3
 Audio 1     Audio 2     Audio 3
 Subs 1      Subs 2      Subs 3
```

Each scene depends on:
- Previous scene (narrative continuity)
- Character bible (consistent appearances)
- World rules (consistent setting)

A scene edit cascades to:
- Next scene (if narrative changed)
- Same scene's images (if prompt changed)
- Same scene's audio (if narration text changed)

It does NOT cascade to:
- Unrelated scenes (visual changes are scene-local)
- Cached assets (same inputs = same outputs)
