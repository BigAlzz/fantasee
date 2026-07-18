import { useEffect, useRef, useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import {
  Archive, ArrowDown, ArrowUp, ChevronRight, Clapperboard, Cpu, Gauge, Image, Library,
  LoaderCircle, MoreHorizontal, Music2, Pause, Play, Plus, Radio, RefreshCw,
  Search, Settings, Sparkles, Square, Trash2, Wand2,
  Volume1, Volume2, X,
} from "lucide-react";
import { api, type BackgroundTrack, type ComfyWorker, type GenerateInput, type GenerationTask, type MigrationReadiness, type ProductionEvent, type ProductionJob, type ProductionRelease, type ProductionRun, type RenderingMode, type SavedVoiceProfile, type Scene, type SeedSuggestion, type SemanticShot, type ShotAsset, type Story, type StoryDetail, type StudioSettings, type SubtitleCue, type TimelineShot, type TtsGenerateInput, type TtsModel, type Worker, type WorldArc, type WorldCharacter, type WorldKnowledgeBase, type WorldRelationship } from "./api";
import { StoryStudioWorkspace } from "./StoryStudio";
import { LibraryCatalog } from "./LibraryCatalog";
import { StoryDetails } from "./StoryDetails";
import { projectProductionActivity, type ProductionActivity } from "./productionActivity";
import { selectPlayableRelease } from "./releasePlayback";

const nav = [
  [Library, "Library"], [Sparkles, "Story Studio"], [Volume2, "Voice Studio"], [Clapperboard, "Production Runs"], [Archive, "Assets"], [Settings, "Settings"],
] as const;

const directorPresets = [
  { id: "finn", label: "Finn realism", style: "cinematic grounded realism", tone: "grounded, tense, humane", scenes: 8, images: 7, voice: "Dean", narrationStyle: "" },
  { id: "dark-fable", label: "Dark fable", style: "moody painterly fantasy", tone: "ominous, intimate, restrained", scenes: 7, images: 6, voice: "Milo", narrationStyle: "" },
  { id: "bright-adventure", label: "Bright adventure", style: "cinematic storybook adventure", tone: "warm, kinetic, hopeful", scenes: 6, images: 5, voice: "Mia", narrationStyle: "" },
  { id: "comic-panels", label: "Comic book panels", style: "comic book panels", tone: "kinetic, high-stakes, graphic, emotional", scenes: 7, images: 7, voice: "Dean", narrationStyle: "story-style-prompt" },
] as const;

const styleOptions = [
  ["cinematic grounded realism", "Cinematic realism"],
  ["moody painterly fantasy", "Moody painterly fantasy"],
  ["cinematic storybook adventure", "Storybook adventure"],
  ["neon noir animation", "Neon noir animation"],
  ["hand-painted dark folklore", "Hand-painted dark folklore"],
  ["warm documentary naturalism", "Warm documentary naturalism"],
  ["comic book panels", "Comic book panels · dynamic sequential art"],
] as const;

const toneOptions = [
  ["grounded, tense, humane", "Grounded and humane"],
  ["ominous, intimate, restrained", "Ominous and intimate"],
  ["warm, kinetic, hopeful", "Warm and kinetic"],
  ["witty, brisk, mischievous", "Witty and mischievous"],
  ["lyrical, tender, melancholic", "Lyrical and melancholic"],
  ["strange, dreamlike, unsettling", "Dreamlike and strange"],
] as const;

const narrationOptions = [
  ["", "Studio default"],
  ["story-style-prompt", "Cinematic story direction"],
  ["gamelit-isekai-style-prompt", "Game-lit adventure direction"],
] as const;

const narrationStylePresets = [
  { value: "", label: "Studio default", prompt: "Clear, smooth, lightly expressive narration with believable emotion." },
  { value: "story-style-prompt", label: "Cinematic storyteller", prompt: "A cinematic storyteller with controlled momentum, sensory emphasis, and restrained dramatic weight. Keep the delivery intimate and human." },
  { value: "gamelit-isekai-style-prompt", label: "Game-lit adventure", prompt: "A confident serialized adventure narrator with crisp action phrasing, quick momentum, and a warm sense of discovery. Keep emotional turns grounded." },
  { value: "audiobook-intimate", label: "Intimate audiobook", prompt: "A close, patient audiobook performance with quiet warmth, natural breaths, thoughtful pauses, and precise diction. Speak as if one listener is nearby." },
  { value: "documentary-observer", label: "Documentary observer", prompt: "A measured documentary voice with calm authority, lucid phrasing, and curious attention to concrete details. Avoid theatrical exaggeration." },
  { value: "dark-folklore", label: "Dark folklore", prompt: "A low, shadowed folklore delivery with deliberate pacing and a faint sense of old memory. Let unease live underneath the words without melodrama." },
  { value: "bright-companion", label: "Bright companion", prompt: "A warm, lightly playful companion telling a story to a trusted friend. Lift hopeful beats, keep humor natural, and never sound like an advertisement." },
] as const;

const voiceOptions = [
  ["Dean", "Dean · deep, warm authority"],
  ["Mia", "Mia · intimate, luminous"],
  ["Milo", "Milo · grounded, textured"],
  ["Chloe", "Chloe · ethereal, precise"],
] as const;

const sceneOptions = [3, 5, 7, 8, 10, 12] as const;
const imageOptions = [3, 5, 7, 9] as const;
const fallbackBackgroundTrack = "musictown-cinematic-atmosphere-score-1-no-melody-99288.mp3";

const releaseEditionOptions = [
  { id: "short", label: "Short", detail: "A tight shareable cut", icon: Sparkles },
  { id: "cinematic", label: "Cinematic", detail: "The full visual master", icon: Clapperboard },
  { id: "audiobook", label: "Audiobook", detail: "Narration-first listening", icon: Volume2 },
  { id: "trailer", label: "Trailer", detail: "A focused story hook", icon: Play },
  { id: "plex", label: "Plex", detail: "Packaged with artwork", icon: Archive },
] as const;

type ReleaseEditionId = typeof releaseEditionOptions[number]["id"];

type StudioUiState = { activeView?: string; selectedStoryId?: string; selectedRunId?: string; query?: string };
type ProductionDirection = { id: string; title: string; description: string; selected: boolean; input: GenerateInput };

function directionFromSeed(seed: SeedSuggestion, index: number, base: GenerateInput): ProductionDirection {
  return {
    id: `direction-${index + 1}`,
    title: seed.title,
    description: seed.description,
    selected: true,
    input: {
      ...base,
      story_concept: `${seed.title}\n${seed.description}`,
      style: seed.style || base.style,
      tone: seed.tone || base.tone,
      characters: seed.characters || base.characters,
    },
  };
}

const defaultWorldKnowledge: WorldKnowledgeBase = {
  title: "",
  premise: "",
  rules: "",
  factions: "",
  characters: [],
  relationships: [],
  arcs: [],
  flowDiagram: "flowchart TD\n  A[Inciting pressure] --> B[Choice]\n  B --> C[Consequence]\n  C --> D[Next arc question]",
};

const humansVsNeanderthalsExample: WorldKnowledgeBase = {
  title: "The Return — Humans vs Neanderthals",
  premise: "Forty thousand years after the Neanderthals vanished from Earth, a hidden Antarctic Ice Wall fails. Magical Neanderthals return from the Deep Cradle and dying Nevarrah while technologically advanced humans discover that their energy grid has been draining the world the returnees are trying to save.",
  rules: "The Ice Wall is an engineered prison and cloaking field, not a natural barrier. Its inner pocket, Tshuka-Vell (the Deep Cradle), contains the Luminous Vault, geothermal jungles, Arcaneite crystals, warped Crushed Horizons, and surviving Pleistocene megafauna. The Weave powers Neanderthal magic but does not naturally exist for humans. Climate change, drilling, and satellite electromagnetic activity fracture the wall; zero-point infrastructure can drain the hidden ecosystem. A rare human jailer marker may interact with and rewrite the blue runes. Neither species is morally uniform.",
  factions: "Stone-Born: militaristic reconquest led by First-Marked warchiefs. Weave-Born: shamans seeking coexistence and a third path. Deep-Men: shadow-adapted refugees who prefer the dark. Scattered: survival communities and bridge-builders. The Concord: global containment and research authority. Free Frontier: local human-Neanderthal coexistence. The Veil: human religious surrender movement. Apex Energy and treaty custodians: a covert network that hid the Ice Wall and profited from Weave-draining power systems. Human Guardians Unit 734: deniable Antarctic containment team.",
  characters: [
    { id: "nara", name: "Nara", role: "Human scout", description: "Observant, impatient with inherited hatred, and carrying a map of safe winter passes.", voice: "Mia", style: "Intimate audiobook", age: "28", alignment: "Chaotic good", traits: "observant, impatient, protective", appearance: "Wind-burned face, dark braids threaded with blue stone, layered hide and woven reed cloak.", biography: "Raised between trading camps, Nara learned every safe pass before she learned which people she was supposed to fear.", motivation: "She wants to prove cooperation is practical before the valley's scarcity turns hope into a luxury." },
    { id: "var", name: "Var", role: "Neanderthal toolmaker", description: "Patient, physically imposing, and quietly funny; believes objects remember the hands that made them.", voice: "Milo", style: "Grounded and warm", age: "34", alignment: "True neutral", traits: "patient, inventive, quietly funny", appearance: "Broad shoulders, ash-grey curls, ochre-stained hands, a carved bone tool worn as a pendant.", biography: "Var inherited a workshop and a feud, then quietly turned both into places where people could be useful together.", motivation: "He wants to keep his settlement alive without becoming the weapon his elders expect." },
    { id: "korrath", name: "Korrath Stone-Hand", role: "First-Marked Stone-Born warchief", description: "A broad, scarred commander carrying a volcanic monolith blade and a crystal-fused left hand. He believes war is inevitable and wants it to be brief.", voice: "Dean", style: "Deep, restrained authority", age: "47", alignment: "Conflicted militant", traits: "commanding, grieving, disciplined", appearance: "Gray-umber skin, ceremonial facial scars, long braids threaded with stone, glowing crystal hand.", biography: "Korrath leads the vanguard out of exile, carrying the memory of Earth as both home and wound.", motivation: "Reclaim Earth while preventing the Stone-Born from becoming the monsters humans already fear." },
    { id: "selene", name: "Selene Weave-Born", role: "Weave-Born elder and mediator", description: "An ancient survivor of the First Crossing who knows the cost of forcing two worlds together.", voice: "Mia", style: "Intimate, luminous", age: "300", alignment: "Principled mediator", traits: "patient, burdened, farsighted", appearance: "White-silver eyes, weathered face, simple fungal-fiber robes, hands marked by old rift burns.", biography: "Selene remembers Earth, Nevarrah before the Wound, and the decision that turned refuge into imprisonment.", motivation: "Find a third path before the Ice Wall breach destroys both worlds." },
    { id: "aris-thorne", name: "Dr. Aris Thorne", role: "Project Chimera geneticist", description: "A brilliant human researcher who sees the Weave and hybrid marker as solvable systems before he sees the people endangered by them.", voice: "Milo", style: "Grounded, clinical", age: "39", alignment: "Compromised human scientist", traits: "brilliant, curious, rationalizing", appearance: "Tired eyes, immaculate field coat, neural interface at the temple, blue rune fragments in his evidence case.", biography: "Thorne is trying to engineer a human who can channel the Weave and insists every boundary he crosses is temporary.", motivation: "Prove humanity can inherit magic without admitting the cost of the power grid." },
    { id: "marcus-cole", name: "Captain Marcus Cole", role: "Concord rapid-response commander", description: "A professional soldier whose first engagement with the Stone-Born left him convinced that restraint exists on both sides.", voice: "Dean", style: "Weathered, controlled", age: "44", alignment: "Conflicted protector", traits: "tactical, loyal, haunted", appearance: "Powered Ironhide armor, field-worn face, scar across the jaw, rifle kept lowered when civilians are near.", biography: "Cole serves the Concord while hiding that Korrath spared his unit when he could have finished them.", motivation: "Keep civilians alive long enough for the truth about the Antarctic breach to become impossible to bury." },
  ],
  relationships: [
    { id: "nara-var", from: "Nara", to: "Var", label: "uneasy alliance", status: "forming" },
    { id: "nara-ash", from: "Nara", to: "Ash Council", label: "opposed by", status: "active" },
    { id: "korrath-selene", from: "Korrath Stone-Hand", to: "Selene Weave-Born", label: "opposed by", status: "fractured" },
    { id: "thorne-cole", from: "Dr. Aris Thorne", to: "Captain Marcus Cole", label: "depends on", status: "forming" },
    { id: "apex-concord", from: "Apex Energy", to: "The Concord", label: "uneasy alliance", status: "active" },
    { id: "runes-engineer", from: "Human rune-bearer", to: "Ice Wall custodians", label: "opposed by", status: "forming" },
  ],
  arcs: [
    { id: "shared-winter", title: "The Shared Winter", summary: "Nara and Var must protect a mixed settlement before the first deep freeze.", status: "planned", beats: "Discovery of the pass\nA failed exchange\nThe avalanche\nA shared fire\nThe council's betrayal" },
    { id: "antarctic-breach", title: "The Antarctic Breach", summary: "A Human Guardian survives the McMurdo breach and finds the defense grid was disabled from inside.", status: "planned", beats: "Heartbeat in the ice\nThe blue blizzard\nThe silent outpost\nThe first vanguard\nThe treaty cover story" },
    { id: "power-crisis", title: "The Power Crisis", summary: "An Apex Energy engineer proves that human zero-point power is starving Tshuka-Vell.", status: "planned", beats: "The dimming crystals\nThe impossible energy balance\nThe city-wide blackout\nA choice between grids\nThe Deep Cradle answers" },
    { id: "hybrid-prophecy", title: "The Rune-Bearer", summary: "A human engineer with the jailer marker can rewrite the blue runes and becomes a target of both species.", status: "planned", beats: "The genetic match\nA rune responds\nThe Concord containment order\nStone-Born pursuit\nA new meaning for home" },
  ],
  flowDiagram: "flowchart TD\n  A[Ice Wall fractures] --> B[McMurdo outpost goes dark]\n  B --> C[Neanderthal vanguard crosses]\n  C --> D[Humans discover the power drain]\n  D --> E[Human rune-bearer wakes the blue seal]\n  E --> F[Both species choose war or a shared Earth]",
};

const worldTemplates = [
  { id: "current", label: "Current world", detail: "Use the canon currently open in World Builder." },
  { id: "humans-vs-neanderthals", label: "Humans vs Neanderthals", detail: "Antarctic Ice Wall, Deep Cradle, technology vs Weave.", world: humansVsNeanderthalsExample },
  { id: "blank", label: "Blank worldbuilder", detail: "Start a fresh universe with no inherited canon.", world: defaultWorldKnowledge },
] as const;

function readWorldKnowledge(): WorldKnowledgeBase {
  if (typeof window === "undefined") return defaultWorldKnowledge;
  try {
    const saved = window.localStorage.getItem("fantasee.world.knowledge");
    return saved ? { ...defaultWorldKnowledge, ...JSON.parse(saved) as WorldKnowledgeBase } : defaultWorldKnowledge;
  } catch {
    return defaultWorldKnowledge;
  }
}

function worldContextPrompt(world: WorldKnowledgeBase) {
  const characters = world.characters.map((character) => [
    `${character.name} (${character.role})`,
    character.age ? `Age/era: ${character.age}` : "",
    character.alignment ? `Alignment: ${character.alignment}` : "",
    character.traits ? `Traits: ${character.traits}` : "",
    `Biography: ${character.biography || character.description}`,
    character.appearance ? `Appearance: ${character.appearance}` : "",
    character.motivation ? `Motivation: ${character.motivation}` : "",
    `Voice: ${character.voice}; style: ${character.style}`,
  ].filter(Boolean).join(" | ")).join("\n") || "(none yet)";
  const relationships = world.relationships.map((relationship) => `${relationship.from} -> ${relationship.to}: ${relationship.label} [${relationship.status}]`).join("\n") || "(none yet)";
  const arcs = world.arcs.map((arc) => `${arc.title} [${arc.status}]: ${arc.summary}\nBeats: ${arc.beats}`).join("\n") || "(none yet)";
  return [
    `Universe: ${world.title || "Untitled universe"}`,
    `Premise: ${world.premise || "(not established)"}`,
    `World rules: ${world.rules || "(not established)"}`,
    `Factions: ${world.factions || "(not established)"}`,
    `Character sheets:\n${characters}`,
    `Relationships:\n${relationships}`,
    `Universe arcs:\n${arcs}`,
  ].join("\n\n");
}

function readSavedVoiceProfiles(): SavedVoiceProfile[] {
  if (typeof window === "undefined") return [];
  try {
    const saved = window.localStorage.getItem("fantasee.voice.profiles");
    const parsed = saved ? JSON.parse(saved) : [];
    return Array.isArray(parsed) ? parsed as SavedVoiceProfile[] : [];
  } catch {
    return [];
  }
}

const voiceProfileDbName = "fantasee-studio-voice-library";
const voiceProfileStoreName = "profiles";

function openVoiceProfileDb(): Promise<IDBDatabase | undefined> {
  if (typeof window === "undefined" || !window.indexedDB) return Promise.resolve(undefined);
  return new Promise((resolve) => {
    const request = window.indexedDB.open(voiceProfileDbName, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(voiceProfileStoreName)) {
        request.result.createObjectStore(voiceProfileStoreName, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(undefined);
  });
}

async function loadSavedVoiceProfiles(): Promise<SavedVoiceProfile[]> {
  const db = await openVoiceProfileDb();
  if (!db) return readSavedVoiceProfiles();
  return new Promise((resolve) => {
    const request = db.transaction(voiceProfileStoreName, "readonly").objectStore(voiceProfileStoreName).getAll();
    request.onsuccess = () => resolve((request.result as SavedVoiceProfile[]).sort((a, b) => b.created_at - a.created_at));
    request.onerror = () => resolve(readSavedVoiceProfiles());
  });
}

async function persistSavedVoiceProfiles(profiles: SavedVoiceProfile[]) {
  try {
    window.localStorage.setItem("fantasee.voice.profiles", JSON.stringify(profiles.map(({ voice_sample: _sample, ...profile }) => profile)));
  } catch {
    // IndexedDB below is the durable path for larger clone samples.
  }
  const db = await openVoiceProfileDb();
  if (!db) return;
  await new Promise<void>((resolve) => {
    const transaction = db.transaction(voiceProfileStoreName, "readwrite");
    const store = transaction.objectStore(voiceProfileStoreName);
    store.clear();
    profiles.forEach((profile) => store.put(profile));
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => resolve();
    transaction.onabort = () => resolve();
  });
}

function readStudioUiState(): StudioUiState {
  if (typeof window === "undefined") return {};
  try {
    const saved = window.localStorage.getItem("fantasee.studio.ui");
    return saved ? JSON.parse(saved) as StudioUiState : {};
  } catch {
    return {};
  }
}

function telemetrySourceLabel(source?: string) {
  return ({
    "windows-gpu-engine": "Windows GPU engine",
    "windows-process": "Windows process counter",
    "psutil-process": "psutil process counter",
    "nvidia-smi": "nvidia-smi",
  } as Record<string, string>)[source || ""] || "Telemetry unavailable";
}

function timestamp(value?: string | number) {
  if (!value) return "Awaiting date";
  const date = new Date(typeof value === "number" && value < 10_000_000_000 ? value * 1000 : value);
  return Number.isNaN(date.valueOf()) ? "Awaiting date" : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function humanStatus(status: string) {
  return status.replaceAll("_", " ").replace(/^./, (value) => value.toUpperCase());
}

function jobStoryName(job: ProductionJob) {
  return job.story_name || job.story_id || "Story context pending";
}

function productionRunPhase(run: ProductionRun) {
  const status = String(run.status || "").toLowerCase();
  const stage = String(run.stage || "").toLowerCase();
  const message = String(run.message || "").toLowerCase();
  const failed = ["error", "failed", "cancelled"].includes(status);
  const active = ["running", "leased"].includes(status);
  const queued = ["queued", "retryable"].includes(status);
  const finished = ["done", "succeeded", "complete"].includes(status);
  const renderStage = stage.includes("render") || message.includes("render");
  const outlineStage = stage.includes("outline") || message.includes("outline");
  const sceneStage = stage.includes("scene");
  const bibleStage = stage.includes("bible");

  if (finished) {
    if (renderStage) return "Rendered and complete";
    return "Completed";
  }
  if (failed) {
    if (renderStage) return "Failed during render";
    if (outlineStage) return "Failed before scene outline";
    if (sceneStage) return "Failed while generating scenes";
    if (bibleStage) return "Failed while writing the story bible";
    return "Failed before render";
  }
  if (active) {
    if (renderStage) return "Rendering video";
    if (outlineStage) return "Building the scene outline";
    if (bibleStage) return "Writing the story bible";
    if (sceneStage) return "Generating scenes";
    return "Generating story";
  }
  if (queued) {
    if (renderStage) return "Queued for render";
    if (outlineStage) return "Queued for outline";
    if (sceneStage) return "Queued for scenes";
    return "Waiting in queue";
  }
  return humanStatus(run.status || run.kind);
}

function productionRunNote(run: ProductionRun) {
  const status = String(run.status || "").toLowerCase();
  const phase = productionRunPhase(run);
  const renderStage = String(run.stage || "").toLowerCase().includes("render") || String(run.message || "").toLowerCase().includes("render");
  const outlineStage = String(run.stage || "").toLowerCase().includes("outline") || String(run.message || "").toLowerCase().includes("outline");

  if (["done", "succeeded", "complete"].includes(status)) {
    return renderStage ? "The render is finished and ready for release checks." : "The run finished and can feed the next release step.";
  }
  if (["error", "failed", "cancelled"].includes(status)) {
    if (renderStage) return `${phase}. The pipeline reached render work before stopping.`;
    if (outlineStage) return `${phase}. The run stopped before MP4 rendering started.`;
    return `${phase}. The run did not reach the render stage.`;
  }
  if (["running", "leased"].includes(status)) {
    if (renderStage) return "The pipeline is rendering video now.";
    if (outlineStage) return "The pipeline is still building story structure, not rendering yet.";
    return "The pipeline is still generating story assets, not rendering yet.";
  }
  if (["queued", "retryable"].includes(status)) {
    if (renderStage) return "Queued for the render stage.";
    return "Waiting for a worker to pick up the next stage.";
  }
  return "The run is waiting for the next durable update.";
}

function eventIndicator(event: ProductionEvent, latestSequence: number, runStatus: string, hasActiveJob: boolean) {
  const payloadStatus = String(event.payload.status || "").toLowerCase();
  if (event.event_type === "task.finished") {
    return payloadStatus === "succeeded" ? { tone: "green", label: "complete" } : { tone: "red", label: payloadStatus || "failed" };
  }
  if (event.event_type === "task.job_queued") return { tone: "amber", label: "queued" };
  if (event.event_type === "task.job_updated") {
    if (["succeeded", "complete"].includes(payloadStatus)) return { tone: "green", label: "complete" };
    if (["failed", "cancelled"].includes(payloadStatus)) return { tone: "red", label: payloadStatus };
    if (["running", "leased"].includes(payloadStatus)) return { tone: "blue", label: "active" };
    return { tone: "amber", label: payloadStatus || "waiting" };
  }
  if (event.event_type === "task.progress" && event.sequence === latestSequence && runStatus === "running") {
    return { tone: "blue", label: hasActiveJob ? "active" : "latest reported" };
  }
  if (event.event_type === "task.started") return { tone: "muted", label: "recorded" };
  return { tone: "muted", label: "history" };
}

function completionRows(story?: Story) {
  const completion = story?.completion ?? {};
  const counts = (completion.counts as Record<string, number> | undefined) ?? {};
  const scenes = counts.scenes ?? story?.scene_count ?? 0;
  const ready = (key: string) => scenes > 0 && counts[key] === scenes;
  const issues = Array.isArray(completion.issues) ? completion.issues as Array<{ kind?: string; message?: string }> : [];
  const finding = (...kinds: string[]) => issues.find((issue) => kinds.includes(String(issue.kind)))?.message;
  const imageReady = ready("scenes_with_images");
  const narrationReady = ready("scenes_with_audio");
  const subtitleReady = ready("scenes_with_subtitles");
  const media = [
    [Image, "Images", imageReady, imageReady ? `${counts.scenes_with_images ?? 0}/${scenes || "--"} scenes` : finding("image", "shot_image") || `${counts.scenes_with_images ?? 0}/${scenes || "--"} scenes`],
    [Volume2, "Narration", narrationReady, narrationReady ? `${counts.scenes_with_audio ?? 0}/${scenes || "--"} tracks` : finding("audio") || `${counts.scenes_with_audio ?? 0}/${scenes || "--"} tracks`],
    [Archive, "Subtitles", subtitleReady, subtitleReady ? `${counts.scenes_with_subtitles ?? 0}/${scenes || "--"} timed` : finding("subtitles") || `${counts.scenes_with_subtitles ?? 0}/${scenes || "--"} timed`],
    [Gauge, "Timeline", Boolean(completion.complete), completion.complete ? "canonical" : finding("shot_timeline") || "final pass pending"],
    [Clapperboard, "MP4", Boolean(completion.full_video_ok), completion.full_video_ok ? "master verified" : finding("scene_video", "full_video") || "master pending"],
    [ChevronRight, "Plex", Boolean(completion.plex_video_ok), completion.plex_video_ok ? "export verified" : finding("plex") || "export pending"],
  ] as const;
  return media;
}

function hasUsableCover(story: Story) {
  const counts = (story.completion?.counts as Record<string, number> | undefined) ?? {};
  return Boolean(story.cover_image_url || story.hero_image) && (counts.scenes === undefined || counts.scenes_with_images > 0);
}

function storyHealth(story: Story) {
  const completion = story.completion ?? {};
  if (completion.complete) return { text: "Ready", tone: "ready" };
  const names: Record<string, string> = { story_text: "script", image: "images", shot_image: "shot art", audio: "audio", subtitles: "subtitles", shot_timeline: "timeline", scene_video: "scene MP4", full_video: "master MP4", plex: "Plex" };
  const missing = Array.isArray(completion.missing) ? completion.missing.map((value) => names[String(value)] || String(value)).slice(0, 3) : [];
  return { text: missing.length ? `Needs ${missing.join(" · ")}` : "Needs completion", tone: "attention" };
}

function workerLabel(worker: Worker | ComfyWorker) {
  const comfy = worker as ComfyWorker;
  const production = worker as Worker;
  if (comfy.kind === "gpu") return "GPU worker";
  if (comfy.kind === "cpu") return "CPU worker";
  if (comfy.device) return comfy.device.toUpperCase().includes("GPU") ? "GPU worker" : "CPU worker";
  if (production.capabilities?.includes("gpu")) return "GPU worker";
  return "CPU worker";
}

function workerIdentity(worker: Worker | ComfyWorker) {
  return (worker as ComfyWorker).url || (worker as Worker).id || "ComfyUI worker";
}

function metricPercent(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? Math.round(Math.max(0, Math.min(100, value))) : undefined;
}

function runLedTone(status: string) {
  if (["done", "succeeded"].includes(status)) return "green";
  if (["error", "failed", "cancelled"].includes(status)) return "red";
  if (["running", "leased"].includes(status)) return "blue";
  return "amber";
}

function runWorkerSummary(run: ProductionRun) {
  const workers = run.worker_ids?.length
    ? run.worker_ids
    : run.worker_id
      ? [run.worker_id]
      : [];
  if (workers.length) return { label: `Working · ${workers.join(", ")}`, tone: "green", live: true };
  if (["running", "leased"].includes(run.status)) return { label: "Working · Studio pipeline", tone: "blue", live: true };
  if (["queued", "retryable"].includes(run.status)) return { label: "Waiting for a worker", tone: "amber", live: false };
  return { label: "No active worker", tone: runLedTone(run.status), live: false };
}

function jobWorkerLabel(job: ProductionJob) {
  if (job.worker_id) return `Working · ${job.worker_id}`;
  if (["queued", "retryable"].includes(job.status)) return "Waiting for a worker";
  if (["leased", "running"].includes(job.status)) return "Worker identity pending";
  return "No active worker";
}

function UsageLeds({ label, value, source }: { label: string; value?: number | null; source?: string }) {
  const percent = metricPercent(value);
  const ledCount = percent === undefined ? 0 : Math.round(percent / 100 * 18);
  const description = percent === undefined ? `${label} usage unavailable` : `${label} usage ${percent}%`;
  return <div className="usage-strip" title={description}><span>{label}</span><div className={percent === undefined ? "level-meter unavailable" : "level-meter"} aria-label={description}>{Array.from({ length: 18 }, (_, index) => <i key={index} className={index < ledCount ? "lit" : ""}/>)}</div><b>{percent === undefined ? "--" : `${percent}%`}</b><small>{percent === undefined ? "Unavailable" : telemetrySourceLabel(source)}</small></div>;
}

export function App() {
  const [stories, setStories] = useState<Story[]>([]);
  const [runs, setRuns] = useState<ProductionRun[]>([]);
  const [generationTasks, setGenerationTasks] = useState<GenerationTask[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [comfyWorkers, setComfyWorkers] = useState<ComfyWorker[]>([]);
  const [selectedStoryId, setSelectedStoryId] = useState<string | undefined>(() => readStudioUiState().selectedStoryId);
  const [detailStoryId, setDetailStoryId] = useState<string>();
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>(() => readStudioUiState().selectedRunId);
  const [jobs, setJobs] = useState<ProductionJob[]>([]);
  const [events, setEvents] = useState<ProductionEvent[]>([]);
  const [query, setQuery] = useState(() => readStudioUiState().query || "");
  const [notice, setNotice] = useState("Connecting to the production ledger...");
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [worldTemplateId, setWorldTemplateId] = useState("current");
  const [editorOpen, setEditorOpen] = useState(false);
  const [playerOpen, setPlayerOpen] = useState(false);
  const [playerRelease, setPlayerRelease] = useState<ProductionRelease>();
  const [workersOpen, setWorkersOpen] = useState(false);
  const [activeView, setActiveView] = useState(() => {
    const savedView = readStudioUiState().activeView;
    return savedView === "Workers" ? "Library" : savedView === "Productions" ? "Production Runs" : savedView || "Library";
  });
  const [editorStory, setEditorStory] = useState<StoryDetail>();
  const [editorScene, setEditorScene] = useState(0);
  const [brief, setBrief] = useState<GenerateInput>({ story_concept: "", style: "comic book panels", num_scenes: 5, images_per_scene: 5, characters: "", tone: "dramatic", voice_preset: "Dean", narration_style: "" });
  const [world, setWorld] = useState<WorldKnowledgeBase>(() => readWorldKnowledge());
  const [seeds, setSeeds] = useState<SeedSuggestion[]>([]);
  const [directionDrafts, setDirectionDrafts] = useState<ProductionDirection[]>([]);
  const [activeDirectionId, setActiveDirectionId] = useState<string>();
  const [seedBusy, setSeedBusy] = useState(false);
  const [admissionPaused, setAdmissionPaused] = useState(false);
  const [renderingMode, setRenderingMode] = useState<RenderingMode>("gpu");

  useEffect(() => {
    void api.settings().then((settings) => {
      setBrief((current) => current.story_concept.trim() ? current : {
        ...current,
        style: settings.default_visual_style || "comic book panels",
        tone: settings.default_tone || current.tone,
        num_scenes: settings.default_scenes || current.num_scenes,
        images_per_scene: settings.default_images_per_scene || current.images_per_scene,
        voice_preset: settings.tts_voice_preset || current.voice_preset,
        narration_style: settings.narration_style || current.narration_style,
      });
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem("fantasee.studio.ui", JSON.stringify({ activeView, selectedStoryId, selectedRunId, query }));
    } catch {
      // Private browsing or a locked-down profile may disable local storage.
    }
  }, [activeView, selectedStoryId, selectedRunId, query]);

  useEffect(() => {
    try { window.localStorage.setItem("fantasee.world.knowledge", JSON.stringify(world)); }
    catch { /* Keep the editor usable when browser storage is unavailable. */ }
  }, [world]);

  const refreshCore = async () => {
    try {
      const [storyResult, runResult, taskResult, controlResult] = await Promise.all([
        api.stories(), api.runs(), api.generationTasks(), api.productionControl().catch(() => ({ admission_paused: false, rendering_mode: "gpu" as RenderingMode })),
      ]);
      const sortedStories = [...storyResult.stories].sort((a, b) => Number(b.updated_at || b.created_at || 0) - Number(a.updated_at || a.created_at || 0));
      setStories(sortedStories);
      const visibleRuns = runResult.runs.filter((run) => !run.kind.includes("library_story"));
      setRuns(visibleRuns);
      setGenerationTasks(taskResult.tasks || []);
      setAdmissionPaused(controlResult.admission_paused);
      setRenderingMode(controlResult.rendering_mode);
      setSelectedStoryId((current) => current && sortedStories.some((story) => story.id === current) ? current : sortedStories[0]?.id);
      setSelectedRunId((current) => current && visibleRuns.some((run) => run.id === current) ? current : visibleRuns[0]?.id);
      setNotice("Production ledger is live.");
    } catch (error) {
      setNotice(error instanceof Error ? `Connection issue: ${error.message}` : "Connection issue.");
    }
  };

  const refreshWorkers = async () => {
    const [workerResult, comfyResult] = await Promise.allSettled([api.workers(), api.comfyWorkers()]);
    if (workerResult.status === "fulfilled") setWorkers(workerResult.value.workers);
    if (comfyResult.status === "fulfilled") setComfyWorkers(comfyResult.value.workers || []);
    // Keep each last good worker sample visible while the other endpoint recovers.
  };

  const refresh = async () => {
    const coreRefresh = refreshCore();
    void refreshWorkers();
    if (selectedRunId) {
      void api.run(selectedRunId).then((result) => setJobs(result.jobs)).catch(() => undefined);
    }
    await coreRefresh;
  };

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), 4_000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => void refreshWorkers(), 4_000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!selectedRunId) { setJobs([]); setEvents([]); return; }
    const loadJobs = () => api.run(selectedRunId).then((result) => setJobs(result.jobs)).catch(() => setJobs([]));
    void loadJobs();
    const interval = window.setInterval(() => void loadJobs(), 4_000);
    setEvents([]);
    return () => window.clearInterval(interval);
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedRunId) return;
    let cursor = 0;
    let active = true;
    const loadEvents = async () => {
      try {
        const result = await api.events(selectedRunId, cursor);
        if (!active) return;
        cursor = result.next_sequence;
        if (result.events.length) setEvents((current) => [...current, ...result.events].slice(-80));
      } catch {
        // The summary poll remains authoritative while the event stream reconnects.
      }
    };
    void loadEvents();
    const interval = window.setInterval(() => void loadEvents(), 2500);
    return () => { active = false; window.clearInterval(interval); };
  }, [selectedRunId]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (createOpen) setCreateOpen(false);
      if (editorOpen) setEditorOpen(false);
      if (playerOpen) { setPlayerOpen(false); setPlayerRelease(undefined); }
      if (workersOpen) setWorkersOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [createOpen, editorOpen, playerOpen, workersOpen]);

  const selectedStory = stories.find((story) => story.id === selectedStoryId);
  const detailStory = stories.find((story) => story.id === detailStoryId);
  const selectedRun = runs.find((run) => run.id === selectedRunId);
  const regenerationTask = selectedStory
    ? generationTasks
      .filter((task) => task.kind === "regenerate" && task.story_id === selectedStory.id)
      .sort((left, right) => Number(right.updated_at || right.created_at || 0) - Number(left.updated_at || left.created_at || 0))
      .at(0)
    : undefined;
  const visibleStories = stories.filter((story) => story.title.toLowerCase().includes(query.toLowerCase()));
  const activeWorkers = [...workers, ...comfyWorkers].filter((worker) => (worker as Worker).status !== "stale" && (worker as ComfyWorker).running !== false);
  const activeComfyWorkers = comfyWorkers.filter((worker) => worker.running !== false);
  const sidebarWorkers = activeComfyWorkers;
  const productionActivity = projectProductionActivity(generationTasks, workers);
  const gpuWorkingCount = activeComfyWorkers.filter((worker) => (worker.queue_running || 0) > 0).length;
  const productionStatus = productionActivity.workingRoles
    ? `${productionActivity.workingRoles} production role${productionActivity.workingRoles === 1 ? "" : "s"} working`
    : productionActivity.activities.length
      ? `${productionActivity.activities.length} production role${productionActivity.activities.length === 1 ? "" : "s"} waiting`
      : "Production idle";
  const gpuStatus = activeComfyWorkers.length
    ? `GPU ${gpuWorkingCount ? "busy" : "idle"} (${activeComfyWorkers.length} online)`
    : "GPU offline";
  const workerSummary = `${productionStatus} · ${gpuStatus}`;

  const runAction = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try { await action(); setNotice(message); await refresh(); }
    catch (error) { setNotice(error instanceof Error ? error.message : "The control request did not complete."); }
    finally { setBusy(false); }
  };

  const restartEverything = async () => {
    if (!window.confirm("Restart the Studio app and all local ComfyUI workers? Active jobs will recover from durable state after restart.")) return;
    setBusy(true);
    try {
      const result = await api.restartEverything(renderingMode);
      setNotice(`${result.message} Mode: ${renderingMode}. Reconnecting after restart...`);
    } catch (error) {
      setBusy(false);
      setNotice(error instanceof Error ? error.message : "The full restart could not be requested.");
    }
  };

  const queueProductions = async (inputs: GenerateInput[], worldContext = world) => {
    if (inputs.some((input) => input.story_concept.trim().length < 10)) { setNotice("Give each selected direction at least a sentence of story intent."); return; }
    const validInputs = inputs;
    setBusy(true);
    try {
      const payloads = validInputs.map((input) => ({
        ...input,
        world_context: worldContextPrompt(worldContext),
        voice_assignments: JSON.stringify(worldContext.characters.map((character) => ({
          name: character.name,
          role: character.role,
          voice: character.voice,
          style: character.style,
          alignment: character.alignment,
          traits: character.traits,
        }))),
      }));
      const result = payloads.length > 1
        ? await api.generateQueue(payloads)
        : await api.generate(payloads[0]);
      const queuedId = "queue_id" in result ? result.queue_id : result.task_id;
      setCreateOpen(false);
      setDirectionDrafts([]);
      setSeeds([]);
      setSelectedRunId(queuedId);
      setNotice(`${payloads.length} production${payloads.length === 1 ? "" : "s"} entered the durable queue.`);
      await refresh();
    } catch (error) { setNotice(error instanceof Error ? error.message : "The production brief could not be queued."); }
    finally { setBusy(false); }
  };

  const queueBrief = async (worldContext = world) => queueProductions([brief], worldContext);

  const regenerateSelectedStory = async () => {
    if (!selectedStory) return;
    if (!window.confirm(`Regenerate ${selectedStory.title} from its saved direction? The current production will be backed up before the new run starts.`)) return;
    setBusy(true);
    try {
      const result = await api.regenerateStory(selectedStory.id, true);
      setNotice(`${result.message} Detailed progress and completion evidence will update here as the run advances.`);
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Story regeneration could not be started.");
    } finally {
      setBusy(false);
    }
  };

  const submitBrief = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const template = worldTemplates.find((item) => item.id === worldTemplateId);
    const templateWorld = template && "world" in template ? template.world : undefined;
    const selectedWorld = templateWorld || world;
    if (templateWorld) setWorld({ ...templateWorld });
    const selectedDirections = directionDrafts.filter((direction) => direction.selected).map((direction) => direction.input);
    await queueProductions(selectedDirections.length ? selectedDirections : [brief], selectedWorld);
  };

  const suggestSeeds = async () => {
    if (brief.story_concept.trim().length < 10) { setNotice("Give the seed picker at least a sentence of story intent."); return; }
    setSeedBusy(true);
    try {
      const result = await api.seedSuggestions(brief);
      const drafts = result.seeds.map((seed, index) => directionFromSeed(seed, index, brief));
      setSeeds(result.seeds);
      setDirectionDrafts(drafts);
      setActiveDirectionId(drafts[0]?.id);
      setNotice("Three story directions are ready. Select, tune, and queue any combination.");
    }
    catch (error) { setNotice(error instanceof Error ? error.message : "Seed suggestions could not be generated."); }
    finally { setSeedBusy(false); }
  };

  const openEditor = async () => {
    if (!selectedStory) return;
    setEditorOpen(true);
    setEditorScene(0);
    try { setEditorStory(await api.story(selectedStory.id)); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not load the story editor."); }
  };

  const openCanonicalPlayer = async (story?: Story) => {
    if (!story) return;
    try {
      const result = await api.releases(story.id);
      const release = selectPlayableRelease(result.releases);
      if (!release) throw new Error("This story has no verified release to play yet.");
      setPlayerRelease(release);
      setPlayerOpen(true);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not load the current release.");
    }
  };

  return <main className="studio-shell">
    <aside className="rail">
      <div className="rail-header">
        <div className="brand"><img src="branding/fantasee-studio-banner.png" alt="FantaSee Studio" /></div>
        <nav>{nav.map(([Icon, label]) => <button className={label === activeView ? "nav-item active" : "nav-item"} key={label} onClick={() => { setActiveView(label); setNotice(`${label} desk selected.`); }} aria-current={label === activeView ? "page" : undefined}><Icon size={19}/><span>{label}</span><i>{label === activeView ? "" : undefined}</i></button>)}</nav>
      </div>
      <section className="rail-activity" aria-label="Production activity"><div className="rail-section-title"><span>Production activity</span><small>{productionActivity.workingRoles} working</small></div><div className="rail-activity-stack">{productionActivity.activities.length ? productionActivity.activities.slice(0, 3).map((activity) => <ProductionActivityLane key={activity.id} activity={activity}/>) : <div className="rail-activity-empty"><span className="led muted"/><div><strong>No production roles active</strong><small>Queued work will appear here with its real stage.</small></div></div>}</div></section>
      <section className="rail-workers" aria-label="ComfyUI workers"><div className="rail-section-title"><span>Render hardware</span><small>{sidebarWorkers.length} GPU online</small></div><div className="rail-worker-stack">{sidebarWorkers.length ? sidebarWorkers.map((worker, index) => { const comfyUrl = (worker as ComfyWorker).url; return <WorkerLane key={`${workerIdentity(worker)}-${index}`} worker={worker} jobs={[]} busy={busy} onSpawn={() => void runAction(() => api.spawn("gpu"), "GPU ComfyUI worker started.")} onKill={comfyUrl ? () => void runAction(() => api.killComfy(comfyUrl), "Selected ComfyUI worker stopped.") : undefined}/>; }) : <WorkerLane empty jobs={[]} busy={busy} onSpawn={() => void runAction(() => api.spawn("gpu"), "GPU ComfyUI worker started.")}/>}</div></section>
      <div className="rail-status"><span><span className="led green"/> {notice}</span><small>{workerSummary}</small></div>
    </aside>

    <section className="workspace">
      <header className="command-bar"><label><Search size={19}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search stories..." /></label><div><button className="icon-button" onClick={() => void refresh()} aria-label="Refresh"><RefreshCw size={18}/></button><button className="create" onClick={() => setCreateOpen(true)}><Plus size={17}/> Create story</button><button className="icon-button" onClick={() => setWorkersOpen(true)} aria-label="Open worker controls" title="Worker controls"><MoreHorizontal size={19}/></button></div></header>
      <div className="status-strip"><span className="led green"/> {notice} <span>•</span> {workerSummary}</div>
      {activeView === "Library" ? <><div className={detailStory ? "library-details-layer open" : "library-details-layer"}>{detailStory && <StoryDetails story={detailStory} onBack={() => setDetailStoryId(undefined)} onOpenEditor={() => void openEditor()} onPlay={() => void openCanonicalPlayer(detailStory)} onDeleted={() => { setDetailStoryId(undefined); setSelectedStoryId(undefined); void refresh(); }} />}</div><div className="content-grid">
        <section className="library-module metal-panel">
          <div className="eyebrow"><span>Featured story</span><span>Newest first</span></div>
          {selectedStory ? <article className="feature">
            <div className="cover">{hasUsableCover(selectedStory) ? <img src={selectedStory.cover_image_url || selectedStory.hero_image} alt=""/> : <Sparkles size={34}/>}</div>
            <div><h1>{selectedStory.title}</h1><p>{selectedStory.description || "A new production, ready for its editorial pass."}</p><div className="story-meta">{selectedStory.scene_count || 0} scenes <span/> updated {timestamp(selectedStory.updated_at || selectedStory.created_at)}</div><div className="feature-actions"><button className="outline-button" onClick={() => void openEditor()}>Open in editor <ChevronRight size={16}/></button><button className="outline-button" disabled={!selectedStory.completion?.full_video_ok} onClick={() => void openCanonicalPlayer(selectedStory)}><Play size={15}/> Play release</button><button className="outline-button" disabled={busy} onClick={() => void runAction(() => api.generateStoryThumbnail(selectedStory.id), `Story card art requested for ${selectedStory.title}.`)}><Image size={15}/> {busy ? "Painting..." : "Generate card art"}</button></div></div>
          </article> : <div className="empty-state"><Sparkles size={28}/><h1>No stories yet</h1><p>Create a story to establish the first production run.</p></div>}
          <div className="section-heading"><h2>Story library</h2><span>{visibleStories.length} title{visibleStories.length === 1 ? "" : "s"}</span></div>
          <LibraryCatalog stories={visibleStories} selectedStoryId={selectedStoryId} onSelectStory={(story) => setSelectedStoryId(story.id)} onOpenStory={(story) => { setSelectedStoryId(story.id); setDetailStoryId(story.id); }} />
          <div className="story-list">{visibleStories.map((story) => <button key={story.id} className={story.id === selectedStoryId ? "story-row selected" : "story-row"} onClick={() => setSelectedStoryId(story.id)}>
            <span className="star">{story.id === selectedStoryId ? "+" : "o"}</span><span className="thumb">{hasUsableCover(story) ? <img src={story.cover_image_url || story.hero_image} alt="" onError={(event) => { event.currentTarget.style.display = "none"; }}/> : null}<Image className="fallback-icon" size={15}/></span><strong>{story.title}</strong><span className={`story-health ${storyHealth(story).tone}`}>{storyHealth(story).text}</span><span>{story.scene_count || 0} scenes</span><span>{timestamp(story.updated_at || story.created_at)}</span><ChevronRight size={17}/>
          </button>)}</div>
        </section>

        <aside className="inspector metal-panel">
          <div className="eyebrow"><span>Production run</span>{selectedStory && <button type="button" className="run-regenerate-button" disabled={busy || regenerationTask?.status === "running"} onClick={() => void regenerateSelectedStory()}><span className={`led ${regenerationTask?.status === "running" ? "blue live" : "amber"}`}/>{regenerationTask?.status === "running" ? "Regenerating" : "Regenerate"}</button>}<span className={`run-state ${selectedRun?.status || "idle"}`}>{humanStatus(selectedRun?.status || "idle")}</span></div>
          {selectedRun ? <><div className="run-summary"><span className={`led ${runLedTone(selectedRun.status)} ${runWorkerSummary(selectedRun).live ? "live" : ""}`}/> <small>{selectedRun.id}</small><h2>{selectedStory?.title || selectedRun.story_id || "Library maintenance"}</h2><p>{productionRunPhase(selectedRun)}</p><small className="run-summary-note">{productionRunNote(selectedRun)}</small><div className="run-worker-summary"><span className={`led ${runWorkerSummary(selectedRun).tone} ${runWorkerSummary(selectedRun).live ? "live" : ""}`}/><span>{runWorkerSummary(selectedRun).label}</span></div><div className="progress-track"><i style={{width: `${Math.round((selectedRun.progress || 0) * 100)}%`}}/></div><b>{Math.round((selectedRun.progress || 0) * 100)}% complete</b></div>
          {regenerationTask && <div className={`regeneration-progress ${regenerationTask.status === "error" ? "error" : regenerationTask.status === "done" ? "complete" : "active"}`}><div><span className={`led ${regenerationTask.status === "error" ? "red" : regenerationTask.status === "done" ? "green" : "blue live"}`}/><strong>{regenerationTask.status === "done" ? "Regeneration complete" : regenerationTask.status === "error" ? "Regeneration stopped" : `Regenerating · ${Math.round((regenerationTask.progress || 0) * 100)}%`}</strong><small>{regenerationTask.stage || "pipeline"}</small></div><p>{regenerationTask.message || "The durable pipeline is reporting its next step."}</p></div>}
          <div className="completion"><h3>Completion evidence</h3>{completionRows(selectedStory).map(([Icon, label, complete, detail]) => <div className="completion-row" key={label}><Icon size={18}/><span>{label}</span><small>{complete ? "verified" : regenerationTask?.status === "running" ? "building" : "pending"} · {detail}</small><i className={complete ? "led green live" : regenerationTask?.status === "running" ? "led blue live" : "led amber"}/></div>)}</div>
          <div className="run-controls"><h3>Run controls</h3><button disabled={busy} className="outline-button" onClick={() => void runAction(async () => { const result = await api.setProductionControl({ admission_paused: !admissionPaused }); setAdmissionPaused(result.admission_paused); }, admissionPaused ? "Queue admission resumed." : "Queue admission paused.")}>{admissionPaused ? "Resume queue admission" : "Pause new jobs"}</button><div className="queue-priority-panel"><span>Queue priority</span>{jobs.filter((job) => ["queued", "retryable"].includes(job.status)).map((job) => <div key={job.id}><small>{humanStatus(job.job_type)} · {job.priority ?? 0}</small><button className="micro-button" disabled={busy || (job.priority ?? 0) >= 100} onClick={() => void runAction(() => api.priorityJob(job.id, Math.min(100, (job.priority ?? 0) + 1)), `Raised priority for ${job.id}.`)} title="Raise priority"><ArrowUp size={12}/></button><button className="micro-button" disabled={busy || (job.priority ?? 0) <= 0} onClick={() => void runAction(() => api.priorityJob(job.id, Math.max(0, (job.priority ?? 0) - 1)), `Lowered priority for ${job.id}.`)} title="Lower priority"><ArrowDown size={12}/></button></div>)}</div><button disabled={busy || jobs.length === 0} className="danger" onClick={() => jobs[0] && void runAction(() => api.cancelJob(jobs[0].id), "Cancellation requested for the current job.")}><Pause size={17}/> Pause / cancel</button><button disabled={busy || jobs.length === 0} className="outline-button" onClick={() => jobs[0] && void runAction(() => api.retryJob(jobs[0].id), "The current job has been returned to the durable queue.")}><RefreshCw size={16}/> Retry</button></div>
          <details className="run-details"><summary><span>Job ledger</span><small>{jobs.length ? `${jobs.length} item${jobs.length === 1 ? "" : "s"}` : "empty"}</small></summary><div className="job-ledger">{jobs.length ? jobs.map((job) => <div className="job-row" key={job.id}><div><span className={`led ${runLedTone(job.status)} ${job.worker_id ? "live" : ""}`}/><strong>{humanStatus(job.job_type)}</strong><small className="job-story">{jobStoryName(job)}</small><small>{job.message || humanStatus(job.status)} · attempt {job.attempts + 1}</small><small className="job-worker"><span className={`led ${job.worker_id ? "green live" : runLedTone(job.status)}`}/>{jobWorkerLabel(job)}</small></div><div className="job-controls">{job.status !== "succeeded" && <button className="micro-button" disabled={busy} onClick={() => void runAction(() => api.retryJob(job.id), `Job ${job.id} queued for retry.`)} title="Retry this job"><RefreshCw size={13}/></button>}{["queued", "running"].includes(job.status) && <button className="micro-button" disabled={busy} onClick={() => void runAction(() => api.cancelJob(job.id), `Cancellation requested for job ${job.id}.`)} title="Cancel this job"><X size={13}/></button>}</div></div>) : <p className="ledger-empty">No durable jobs have been recorded for this run yet.</p>}</div></details><details className="run-details"><summary><span>Live event spool</span><small>{events.length ? `${events.length} events` : "empty"}</small></summary><div className="event-spool"><p className="event-spool-help">Newest is at the top. Blue is the latest report, amber is waiting, green is terminal success, and dim is history. A blue event is active only when the job ledger says running.</p><JobPriorityQueue jobs={jobs} busy={busy} onPriority={(job, priority) => void runAction(() => api.priorityJob(job.id, priority), `Updated priority for ${jobStoryName(job)}.`)} />{events.length ? events.slice().reverse().slice(0, 10).map((event) => { const indicator = eventIndicator(event, events[events.length - 1].sequence, selectedRun.status, jobs.some((job) => ["leased", "running"].includes(job.status))); return <div className="event-row" key={`${event.sequence}-${event.event_type}`}><span className={`led ${indicator.tone}`}/><small>#{event.sequence} {event.event_type} · {indicator.label}</small><strong>{String(event.payload.message || event.payload.stage || "Recorded production event")}</strong></div>; }) : <p className="ledger-empty">Waiting for durable progress events.</p>}</div></details></> : <div className="empty-state"><Radio size={25}/><p>No production run selected.</p></div>}
        {selectedRun && <RunControls renderingMode={renderingMode} admissionPaused={admissionPaused} busy={busy} jobs={jobs} onToggleAdmission={() => void runAction(async () => { const result = await api.setProductionControl({ admission_paused: !admissionPaused }); setAdmissionPaused(result.admission_paused); }, admissionPaused ? "Queue admission resumed." : "Queue admission paused.")} onRenderingMode={(mode) => void runAction(async () => { const result = await api.setProductionControl({ rendering_mode: mode }); setRenderingMode(result.rendering_mode); }, `Rendering mode set to ${mode === "basic" ? "Basic / CPU" : mode === "gpu" ? "GPU" : "Max / GPU + CPU"}.`)} onPriority={(job, priority) => void runAction(() => api.priorityJob(job.id, priority), `Updated priority for ${job.id}.`)} onCancel={() => jobs[0] && void runAction(() => api.cancelJob(jobs[0].id), "Cancellation requested for the current job.")} onRetry={() => jobs[0] && void runAction(() => api.retryJob(jobs[0].id), "The current job has been returned to the durable queue.")} />}
        </aside>
      </div>
      <section className="worker-deck">{activeWorkers.length ? activeWorkers.slice(0, 2).map((worker, index) => {
        const comfyUrl = (worker as ComfyWorker).url;
        return <WorkerLane key={index} worker={worker} jobs={jobs} busy={busy} onSpawn={() => void runAction(() => api.spawn(index ? "cpu" : "gpu"), `${index ? "CPU" : "GPU"} ComfyUI worker started.`)} onKill={comfyUrl ? () => void runAction(() => api.killComfy(comfyUrl), "Selected ComfyUI worker stopped.") : undefined}/>;
      }) : <WorkerLane empty jobs={jobs} busy={busy} onSpawn={() => void runAction(() => api.spawn("gpu"), "GPU ComfyUI worker started.")}/>}</section></> : <StudioDesk view={activeView} stories={stories} runs={runs} workers={activeWorkers} selectedStory={selectedStory} jobs={jobs} busy={busy} brief={brief} onBriefChange={setBrief} world={world} onWorldChange={setWorld} seeds={seeds} seedBusy={seedBusy} onSuggestSeeds={() => void suggestSeeds()} onQueueBrief={() => void queueBrief()} onSpawn={(kind) => void runAction(() => api.spawn(kind), `${kind.toUpperCase()} ComfyUI worker started.`)} onRefresh={() => void refresh()} onSelectRun={(id) => { setSelectedRunId(id); setActiveView("Library"); setNotice(`Run ${id} selected.`); }} onSelectStory={setSelectedStoryId} onAction={(action, message) => void runAction(action, message)} onPreviewRelease={(release) => { setPlayerRelease(release); setPlayerOpen(true); }} />}
      {createOpen && <div className="modal-scrim" role="dialog" aria-modal="true" aria-labelledby="brief-modal-title"><form className="brief-modal metal-panel" onSubmit={submitBrief}>
        <div className="eyebrow"><span>New production brief</span><button type="button" className="icon-button" onClick={() => setCreateOpen(false)} aria-label="Close"><X size={17}/></button></div>
        <div className="brief-modal-intro"><div><h2 id="brief-modal-title">Set the story in motion.</h2><p>The director will break this brief into granular scene commissions and complete every media requirement before release.</p></div><span className="brief-modal-step">01 / 03<small>Context first</small></span></div>
        <label className="brief-field world-template-field"><span>Universe / World Builder template</span><select value={worldTemplateId} onChange={(event) => setWorldTemplateId(event.target.value)}>{worldTemplates.map((template) => <option value={template.id} key={template.id}>{template.label} - {template.detail}</option>)}</select><small>The selected canon is attached to this production and becomes the writer's generation context.</small></label>
        <div className="brief-modal-section-label"><span>Creative direction</span><small>Shape the run without overloading the brief.</small></div>
        <label className="brief-field wide">Story intent<textarea autoFocus value={brief.story_concept} onChange={(event) => setBrief({ ...brief, story_concept: event.target.value })} placeholder="A medic from Johannesburg wakes in a cold mountain village where every wound carries a memory..." /><button type="button" className="outline-button seed-button" disabled={seedBusy} onClick={() => void suggestSeeds()}>{seedBusy ? "Consulting director..." : "Suggest three directions"}</button></label>{seeds.length > 0 && <div className="seed-grid">{seeds.map((seed) => <button type="button" className="seed-card" key={`${seed.title}-${seed.description}`} onClick={() => { setBrief({ ...brief, story_concept: `${seed.title}\n${seed.description}`, style: seed.style || brief.style, tone: seed.tone || brief.tone, characters: seed.characters || brief.characters }); setSeeds([]); }}><strong>{seed.title}</strong><small>{seed.description}</small><em>{seed.style || brief.style} · {seed.tone || brief.tone}</em></button>)}</div>}
        {!directionDrafts.length && <>
        <DirectionSettings input={brief} onChange={setBrief} />
        </>}
        {directionDrafts.length > 0 && <DirectionBuilder drafts={directionDrafts} activeId={activeDirectionId} onActive={setActiveDirectionId} onChange={setDirectionDrafts} />}
        {/* Legacy controls remain below for the single-brief path. */}
        <div className="brief-grid direction-legacy-hidden">
          <label className="brief-field">Director preset<select value={directorPresets.find((preset) => preset.style === brief.style && preset.tone === brief.tone)?.id || "custom"} onChange={(event) => { const preset = directorPresets.find((item) => item.id === event.target.value); if (preset) setBrief({ ...brief, style: preset.style, tone: preset.tone, num_scenes: preset.scenes, images_per_scene: preset.images, voice_preset: preset.voice, narration_style: preset.narrationStyle }); }}><option value="custom">Custom direction</option>{directorPresets.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}</select></label>
          <label className="brief-field">Scene count<select value={brief.num_scenes} onChange={(event) => setBrief({ ...brief, num_scenes: Number(event.target.value) })}>{sceneOptions.map((count) => <option key={count} value={count}>{count} scenes · {count <= 5 ? "short arc" : count >= 10 ? "full feature" : "balanced arc"}</option>)}</select></label>
          <label className="brief-field">Visual density<select value={brief.images_per_scene} onChange={(event) => setBrief({ ...brief, images_per_scene: Number(event.target.value) })}>{imageOptions.map((count) => <option key={count} value={count}>{count} beats per scene · {count <= 3 ? "spare" : count >= 9 ? "rich" : "cinematic"}</option>)}</select></label>
          <label className="brief-field">Visual language<select value={brief.style} onChange={(event) => setBrief({ ...brief, style: event.target.value })}>{styleOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="brief-field">Emotional register<select value={brief.tone} onChange={(event) => setBrief({ ...brief, tone: event.target.value })}>{toneOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="brief-field">Narration direction<select value={brief.narration_style || ""} onChange={(event) => setBrief({ ...brief, narration_style: event.target.value })}>{narrationOptions.map(([value, label]) => <option key={value || "default"} value={value}>{label}</option>)}</select></label>
        </div>
        <label className="brief-field wide direction-legacy-hidden-field">Characters and continuity<textarea value={brief.characters} onChange={(event) => setBrief({ ...brief, characters: event.target.value })} placeholder="Optional character, setting, or visual continuity notes." /></label>
        <label className="brief-field wide direction-legacy-hidden-field">Narrator<select value={brief.voice_preset} onChange={(event) => setBrief({ ...brief, voice_preset: event.target.value })}>{voiceOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <div className="modal-actions"><button type="button" className="outline-button" onClick={() => setCreateOpen(false)}>Cancel</button><button className="create" disabled={busy} type="submit"><Plus size={17}/> Queue production</button></div>
      </form></div>}
      {editorOpen && <><StoryEditor story={editorStory} sceneIndex={editorScene} busy={busy} onClose={() => setEditorOpen(false)} onSelectScene={setEditorScene} onStoryRefresh={async () => { if (editorStory) setEditorStory(await api.story(editorStory.id)); }} onAction={(action, message) => void runAction(action, message)} /><SceneImageControls story={editorStory} sceneIndex={editorScene} busy={busy} onStoryRefresh={async () => { if (editorStory) setEditorStory(await api.story(editorStory.id)); }} onAction={(action, message) => void runAction(action, message)} /><SceneWaveformDock story={editorStory} sceneIndex={editorScene} /></>}
      {playerOpen && selectedStory && <ReleasePlayerWithAudio story={selectedStory} release={playerRelease} onClose={() => { setPlayerOpen(false); setPlayerRelease(undefined); }} />}
      {workersOpen && <WorkerConsole workers={comfyWorkers} busy={busy} onClose={() => setWorkersOpen(false)} onRefresh={() => void refresh()} onSpawn={(kind) => void runAction(() => api.spawn(kind), `${kind.toUpperCase()} ComfyUI worker started.`)} onKill={(url) => void runAction(() => api.killComfy(url), "Selected ComfyUI worker stopped.")} onRestart={() => void restartEverything()} />}
    </section>
  </main>;
}

function DirectionSettings({ input, onChange }: { input: GenerateInput; onChange: (input: GenerateInput) => void }) {
  const update = (patch: Partial<GenerateInput>) => onChange({ ...input, ...patch });
  const presetId = directorPresets.find((preset) => preset.style === input.style && preset.tone === input.tone)?.id || "custom";
  return <div className="direction-settings"><div className="direction-settings-heading"><div><span className="eyebrow-label">Selected direction settings</span><h3>Make this version yours</h3></div><small>These settings apply only to the active direction.</small></div><label className="brief-field wide">Story direction<textarea value={input.story_concept} onChange={(event) => update({ story_concept: event.target.value })}/></label><div className="brief-grid"><label className="brief-field">Director preset<select value={presetId} onChange={(event) => { const preset = directorPresets.find((item) => item.id === event.target.value); if (preset) update({ style: preset.style, tone: preset.tone, num_scenes: preset.scenes, images_per_scene: preset.images, voice_preset: preset.voice, narration_style: preset.narrationStyle }); }}><option value="custom">Custom direction</option>{directorPresets.map((preset) => <option value={preset.id} key={preset.id}>{preset.label}</option>)}</select></label><label className="brief-field">Scene count<select value={input.num_scenes} onChange={(event) => update({ num_scenes: Number(event.target.value) })}>{sceneOptions.map((count) => <option key={count} value={count}>{count} scenes - {count <= 5 ? "short arc" : count >= 10 ? "full feature" : "balanced arc"}</option>)}</select></label><label className="brief-field">Visual density<select value={input.images_per_scene} onChange={(event) => update({ images_per_scene: Number(event.target.value) })}>{imageOptions.map((count) => <option key={count} value={count}>{count} beats per scene - {count <= 3 ? "spare" : count >= 9 ? "rich" : "cinematic"}</option>)}</select></label><label className="brief-field">Visual language<select value={input.style} onChange={(event) => update({ style: event.target.value })}>{styleOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="brief-field">Emotional register<select value={input.tone} onChange={(event) => update({ tone: event.target.value })}>{toneOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="brief-field">Narration direction<select value={input.narration_style || ""} onChange={(event) => update({ narration_style: event.target.value })}>{narrationOptions.map(([value, label]) => <option key={value || "default"} value={value}>{label}</option>)}</select></label></div><label className="brief-field wide">Characters and continuity<textarea value={input.characters} onChange={(event) => update({ characters: event.target.value })} placeholder="Optional immediate cast notes; deeper canon comes from the selected worldbuilder." /></label><label className="brief-field wide">Narrator<select value={input.voice_preset} onChange={(event) => update({ voice_preset: event.target.value })}>{voiceOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>;
}

function DirectionBuilder({ drafts, activeId, onActive, onChange }: { drafts: ProductionDirection[]; activeId?: string; onActive: (id: string) => void; onChange: Dispatch<SetStateAction<ProductionDirection[]>> }) {
  return <section className="direction-builder"><div className="direction-builder-heading"><div><span className="eyebrow-label">Parallel production directions</span><h3>Choose the stories to make</h3></div><small>{drafts.filter((direction) => direction.selected).length} of {drafts.length} selected</small></div><div className="direction-picker">{drafts.map((direction) => <article className={direction.id === activeId ? "direction-card active" : "direction-card"} key={direction.id}><button type="button" className="direction-card-select" onClick={() => onActive(direction.id)}><strong>{direction.title}</strong><small>{direction.description}</small><em>{direction.input.style} - {direction.input.tone}</em></button><label className="direction-include"><input type="checkbox" checked={direction.selected} onChange={() => onChange((current) => current.map((item) => item.id === direction.id ? { ...item, selected: !item.selected } : item))}/><span>Queue this story</span></label></article>)}</div>{(() => { const active = drafts.find((direction) => direction.id === activeId) || drafts[0]; return active ? <DirectionSettings input={active.input} onChange={(input) => onChange((current) => current.map((item) => item.id === active.id ? { ...item, input } : item))} /> : null; })()}</section>;
}

function RunControls({ renderingMode, admissionPaused, busy, jobs, onToggleAdmission, onRenderingMode, onPriority, onCancel, onRetry }: { renderingMode: RenderingMode; admissionPaused: boolean; busy: boolean; jobs: ProductionJob[]; onToggleAdmission: () => void; onRenderingMode: (mode: RenderingMode) => void; onPriority: (job: ProductionJob, priority: number) => void; onCancel: () => void; onRetry: () => void }) {
  const queuedJobs = jobs.filter((job) => ["queued", "retryable"].includes(job.status));
  return <div className="run-controls-panel">
    <div className="run-controls-heading"><h3>Run controls</h3><span className={`run-control-state ${admissionPaused ? "paused" : "open"}`}>{admissionPaused ? "Queue paused" : "Queue open"}</span></div>
    <div className="run-control-actions">
      <label className="rendering-mode-control"><span>Rendering</span><select value={renderingMode} onChange={(event) => onRenderingMode(event.target.value as RenderingMode)}><option value="basic">Basic · CPU</option><option value="gpu">GPU</option><option value="max">Max · GPU + CPU</option></select></label>
      <button disabled={busy} className="outline-button" onClick={onToggleAdmission}>{admissionPaused ? "Resume queue" : "Pause new jobs"}</button>
      <span className="queue-priority-inline">{queuedJobs.length ? `${queuedJobs.length} waiting` : "No waiting jobs"}{queuedJobs.slice(0, 1).map((job) => <span key={job.id}><small>{humanStatus(job.job_type)} · {job.priority ?? 0}</small><button className="micro-button" disabled={busy || (job.priority ?? 0) >= 100} onClick={() => onPriority(job, Math.min(100, (job.priority ?? 0) + 1))} title="Raise priority"><ArrowUp size={12}/></button><button className="micro-button" disabled={busy || (job.priority ?? 0) <= 0} onClick={() => onPriority(job, Math.max(0, (job.priority ?? 0) - 1))} title="Lower priority"><ArrowDown size={12}/></button></span>)}</span>
      <button disabled={busy || jobs.length === 0} className="danger" onClick={onCancel}><Pause size={15}/> Pause current</button>
      <button disabled={busy || jobs.length === 0} className="outline-button" onClick={onRetry}><RefreshCw size={15}/> Retry</button>
    </div>
  </div>;
}

function JobPriorityQueue({ jobs, busy, onPriority }: { jobs: ProductionJob[]; busy: boolean; onPriority: (job: ProductionJob, priority: number) => void }) {
  const queuedJobs = jobs.filter((job) => ["queued", "retryable"].includes(job.status));
  if (!queuedJobs.length) return <p className="event-priority-empty">No queued jobs to prioritize.</p>;
  return <div className="event-priority-list"><div className="event-priority-heading"><strong>Queued job priority</strong><small>Higher runs first</small></div>{queuedJobs.map((job) => <div className="event-priority-row" key={job.id}><span><strong>{jobStoryName(job)}</strong><small>{humanStatus(job.job_type)} · priority {job.priority ?? 0}</small></span><span className="job-controls"><button className="micro-button" disabled={busy || (job.priority ?? 0) >= 100} onClick={() => onPriority(job, Math.min(100, (job.priority ?? 0) + 1))} title="Raise priority"><ArrowUp size={12}/></button><button className="micro-button" disabled={busy || (job.priority ?? 0) <= 0} onClick={() => onPriority(job, Math.max(0, (job.priority ?? 0) - 1))} title="Lower priority"><ArrowDown size={12}/></button></span></div>)}</div>;
}

function StudioDesk({ view, stories, runs, workers, selectedStory, jobs, busy, brief, onBriefChange, world, onWorldChange, seeds, seedBusy, onSuggestSeeds, onQueueBrief, onSpawn, onRefresh, onSelectRun, onSelectStory, onAction, onPreviewRelease }: { view: string; stories: Story[]; runs: ProductionRun[]; workers: Array<Worker | ComfyWorker>; selectedStory?: Story; jobs: ProductionJob[]; busy: boolean; brief: GenerateInput; onBriefChange: (brief: GenerateInput) => void; world: WorldKnowledgeBase; onWorldChange: (world: WorldKnowledgeBase) => void; seeds: SeedSuggestion[]; seedBusy: boolean; onSuggestSeeds: () => void; onQueueBrief: () => void; onSpawn: (kind: "cpu" | "gpu") => void; onRefresh: () => void; onSelectRun: (id: string) => void; onSelectStory: (id: string) => void; onAction: (action: () => Promise<unknown>, message: string) => void; onPreviewRelease: (release: ProductionRelease) => void }) {
  const [settings, setSettings] = useState<StudioSettings>();
  const [releases, setReleases] = useState<ProductionRelease[]>([]);
  const [migration, setMigration] = useState<MigrationReadiness>();
  const [migrationLoading, setMigrationLoading] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [auditionBusy, setAuditionBusy] = useState(false);
  const [auditionUrl, setAuditionUrl] = useState<string>();
  useEffect(() => { if (view === "Settings" || view === "Voice Studio") void api.settings().then(setSettings).catch(() => setSettings(undefined)); }, [view]);
  useEffect(() => {
    if (view !== "Assets" || !selectedStory) { setReleases([]); return; }
    void api.releases(selectedStory.id).then((result) => setReleases(result.releases)).catch(() => setReleases([]));
  }, [view, selectedStory?.id]);
  useEffect(() => {
    if (view !== "Assets") { setMigration(undefined); setMigrationLoading(false); return; }
    setMigrationLoading(true);
    void api.migrationReadiness().then(setMigration).catch(() => setMigration(undefined)).finally(() => setMigrationLoading(false));
  }, [view]);
  const auditionVoice = async (input?: TtsGenerateInput) => {
    if (!settings) return;
    setAuditionBusy(true);
    try {
      const result = await api.ttsGenerate(input || { text: "The road is cold. She keeps walking.", voice_preset: settings.tts_voice_preset, speed: settings.tts_speed });
      setAuditionUrl(result.url);
    }
    catch { setAuditionUrl(undefined); }
    finally { setAuditionBusy(false); }
  };
  const saveSettings = async () => {
    if (!settings) return;
    setSettingsBusy(true);
    try { const result = await api.updateSettings(settings); setSettings(result.settings); onRefresh(); }
    finally { setSettingsBusy(false); }
  };
  const title = view === "Production Runs" ? "Production desk" : view === "Assets" ? "Asset library" : view === "Story Studio" ? "Story Studio" : view === "Voice Studio" ? "Voice Studio" : "Studio settings";
  return <section className="desk-panel metal-panel"><div className="eyebrow"><span>{title}</span><span>{view === "Production Runs" ? `${runs.length} durable runs` : view === "Workers" ? `${workers.length} active signals` : "Operator view"}</span></div>
    {view === "Production Runs" && <ProductionWorkspace runs={runs} stories={stories} selectedStory={selectedStory} jobs={jobs} busy={busy} onSelectRun={onSelectRun} onAction={onAction} />}
    {view === "Assets" && <AssetWorkspace stories={stories} selectedStory={selectedStory} releases={releases} migration={migration} migrationLoading={migrationLoading} onSelectStory={onSelectStory} onPreviewRelease={onPreviewRelease} />}
    {view === "Story Studio" && <StoryStudioWorkspace brief={brief} onBriefChange={onBriefChange} world={world} onWorldChange={onWorldChange} seeds={seeds} seedBusy={seedBusy} onSuggestSeeds={onSuggestSeeds} onQueueBrief={onQueueBrief} />}
    {view === "Voice Studio" && <VoiceStudioWorkspace settings={settings} brief={brief} onBriefChange={onBriefChange} world={world} onWorldChange={onWorldChange} settingsBusy={settingsBusy} auditionBusy={auditionBusy} auditionUrl={auditionUrl} onSettingsChange={setSettings} onAudition={auditionVoice} onSave={saveSettings} />}
    {view === "Settings" && <SettingsWorkspace settings={settings} busy={settingsBusy} auditionBusy={auditionBusy} auditionUrl={auditionUrl} onChange={setSettings} onAudition={() => void auditionVoice()} onReload={() => void api.settings().then(setSettings)} onSave={() => void saveSettings()} />}
    {view === "Settings" && settings && <BackgroundAudioSettings settings={settings} onChange={setSettings} busy={settingsBusy} onSave={() => void saveSettings()} />}
  </section>;
}

function SettingsWorkspace({ settings, busy, auditionBusy, auditionUrl, onChange, onAudition, onReload, onSave }: { settings?: StudioSettings; busy: boolean; auditionBusy: boolean; auditionUrl?: string; onChange: (settings: StudioSettings) => void; onAudition: () => void; onReload: () => void; onSave: () => void }) {
  const [llmModels, setLlmModels] = useState<string[]>([]);
  const [modelsBusy, setModelsBusy] = useState(false);
  const [modelsMessage, setModelsMessage] = useState("");

  useEffect(() => {
    if (settings?.llm_model) setLlmModels((current) => current.includes(settings.llm_model) ? current : [settings.llm_model, ...current]);
  }, [settings?.llm_model]);

  if (!settings) return <><h1>Keep the chain honest.</h1><p className="ledger-empty">Loading validated settings...</p></>;

  const update = (patch: Partial<StudioSettings>) => onChange({ ...settings, ...patch });
  const editableSecret = (value?: string) => value && !value.includes("...") && value !== "****" ? value : "";
  const discoverModels = async () => {
    setModelsBusy(true);
    setModelsMessage("");
    try {
      const result = await api.llmModels({ base_url: settings.llm_base_url, api_key: settings.llm_api_key || "" });
      if (!result.ok) throw new Error(result.error || "Provider did not return a model list");
      const models = Array.from(new Set([settings.llm_model, ...result.models].filter(Boolean)));
      setLlmModels(models);
      setModelsMessage(`${result.models.length} models returned by provider`);
    } catch (error) {
      setModelsMessage(error instanceof Error ? error.message : "Could not load provider models");
    } finally {
      setModelsBusy(false);
    }
  };

  return <>
    <h1>Keep the chain honest.</h1>
    <p className="desk-intro">Provider endpoints and credentials are persisted locally and applied to new production work. Credentials are masked after saving.</p>
    <div className="provider-settings-grid">
      <section className="provider-settings-card">
        <div className="provider-settings-heading"><span className="led green"/><div><h2>Language model</h2><small>OpenAI-compatible provider</small></div></div>
        <label>LLM endpoint<input value={settings.llm_base_url} onChange={(event) => update({ llm_base_url: event.target.value })} placeholder="https://provider.example/v1" /></label>
        <label>LLM API key<input type="password" autoComplete="off" value={editableSecret(settings.llm_api_key)} placeholder={settings.llm_api_key || "Enter provider key"} onChange={(event) => update({ llm_api_key: event.target.value })} /></label>
        <label>LLM model<select value={settings.llm_model} onChange={(event) => update({ llm_model: event.target.value })}>{Array.from(new Set([settings.llm_model, ...llmModels].filter(Boolean))).map((model) => <option key={model} value={model}>{model}</option>)}</select></label>
        <button type="button" className="outline-button provider-discovery" disabled={modelsBusy} onClick={() => void discoverModels()}><RefreshCw size={14}/>{modelsBusy ? "Loading models..." : "Load models from provider"}</button>
        {modelsMessage && <p className="provider-message" role="status">{modelsMessage}</p>}
      </section>

      <section className="provider-settings-card">
        <div className="provider-settings-heading"><span className="led green"/><div><h2>Text to speech</h2><small>Independent narration provider</small></div></div>
        <label>TTS endpoint<input value={settings.tts_base_url} onChange={(event) => update({ tts_base_url: event.target.value })} placeholder="https://voice-provider.example/v1" /></label>
        <label>TTS API key<input type="password" autoComplete="off" value={editableSecret(settings.tts_api_key)} placeholder={settings.tts_api_key || "Blank uses the LLM key"} onChange={(event) => update({ tts_api_key: event.target.value })} /></label>
        <label>TTS model<input value={settings.tts_model} onChange={(event) => update({ tts_model: event.target.value })} placeholder="mimo-v2.5-tts" /></label>
        <div className="settings-pair"><label>Voice<select value={settings.tts_voice_preset} onChange={(event) => update({ tts_voice_preset: event.target.value })}><option>Dean</option><option>Milo</option><option>Mia</option><option>Chloe</option></select></label><label>Speed<input type="number" min="0.5" max="3" step="0.05" value={settings.tts_speed} onChange={(event) => update({ tts_speed: Number(event.target.value) })}/></label></div>
        <div className="voice-audition"><button className="outline-button" disabled={auditionBusy} onClick={onAudition}>{auditionBusy ? "Generating audition..." : "Audition voice"}</button>{auditionUrl && <audio controls autoPlay src={auditionUrl} />}</div>
      </section>

      <section className="provider-settings-card">
        <div className="provider-settings-heading"><span className="led amber"/><div><h2>Additional images</h2><small>Unsplash provider</small></div></div>
        <label>Unsplash endpoint<input value={settings.unsplash_base_url} onChange={(event) => update({ unsplash_base_url: event.target.value })} placeholder="https://api.unsplash.com" /></label>
        <label>Unsplash access key<input type="password" autoComplete="off" value={editableSecret(settings.unsplash_access_key)} placeholder={settings.unsplash_access_key || "Enter Unsplash access key"} onChange={(event) => update({ unsplash_access_key: event.target.value })} /></label>
        <p className="provider-note">Stored for the additional-image source. Generated ComfyUI artwork remains a separate provider.</p>
      </section>

      <section className="provider-settings-card">
        <div className="provider-settings-heading"><span className="led green"/><div><h2>Production defaults</h2><small>Local engine and export</small></div></div>
        <div className="settings-pair"><label>Default visual style<input value={settings.default_visual_style} onChange={(event) => update({ default_visual_style: event.target.value })}/></label><label>Default tone<input value={settings.default_tone} onChange={(event) => update({ default_tone: event.target.value })}/></label></div>
        <label>ComfyUI workers<input value={settings.comfyui_urls} onChange={(event) => update({ comfyui_urls: event.target.value })}/></label>
        <label>Plex destination<input value={settings.plex_destination} onChange={(event) => update({ plex_destination: event.target.value })}/></label>
      </section>
    </div>
    <div className="settings-actions provider-settings-actions"><button className="outline-button" disabled={busy} onClick={onReload}>Reload</button><button className="create" disabled={busy} onClick={onSave}>Save settings</button></div>
  </>;
}

function ProductionWorkspace({ runs, stories, selectedStory, jobs, busy, onSelectRun, onAction }: { runs: ProductionRun[]; stories: Story[]; selectedStory?: Story; jobs: ProductionJob[]; busy: boolean; onSelectRun: (id: string) => void; onAction: (action: () => Promise<unknown>, message: string) => void }) {
  const [planStoryId, setPlanStoryId] = useState(selectedStory?.id || stories[0]?.id || "");
  const [editions, setEditions] = useState<ReleaseEditionId[]>(["cinematic", "plex"]);
  const planStory = stories.find((story) => story.id === planStoryId);
  const focusedRun = runs.find((run) => ["running", "queued", "retryable", "leased"].includes(run.status)) || runs[0];
  const focusedStory = focusedRun ? stories.find((story) => story.id === focusedRun.story_id) : undefined;
  useEffect(() => {
    if (selectedStory?.id) setPlanStoryId(selectedStory.id);
  }, [selectedStory?.id]);
  useEffect(() => {
    if (!planStoryId) return;
    try {
      const stored = window.localStorage.getItem(`fantasee.release-plan.${planStoryId}`);
      if (stored) setEditions(JSON.parse(stored) as ReleaseEditionId[]);
    } catch {
      // Keep the safe default when browser storage is unavailable or malformed.
    }
  }, [planStoryId]);
  const toggleEdition = (id: ReleaseEditionId) => {
    const next = editions.includes(id) ? editions.filter((value) => value !== id) : [...editions, id];
    setEditions(next);
    if (planStoryId) window.localStorage.setItem(`fantasee.release-plan.${planStoryId}`, JSON.stringify(next));
  };
  const runTitle = (run: ProductionRun) => {
    const origin = stories.find((story) => story.id === run.story_id);
    return origin?.title || (run.story_id === "library" ? "Library maintenance" : run.story_id || humanStatus(run.kind));
  };
  return <div className="production-workspace"><div className="production-intro"><div><span className="eyebrow-label">Production command center</span><h1>From origin story to release.</h1><p className="desk-intro">This is where durable work becomes a release plan. Choose an origin story, select editions, then jump into the live ledger only when you need the event-level detail.</p></div><div className="production-stat"><b>{runs.length}</b><small>durable runs</small><span>{jobs.filter((job) => ["queued", "running", "retryable"].includes(job.status)).length} active jobs in focus</span></div></div>{focusedRun && <section className="production-focus"><div className="production-focus-heading"><span className="eyebrow-label">Current run</span><span className={`run-state ${focusedRun.status}`}>{humanStatus(focusedRun.status)}</span></div><div className="production-focus-body"><div><span className="production-focus-label">Working on story</span><h2>{focusedStory?.title || runTitle(focusedRun)}</h2><p>{productionRunPhase(focusedRun)}</p><small>{runWorkerSummary(focusedRun).label}</small></div><div className="production-focus-progress"><b>{Math.round((focusedRun.progress || 0) * 100)}%</b><small>{focusedRun.id}</small></div></div></section>}<div className="production-layout"><section><div className="section-heading"><h2>Production runs</h2><span>Art and origin included</span></div><div className="production-card-grid">{runs.length ? runs.map((run) => { const origin = stories.find((story) => story.id === run.story_id); const progress = Math.round((run.progress || 0) * 100); const terminal = ["succeeded", "failed", "cancelled", "done", "error"].includes(run.status); const worker = runWorkerSummary(run); return <article className="production-card" key={run.id}><div className={origin && hasUsableCover(origin) ? "production-art" : "production-art production-art-empty"}>{origin && hasUsableCover(origin) ? <img src={origin.cover_image_url || origin.hero_image} alt="" /> : <Clapperboard size={25}/>}<span className={`led ${runLedTone(run.status)} ${worker.live ? "live" : ""}`} title={worker.label}/></div><div className="production-card-body"><div className="production-card-kicker"><span>{humanStatus(run.kind)}</span><b>{progress}%</b></div><h3>{runTitle(run)}</h3><p>{productionRunNote(run)}</p><div className="production-card-meta"><span>Origin</span><strong>{origin?.title || run.story_id || "Library"}</strong><small>{run.item_count ? `${run.item_count} work items` : timestamp(run.created_at)}</small><div className="production-worker-status"><span className={`led ${worker.tone} ${worker.live ? "live" : ""}`}/><span>{worker.label}</span></div></div><div className="progress-track"><i style={{ width: `${progress}%` }}/></div><div className="production-card-actions"><button className="outline-button" onClick={() => onSelectRun(run.id)}>Open live ledger <ChevronRight size={14}/></button><button className="production-card-delete" disabled={busy || !terminal} onClick={() => { if (!terminal) return; if (!window.confirm(`Delete the ${runTitle(run)} run and its durable history?`)) return; void onAction(() => api.deleteRun(run.id), `Deleted production run for ${runTitle(run)}.`); }} title={terminal ? "Delete this finished run" : "Only finished runs can be deleted"}><Trash2 size={13}/> Delete</button></div></div></article>; }) : <div className="empty-state"><Radio size={25}/><p>No durable production runs yet.</p></div>}</div></section><aside className="release-planner"><div className="eyebrow"><span>Release planning</span><span>{editions.length} selected</span></div><h2>Choose the output editions.</h2><p>Plans are remembered per story. The current render and Plex actions are executable; the other editions remain clearly marked until their dedicated exporters land.</p><label className="planner-story">Origin story<select value={planStoryId} onChange={(event) => setPlanStoryId(event.target.value)}>{stories.length ? stories.map((story) => <option key={story.id} value={story.id}>{story.title}</option>) : <option value="">No stories available</option>}</select></label><div className="edition-grid">{releaseEditionOptions.map(({ id, label, detail, icon: Icon }) => { const selected = editions.includes(id); const executable = id === "cinematic" || id === "plex"; return <button type="button" className={selected ? "edition-card selected" : "edition-card"} key={id} onClick={() => toggleEdition(id)}><span className="edition-icon"><Icon size={16}/></span><span><strong>{label}</strong><small>{detail}</small></span><em>{executable ? "available" : "planned"}</em></button>; })}</div><div className="planner-actions"><button className="create" disabled={busy || !planStory} onClick={() => planStory && onAction(() => api.renderStory(planStory.id), `Cinematic master render requested for ${planStory.title}.`)}><Clapperboard size={15}/> Render cinematic</button><button className="outline-button" disabled={busy || !planStory || !editions.includes("plex")} onClick={() => planStory && onAction(() => api.exportPlex(planStory.id), `Plex package requested for ${planStory.title}.`)}><Archive size={15}/> Export Plex</button></div><small className="planner-note">Selected: {planStory?.title || "Choose an origin story"}</small></aside></div></div>;
}

function AssetWorkspace({ stories, selectedStory, releases, migration, migrationLoading, onSelectStory, onPreviewRelease }: { stories: Story[]; selectedStory?: Story; releases: ProductionRelease[]; migration?: MigrationReadiness; migrationLoading: boolean; onSelectStory: (id: string) => void; onPreviewRelease: (release: ProductionRelease) => void }) {
  return <div className="asset-workspace"><div className="asset-intro"><div><span className="eyebrow-label">Approved asset library</span><h1>Every story has a visual home.</h1><p className="desk-intro">Browse origin artwork, completion evidence, and release artifacts together. This library is intentionally scrollable so the collection can grow without squeezing the rest of Studio.</p></div>{migrationLoading ? <span className="asset-scan"><span className="led amber"/> Scanning evidence</span> : migration && <span className="asset-scan"><span className="led green"/> {migration.summary.rollback_ready} rollback-ready</span>}</div><div className="asset-library-scroll"><div className="asset-story-grid">{stories.length ? stories.map((story) => <button className={selectedStory?.id === story.id ? "asset-story-card selected" : "asset-story-card"} key={story.id} onClick={() => onSelectStory(story.id)}><div className="asset-story-art">{hasUsableCover(story) ? <img src={story.cover_image_url || story.hero_image} alt="" /> : <Image size={25}/>}</div><div><strong>{story.title}</strong><small>{story.scene_count || 0} scenes · {storyHealth(story).text}</small></div><span className={`led ${storyHealth(story).tone === "ready" ? "green" : "amber"}`}/></button>) : <p className="ledger-empty">No stories have been added to the managed library.</p>}</div></div>{selectedStory ? <section className="asset-detail-panel"><div className="asset-detail-heading"><div><span className="eyebrow-label">Origin story</span><h2>{selectedStory.title}</h2><p>{selectedStory.description || "No story description has been recorded yet."}</p></div><div className="asset-detail-cover">{hasUsableCover(selectedStory) ? <img src={selectedStory.cover_image_url || selectedStory.hero_image} alt="" /> : <Image size={22}/>}</div></div><div className="asset-evidence-grid">{completionRows(selectedStory).map(([, label, complete, detail]) => <div className="asset-evidence-card" key={label}><span className={`led ${complete ? "green" : "amber"}`}/><strong>{label}</strong><small>{detail}</small></div>)}</div><ReleaseLedger releases={releases} onPreview={onPreviewRelease} /></section> : <div className="asset-empty"><Archive size={24}/><p>Select a story card to inspect its assets and releases.</p></div>}</div>;
}

function LegacyStoryStudioWorkspaceOld({ brief, onBriefChange, world, onWorldChange, seeds, seedBusy, onSuggestSeeds, onQueueBrief }: { brief: GenerateInput; onBriefChange: (brief: GenerateInput) => void; world: WorldKnowledgeBase; onWorldChange: (world: WorldKnowledgeBase) => void; seeds: SeedSuggestion[]; seedBusy: boolean; onSuggestSeeds: () => void; onQueueBrief: () => void }) {
  const updateBrief = (patch: Partial<GenerateInput>) => onBriefChange({ ...brief, ...patch });
  const updateWorld = (patch: Partial<WorldKnowledgeBase>) => onWorldChange({ ...world, ...patch });
  const updateCharacter = (id: string, patch: Partial<WorldCharacter>) => updateWorld({ characters: world.characters.map((character) => character.id === id ? { ...character, ...patch } : character) });
  const updateRelationship = (id: string, patch: Partial<WorldRelationship>) => updateWorld({ relationships: world.relationships.map((relationship) => relationship.id === id ? { ...relationship, ...patch } : relationship) });
  const updateArc = (id: string, patch: Partial<WorldArc>) => updateWorld({ arcs: world.arcs.map((arc) => arc.id === id ? { ...arc, ...patch } : arc) });
  const addCharacter = () => updateWorld({ characters: [...world.characters, { id: `character-${Date.now()}`, name: "New character", role: "Role", description: "Character sheet notes and continuity state.", voice: "Dean", style: "Studio default" }] });
  const addRelationship = () => updateWorld({ relationships: [...world.relationships, { id: `relationship-${Date.now()}`, from: world.characters[0]?.name || "Character A", to: world.characters[1]?.name || "Character B", label: "relationship", status: "forming" }] });
  const addArc = () => updateWorld({ arcs: [...world.arcs, { id: `arc-${Date.now()}`, title: "New universe arc", summary: "What changes across this arc?", status: "planned", beats: "Inciting pressure\nComplication\nChoice\nConsequence" }] });
  const loadExample = () => onWorldChange(humansVsNeanderthalsExample);
  return <div className="creative-workspace story-studio-workspace"><div className="creative-heading"><div><span className="eyebrow-label">Writer · world architect · continuity editor</span><h1>Build the universe before we spend a frame.</h1><p className="desk-intro">The universe bible is remembered locally and handed to the production pipeline with every queued brief. Characters, relationships, rules, and arcs remain available to the writer and performance director.</p></div><div className="pipeline-steps"><span className="active">01 Universe</span><span>02 Characters</span><span>03 Arcs</span><span>04 Production</span></div></div><section className="world-overview"><div className="section-heading"><h2>World knowledge base</h2><span>{world.characters.length} character sheets · {world.arcs.length} arcs</span></div><div className="world-actions"><button type="button" className="outline-button" onClick={loadExample}>Load Humans vs Neanderthals example</button><small>Use this as a starting point, then replace every fact with your own canon.</small></div><div className="brief-grid"><label className="brief-field">Universe name<input value={world.title} onChange={(event) => updateWorld({ title: event.target.value })} placeholder="The world or universe title" /></label><label className="brief-field wide">Core premise<textarea value={world.premise} onChange={(event) => updateWorld({ premise: event.target.value })} placeholder="What is true about this world, and what pressure keeps its stories moving?" /></label><label className="brief-field wide">World rules and knowledge<textarea value={world.rules} onChange={(event) => updateWorld({ rules: event.target.value })} placeholder="History, physics, technology, magic, ecology, taboos, and continuity facts." /></label><label className="brief-field wide">Factions, cultures, and institutions<textarea value={world.factions} onChange={(event) => updateWorld({ factions: event.target.value })} placeholder="Groups, competing beliefs, resources, and power structures." /></label></div></section><section className="world-section"><div className="section-heading"><h2>Deep character sheets</h2><button type="button" className="micro-button" onClick={addCharacter}><Plus size={13}/> Add character</button></div><div className="character-sheet-grid">{world.characters.length ? world.characters.map((character) => <article className="character-sheet" key={character.id}><div className="character-sheet-heading"><input value={character.name} onChange={(event) => updateCharacter(character.id, { name: event.target.value })} aria-label="Character name"/><button type="button" className="micro-button" onClick={() => updateWorld({ characters: world.characters.filter((item) => item.id !== character.id) })} title="Remove character"><X size={12}/></button></div><label>Role<input value={character.role} onChange={(event) => updateCharacter(character.id, { role: event.target.value })}/></label><label>Continuity and inner life<textarea value={character.description} onChange={(event) => updateCharacter(character.id, { description: event.target.value })} placeholder="Motivation, appearance, wound, secret, values, knowledge, and state changes." /></label><div className="character-sheet-meta"><span>Voice</span><strong>{character.voice}</strong><span>Style</span><strong>{character.style}</strong></div></article>) : <p className="ledger-empty">Add the first character sheet, or load the example universe.</p>}</div></section><section className="world-section"><div className="section-heading"><h2>Relationships</h2><button type="button" className="micro-button" onClick={addRelationship}><Plus size={13}/> Add relationship</button></div><div className="relationship-list">{world.relationships.length ? world.relationships.map((relationship) => <div className="relationship-row" key={relationship.id}><input value={relationship.from} onChange={(event) => updateRelationship(relationship.id, { from: event.target.value })} aria-label="Relationship source"/><span>→</span><input value={relationship.to} onChange={(event) => updateRelationship(relationship.id, { to: event.target.value })} aria-label="Relationship target"/><input value={relationship.label} onChange={(event) => updateRelationship(relationship.id, { label: event.target.value })} aria-label="Relationship description"/><select value={relationship.status} onChange={(event) => updateRelationship(relationship.id, { status: event.target.value })}><option>forming</option><option>active</option><option>fractured</option><option>resolved</option></select><button type="button" className="micro-button" onClick={() => updateWorld({ relationships: world.relationships.filter((item) => item.id !== relationship.id) })} title="Remove relationship"><X size={12}/></button></div>) : <p className="ledger-empty">No relationships have been defined yet.</p>}</div></section><section className="world-section"><div className="section-heading"><h2>Universe arcs</h2><button type="button" className="micro-button" onClick={addArc}><Plus size={13}/> Add arc</button></div><div className="arc-grid">{world.arcs.length ? world.arcs.map((arc) => <article className="arc-card" key={arc.id}><div className="character-sheet-heading"><input value={arc.title} onChange={(event) => updateArc(arc.id, { title: event.target.value })} aria-label="Arc title"/><select value={arc.status} onChange={(event) => updateArc(arc.id, { status: event.target.value as WorldArc["status"] })}><option value="planned">Planned</option><option value="active">Active</option><option value="resolved">Resolved</option></select><button type="button" className="micro-button" onClick={() => updateWorld({ arcs: world.arcs.filter((item) => item.id !== arc.id) })} title="Remove arc"><X size={12}/></button></div><label>Arc summary<textarea value={arc.summary} onChange={(event) => updateArc(arc.id, { summary: event.target.value })}/></label><label>Beats, one per line<textarea value={arc.beats} onChange={(event) => updateArc(arc.id, { beats: event.target.value })}/></label></article>) : <p className="ledger-empty">Add an arc to track promises, turning points, and consequences across stories.</p>}</div></section><section className="world-section diagram-section"><div className="section-heading"><h2>Story flow and arc map</h2><span>Mermaid-compatible source</span></div><p className="desk-intro">Edit the Mermaid definition as the universe grows. It travels with the world bible so important flows remain inspectable instead of living only in prose.</p><textarea className="mermaid-editor" value={world.flowDiagram} onChange={(event) => updateWorld({ flowDiagram: event.target.value })}/><pre className="mermaid-preview">{world.flowDiagram}</pre></section><div className="creative-grid story-brief-grid"><section className="creative-form"><div className="section-heading"><h2>Story brief</h2><span>Current production</span></div><label className="brief-field wide">Story intent<textarea value={brief.story_concept} onChange={(event) => updateBrief({ story_concept: event.target.value })} placeholder="A medic from Johannesburg wakes in a cold mountain village where every wound carries a memory..." /><button type="button" className="outline-button seed-button" disabled={seedBusy} onClick={onSuggestSeeds}>{seedBusy ? "Consulting director..." : "Suggest three directions"}</button></label>{seeds.length > 0 && <div className="seed-grid">{seeds.map((seed) => <button type="button" className="seed-card" key={`${seed.title}-${seed.description}`} onClick={() => { updateBrief({ story_concept: `${seed.title}\n${seed.description}`, style: seed.style || brief.style, tone: seed.tone || brief.tone, characters: seed.characters || brief.characters }); }}>{seed.title}<small>{seed.description}</small><em>{seed.style || brief.style} · {seed.tone || brief.tone}</em></button>)}</div>}<div className="brief-grid"><label className="brief-field">Director preset<select value={directorPresets.find((preset) => preset.style === brief.style && preset.tone === brief.tone)?.id || "custom"} onChange={(event) => { const preset = directorPresets.find((item) => item.id === event.target.value); if (preset) updateBrief({ style: preset.style, tone: preset.tone, num_scenes: preset.scenes, images_per_scene: preset.images, voice_preset: preset.voice, narration_style: preset.narrationStyle }); }}><option value="custom">Custom direction</option>{directorPresets.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}</select></label><label className="brief-field">Scene count<select value={brief.num_scenes} onChange={(event) => updateBrief({ num_scenes: Number(event.target.value) })}>{sceneOptions.map((count) => <option key={count} value={count}>{count} scenes · {count <= 5 ? "short arc" : count >= 10 ? "full feature" : "balanced arc"}</option>)}</select></label><label className="brief-field">Visual density<select value={brief.images_per_scene} onChange={(event) => updateBrief({ images_per_scene: Number(event.target.value) })}>{imageOptions.map((count) => <option key={count} value={count}>{count} beats per scene · {count <= 3 ? "spare" : count >= 9 ? "rich" : "cinematic"}</option>)}</select></label><label className="brief-field">Visual language<select value={brief.style} onChange={(event) => updateBrief({ style: event.target.value })}>{styleOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="brief-field">Emotional register<select value={brief.tone} onChange={(event) => updateBrief({ tone: event.target.value })}>{toneOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="brief-field">Narration direction<select value={brief.narration_style || ""} onChange={(event) => updateBrief({ narration_style: event.target.value })}>{narrationOptions.map(([value, label]) => <option key={value || "default"} value={value}>{label}</option>)}</select></label></div><label className="brief-field wide">Characters and continuity<textarea value={brief.characters} onChange={(event) => updateBrief({ characters: event.target.value })} placeholder="Optional immediate cast notes; deeper canon lives above." /></label><label className="brief-field wide">Narrator<select value={brief.voice_preset} onChange={(event) => updateBrief({ voice_preset: event.target.value })}>{voiceOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><button className="create queue-brief-button" type="button" onClick={onQueueBrief}><Plus size={16}/> Push world-aware brief to production</button></section><aside className="creative-rail"><h2>Continuity handoff</h2><p>Every queued production receives the premise, rules, cast sheets, relationship states, arc beats, Mermaid source, and character voice assignments.</p><div className="handoff-step"><span>01</span><div><strong>World bible</strong><small>{world.title || "Untitled universe"}</small></div></div><div className="handoff-step"><span>02</span><div><strong>Character state</strong><small>{world.characters.length} sheets · {world.relationships.length} relationships</small></div></div><div className="handoff-step"><span>03</span><div><strong>Arc tracking</strong><small>{world.arcs.filter((arc) => arc.status !== "resolved").length} open arcs</small></div></div><div className="handoff-step"><span>04</span><div><strong>Performance</strong><small>Voice Studio allocations</small></div></div></aside></div></div>;
}

function LegacyStoryStudioWorkspace({ brief, onBriefChange, seeds, seedBusy, onSuggestSeeds, onQueueBrief }: { brief: GenerateInput; onBriefChange: (brief: GenerateInput) => void; seeds: SeedSuggestion[]; seedBusy: boolean; onSuggestSeeds: () => void; onQueueBrief: () => void }) {
  const update = (patch: Partial<GenerateInput>) => onBriefChange({ ...brief, ...patch });
  return <div className="creative-workspace story-studio-workspace"><div className="creative-heading"><div><span className="eyebrow-label">Writer · director · producer</span><h1>Construct the story before we render it.</h1><p className="desk-intro">Story Studio is the creative control surface. These parameters are handed to the durable production pipeline as one inspectable brief.</p></div><div className="pipeline-steps"><span className="active">01 Intent</span><span>02 Scenes</span><span>03 Performance</span><span>04 Release</span></div></div><div className="creative-grid"><section className="creative-form"><label className="brief-field wide">Story intent<textarea value={brief.story_concept} onChange={(event) => update({ story_concept: event.target.value })} placeholder="A medic from Johannesburg wakes in a cold mountain village where every wound carries a memory..." /><button type="button" className="outline-button seed-button" disabled={seedBusy} onClick={onSuggestSeeds}>{seedBusy ? "Consulting director..." : "Suggest three directions"}</button></label>{seeds.length > 0 && <div className="seed-grid">{seeds.map((seed) => <button type="button" className="seed-card" key={`${seed.title}-${seed.description}`} onClick={() => { update({ story_concept: `${seed.title}\n${seed.description}`, style: seed.style || brief.style, tone: seed.tone || brief.tone, characters: seed.characters || brief.characters }); }}>{seed.title}<small>{seed.description}</small><em>{seed.style || brief.style} · {seed.tone || brief.tone}</em></button>)}</div>}<div className="brief-grid"><label className="brief-field">Director preset<select value={directorPresets.find((preset) => preset.style === brief.style && preset.tone === brief.tone)?.id || "custom"} onChange={(event) => { const preset = directorPresets.find((item) => item.id === event.target.value); if (preset) update({ style: preset.style, tone: preset.tone, num_scenes: preset.scenes, images_per_scene: preset.images, voice_preset: preset.voice, narration_style: preset.narrationStyle }); }}><option value="custom">Custom direction</option>{directorPresets.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}</select></label><label className="brief-field">Scene count<select value={brief.num_scenes} onChange={(event) => update({ num_scenes: Number(event.target.value) })}>{sceneOptions.map((count) => <option key={count} value={count}>{count} scenes · {count <= 5 ? "short arc" : count >= 10 ? "full feature" : "balanced arc"}</option>)}</select></label><label className="brief-field">Visual density<select value={brief.images_per_scene} onChange={(event) => update({ images_per_scene: Number(event.target.value) })}>{imageOptions.map((count) => <option key={count} value={count}>{count} beats per scene · {count <= 3 ? "spare" : count >= 9 ? "rich" : "cinematic"}</option>)}</select></label><label className="brief-field">Visual language<select value={brief.style} onChange={(event) => update({ style: event.target.value })}>{styleOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="brief-field">Emotional register<select value={brief.tone} onChange={(event) => update({ tone: event.target.value })}>{toneOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="brief-field">Narration direction<select value={brief.narration_style || ""} onChange={(event) => update({ narration_style: event.target.value })}>{narrationOptions.map(([value, label]) => <option key={value || "default"} value={value}>{label}</option>)}</select></label></div><label className="brief-field wide">Characters and continuity<textarea value={brief.characters} onChange={(event) => update({ characters: event.target.value })} placeholder="Optional character, setting, or visual continuity notes." /></label><label className="brief-field wide">Narrator<select value={brief.voice_preset} onChange={(event) => update({ voice_preset: event.target.value })}>{voiceOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><button className="create queue-brief-button" type="button" onClick={onQueueBrief}><Plus size={16}/> Push brief to production</button></section><aside className="creative-rail"><h2>Pipeline handoff</h2><p>Once queued, the brief is decomposed into durable jobs. Approved decisions remain traceable and editable.</p><div className="handoff-step"><span>01</span><div><strong>Writer</strong><small>Bible, outline, scenes</small></div></div><div className="handoff-step"><span>02</span><div><strong>Director</strong><small>Shots, rhythm, artwork</small></div></div><div className="handoff-step"><span>03</span><div><strong>Performance</strong><small>Voice, pace, subtitles</small></div></div><div className="handoff-step"><span>04</span><div><strong>Producer</strong><small>Timeline, editions, evidence</small></div></div></aside></div></div>;
}

function VoiceStudioWorkspace({ settings, brief, onBriefChange, world, onWorldChange, settingsBusy, auditionBusy, auditionUrl, onSettingsChange, onAudition, onSave }: { settings?: StudioSettings; brief: GenerateInput; onBriefChange: (brief: GenerateInput) => void; world: WorldKnowledgeBase; onWorldChange: (world: WorldKnowledgeBase) => void; settingsBusy: boolean; auditionBusy: boolean; auditionUrl?: string; onSettingsChange: (settings: StudioSettings) => void; onAudition: (input: TtsGenerateInput) => Promise<void>; onSave: () => Promise<void> }) {
  const [mode, setMode] = useState<TtsModel>("preset");
  const [voiceDescription, setVoiceDescription] = useState("A warm, cinematic storyteller with a grounded, intimate presence and clear English diction.");
  const [stylePrompt, setStylePrompt] = useState(settings?.default_style || narrationStylePresets[0].prompt);
  const [selectedStyleIndex, setSelectedStyleIndex] = useState(0);
  const [auditionText, setAuditionText] = useState("The road is cold. She keeps walking.");
  const [optimizeText, setOptimizeText] = useState(true);
  const [streamPreview, setStreamPreview] = useState(false);
  const [voiceSample, setVoiceSample] = useState<string>();
  const [voiceSampleName, setVoiceSampleName] = useState<string>();
  const [sampleError, setSampleError] = useState<string>();
  const [profileName, setProfileName] = useState("");
  const [profileError, setProfileError] = useState<string>();
  const [profileBusy, setProfileBusy] = useState(false);
  const [savedVoices, setSavedVoices] = useState<SavedVoiceProfile[]>(() => readSavedVoiceProfiles());
  const audioTags = ["(whispers)", "(sighs)", "(speaking faster)", "(soft pause)", "(laughs softly)", "(singing)"];
  useEffect(() => {
    if (settings?.default_style) setStylePrompt(settings.default_style);
    const index = narrationStylePresets.findIndex((preset) => preset.value === (settings?.narration_style || ""));
    if (index >= 0) setSelectedStyleIndex(index);
  }, [settings?.default_style, settings?.narration_style]);
  useEffect(() => {
    let active = true;
    void loadSavedVoiceProfiles().then((profiles) => {
      if (active && profiles.length) setSavedVoices(profiles);
    });
    return () => { active = false; };
  }, []);
  if (!settings) return <div className="creative-workspace"><div className="migration-loading"><span className="led amber"/> Loading voice controls...</div></div>;
  const update = (patch: Partial<StudioSettings>) => onSettingsChange({ ...settings, ...patch });
  const selectVoice = (voice: string) => { update({ tts_voice_preset: voice }); onBriefChange({ ...brief, voice_preset: voice }); };
  const updateCharacter = (id: string, patch: Partial<WorldCharacter>) => onWorldChange({ ...world, characters: world.characters.map((character) => character.id === id ? { ...character, ...patch } : character) });
  const chooseStyle = (index: number) => {
    const preset = narrationStylePresets[index];
    setSelectedStyleIndex(index);
    setStylePrompt(preset.prompt);
    update({ default_style: preset.prompt, narration_style: preset.value });
    onBriefChange({ ...brief, narration_style: preset.value });
  };
  const moveStyle = (delta: number) => chooseStyle((selectedStyleIndex + delta + narrationStylePresets.length) % narrationStylePresets.length);
  const readSample = (file?: File) => {
    if (!file) return;
    const supportedType = ["audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav"].includes(file.type) || /\.(mp3|wav)$/i.test(file.name);
    if (!supportedType) { setSampleError("Choose an MP3 or WAV sample."); return; }
    if (file.size > 7_500_000) { setSampleError("Keep the source file under 7.5 MB so the encoded sample stays under MiMo's 10 MB limit."); return; }
    const reader = new FileReader();
    reader.onload = () => { const data = String(reader.result || ""); if (data.length > 10 * 1024 * 1024) { setSampleError("The encoded sample exceeds MiMo's 10 MB limit."); return; } setSampleError(undefined); setVoiceSample(data); setVoiceSampleName(file.name); };
    reader.onerror = () => setSampleError("The sample could not be read.");
    reader.readAsDataURL(file);
  };
  const insertTag = (tag: string) => setAuditionText((current) => `${current.trim()} ${tag}`.trim());
  const audition = (style = stylePrompt) => {
    const text = auditionText.trim();
    if (!text) return;
    void onAudition({ text, model: mode, voice_preset: mode === "preset" ? settings.tts_voice_preset : undefined, style: mode === "preset" || mode === "clone" ? style : undefined, voice_description: mode === "design" ? voiceDescription : undefined, voice_sample: mode === "clone" ? voiceSample : undefined, optimize_text_preview: optimizeText, stream: mode === "preset" && streamPreview, speed: settings.tts_speed });
  };
  const saveVoiceProfile = async () => {
    if (mode === "clone" && !voiceSample) {
      setProfileError("Add a clone sample and audition it before saving the profile.");
      return;
    }
    const name = profileName.trim() || `${mode === "clone" ? "Cloned" : mode === "design" ? "Designed" : "Preset"} ${narrationStylePresets[selectedStyleIndex].label}`;
    const profile: SavedVoiceProfile = {
      id: `voice-${Date.now()}`,
      name,
      model: mode,
      voice_preset: mode === "preset" ? settings.tts_voice_preset : undefined,
      voice_description: mode === "design" ? voiceDescription : undefined,
      style: stylePrompt,
      narration_style: narrationStylePresets[selectedStyleIndex].value,
      voice_sample: mode === "clone" ? voiceSample : undefined,
      sample_name: mode === "clone" ? voiceSampleName : undefined,
      created_at: Date.now(),
    };
    const next = [profile, ...savedVoices.filter((item) => item.name !== name)].slice(0, 30);
    setProfileBusy(true);
    try {
      await persistSavedVoiceProfiles(next);
      setSavedVoices(next);
      setProfileName("");
      setProfileError(undefined);
    } catch {
      setProfileError("This voice could not be saved in browser storage.");
    } finally {
      setProfileBusy(false);
    }
  };
  const loadVoiceProfile = (profile: SavedVoiceProfile) => {
    if (profile.model === "clone" && !profile.voice_sample) {
      setProfileError("This saved clone has no sample data. Upload the original sample again to use it.");
      return;
    }
    setMode(profile.model);
    setVoiceDescription(profile.voice_description || "");
    setStylePrompt(profile.style || narrationStylePresets[0].prompt);
    setVoiceSample(profile.voice_sample);
    setVoiceSampleName(profile.sample_name);
    const styleIndex = narrationStylePresets.findIndex((preset) => preset.value === (profile.narration_style || ""));
    if (styleIndex >= 0) setSelectedStyleIndex(styleIndex);
    update({
      tts_voice_preset: profile.voice_preset || settings.tts_voice_preset,
      default_style: profile.style || "",
      narration_style: profile.narration_style || "",
    });
    onBriefChange({ ...brief, voice_preset: profile.voice_preset || brief.voice_preset, narration_style: profile.narration_style || "" });
    setProfileError(undefined);
  };
  return <div className="creative-workspace voice-studio-workspace"><section className="saved-voice-library"><div className="section-heading"><div><h2>Saved voice library</h2><p>Save a designed or cloned voice once, then reload it for another story or style audition.</p></div><span>{savedVoices.length} reusable</span></div><div className="saved-voice-actions"><input value={profileName} onChange={(event) => setProfileName(event.target.value)} placeholder="Profile name, e.g. Var - winter guardian" aria-label="Saved voice profile name"/><button type="button" className="outline-button" disabled={profileBusy || (mode === "clone" && !voiceSample)} onClick={() => void saveVoiceProfile()}>{profileBusy ? "Saving profile..." : "Save current voice"}</button></div>{profileError && <p className="form-error">{profileError}</p>}<div className="saved-voice-list">{savedVoices.map((profile) => <button type="button" className="saved-voice-card" key={profile.id} onClick={() => loadVoiceProfile(profile)}><strong>{profile.name}</strong><small>{profile.model} · {profile.voice_preset || "custom voice"} · {narrationStylePresets.find((preset) => preset.value === (profile.narration_style || ""))?.label || "Custom style"}</small></button>)}{!savedVoices.length && <p className="ledger-empty">Save the current voice to make it available for future productions.</p>}</div></section><div className="creative-heading"><div><span className="eyebrow-label">MiMo V2.5 performance director</span><h1>Audition the voice before it becomes canon.</h1><p className="desk-intro">Move through narration styles, audition the selected direction, then assign a voice and delivery style to every character in the active universe.</p></div><div className="voice-brief-chip"><span>Current brief voice</span><strong>{brief.voice_preset}</strong></div></div><div className="voice-studio-grid"><section className="voice-console"><div className="section-heading"><h2>Voice palette & direction</h2><span>MiMo V2.5 TTS</span></div><div className="voice-selection-banner"><span>Selected voice</span><strong>{mode === "preset" ? settings.tts_voice_preset : mode === "design" ? "Designed voice" : voiceSampleName || "Clone sample required"}</strong><small>{mode === "preset" ? "This built-in voice will narrate the next audition and production brief." : mode === "design" ? "The saved voice description will drive the next audition." : "The uploaded clone sample will drive the next audition."}</small></div><div className="mimo-mode-grid"><button type="button" className={mode === "preset" ? "mimo-mode selected" : "mimo-mode"} onClick={() => setMode("preset")}><strong>Built-in voice</strong><small>Mia, Chloe, Milo, or Dean. Fast preview available.</small></button><button type="button" className={mode === "design" ? "mimo-mode selected" : "mimo-mode"} onClick={() => setMode("design")}><strong>Voice design</strong><small>Describe the character, timbre, and delivery.</small></button><button type="button" className={mode === "clone" ? "mimo-mode selected" : "mimo-mode"} onClick={() => setMode("clone")}><strong>Voice clone</strong><small>Replicate a private MP3 or WAV sample.</small></button></div><section className="voice-style-panel"><div className="section-heading"><h2>Narration style carousel</h2><span>{selectedStyleIndex + 1} / {narrationStylePresets.length}</span></div><div className="style-carousel"><button type="button" className="outline-button" onClick={() => moveStyle(-1)} aria-label="Previous narration style">Previous</button><article className="style-current"><strong>{narrationStylePresets[selectedStyleIndex].label}</strong><p>{narrationStylePresets[selectedStyleIndex].prompt}</p></article><button type="button" className="outline-button" onClick={() => moveStyle(1)} aria-label="Next narration style">Next</button></div><div className="style-shelf">{narrationStylePresets.map((preset, index) => <button type="button" key={preset.value || "default"} className={index === selectedStyleIndex ? "style-chip selected" : "style-chip"} onClick={() => chooseStyle(index)}>{preset.label}</button>)}</div><button type="button" className="create style-audition-button" disabled={auditionBusy || !auditionText.trim()} onClick={() => audition(narrationStylePresets[selectedStyleIndex].prompt)}>{auditionBusy ? "Auditioning style..." : `Audition ${narrationStylePresets[selectedStyleIndex].label}`}</button></section>{mode === "preset" && <><h2>Voice palette</h2><div className="voice-card-grid">{voiceOptions.map(([value, label]) => <button type="button" className={settings.tts_voice_preset === value ? "voice-card selected" : "voice-card"} key={value} onClick={() => selectVoice(value)}><span className="voice-avatar"><Volume2 size={17}/></span><span><strong>{label.split(" · ")[0]}</strong><small>{label.split(" · ")[1] || "Studio voice"}</small></span>{settings.tts_voice_preset === value && <span className="led green"/>}</button>)}</div></>}{mode === "design" && <label className="brief-field wide mimo-textarea">Voice description<textarea value={voiceDescription} onChange={(event) => setVoiceDescription(event.target.value)} placeholder="A low, weathered voice with patient warmth, a slight northern accent, and a smile held back by exhaustion."/><small>Describe identity, personality, timbre, accent, and speaking habits.</small></label>}{mode === "clone" && <div className="clone-upload"><label className="brief-field wide">Voice sample<input type="file" accept="audio/mpeg,audio/mp3,audio/wav" onChange={(event) => readSample(event.target.files?.[0])}/><small>{voiceSampleName ? `Loaded ${voiceSampleName}` : "MP3 or WAV, under 7.5 MB source size."}</small></label>{sampleError && <p className="form-error">{sampleError}</p>}</div>}<div className="voice-controls"><label>Performance speed<input type="range" min="0.5" max="2" step="0.05" value={settings.tts_speed} onChange={(event) => update({ tts_speed: Number(event.target.value) })}/><b>{settings.tts_speed.toFixed(2)}×</b></label><label>Current style<select value={narrationStylePresets[selectedStyleIndex].value} onChange={(event) => { const index = narrationStylePresets.findIndex((preset) => preset.value === event.target.value); if (index >= 0) chooseStyle(index); }}>{narrationStylePresets.map((preset) => <option key={preset.value || "default"} value={preset.value}>{preset.label}</option>)}</select></label></div><label className="brief-field wide">Director guidance<textarea value={stylePrompt} onChange={(event) => { setStylePrompt(event.target.value); update({ default_style: event.target.value }); }} placeholder="[Character] ... [Scene] ... [Guidance] ..."/><small>Natural language controls speed, emotion, role-play, dialect, breath, resonance, and scene context.</small></label><div className="tag-control"><div className="section-heading"><h2>Audio tags</h2><span>Insert into audition text</span></div><div className="tag-list">{audioTags.map((tag) => <button type="button" className="tag-button" key={tag} onClick={() => insertTag(tag)}>{tag}</button>)}</div></div><label className="brief-field wide">Audition text<textarea value={auditionText} onChange={(event) => setAuditionText(event.target.value)} placeholder="Write a short line that matches the voice you are designing."/></label><div className="mimo-options"><label className="check-control"><input type="checkbox" checked={optimizeText} onChange={(event) => setOptimizeText(event.target.checked)}/><span>Optimize preview text</span><small>MiMo can polish the target line for a designed voice.</small></label><label className="check-control"><input type="checkbox" checked={streamPreview} disabled={mode !== "preset"} onChange={(event) => setStreamPreview(event.target.checked)}/><span>Low-latency streaming preview</span><small>{mode === "preset" ? "Built-in voices return PCM16 chunks for a faster audition." : "Available only for built-in voices; design and clone use compatibility mode."}</small></label></div><div className="voice-actions"><button className="outline-button" disabled={auditionBusy || !auditionText.trim() || (mode === "clone" && !voiceSample)} onClick={() => audition()}>{auditionBusy ? "Generating audition..." : "Audition current performance"}</button><button className="create" disabled={settingsBusy} onClick={() => void onSave()}>Save voice settings</button></div>{auditionUrl && <audio className="voice-audio" controls autoPlay src={auditionUrl} />}</section><aside className="voice-rail"><span className="eyebrow-label">Character voice allocation</span><h2>Cast the universe.</h2><p>These assignments are included in the next production brief. Keep the style specific to the character, not only to the narrator.</p><div className="character-voice-list">{world.characters.length ? world.characters.map((character) => <article className="character-voice-card" key={character.id}><div><strong>{character.name}</strong><small>{character.role}</small></div><label>Voice<select value={character.voice} onChange={(event) => updateCharacter(character.id, { voice: event.target.value })}>{voiceOptions.map(([value, label]) => <option key={value} value={value}>{label.split(" · ")[0]}</option>)}</select></label><label>Style<select value={character.style} onChange={(event) => updateCharacter(character.id, { style: event.target.value })}>{narrationStylePresets.map((preset) => <option key={preset.label} value={preset.label}>{preset.label}</option>)}</select></label></article>) : <p className="ledger-empty">Add character sheets in Story Studio to allocate voices here.</p>}</div><dl><div><dt>Mode</dt><dd>{mode === "preset" ? "Built-in" : mode === "design" ? "Designed" : "Cloned"}</dd></div><div><dt>Style</dt><dd>{narrationStylePresets[selectedStyleIndex].label}</dd></div><div><dt>Assignments</dt><dd>{world.characters.length} characters</dd></div><div><dt>Subtitles</dt><dd>Re-align after changed narration</dd></div></dl></aside></div></div>;
}

function LegacyVoiceStudioWorkspace({ settings, brief, onBriefChange, settingsBusy, auditionBusy, auditionUrl, onSettingsChange, onAudition, onSave }: { settings?: StudioSettings; brief: GenerateInput; onBriefChange: (brief: GenerateInput) => void; settingsBusy: boolean; auditionBusy: boolean; auditionUrl?: string; onSettingsChange: (settings: StudioSettings) => void; onAudition: () => Promise<void>; onSave: () => Promise<void> }) {
  if (!settings) return <div className="creative-workspace"><div className="migration-loading"><span className="led amber"/> Loading voice controls...</div></div>;
  const update = (patch: Partial<StudioSettings>) => onSettingsChange({ ...settings, ...patch });
  const selectVoice = (voice: string) => { update({ tts_voice_preset: voice }); onBriefChange({ ...brief, voice_preset: voice }); };
  return <div className="creative-workspace voice-studio-workspace"><div className="creative-heading"><div><span className="eyebrow-label">Performance director</span><h1>Shape the voice before it becomes audio.</h1><p className="desk-intro">Build a voice preset, audition it, and carry the decision directly into the next Story Studio brief.</p></div><div className="voice-brief-chip"><span>Current brief voice</span><strong>{brief.voice_preset}</strong></div></div><div className="voice-studio-grid"><section className="voice-console"><h2>Voice palette</h2><div className="voice-card-grid">{voiceOptions.map(([value, label]) => <button type="button" className={settings.tts_voice_preset === value ? "voice-card selected" : "voice-card"} key={value} onClick={() => selectVoice(value)}><span className="voice-avatar"><Volume2 size={17}/></span><span><strong>{label.split(" · ")[0]}</strong><small>{label.split(" · ")[1] || "Studio voice"}</small></span>{settings.tts_voice_preset === value && <span className="led green"/>}</button>)}</div><div className="voice-controls"><label>Performance speed<input type="range" min="0.5" max="2" step="0.05" value={settings.tts_speed} onChange={(event) => update({ tts_speed: Number(event.target.value) })}/><b>{settings.tts_speed.toFixed(2)}×</b></label><label>Narration direction<select value={settings.narration_style || ""} onChange={(event) => { update({ narration_style: event.target.value }); onBriefChange({ ...brief, narration_style: event.target.value }); }}>{narrationOptions.map(([value, label]) => <option key={value || "default"} value={value}>{label}</option>)}</select></label></div><div className="voice-actions"><button className="outline-button" disabled={auditionBusy} onClick={() => void onAudition()}>{auditionBusy ? "Generating audition..." : "Audition selected voice"}</button><button className="create" disabled={settingsBusy} onClick={() => void onSave()}>Save voice settings</button></div>{auditionUrl && <audio className="voice-audio" controls autoPlay src={auditionUrl} />}</section><aside className="voice-rail"><span className="eyebrow-label">Performance notes</span><h2>Make it consistent.</h2><p>Speed and narration direction are persisted as defaults. Story-specific choices still travel with the production brief.</p><dl><div><dt>Voice</dt><dd>{settings.tts_voice_preset}</dd></div><div><dt>Speed</dt><dd>{settings.tts_speed.toFixed(2)}×</dd></div><div><dt>Subtitles</dt><dd>Re-align after changed narration</dd></div></dl></aside></div></div>;
}

function LegacyVoiceStudioWorkspace2({ settings, brief, onBriefChange, settingsBusy, auditionBusy, auditionUrl, onSettingsChange, onAudition, onSave }: { settings?: StudioSettings; brief: GenerateInput; onBriefChange: (brief: GenerateInput) => void; settingsBusy: boolean; auditionBusy: boolean; auditionUrl?: string; onSettingsChange: (settings: StudioSettings) => void; onAudition: (input: TtsGenerateInput) => Promise<void>; onSave: () => Promise<void> }) {
  const [mode, setMode] = useState<TtsModel>("preset");
  const [voiceDescription, setVoiceDescription] = useState("A warm, cinematic storyteller with a grounded, intimate presence and clear English diction.");
  const [stylePrompt, setStylePrompt] = useState(settings?.default_style || "Speak naturally, with restrained emotion, clear phrasing, and gentle pauses between thoughts.");
  const [auditionText, setAuditionText] = useState("The road is cold. She keeps walking.");
  const [optimizeText, setOptimizeText] = useState(true);
  const [streamPreview, setStreamPreview] = useState(false);
  const [voiceSample, setVoiceSample] = useState<string>();
  const [voiceSampleName, setVoiceSampleName] = useState<string>();
  const [sampleError, setSampleError] = useState<string>();
  useEffect(() => {
    if (settings?.default_style) setStylePrompt(settings.default_style);
  }, [settings?.default_style]);
  if (!settings) return <div className="creative-workspace"><div className="migration-loading"><span className="led amber"/> Loading voice controls...</div></div>;
  const update = (patch: Partial<StudioSettings>) => onSettingsChange({ ...settings, ...patch });
  const selectVoice = (voice: string) => { update({ tts_voice_preset: voice }); onBriefChange({ ...brief, voice_preset: voice }); };
  const audioTags = ["(whispers)", "(sighs)", "(speaking faster)", "(soft pause)", "(laughs softly)", "(singing)"];
  const insertTag = (tag: string) => setAuditionText((current) => `${current.trim()} ${tag}`.trim());
  const readSample = (file?: File) => {
    if (!file) return;
    const supportedType = ["audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav"].includes(file.type) || /\.(mp3|wav)$/i.test(file.name);
    if (!supportedType) { setSampleError("Choose an MP3 or WAV sample."); return; }
    if (file.size > 7_500_000) { setSampleError("Keep the source file under 7.5 MB so the encoded sample stays under MiMo's 10 MB limit."); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const data = String(reader.result || "");
      if (data.length > 10 * 1024 * 1024) { setSampleError("The encoded sample exceeds MiMo's 10 MB limit."); return; }
      setSampleError(undefined);
      setVoiceSample(data);
      setVoiceSampleName(file.name);
    };
    reader.onerror = () => setSampleError("The sample could not be read.");
    reader.readAsDataURL(file);
  };
  const audition = () => {
    const text = auditionText.trim();
    if (!text) return;
    void onAudition({
      text,
      model: mode,
      voice_preset: mode === "preset" ? settings.tts_voice_preset : undefined,
      style: mode === "preset" || mode === "clone" ? stylePrompt : undefined,
      voice_description: mode === "design" ? voiceDescription : undefined,
      voice_sample: mode === "clone" ? voiceSample : undefined,
      optimize_text_preview: optimizeText,
      stream: mode === "preset" && streamPreview,
      speed: settings.tts_speed,
    });
  };
  return <div className="creative-workspace voice-studio-workspace"><div className="creative-heading"><div><span className="eyebrow-label">MiMo V2.5 performance director</span><h1>Design, clone, and direct the voice.</h1><p className="desk-intro">Use a built-in voice, describe a new voice, or audition a local MP3/WAV clone. Every instruction stays attached to the audition request and can be carried into the production brief.</p></div><div className="voice-brief-chip"><span>Current brief voice</span><strong>{brief.voice_preset}</strong></div></div><div className="voice-studio-grid"><section className="voice-console"><div className="section-heading"><h2>Voice mode</h2><span>MiMo V2.5 TTS</span></div><div className="mimo-mode-grid"><button type="button" className={mode === "preset" ? "mimo-mode selected" : "mimo-mode"} onClick={() => setMode("preset")}><strong>Built-in voice</strong><small>Mia, Chloe, Milo, or Dean. Fast preview available.</small></button><button type="button" className={mode === "design" ? "mimo-mode selected" : "mimo-mode"} onClick={() => setMode("design")}><strong>Voice design</strong><small>Describe the character, timbre, and delivery in 1-4 sentences.</small></button><button type="button" className={mode === "clone" ? "mimo-mode selected" : "mimo-mode"} onClick={() => setMode("clone")}><strong>Voice clone</strong><small>Replicate a voice from a private MP3 or WAV sample.</small></button></div>{mode === "preset" && <><h2>Voice palette</h2><div className="voice-card-grid">{voiceOptions.map(([value, label]) => <button type="button" className={settings.tts_voice_preset === value ? "voice-card selected" : "voice-card"} key={value} onClick={() => selectVoice(value)}><span className="voice-avatar"><Volume2 size={17}/></span><span><strong>{label.split(" Â· ")[0]}</strong><small>{label.split(" Â· ")[1] || "Studio voice"}</small></span>{settings.tts_voice_preset === value && <span className="led green"/>}</button>)}</div></>}{mode === "design" && <label className="brief-field wide mimo-textarea">Voice description<textarea value={voiceDescription} onChange={(event) => setVoiceDescription(event.target.value)} placeholder="A low, weathered voice with patient warmth, a slight northern accent, and a smile held back by exhaustion."/><small>Describe identity, personality, timbre, accent, and speaking habits. Avoid reverb, EQ, compression, or other post-processing terms.</small></label>}{mode === "clone" && <div className="clone-upload"><label className="brief-field wide">Voice sample<input type="file" accept="audio/mpeg,audio/mp3,audio/wav" onChange={(event) => readSample(event.target.files?.[0])}/><small>{voiceSampleName ? `Loaded ${voiceSampleName}` : "MP3 or WAV, under 7.5 MB source size."}</small></label>{sampleError && <p className="form-error">{sampleError}</p>}</div>}<div className="voice-controls"><label>Performance speed<input type="range" min="0.5" max="2" step="0.05" value={settings.tts_speed} onChange={(event) => update({ tts_speed: Number(event.target.value) })}/><b>{settings.tts_speed.toFixed(2)}×</b></label><label>Narration direction<select value={settings.narration_style || ""} onChange={(event) => { update({ narration_style: event.target.value }); onBriefChange({ ...brief, narration_style: event.target.value }); }}>{narrationOptions.map(([value, label]) => <option key={value || "default"} value={value}>{label}</option>)}</select></label></div><label className="brief-field wide">Director guidance<textarea value={stylePrompt} onChange={(event) => { setStylePrompt(event.target.value); update({ default_style: event.target.value }); }} placeholder="[Character] ... [Scene] ... [Guidance] ..."/><small>Natural language controls speed, emotion, role-play, dialect, breath, resonance, and scene context.</small></label><div className="tag-control"><div className="section-heading"><h2>Audio tags</h2><span>Insert into assistant text</span></div><div className="tag-list">{audioTags.map((tag) => <button type="button" className="tag-button" key={tag} onClick={() => insertTag(tag)}>{tag}</button>)}</div></div><label className="brief-field wide">Audition text<textarea value={auditionText} onChange={(event) => setAuditionText(event.target.value)} placeholder="Write a short line that matches the voice you are designing."/></label><div className="mimo-options"><label className="check-control"><input type="checkbox" checked={optimizeText} onChange={(event) => setOptimizeText(event.target.checked)}/><span>Optimize preview text</span><small>MiMo can polish the target line for a designed voice.</small></label><label className="check-control"><input type="checkbox" checked={streamPreview} disabled={mode !== "preset"} onChange={(event) => setStreamPreview(event.target.checked)}/><span>Low-latency streaming preview</span><small>{mode === "preset" ? "Built-in voices return PCM16 chunks for a faster audition." : "Available only for built-in voices; design and clone use compatibility mode."}</small></label></div><div className="voice-actions"><button className="outline-button" disabled={auditionBusy || !auditionText.trim() || (mode === "clone" && !voiceSample)} onClick={audition}>{auditionBusy ? "Generating audition..." : "Audition MiMo performance"}</button><button className="create" disabled={settingsBusy} onClick={() => void onSave()}>Save voice settings</button></div>{auditionUrl && <audio className="voice-audio" controls autoPlay src={auditionUrl} />}</section><aside className="voice-rail"><span className="eyebrow-label">Performance handoff</span><h2>Make it repeatable.</h2><p>Speed, direction, and the selected narrator are carried into the Story Studio brief. Changed narration must re-align subtitles before release.</p><dl><div><dt>Mode</dt><dd>{mode === "preset" ? "Built-in" : mode === "design" ? "Designed" : "Cloned"}</dd></div><div><dt>Voice</dt><dd>{mode === "preset" ? settings.tts_voice_preset : mode === "design" ? "Text description" : voiceSampleName || "Sample required"}</dd></div><div><dt>Speed</dt><dd>{settings.tts_speed.toFixed(2)}×</dd></div><div><dt>Audio tags</dt><dd>{audioTags.length} ready</dd></div></dl></aside></div></div>;
}

function BackgroundAudioSettings({ settings, onChange, busy, onSave }: { settings: StudioSettings; onChange: (settings: StudioSettings) => void; busy: boolean; onSave: () => void }) {
  const [trackCount, setTrackCount] = useState<number>();
  const [scanBusy, setScanBusy] = useState(false);
  const [scanError, setScanError] = useState<string>();
  const scan = async () => {
    setScanBusy(true);
    setScanError(undefined);
    try {
      const result = await api.backgroundTracks();
      setTrackCount(result.tracks.length);
    } catch (error) {
      setScanError(error instanceof Error ? error.message : "The audio folder could not be scanned.");
    } finally {
      setScanBusy(false);
    }
  };
  return <section className="background-audio-settings"><div className="inspector-title"><div><h2>Background audio library</h2><p>Use music you have rights to keep locally. Nothing from this folder is copied into the repository.</p></div><Music2 size={18}/></div><label>Local audio folder<input value={settings.background_audio_dir || ""} placeholder="D:\\Music\\Audio" onChange={(event) => onChange({ ...settings, background_audio_dir: event.target.value })}/></label><div className="background-audio-actions"><button className="outline-button" disabled={busy} onClick={onSave}>Save folder</button><button className="outline-button" disabled={scanBusy} onClick={() => void scan()}>{scanBusy ? "Scanning..." : "Scan folder"}</button>{trackCount !== undefined && <small>{trackCount} selectable track{trackCount === 1 ? "" : "s"}</small>}</div>{scanError && <small className="field-error">{scanError}</small>}</section>;
}

function ReleaseLedger({ releases, onPreview }: { releases: ProductionRelease[]; onPreview: (release: ProductionRelease) => void }) {
  return <section className="release-ledger"><div className="inspector-title"><h2>Release history</h2><small>{releases.length ? `${releases.length} recorded artifacts` : "No release artifacts"}</small></div>{releases.length ? <div className="release-list">{releases.map((release) => <article className="release-row" key={release.id}><span className={`led ${release.status === "current" ? "green" : "amber"}`}/><div><strong>{humanStatus(release.release_type)} <em>{humanStatus(release.status)}</em></strong><small>{timestamp(release.created_at)} · fingerprint {release.fingerprint.slice(0, 12)}</small><small className="release-path">{release.path}</small></div><button className="micro-button release-preview" onClick={() => onPreview(release)} title="Preview this release"><Play size={13}/></button></article>)}</div> : <p className="ledger-empty">Render or export a verified story to create its first release record.</p>}<p className="release-note">Superseded artifacts stay visible for audit and recovery. Previewing an older release never changes the current completion state.</p></section>;
}

function MigrationSummary({ readiness }: { readiness: MigrationReadiness }) {
  const summary = readiness.summary;
  return <section className="migration-summary"><div className="inspector-title"><h2>Migration readiness</h2><small>Read-only inventory</small></div><div className="migration-metrics"><span><b>{summary.migration_ready}</b><small>ready</small></span><span><b>{summary.incomplete}</b><small>incomplete</small></span><span><b>{summary.legacy_read_only}</b><small>legacy</small></span><span><b>{summary.rollback_ready}</b><small>backed up</small></span></div><p>Nothing was moved or deleted. Legacy stories remain read-only until backup, import, and rollback gates are explicitly approved.</p></section>;
}

function ReleasePlayer({ story, release, onClose }: { story: Story; release?: ProductionRelease; onClose: () => void }) {
  const video = release ? api.releaseVideo(story.id, release.id) : `/generated/${story.id}/${story.id}_full.mp4`;
  const subtitles = release ? api.releaseSubtitles(story.id, release.id) : `/generated/${story.id}/${story.id}_full.vtt`;
  return <div className="modal-scrim player-scrim" role="dialog" aria-modal="true" aria-labelledby="release-player-title"><section className="release-player metal-panel"><header className="editor-header"><div><span className="eyebrow-label">{release ? "Archived release preview" : "Canonical release"}</span><h1 id="release-player-title">{story.title}</h1><small>{release ? `${humanStatus(release.release_type)} · ${humanStatus(release.status)}` : "MP4 + timeline subtitles"}</small></div><button className="icon-button" onClick={onClose} aria-label="Close player"><X size={19}/></button></header><video controls autoPlay preload="metadata"><source src={video} type="video/mp4"/><track kind="subtitles" src={subtitles} srcLang="en" label="English" default /></video><NarrationWaveform src={video} /><p className="player-note">{release ? "This is a historical artifact. Previewing it does not restore it or change the current completion evidence." : "Playback uses the rendered release and its canonical subtitle timeline. If the release is stale, return to the editor and rebuild the approved timeline."}</p></section></div>;
}

function LegacyReleasePlayerWithAudio({ story, release, onClose }: { story: Story; release?: ProductionRelease; onClose: () => void }) {
  const video = release ? api.releaseVideo(story.id, release.id) : `/generated/${story.id}/${story.id}_full.mp4`;
  const subtitles = release ? api.releaseSubtitles(story.id, release.id) : `/generated/${story.id}/${story.id}_full.vtt`;
  const backgroundTrack = story.background_audio || fallbackBackgroundTrack;
  const backgroundSrc = `/api/background/${encodeURIComponent(backgroundTrack)}`;
  const videoRef = useRef<HTMLVideoElement>(null);
  const backgroundAudioRef = useRef<HTMLAudioElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [backgroundEnabled, setBackgroundEnabled] = useState(Boolean(backgroundTrack));
  const [backgroundVolume, setBackgroundVolume] = useState(Math.round(Math.max(0, Math.min(1, story.background_volume ?? 0.05)) * 100));
  useEffect(() => {
    if (backgroundAudioRef.current) backgroundAudioRef.current.volume = backgroundVolume / 100;
  }, [backgroundVolume]);
  useEffect(() => () => { backgroundAudioRef.current?.pause(); }, []);
  const playBackground = () => {
    if (!backgroundEnabled) return;
    void backgroundAudioRef.current?.play().catch(() => undefined);
  };
  const handlePlay = () => { playBackground(); };
  const handlePause = () => { backgroundAudioRef.current?.pause(); };
  const toggleBackground = (enabled: boolean) => {
    setBackgroundEnabled(enabled);
    if (enabled && !videoRef.current?.paused) playBackground();
    if (!enabled) backgroundAudioRef.current?.pause();
  };
  return <div className="modal-scrim player-scrim" role="dialog" aria-modal="true" aria-labelledby="release-player-title"><section className="release-player metal-panel"><header className="editor-header"><div><span className="eyebrow-label">{release ? "Archived release preview" : "Canonical release"}</span><h1 id="release-player-title">{story.title}</h1><small>{release ? `${humanStatus(release.release_type)} · ${humanStatus(release.status)}` : "MP4 + timeline subtitles"}</small></div><div className="player-tools"><div className="player-menu"><button className="icon-button" onClick={() => setMenuOpen((open) => !open)} aria-label="Player audio menu" aria-expanded={menuOpen}><MoreHorizontal size={19}/></button>{menuOpen && <div className="player-menu-popover" role="menu"><div className="player-menu-heading"><Music2 size={14}/><span>Audio bed</span><small>{backgroundEnabled ? `${backgroundVolume}%` : "off"}</small></div><label className="audio-toggle"><input type="checkbox" checked={backgroundEnabled} onChange={(event) => toggleBackground(event.target.checked)} /><span>{backgroundEnabled ? "Background audio on" : "Background audio off"}</span></label><label className="volume-control"><span><Volume1 size={14}/> Volume</span><input type="range" min="0" max="100" step="1" value={backgroundVolume} onChange={(event) => setBackgroundVolume(Number(event.target.value))} aria-label="Background audio volume" /><b>{backgroundVolume}%</b></label><small className="player-track-name">{backgroundTrack.replace(/\.[^.]+$/, "").replaceAll("-", " ")}</small></div>}</div><button className="icon-button" onClick={onClose} aria-label="Close player"><X size={19}/></button></div></header><video ref={videoRef} controls autoPlay preload="metadata" onPlay={handlePlay} onPause={handlePause} onEnded={handlePause}><source src={video} type="video/mp4"/><track kind="subtitles" src={subtitles} srcLang="en" label="English" default /></video><audio ref={backgroundAudioRef} className="background-audio" src={backgroundSrc} loop preload="metadata" onError={() => toggleBackground(false)} aria-label="Background audio" /><div className="player-audio-status"><span className={backgroundEnabled ? "led green" : "led amber"}/><span>{backgroundEnabled ? "Music bed ready" : "Music bed muted"}</span><small>Open ··· for volume</small></div><NarrationWaveform src={video} /><p className="player-note">{release ? "This is a historical artifact. Previewing it does not restore it or change the current completion evidence." : "Playback uses the rendered release and its canonical subtitle timeline. Background audio is a separate low-volume bed under the rendered narration."}</p></section></div>;
}

type BackgroundProcessing = "clean" | "smooth" | "atmosphere";

type PlayerScene = { index: number; title: string; start: number; end: number };

type BackgroundAudioGraph = {
  context: AudioContext;
  source: MediaElementAudioSourceNode;
  filter: BiquadFilterNode;
  compressor: DynamicsCompressorNode;
  gain: GainNode;
};

function buildPlayerScenes(story?: StoryDetail): PlayerScene[] {
  if (!story?.scenes?.length) return [];
  let cursor = 0;
  return story.scenes.flatMap((scene, index) => {
    const duration = Number(scene.audio_duration || 0);
    if (!Number.isFinite(duration) || duration <= 0) return [];
    const playerScene = { index, title: scene.title || `Scene ${index + 1}`, start: cursor, end: cursor + duration };
    cursor += duration;
    return [playerScene];
  });
}

function formatTrackDuration(seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "duration unknown";
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

function ReleasePlayerWithAudio({ story, release, onClose }: { story: Story; release?: ProductionRelease; onClose: () => void }) {
  const video = release ? api.releaseVideo(story.id, release.id) : `/generated/${story.id}/${story.id}_full.mp4`;
  const subtitles = release ? api.releaseSubtitles(story.id, release.id) : `/generated/${story.id}/${story.id}_full.vtt`;
  const isCanonical = release?.status === "current";
  const videoRef = useRef<HTMLVideoElement>(null);
  const backgroundAudioRef = useRef<HTMLAudioElement>(null);
  const audioGraphRef = useRef<BackgroundAudioGraph | undefined>(undefined);
  const [storyDetail, setStoryDetail] = useState<StoryDetail>();
  const [backgroundTracks, setBackgroundTracks] = useState<BackgroundTrack[]>([]);
  const [backgroundTrackName, setBackgroundTrackName] = useState(story.background_audio || fallbackBackgroundTrack);
  const [backgroundProcessing, setBackgroundProcessing] = useState<BackgroundProcessing>("smooth");
  const [menuOpen, setMenuOpen] = useState(false);
  const [backgroundEnabled, setBackgroundEnabled] = useState(Boolean(story.background_audio || fallbackBackgroundTrack));
  const [backgroundVolume, setBackgroundVolume] = useState(Math.round(Math.max(0, Math.min(1, story.background_volume ?? 0.05)) * 100));
  const [subtitlesEnabled, setSubtitlesEnabled] = useState(true);
  const [sceneIndex, setSceneIndex] = useState(0);

  useEffect(() => {
    let active = true;
    setStoryDetail(undefined);
    setBackgroundTracks([]);
    setBackgroundTrackName(story.background_audio || fallbackBackgroundTrack);
    setBackgroundEnabled(Boolean(story.background_audio || fallbackBackgroundTrack));
    setBackgroundVolume(Math.round(Math.max(0, Math.min(1, story.background_volume ?? 0.05)) * 100));
    setSceneIndex(0);
    void api.story(story.id).then((detail) => { if (active) setStoryDetail(detail); }).catch(() => undefined);
    void api.backgroundTracks().then((result) => { if (active) setBackgroundTracks(result.tracks || []); }).catch(() => undefined);
    return () => { active = false; };
  }, [story.id, release?.id]);

  const sceneBounds = buildPlayerScenes(storyDetail);
  const currentScene = sceneBounds[sceneIndex];
  const selectedTrack = backgroundTracks.find((track) => track.filename === backgroundTrackName);
  const backgroundSrc = backgroundTrackName ? `/api/background/${encodeURIComponent(backgroundTrackName)}` : undefined;

  const configureBackgroundGraph = () => {
    const graph = audioGraphRef.current;
    if (!graph) return;
    if (backgroundProcessing === "clean") {
      graph.filter.type = "allpass";
      graph.compressor.threshold.value = 0;
      graph.compressor.knee.value = 0;
      graph.compressor.ratio.value = 1;
    } else if (backgroundProcessing === "atmosphere") {
      graph.filter.type = "lowpass";
      graph.filter.frequency.value = 9000;
      graph.compressor.threshold.value = -32;
      graph.compressor.knee.value = 18;
      graph.compressor.ratio.value = 4;
    } else {
      graph.filter.type = "allpass";
      graph.compressor.threshold.value = -28;
      graph.compressor.knee.value = 18;
      graph.compressor.ratio.value = 3;
    }
    graph.compressor.attack.value = 0.01;
    graph.compressor.release.value = 0.3;
    graph.gain.gain.value = 1;
  };

  const ensureAudioGraph = () => {
    const audio = backgroundAudioRef.current;
    if (!audio || audioGraphRef.current) {
      configureBackgroundGraph();
      return;
    }
    const AudioContextConstructor = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextConstructor) return;
    const context = new AudioContextConstructor();
    const source = context.createMediaElementSource(audio);
    const filter = context.createBiquadFilter();
    const compressor = context.createDynamicsCompressor();
    const gain = context.createGain();
    source.connect(filter).connect(compressor).connect(gain).connect(context.destination);
    audioGraphRef.current = { context, source, filter, compressor, gain };
    configureBackgroundGraph();
  };

  useEffect(() => {
    if (backgroundAudioRef.current) backgroundAudioRef.current.volume = backgroundVolume / 100;
  }, [backgroundVolume]);

  useEffect(() => {
    configureBackgroundGraph();
  }, [backgroundProcessing]);

  useEffect(() => () => {
    backgroundAudioRef.current?.pause();
    void audioGraphRef.current?.context.close();
  }, []);

  const applySubtitleMode = () => {
    const track = videoRef.current?.textTracks[0];
    if (track) track.mode = subtitlesEnabled ? "showing" : "disabled";
  };

  useEffect(() => {
    applySubtitleMode();
  }, [subtitlesEnabled]);

  const playBackground = () => {
    if (!backgroundEnabled || !backgroundAudioRef.current || !backgroundSrc) return;
    ensureAudioGraph();
    const context = audioGraphRef.current?.context;
    if (context?.state === "suspended") void context.resume();
    void backgroundAudioRef.current.play().catch(() => undefined);
  };

  const handlePlay = () => { playBackground(); };
  const handlePause = () => { backgroundAudioRef.current?.pause(); };

  const toggleBackground = (enabled: boolean) => {
    setBackgroundEnabled(enabled);
    if (enabled && !videoRef.current?.paused) playBackground();
    if (!enabled) backgroundAudioRef.current?.pause();
  };

  const selectBackgroundTrack = (filename: string) => {
    setBackgroundTrackName(filename);
    setBackgroundEnabled(Boolean(filename));
    const audio = backgroundAudioRef.current;
    if (!audio) return;
    audio.load();
    if (!videoRef.current?.paused) void audio.play().catch(() => undefined);
  };

  const jumpScene = (offset: number) => {
    const videoElement = videoRef.current;
    if (!videoElement || !sceneBounds.length) return;
    const nextIndex = Math.max(0, Math.min(sceneBounds.length - 1, sceneIndex + offset));
    if (nextIndex === sceneIndex) return;
    const wasPlaying = !videoElement.paused;
    videoElement.currentTime = sceneBounds[nextIndex].start;
    setSceneIndex(nextIndex);
    if (wasPlaying) void videoElement.play().catch(() => undefined);
  };

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    const mediaSession = navigator.mediaSession;
    const setSceneAction = (action: MediaSessionAction, handler: (() => void) | null) => {
      try {
        mediaSession.setActionHandler(action, handler);
      } catch {
        // Some browsers expose Media Session without supporting every action.
      }
    };
    setSceneAction("previoustrack", () => jumpScene(-1));
    setSceneAction("nexttrack", () => jumpScene(1));
    return () => {
      setSceneAction("previoustrack", null);
      setSceneAction("nexttrack", null);
    };
  }, [sceneIndex, sceneBounds.length]);

  useEffect(() => {
    if (!("mediaSession" in navigator) || !("MediaMetadata" in window)) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: story.title,
      artist: currentScene?.title || "FantaSee Studio",
      album: isCanonical ? "Canonical release" : "Archived release",
    });
  }, [currentScene?.title, release, story.title]);

  const handleTimeUpdate = () => {
    const time = videoRef.current?.currentTime;
    if (time === undefined || !sceneBounds.length) return;
    const foundIndex = sceneBounds.findIndex((scene) => time >= scene.start && time < scene.end);
    const nextIndex = foundIndex >= 0 ? foundIndex : time >= sceneBounds[sceneBounds.length - 1].end ? sceneBounds.length - 1 : 0;
    if (nextIndex !== sceneIndex) setSceneIndex(nextIndex);
  };

  const processingLabel = backgroundProcessing === "clean" ? "Clean" : backgroundProcessing === "atmosphere" ? "Atmosphere" : "Smooth bed";
  return <div className="modal-scrim player-scrim" role="dialog" aria-modal="true" aria-labelledby="release-player-title">
    <section className="release-player metal-panel">
      <header className="editor-header">
        <div><span className="eyebrow-label">{isCanonical ? "Canonical release" : "Archived release preview"}</span><h1 id="release-player-title">{story.title}</h1><small>{release ? `${humanStatus(release.release_type)} Â· ${humanStatus(release.status)}` : "MP4 + timeline subtitles"}</small></div>
        <div className="player-tools">
          <div className="player-menu">
            <button className="icon-button" onClick={() => setMenuOpen((open) => !open)} aria-label="Player options" aria-expanded={menuOpen}><MoreHorizontal size={19}/></button>
            {menuOpen && <div className="player-menu-popover" role="menu">
              <div className="player-menu-heading"><Music2 size={14}/><span>Player options</span></div>
              <label className="audio-toggle"><input type="checkbox" checked={backgroundEnabled} onChange={(event) => toggleBackground(event.target.checked)} /><span>{backgroundEnabled ? "Background audio on" : "Background audio off"}</span></label>
              <label className="player-select"><span>Background track</span><select value={backgroundTrackName} onChange={(event) => selectBackgroundTrack(event.target.value)} aria-label="Background track"><option value="">No background track</option>{backgroundTracks.map((track) => <option value={track.filename} key={track.filename}>{track.filename.replace(/\.[^.]+$/, "").replaceAll("-", " ")} ({formatTrackDuration(track.duration_seconds)})</option>)}{!backgroundTracks.some((track) => track.filename === backgroundTrackName) && backgroundTrackName && <option value={backgroundTrackName}>{backgroundTrackName.replace(/\.[^.]+$/, "").replaceAll("-", " ")}</option>}</select></label>
              <label className="player-select"><span>Background processing</span><select value={backgroundProcessing} onChange={(event) => setBackgroundProcessing(event.target.value as BackgroundProcessing)} aria-label="Background processing"><option value="smooth">Smooth bed</option><option value="clean">Clean</option><option value="atmosphere">Atmosphere</option></select></label>
              <label className="volume-control"><span><Volume1 size={14}/> Bed volume</span><input type="range" min="0" max="100" step="1" value={backgroundVolume} onChange={(event) => setBackgroundVolume(Number(event.target.value))} aria-label="Background audio volume" /><b>{backgroundVolume}%</b></label>
              <label className="audio-toggle"><input type="checkbox" checked={subtitlesEnabled} onChange={(event) => setSubtitlesEnabled(event.target.checked)} /><span>Subtitles {subtitlesEnabled ? "on" : "off"}</span></label>
              <small className="player-track-name">{selectedTrack ? `${selectedTrack.tags.join(" Â· ")} Â· ${formatTrackDuration(selectedTrack.duration_seconds)}` : backgroundTrackName ? backgroundTrackName.replace(/\.[^.]+$/, "").replaceAll("-", " ") : "No background track"}</small>
            </div>}
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close player"><X size={19}/></button>
        </div>
      </header>
      <video ref={videoRef} controls autoPlay preload="metadata" onLoadedMetadata={applySubtitleMode} onTimeUpdate={handleTimeUpdate} onPlay={handlePlay} onPause={handlePause} onEnded={handlePause}>
        <source src={video} type="video/mp4"/><track kind="subtitles" src={subtitles} srcLang="en" label="English" default />
      </video>
      <audio ref={backgroundAudioRef} className="background-audio" src={backgroundSrc} loop preload="metadata" onError={() => toggleBackground(false)} aria-label="Background audio" />
      <div className="player-audio-status"><span className={backgroundEnabled ? "led green" : "led amber"}/><span>{backgroundEnabled ? `${processingLabel} bed ready` : "Music bed muted"}</span><small>Open ... for audio and subtitle controls</small></div>
      <p className="player-note">{isCanonical ? "Playback uses the rendered release and its canonical subtitle timeline. Narration is loudness-normalized during generation and final render." : "This is a historical artifact. Previewing it does not restore it or change the current completion evidence."}</p>
    </section>
  </div>;
}

function SceneWaveformDock({ story, sceneIndex }: { story?: StoryDetail; sceneIndex: number }) {
  const scene = story?.scenes[sceneIndex];
  return <aside className="scene-waveform-dock" aria-label="Scene narration waveform"><div><span>Scene narration</span><small>{scene?.audio_duration ? `${scene.audio_duration.toFixed(1)}s` : "pending"}</small></div>{scene?.audio_filename ? <NarrationWaveform src={`/generated/${story!.id}/${scene.audio_filename}`} /> : <small>Generate narration to inspect its waveform.</small>}</aside>;
}

function NarrationWaveform({ src }: { src?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !src) return;
    let disposed = false;
    let context: AudioContext | undefined;
    const draw = (data: Float32Array) => {
      const target = canvas.getContext("2d");
      if (!target) return;
      const width = canvas.width = Math.max(240, Math.floor(canvas.clientWidth * 2));
      const height = canvas.height = 64;
      target.clearRect(0, 0, width, height);
      target.fillStyle = "#b97935";
      const step = Math.max(1, Math.floor(data.length / width));
      for (let x = 0; x < width; x += 1) {
        let peak = 0;
        for (let index = x * step; index < Math.min(data.length, (x + 1) * step); index += 1) peak = Math.max(peak, Math.abs(data[index]));
        const bar = Math.max(1, peak * height * 0.9);
        target.fillRect(x, (height - bar) / 2, 1, bar);
      }
    };
    void fetch(src).then((response) => response.arrayBuffer()).then((bytes) => {
      context = new AudioContext();
      return context.decodeAudioData(bytes);
    }).then((audio) => { if (!disposed) draw(audio.getChannelData(0)); }).catch(() => undefined);
    return () => { disposed = true; void context?.close(); };
  }, [src]);
  return <canvas className="narration-waveform" ref={canvasRef} aria-label="Narration waveform" />;
}

function WorkerConsole({ workers, busy, onClose, onRefresh, onSpawn, onKill, onRestart }: { workers: ComfyWorker[]; busy: boolean; onClose: () => void; onRefresh: () => void; onSpawn: (kind: "cpu" | "gpu") => void; onKill: (url: string) => void; onRestart: () => void }) {
  const [selectedUrl, setSelectedUrl] = useState<string>();
  useEffect(() => {
    setSelectedUrl((current) => current && workers.some((worker) => worker.url === current) ? current : workers[0]?.url);
  }, [workers]);
  const selected = workers.find((worker) => worker.url === selectedUrl);
  return <div className="modal-scrim" role="dialog" aria-modal="true" aria-labelledby="worker-console-title"><section className="worker-console metal-panel">
    <header className="editor-header"><div><span className="eyebrow-label">Production hardware</span><h1 id="worker-console-title">ComfyUI workers</h1><small>Select a live instance to inspect or stop it.</small></div><button className="icon-button" onClick={onClose} aria-label="Close worker controls"><X size={19}/></button></header>
    <div className="worker-console-body"><div className="worker-selector">{workers.length ? workers.map((worker) => <button key={worker.url} className={worker.url === selectedUrl ? "worker-option selected" : "worker-option"} onClick={() => setSelectedUrl(worker.url)}><span className={`led ${worker.running === false ? "red" : "green"}`}/><strong>{workerLabel(worker)}</strong><small>{worker.url}</small><b>{worker.running === false ? "offline" : `${worker.queue_running || 0} running · ${worker.queue_remaining || 0} waiting`}</b><div className="worker-option-usage"><UsageLeds label="GPU" value={worker.telemetry?.gpu_percent} source={worker.telemetry?.gpu_source || worker.telemetry?.source}/><UsageLeds label="CPU" value={worker.telemetry?.cpu_percent} source={worker.telemetry?.cpu_source}/></div></button>) : <p className="ledger-empty">No ComfyUI workers are reporting.</p>}</div><aside className="worker-detail"><div className="eyebrow"><span>Selected instance</span><button className="micro-button" onClick={onRefresh} disabled={busy} aria-label="Refresh workers"><RefreshCw size={13}/></button></div>{selected ? <><h2>{workerLabel(selected)}</h2><p>{selected.url}</p><div className="worker-detail-usage"><UsageLeds label="GPU" value={selected.telemetry?.gpu_percent} source={selected.telemetry?.gpu_source || selected.telemetry?.source}/><UsageLeds label="CPU" value={selected.telemetry?.cpu_percent} source={selected.telemetry?.cpu_source}/></div><dl className="settings-ledger"><div><dt>Process</dt><dd>{selected.pid || "unknown"}</dd></div><div><dt>Queue</dt><dd>{selected.queue_running || 0} active / {selected.queue_remaining || 0} waiting</dd></div><div><dt>Device</dt><dd>{selected.device || selected.kind || "unknown"}</dd></div></dl><button className="danger" disabled={busy || selected.running === false || !selected.url} onClick={() => selected.url && onKill(selected.url)}><Square size={15}/> Kill selected worker</button></> : <p>Select a worker to see its process and queue.</p>}</aside></div>
    <footer className="modal-actions"><button className="outline-button" disabled={busy} onClick={() => onSpawn("cpu")}><Cpu size={15}/> Spawn CPU</button><button className="outline-button" disabled={busy} onClick={() => onSpawn("gpu")}><Sparkles size={15}/> Spawn GPU</button><button className="danger" disabled={busy} onClick={onRestart}>Restart all</button><button className="create" onClick={onClose}>Close</button></footer>
  </section></div>;
}

function CandidateGallery({ assets, busy, onApprove }: { assets: ShotAsset[]; busy: boolean; onApprove: (asset: ShotAsset) => void }) {
  const [previewId, setPreviewId] = useState<string>();
  const preview = assets.find((asset) => asset.id === previewId) || assets[0];
  return <div className="candidate-list"><div className="candidate-heading"><b>Image candidates</b><small>{assets.length} generated {assets.length === 1 ? "frame" : "frames"}</small></div>{preview?.url && <img className="candidate-preview" src={preview.url} alt="Selected generated candidate" />}{assets.map((asset) => <button type="button" className={asset.id === preview?.id ? "candidate-card selected" : "candidate-card"} key={asset.id} onClick={() => setPreviewId(asset.id)}><span className="candidate-thumb">{asset.url ? <img src={asset.url} alt="" /> : <Image size={14}/>}</span><span className="candidate-meta"><strong>{asset.status}</strong><small>{asset.filename}</small></span>{asset.status !== "approved" && <span className="candidate-approve" onClick={(event) => { event.stopPropagation(); onApprove(asset); }}>Approve</span>}</button>)}</div>;
}

function SceneImageControls({ story, sceneIndex, busy, onStoryRefresh, onAction }: { story?: StoryDetail; sceneIndex: number; busy: boolean; onStoryRefresh: () => Promise<void>; onAction: (action: () => Promise<unknown>, message: string) => void }) {
  const [count, setCount] = useState(1);
  const [placement, setPlacement] = useState("end");
  const scene = story?.scenes[sceneIndex];
  if (!story || !scene) return null;
  const request = (mode: "director" | "manual") => onAction(async () => {
    const result = await api.addSceneImage(story.id, sceneIndex, { mode, count, position: placement === "end" ? undefined : Number(placement) });
    await onStoryRefresh();
    return result;
  }, `${count} image${count === 1 ? "" : "s"} added with ${mode === "director" ? "director placement" : "manual placement"}.`);
  return <aside className="scene-image-controls metal-panel"><div><span className="eyebrow-label">Visual rhythm</span><h3>Add more images</h3><p>Let the Director place a new visual beat against the shot plan, or insert it yourself.</p></div><label>Images to add<select value={count} onChange={(event) => setCount(Number(event.target.value))}><option value={1}>1 image</option><option value={2}>2 images</option><option value={3}>3 images</option><option value={4}>4 images</option></select></label><label>Manual insertion<select value={placement} onChange={(event) => setPlacement(event.target.value)}><option value="end">At the end</option>{(scene.image_filenames || []).map((_, index) => <option value={String(index)} key={index}>Before image {index + 1}</option>)}</select></label><button type="button" className="outline-button" disabled={busy} onClick={() => request("director")}><Wand2 size={15}/> Director placement</button><button type="button" className="outline-button" disabled={busy} onClick={() => request("manual")}><Plus size={15}/> Place manually</button><small>{scene.image_filenames?.length || 0} images currently in this scene. New artwork marks the release timeline stale until rebuilt.</small></aside>;
}

function StoryEditor({ story, sceneIndex, busy, onClose, onSelectScene, onStoryRefresh, onAction }: { story?: StoryDetail; sceneIndex: number; busy: boolean; onClose: () => void; onSelectScene: (index: number) => void; onStoryRefresh: () => Promise<void>; onAction: (action: () => Promise<unknown>, message: string) => void }) {
  const [shots, setShots] = useState<SemanticShot[]>([]);
  const [sceneDraft, setSceneDraft] = useState<Scene>();
  const [selectedShot, setSelectedShot] = useState<SemanticShot>();
  const [shotContext, setShotContext] = useState("");
  const [shotAssets, setShotAssets] = useState<ShotAsset[]>([]);
  const [shotRevisions, setShotRevisions] = useState<number[]>([]);
  const [shotLocked, setShotLocked] = useState(false);
  const [timelineStatus, setTimelineStatus] = useState<string>();
  const [timelineShots, setTimelineShots] = useState<TimelineShot[]>([]);
  const [subtitleCues, setSubtitleCues] = useState<SubtitleCue[]>([]);
  const [dragShotId, setDragShotId] = useState<string>();
  useEffect(() => {
    if (!story) { setShots([]); setSceneDraft(undefined); setSelectedShot(undefined); setShotAssets([]); setShotRevisions([]); setTimelineStatus(undefined); setTimelineShots([]); setSubtitleCues([]); return; }
    setSceneDraft(story.scenes[sceneIndex]);
    setSelectedShot(undefined); setShotAssets([]); setShotRevisions([]); setTimelineStatus(undefined); setTimelineShots([]); setSubtitleCues([]); setShotLocked(false); setDragShotId(undefined);
    void api.sceneShots(story.id, sceneIndex).then((result) => setShots(result.shots)).catch(() => setShots([]));
    void api.shotRevisions(story.id, sceneIndex).then((result) => setShotRevisions(result.revisions)).catch(() => setShotRevisions([]));
    void api.storyTimeline(story.id).then((result) => setTimelineShots(result.shot_segments)).catch(() => setTimelineShots([]));
    void api.sceneSubtitles(story.id, sceneIndex).then((result) => setSubtitleCues(result.segments || [])).catch(() => setSubtitleCues([]));
  }, [story, sceneIndex]);
  const scene = sceneDraft || story?.scenes[sceneIndex];
  const narration = scene?.narration || scene?.narration_text || scene?.narrative || "";
  const prompt = scene?.prompt || "";
  const draftChanged = Boolean(scene && ((sceneDraft?.narration || sceneDraft?.narration_text || "") !== (story?.scenes[sceneIndex]?.narration || story?.scenes[sceneIndex]?.narration_text || "") || (sceneDraft?.prompt || "") !== (story?.scenes[sceneIndex]?.prompt || "")));
  const regenerateDraft = () => onAction(async () => {
    const original = story!.scenes[sceneIndex];
    const originalNarration = original.narration || original.narration_text || "";
    const narrationChanged = narration !== originalNarration;
    const promptChanged = prompt !== (original.prompt || "");
    if (narrationChanged || promptChanged) await api.updateScene(story!.id, sceneIndex, { narration, prompt });
    const rebuilt = await api.regenerateScene(story!.id, sceneIndex, { regenerate_audio: narrationChanged, regenerate_images: promptChanged });
    setSceneDraft(rebuilt.scene);
    const subtitles = await api.sceneSubtitles(story!.id, sceneIndex).catch(() => ({ segments: [] as SubtitleCue[] }));
    setSubtitleCues(subtitles.segments || []);
    await onStoryRefresh();
    return rebuilt;
  }, `Scene ${sceneIndex + 1} updated; changed outputs and subtitle alignment are current.`);
  const selectShot = (shot: SemanticShot) => { setSelectedShot(shot); setShotLocked(false); setShotContext(shot.visual_context); void api.shotAssets(story!.id, sceneIndex, shot.id).then((result) => setShotAssets(result.assets)).catch(() => setShotAssets([])); };
  const reorderShot = (targetId: string) => {
    if (!dragShotId || dragShotId === targetId) return;
    const ids = shots.map((shot) => shot.id);
    const from = ids.indexOf(dragShotId);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return;
    ids.splice(from, 1);
    ids.splice(to, 0, dragShotId);
    onAction(async () => {
      const result = await api.reorderSceneShots(story!.id, sceneIndex, ids);
      setShots(result.shots);
      setShotRevisions((current) => [result.revision, ...current]);
      setTimelineShots([]);
      setTimelineStatus("Shot order saved. Rebuild the canonical timeline before release.");
    }, "Shot order saved as a new revision; release timeline marked stale.");
    setDragShotId(undefined);
  };
  const moveShotBy = (shotId: string, offset: number) => {
    const ids = shots.map((shot) => shot.id);
    const from = ids.indexOf(shotId);
    const target = from + offset;
    if (from < 0 || target < 0 || target >= ids.length) return;
    ids.splice(from, 1);
    ids.splice(target, 0, shotId);
    onAction(async () => {
      const result = await api.reorderSceneShots(story!.id, sceneIndex, ids);
      setShots(result.shots);
      setShotRevisions((current) => [result.revision, ...current]);
      setTimelineShots([]);
      setTimelineStatus("Shot order saved. Rebuild the canonical timeline before release.");
    }, `Moved shot ${from + 1} ${offset < 0 ? "up" : "down"}; release timeline marked stale.`);
    setSelectedShot(shots.find((shot) => shot.id === shotId));
  };
  const timelineDuration = Math.max(1, ...timelineShots.map((segment) => segment.end));
  return <div className="editor-scrim" role="dialog" aria-modal="true" aria-labelledby="story-editor-title"><section className="story-editor metal-panel">{story && scene ? <>
    <header className="editor-header"><div><span className="eyebrow-label">Story editor</span><h1 id="story-editor-title">{story.title}</h1><small>Scene {String(sceneIndex + 1).padStart(2, "0")} of {story.scenes.length}</small></div><button className="icon-button" onClick={onClose} aria-label="Close editor"><X size={19}/></button></header>
    <div className="editor-body"><aside className="scene-strip"><h3>Scenes</h3>{story.scenes.map((item, index) => <button key={`${item.title}-${index}`} className={index === sceneIndex ? "scene-chip active" : "scene-chip"} onClick={() => onSelectScene(index)}><span>{String(index + 1).padStart(2, "0")}</span><strong>{item.title || `Scene ${index + 1}`}</strong><small>{item.image_filenames?.length || 0} images</small></button>)}</aside>
      <main className="scene-workbench"><div className="scene-kicker">{scene.title || `Scene ${sceneIndex + 1}`}</div><div className="shot-canvas">{scene.image_filenames?.[0] ? <img src={`/generated/${story.id}/${scene.image_filenames[0]}`} alt="" onError={(event) => { event.currentTarget.style.display = "none"; }}/> : <div><Image size={34}/><p>No approved scene artwork</p></div>}<span className="canvas-label">Primary visual beat</span></div><div className="editor-columns"><section><h3>Narration</h3><textarea className="editor-textarea narration-copy" value={narration} onChange={(event) => setSceneDraft((current) => ({ ...(current || scene), narration: event.target.value, narration_text: event.target.value }))} /><div className="audio-review">{scene.audio_filename ? <audio controls preload="metadata" src={`/generated/${story.id}/${scene.audio_filename}`} /> : <small>Narration audio is pending rebuild.</small>}<small>{scene.stale_outputs?.includes("audio") || scene.stale_outputs?.includes("subtitles") ? "Audio and subtitles need rebuilding after this edit." : `${scene.audio_duration ? scene.audio_duration.toFixed(1) : "--"}s aligned narration`}</small></div><div className="subtitle-inspector"><div className="subtitle-heading"><h3>Subtitle alignment</h3><small>{subtitleCues.length ? `${subtitleCues.length} Whisper cues` : "No aligned cues"}</small></div>{subtitleCues.length ? <>{subtitleCues.map((cue, index) => <div className="subtitle-cue" key={`${cue.start}-${index}`}><span>{cue.start.toFixed(1)}–{cue.end.toFixed(1)}s</span><strong>{cue.text}</strong></div>)}</> : <p>Regenerate the scene to align subtitles to the current audio fingerprint.</p>}</div></section><section><h3>Visual direction</h3><textarea className="editor-textarea prompt-copy" value={prompt} onChange={(event) => setSceneDraft((current) => ({ ...(current || scene), prompt: event.target.value }))} /></section></div><div className="editor-actions"><button className="create" disabled={busy || !draftChanged} onClick={regenerateDraft}><RefreshCw size={15}/> Regenerate changed outputs</button><button className="outline-button" disabled={busy} onClick={() => onAction(async () => { const rebuilt = await api.regenerateScene(story.id, sceneIndex); setSceneDraft(rebuilt.scene); const subtitles = await api.sceneSubtitles(story.id, sceneIndex).catch(() => ({ segments: [] as SubtitleCue[] })); setSubtitleCues(subtitles.segments || []); await onStoryRefresh(); return rebuilt; }, `Scene ${sceneIndex + 1} is regenerating its artwork and narration.`)}><RefreshCw size={15}/> Regenerate scene</button><button className="outline-button" disabled={busy} onClick={() => onAction(() => api.addSceneImage(story.id, sceneIndex), `One additional image has been requested for scene ${sceneIndex + 1}.`)}><Plus size={15}/> Add visual beat</button></div></main>
      <aside className="scene-inspector"><div className="inspector-title"><h3>Shot plan</h3><button className="micro-button" disabled={busy} title="Plan semantic shots" onClick={() => onAction(async () => { const result = await api.planSceneShots(story.id, sceneIndex); setShots(result.shots); setShotRevisions((current) => [result.revision, ...current]); }, `Stored semantic shot plan for scene ${sceneIndex + 1}.`)}><Plus size={13}/></button></div>{shots.length ? shots.map((shot) => <button draggable aria-grabbed={dragShotId === shot.id} className={selectedShot?.id === shot.id ? "shot-card selected" : "shot-card"} key={shot.id} onClick={() => selectShot(shot)} onKeyDown={(event) => { if (event.key === "ArrowUp") { event.preventDefault(); moveShotBy(shot.id, -1); } if (event.key === "ArrowDown") { event.preventDefault(); moveShotBy(shot.id, 1); } }} onDragStart={() => setDragShotId(shot.id)} onDragOver={(event) => event.preventDefault()} onDrop={() => reorderShot(shot.id)} title="Drag to reorder this shot, or use Arrow Up/Down"><span className="led green"/><strong>{String(shot.order).padStart(2, "0")} · {shot.shot_type}</strong><small>{shot.purpose} · {shot.duration_seconds.toFixed(1)}s</small></button>) : <div className="shot-card"><span className="led amber"/><strong>No semantic plan yet</strong><small>Use + to derive ordered visual beats from this scene's narration and direction.</small></div>}
        {shots.length > 0 && <div className="timeline-control"><button className="outline-button" disabled={busy} onClick={() => onAction(async () => { const result = await api.buildStoryShotTimeline(story.id); setTimelineShots(result.segments as TimelineShot[]); setTimelineStatus(`${result.segments.length} approved shots placed on the full narration timeline.`); }, "Built the approved visual timeline for the full story.")}>Build release timeline</button><button className="outline-button" disabled={busy || timelineShots.length === 0} onClick={() => onAction(() => api.renderStory(story.id), "Approved timeline render completed or was rejected by the evidence gate.")}>Render MP4</button><button className="outline-button" disabled={busy} onClick={() => onAction(() => api.exportPlex(story.id), "Plex export requested; the completion gate will report its result.")}>Export Plex</button>{timelineStatus && <small>{timelineStatus}</small>}</div>}
        {selectedShot && <div className="shot-edit"><label>Revise visual context<textarea value={shotContext} onChange={(event) => setShotContext(event.target.value)} /></label><button className="outline-button" disabled={busy || !shotContext.trim()} onClick={() => onAction(async () => { const result = await api.reviseSceneShot(story.id, sceneIndex, selectedShot.id, shotContext); setShots(result.shots); setShotRevisions((current) => [result.revision, ...current]); setSelectedShot(undefined); }, `Created a new revision for shot ${selectedShot.order}.`)}><RefreshCw size={14}/> Save shot revision</button><button className="outline-button" disabled={busy} onClick={() => onAction(() => api.generateSceneShot(story.id, sceneIndex, selectedShot.id), `GPU image job queued for shot ${selectedShot.order}.`)}><Image size={14}/> Generate this shot</button>{shotAssets.length > 0 && <CandidateGallery assets={shotAssets} busy={busy} onApprove={(asset) => onAction(async () => { await api.approveShotAsset(story.id, sceneIndex, selectedShot.id, asset.id); const result = await api.shotAssets(story.id, sceneIndex, selectedShot.id); setShotAssets(result.assets); }, "Approved this shot image candidate.")} />}</div>}{shotRevisions.length > 1 && <div className="revision-list"><b>Plan history</b>{shotRevisions.slice(1).map((revision) => <button key={revision} disabled={busy} onClick={() => onAction(async () => { const result = await api.restoreShotRevision(story.id, sceneIndex, revision); setShots(result.shots); setShotRevisions((current) => [result.revision, ...current]); setSelectedShot(undefined); }, `Restored plan revision ${revision} as a new current revision.`)}>Restore r{revision}</button>)}</div>}<h3>Continuity</h3><p>Changes stay contained to this scene. The release is marked stale until its media evidence is rebuilt.</p><h3>Evidence</h3><dl><div><dt>Images</dt><dd>{scene.image_filenames?.length || 0}</dd></div><div><dt>Duration</dt><dd>{scene.audio_duration ? `${scene.audio_duration.toFixed(1)}s` : "pending"}</dd></div></dl></aside>
    </div></> : <div className="empty-state"><LoaderCircle className="spin" size={30}/><p>Loading story workstation...</p><button className="outline-button" onClick={onClose}>Close</button></div>}{story && scene && timelineShots.length > 0 && <div className="timeline-rack"><header><span>Canonical visual timeline</span><span>{timelineShots.length} approved shots</span></header><div className="timeline-track">{timelineShots.map((segment) => <i key={segment.shot_id} style={{ left: `${segment.start / timelineDuration * 100}%`, width: `${Math.max(1, (segment.end - segment.start) / timelineDuration * 100)}%` }}><span>{segment.shot_id}</span></i>)}</div></div>}{story && scene && selectedShot && <button className="shot-lock-float" disabled={busy} onClick={() => onAction(async () => { const result = await api.lockSceneShot(story.id, sceneIndex, selectedShot.id, !shotLocked); setShotLocked(result.locked); }, `${shotLocked ? "Unlocked" : "Locked"} shot ${selectedShot.order}.`)}>{shotLocked ? "Unlock selected shot" : "Lock selected shot"}</button>}</section></div>;
}

function ProductionActivityLane({ activity }: { activity: ProductionActivity }) {
  const progress = Math.round(activity.progress * 100);
  const working = ["running", "leased"].includes(activity.status);
  const waiting = ["queued", "retryable"].includes(activity.status);
  return <article className="production-activity-card"><div className="activity-heading"><span className={`led ${working ? "blue live" : waiting ? "amber" : runLedTone(activity.status)}`}/><strong>{activity.role}</strong><small>{activity.stage}</small></div><div className="activity-story" title={activity.story}>{activity.story}</div><p title={activity.message}>{activity.message}</p><div className="activity-progress"><div className="progress-track"><i style={{ width: `${progress}%` }}/></div><b>{progress}%</b></div>{activity.workerId && <small className="activity-worker">Worker · {activity.workerId}</small>}</article>;
}

function WorkerLane({ worker, jobs, busy, empty, onSpawn, onKill }: { worker?: Worker | ComfyWorker; jobs: ProductionJob[]; busy: boolean; empty?: boolean; onSpawn: () => void; onKill?: () => void }) {
  const productionWorker = worker as Worker | undefined;
  const comfyWorker = worker as ComfyWorker | undefined;
  const runningJob = jobs.find((job) => job.id === productionWorker?.current_job_id || job.worker_id === productionWorker?.id);
  const comfyRunning = (comfyWorker?.queue_running || 0) > 0;
  const progress = Math.round((runningJob?.progress || 0) * 100);
  const telemetry = worker as ComfyWorker | undefined;
  const storyName = runningJob ? jobStoryName(runningJob) : comfyRunning ? "Artwork render" : "No story assigned";
  const taskMessage = runningJob?.message || (comfyRunning ? `${comfyWorker?.queue_running} ComfyUI workflow${comfyWorker?.queue_running === 1 ? "" : "s"} rendering` : empty ? "Awaiting assignment" : "Standing by for an artwork job");
  return <article className="worker-lane metal-panel"><div className="worker-title"><span className={empty ? "led amber" : comfyRunning || runningJob ? "led blue live" : "led green"}/><h2>{empty ? "Worker bay available" : workerLabel(worker!)}</h2><small>{empty ? "awaiting assignment" : comfyRunning || runningJob ? "rendering" : "signal live · idle"}</small></div><div className="lane-task"><span>Assignment</span><strong title={storyName}>{empty ? "No worker in this lane" : storyName}</strong><small>{taskMessage} · queue {comfyWorker?.queue_remaining ?? jobs.filter((job) => ["queued", "running"].includes(job.status)).length}</small></div><div className="meter"><span>Progress</span><div className="progress-track"><i style={{width: `${progress}%`}}/></div><b>{comfyRunning && !runningJob ? "live" : `${progress}%`}</b></div><div className="worker-usage"><UsageLeds label="GPU" value={telemetry?.telemetry?.gpu_percent} source={telemetry?.telemetry?.gpu_source || telemetry?.telemetry?.source}/><UsageLeds label="CPU" value={telemetry?.telemetry?.cpu_percent} source={telemetry?.telemetry?.cpu_source}/></div><div className="lane-actions">{empty ? <button disabled={busy} onClick={onSpawn}><Plus size={17}/> Start GPU</button> : <><button disabled={busy} onClick={onSpawn} title="Start an additional worker"><Plus size={17}/></button>{onKill && <button disabled={busy} onClick={onKill} title="Stop this selected worker"><X size={17}/></button>}</>}</div></article>;
}
