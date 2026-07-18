export type Story = {
  id: string;
  title: string;
  description?: string;
  story_concept?: string;
  status?: string;
  style?: string;
  tone?: string;
  voice_preset?: string;
  narration_style?: string;
  characters?: string;
  world_context?: string;
  voice_assignments?: string;
  critic_rating?: number;
  rating?: number;
  review?: Record<string, unknown>;
  pipeline?: Record<string, unknown>;
  created_at?: string | number;
  updated_at?: string | number;
  scene_count?: number;
  num_scenes?: number;
  images_per_scene?: number;
  scene_art_urls?: string[];
  cover_image_url?: string;
  hero_image?: string;
  background_audio?: string;
  background_volume?: number;
  completion?: Record<string, unknown>;
};

export type Scene = {
  title?: string;
  narrative?: string;
  narration?: string;
  narration_text?: string;
  prompt?: string;
  image_filenames?: string[];
  image_urls?: string[];
  audio_duration?: number;
  audio_filename?: string;
  subtitle_file?: string;
  stale_outputs?: string[];
};

export type StoryDetail = Story & { scenes: Scene[] };

export type SemanticShot = {
  id: string;
  revision?: number;
  order: number;
  purpose: string;
  shot_type: string;
  duration_seconds: number;
  visual_context: string;
};

export type ShotAsset = { id: string; status: string; filename: string; url?: string; revision?: number };
export type TimelineShot = { scene_id: string; shot_id: string; asset_path: string; start: number; end: number };
export type SubtitleCue = { start: number; end: number; text: string };

export type ProductionJob = {
  id: string;
  story_id?: string;
  story_name?: string;
  job_type: string;
  status: string;
  attempts: number;
  progress: number;
  message: string;
  required_capabilities: string[];
  priority: number;
  worker_id?: string;
  worker_status?: string;
  lease_expires_at?: number;
};

export type ProductionRun = {
  id: string;
  kind: string;
  story_id?: string;
  status: string;
  progress: number;
  stage: string;
  message: string;
  created_at?: number;
  updated_at?: number;
  item_count?: number;
  worker_ids?: string[];
  worker_id?: string;
  worker_status?: string;
};

export type ProductionEvent = {
  sequence: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: number;
};

export type ProductionRelease = {
  id: string;
  story_id: string;
  release_type: string;
  fingerprint: string;
  status: string;
  path: string;
  created_at: number;
};

export type MigrationReadiness = {
  stories: Array<{ id: string; title: string; storage_root: string; complete: boolean; migration_ready: boolean; rollback_ready: boolean; risks: string[] }>;
  summary: { total: number; migration_ready: number; legacy_read_only: number; incomplete: number; rollback_ready: number };
  destructive_actions_performed: boolean;
};

export type Worker = {
  id: string;
  capabilities: string[];
  status: string;
  current_job_id?: string;
};

export type ComfyWorker = {
  url?: string;
  port?: number;
  kind?: "cpu" | "gpu" | "manual";
  pid?: number;
  name?: string;
  running?: boolean;
  device?: string;
  queue_remaining?: number;
  queue_running?: number;
  telemetry?: {
    gpu_percent?: number | null;
    cpu_percent?: number | null;
    cpu_source?: string;
    gpu_source?: string;
    source?: string;
    sampled_at?: number;
  };
};

export type RenderingMode = "basic" | "gpu" | "max";

export type BackgroundTrack = {
  filename: string;
  duration_seconds: number;
  tags: string[];
};

export type GenerateInput = {
  story_concept: string;
  style: string;
  num_scenes: number;
  images_per_scene: number;
  characters: string;
  tone: string;
  voice_preset: string;
  narration_style?: string;
  world_context?: string;
  voice_assignments?: string;
};

export type WorldCharacter = {
  id: string;
  name: string;
  role: string;
  description: string;
  voice: string;
  style: string;
  age?: string;
  alignment?: string;
  traits?: string;
  appearance?: string;
  biography?: string;
  motivation?: string;
  portrait_url?: string;
};

export type WorldRelationship = {
  id: string;
  from: string;
  to: string;
  label: string;
  status: string;
};

export type WorldArc = {
  id: string;
  title: string;
  summary: string;
  status: "planned" | "active" | "resolved";
  beats: string;
};

export type WorldKnowledgeBase = {
  title: string;
  premise: string;
  rules: string;
  factions: string;
  characters: WorldCharacter[];
  relationships: WorldRelationship[];
  arcs: WorldArc[];
  flowDiagram: string;
};

export type SeedSuggestion = { title: string; description: string; style?: string; tone?: string; characters?: string };
export type TtsModel = "preset" | "design" | "clone";
export type TtsGenerateInput = {
  text: string;
  voice_preset?: string;
  model?: TtsModel;
  style?: string;
  voice_description?: string;
  voice_sample?: string;
  optimize_text_preview?: boolean;
  stream?: boolean;
  tone?: string;
  speed?: number;
};
export type SavedVoiceProfile = {
  id: string;
  name: string;
  model: TtsModel;
  voice_preset?: string;
  voice_description?: string;
  style: string;
  narration_style?: string;
  voice_sample?: string;
  sample_name?: string;
  created_at: number;
};
export type StudioSettings = {
  comfyui_urls: string;
  comfyui_auto_spawn: boolean;
  llm_base_url: string;
  llm_api_key?: string;
  llm_model: string;
  tts_base_url: string;
  tts_api_key?: string;
  tts_model: string;
  tts_voice_preset: string;
  tts_speed: number;
  unsplash_base_url: string;
  unsplash_access_key?: string;
  plex_destination: string;
  background_audio_dir: string;
  whisper_model_size: string;
  default_scenes: number;
  default_images_per_scene: number;
  default_style: string;
  default_tone: string;
  narration_style: string;
  [key: string]: unknown;
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  return response.json() as Promise<T>;
}

export const api = {
  stories: () => request<{ stories: Story[] }>("/api/stories"),
  story: (id: string) => request<StoryDetail>(`/api/stories/${id}`),
  releases: (storyId: string) => request<{ releases: ProductionRelease[] }>(`/api/stories/${storyId}/releases`),
  migrationReadiness: () => request<MigrationReadiness>("/api/migration/readiness"),
  releaseVideo: (storyId: string, releaseId: string) => `/api/stories/${storyId}/releases/${releaseId}/video`,
  releaseSubtitles: (storyId: string, releaseId: string) => `/api/stories/${storyId}/releases/${releaseId}/subtitles`,
  updateScene: (storyId: string, sceneIndex: number, input: { title?: string; prompt?: string; narration?: string }) => request<{ status: string; scene: Scene; stale_outputs: string[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(input) }),
  runs: () => request<{ runs: ProductionRun[] }>("/api/production/runs"),
  run: (id: string) => request<{ run: ProductionRun; jobs: ProductionJob[] }>(`/api/production/runs/${id}`),
  events: (id: string, afterSequence = 0) => request<{ run_id: string; events: ProductionEvent[]; next_sequence: number }>(`/api/production/runs/${id}/events?after_sequence=${afterSequence}`),
  deleteRun: (id: string) => request<{ status: string; run_id: string; story_id: string; message: string }>(`/api/production/runs/${id}`, { method: "DELETE", headers: { "content-type": "application/json" }, body: JSON.stringify({ confirm: true }) }),
  workers: () => request<{ workers: Worker[] }>("/api/production/workers"),
  comfyWorkers: () => request<{ workers: ComfyWorker[] }>("/api/comfyui/workers"),
  backgroundTracks: () => request<{ tracks: BackgroundTrack[] }>("/api/background/tracks"),
  restartEverything: (rendering_mode?: RenderingMode) => request<{ accepted: boolean; message: string; rendering_mode: RenderingMode; services: Array<{ name: string; command: string; port: number }> }>("/api/system/restart", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(rendering_mode ? { rendering_mode } : {}) }),
  retryJob: (id: string) => request(`/api/production/jobs/${id}/retry`, { method: "POST" }),
  cancelJob: (id: string) => request(`/api/production/jobs/${id}/cancel`, { method: "POST" }),
  priorityJob: (id: string, priority: number) => request(`/api/production/jobs/${id}/priority`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ priority }) }),
  productionControl: () => request<{ admission_paused: boolean; rendering_mode: RenderingMode }>("/api/production/control"),
  setProductionControl: (input: { admission_paused?: boolean; rendering_mode?: RenderingMode }) => request<{ admission_paused: boolean; rendering_mode: RenderingMode }>("/api/production/control", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input) }),
  ttsGenerate: (input: TtsGenerateInput | string, legacyVoice?: string) => {
    const body = typeof input === "string" ? { text: input, voice_preset: legacyVoice } : input;
    return request<{ url: string; duration: number }>("/api/tts/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  },
  spawn: (kind: "cpu" | "gpu") => request(`/api/comfyui/workers/spawn-${kind}`, { method: "POST" }),
  killComfy: (url: string) => request("/api/comfyui/workers/kill", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url }) }),
  generate: (input: GenerateInput) => request<{ task_id: string; message: string; deduplicated?: boolean }>("/api/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input) }),
  generateCharacterPortrait: (input: { character_id: string; name: string; role: string; description?: string; appearance?: string; alignment?: string; traits?: string; biography?: string; world_context?: string }) => request<{ url: string; filename: string }>("/api/world/character-portrait", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input) }),
  generateCharacterPortraits: (input: { world_context?: string; characters: Array<{ character_id: string; name: string; role: string; description?: string; appearance?: string; alignment?: string; traits?: string; biography?: string }> }) => request<{ portraits: Array<{ character_id: string; url: string; filename: string }>; failed: string[] }>("/api/world/character-portraits", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input) }),
  generateStoryThumbnail: (storyId: string) => request<{ url: string; filename: string }>(`/api/world/stories/${storyId}/thumbnail`, { method: "POST" }),
  repairStory: (storyId: string) => request<{ task_id: string; status: string; message: string }>(`/api/stories/${storyId}/repair`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({}) }),
  deleteStory: (storyId: string, backup = false) => request<{ task_id?: string; status: string; story_id: string; message?: string }>(`/api/stories/${storyId}`, { method: "DELETE", headers: { "content-type": "application/json" }, body: JSON.stringify({ confirm: true, backup }) }),
  seedSuggestions: (input: Pick<GenerateInput, "story_concept" | "style" | "tone" | "characters">) => request<{ seeds: SeedSuggestion[] }>("/api/seed-suggestions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ concept: input.story_concept, style: input.style, tone: input.tone, characters: input.characters, count: 3 }) }),
  regenerateScene: (storyId: string, sceneIndex: number, options?: { regenerate_audio?: boolean; regenerate_images?: boolean }) => request<{ status: string; scene: Scene; regenerated?: string[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/regenerate`, { method: "POST", headers: options ? { "content-type": "application/json" } : undefined, body: options ? JSON.stringify(options) : undefined }),
  updateStoryBrief: (storyId: string, input: Partial<Pick<GenerateInput, "story_concept" | "style" | "tone" | "voice_preset" | "narration_style" | "characters" | "world_context" | "voice_assignments" | "num_scenes" | "images_per_scene">>) => request<{ status: string; story_id: string; manifest: Story }>(`/api/stories/${storyId}/brief`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(input) }),
  scanStoryContext: (storyId: string, force = false) => request<{ status: string; story_id: string; manifest: StoryDetail; summary: { characters: number; scenes: number; scanned: boolean } }>(`/api/stories/${storyId}/context/scan`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ force }) }),
  regenerateStory: (storyId: string, backup = true) => request<{ task_id: string; status: string; story_id: string; message: string }>(`/api/stories/${storyId}/regenerate`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ backup }) }),
  addSceneImage: (storyId: string, sceneIndex: number, input?: { mode?: "director" | "manual"; count?: number; position?: number }) => request<{ status: string; filename: string; filenames: string[]; placements: Array<{ filename: string; position: number; shot_id?: string | null }>; total_images: number; mode: string }>(`/api/stories/${storyId}/scenes/${sceneIndex}/add-image`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input || {}) }),
  sceneShots: (storyId: string, sceneIndex: number) => request<{ shots: SemanticShot[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots`),
  planSceneShots: (storyId: string, sceneIndex: number) => request<{ revision: number; shots: SemanticShot[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ pacing: "balanced" }) }),
  reviseSceneShot: (storyId: string, sceneIndex: number, shotId: string, visualContext: string) => request<{ revision: number; shots: SemanticShot[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/${shotId}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ visual_context: visualContext }) }),
  reorderSceneShots: (storyId: string, sceneIndex: number, shotIds: string[]) => request<{ revision: number; shots: SemanticShot[]; timeline_stale: boolean }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/order`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ shot_ids: shotIds }) }),
  lockSceneShot: (storyId: string, sceneIndex: number, shotId: string, locked: boolean) => request<{ shot_id: string; locked: boolean }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/${shotId}/lock`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ locked }) }),
  generateSceneShot: (storyId: string, sceneIndex: number, shotId: string) => request<{ run_id: string }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/${shotId}/generate`, { method: "POST" }),
  shotAssets: (storyId: string, sceneIndex: number, shotId: string) => request<{ assets: ShotAsset[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/${shotId}/assets`),
  approveShotAsset: (storyId: string, sceneIndex: number, shotId: string, assetId: string) => request(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/${shotId}/assets/${assetId}/approve`, { method: "POST" }),
  shotRevisions: (storyId: string, sceneIndex: number) => request<{ revisions: number[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/revisions`),
  restoreShotRevision: (storyId: string, sceneIndex: number, revision: number) => request<{ revision: number; shots: SemanticShot[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/revisions/${revision}/restore`, { method: "POST" }),
  buildShotTimeline: (storyId: string, sceneIndex: number) => request<{ path: string; segments: Array<{ shot_id: string; start: number; end: number }> }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/timeline`, { method: "POST" }),
  buildStoryShotTimeline: (storyId: string) => request<{ path: string; segments: Array<{ shot_id: string; start: number; end: number }> }>(`/api/stories/${storyId}/shots/timeline`, { method: "POST" }),
  storyTimeline: (storyId: string) => request<{ shot_segments: TimelineShot[]; segments: Array<{ scene_id: string; text: string; start: number; end: number }> }>(`/api/stories/${storyId}/timeline`),
  sceneSubtitles: (storyId: string, sceneIndex: number) => request<{ audio_filename: string; subtitle_file: string; segments: SubtitleCue[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/subtitles`),
  renderStory: (storyId: string) => request<{ status: string; message?: string; rendered_count?: number }>(`/api/stories/${storyId}/render`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({}) }),
  exportPlex: (storyId: string) => request<{ status: string; message?: string; task_id?: string }>(`/api/stories/${storyId}/export-plex`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({}) }),
  settings: () => request<StudioSettings>("/api/settings"),
  llmModels: (input?: { base_url?: string; api_key?: string }) => request<{ ok: boolean; models: string[]; error?: string }>("/api/settings/llm-models", input ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input) } : undefined),
  updateSettings: (settings: StudioSettings) => request<{ ok: boolean; settings: StudioSettings }>("/api/settings", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(settings) }),
};
