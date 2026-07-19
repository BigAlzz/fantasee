"""World-builder creative asset endpoints."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from fantasee_server.paths import GEN_OUTPUTS, generated_story_dir, path_under
from fantasee_server.state import atomic_write_json


router = APIRouter(tags=["world"])


def _safe_slug(value: str, fallback: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-") or fallback


def _portrait_job(character: dict, world_context: str, output_dir: Path) -> dict:
    character_id = str(character.get("character_id", "")).strip()
    name = str(character.get("name", "")).strip()
    description = str(character.get("description", "")).strip()
    appearance = str(character.get("appearance", "")).strip()
    alignment = str(character.get("alignment", "")).strip()
    traits = str(character.get("traits", "")).strip()
    biography = str(character.get("biography", "")).strip()
    prompt = (
        f"Character portrait concept art for {name}. Role: {character.get('role', 'story character')}. "
        f"Alignment: {alignment or 'undefined'}. Traits: {traits or 'distinctive and believable'}. "
        f"Appearance: {appearance or description or 'grounded, expressive, story-specific design'}. "
        f"Biography: {biography}. World context: {world_context}. "
        "Mini character sheet portrait, clear silhouette, expressive face, "
        "cinematic studio lighting, no title card, no text, no watermark."
    ).strip()
    return {
        "character_id": character_id,
        "prompt": prompt,
        "output_prefix": f"world_character_{_safe_slug(character_id, 'character')}",
        "seed": int(hashlib.sha256(f"{character_id}:{name}:{prompt}".encode("utf-8")).hexdigest()[:8], 16),
        "width": 256,
        "height": 320,
        "output_dir": str(output_dir),
    }


@router.post("/api/world/character-portrait")
def generate_character_portrait(body: dict = Body(default=None)):
    """Generate a deterministic character concept image for a world sheet."""
    payload = body or {}
    character_id = str(payload.get("character_id", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not character_id or not name:
        raise HTTPException(status_code=400, detail="character_id and name are required")
    if len(character_id) > 80 or len(name) > 120:
        raise HTTPException(status_code=400, detail="character identity is too long")

    # Keep provider-specific imports behind this endpoint so the route remains
    # cheap to import in the default test suite.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from comfyui_utils import generate_image, is_running
    if not is_running().get("running", False):
        raise HTTPException(status_code=503, detail="No healthy ComfyUI worker is available for story card art")

    safe_id = _safe_slug(character_id, "character")
    output_dir = path_under(GEN_OUTPUTS, "world", "characters")
    output_dir.mkdir(parents=True, exist_ok=True)
    description = str(payload.get("description", "")).strip()
    appearance = str(payload.get("appearance", "")).strip()
    alignment = str(payload.get("alignment", "")).strip()
    traits = str(payload.get("traits", "")).strip()
    biography = str(payload.get("biography", "")).strip()
    world_context = str(payload.get("world_context", "")).strip()
    prompt = (
        f"Character portrait concept art for {name}. "
        f"Role: {payload.get('role', 'story character')}. "
        f"Alignment: {alignment or 'undefined'}. Traits: {traits or 'distinctive and believable'}. "
        f"Appearance: {appearance or description or 'grounded, expressive, story-specific design'}. "
        f"Biography: {biography}. World context: {world_context}. "
        "Waist-up character sheet portrait, clear silhouette, expressive face, "
        "cinematic studio lighting, no title card, no text, no watermark."
    ).strip()
    seed = int(hashlib.sha256(f"{character_id}:{name}:{prompt}".encode("utf-8")).hexdigest()[:8], 16)
    filename = generate_image(
        prompt=prompt,
        output_prefix=f"world_character_{safe_id}",
        output_dir=str(output_dir),
        seed=seed,
        width=256,
        height=320,
        timeout=600,
    )
    if not filename:
        raise HTTPException(status_code=500, detail="Portrait generation did not return an asset")
    return {"filename": filename, "url": f"/generated-images/world/characters/{filename}"}


@router.post("/api/world/character-portraits")
def generate_character_portraits(body: dict = Body(default=None)):
    """Fan out small cast portraits across the healthy GPU worker pool."""
    payload = body or {}
    characters = payload.get("characters") or []
    if not isinstance(characters, list) or not characters or len(characters) > 24:
        raise HTTPException(status_code=400, detail="Provide between 1 and 24 characters")
    if any(not isinstance(character, dict) or not str(character.get("character_id", "")).strip() or not str(character.get("name", "")).strip() for character in characters):
        raise HTTPException(status_code=400, detail="Every character needs a character_id and name")

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from comfyui_utils import generate_images_parallel

    output_dir = path_under(GEN_OUTPUTS, "world", "characters")
    output_dir.mkdir(parents=True, exist_ok=True)
    world_context = str(payload.get("world_context", "")).strip()
    jobs = [_portrait_job(character, world_context, output_dir) for character in characters]
    try:
        filenames = generate_images_parallel(jobs, str(output_dir), timeout=600, max_workers=min(len(jobs), 4))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"The portrait worker pool could not start: {exc}") from exc
    portraits = []
    failed = []
    for character, filename in zip(characters, filenames):
        character_id = str(character["character_id"]).strip()
        if filename:
            portraits.append({"character_id": character_id, "filename": filename, "url": f"/generated-images/world/characters/{filename}"})
        else:
            failed.append(character_id)
    return {"portraits": portraits, "failed": failed}


@router.post("/api/world/stories/{story_id}/thumbnail")
def generate_story_thumbnail(story_id: str):
    """Generate a small card image without making it a production requirement."""
    story_dir = generated_story_dir(story_id)
    manifest_path = story_dir / f"{story_id}.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="Story manifest not found")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Story manifest is unreadable") from exc

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from comfyui_utils import generate_image
    title = str(manifest.get("title", story_id)).strip()
    context = " ".join(str(manifest.get(field, "")).strip() for field in ("description", "style", "tone") if manifest.get(field))
    prompt = (
        f"Story card artwork for {title}. {context} "
        "Cinematic establishing image, strong readable silhouette, rich atmosphere, "
        "story artwork only, no title card, no text, no logo, no watermark."
    ).strip()
    seed = int(hashlib.sha256(f"thumbnail:{story_id}:{prompt}".encode("utf-8")).hexdigest()[:8], 16)
    try:
        filename = generate_image(
            prompt=prompt,
            output_prefix=f"{_safe_slug(story_id, 'story')}_thumbnail",
            output_dir=str(story_dir),
            seed=seed,
            width=384,
            height=216,
            timeout=600,
            worker_kind="gpu",
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Story card art generation failed: {exc}") from exc
    if not filename:
        raise HTTPException(status_code=500, detail="Story thumbnail generation did not return an asset")
    manifest["story_thumbnail"] = filename
    manifest["story_thumbnail_provenance"] = {"provider": "comfyui", "width": 384, "height": 216, "seed": seed, "prompt": prompt}
    atomic_write_json(manifest_path, manifest)
    return {"filename": filename, "url": f"/generated/{story_id}/{filename}"}
