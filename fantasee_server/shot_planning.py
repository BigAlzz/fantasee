"""Deterministic semantic-shot planning contracts.

The Director can later replace the descriptive fields with a structured LLM
response. This seam intentionally owns density and validation so one scene's
visual plan is inspectable and independently revisable.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class ShotSpec:
    id: str
    scene_id: str
    order: int
    purpose: str
    shot_type: str
    duration_seconds: float
    visual_context: str


@dataclass(frozen=True)
class ShotPlanValidation:
    valid: bool
    codes: tuple[str, ...]


_PURPOSES = (
    ("establish", "wide"),
    ("track the decisive action", "medium"),
    ("reveal the consequential detail", "close"),
    ("show the response", "over-shoulder"),
    ("carry the transition", "wide"),
    ("leave a visual question", "detail"),
)

_SECONDS_PER_SHOT = {
    "urgent": 4.5,
    "brisk": 5.5,
    "balanced": 6.5,
    "quiet": 8.0,
}


def plan_semantic_shots(
    *,
    scene_id: str,
    narration: str,
    visual_direction: str,
    pacing: str = "balanced",
) -> list[ShotSpec]:
    """Plan two to six distinct visual beats without generating any media."""
    words = len(narration.split())
    duration = max(4.0, words / 2.5)  # Conservative narration rate in seconds.
    seconds_per_shot = _SECONDS_PER_SHOT.get(pacing.lower(), _SECONDS_PER_SHOT["balanced"])
    count = max(2, min(6, ceil(duration / seconds_per_shot)))
    shot_duration = round(duration / count, 2)
    context = visual_direction.strip()

    return [
        ShotSpec(
            id=f"{scene_id}-shot-{order:02d}",
            scene_id=scene_id,
            order=order,
            purpose=f"{purpose} ({order})",
            shot_type=shot_type,
            duration_seconds=shot_duration,
            visual_context=context,
        )
        for order, (purpose, shot_type) in enumerate(_PURPOSES[:count], start=1)
    ]


def validate_shot_plan(shots: list[ShotSpec]) -> ShotPlanValidation:
    """Reject plans that cannot reliably drive distinct image commissions."""
    codes: list[str] = []
    if not shots:
        codes.append("empty_plan")
    if [shot.order for shot in shots] != list(range(1, len(shots) + 1)):
        codes.append("invalid_order")
    purposes = [shot.purpose.strip().lower() for shot in shots]
    if len(purposes) != len(set(purposes)):
        codes.append("duplicate_purpose")
    if any(not shot.visual_context.strip() for shot in shots):
        codes.append("missing_visual_context")
    if any(shot.duration_seconds <= 0 for shot in shots):
        codes.append("invalid_duration")
    return ShotPlanValidation(valid=not codes, codes=tuple(codes))
