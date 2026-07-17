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

export type ShotAsset = { id: string; status: string; filename: string; revision?: number };
export type TimelineShot = { scene_id: string; shot_id: string; asset_path: string; start: number; end: number };

export type ProductionJob = {
  id: string;
  job_type: string;
  status: string;
  attempts: number;
  progress: number;
  message: string;
  required_capabilities: string[];
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
  spawn: (kind: "cpu" | "gpu") => request(`/api/comfyui/workers/spawn-${kind}`, { method: "POST" }),
  killComfy: (url: string) => request("/api/comfyui/workers/kill", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url }) }),
  generate: (input: GenerateInput) => request<{ task_id: string; message: string }>("/api/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input) }),
  regenerateScene: (storyId: string, sceneIndex: number) => request<{ status: string; scene: Scene }>(`/api/stories/${storyId}/scenes/${sceneIndex}/regenerate`, { method: "POST" }),
  addSceneImage: (storyId: string, sceneIndex: number) => request(`/api/stories/${storyId}/scenes/${sceneIndex}/add-image`, { method: "POST" }),
  sceneShots: (storyId: string, sceneIndex: number) => request<{ shots: SemanticShot[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots`),
  planSceneShots: (storyId: string, sceneIndex: number) => request<{ revision: number; shots: SemanticShot[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ pacing: "balanced" }) }),
  reviseSceneShot: (storyId: string, sceneIndex: number, shotId: string, visualContext: string) => request<{ revision: number; shots: SemanticShot[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/${shotId}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ visual_context: visualContext }) }),
  lockSceneShot: (storyId: string, sceneIndex: number, shotId: string, locked: boolean) => request<{ shot_id: string; locked: boolean }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/${shotId}/lock`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ locked }) }),
  generateSceneShot: (storyId: string, sceneIndex: number, shotId: string) => request<{ run_id: string }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/${shotId}/generate`, { method: "POST" }),
  shotAssets: (storyId: string, sceneIndex: number, shotId: string) => request<{ assets: ShotAsset[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/${shotId}/assets`),
  approveShotAsset: (storyId: string, sceneIndex: number, shotId: string, assetId: string) => request(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/${shotId}/assets/${assetId}/approve`, { method: "POST" }),
  shotRevisions: (storyId: string, sceneIndex: number) => request<{ revisions: number[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/revisions`),
  restoreShotRevision: (storyId: string, sceneIndex: number, revision: number) => request<{ revision: number; shots: SemanticShot[] }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/revisions/${revision}/restore`, { method: "POST" }),
  buildShotTimeline: (storyId: string, sceneIndex: number) => request<{ path: string; segments: Array<{ shot_id: string; start: number; end: number }> }>(`/api/stories/${storyId}/scenes/${sceneIndex}/shots/timeline`, { method: "POST" }),
  buildStoryShotTimeline: (storyId: string) => request<{ path: string; segments: Array<{ shot_id: string; start: number; end: number }> }>(`/api/stories/${storyId}/shots/timeline`, { method: "POST" }),
  storyTimeline: (storyId: string) => request<{ shot_segments: TimelineShot[]; segments: Array<{ scene_id: string; text: string; start: number; end: number }> }>(`/api/stories/${storyId}/timeline`),
};
