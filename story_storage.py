"""Storage paths for Fantasee stories.

New generated stories live in ``stories/<story-id>/``. The old ``outputs/``
folder remains readable as a legacy source while existing content is migrated.
"""

from pathlib import Path


ROOT = Path(__file__).parent
STORIES_ROOT = ROOT / "stories"
LEGACY_OUTPUTS_ROOT = ROOT / "outputs"


def ensure_story_layout(story_dir: Path) -> dict[str, Path]:
    """Create the standard subfolders for a story and return them."""
    paths = {
        "root": story_dir,
        "working": story_dir / "working",
        "drafts": story_dir / "working" / "drafts",
        "prompts": story_dir / "working" / "prompts",
        "workflows": story_dir / "working" / "workflows",
        "critic": story_dir / "working" / "critic",
        "logs": story_dir / "working" / "logs",
        "assets": story_dir / "assets",
        "title": story_dir / "assets" / "title",
        "final": story_dir / "final",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def story_dir(story_id: str, create: bool = False) -> Path:
    """Return the canonical directory for a story ID."""
    path = STORIES_ROOT / story_id
    if create:
        ensure_story_layout(path)
    return path


def existing_story_dir(story_id: str) -> Path:
    """Find a story in the canonical root, falling back to legacy outputs."""
    canonical = STORIES_ROOT / story_id
    if canonical.exists():
        return canonical
    legacy = LEGACY_OUTPUTS_ROOT / story_id
    if legacy.exists():
        return legacy
    return canonical

