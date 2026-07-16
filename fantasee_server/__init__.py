"""Fantasee FastAPI server (modularized backend).

This package contains the split-out implementation of the original
``server.py`` monolith. ``server.py`` at the repo root remains the
entry point and re-exports the names tests and CLI tools expect, but
the actual route handlers, helpers, and worker functions now live in
focused submodules:

* ``state``    — process-wide globals, env resolver, WebSocket broadcast helpers.
* ``models``   — Pydantic request/response models.
* ``paths``    — path safety + generated-asset resolution.
* ``discovery``— story manifest discovery + URL enrichment.
* ``seed``     — seed-suggestion parser (LLM response → list[dict]).
* ``library``  — library maintenance queue + per-story completion worker.
* ``improver`` — iterative improvement loop + auto-improve worker.
* ``background`` — generic background-task runner + delete worker.
* ``startup``  — lifespan helpers (worker auto-spawn, library agent).
* ``api.*``    — FastAPI ``APIRouter`` modules grouped by endpoint family.
"""
