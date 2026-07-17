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
};

export type StoryDetail = Story & { scenes: Scene[] };

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
  runs: () => request<{ runs: ProductionRun[] }>("/api/production/runs"),
  run: (id: string) => request<{ run: ProductionRun; jobs: ProductionJob[] }>(`/api/production/runs/${id}`),
  workers: () => request<{ workers: Worker[] }>("/api/production/workers"),
  comfyWorkers: () => request<{ workers: ComfyWorker[] }>("/api/comfyui/workers"),
  retryJob: (id: string) => request(`/api/production/jobs/${id}/retry`, { method: "POST" }),
  cancelJob: (id: string) => request(`/api/production/jobs/${id}/cancel`, { method: "POST" }),
  spawn: (kind: "cpu" | "gpu") => request(`/api/comfyui/workers/spawn-${kind}`, { method: "POST" }),
  killComfy: (url: string) => request("/api/comfyui/workers/kill", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url }) }),
  generate: (input: GenerateInput) => request<{ task_id: string; message: string }>("/api/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input) }),
  regenerateScene: (storyId: string, sceneIndex: number) => request(`/api/stories/${storyId}/scenes/${sceneIndex}/regenerate`, { method: "POST" }),
  addSceneImage: (storyId: string, sceneIndex: number) => request(`/api/stories/${storyId}/scenes/${sceneIndex}/add-image`, { method: "POST" }),
};
