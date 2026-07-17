export type Story = {
  id: string;
  title: string;
  description?: string;
  created_at?: string | number;
  updated_at?: string | number;
  scene_count?: number;
  cover_image_url?: string;
  hero_image?: string;
  completion?: Record<string, unknown>;
};

export type Scene = {
  title?: string;
  narrative?: string;
  narration?: string;
  narration_text?: string;
  prompt?: string;
  image_filenames?: string[];
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
  job_type: string;
  status: string;
  attempts: number;
  progress: number;
  message: string;
  required_capabilities: string[];
  priority: number;
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
};

export type ProductionEvent = {
  sequence: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: number;
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
};

export type GenerateInput = {
  story_concept: string;
  style: string;
  num_scenes: number;
  images_per_scene: number;
  characters: string;
  tone: string;
  voice_preset: string;
};

export type SeedSuggestion = { title: string; description: string; style?: string; tone?: string; characters?: string };
export type StudioSettings = {
  comfyui_urls: string;
  comfyui_auto_spawn: boolean;
  llm_base_url: string;
  llm_api_key?: string;
  llm_model: string;
  tts_voice_preset: string;
  tts_speed: number;
  plex_destination: string;
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
  updateScene: (storyId: string, sceneIndex: number, input: { title?: string; prompt?: string; narration?: string }) => request<{ status: string; scene: Scene; stale_outputs: string[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(input) }),
  runs: () => request<{ runs: ProductionRun[] }>("/api/production/runs"),
  run: (id: string) => request<{ run: ProductionRun; jobs: ProductionJob[] }>(`/api/production/runs/${id}`),
  events: (id: string, afterSequence = 0) => request<{ run_id: string; events: ProductionEvent[]; next_sequence: number }>(`/api/production/runs/${id}/events?after_sequence=${afterSequence}`),
  workers: () => request<{ workers: Worker[] }>("/api/production/workers"),
  comfyWorkers: () => request<{ workers: ComfyWorker[] }>("/api/comfyui/workers"),
  retryJob: (id: string) => request(`/api/production/jobs/${id}/retry`, { method: "POST" }),
  cancelJob: (id: string) => request(`/api/production/jobs/${id}/cancel`, { method: "POST" }),
  priorityJob: (id: string, priority: number) => request(`/api/production/jobs/${id}/priority`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ priority }) }),
  productionControl: () => request<{ admission_paused: boolean }>("/api/production/control"),
  setProductionControl: (admission_paused: boolean) => request<{ admission_paused: boolean }>("/api/production/control", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ admission_paused }) }),
  ttsGenerate: (text: string, voice_preset: string) => request<{ url: string; duration: number }>("/api/tts/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, voice_preset }) }),
  spawn: (kind: "cpu" | "gpu") => request(`/api/comfyui/workers/spawn-${kind}`, { method: "POST" }),
  killComfy: (url: string) => request("/api/comfyui/workers/kill", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url }) }),
  generate: (input: GenerateInput) => request<{ task_id: string; message: string }>("/api/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input) }),
  seedSuggestions: (input: Pick<GenerateInput, "story_concept" | "style" | "tone" | "characters">) => request<{ seeds: SeedSuggestion[] }>("/api/seed-suggestions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ concept: input.story_concept, style: input.style, tone: input.tone, characters: input.characters, count: 3 }) }),
  regenerateScene: (storyId: string, sceneIndex: number) => request<{ status: string; scene: Scene }>(`/api/stories/${storyId}/scenes/${sceneIndex}/regenerate`, { method: "POST" }),
  addSceneImage: (storyId: string, sceneIndex: number) => request(`/api/stories/${storyId}/scenes/${sceneIndex}/add-image`, { method: "POST" }),
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
  updateSettings: (settings: StudioSettings) => request<{ ok: boolean; settings: StudioSettings }>("/api/settings", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(settings) }),
};
