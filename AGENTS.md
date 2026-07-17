# Fantasee Engineering Contract

This file defines the operating rules for humans and coding agents rebuilding
Fantasee. It applies to the entire repository unless a more specific
`AGENTS.md` exists in a child directory.

## Product Mission

Fantasee is a local-first AI animation studio. It turns a creative intent into
a versioned, inspectable production containing story text, visual shots,
narration, synchronized subtitles, a canonical edit timeline, rendered video,
and a verified release such as a Plex package.

The product is not finished when generation returns successfully. A production
is finished only when every required artifact exists, passes validation, and is
derived from the current approved inputs.

## Non-Negotiable Invariants

1. **Truthful completion.** Never label a story, scene, shot, job, or release
   complete unless its completion contract passes.
2. **Durable work.** Queued and running work must survive a server restart.
   Process-local dictionaries are caches, never the source of truth.
3. **Incremental regeneration.** A changed input invalidates only its dependent
   outputs. Never regenerate an entire story when one shot is sufficient.
4. **Safe replacement.** Generate and validate replacement assets before
   removing the last valid asset.
5. **Idempotency.** Retrying the same job with the same fingerprint must not
   create conflicting state or duplicate releases.
6. **Explicit provenance.** Every generated asset records the provider, model,
   workflow, prompt or text fingerprint, seed, settings, and source revision.
7. **Atomic persistence.** Metadata writes use transactions. File writes use a
   temporary path followed by atomic replacement.
8. **One canonical timeline.** The player, subtitles, MP4 renderer, chapters,
   and Plex exporter consume the same approved timeline.
9. **No silent degradation.** Provider fallback, reduced image counts, altered
   quality, missing subtitles, and skipped stages must be visible to the user.
10. **Local-first security.** Bind to loopback by default, keep credentials out
    of the repository, validate provider URLs, and constrain filesystem paths.
11. **Backward compatibility during migration.** Existing story folders remain
    readable and restorable until migration is explicitly declared complete.
12. **User-owned creative decisions.** Agents may propose revisions. They do
    not overwrite locked or approved work without an explicit production rule.

## Domain Language

Use these names consistently in code, interfaces, tests, documentation, and UI:

- **Story**: The creative work and its production requirements.
- **Scene**: A narrative unit containing one or more timed shots.
- **Shot**: A specific visual beat with framing, action, timing, and artwork.
- **Asset**: An immutable generated or imported media object.
- **Revision**: A versioned change to story, scene, shot, narration, or timeline.
- **Production**: The desired state and all work needed to materialize a story.
- **Run**: One execution of a production command.
- **Job**: A durable, lease-based piece of executable work.
- **Worker**: A process with declared capabilities and resource properties.
- **Timeline**: The approved timing of shots, narration, subtitles, and audio.
- **Release**: A validated output edition such as draft MP4 or Plex package.
- **Completion contract**: Machine-checkable requirements for a desired state.

Avoid vague substitutes such as `item`, `thing`, `data`, `done`, or `agent task`
when one of the domain names above is accurate.

## Architecture Rules

### Deep Modules

Build deep modules: substantial behavior behind a small interface. The public
interface is also the primary test seam. Do not spread orchestration knowledge
across routes, scripts, UI handlers, and provider clients.

The planned top-level modules are:

- **Production Engine**: accepts commands, computes desired state, reconciles
  dependencies, and reports production status.
- **Production Store**: transactionally stores stories, revisions, jobs,
  events, workers, assets, timelines, and releases.
- **Scheduler**: leases jobs to compatible workers using capabilities,
  priority, health, and concurrency limits.
- **Asset Store**: stores immutable media by content or generation fingerprint
  and verifies file integrity.
- **Timeline Engine**: turns approved shots, narration, subtitles, and music
  into the canonical edit decision list.
- **Completion Verifier**: evaluates contracts and returns structured evidence.

Routes and UI code call these modules. They must not reproduce their rules.

### Adapter Seams

Create adapters only where behavior genuinely varies. Planned seams are:

- LLM provider
- Image generator, initially ComfyUI
- TTS provider
- Subtitle aligner
- Media renderer, initially FFmpeg
- Publisher, initially local package and Plex
- Production store
- Asset store

Adapters return typed results and typed failures. They do not mutate story
state directly. Provider-specific request and response details stay inside the
adapter implementation.

### Dependency Graph

Every derived output declares its inputs. At minimum:

- Story bible depends on concept and creative settings.
- Scene text depends on bible, outline, style rules, and prior scene context.
- Shot plan depends on scene text, visual direction, and target visual density.
- Image depends on shot prompt, references, model, workflow, seed, and settings.
- Narration audio depends on narration text, voice, performance, speed, and TTS
  model.
- Subtitles depend on the exact approved narration audio and narration text.
- Timeline depends on shots, approved images, narration audio, subtitles, and
  transition rules.
- Scene video depends on the canonical timeline slice and source media.
- Full video depends on every approved scene video and release settings.
- Plex package depends on the approved full video, chapters, subtitles, poster,
  metadata, and destination settings.

Changing an input marks all dependent outputs stale. Stale is not complete.

## Production Workflow

The target workflow is:

1. Capture creative intent.
2. Create or revise the story bible.
3. Produce a structured outline.
4. Write scenes using the canonical story style.
5. Plan semantically distinct timed shots.
6. Produce and validate shot artwork.
7. Direct and synthesize narration performances.
8. Align subtitles to the approved narration audio.
9. Build and validate the canonical timeline.
10. Render scene and full-story editions.
11. Package and publish releases.
12. Run final completion verification.

Stages may run concurrently only when their declared dependencies permit it.

## Creative Agents

Use a small number of deep creative agents:

- **Writer**: bible, outline, scenes, dialogue, continuity, and story style.
- **Director**: shot purpose, visual composition, continuity, and visual rhythm.
- **Performance Director**: casting, pacing, pronunciation, emotion, and audio
  performance specifications.
- **Producer**: desired state, scheduling requests, repair proposals, and
  completion evidence.
- **Critic**: structured evaluation of story, continuity, visual relevance,
  performance, pacing, subtitles, and final media.

Agent rules:

1. Return schema-validated structured output.
2. Never write arbitrary repository or story files directly.
3. Never mark production state complete.
4. Never hide fallback behavior or validation failures.
5. Include evidence for critiques and repair proposals.
6. Respect locked revisions, shots, voices, images, and timelines.
7. Keep prompts model-aware and within the selected model's effective limits.
8. Preserve the canonical narration rules under `skills/` unless a production
   explicitly selects another versioned style pack.

## Durable Job Rules

Allowed job states are:

`queued`, `leased`, `running`, `waiting`, `retryable`, `failed`, `succeeded`,
`cancel_requested`, and `cancelled`.

Every executable job records:

- stable job ID and idempotency key
- production, story, scene, and shot scope where applicable
- job type and required worker capabilities
- priority and dependency IDs
- immutable input payload or input fingerprint
- attempt number and retry policy
- lease owner, lease expiry, and heartbeat
- progress, current stage, and human-readable message
- structured failure category and diagnostic reference
- output asset IDs
- creation, start, update, and completion timestamps

Workers must heartbeat. Expired leases become retryable. Cancellation is
cooperative first and forceful only through a worker-management operation.

## Worker Scheduling

Workers declare capabilities instead of being inferred from names or ports.
Examples include `image.sd15`, `image.sdxl`, `gpu.directml`, `cpu`, `tts`,
`subtitle`, and `render.ffmpeg`.

The scheduler considers:

- required capabilities
- health and heartbeat freshness
- GPU or CPU preference
- configured concurrency
- queue age and explicit priority
- model readiness where observable
- recent failures and circuit-breaker state

Never send the same exclusive GPU device concurrent jobs unless the worker
configuration explicitly allows it.

## Asset Rules

Assets are immutable. Revisions reference assets; they do not edit them.

Each asset records:

- media type, dimensions or duration, and byte size
- checksum and generation fingerprint
- relative storage path
- provenance and source revision
- validation status and evidence
- creation time

Large media remains on disk. SQLite stores metadata and references. Do not put
large image, audio, or video blobs in SQLite.

## Completion Contract

A publishable production requires all of the following:

- Valid story metadata, story bible, and approved scene order
- Every scene has approved narration text and at least one approved shot
- Every shot has its requested usable artwork and timing
- Every required narration track is valid and non-silent
- Subtitles cover the approved narration and fit inside its duration
- Timeline references only current, validated assets
- Scene and full-story renders contain expected video and audio streams
- Release chapters, subtitles, poster, and metadata are present
- Release artifacts are current relative to every dependency
- No required job is queued, running, retryable, failed, or stale
- Completion verifier returns structured passing evidence

File existence alone is never proof of completion.

## Test-Driven Development

TDD is mandatory for new production-engine behavior and bug fixes.

Use the red-green-review cycle:

1. Agree on the public seam and behavior.
2. Add one failing test that expresses user-visible or domain-visible behavior.
3. Confirm the failure is meaningful.
4. Implement only enough behavior to pass.
5. Run focused tests and then the relevant broader suite.
6. Review design and refactor separately while keeping tests green.

Do not write a large speculative test suite before implementation. Build one
vertical tracer slice at a time.

Primary planned test seams are provisional until confirmed in the rebuild plan:

- Production Engine command and inspection interface
- Production Store transactional interface
- Scheduler lease, heartbeat, retry, and cancellation interface
- Adapter contract suites
- Completion Verifier interface
- Timeline Engine interface
- HTTP and WebSocket interface
- Browser-level critical user journeys

Testing rules:

- Test behavior through public interfaces, not private functions.
- Prefer deterministic fakes at provider seams.
- Keep contract tests for every real adapter.
- Keep a small opt-in hardware smoke suite for ComfyUI and FFmpeg.
- Use independent expected fixtures, not values recomputed by production logic.
- Never require paid APIs or a GPU for the default test suite.
- Every migration must include rollback and legacy-import tests.
- Every production bug gets a regression test before its fix.

## Frontend Rules

The target frontend is a typed, modular studio application. It must provide:

- Library
- Production Desk
- Story Studio
- Player
- Worker management
- Settings and provider health

Frontend state is a projection of backend state. Do not invent completion or
progress locally. Recover state after refresh by querying durable runs and
events.

Every long-running action must provide:

- immediate acknowledgement
- durable task identity
- current stage and progress
- waiting reason where applicable
- retry or cancellation behavior
- final success or actionable failure

Use one notification and task system. Do not add parallel toast, modal, and
task-panel implementations for the same operation.

## Migration Rules

Use a strangler migration. Do not replace the working app in one commit.

- Characterize current behavior before moving it.
- Import existing manifests without mutating them by default.
- Introduce new reads before new writes.
- Keep feature flags for old and new execution paths during transition.
- Migrate one vertical capability at a time.
- Each commit leaves the app runnable and tests green.
- Backups and rollback are required before destructive migration.
- Delete legacy code only after parity, migration, and rollback gates pass.

## Security and Repository Hygiene

- Never commit credentials, provider tokens, runtime databases, logs, generated
  stories, model files, or personal transcripts.
- Validate IDs and paths before filesystem access.
- Restrict provider redirects and outbound hosts.
- Use parameterized database operations through the store implementation.
- Treat prompts, generated text, subtitles, filenames, and metadata as
  untrusted input at HTML, shell, FFmpeg, and filesystem seams.
- Never build shell commands by concatenating untrusted strings.
- Public-repository defaults must be safe without secret local configuration.

## Change Discipline

- Use tiny, intention-revealing commits.
- Do not combine architecture migration, UI redesign, and generated media in a
  single commit.
- Include tests in the same commit as the behavior they specify.
- Update architecture decisions and migration status when a decision changes.
- Do not commit runtime outputs as test fixtures; create small deterministic
  fixtures under `tests/fixtures/`.

## Definition of Done for a Code Change

A change is complete only when:

- its public behavior and seam are documented
- a failing test was observed before the implementation when TDD applies
- focused and broader relevant tests pass
- persistence, retry, cancellation, and stale-output effects were considered
- progress and failures are understandable in the UI
- security and path handling were reviewed
- migration and rollback effects are documented
- no unrelated user files or generated assets were modified

## Prohibited Shortcuts

- Process-local state as the only record of work
- Completion inferred only from status strings or file size
- Direct provider calls from routes or UI handlers
- Agents directly mutating production files
- Regenerating a whole story to fix one shot
- Deleting the last valid asset before replacement validation
- Separate timing models for player, subtitles, render, and Plex
- Hidden quality reductions or silent provider fallback
- Tests that mock private implementation details
- Big-bang replacement of the current application

## Planning Source

The implementation sequence, provisional decisions, risks, and acceptance gates
are maintained in `docs/FANTASEE_REBUILD_PLAN.md`. When this file and the plan
conflict, stop and resolve the decision explicitly before implementation.
