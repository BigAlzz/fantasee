import { useState } from "react";
import {
  BookOpen,
  Check,
  ChevronRight,
  GitBranch,
  ImagePlus,
  Plus,
  Save,
  Sparkles,
  Users,
  WandSparkles,
  X,
} from "lucide-react";
import {
  api,
  type GenerateInput,
  type SeedSuggestion,
  type WorldArc,
  type WorldCharacter,
  type WorldKnowledgeBase,
  type WorldRelationship,
} from "./api";

const storyStyles = [
  ["cinematic grounded realism", "Cinematic realism"],
  ["moody painterly fantasy", "Moody painterly fantasy"],
  ["cinematic storybook adventure", "Storybook adventure"],
  ["neon noir animation", "Neon noir animation"],
  ["hand-painted dark folklore", "Hand-painted dark folklore"],
  ["warm documentary naturalism", "Warm documentary naturalism"],
] as const;

const storyTones = [
  ["grounded, tense, humane", "Grounded and humane"],
  ["ominous, intimate, restrained", "Ominous and intimate"],
  ["warm, kinetic, hopeful", "Warm and kinetic"],
  ["witty, brisk, mischievous", "Witty and mischievous"],
  ["lyrical, tender, melancholic", "Lyrical and melancholic"],
  ["strange, dreamlike, unsettling", "Dreamlike and strange"],
] as const;

const narrationOptions = [
  ["", "Studio default"],
  ["story-style-prompt", "Cinematic storyteller"],
  ["gamelit-isekai-style-prompt", "Game-lit adventure"],
] as const;

const voiceOptions = [
  ["Dean", "Dean - deep, warm authority"],
  ["Mia", "Mia - intimate, luminous"],
  ["Milo", "Milo - grounded, textured"],
  ["Chloe", "Chloe - ethereal, precise"],
] as const;

const sceneOptions = [3, 5, 7, 8, 10, 12] as const;
const imageOptions = [3, 5, 7, 9] as const;

const relationshipTypeOptions = [
  "ally",
  "rival",
  "mentor",
  "family",
  "romantic",
  "protects",
  "owes a debt to",
  "opposes",
  "depends on",
  "uneasy alliance",
] as const;

function relationshipActors(world: WorldKnowledgeBase, relationship: WorldRelationship) {
  const characterNames = world.characters.map((character) => character.name.trim()).filter(Boolean);
  const factionNames = Array.from(world.factions.matchAll(/(?:^|[.\n])\s*([^:.\n]{2,60}):/g)).map((match) => match[1].trim());
  return Array.from(new Set([...characterNames, ...factionNames, relationship.from, relationship.to].filter(Boolean)));
}

type StoryStudioTab = "brief" | "world" | "characters";

type StoryStudioProps = {
  brief: GenerateInput;
  onBriefChange: (brief: GenerateInput) => void;
  world: WorldKnowledgeBase;
  onWorldChange: (world: WorldKnowledgeBase) => void;
  seeds: SeedSuggestion[];
  seedBusy: boolean;
  onSuggestSeeds: () => void;
  onQueueBrief: () => void;
};

export function StoryStudioWorkspace({
  brief,
  onBriefChange,
  world,
  onWorldChange,
  seeds,
  seedBusy,
  onSuggestSeeds,
  onQueueBrief,
}: StoryStudioProps) {
  const [tab, setTab] = useState<StoryStudioTab>("brief");
  const [savedSnapshot, setSavedSnapshot] = useState(() =>
    JSON.stringify(world),
  );
  const [saveMessage, setSaveMessage] = useState(
    "Context is ready for the next production.",
  );
  const [portraitBusy, setPortraitBusy] = useState<string>();
  const [portraitBatchBusy, setPortraitBatchBusy] = useState(false);

  const worldSnapshot = JSON.stringify(world);
  const worldDirty = worldSnapshot !== savedSnapshot;
  const updateBrief = (patch: Partial<GenerateInput>) =>
    onBriefChange({ ...brief, ...patch });
  const updateWorld = (patch: Partial<WorldKnowledgeBase>) =>
    onWorldChange({ ...world, ...patch });
  const updateCharacter = (id: string, patch: Partial<WorldCharacter>) =>
    updateWorld({
      characters: world.characters.map((character) =>
        character.id === id ? { ...character, ...patch } : character,
      ),
    });
  const updateRelationship = (id: string, patch: Partial<WorldRelationship>) =>
    updateWorld({
      relationships: world.relationships.map((relationship) =>
        relationship.id === id ? { ...relationship, ...patch } : relationship,
      ),
    });
  const updateArc = (id: string, patch: Partial<WorldArc>) =>
    updateWorld({
      arcs: world.arcs.map((arc) =>
        arc.id === id ? { ...arc, ...patch } : arc,
      ),
    });

  const addCharacter = () =>
    updateWorld({
      characters: [
        ...world.characters,
        {
          id: `character-${Date.now()}`,
          name: "New character",
          role: "Role in the story",
          description:
            "The short continuity anchor the writer should always remember.",
          voice: "Dean",
          style: "Studio default",
          age: "",
          alignment: "Unaligned",
          traits: "observant, conflicted, resilient",
          appearance: "",
          biography: "",
          motivation: "",
        },
      ],
    });
  const addRelationship = () =>
    updateWorld({
      relationships: [
        ...world.relationships,
        {
          id: `relationship-${Date.now()}`,
          from: world.characters[0]?.name || "Character A",
          to: world.characters[1]?.name || "Character B",
          label: "relationship",
          status: "forming",
        },
      ],
    });
  const addArc = () =>
    updateWorld({
      arcs: [
        ...world.arcs,
        {
          id: `arc-${Date.now()}`,
          title: "New universe arc",
          summary: "What changes across this arc?",
          status: "planned",
          beats: "Inciting pressure\nComplication\nChoice\nConsequence",
        },
      ],
    });

  const saveWorld = () => {
    try {
      window.localStorage.setItem("fantasee.world.knowledge", worldSnapshot);
      setSavedSnapshot(worldSnapshot);
      setSaveMessage(
        `Saved ${world.title || "Untitled universe"} with ${world.characters.length} character sheets.`,
      );
    } catch {
      setSaveMessage("The browser could not save this canon locally.");
    }
  };

  const queueWithContext = () => {
    saveWorld();
    onQueueBrief();
  };

  const generatePortrait = async (character: WorldCharacter) => {
    setPortraitBusy(character.id);
    try {
      const result = await api.generateCharacterPortrait({
        character_id: character.id,
        name: character.name,
        role: character.role,
        description: character.description,
        appearance: character.appearance,
        alignment: character.alignment,
        traits: character.traits,
        biography: character.biography,
        world_context: `${world.title}\n${world.rules}\n${world.factions}`,
      });
      updateCharacter(character.id, { portrait_url: result.url });
      setSaveMessage(
        `${character.name || "Character"} portrait generated. Save the canon to keep the reference.`,
      );
    } catch (error) {
      setSaveMessage(
        error instanceof Error
          ? error.message
          : "Portrait generation could not be completed.",
      );
    } finally {
      setPortraitBusy(undefined);
    }
  };

  const generatePortraits = async () => {
    if (!world.characters.length) return;
    setPortraitBatchBusy(true);
    try {
      const result = await api.generateCharacterPortraits({
        world_context: `${world.title}\n${world.rules}\n${world.factions}`,
        characters: world.characters.map((character) => ({
          character_id: character.id,
          name: character.name,
          role: character.role,
          description: character.description,
          appearance: character.appearance,
          alignment: character.alignment,
          traits: character.traits,
          biography: character.biography,
        })),
      });
      result.portraits.forEach((portrait) =>
        updateCharacter(portrait.character_id, { portrait_url: portrait.url }),
      );
      setSaveMessage(
        result.failed.length
          ? `${result.portraits.length} portraits painted; ${result.failed.length} queued for another pass.`
          : `${result.portraits.length} portraits painted across the worker pool.`,
      );
    } catch (error) {
      setSaveMessage(
        error instanceof Error
          ? error.message
          : "The portrait batch could not be completed.",
      );
    } finally {
      setPortraitBatchBusy(false);
    }
  };

  const tabItems: Array<{
    id: StoryStudioTab;
    label: string;
    detail: string;
    icon: typeof BookOpen;
  }> = [
    {
      id: "brief",
      label: "Story brief",
      detail: "Intent and direction",
      icon: BookOpen,
    },
    {
      id: "world",
      label: "World builder",
      detail: "Canon and story flow",
      icon: GitBranch,
    },
    {
      id: "characters",
      label: "Character sheets",
      detail: `${world.characters.length} in the cast`,
      icon: Users,
    },
  ];

  return (
    <div className="creative-workspace story-studio-workspace">
      <div className="creative-heading story-studio-heading">
        <div>
          <span className="eyebrow-label">
            Writer - world architect - continuity editor
          </span>
          <h1>Make the world feel inevitable.</h1>
          <p className="desk-intro">
            Shape the brief first, then give the writer a living canon to draw
            from. Every saved decision travels into the next production run.
          </p>
        </div>
        <div className="world-context-status">
          <span className={worldDirty ? "led amber" : "led green"} />
          <div>
            <strong>
              {worldDirty ? "Unsaved canon changes" : "World context ready"}
            </strong>
            <small>
              {world.title || "Untitled universe"} - {world.characters.length}{" "}
              characters - {world.arcs.length} open arcs
            </small>
          </div>
        </div>
      </div>

      <nav
        className="story-studio-tabs"
        aria-label="Story Studio sections"
        role="tablist"
      >
        {tabItems.map(({ id, label, detail, icon: Icon }) => (
          <button
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={
              tab === id ? "story-studio-tab active" : "story-studio-tab"
            }
            key={id}
            onClick={() => setTab(id)}
          >
            <span className="tab-icon">
              <Icon size={16} />
            </span>
            <span>
              <strong>{label}</strong>
              <small>{detail}</small>
            </span>
            {tab === id && <Check size={15} />}
          </button>
        ))}
      </nav>

      <div className="story-studio-context-bar">
        <span>
          <span className={worldDirty ? "led amber" : "led green"} />
          {worldDirty ? "Draft canon" : "Saved generation context"}
        </span>
        <small>{saveMessage}</small>
        <div>
          <button type="button" className="outline-button" onClick={saveWorld}>
            <Save size={14} /> Save world context
          </button>
          {tab !== "brief" && (
            <button
              type="button"
              className="create"
              onClick={() => setTab("brief")}
            >
              <ChevronRight size={14} /> Continue to brief
            </button>
          )}
        </div>
      </div>

      {tab === "brief" && (
        <StoryBriefTab
          brief={brief}
          updateBrief={updateBrief}
          seeds={seeds}
          seedBusy={seedBusy}
          onSuggestSeeds={onSuggestSeeds}
          onQueueBrief={queueWithContext}
          world={world}
          onOpenWorld={() => setTab("world")}
        />
      )}
      {tab === "world" && (
        <WorldBuilderTab
          world={world}
          updateWorld={updateWorld}
          updateRelationship={updateRelationship}
          updateArc={updateArc}
          addRelationship={addRelationship}
          addArc={addArc}
          onSave={saveWorld}
          onOpenCharacters={() => setTab("characters")}
        />
      )}
      {tab === "characters" && (
        <CharacterSheetsTab
          world={world}
          updateWorld={updateWorld}
          updateCharacter={updateCharacter}
          addCharacter={addCharacter}
          updateRelationship={updateRelationship}
          updateArc={updateArc}
          addRelationship={addRelationship}
          addArc={addArc}
          portraitBusy={portraitBusy}
          portraitsBusy={portraitBatchBusy}
          onGeneratePortrait={generatePortrait}
          onGeneratePortraits={generatePortraits}
          onSave={saveWorld}
        />
      )}
    </div>
  );
}

function StoryBriefTab({
  brief,
  updateBrief,
  seeds,
  seedBusy,
  onSuggestSeeds,
  onQueueBrief,
  world,
  onOpenWorld,
}: {
  brief: GenerateInput;
  updateBrief: (patch: Partial<GenerateInput>) => void;
  seeds: SeedSuggestion[];
  seedBusy: boolean;
  onSuggestSeeds: () => void;
  onQueueBrief: () => void;
  world: WorldKnowledgeBase;
  onOpenWorld: () => void;
}) {
  const selectedPreset = [
    {
      id: "finn",
      label: "Finn realism",
      style: "cinematic grounded realism",
      tone: "grounded, tense, humane",
      scenes: 8,
      images: 7,
      voice: "Dean",
      narrationStyle: "",
    },
    {
      id: "dark-fable",
      label: "Dark fable",
      style: "moody painterly fantasy",
      tone: "ominous, intimate, restrained",
      scenes: 7,
      images: 6,
      voice: "Milo",
      narrationStyle: "",
    },
    {
      id: "bright-adventure",
      label: "Bright adventure",
      style: "cinematic storybook adventure",
      tone: "warm, kinetic, hopeful",
      scenes: 6,
      images: 5,
      voice: "Mia",
      narrationStyle: "",
    },
  ].find(
    (preset) => preset.style === brief.style && preset.tone === brief.tone,
  );
  return (
    <div className="story-brief-tab">
      <section className="brief-hero-panel">
        <div>
          <span className="eyebrow-label">01 - Intent</span>
          <h2>What should this story make us feel?</h2>
          <p>
            Start with a strong creative question. The world context below will
            be attached when you queue the production.
          </p>
        </div>
        <div className="brief-context-card">
          <span className="led green" />
          <div>
            <strong>{world.title || "Untitled universe"}</strong>
            <small>Generation context attached</small>
          </div>
          <button
            type="button"
            className="micro-button"
            onClick={onOpenWorld}
            title="Open world builder"
          >
            <ChevronRight size={15} />
          </button>
        </div>
      </section>
      <div className="creative-grid story-brief-grid">
        <section className="creative-form">
          <label className="brief-field wide">
            <span>Story intent</span>
            <textarea
              value={brief.story_concept}
              onChange={(event) =>
                updateBrief({ story_concept: event.target.value })
              }
              placeholder="A medic from Johannesburg wakes in a cold mountain village where every wound carries a memory..."
            />
            <button
              type="button"
              className="outline-button seed-button"
              disabled={seedBusy}
              onClick={onSuggestSeeds}
            >
              {seedBusy ? "Consulting director..." : "Suggest three directions"}
            </button>
          </label>
          {seeds.length > 0 && (
            <div className="seed-grid">
              {seeds.map((seed) => (
                <button
                  type="button"
                  className="seed-card"
                  key={`${seed.title}-${seed.description}`}
                  onClick={() =>
                    updateBrief({
                      story_concept: `${seed.title}\n${seed.description}`,
                      style: seed.style || brief.style,
                      tone: seed.tone || brief.tone,
                      characters: seed.characters || brief.characters,
                    })
                  }
                >
                  <strong>{seed.title}</strong>
                  <small>{seed.description}</small>
                  <em>
                    {seed.style || brief.style} - {seed.tone || brief.tone}
                  </em>
                </button>
              ))}
            </div>
          )}
          <div className="brief-grid">
            <label className="brief-field">
              <span>Director preset</span>
              <select
                value={selectedPreset?.id || "custom"}
                onChange={(event) => {
                  const preset = [
                    {
                      id: "finn",
                      style: "cinematic grounded realism",
                      tone: "grounded, tense, humane",
                      scenes: 8,
                      images: 7,
                      voice: "Dean",
                      narrationStyle: "",
                    },
                    {
                      id: "dark-fable",
                      style: "moody painterly fantasy",
                      tone: "ominous, intimate, restrained",
                      scenes: 7,
                      images: 6,
                      voice: "Milo",
                      narrationStyle: "",
                    },
                    {
                      id: "bright-adventure",
                      style: "cinematic storybook adventure",
                      tone: "warm, kinetic, hopeful",
                      scenes: 6,
                      images: 5,
                      voice: "Mia",
                      narrationStyle: "",
                    },
                  ].find((item) => item.id === event.target.value);
                  if (preset)
                    updateBrief({
                      style: preset.style,
                      tone: preset.tone,
                      num_scenes: preset.scenes,
                      images_per_scene: preset.images,
                      voice_preset: preset.voice,
                      narration_style: preset.narrationStyle,
                    });
                }}
              >
                <option value="custom">Custom direction</option>
                <option value="finn">Finn realism</option>
                <option value="dark-fable">Dark fable</option>
                <option value="bright-adventure">Bright adventure</option>
              </select>
            </label>
            <label className="brief-field">
              <span>Scene count</span>
              <select
                value={brief.num_scenes}
                onChange={(event) =>
                  updateBrief({ num_scenes: Number(event.target.value) })
                }
              >
                {sceneOptions.map((count) => (
                  <option key={count} value={count}>
                    {count} scenes -{" "}
                    {count <= 5
                      ? "short arc"
                      : count >= 10
                        ? "full feature"
                        : "balanced arc"}
                  </option>
                ))}
              </select>
            </label>
            <label className="brief-field">
              <span>Visual density</span>
              <select
                value={brief.images_per_scene}
                onChange={(event) =>
                  updateBrief({ images_per_scene: Number(event.target.value) })
                }
              >
                {imageOptions.map((count) => (
                  <option key={count} value={count}>
                    {count} beats per scene
                  </option>
                ))}
              </select>
            </label>
            <label className="brief-field">
              <span>Visual language</span>
              <select
                value={brief.style}
                onChange={(event) => updateBrief({ style: event.target.value })}
              >
                {storyStyles.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="brief-field">
              <span>Emotional register</span>
              <select
                value={brief.tone}
                onChange={(event) => updateBrief({ tone: event.target.value })}
              >
                {storyTones.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="brief-field">
              <span>Narration direction</span>
              <select
                value={brief.narration_style || ""}
                onChange={(event) =>
                  updateBrief({ narration_style: event.target.value })
                }
              >
                {narrationOptions.map(([value, label]) => (
                  <option key={value || "default"} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="brief-field wide">
            <span>Characters and continuity notes</span>
            <textarea
              value={brief.characters}
              onChange={(event) =>
                updateBrief({ characters: event.target.value })
              }
              placeholder="Optional immediate cast notes. Deep canon lives in the World Builder."
            />
          </label>
          <label className="brief-field wide">
            <span>Narrator</span>
            <select
              value={brief.voice_preset}
              onChange={(event) =>
                updateBrief({ voice_preset: event.target.value })
              }
            >
              {voiceOptions.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button
            className="create queue-brief-button"
            type="button"
            onClick={onQueueBrief}
          >
            <WandSparkles size={16} /> Save context and push to production
          </button>
        </section>
        <aside className="creative-rail brief-rail">
          <span className="eyebrow-label">Continuity handoff</span>
          <h2>{world.title || "Untitled universe"}</h2>
          <p>
            The writer receives the saved premise, rules, factions, character
            canon, relationships, arcs, and flow map.
          </p>
          <div className="handoff-step">
            <span>01</span>
            <div>
              <strong>Story question</strong>
              <small>
                {brief.story_concept
                  ? "Creative intent captured"
                  : "Waiting for your premise"}
              </small>
            </div>
          </div>
          <div className="handoff-step">
            <span>02</span>
            <div>
              <strong>World context</strong>
              <small>
                {world.rules
                  ? "Rules and canon attached"
                  : "Add rules in World Builder"}
              </small>
            </div>
          </div>
          <div className="handoff-step">
            <span>03</span>
            <div>
              <strong>Cast</strong>
              <small>{world.characters.length} rich character sheets</small>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function WorldBuilderTab({
  world,
  updateWorld,
  updateRelationship,
  updateArc,
  addRelationship,
  addArc,
  onSave,
  onOpenCharacters,
}: {
  world: WorldKnowledgeBase;
  updateWorld: (patch: Partial<WorldKnowledgeBase>) => void;
  updateRelationship: (id: string, patch: Partial<WorldRelationship>) => void;
  updateArc: (id: string, patch: Partial<WorldArc>) => void;
  addRelationship: () => void;
  addArc: () => void;
  onSave: () => void;
  onOpenCharacters: () => void;
}) {
  return (
    <div className="world-builder-tab">
      <section className="world-overview world-builder-hero">
        <div>
          <span className="eyebrow-label">02 - Canon</span>
          <h2>Give the universe rules it can remember.</h2>
          <p>
            Save this layer before generation. It becomes the shared context for
            story writing, visual direction, and character continuity.
          </p>
        </div>
        <div className="world-builder-actions">
          <button type="button" className="outline-button" onClick={onSave}>
            <Save size={14} /> Save canon
          </button>
          <button type="button" className="create" onClick={onOpenCharacters}>
            <Users size={14} /> Shape the cast
          </button>
        </div>
      </section>
      <section className="world-section world-overview">
        <div className="section-heading">
          <div>
            <h2>World knowledge base</h2>
            <small>
              A compact source of truth for every story in this universe.
            </small>
          </div>
          <span>
            {world.characters.length} sheets - {world.arcs.length} arcs
          </span>
        </div>
        <div className="brief-grid">
          <label className="brief-field">
            <span>Universe name</span>
            <input
              value={world.title}
              onChange={(event) => updateWorld({ title: event.target.value })}
              placeholder="The world or universe title"
            />
          </label>
          <label className="brief-field wide">
            <span>Core premise</span>
            <textarea
              value={world.premise}
              onChange={(event) => updateWorld({ premise: event.target.value })}
              placeholder="What is true about this world, and what pressure keeps its stories moving?"
            />
          </label>
          <label className="brief-field wide">
            <span>Rules and knowledge</span>
            <textarea
              value={world.rules}
              onChange={(event) => updateWorld({ rules: event.target.value })}
              placeholder="History, physics, technology, magic, ecology, taboos, and continuity facts."
            />
          </label>
          <label className="brief-field wide">
            <span>Factions, cultures, and institutions</span>
            <textarea
              value={world.factions}
              onChange={(event) =>
                updateWorld({ factions: event.target.value })
              }
              placeholder="Groups, competing beliefs, resources, and power structures."
            />
          </label>
        </div>
      </section>
      <section className="world-section relationship-section">
        <div className="section-heading">
          <div>
            <h2>Relationships</h2>
            <small>Keep the pressure between people visible.</small>
          </div>
          <button
            type="button"
            className="micro-button"
            onClick={addRelationship}
          >
            <Plus size={13} /> Add relationship
          </button>
        </div>
        <div className="relationship-list">
          {world.relationships.length ? (
            world.relationships.map((relationship) => (
              <div className="relationship-row" key={relationship.id}>
                <select
                  value={relationship.from}
                  onChange={(event) =>
                    updateRelationship(relationship.id, {
                      from: event.target.value,
                    })
                  }
                  aria-label="Relationship source"
                >
                  <option value="">Choose source...</option>
                  {relationshipActors(world, relationship).map((actor) => (
                    <option value={actor} key={`from-${actor}`}>
                      {actor}
                    </option>
                  ))}
                </select>
                <span>to</span>
                <select
                  value={relationship.to}
                  onChange={(event) =>
                    updateRelationship(relationship.id, {
                      to: event.target.value,
                    })
                  }
                  aria-label="Relationship target"
                >
                  <option value="">Choose target...</option>
                  {relationshipActors(world, relationship).map((actor) => (
                    <option value={actor} key={`to-${actor}`}>
                      {actor}
                    </option>
                  ))}
                </select>
                <select
                  value={relationship.label}
                  onChange={(event) =>
                    updateRelationship(relationship.id, {
                      label: event.target.value,
                    })
                  }
                  aria-label="Relationship description"
                >
                  {!relationshipTypeOptions.includes(relationship.label as (typeof relationshipTypeOptions)[number]) && (
                    <option value={relationship.label}>{relationship.label}</option>
                  )}
                  {relationshipTypeOptions.map((type) => (
                    <option value={type} key={type}>
                      {type}
                    </option>
                  ))}
                </select>
                <select
                  value={relationship.status}
                  onChange={(event) =>
                    updateRelationship(relationship.id, {
                      status: event.target.value,
                    })
                  }
                >
                  <option>forming</option>
                  <option>active</option>
                  <option>fractured</option>
                  <option>resolved</option>
                </select>
                <button
                  type="button"
                  className="micro-button"
                  onClick={() =>
                    updateWorld({
                      relationships: world.relationships.filter(
                        (item) => item.id !== relationship.id,
                      ),
                    })
                  }
                  title="Remove relationship"
                >
                  <X size={12} />
                </button>
              </div>
            ))
          ) : (
            <p className="ledger-empty">
              No relationships yet. Add the first tension line.
            </p>
          )}
        </div>
      </section>
      <section className="world-section diagram-section">
        <div className="section-heading">
          <div>
            <h2>Story flow and arc map</h2>
            <small>
              Live visual preview from your Mermaid-compatible source.
            </small>
          </div>
          <span>
            <GitBranch size={14} /> {world.arcs.length} tracked arcs
          </span>
        </div>
        <MermaidFlowPreview
          source={world.flowDiagram}
          onChange={(flowDiagram) => updateWorld({ flowDiagram })}
        />
      </section>
    </div>
  );
}

function CharacterSheetsTab({
  world,
  updateWorld,
  updateCharacter,
  addCharacter,
  updateRelationship,
  updateArc,
  addRelationship,
  addArc,
  portraitBusy,
  portraitsBusy,
  onGeneratePortrait,
  onGeneratePortraits,
  onSave,
}: {
  world: WorldKnowledgeBase;
  updateWorld: (patch: Partial<WorldKnowledgeBase>) => void;
  updateCharacter: (id: string, patch: Partial<WorldCharacter>) => void;
  addCharacter: () => void;
  updateRelationship: (id: string, patch: Partial<WorldRelationship>) => void;
  updateArc: (id: string, patch: Partial<WorldArc>) => void;
  addRelationship: () => void;
  addArc: () => void;
  portraitBusy?: string;
  portraitsBusy: boolean;
  onGeneratePortrait: (character: WorldCharacter) => Promise<void>;
  onGeneratePortraits: () => Promise<void>;
  onSave: () => void;
}) {
  return (
    <div className="character-studio-tab">
      <section className="world-section character-intro">
        <div>
          <span className="eyebrow-label">03 - Cast</span>
          <h2>Characters with a pulse.</h2>
          <p>
            Give each person a face, a history, and a contradiction. These
            sheets become continuity context for the writer and the performance
            director.
          </p>
        </div>
        <div className="character-intro-actions">
          <button type="button" className="outline-button" onClick={onSave}>
            <Save size={14} /> Save character canon
          </button>
          <button
            type="button"
            className="outline-button"
            disabled={portraitsBusy || !world.characters.length}
            onClick={() => void onGeneratePortraits()}
          >
            <WandSparkles size={14} />{" "}
            {portraitsBusy ? "Painting cast..." : "Paint cast in parallel"}
          </button>
          <button type="button" className="create" onClick={addCharacter}>
            <Plus size={14} /> Add character
          </button>
        </div>
      </section>
      <div className="rich-character-grid">
        {world.characters.length ? (
          world.characters.map((character) => (
            <RichCharacterCard
              key={character.id}
              character={character}
              portraitBusy={portraitBusy === character.id}
              updateCharacter={updateCharacter}
              onGeneratePortrait={onGeneratePortrait}
            />
          ))
        ) : (
          <div className="empty-state">
            <Users size={28} />
            <h3>Build your first character</h3>
            <p>
              The world becomes easier to write when its people have a point of
              view.
            </p>
            <button type="button" className="create" onClick={addCharacter}>
              <Plus size={14} /> Add character
            </button>
          </div>
        )}
      </div>
      <div className="character-support-grid">
        <section className="world-section">
          <div className="section-heading">
            <div>
              <h2>Relationship web</h2>
              <small>Character names stay editable as the cast evolves.</small>
            </div>
            <button
              type="button"
              className="micro-button"
              onClick={addRelationship}
            >
              <Plus size={13} /> Add
            </button>
          </div>
          <div className="relationship-list">
            {world.relationships.map((relationship) => (
              <div className="relationship-row" key={relationship.id}>
                <select
                  value={relationship.from}
                  onChange={(event) =>
                    updateRelationship(relationship.id, {
                      from: event.target.value,
                    })
                  }
                  aria-label="Relationship source"
                >
                  <option value="">Choose source...</option>
                  {relationshipActors(world, relationship).map((actor) => (
                    <option value={actor} key={`from-${actor}`}>
                      {actor}
                    </option>
                  ))}
                </select>
                <span>to</span>
                <select
                  value={relationship.to}
                  onChange={(event) =>
                    updateRelationship(relationship.id, {
                      to: event.target.value,
                    })
                  }
                  aria-label="Relationship target"
                >
                  <option value="">Choose target...</option>
                  {relationshipActors(world, relationship).map((actor) => (
                    <option value={actor} key={`to-${actor}`}>
                      {actor}
                    </option>
                  ))}
                </select>
                <select
                  value={relationship.label}
                  onChange={(event) =>
                    updateRelationship(relationship.id, {
                      label: event.target.value,
                    })
                  }
                  aria-label="Relationship description"
                >
                  {!relationshipTypeOptions.includes(relationship.label as (typeof relationshipTypeOptions)[number]) && (
                    <option value={relationship.label}>{relationship.label}</option>
                  )}
                  {relationshipTypeOptions.map((type) => (
                    <option value={type} key={type}>
                      {type}
                    </option>
                  ))}
                </select>
                <select
                  value={relationship.status}
                  onChange={(event) =>
                    updateRelationship(relationship.id, {
                      status: event.target.value,
                    })
                  }
                >
                  <option>forming</option>
                  <option>active</option>
                  <option>fractured</option>
                  <option>resolved</option>
                </select>
              </div>
            ))}
          </div>
        </section>
        <section className="world-section">
          <div className="section-heading">
            <div>
              <h2>Universe arcs</h2>
              <small>Promises that continue beyond one story.</small>
            </div>
            <button type="button" className="micro-button" onClick={addArc}>
              <Plus size={13} /> Add
            </button>
          </div>
          <div className="arc-grid">
            {world.arcs.map((arc) => (
              <article className="arc-card" key={arc.id}>
                <div className="character-sheet-heading">
                  <input
                    value={arc.title}
                    onChange={(event) =>
                      updateArc(arc.id, { title: event.target.value })
                    }
                    aria-label="Arc title"
                  />
                  <select
                    value={arc.status}
                    onChange={(event) =>
                      updateArc(arc.id, {
                        status: event.target.value as WorldArc["status"],
                      })
                    }
                  >
                    <option value="planned">Planned</option>
                    <option value="active">Active</option>
                    <option value="resolved">Resolved</option>
                  </select>
                </div>
                <textarea
                  value={arc.summary}
                  onChange={(event) =>
                    updateArc(arc.id, { summary: event.target.value })
                  }
                  aria-label="Arc summary"
                />
                <textarea
                  value={arc.beats}
                  onChange={(event) =>
                    updateArc(arc.id, { beats: event.target.value })
                  }
                  aria-label="Arc beats"
                />
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function RichCharacterCard({
  character,
  portraitBusy,
  updateCharacter,
  onGeneratePortrait,
}: {
  character: WorldCharacter;
  portraitBusy: boolean;
  updateCharacter: (id: string, patch: Partial<WorldCharacter>) => void;
  onGeneratePortrait: (character: WorldCharacter) => Promise<void>;
}) {
  const initials =
    character.name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase() || "?";
  return (
    <article className="rich-character-card">
      <div className="character-portrait-column">
        <div className="character-portrait">
          {character.portrait_url ? (
            <img
              src={character.portrait_url}
              alt={`${character.name} portrait`}
            />
          ) : (
            <span>{initials}</span>
          )}
          <div className="portrait-glow" />
        </div>
        <button
          type="button"
          className="portrait-button"
          disabled={portraitBusy}
          onClick={() => void onGeneratePortrait(character)}
        >
          {portraitBusy ? (
            <>
              <Sparkles size={13} /> Painting...
            </>
          ) : (
            <>
              <ImagePlus size={13} /> Generate look
            </>
          )}
        </button>
        <small>Uses the world rules and this sheet as visual context.</small>
      </div>
      <div className="character-sheet-body">
        <div className="character-sheet-heading rich-heading">
          <div>
            <input
              className="character-name-input"
              value={character.name}
              onChange={(event) =>
                updateCharacter(character.id, { name: event.target.value })
              }
              aria-label="Character name"
            />
            <input
              className="character-role-input"
              value={character.role}
              onChange={(event) =>
                updateCharacter(character.id, { role: event.target.value })
              }
              aria-label="Character role"
            />
          </div>
          <span className="character-voice-mark">
            {character.voice} / {character.style}
          </span>
        </div>
        <div className="character-facts-grid">
          <label>
            <span>Age / era</span>
            <input
              value={character.age || ""}
              onChange={(event) =>
                updateCharacter(character.id, { age: event.target.value })
              }
              placeholder="32, elder, timeless..."
            />
          </label>
          <label>
            <span>Alignment</span>
            <select
              value={character.alignment || "Unaligned"}
              onChange={(event) =>
                updateCharacter(character.id, { alignment: event.target.value })
              }
            >
              <option>Unaligned</option>
              <option>Lawful good</option>
              <option>Chaotic good</option>
              <option>True neutral</option>
              <option>Lawful neutral</option>
              <option>Chaotic neutral</option>
              <option>Lawful cruel</option>
              <option>Chaotic cruel</option>
            </select>
          </label>
          <label className="wide">
            <span>Traits</span>
            <input
              value={character.traits || ""}
              onChange={(event) =>
                updateCharacter(character.id, { traits: event.target.value })
              }
              placeholder="patient, proud, funny under pressure"
            />
          </label>
        </div>
        <label className="character-long-field">
          <span>Biography</span>
          <textarea
            value={character.biography || character.description}
            onChange={(event) =>
              updateCharacter(character.id, {
                biography: event.target.value,
                description: event.target.value,
              })
            }
            placeholder="Where did they come from? What shaped the person they are now?"
          />
        </label>
        <div className="character-detail-grid">
          <label>
            <span>Appearance</span>
            <textarea
              value={character.appearance || ""}
              onChange={(event) =>
                updateCharacter(character.id, {
                  appearance: event.target.value,
                })
              }
              placeholder="Face, silhouette, clothing, materials, distinguishing details..."
            />
          </label>
          <label>
            <span>Motivation and wound</span>
            <textarea
              value={character.motivation || ""}
              onChange={(event) =>
                updateCharacter(character.id, {
                  motivation: event.target.value,
                })
              }
              placeholder="What do they want, and what do they refuse to face?"
            />
          </label>
        </div>
      </div>
    </article>
  );
}

type FlowNode = { id: string; label: string; x: number; y: number };
type FlowEdge = { from: string; to: string };

function parseFlow(source: string): {
  direction: "LR" | "TD";
  nodes: FlowNode[];
  edges: FlowEdge[];
} {
  const nodeMap = new Map<string, string>();
  const nodePattern = /([A-Za-z][\w-]*)\s*\[([^\]]+)\]/g;
  for (const match of source.matchAll(nodePattern))
    nodeMap.set(match[1], match[2].trim());
  const edges: FlowEdge[] = [];
  const edgePattern =
    /([A-Za-z][\w-]*)\s*(?:-->|-.->|==>|---)\s*([A-Za-z][\w-]*)/g;
  for (const match of source.matchAll(edgePattern))
    edges.push({ from: match[1], to: match[2] });
  edges.forEach(({ from, to }) => {
    if (!nodeMap.has(from)) nodeMap.set(from, from);
    if (!nodeMap.has(to)) nodeMap.set(to, to);
  });
  const direction = /^\s*(?:flowchart|graph)\s+LR/i.test(source) ? "LR" : "TD";
  const nodes = [...nodeMap.entries()].map(([id, label], index) =>
    direction === "LR"
      ? { id, label, x: 130 + index * 250, y: 100 }
      : { id, label, x: 390, y: 75 + index * 92 },
  );
  return { direction, nodes, edges };
}

function MermaidFlowPreview({
  source,
  onChange,
}: {
  source: string;
  onChange: (source: string) => void;
}) {
  const flow = parseFlow(source);
  const width =
    flow.direction === "LR" ? Math.max(760, flow.nodes.length * 250 + 80) : 760;
  const height =
    flow.direction === "LR" ? 220 : Math.max(260, flow.nodes.length * 92 + 35);
  const positions = new Map(flow.nodes.map((node) => [node.id, node]));
  const wrapLabel = (label: string) =>
    label.length > 25 ? `${label.slice(0, 24)}...` : label;
  return (
    <div className="flow-preview-shell">
      <div className="flow-preview-toolbar">
        <span>
          <span className="led green" /> Rendered flow
        </span>
        <small>
          {flow.direction === "LR" ? "left to right" : "top to bottom"} -{" "}
          {flow.nodes.length} nodes
        </small>
      </div>
      {flow.nodes.length ? (
        <div className="flow-canvas">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label="Rendered story flow diagram"
          >
            <defs>
              <marker
                id="flow-arrow"
                markerWidth="8"
                markerHeight="8"
                refX="7"
                refY="4"
                orient="auto"
              >
                <path d="M0,0 L8,4 L0,8 z" fill="#c58a42" />
              </marker>
            </defs>
            {flow.edges.map((edge) => {
              const from = positions.get(edge.from);
              const to = positions.get(edge.to);
              if (!from || !to) return null;
              return (
                <line
                  key={`${edge.from}-${edge.to}`}
                  x1={from.x}
                  y1={from.y + (flow.direction === "TD" ? 27 : 0)}
                  x2={to.x - (flow.direction === "LR" ? 100 : 0)}
                  y2={to.y - (flow.direction === "TD" ? 27 : 0)}
                  stroke="#8b6e3e"
                  strokeWidth="2"
                  markerEnd="url(#flow-arrow)"
                />
              );
            })}
            {flow.nodes.map((node) => (
              <g
                key={node.id}
                transform={`translate(${node.x - 100}, ${node.y - 27})`}
              >
                <rect
                  width="200"
                  height="54"
                  rx="4"
                  fill="#171a16"
                  stroke="#b18245"
                />
                <text
                  x="100"
                  y="22"
                  textAnchor="middle"
                  fill="#ead8b5"
                  fontSize="12"
                  fontFamily="Bahnschrift, sans-serif"
                >
                  {wrapLabel(node.label)}
                </text>
                <text
                  x="100"
                  y="42"
                  textAnchor="middle"
                  fill="#827961"
                  fontSize="9"
                  fontFamily="Consolas, monospace"
                >
                  {node.id}
                </text>
              </g>
            ))}
          </svg>
        </div>
      ) : (
        <div className="flow-empty">
          <GitBranch size={22} />
          <span>
            Use Mermaid nodes such as{" "}
            <code>A[Inciting pressure] --&gt; B[Choice]</code> to draw the map.
          </span>
        </div>
      )}
      <details className="mermaid-source">
        <summary>Edit Mermaid source</summary>
        <textarea
          value={source}
          onChange={(event) => onChange(event.target.value)}
          aria-label="Mermaid flow source"
        />
        <small>
          Keep node IDs simple. The preview supports flowchart and graph
          directions with bracketed node labels.
        </small>
      </details>
    </div>
  );
}
