"""Pydantic request/response models for the Fantasee API.

All models that used to be declared next to their FastAPI route
handler now live here so the ``api/`` modules can import them
without circular dependencies.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    story_concept: str
    style: str = "fantasy painterly"
    num_scenes: int = 5
    images_per_scene: int = 5
    characters: str = ""
    tone: str = "dramatic"
    voice_preset: str = "Dean"
    narration_style: str = ""  # optional: name of a style file in skills/
    world_context: str = ""
    voice_assignments: str = ""


class SeedRequest(BaseModel):
    concept: str
    count: int = 3
    style: str = "fantasy painterly"
    tone: str = "dramatic"
    characters: str = ""


class QueueRequest(BaseModel):
    items: list[GenerateRequest]


class TTSRequest(BaseModel):
    text: str
    voice_preset: str = "Dean"
    output_name: Optional[str] = None
    model: Literal["preset", "design", "clone"] = "preset"
    style: str = ""
    voice_description: str = ""
    voice_sample: Optional[str] = None
    optimize_text_preview: bool = True
    stream: bool = False
    tone: str = ""
    speed: Optional[float] = None


class PlexExportRequest(BaseModel):
    background_volume: Optional[float] = None
    background_muted: Optional[bool] = None
    background_audio: Optional[str] = None
    # Optional override of the Plex library root. Defaults to
    # FANTASEE_PLEX_DEST env var, then D:\Downloads\Plex. The exporter
    # creates <root>/Movies/<Title> (<Year>)/ and copies the package
    # into it so a Plex library scan picks the story up automatically.
    destination: Optional[str] = None


class ExtendRequest(BaseModel):
    scenes: int = 5
    images_per_scene: Optional[int] = None
    voice: Optional[str] = None
    tone: Optional[str] = None


class RegenRequest(BaseModel):
    backup: bool = True
    dry_run: bool = False
    force: bool = False


class RepairRequest(BaseModel):
    dry_run: bool = False
