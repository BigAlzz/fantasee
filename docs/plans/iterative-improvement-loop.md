# Fantasee Iterative Improvement Loop — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add scene-level regeneration, image addition, prompt refinement, re-rendering, and a full auto-improve loop to Fantasee, with UI controls.

**Architecture:** Server-side API endpoints in `server.py` that operate on individual scenes within existing story manifests. Each endpoint reads the manifest, performs the operation (ComfyUI generation, TTS, LLM refinement), updates the manifest, and returns the result. UI buttons in `index.html` wire into these endpoints with progress feedback via the existing WebSocket.

**Tech Stack:** Python/FastAPI (server.py), vanilla JS (index.html), ComfyUI (image gen), MiMo TTS (audio), edge-tts (fallback), Whisper (subtitles), ffmpeg (video render)

---

## Task 1: Scene Regeneration Endpoint

**Objective:** Add `POST /api/stories/{id}/scenes/{idx}/regenerate` — regenerate images + TTS for a single scene.

**Files:**
- Modify: `C:/dev/fantasee/server.py` (add endpoint after line ~832)

**Implementation:**

Add endpoint that:
1. Reads story manifest from `outputs/{id}/{id}.json`
2. Gets the scene at index `idx`
3. Calls `comfyui_utils.generate_image()` to create new image(s)
4. Calls `tts_utils.generate_tts()` to regenerate audio
5. Calls Whisper for new subtitles
6. Updates the manifest JSON
7. Returns the updated scene data

```python
@app.post("/api/stories/{story_id}/scenes/{scene_idx}/regenerate")
async def regenerate_scene(story_id: str, scene_idx: int):
    """Regenerate images and TTS for a single scene."""
    story_dir = OUTPUTS_DIR / story_id
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")
    
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")
    
    scene = scenes[scene_idx]
    scene_num = scene_idx + 1
    padded = f"{scene_num:02d}"
    safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", "")).strip("_")[:30]
    
    # Delete old images
    for old_img in scene.get("image_filenames", []):
        old_path = story_dir / old_img
        if old_path.exists():
            old_path.unlink()
    
    # Generate new image
    from comfyui_utils import generate_image, is_running
    status = is_running()
    if status.get("running", False):
        seed = hash(story_id + str(scene_num)) % (2**32 - 1)
        prefix = f"{story_id}_s{padded}_{safe_title}_01"
        filename = generate_image(
            prompt=scene["prompt"],
            output_prefix=prefix,
            output_dir=str(story_dir),
            seed=seed,
            timeout=600,
        )
        if filename:
            scene["image_filenames"] = [filename]
    
    # Regenerate TTS
    from tts_utils import generate_tts, get_audio_duration
    narration = scene.get("narration", scene.get("narration_text", ""))
    if narration:
        # Delete old audio
        old_audio = scene.get("audio_filename", "")
        if old_audio:
            old_path = story_dir / old_audio
            if old_path.exists():
                old_path.unlink()
        
        audio_filename = f"tts_{story_id}_s{padded}.wav"
        audio_path = str(story_dir / audio_filename)
        ok = generate_tts(narration, audio_path, voice_preset="dramatic_male")
        if ok:
            scene["audio_filename"] = audio_filename
            scene["audio_duration"] = get_audio_duration(audio_path)
    
    # Update manifest
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    
    return {"status": "ok", "scene": scene}
```

**Verification:**
```bash
curl -X POST http://127.0.0.1:8765/api/stories/the-emerald-s-fading-cure/scenes/0/regenerate | python -m json.tool
```
Expected: returns updated scene with new image_filenames and audio_filename.

---

## Task 2: Add Image Endpoint

**Objective:** Add `POST /api/stories/{id}/scenes/{idx}/add-image` — add an additional image beat to a scene (increases visual density).

**Files:**
- Modify: `C:/dev/fantasee/server.py`

**Implementation:**

```python
@app.post("/api/stories/{story_id}/scenes/{scene_idx}/add-image")
async def add_scene_image(story_id: str, scene_idx: int):
    """Add an additional image to a scene for more visual variety."""
    story_dir = OUTPUTS_DIR / story_id
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")
    
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")
    
    scene = scenes[scene_idx]
    scene_num = scene_idx + 1
    padded = f"{scene_num:02d}"
    safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", "")).strip("_")[:30]
    
    from comfyui_utils import generate_image, is_running
    status = is_running()
    if not status.get("running", False):
        raise HTTPException(status_code=503, detail="ComfyUI not running")
    
    existing = len(scene.get("image_filenames", []))
    seed = hash(story_id + str(scene_num) + str(existing)) % (2**32 - 1)
    prefix = f"{story_id}_s{padded}_{safe_title}_{existing + 1:02d}"
    
    filename = generate_image(
        prompt=scene["prompt"],
        output_prefix=prefix,
        output_dir=str(story_dir),
        seed=seed,
        timeout=600,
    )
    
    if filename:
        scene.setdefault("image_filenames", []).append(filename)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {"status": "ok", "filename": filename, "total_images": len(scene["image_filenames"])}
    
    raise HTTPException(status_code=500, detail="Image generation failed")
```

**Verification:**
```bash
curl -X POST http://127.0.0.1:8765/api/stories/the-emerald-s-fading-cure/scenes/0/add-image | python -m json.tool
```
Expected: returns new filename and incremented total_images count.

---

## Task 3: Prompt Refinement Endpoint

**Objective:** Add `POST /api/stories/{id}/scenes/{idx}/refine-prompt` — use LLM to improve a scene's visual prompt based on critic feedback or manual instruction.

**Files:**
- Modify: `C:/dev/fantasee/server.py`

**Implementation:**

```python
@app.post("/api/stories/{story_id}/scenes/{scene_idx}/refine-prompt")
async def refine_prompt(story_id: str, scene_idx: int, body: dict = None):
    """Use LLM to improve a scene's visual prompt."""
    story_dir = OUTPUTS_DIR / story_id
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")
    
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")
    
    scene = scenes[scene_idx]
    instruction = (body or {}).get("instruction", "")
    
    # Build refinement prompt
    system = """You are an expert at writing image generation prompts. 
Improve the given prompt to be more detailed, vivid, and visually specific.
Keep the same scene and characters. Output ONLY the improved prompt, nothing else.
80-150 words, natural language prose, not tag lists."""
    
    user_prompt = f"Improve this image generation prompt:\n\n{scene['prompt']}"
    if instruction:
        user_prompt += f"\n\nSpecific direction: {instruction}"
    
    # Call LLM
    api_key = _resolve_env_var("XIAOMI_API_KEY")
    base_url = _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
    
    resp = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": "mimo-v2.5-pro",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 512,
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=120,
    )
    resp.raise_for_status()
    new_prompt = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
    
    old_prompt = scene["prompt"]
    scene["prompt"] = new_prompt
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    
    return {"status": "ok", "old_prompt": old_prompt, "new_prompt": new_prompt}
```

**Verification:**
```bash
curl -X POST http://127.0.0.1:8765/api/stories/the-emerald-s-fading-cure/scenes/0/refine-prompt \
  -H "Content-Type: application/json" \
  -d '{"instruction": "make it more dramatic and cinematic"}' | python -m json.tool
```
Expected: returns old_prompt and new_prompt.

---

## Task 4: Video Re-render Endpoint

**Objective:** Add `POST /api/stories/{id}/render` — re-render video for specific scenes or the full story.

**Files:**
- Modify: `C:/dev/fantasee/server.py`

**Implementation:**

```python
@app.post("/api/stories/{story_id}/render")
async def render_story(story_id: str, body: dict = None):
    """Re-render video. Pass scene_idx for single scene, or omit for full story."""
    story_dir = OUTPUTS_DIR / story_id
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")
    
    scene_idx = (body or {}).get("scene_idx")  # None = full story
    
    cmd = [sys.executable, str(Path(__file__).parent / "render_video.py"), story_id]
    if scene_idx is not None:
        cmd += ["--scene-only", str(scene_idx + 1)]
    
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          cwd=str(Path(__file__).parent))
    
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Render failed: {proc.stderr[:500]}")
    
    return {"status": "ok", "message": "Render complete", "scene_idx": scene_idx}
```

**Verification:**
```bash
curl -X POST http://127.0.0.1:8765/api/stories/the-emerald-s-fading-cure/render \
  -H "Content-Type: application/json" -d '{"scene_idx": 0}'
```
Expected: `{"status": "ok", "message": "Render complete", "scene_idx": 0}`

---

## Task 5: Auto-Improve Loop Endpoint

**Objective:** Add `POST /api/stories/{id}/improve` — run critic, identify weakest scenes, refine prompts, regenerate images, re-render.

**Files:**
- Modify: `C:/dev/fantasee/server.py`

**Implementation:**

```python
@app.post("/api/stories/{story_id}/improve")
async def auto_improve(story_id: str, body: dict = None):
    """Auto-improve: critic → identify weak scenes → refine → regenerate → re-render."""
    story_dir = OUTPUTS_DIR / story_id
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Story not found")
    
    max_scenes = (body or {}).get("max_scenes", 3)  # improve up to N weakest scenes
    
    # Step 1: Run critic
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "critic.py"), story_id, "--json"],
        capture_output=True, text=True, timeout=180,
        cwd=str(Path(__file__).parent),
        env={**os.environ, "XIAOMI_API_KEY": _resolve_env_var("XIAOMI_API_KEY"),
             "XIAOMI_BASE_URL": _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")},
    )
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Critic failed: {proc.stderr[:300]}")
    
    stdout = proc.stdout.strip()
    json_end = stdout.rfind("}")
    if json_end >= 0:
        stdout = stdout[:json_end + 1]
    review = json.loads(stdout)
    
    # Step 2: Identify weak scenes (from critic needs_work or low scores)
    needs_work = review.get("review", {}).get("needs_work", [])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    
    # For now, improve scenes that have few images or weak prompts
    targets = []
    for i, scene in enumerate(scenes):
        img_count = len(scene.get("image_filenames", []))
        prompt_len = len(scene.get("prompt", "").split())
        score = img_count * 2 + prompt_len / 10  # rough quality heuristic
        targets.append((i, score))
    
    targets.sort(key=lambda x: x[1])  # weakest first
    targets = targets[:max_scenes]
    
    improved = []
    for idx, score in targets:
        scene = scenes[idx]
        
        # Refine prompt
        # (inline LLM call — same as Task 3)
        api_key = _resolve_env_var("XIAOMI_API_KEY")
        base_url = _resolve_env_var("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
        
        resp = requests.post(
            f"{base_url}/chat/completions",
            json={
                "model": "mimo-v2.5-pro",
                "messages": [
                    {"role": "system", "content": "Improve this image generation prompt. Be more vivid and detailed. Output ONLY the improved prompt. 80-150 words."},
                    {"role": "user", "content": scene["prompt"]},
                ],
                "temperature": 0.7,
                "max_tokens": 512,
            },
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=120,
        )
        if resp.ok:
            scene["prompt"] = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
        
        # Regenerate image
        from comfyui_utils import generate_image, is_running
        if is_running().get("running", False):
            # Delete old images
            for old_img in scene.get("image_filenames", []):
                old_path = story_dir / old_img
                if old_path.exists():
                    old_path.unlink()
            
            scene_num = idx + 1
            padded = f"{scene_num:02d}"
            safe_title = re.sub(r'[^a-zA-Z0-9]+', '_', scene.get("title", "")).strip("_")[:30]
            seed = hash(story_id + str(scene_num)) % (2**32 - 1)
            prefix = f"{story_id}_s{padded}_{safe_title}_01"
            filename = generate_image(
                prompt=scene["prompt"],
                output_prefix=prefix,
                output_dir=str(story_dir),
                seed=seed,
                timeout=600,
            )
            if filename:
                scene["image_filenames"] = [filename]
        
        improved.append({"scene_idx": idx, "title": scene.get("title", "")})
    
    # Update manifest
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    
    # Step 3: Re-render full story
    render_proc = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "render_video.py"), story_id],
        capture_output=True, text=True, timeout=600,
        cwd=str(Path(__file__).parent),
    )
    
    return {
        "status": "ok",
        "review_stars": review.get("review", {}).get("stars", 0),
        "improved_scenes": improved,
        "render_ok": render_proc.returncode == 0,
    }
```

**Verification:**
```bash
curl -X POST http://127.0.0.1:8765/api/stories/the-emerald-s-fading-cure/improve \
  -H "Content-Type: application/json" -d '{"max_scenes": 2}'
```
Expected: returns list of improved scenes and render status.

---

## Task 6: UI — Per-Scene Action Buttons

**Objective:** Add action buttons to each scene card in the story detail view: Regenerate, Add Image, Refine Prompt.

**Files:**
- Modify: `C:/dev/fantasee/static/index.html` (scene card HTML + CSS + JS functions)

**Implementation:**

Add CSS for scene action buttons:
```css
.scene-actions {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  opacity: 0;
  transition: opacity 0.2s;
}
.scene-card:hover .scene-actions {
  opacity: 1;
}
.scene-action-btn {
  background: rgba(255,255,255,0.1);
  border: 1px solid rgba(255,255,255,0.2);
  color: #fff;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.2s;
}
.scene-action-btn:hover {
  background: rgba(255,255,255,0.25);
}
.scene-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

Update scene card HTML to include action buttons:
```javascript
// In the scene card template, after scene-card-info:
<div class="scene-actions">
  <button class="scene-action-btn" onclick="event.stopPropagation(); regenerateScene('${story.id}', ${i}, this)">
    🔄 Regenerate
  </button>
  <button class="scene-action-btn" onclick="event.stopPropagation(); addSceneImage('${story.id}', ${i}, this)">
    ➕ Image
  </button>
  <button class="scene-action-btn" onclick="event.stopPropagation(); refineScenePrompt('${story.id}', ${i}, this)">
    ✨ Refine
  </button>
</div>
```

Add JS functions:
```javascript
async function regenerateScene(storyId, idx, btn) {
  btn.disabled = true;
  btn.textContent = '⏳ Working...';
  try {
    const res = await fetch(`/api/stories/${storyId}/scenes/${idx}/regenerate`, { method: 'POST' });
    if (res.ok) {
      btn.textContent = '✅ Done';
      setTimeout(() => { btn.textContent = '🔄 Regenerate'; btn.disabled = false; }, 2000);
      showDetail(storyId);  // refresh
    } else {
      btn.textContent = '❌ Failed';
      setTimeout(() => { btn.textContent = '🔄 Regenerate'; btn.disabled = false; }, 3000);
    }
  } catch(e) {
    btn.textContent = '❌ Error';
    setTimeout(() => { btn.textContent = '🔄 Regenerate'; btn.disabled = false; }, 3000);
  }
}

async function addSceneImage(storyId, idx, btn) {
  btn.disabled = true;
  btn.textContent = '⏳ Adding...';
  try {
    const res = await fetch(`/api/stories/${storyId}/scenes/${idx}/add-image`, { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      btn.textContent = `✅ ${data.total_images} images`;
      setTimeout(() => { btn.textContent = '➕ Image'; btn.disabled = false; }, 2000);
      showDetail(storyId);
    } else {
      btn.textContent = '❌ Failed';
      setTimeout(() => { btn.textContent = '➕ Image'; btn.disabled = false; }, 3000);
    }
  } catch(e) {
    btn.textContent = '❌ Error';
    setTimeout(() => { btn.textContent = '➕ Image'; btn.disabled = false; }, 3000);
  }
}

async function refineScenePrompt(storyId, idx, btn) {
  const instruction = prompt('Refinement direction (optional):');
  btn.disabled = true;
  btn.textContent = '⏳ Refining...';
  try {
    const body = instruction ? { instruction } : {};
    const res = await fetch(`/api/stories/${storyId}/scenes/${idx}/refine-prompt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      btn.textContent = '✅ Refined';
      setTimeout(() => { btn.textContent = '✨ Refine'; btn.disabled = false; }, 2000);
      showDetail(storyId);
    } else {
      btn.textContent = '❌ Failed';
      setTimeout(() => { btn.textContent = '✨ Refine'; btn.disabled = false; }, 3000);
    }
  } catch(e) {
    btn.textContent = '❌ Error';
    setTimeout(() => { btn.textContent = '✨ Refine'; btn.disabled = false; }, 3000);
  }
}
```

**Verification:** Open http://127.0.0.1:8765, click a story, hover over scene cards — action buttons appear. Click each to test.

---

## Task 7: UI — Story-Level Improve Button + Render Button

**Objective:** Add "✨ Improve Story" and "🎬 Re-render" buttons to the story detail actions bar.

**Files:**
- Modify: `C:/dev/fantasee/static/index.html`

**Implementation:**

Add buttons to the detail-actions div (after Run Critic):
```javascript
// After the Run Critic button in detail-actions:
<button class="btn-secondary" id="btn-improve" onclick="improveStory('${story.id}')">
  ✨ Improve Story
</button>
<button class="btn-secondary" id="btn-render" onclick="renderStory('${story.id}')">
  🎬 Re-render
</button>
```

Add JS functions:
```javascript
async function improveStory(storyId) {
  const btn = document.getElementById('btn-improve');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Improving...';
  }
  try {
    const res = await fetch(`/api/stories/${storyId}/improve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ max_scenes: 3 }),
    });
    if (res.ok) {
      const data = await res.json();
      alert(`Improved ${data.improved_scenes.length} scenes. Render: ${data.render_ok ? '✓' : '✗'}`);
      showDetail(storyId);
    } else {
      const err = await res.json();
      alert(`Improve failed: ${err.detail}`);
    }
  } catch(e) {
    alert(`Error: ${e.message}`);
  }
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '✨ Improve Story';
  }
}

async function renderStory(storyId) {
  const btn = document.getElementById('btn-render');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Rendering...';
  }
  try {
    const res = await fetch(`/api/stories/${storyId}/render`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (res.ok) {
      alert('Render complete!');
    } else {
      const err = await res.json();
      alert(`Render failed: ${err.detail}`);
    }
  } catch(e) {
    alert(`Error: ${e.message}`);
  }
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '🎬 Re-render';
  }
}
```

**Verification:** Open story detail — "Improve Story" and "Re-render" buttons visible in action bar. Click Improve → scenes get refined prompts + new images → video re-rendered.

---

## Task 8: Restart Server & End-to-End Test

**Objective:** Kill old server, restart, verify all endpoints work.

**Files:**
- None (verification only)

**Steps:**
1. Kill old server process
2. Restart: `python server.py`
3. Test each endpoint with curl
4. Open browser and verify UI buttons work

```bash
# Test scene regeneration
curl -s -X POST http://127.0.0.1:8765/api/stories/the-emerald-s-fading-cure/scenes/0/regenerate | python -m json.tool

# Test add image
curl -s -X POST http://127.0.0.1:8765/api/stories/the-emerald-s-fading-cure/scenes/0/add-image | python -m json.tool

# Test prompt refinement
curl -s -X POST http://127.0.0.1:8765/api/stories/the-emerald-s-fading-cure/scenes/0/refine-prompt \
  -H "Content-Type: application/json" -d '{"instruction": "more dramatic lighting"}' | python -m json.tool

# Test render
curl -s -X POST http://127.0.0.1:8765/api/stories/the-emerald-s-fading-cure/render \
  -H "Content-Type: application/json" -d '{"scene_idx": 0}' | python -m json.tool
```

**Expected:** All return `{"status": "ok", ...}`. UI shows buttons, clicking them triggers operations, results visible in viewer.
