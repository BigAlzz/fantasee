# Fantasee Rebuild Todo

This is the living checklist for the Fantasee Studio rebuild.
Update the checkboxes as work lands so progress stays visible.

## Core Architecture Gaps

- [x] Add CI, deterministic fixture factories, and opt-in media/hardware test markers.
- [ ] Complete database migrations and domain tables for stories, scenes, revisions, dependencies, and assets.
- [ ] Formalize adapter interfaces and fake adapters for LLM, ComfyUI, TTS, subtitles, FFmpeg, and Plex.
- [ ] Complete revision comparison, rollback, text/voice/image/timeline locks, and alternate branches.
- [ ] Finish worker heartbeat, circuit-breaker, concurrency, logging, and hardware smoke coverage.
- [ ] Complete audio performance direction, pronunciation handling, loudness validation, and FFprobe release checks.

## Creative and Release Pipeline

- [ ] Add remix controls for tone, pace, intimacy, humor, and strangeness before generation begins.
- [ ] Add multiple release editions: short, cinematic, audiobook, trailer, and Plex.
- [ ] Add automatic trailers, posters, thumbnails, and credits for each applicable release edition.

## Studio Gaps

- [ ] Complete release rollback UI, beyond current shot-plan history and archived preview.
- [ ] Add true mood-board and reference-image management.
- [ ] Unify notifications and task/progress presentation.
- [ ] Add committed Playwright journeys, refresh/recovery tests, and parity acceptance.
- [ ] Remove the legacy UI only after parity approval.

## Migration Completion

- [ ] Run dry-run migration across every story.
- [ ] Back up and migrate pilot stories.
- [ ] Verify migrated playback and releases.
- [ ] Migrate the remaining library resumably.
- [ ] Establish the read-only legacy compatibility window.
- [ ] Remove legacy write paths, task dictionaries, orchestration, and frontend.
- [ ] Archive obsolete scripts and publish release documentation.
- [ ] Tag the first production-ready Studio release.

## Final Acceptance Gates

- [ ] Every story has migration evidence or an explicit exception.
- [ ] Rollback has been exercised.
- [ ] No production request reaches a legacy write path.
- [ ] Critical Playwright journeys pass.
- [ ] User approves feature parity and visual direction.
- [ ] Final pull request merges the rebuild into main.

## Notes

- Keep this checklist in sync with `docs/FANTASEE_REBUILD_PLAN.md`.
- If an item changes scope, update the checkbox text instead of burying the change in comments.
