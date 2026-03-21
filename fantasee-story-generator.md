# FANTASEE Story Generator

A cinematic, local-first AI story studio that writes, narrates, illustrates, and plays back multi-part stories in a beautiful browser experience.

This document is written as a build brief for Codex. It describes the product vision, architecture, roadmap, database design, API contracts, worker behavior, UI, prompt strategy, and delivery phases for a local-first MVP that runs on a Windows PC and is accessible from browsers on the local network.

---

## 1. Product Goal

Build a polished web app that allows a user to:

- choose from many story genres
- optionally enter a title and premise
- or press Generate to receive 3 suggested story concepts
- select one concept and start generation immediately
- begin listening to Part 1 as soon as it is ready
- continue generating later parts in the background while playback continues
- view the story in a tablet or ebook-style reader
- auto-scroll the text as narration progresses
- highlight the current sentence or line being read
- change font size and theme
- pause, resume, seek, skip, and bookmark
- save stories in a personal local library
- continue a story beyond its original planned ending
- optionally generate cover and scene art
- assign different voices to different characters using Kokoro on the local server

The product should feel slick, elegant, fun, cinematic, and modern.

---

## 2. Why this architecture

Keep the first version simple.

Use:

- Next.js for the UI and local API layer
- SQLite for storage
- Prisma ORM
- a lightweight Python worker service for long-running jobs
- LM Studio for story generation
- Kokoro for TTS
- ffmpeg for stitching audio
- local filesystem for media assets

Do not introduce Redis in v1.

A SQLite-backed jobs table is sufficient for a single-machine or single-user local app. Redis only becomes worthwhile later for multi-machine workers, large concurrency, or real-time pub/sub across multiple app instances.

---

## 3. Recommended technical stack

### Frontend

- Next.js 15+ with App Router
- TypeScript
- Tailwind CSS
- Framer Motion
- Zustand for local player and reader state
- TanStack Query for job polling and API state
- Howler.js or HTMLAudioElement for playback orchestration
- react-window only if library list becomes large
- optional shadcn/ui for base components

### Backend within the app

- Next.js Route Handlers
- Prisma ORM
- SQLite database
- Zod for request and response validation

### Worker and media pipeline

- Python 3.11+
- FastAPI or a lightweight background worker process
- requests or httpx for LM Studio / Kokoro calls
- ffmpeg installed on the PC and accessible in PATH
- Pillow for any simple image or cover composition work
- pydantic for structured worker contracts

### AI and media services

- LM Studio local server for story generation and structuring http://172.23.48.1:3006/v1
- Kokoro local server for multi-voice TTS
- optional local image generation later
- optional hosted image API later if needed

### Storage

- SQLite file for metadata and jobs
- media files stored locally under a data directory

Suggested layout:

```text
/data
  /stories
    /<story-id>
      /parts
      /audio
      /images
      /timings
      /exports
```

---

## 4. Product identity and UX direction

This should not look like an admin dashboard. It should feel like a small private story studio.

### Visual direction

- dark cinematic default theme
- alternate parchment and sepia reading themes
- soft gradients and restrained glow effects
- elegant serif font for story text
- clean sans-serif font for controls and metadata
- subtle motion, not noisy motion
- polished cover cards in the library
- immersive create flow
- bottom playback rail with smooth state changes

### Product tagline

Fantasee is a cinematic, local-first story studio that writes, narrates, illustrates, and evolves stories in real time.

---

## 5. Core features

### 5.1 Story creation

User can:

- choose a genre from a large catalog
- optionally choose a subgenre or tone
- enter an optional title
- enter an optional premise or keywords
- choose the number of parts
- choose target length per part
- choose reading style or narrator pack
- enable or disable image generation

If no title is supplied, the app generates 3 story concepts with:

- title
- blurb
- tone tags
- optional sample cover prompt

### 5.2 Story generation

The app creates a Story Bible and then generates the story in parts.

Each part should:

- remain consistent with prior parts
- move toward a natural ending by the selected number of parts
- return structured text broken into narration and dialogue segments
- return summary and continuity notes
- optionally return image prompts

### 5.3 Audio generation and playback

- Kokoro handles TTS locally
- each important character can be assigned a different voice
- narrator voice covers prose and unattributed lines
- segments are synthesized separately and stitched into a final part audio file
- Part 1 should start playing as soon as its audio is ready
- later parts should continue generating in the background
- the player should preload the next ready part

### 5.4 Reader

- ebook or tablet-style reading view
- auto-scroll synced to playback
- highlight current sentence or paragraph
- adjustable font size
- theme switching
- pause, play, seek, skip, next part, previous part
- bookmark current position
- resume from last position

### 5.5 Library

- saved stories grid/list view
- continue listening
- continue reading
- search and filter by genre, title, status
- cover image preview
- reading progress display

### 5.6 Continuation

If the story has not ended or the user wants more, they can press Continue Story.

This should:

- generate more parts using prior summaries and unresolved threads
- preserve continuity
- optionally let the user steer tone or direction

---

## 6. Genre system

Support a wide list of genres. The UI should make genre selection enjoyable, not just a raw dropdown.

### Recommended initial genre list

Core genres:

- Fantasy
- Epic Fantasy
- Dark Fantasy
- Urban Fantasy
- Fairy Tale
- Mythic Adventure
- Science Fiction
- Space Opera
- Cyberpunk
- Steampunk
- Dystopian
- Post-Apocalyptic
- Time Travel
- Mystery
- Detective
- Thriller
- Psychological Thriller
- Horror
- Gothic Horror
- Paranormal
- Adventure
- Action
- Historical Fiction
- Alternate History
- Romance
- Romantic Comedy
- Drama
- Literary Fiction
- Young Adult
- Coming of Age
- Comedy
- Satire

Lighter and family-oriented:

- Bedtime Story
- Children’s Adventure
- Animal Tale
- Educational Story
- Magical School
- Cozy Village Tale
- Folklore Inspired

Distinctive and regional:

- African Fantasy
- Afrofuturism
- Township Mystery
- Johannesburg Magic
- Karoo Ghost Story
- Futuristic African City
- Pirate Adventure
- Treasure Hunt
- Court Intrigue
- Survival Tale
- Monster Hunt
- Superhero

### Tone packs

Add a second layer of selection:

- Grand Epic
- Cozy Campfire
- Dark Theatre
- Dreamlike
- Storybook
- Witty and Fast
- Noir Broadcast
- Playful Adventure
- Children’s Bedtime

---

## 7. Recommended architecture

### 7.1 High-level shape

Use two app processes plus local services:

1. Next.js app
2. Python worker
3. LM Studio local server
4. Kokoro local server

### 7.2 Responsibilities

#### Next.js app

- create story records
- present UI
- accept user input
- start jobs
- serve story library
- serve reader/player state
- poll job status
- expose media assets

#### Python worker

- claim queued jobs from SQLite
- call LM Studio
- parse and validate structured responses
- assign voices to characters
- call Kokoro to synthesize segments
- merge audio with ffmpeg
- generate timing metadata
- save images and timing files
- update status and results

---

## 8. Monorepo / project layout for Codex

Use a clean repo layout.

```text
fantasee/
  app/
    (next app router pages)
  components/
  lib/
    db.ts
    api/
    player/
    prompts/
    schemas/
  prisma/
    schema.prisma
  public/
  scripts/
  worker/
    main.py
    jobs/
    services/
    schemas/
    utils/
  data/
  package.json
  pyproject.toml
  README.md
  AGENTS.md
```

### Important repo additions for Codex

- include `README.md` with setup instructions
- include `AGENTS.md` with project conventions, coding rules, and verification steps
- include sample `.env.example`
- include seed script for genres and voice packs
- include a developer script to verify LM Studio and Kokoro connectivity

Codex supports repo-local instructions and reusable workflows via docs like `AGENTS.md`, and OpenAI has published guidance on using repo-local skills and structured instructions to improve agentic coding workflows. citeturn955301search6turn955301search8

---

## 9. Database schema

Use Prisma with SQLite.

### 9.1 stories

Fields:

- id
- title
- genre
- subgenre
- tone_pack
- description
- status
- planned_parts
- generated_parts
- cover_image_path
- image_mode
- narrator_voice_id
- total_duration_seconds
- created_at
- updated_at

Status examples:

- draft
- generating
- playable
- complete
- failed
- archived

### 9.2 story_parts

Fields:

- id
- story_id
- part_number
- title
- summary
- full_text
- continuity_notes_json
- status
- audio_status
- image_status
- merged_audio_path
- timing_json_path
- duration_seconds
- created_at
- updated_at

### 9.3 story_part_segments

Fields:

- id
- story_part_id
- segment_order
- type
- speaker_name
- text
- voice_id
- audio_path
- start_ms
- end_ms
- char_start_index
- char_end_index
- created_at

`type` values:

- narration
- dialogue
- interlude

### 9.4 characters

Fields:

- id
- story_id
- name
- role
- description
- traits_json
- voice_id
- first_appearance_part
- created_at
- updated_at

### 9.5 voices

Fields:

- id
- provider
- local_voice_name
- label
- gender_hint
- age_hint
- tone_tags_json
- style_tags_json
- active

Provider will be `kokoro` for now.

### 9.6 jobs

Fields:

- id
- story_id
- part_number
- job_type
- status
- priority
- payload_json
- result_json
- error_text
- attempts
- created_at
- started_at
- finished_at

Recommended job types:

- generate_concepts
- build_story_bible
- generate_part
- generate_part_audio
- generate_part_images
- continue_story
- rebuild_timings

Recommended status values:

- queued
- running
- done
- failed
- canceled

### 9.7 bookmarks

Fields:

- id
- story_id
- story_part_id
- char_index
- audio_position_ms
- note
- created_at

### 9.8 reading_progress

Fields:

- id
- story_id
- current_part_number
- char_index
- audio_position_ms
- font_size
- theme
- playback_speed
- auto_scroll
- updated_at

### 9.9 story_bibles

Fields:

- id
- story_id
- world_rules_json
- plot_arc_json
- ending_plan_json
- continuity_state_json
- created_at
- updated_at

### 9.10 images

Fields:

- id
- story_id
- story_part_id
- image_type
- prompt_text
- file_path
- created_at

`image_type` values:

- cover
- chapter
- scene
- metaphor

---

## 10. Story generation model design

### 10.1 Use structured generation

Do not ask LM Studio for raw freeform prose only. Ask for structured JSON.

Each part must return:

- part_title
- summary
- segments[]
- continuity_notes[]
- character_updates[]
- image_prompts[]
- end_state

### 10.2 Story Bible

Before generating the first part, generate a Story Bible containing:

- premise
- setting
- world rules
- narrator style
- cast list
- major plot arc
- major conflict
- ending intention
- unresolved threads list

This hidden structured memory helps keep the story coherent.

### 10.3 Part generation rules

For a selected number of parts, the model should:

- open the story strongly in Part 1
- develop conflict and stakes in middle parts
- move toward resolution in final planned part
- leave continuation room only if the user selected open ending or expandable saga

### 10.4 Ending modes

Support:

- Tight Ending
- Open Ending
- Expandable Saga

### 10.5 Structured JSON example

```json
{
  "part_title": "The Clocktower at Ashfall",
  "summary": "Mira discovers the clocktower is alive and Old Ferren knows why.",
  "segments": [
    {
      "type": "narration",
      "speaker": "Narrator",
      "text": "Rain moved over Ashfall like a dark curtain."
    },
    {
      "type": "dialogue",
      "speaker": "Mira",
      "text": "You knew this place was awake, didn’t you?"
    },
    {
      "type": "dialogue",
      "speaker": "Old Ferren",
      "text": "Knowing is one thing. Surviving it is another."
    }
  ],
  "continuity_notes": [
    "Mira does not yet know what happened to her brother.",
    "The tower responds to brass objects."
  ],
  "character_updates": [
    {
      "name": "Mira",
      "state": "More suspicious of Old Ferren"
    }
  ],
  "image_prompts": [
    "A haunted clocktower over a rain-soaked village at dusk"
  ],
  "end_state": "Tension escalates and the mystery deepens"
}
```

---

## 11. Prompt strategy for Codex to implement

Store prompts in versioned files under `lib/prompts/`.

### 11.1 Concept prompt

Input:

- genre
- tone pack
- optional title hint
- optional premise

Output:

- three concepts, each with title, blurb, and tone tags

### 11.2 Story Bible prompt

Input:

- chosen concept
- planned parts
- ending mode
- audience age band
- genre and tone

Output:

- story bible JSON

### 11.3 Part generation prompt

Input:

- story bible
- previous part summaries
- unresolved threads
- target part number
- planned parts
- desired pacing

Output:

- structured part JSON

### 11.4 Continue story prompt

Input:

- story bible
- all summaries so far
- unresolved threads
- latest end state
- continue directive from user

Output:

- next part JSON plus updated continuity state

### 11.5 Safety and formatting rules

Prompt should explicitly require:

- valid JSON only
- no markdown wrapper
- no omitted required fields
- no contradictory character behavior without explanation
- consistent tense and voice
- natural prose, not screenplay format, unless a future mode supports it

---

## 12. Kokoro TTS design

Kokoro is the local TTS engine.

### 12.1 Voice strategy

Treat voice assignment like casting.

Layers:

1. global style pack
2. narrator voice
3. per-character voices

### 12.2 Character voice assignment

Auto-cast voices using character role and traits.

Examples:

- wise mentor -> deep, slow, deliberate
- young hero -> bright, energetic, warm
- villain -> calm, cold, low-intensity
- comic sidekick -> lively, expressive
- elder spirit -> airy, distant, strange

Store assignments in the database to maintain continuity.

### 12.3 Segment-based TTS flow

For each part:

1. iterate over segments in order
2. select voice based on speaker
3. synthesize each segment via Kokoro
4. save segment audio files
5. stitch all segments into one merged part file with ffmpeg
6. compute start and end times for each segment
7. save timing metadata

### 12.4 Timing strategy

Start with sentence-level or paragraph-level highlighting.

Word-level karaoke is possible later, but sentence-level is the better initial tradeoff between complexity and polish.

### 12.5 Audio file strategy

Store:

- raw segment files
- merged part file
- timing JSON

This allows regeneration of merged audio without fully rerunning generation.

---

## 13. Playback and reader design

### 13.1 Playback behavior

- play Part 1 as soon as audio exists
- while Part 1 plays, generate Part 2 and beyond in the background
- preload the next merged audio file once ready
- auto-advance between parts when possible
- if next part is still rendering, show a polite loading state and continue polling

### 13.2 Reader behavior

- render story text in a centered reading panel
- highlight the active sentence or paragraph according to current playback time
- auto-scroll active text into view
- allow toggling auto-scroll off
- preserve font size and theme in `reading_progress`

### 13.3 Controls

- play / pause
- previous / next part
- skip back 10 seconds
- skip forward 10 seconds
- playback speed
- font size plus/minus
- theme selector
- bookmark
- continue story
- regenerate final part ending later, optional future feature

### 13.4 Themes

Implement at least:

- Dark Velvet
- Parchment
- Sepia Moon

---

## 14. Image generation design

Images should be optional and should not block the MVP.

### 14.1 Initial modes

- Off
- Cover Only
- Cover + Chapter Art
- Cover + Scene Art

### 14.2 Use cases

- cover generation at story creation
- scene art for key moments
- metaphorical art if literal scene rendering is unreliable

### 14.3 Future approach

Start with placeholder support and image prompt generation. Add actual generation after text/audio pipeline is working.

---

## 15. API design for Next.js

Use Route Handlers under `app/api/...`.

### 15.1 Stories

#### `POST /api/stories`

Create a story draft.

Body:

```json
{
  "genre": "Fantasy",
  "subgenre": "Epic Fantasy",
  "tonePack": "Grand Epic",
  "plannedParts": 4,
  "title": "",
  "premise": "",
  "imageMode": "cover_only",
  "narratorVoiceId": "voice_01",
  "endingMode": "tight"
}
```

Response:

- story record
- queued job ids

#### `GET /api/stories/:id`

Return full story metadata.

#### `GET /api/stories/:id/parts`

Return all generated parts and statuses.

#### `POST /api/stories/:id/continue`

Queue continuation generation.

#### `POST /api/stories/:id/bookmarks`

Create bookmark.

#### `PATCH /api/stories/:id/progress`

Update reading progress.

### 15.2 Concepts

#### `POST /api/concepts`

Generate 3 concepts when no title is supplied.

### 15.3 Jobs

#### `GET /api/jobs/:id`

Return job status.

#### `GET /api/stories/:id/status`

Aggregate status across text, audio, and image jobs.

### 15.4 Voices

#### `GET /api/voices`

List available Kokoro voices and packs.

### 15.5 Genres

#### `GET /api/genres`

Return seeded genre catalog.

---

## 16. Worker design

### 16.1 Worker loop

Simple polling loop:

1. query jobs where status = queued
2. claim one atomically
3. update status to running
4. execute
5. store result
6. update status to done or failed

### 16.2 Job execution handlers

Implement handlers for:

- generate_concepts
- build_story_bible
- generate_part
- generate_part_audio
- generate_part_images
- continue_story

### 16.3 Atomicity rules

- every job should be idempotent where possible
- worker should tolerate crashes and restart cleanly
- use attempts count and retry caps
- do not duplicate part numbers

### 16.4 Recommended worker file structure

```text
worker/
  main.py
  jobs/
    base.py
    concepts.py
    story_bible.py
    part_generation.py
    part_audio.py
    part_images.py
    continue_story.py
  services/
    lm_studio.py
    kokoro.py
    ffmpeg.py
    storage.py
    db.py
  schemas/
    story.py
    jobs.py
    audio.py
  utils/
    text.py
    timings.py
    logging.py
```

---

## 17. Suggested connectivity contracts

### 17.1 LM Studio connectivity

Assume LM Studio is exposing an OpenAI-compatible local endpoint. LM Studio’s recent releases continue to support its local server and have expanded agentic features through its API-compatible surface. citeturn955301search0

Implement a connectivity health check script that:

- verifies base URL
- verifies model is available
- runs a tiny test completion
- verifies JSON output mode if used

### 17.2 Kokoro connectivity

Implement a health check that:

- pings the local Kokoro endpoint
- lists available voices
- synthesizes a tiny test segment
- confirms returned audio is valid

---

## 18. UI page map

### `/`

Home screen:

- hero banner
- Create Story button
- recent stories
- continue reading section
- featured genre carousel

### `/create`

Creation wizard:

Step 1
- genre
- subgenre
- tone pack
- planned parts
- ending mode

Step 2
- optional title
- optional premise
- surprise me button

Step 3
- show 3 generated concepts if needed
- select narrator pack
- image mode
- generate story button

### `/story/[id]`

Reader/player page:

- main reading panel
- right side drawer for art, cast, chapters, bookmarks
- bottom playback rail
- progress bar and generation status chips

### `/library`

Saved stories:

- grid/list toggle
- sort by latest, title, genre, duration
- filters

### `/settings`

- model settings
- LM Studio base URL
- Kokoro base URL
- ffmpeg path if needed
- media folder path
- default theme
- default narrator pack

---

## 19. UX details that matter

These are important to the feel of the product.

### 19.1 Smoothness

- avoid full-page refreshes
- use optimistic UI where safe
- keep generation status visible but unobtrusive
- preload next media asset
- use subtle loading animations

### 19.2 Fun

- concept cards should feel collectible and inviting
- narrator packs should feel like choosing a performance style
- cast panel should display characters like a tiny theatre roster

### 19.3 Elegance

- limit on-screen clutter
- hide advanced knobs behind drawers
- prioritize reading experience over admin controls

---

## 20. Enhancements to include in the plan

These are worth designing for, even if some are phase 2 or 3.

### 20.1 Bookmarks

Required. The user specifically wants this.

### 20.2 Director controls

Future controls to steer the story without re-prompting from scratch:

- make it darker
- add action
- more mystery
- more romance
- introduce a new character
- wrap it up
- add a twist
- make it child-friendly

### 20.3 Voice auditioning

Let the user preview narrator and sample character voices before starting.

### 20.4 Story exports

Later:

- export text as markdown or txt
- export package as zip
- export ebook format later

### 20.5 Cast panel

Show:

- character name
- short description
- voice label
- first appearance

### 20.6 Story map and continuity panel

Later, expose a simplified view of the hidden story bible.

---

## 21. What not to do in v1

Do not overcomplicate the first build.

Avoid in v1:

- Redis
- Postgres
- Docker-only dependency if not needed on the user’s PC
- multi-user auth
- billing
- cloud storage
- word-perfect karaoke timing if sentence-level looks good
- full branching narratives
- complicated recommendation engine

---

## 22. MVP definition

The MVP must prove the core magic.

### MVP requirements

- browse and select genre
- optionally generate 3 concepts
- pick one and start story generation
- generate Part 1
- synthesize Part 1 with Kokoro
- start playback in browser
- queue Part 2 and later parts in background
- display text in reader view
- highlight current sentence or paragraph
- auto-scroll with playback
- allow pause, resume, seek, font size change
- save story in library
- support bookmarks
- support Continue Story after planned ending

If those work, the product concept is proven.

---

## 23. Roadmap

### Phase 0: Project bootstrap

Deliverables:

- initialize Next.js app
- initialize Prisma with SQLite
- initialize Python worker
- create shared schemas and contracts
- add health-check scripts for LM Studio and Kokoro
- seed genres and voice packs
- create basic README and AGENTS.md

Definition of done:

- app starts
- worker starts
- health checks pass or fail clearly
- DB migrates successfully

### Phase 1: Story creation flow

Deliverables:

- create page UI
- genre selector
- tone pack selector
- planned parts selector
- title and premise fields
- concept generation endpoint
- concept selection cards
- story draft creation

Definition of done:

- user can create a draft story and select a concept or provide a title

### Phase 2: Story Bible and part generation

Deliverables:

- LM Studio service wrapper
- prompts stored as versioned files
- story bible generation
- generate_part job
- persist story parts in DB
- part status UI

Definition of done:

- Part 1 and later parts can be generated as structured JSON and stored cleanly

### Phase 3: Kokoro integration and merged playback

Deliverables:

- Kokoro service wrapper
- voice listing endpoint
- voice assignment logic
- part audio generation jobs
- ffmpeg merging
- merged audio file storage
- basic browser player

Definition of done:

- Part 1 can be listened to in the browser
- multiple character voices work inside a single part

### Phase 4: Reader sync and polish

Deliverables:

- timing metadata generation
- highlight current sentence or paragraph
- auto-scroll
- theme switching
- font size controls
- reading progress persistence

Definition of done:

- story can be read comfortably while being narrated

### Phase 5: Background generation and seamless queueing

Deliverables:

- background generation of next parts
- player preload strategy
- job status aggregation UI
- graceful waiting if next part is not yet ready

Definition of done:

- while Part 1 plays, the app can progress on later parts and auto-advance when ready

### Phase 6: Library and bookmarks

Deliverables:

- library page
- progress cards
- search and filter
- bookmarks
- resume from saved position

Definition of done:

- generated stories are reusable and easy to revisit

### Phase 7: Continue Story and director controls

Deliverables:

- Continue Story action
- continuation prompt chain
- unresolved thread carryover
- optional steering controls

Definition of done:

- user can extend a story naturally without breaking continuity

### Phase 8: Image pipeline

Deliverables:

- image prompt generation
- cover image pipeline
- optional chapter/scene art
- image display in reader and library

Definition of done:

- art enhances the story without blocking text/audio experience

### Phase 9: Production hardening for local deployment

Deliverables:

- error handling and retries
- better logging
- backup/export utilities
- settings page
- startup checks
- file cleanup strategy

Definition of done:

- app is stable enough for daily personal use

---

## 24. Codex-specific build guidance

The user wants Codex to build this. Structure the repo so Codex can work effectively.

### 24.1 Use a strong repo brief

Add `AGENTS.md` with:

- project purpose
- coding conventions
- architecture boundaries
- naming conventions
- how to run tests
- what constitutes done for each phase
- local URLs for LM Studio and Kokoro
- rules about not changing generated data formats without updating both app and worker

### 24.2 Include task-friendly docs

Add:

- `docs/architecture.md`
- `docs/api.md`
- `docs/worker.md`
- `docs/prompts.md`
- `docs/roadmap.md`

Codex is available across multiple surfaces including the app, IDE extension, CLI, and cloud workflows, and OpenAI’s official docs emphasize structured project instructions and repository context to improve long-running agentic tasks. citeturn955301search1turn955301search2turn955301search9turn955301search14

### 24.3 Suggested initial tasks for Codex

Task 1:
Bootstrap repo with Next.js, Prisma, SQLite, Tailwind, and Python worker skeleton.

Task 2:
Implement Prisma schema and seed scripts for genres and voice packs.

Task 3:
Implement create-story wizard and concept selection UI.

Task 4:
Implement LM Studio wrapper and JSON prompt pipeline.

Task 5:
Implement worker jobs for concept generation, story bible, and part generation.

Task 6:
Implement Kokoro wrapper and per-segment audio generation.

Task 7:
Implement ffmpeg merge and timing metadata.

Task 8:
Implement reader/player page with highlighting and auto-scroll.

Task 9:
Implement library and bookmarks.

Task 10:
Implement continue-story flow.

### 24.4 Model choice guidance

OpenAI’s current Codex surfaces support long-running coding tasks, and recent OpenAI materials describe GPT-5.3-Codex as the more capable long-horizon coding model, while GPT-5.4 mini is positioned as a faster, cheaper option for lighter tasks and subagents. citeturn955301search0turn955301search4turn955301search10

Recommended practical usage:

- use the strongest Codex model available for architecture, schema, and worker orchestration tasks
- use the lighter fast model for repetitive UI scaffolding, small refactors, and test fixes

---

## 25. Testing strategy

### 25.1 Unit tests

Test:

- prompt builders
- JSON validators
- voice assignment logic
- timing merge logic
- job claim logic

### 25.2 Integration tests

Test:

- story draft creation
- concept generation pipeline with mocked LM Studio
- part generation pipeline with mocked LM Studio
- audio generation with mocked Kokoro
- merged output artifact creation

### 25.3 Manual acceptance tests

- create fantasy story without title
- pick one of three concepts
- generate and listen to Part 1
- verify Part 2 starts generating in background
- verify bookmark works
- verify continue story works
- verify font size and auto-scroll are remembered

---

## 26. Error handling requirements

### 26.1 LM Studio failures

- mark job failed with visible error
- allow retry
- preserve story draft

### 26.2 Kokoro failures

- keep part text playable in reading mode even if audio failed
- allow audio-only retry

### 26.3 ffmpeg failures

- preserve raw segment files
- allow rebuild merged audio job

### 26.4 Partial generation

- if a later part fails, earlier playable parts remain accessible

---

## 27. Future expansion path

Design DB and code so future additions are possible without rewrites.

Future features:

- multi-user auth
- pay gate / subscription
- cloud sync
- collaborative stories
- branching interactive mode
- ambient soundtracks
- EPUB export
- mobile PWA packaging
- analytics dashboard for popular genres and voice packs

SQLite is fine for v1 and can later migrate to Postgres if the product grows.

---

## 28. Build order recommendation

For fastest path to value, Codex should build in this exact order:

1. bootstrap repo and DB
2. story creation wizard
3. concept generation
4. story bible generation
5. Part 1 generation
6. Part 1 audio via Kokoro
7. browser playback
8. background generation for later parts
9. highlighting and auto-scroll
10. library and bookmarks
11. continue story
12. image support

That order proves the core experience early.

---

## 29. Definition of success

The first successful version should allow this exact moment:

The user picks Fantasy, taps Generate, chooses one of three concept cards, and within a short wait the app begins reading Part 1 aloud with a polished narrator voice while the text scrolls in a beautiful reader. Different characters sound different. Part 2 is already cooking in the background. The story is saved automatically into the library and can be resumed later from the exact same place.

That is the magic.

---

## 30. Final recommendation

Build this as a local-first cinematic story studio.

Use:

- Next.js
- TypeScript
- Tailwind
- Prisma + SQLite
- Python worker
- LM Studio
- Kokoro
- ffmpeg

Avoid premature architecture complexity.

Do not use Redis yet.

Nail the experience first.

---

## 31. Suggested first commit plan for Codex

1. Initialize Next.js app with Tailwind and TypeScript.
2. Add Prisma and SQLite schema.
3. Create worker skeleton with FastAPI or polling loop.
4. Add health-check page and scripts for LM Studio and Kokoro.
5. Build `/create` page with genre, tone, title, and planned parts.
6. Add concept generation API and UI cards.
7. Add Story Bible generation and part generation worker jobs.
8. Add Kokoro voice listing and per-segment synthesis.
9. Merge segment audio and expose browser playback.
10. Build reader with active sentence highlighting and bookmarks.
11. Build library page with resume support.
12. Add Continue Story.

---

## 32. Notes on Codex availability and usage

OpenAI’s official materials indicate Codex is available across the Codex app, IDE extension, CLI, and web-connected surfaces, with the Codex app now available on Windows and designed for parallel long-running tasks and reusable skills. citeturn955301search2turn955301search7turn955301search9

That makes this project a good fit for Codex, especially if the repo includes:

- clear architecture docs
- a roadmap
- strict JSON contracts
- AGENTS.md instructions
- small, testable tasks

---

## 33. Non-negotiable implementation rules

Codex should follow these rules while building:

- keep app and worker contracts typed and versioned
- validate all LM Studio outputs before saving
- never block the UI on long-running jobs
- preserve partially generated work
- treat audio generation and image generation as retryable child jobs
- keep all file paths relative to configured data root
- preserve voice consistency per character across all parts
- preserve continuity state after each part
- design APIs for local browser use first
- keep the repo simple and understandable

---

## 34. Nice names for UI modules

Optional, but helpful for product feel:

- Story Forge -> create flow
- Cast Booth -> voice auditioning
- Reading Room -> reader/player
- Archive -> library
- Director Panel -> future steering controls

---

## 35. Closing note

This product should feel like a private miniature theatre inside the machine.

The user presses Generate.
A story appears.
It speaks.
It scrolls.
It remembers.
It continues.

That is the north star.
