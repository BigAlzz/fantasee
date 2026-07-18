import type { GenerationTask, Worker } from "./api";

export type ProductionActivity = {
  id: string;
  role: string;
  stage: string;
  story: string;
  message: string;
  progress: number;
  status: string;
  workerId?: string;
};

export type ProductionActivityProjection = {
  activities: ProductionActivity[];
  onlineWorkers: number;
  workingRoles: number;
};

const ACTIVE_STATUSES = new Set(["queued", "leased", "running", "retryable"]);
const WORKING_STATUSES = new Set(["leased", "running"]);
const QUEUE_KINDS = new Set(["generation_queue", "library_maintenance", "library_story"]);

function sentenceCase(value: string) {
  const words = value.replace(/[._-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Starting";
}

function roleFor(task: GenerationTask) {
  const signal = `${task.kind || ""} ${task.stage || ""} ${task.message || ""}`.toLowerCase();
  if (signal.includes("library") || signal.includes("maintenance")) return "Task librarian";
  if (/\b(critic|review|quality|continuity|verify|validation)\b/.test(signal)) return "Critic";
  if (/\b(voice|tts|audio|subtitle|align|performance)\b/.test(signal)) return "Performance director";
  if (/\b(art director|visual|image|illustration|artwork|shot|comfy)\b/.test(signal)) return "Art director";
  if (/\b(title|description|bible|outline|scene|narration|writer|writing|story|arc|context)\b/.test(signal)) return "Writer";
  return "Producer";
}

function stageFor(task: GenerationTask, role: string) {
  const stage = String(task.stage || "").trim();
  if (stage && !["generate", "running", "queued"].includes(stage.toLowerCase())) return sentenceCase(stage);
  const stages: Record<string, string> = {
    "Art director": "Art direction",
    "Performance director": "Voice and timing",
    "Task librarian": "Library maintenance",
    Writer: "Writing",
    Critic: "Review",
    Producer: stage.toLowerCase() === "queued" ? "Queued" : "Orchestration",
  };
  return stages[role] || sentenceCase(stage);
}

function storyFor(task: GenerationTask) {
  const request = task.request || {};
  return String(
    task.title
    || task.story_name
    || request.story_title
    || request.story_concept
    || request.concept
    || task.story_id
    || "Story context pending",
  );
}

function activityFor(task: GenerationTask, workerId?: string): ProductionActivity {
  const role = roleFor(task);
  return {
    id: task.id,
    role,
    stage: stageFor(task, role),
    story: storyFor(task),
    message: task.message || sentenceCase(task.status),
    progress: Math.max(0, Math.min(1, Number(task.progress) || 0)),
    status: task.status,
    ...(workerId ? { workerId } : {}),
  };
}

/**
 * Collapse parent queue records and their executable child into one visible
 * activity. Production workers win when they name the currently leased job;
 * otherwise each active queue family contributes at most one activity.
 */
export function projectProductionActivity(
  tasks: GenerationTask[],
  workers: Worker[],
): ProductionActivityProjection {
  const allTasksById = new Map(tasks.map((task) => [task.id, task]));
  const activeTasks = tasks.filter((task) => {
    if (!ACTIVE_STATUSES.has(task.status)) return false;
    if (!task.parent) return true;
    const parent = allTasksById.get(task.parent);
    return !parent || ACTIVE_STATUSES.has(parent.status);
  });
  const taskById = new Map(activeTasks.map((task) => [task.id, task]));
  const onlineWorkers = workers.filter((worker) => worker.status !== "stale");
  const workerByJob = new Map(
    onlineWorkers
      .filter((worker) => worker.current_job_id)
      .map((worker) => [worker.current_job_id!, worker.id]),
  );
  const childrenByParent = new Map<string, GenerationTask[]>();
  for (const task of activeTasks) {
    if (!task.parent) continue;
    const children = childrenByParent.get(task.parent) || [];
    children.push(task);
    childrenByParent.set(task.parent, children);
  }

  const represented = new Set<string>();
  const activities: ProductionActivity[] = [];
  const roots = activeTasks.filter((task) => !task.parent || !taskById.has(task.parent));

  for (const root of roots) {
    const children = childrenByParent.get(root.id) || [];
    const workerChild = children.find((child) => workerByJob.has(child.id));
    const rootWorkerId = workerByJob.get(root.id);
    const queueManaged = QUEUE_KINDS.has(root.kind || "") || children.some((child) => QUEUE_KINDS.has(child.kind || ""));
    if (queueManaged && !workerChild && !rootWorkerId && !["queued", "retryable"].includes(root.status)) {
      represented.add(root.id);
      for (const child of children) represented.add(child.id);
      continue;
    }
    const runningChild = children.find((child) => WORKING_STATUSES.has(child.status));
    const selected = workerChild || (queueManaged ? undefined : runningChild) || children[0] || root;
    const workerId = workerByJob.get(selected.id) || rootWorkerId;
    activities.push(activityFor(selected, workerId));
    represented.add(selected.id);
    represented.add(root.id);
    for (const child of children) represented.add(child.id);
  }

  for (const task of activeTasks) {
    if (represented.has(task.id)) continue;
    if (QUEUE_KINDS.has(task.kind || "") && !workerByJob.has(task.id) && !["queued", "retryable"].includes(task.status)) continue;
    activities.push(activityFor(task, workerByJob.get(task.id)));
  }

  activities.sort((left, right) => {
    const leftWorking = WORKING_STATUSES.has(left.status) ? 1 : 0;
    const rightWorking = WORKING_STATUSES.has(right.status) ? 1 : 0;
    return rightWorking - leftWorking || right.progress - left.progress;
  });

  return {
    activities,
    onlineWorkers: onlineWorkers.length,
    workingRoles: activities.filter((activity) => WORKING_STATUSES.has(activity.status)).length,
  };
}
