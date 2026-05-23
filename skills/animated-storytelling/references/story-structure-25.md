# 25-Scene Story Structure (4-Act)

Battle-tested across The Ironwood Covenant, The Last Rampart, The Bone Road,
and The Frost Grave. For high-density animated stories where each scene gets
~10-25s of narration.

## Character Bible Format

Embed the character bible at the top of the story markdown:

```markdown
### Name — Role
- **Hair:** exact descriptor
- **Eyes:** exact color + descriptor
- **Face:** shape, scars, expression
- **Build:** body type, height cues
- **Outfit:** specific clothing items (reuse these exact terms in ALL prompts)
- **Personality:** 1-2 sentence summary
```

Reuse hair/eyes/outfit descriptors verbatim in every scene prompt for consistency.

## Act Structure

### Act 1: The Setup (Scenes 1-6)
Establish protagonist, setting, and inciting incident. End with the character
committing to the journey/conflict.

| Scene | Purpose |
|-------|---------|
| 1 | Protagonist in their element — establish who they are |
| 2 | The problem arrives — inciting incident |
| 3 | Resistance/reaction — the world pushes back |
| 4 | The stakes become visible — scale, threat, what's at risk |
| 5 | Quiet before storm — emotional beat, bonding, doubt |
| 6 | Commitment — character chooses to act |

### Act 2: The Journey/Escalation (Scenes 7-14)
The character enters the unknown. Conflict intensifies. Allies/enemies revealed.

| Scene | Purpose |
|-------|---------|
| 7 | First step into danger/new territory |
| 8 | Discovery — something unexpected |
| 9 | Ally/enemy introduction — key secondary character |
| 10 | Bonding/tension — relationship development |
| 11 | Deeper into danger — sneaking, planning, travel |
| 12 | Brief victory or beauty — a moment of hope/wonder |
| 13 | Setback — the enemy strikes back, things go wrong |
| 14 | Lowest point so far — loss, sacrifice, the cost |

### Act 3: The Turning Point (Scenes 15-21)
Everything changes. The protagonist finds new strength/resources/allies and
turns the tide.

| Scene | Purpose |
|-------|---------|
| 15 | Picking up the pieces — aftermath of setback |
| 16 | Resource/recovery — finding what's needed to continue |
| 17 | The new plan/ritual/transformation |
| 18 | Return or confrontation begins |
| 19 | Victory that matters — small or large, but earned |
| 20 | Enemy's gambit — final threat escalates |
| 21 | The big confrontation — battle, ritual, final challenge |

### Act 4: Resolution & Legacy (Scenes 22-25)
Aftermath, new status quo, and a glimpse of the future.

| Scene | Purpose |
|-------|---------|
| 22 | The climax — enemy falls, problem solved, truth revealed |
| 23 | New order established — the world is different now |
| 24 | Looking forward — the character's choice about the future |
| 25 | Final wide shot — legacy, hope, the road ahead |

## Scene Block Format (parseable)

Each scene in the markdown must follow this exact format to be parseable
by the workflow generator:

```markdown
### Scene N — "Title" (Seed: NNNN)
**Narration:** The spoken text. Keep under 100 words for 25-scene density.
Write in present tense, active voice. Make each scene a complete story beat.

**Image Prompt:** A [shot type] of [exact moment from narration]. [Character
descriptions from bible]. [Setting with lighting]. [Mood]. High quality
anime illustration.
```

## Seed Convention

```
seed = 7000 + (project_number * 100) + scene_number

Project 1: 7101-7110 (Ironwood Covenant, 10 scenes)
Project 2: 7201-7225 (The Last Rampart, 25 scenes)
Project 3: 7301-7325 (The Bone Road, 25 scenes)
Project 4: 7401-7425 (The Frost Grave, 25 scenes)
Project 5: 7501-7525 (The Flood Tide, 25 scenes)
Project 6: 7601-7625 (The Star Watchers, 25 scenes)
```

Increment project_number for each new story. This prevents seed collisions
across projects.

## Narration Pacing

- 25 scenes: 60-95 words per narration (~10-25s spoken)
- 10 scenes: 80-120 words per narration (~20-40s spoken)
- Target spoken pace: ~150 words per minute (Edge TTS)

Total 25-scene story: ~1,800-2,200 words of narration → ~12-17 minutes.
