import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  Archive, ArrowDown, ArrowUp, ChevronRight, Clapperboard, Cpu, Gauge, Image, Library,
  LoaderCircle, MoreHorizontal, Pause, Play, Plus, Radio, RefreshCw,
  Search, Settings, SlidersHorizontal, Sparkles, Square, UserRoundCog,
  Volume2, X,
} from "lucide-react";
import { api, type ComfyWorker, type GenerateInput, type ProductionEvent, type ProductionJob, type ProductionRelease, type ProductionRun, type Scene, type SeedSuggestion, type SemanticShot, type ShotAsset, type Story, type StoryDetail, type StudioSettings, type SubtitleCue, type TimelineShot, type Worker } from "./api";

const nav = [
  [Library, "Library"], [Clapperboard, "Productions"], [Archive, "Assets"], [UserRoundCog, "Workers"], [Settings, "Settings"],
] as const;

function timestamp(value?: string | number) {
  if (!value) return "Awaiting date";
  const date = new Date(typeof value === "number" && value < 10_000_000_000 ? value * 1000 : value);
  return Number.isNaN(date.valueOf()) ? "Awaiting date" : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function humanStatus(status: string) {
  return status.replaceAll("_", " ").replace(/^./, (value) => value.toUpperCase());
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

export function App() {
  const [stories, setStories] = useState<Story[]>([]);
  const [runs, setRuns] = useState<ProductionRun[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [comfyWorkers, setComfyWorkers] = useState<ComfyWorker[]>([]);
  const [selectedStoryId, setSelectedStoryId] = useState<string>();
  const [selectedRunId, setSelectedRunId] = useState<string>();
  const [jobs, setJobs] = useState<ProductionJob[]>([]);
  const [events, setEvents] = useState<ProductionEvent[]>([]);
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("Connecting to the production ledger...");
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [playerOpen, setPlayerOpen] = useState(false);
  const [workersOpen, setWorkersOpen] = useState(false);
  const [activeView, setActiveView] = useState("Library");
  const [editorStory, setEditorStory] = useState<StoryDetail>();
  const [editorScene, setEditorScene] = useState(0);
  const [brief, setBrief] = useState<GenerateInput>({ story_concept: "", style: "cinematic fantasy realism", num_scenes: 8, images_per_scene: 5, characters: "", tone: "grounded, tense, humane", voice_preset: "Dean" });
  const [seeds, setSeeds] = useState<SeedSuggestion[]>([]);
  const [seedBusy, setSeedBusy] = useState(false);
  const [admissionPaused, setAdmissionPaused] = useState(false);

  const refresh = async () => {
    try {
      const [storyResult, runResult, workerResult, comfyResult, controlResult] = await Promise.all([
        api.stories(), api.runs(), api.workers(), api.comfyWorkers(), api.productionControl().catch(() => ({ admission_paused: false })),
      ]);
      const sortedStories = [...storyResult.stories].sort((a, b) => Number(b.updated_at || b.created_at || 0) - Number(a.updated_at || a.created_at || 0));
      setStories(sortedStories);
      const visibleRuns = runResult.runs.filter((run) => !run.kind.includes("library_story"));
      setRuns(visibleRuns);
      setWorkers(workerResult.workers);
      setComfyWorkers(comfyResult.workers || []);
      setAdmissionPaused(controlResult.admission_paused);
      setSelectedStoryId((current) => current || sortedStories[0]?.id);
      setSelectedRunId((current) => current && visibleRuns.some((run) => run.id === current) ? current : visibleRuns[0]?.id);
      setNotice("Production ledger is live.");
    } catch (error) {
      setNotice(error instanceof Error ? `Connection issue: ${error.message}` : "Connection issue.");
    }
  };

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), 12_000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!selectedRunId) { setJobs([]); setEvents([]); return; }
    void api.run(selectedRunId).then((result) => setJobs(result.jobs)).catch(() => setJobs([]));
    setEvents([]);
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

  const selectedStory = stories.find((story) => story.id === selectedStoryId);
  const selectedRun = runs.find((run) => run.id === selectedRunId);
  const visibleStories = stories.filter((story) => story.title.toLowerCase().includes(query.toLowerCase()));
  const activeWorkers = [...workers, ...comfyWorkers].filter((worker) => (worker as Worker).status !== "stale" && (worker as ComfyWorker).running !== false);

  const runAction = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try { await action(); setNotice(message); await refresh(); }
    catch (error) { setNotice(error instanceof Error ? error.message : "The control request did not complete."); }
    finally { setBusy(false); }
  };

  const submitBrief = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (brief.story_concept.trim().length < 10) { setNotice("Give the director at least a sentence of story intent."); return; }
    setBusy(true);
    try {
      const result = await api.generate(brief);
      setSelectedRunId(result.task_id);
      setCreateOpen(false);
      setNotice(`Production ${result.task_id} has entered the durable queue.`);
      await refresh();
    } catch (error) { setNotice(error instanceof Error ? error.message : "The production brief could not be queued."); }
    finally { setBusy(false); }
  };

  const suggestSeeds = async () => {
    if (brief.story_concept.trim().length < 10) { setNotice("Give the seed picker at least a sentence of story intent."); return; }
    setSeedBusy(true);
    try { const result = await api.seedSuggestions(brief); setSeeds(result.seeds); setNotice("The director returned three small story directions."); }
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

  return <main className="studio-shell">
    <aside className="rail">
      <div className="brand"><span>FantaSee</span><small>Studio</small></div>
      <nav>{nav.map(([Icon, label], index) => <button className={label === activeView ? "nav-item active" : "nav-item"} key={label} onClick={() => { setActiveView(label); setNotice(`${label} desk selected.`); }} aria-current={label === activeView ? "page" : undefined}><Icon size={19}/><span>{label}</span><i>{label === activeView ? "" : undefined}</i></button>)}</nav>
      <section className="vu-panel" aria-label="System activity"><div className="vu-heading"><span>L</span><span>R</span></div><div className="needles"><i/><i/></div><b>VU</b></section>
      <section className="system-panel"><div><span className="led green"/> System <em>online</em></div><div className="transport"><button aria-label="previous">◀◀</button><button aria-label="play"><Play size={13}/></button><button aria-label="stop"><Square size={12}/></button><button className="record" aria-label="record">●</button></div></section>
    </aside>

    <section className="workspace">
      <header className="command-bar"><label><Search size={19}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search stories..." /></label><div><button className="icon-button" onClick={() => void refresh()} aria-label="Refresh"><RefreshCw size={18}/></button><button className="create" onClick={() => setCreateOpen(true)}><Plus size={17}/> Create story</button><button className="icon-button" onClick={() => setWorkersOpen(true)} aria-label="Open worker controls"><SlidersHorizontal size={18}/></button></div></header>
      <div className="status-strip"><span className="led green"/> {notice} <span>•</span> {activeWorkers.length} active worker{activeWorkers.length === 1 ? "" : "s"}</div>
      {activeView === "Library" ? <><div className="content-grid">
        <section className="library-module metal-panel">
          <div className="eyebrow"><span>Featured story</span><span>Newest first</span></div>
          {selectedStory ? <article className="feature">
            <div className="cover">{hasUsableCover(selectedStory) ? <img src={selectedStory.cover_image_url || selectedStory.hero_image} alt=""/> : <Sparkles size={34}/>}</div>
            <div><h1>{selectedStory.title}</h1><p>{selectedStory.description || "A new production, ready for its editorial pass."}</p><div className="story-meta">{selectedStory.scene_count || 0} scenes <span/> updated {timestamp(selectedStory.updated_at || selectedStory.created_at)}</div><div className="feature-actions"><button className="outline-button" onClick={() => void openEditor()}>Open in editor <ChevronRight size={16}/></button><button className="outline-button" disabled={!selectedStory.completion?.full_video_ok} onClick={() => setPlayerOpen(true)}><Play size={15}/> Play release</button></div></div>
          </article> : <div className="empty-state"><Sparkles size={28}/><h1>No stories yet</h1><p>Create a story to establish the first production run.</p></div>}
          <div className="section-heading"><h2>Story library</h2><span>{visibleStories.length} title{visibleStories.length === 1 ? "" : "s"}</span></div>
          <div className="story-list">{visibleStories.map((story) => <button key={story.id} className={story.id === selectedStoryId ? "story-row selected" : "story-row"} onClick={() => setSelectedStoryId(story.id)}>
            <span className="star">{story.id === selectedStoryId ? "+" : "o"}</span><span className="thumb">{hasUsableCover(story) ? <img src={story.cover_image_url || story.hero_image} alt="" onError={(event) => { event.currentTarget.style.display = "none"; }}/> : null}<Image className="fallback-icon" size={15}/></span><strong>{story.title}</strong><span className={`story-health ${storyHealth(story).tone}`}>{storyHealth(story).text}</span><span>{story.scene_count || 0} scenes</span><span>{timestamp(story.updated_at || story.created_at)}</span><ChevronRight size={17}/>
          </button>)}</div>
        </section>

        <aside className="inspector metal-panel">
          <div className="eyebrow"><span>Production run</span><span className={`run-state ${selectedRun?.status || "idle"}`}>{humanStatus(selectedRun?.status || "idle")}</span></div>
          {selectedRun ? <><div className="run-summary"><span className="led red"/> <small>{selectedRun.id}</small><h2>{selectedStory?.title || selectedRun.story_id || "Library maintenance"}</h2><p>{selectedRun.stage}: {selectedRun.message}</p><div className="progress-track"><i style={{width: `${Math.round((selectedRun.progress || 0) * 100)}%`}}/></div><b>{Math.round((selectedRun.progress || 0) * 100)}% complete</b></div>
          <div className="completion"><h3>Completion evidence</h3>{completionRows(selectedStory).map(([Icon, label, complete, detail]) => <div className="completion-row" key={label}><Icon size={18}/><span>{label}</span><small>{complete ? "verified" : "pending"} · {detail}</small><i className={complete ? "led green" : "led amber"}/></div>)}</div>
          <div className="run-controls"><h3>Run controls</h3><button disabled={busy} className="outline-button" onClick={() => void runAction(async () => { const result = await api.setProductionControl(!admissionPaused); setAdmissionPaused(result.admission_paused); }, admissionPaused ? "Queue admission resumed." : "Queue admission paused.")}>{admissionPaused ? "Resume queue admission" : "Pause queue admission"}</button><div className="queue-priority-panel"><span>Queue priority</span>{jobs.filter((job) => ["queued", "retryable"].includes(job.status)).map((job) => <div key={job.id}><small>{humanStatus(job.job_type)} · {job.priority ?? 0}</small><button className="micro-button" disabled={busy || (job.priority ?? 0) >= 100} onClick={() => void runAction(() => api.priorityJob(job.id, Math.min(100, (job.priority ?? 0) + 1)), `Raised priority for ${job.id}.`)} title="Raise priority"><ArrowUp size={12}/></button><button className="micro-button" disabled={busy || (job.priority ?? 0) <= 0} onClick={() => void runAction(() => api.priorityJob(job.id, Math.max(0, (job.priority ?? 0) - 1)), `Lowered priority for ${job.id}.`)} title="Lower priority"><ArrowDown size={12}/></button></div>)}</div><button disabled={busy || jobs.length === 0} className="danger" onClick={() => jobs[0] && void runAction(() => api.cancelJob(jobs[0].id), "Cancellation requested for the current job.")}><Pause size={17}/> Pause / cancel</button><button disabled={busy || jobs.length === 0} className="outline-button" onClick={() => jobs[0] && void runAction(() => api.retryJob(jobs[0].id), "The current job has been returned to the durable queue.")}><RefreshCw size={16}/> Retry</button></div>
          <div className="job-ledger"><h3>Job ledger</h3>{jobs.length ? jobs.map((job) => <div className="job-row" key={job.id}><div><span className={`led ${job.status === "succeeded" ? "green" : job.status === "failed" ? "red" : "amber"}`}/><strong>{humanStatus(job.job_type)}</strong><small>{job.message || humanStatus(job.status)} · attempt {job.attempts + 1}</small></div><div className="job-controls">{job.status !== "succeeded" && <button className="micro-button" disabled={busy} onClick={() => void runAction(() => api.retryJob(job.id), `Job ${job.id} queued for retry.`)} title="Retry this job"><RefreshCw size={13}/></button>}{["queued", "running"].includes(job.status) && <button className="micro-button" disabled={busy} onClick={() => void runAction(() => api.cancelJob(job.id), `Cancellation requested for job ${job.id}.`)} title="Cancel this job"><X size={13}/></button>}</div></div>) : <p className="ledger-empty">No durable jobs have been recorded for this run yet.</p>}</div><div className="event-spool"><h3>Live event spool</h3>{events.length ? events.slice().reverse().slice(0, 10).map((event) => <div className="event-row" key={`${event.sequence}-${event.event_type}`}><span className="led green"/><small>#{event.sequence} {event.event_type}</small><strong>{String(event.payload.message || event.payload.stage || "Recorded production event")}</strong></div>) : <p className="ledger-empty">Waiting for durable progress events.</p>}</div></> : <div className="empty-state"><Radio size={25}/><p>No production run selected.</p></div>}
        </aside>
      </div>
      <section className="worker-deck">{activeWorkers.length ? activeWorkers.slice(0, 2).map((worker, index) => {
        const comfyUrl = (worker as ComfyWorker).url;
        return <WorkerLane key={index} worker={worker} jobs={jobs} busy={busy} onSpawn={() => void runAction(() => api.spawn(index ? "cpu" : "gpu"), `${index ? "CPU" : "GPU"} ComfyUI worker started.`)} onKill={comfyUrl ? () => void runAction(() => api.killComfy(comfyUrl), "Selected ComfyUI worker stopped.") : undefined}/>;
      }) : <WorkerLane empty jobs={jobs} busy={busy} onSpawn={() => void runAction(() => api.spawn("gpu"), "GPU ComfyUI worker started.")}/>}</section></> : <StudioDesk view={activeView} stories={stories} runs={runs} workers={activeWorkers} selectedStory={selectedStory} jobs={jobs} busy={busy} onSpawn={(kind) => void runAction(() => api.spawn(kind), `${kind.toUpperCase()} ComfyUI worker started.`)} onRefresh={() => void refresh()} onSelectRun={(id) => { setSelectedRunId(id); setActiveView("Library"); setNotice(`Run ${id} selected.`); }} />}
      {createOpen && <div className="modal-scrim" role="presentation"><form className="brief-modal metal-panel" onSubmit={submitBrief}>
        <div className="eyebrow"><span>New production brief</span><button type="button" className="icon-button" onClick={() => setCreateOpen(false)} aria-label="Close"><X size={17}/></button></div>
        <h2>Set the story in motion.</h2><p>The director will break this brief into granular scene commissions and complete every media requirement before release.</p>
        <label className="brief-field wide">Story intent<textarea autoFocus value={brief.story_concept} onChange={(event) => setBrief({ ...brief, story_concept: event.target.value })} placeholder="A medic from Johannesburg wakes in a cold mountain village where every wound carries a memory..." /><button type="button" className="outline-button seed-button" disabled={seedBusy} onClick={() => void suggestSeeds()}>{seedBusy ? "Consulting director..." : "Suggest three directions"}</button></label>{seeds.length > 0 && <div className="seed-grid">{seeds.map((seed) => <button type="button" className="seed-card" key={`${seed.title}-${seed.description}`} onClick={() => { setBrief({ ...brief, story_concept: `${seed.title}\n${seed.description}`, style: seed.style || brief.style, tone: seed.tone || brief.tone, characters: seed.characters || brief.characters }); setSeeds([]); }}><strong>{seed.title}</strong><small>{seed.description}</small><em>{seed.style || brief.style} · {seed.tone || brief.tone}</em></button>)}</div>}
        <div className="brief-grid"><label className="brief-field">Scenes<input type="number" min="3" max="20" value={brief.num_scenes} onChange={(event) => setBrief({ ...brief, num_scenes: Number(event.target.value) })}/></label><label className="brief-field">Images per scene<input type="number" min="1" max="10" value={brief.images_per_scene} onChange={(event) => setBrief({ ...brief, images_per_scene: Number(event.target.value) })}/></label><label className="brief-field">Style<input value={brief.style} onChange={(event) => setBrief({ ...brief, style: event.target.value })}/></label><label className="brief-field">Tone<input value={brief.tone} onChange={(event) => setBrief({ ...brief, tone: event.target.value })}/></label></div>
        <label className="brief-field wide">Characters and continuity<textarea value={brief.characters} onChange={(event) => setBrief({ ...brief, characters: event.target.value })} placeholder="Optional character, setting, or visual continuity notes." /></label>
        <label className="brief-field wide">Narrator<input value={brief.voice_preset} onChange={(event) => setBrief({ ...brief, voice_preset: event.target.value })}/></label>
        <div className="modal-actions"><button type="button" className="outline-button" onClick={() => setCreateOpen(false)}>Cancel</button><button className="create" disabled={busy} type="submit"><Plus size={17}/> Queue production</button></div>
      </form></div>}
      {editorOpen && <StoryEditor story={editorStory} sceneIndex={editorScene} busy={busy} onClose={() => setEditorOpen(false)} onSelectScene={setEditorScene} onAction={(action, message) => void runAction(action, message)} />}
      {playerOpen && selectedStory && <ReleasePlayer story={selectedStory} onClose={() => setPlayerOpen(false)} />}
      {workersOpen && <WorkerConsole workers={comfyWorkers} busy={busy} onClose={() => setWorkersOpen(false)} onRefresh={() => void refresh()} onSpawn={(kind) => void runAction(() => api.spawn(kind), `${kind.toUpperCase()} ComfyUI worker started.`)} onKill={(url) => void runAction(() => api.killComfy(url), "Selected ComfyUI worker stopped.")} />}
    </section>
  </main>;
}

function StudioDesk({ view, stories, runs, workers, selectedStory, jobs, busy, onSpawn, onRefresh, onSelectRun }: { view: string; stories: Story[]; runs: ProductionRun[]; workers: Array<Worker | ComfyWorker>; selectedStory?: Story; jobs: ProductionJob[]; busy: boolean; onSpawn: (kind: "cpu" | "gpu") => void; onRefresh: () => void; onSelectRun: (id: string) => void }) {
  const [settings, setSettings] = useState<StudioSettings>();
  const [releases, setReleases] = useState<ProductionRelease[]>([]);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [auditionBusy, setAuditionBusy] = useState(false);
  const [auditionUrl, setAuditionUrl] = useState<string>();
  useEffect(() => { if (view === "Settings") void api.settings().then(setSettings).catch(() => setSettings(undefined)); }, [view]);
  useEffect(() => {
    if (view !== "Assets" || !selectedStory) { setReleases([]); return; }
    void api.releases(selectedStory.id).then((result) => setReleases(result.releases)).catch(() => setReleases([]));
  }, [view, selectedStory?.id]);
  const auditionVoice = async () => {
    if (!settings) return;
    setAuditionBusy(true);
    try { const result = await api.ttsGenerate("The road is cold. She keeps walking.", settings.tts_voice_preset); setAuditionUrl(result.url); }
    catch { setAuditionUrl(undefined); }
    finally { setAuditionBusy(false); }
  };
  const saveSettings = async () => {
    if (!settings) return;
    setSettingsBusy(true);
    try { const result = await api.updateSettings(settings); setSettings(result.settings); onRefresh(); }
    finally { setSettingsBusy(false); }
  };
  const title = view === "Productions" ? "Production desk" : view === "Assets" ? "Asset library" : view === "Workers" ? "Worker control" : "Studio settings";
  return <section className="desk-panel metal-panel"><div className="eyebrow"><span>{title}</span><span>{view === "Productions" ? `${runs.length} durable runs` : view === "Workers" ? `${workers.length} active signals` : "Operator view"}</span></div>
    {view === "Productions" && <><h1>Every run leaves a trail.</h1><p className="desk-intro">Durable production records survive refreshes and restarts. Select a run to return to its live job ledger and event spool.</p><div className="desk-list">{runs.length ? runs.map((run) => <button className="desk-row desk-row-button" key={run.id} onClick={() => onSelectRun(run.id)}><span className={`led ${run.status === "succeeded" ? "green" : run.status === "failed" ? "red" : "amber"}`}/><div><strong>{run.story_id || run.kind}</strong><small>{run.stage}: {run.message}</small></div><b>{Math.round((run.progress || 0) * 100)}%</b><ChevronRight size={15}/></button>) : <p className="ledger-empty">No durable runs are recorded yet.</p>}</div></>}
    {view === "Assets" && <><h1>Approved inputs only.</h1><p className="desk-intro">Candidates remain reversible until explicitly approved. Current story evidence is the release gate.</p>{selectedStory ? <><div className="asset-ledger">{completionRows(selectedStory).map(([, label, complete, detail]) => <div className="asset-row" key={label}><span className={`led ${complete ? "green" : "amber"}`}/><strong>{label}</strong><small>{detail}</small></div>)}</div><ReleaseLedger releases={releases} /></> : <p className="ledger-empty">Select a story to inspect its assets.</p>}</>}
    {view === "Workers" && <><h1>Hardware, with a signal.</h1><p className="desk-intro">The next compatible job is assigned by capability. Stop a worker safely and its lease can recover.</p><div className="desk-list">{workers.length ? workers.map((worker, index) => <article className="desk-row" key={`${workerIdentity(worker)}-${index}`}><span className="led green"/><div><strong>{workerLabel(worker)}</strong><small>{workerIdentity(worker)}</small></div><button className="micro-button" disabled={busy} onClick={() => onSpawn(workerLabel(worker).startsWith("GPU") ? "gpu" : "cpu")}>Spawn peer</button></article>) : <p className="ledger-empty">No workers are currently reporting.</p>}</div><div className="desk-actions"><button className="outline-button" disabled={busy} onClick={() => onSpawn("gpu")}>Start GPU</button><button className="outline-button" disabled={busy} onClick={() => onSpawn("cpu")}>Start CPU</button></div></>}
    {view === "Settings" && <><h1>Keep the chain honest.</h1><p className="desk-intro">These controls are persisted locally and applied to new production work. Existing approved media is never silently rewritten.</p>{settings ? <div className="settings-form"><label>Voice<select value={settings.tts_voice_preset} onChange={(event) => setSettings({ ...settings, tts_voice_preset: event.target.value })}><option>Dean</option><option>Milo</option><option>Mia</option><option>Chloe</option></select></label><div className="voice-audition"><button className="outline-button" disabled={auditionBusy} onClick={() => void auditionVoice()}>{auditionBusy ? "Generating audition..." : "Audition voice"}</button>{auditionUrl && <audio controls autoPlay src={auditionUrl} />}</div><label>Speed<input type="number" min="0.5" max="3" step="0.05" value={settings.tts_speed} onChange={(event) => setSettings({ ...settings, tts_speed: Number(event.target.value) })}/></label><label>Default style<input value={settings.default_style} onChange={(event) => setSettings({ ...settings, default_style: event.target.value })}/></label><label>Default tone<input value={settings.default_tone} onChange={(event) => setSettings({ ...settings, default_tone: event.target.value })}/></label><label className="wide">ComfyUI workers<input value={settings.comfyui_urls} onChange={(event) => setSettings({ ...settings, comfyui_urls: event.target.value })}/></label><label className="wide">Plex destination<input value={settings.plex_destination} onChange={(event) => setSettings({ ...settings, plex_destination: event.target.value })}/></label><div className="settings-actions"><button className="outline-button" disabled={settingsBusy} onClick={() => void api.settings().then(setSettings)}>Reload</button><button className="create" disabled={settingsBusy} onClick={() => void saveSettings()}>Save settings</button></div></div> : <p className="ledger-empty">Loading validated settings...</p>}</>}
  </section>;
}

function ReleaseLedger({ releases }: { releases: ProductionRelease[] }) {
  return <section className="release-ledger"><div className="inspector-title"><h2>Release history</h2><small>{releases.length ? `${releases.length} recorded artifacts` : "No release artifacts"}</small></div>{releases.length ? <div className="release-list">{releases.map((release) => <article className="release-row" key={release.id}><span className={`led ${release.status === "current" ? "green" : "amber"}`}/><div><strong>{humanStatus(release.release_type)} <em>{humanStatus(release.status)}</em></strong><small>{timestamp(release.created_at)} · fingerprint {release.fingerprint.slice(0, 12)}</small><small className="release-path">{release.path}</small></div></article>)}</div> : <p className="ledger-empty">Render or export a verified story to create its first release record.</p>}<p className="release-note">Superseded artifacts stay visible for audit and recovery. A release cannot be restored through this view unless it passes the current completion gate again.</p></section>;
}

function ReleasePlayer({ story, onClose }: { story: Story; onClose: () => void }) {
  return <div className="modal-scrim player-scrim"><section className="release-player metal-panel"><header className="editor-header"><div><span className="eyebrow-label">Canonical release</span><h1>{story.title}</h1><small>MP4 + timeline subtitles</small></div><button className="icon-button" onClick={onClose} aria-label="Close player"><X size={19}/></button></header><video controls autoPlay preload="metadata"><source src={`/generated/${story.id}/${story.id}_full.mp4`} type="video/mp4"/><track kind="subtitles" src={`/generated/${story.id}/${story.id}_full.vtt`} srcLang="en" label="English" default /></video><NarrationWaveform src={`/generated/${story.id}/${story.id}_full.mp4`} /><p className="player-note">Playback uses the rendered release and its canonical subtitle timeline. If the release is stale, return to the editor and rebuild the approved timeline.</p></section></div>;
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

function WorkerConsole({ workers, busy, onClose, onRefresh, onSpawn, onKill }: { workers: ComfyWorker[]; busy: boolean; onClose: () => void; onRefresh: () => void; onSpawn: (kind: "cpu" | "gpu") => void; onKill: (url: string) => void }) {
  const [selectedUrl, setSelectedUrl] = useState<string>();
  useEffect(() => {
    setSelectedUrl((current) => current && workers.some((worker) => worker.url === current) ? current : workers[0]?.url);
  }, [workers]);
  const selected = workers.find((worker) => worker.url === selectedUrl);
  return <div className="modal-scrim" role="dialog" aria-modal="true" aria-labelledby="worker-console-title"><section className="worker-console metal-panel">
    <header className="editor-header"><div><span className="eyebrow-label">Production hardware</span><h1 id="worker-console-title">ComfyUI workers</h1><small>Select a live instance to inspect or stop it.</small></div><button className="icon-button" onClick={onClose} aria-label="Close worker controls"><X size={19}/></button></header>
    <div className="worker-console-body"><div className="worker-selector">{workers.length ? workers.map((worker) => <button key={worker.url} className={worker.url === selectedUrl ? "worker-option selected" : "worker-option"} onClick={() => setSelectedUrl(worker.url)}><span className={`led ${worker.running === false ? "red" : "green"}`}/><strong>{workerLabel(worker)}</strong><small>{worker.url}</small><b>{worker.running === false ? "offline" : `${worker.queue_running || 0} running · ${worker.queue_remaining || 0} waiting`}</b></button>) : <p className="ledger-empty">No ComfyUI workers are reporting.</p>}</div><aside className="worker-detail"><div className="eyebrow"><span>Selected instance</span><button className="micro-button" onClick={onRefresh} disabled={busy} aria-label="Refresh workers"><RefreshCw size={13}/></button></div>{selected ? <><h2>{workerLabel(selected)}</h2><p>{selected.url}</p><dl className="settings-ledger"><div><dt>Process</dt><dd>{selected.pid || "unknown"}</dd></div><div><dt>Queue</dt><dd>{selected.queue_running || 0} active / {selected.queue_remaining || 0} waiting</dd></div><div><dt>Device</dt><dd>{selected.device || selected.kind || "unknown"}</dd></div></dl><button className="danger" disabled={busy || selected.running === false || !selected.url} onClick={() => selected.url && onKill(selected.url)}><Square size={15}/> Kill selected worker</button></> : <p>Select a worker to see its process and queue.</p>}</aside></div>
    <footer className="modal-actions"><button className="outline-button" disabled={busy} onClick={() => onSpawn("cpu")}><Cpu size={15}/> Spawn CPU</button><button className="outline-button" disabled={busy} onClick={() => onSpawn("gpu")}><Sparkles size={15}/> Spawn GPU</button><button className="create" onClick={onClose}>Close</button></footer>
  </section></div>;
}

function CandidateGallery({ assets, busy, onApprove }: { assets: ShotAsset[]; busy: boolean; onApprove: (asset: ShotAsset) => void }) {
  const [previewId, setPreviewId] = useState<string>();
  const preview = assets.find((asset) => asset.id === previewId) || assets[0];
  return <div className="candidate-list"><div className="candidate-heading"><b>Image candidates</b><small>{assets.length} generated {assets.length === 1 ? "frame" : "frames"}</small></div>{preview?.url && <img className="candidate-preview" src={preview.url} alt="Selected generated candidate" />}{assets.map((asset) => <button type="button" className={asset.id === preview?.id ? "candidate-card selected" : "candidate-card"} key={asset.id} onClick={() => setPreviewId(asset.id)}><span className="candidate-thumb">{asset.url ? <img src={asset.url} alt="" /> : <Image size={14}/>}</span><span className="candidate-meta"><strong>{asset.status}</strong><small>{asset.filename}</small></span>{asset.status !== "approved" && <span className="candidate-approve" onClick={(event) => { event.stopPropagation(); onApprove(asset); }}>Approve</span>}</button>)}</div>;
}

function StoryEditor({ story, sceneIndex, busy, onClose, onSelectScene, onAction }: { story?: StoryDetail; sceneIndex: number; busy: boolean; onClose: () => void; onSelectScene: (index: number) => void; onAction: (action: () => Promise<unknown>, message: string) => void }) {
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
  return <div className="editor-scrim"><section className="story-editor metal-panel">{story && scene ? <>
    <header className="editor-header"><div><span className="eyebrow-label">Story editor</span><h1>{story.title}</h1><small>Scene {String(sceneIndex + 1).padStart(2, "0")} of {story.scenes.length}</small></div><button className="icon-button" onClick={onClose} aria-label="Close editor"><X size={19}/></button></header>
    <div className="editor-body"><aside className="scene-strip"><h3>Scenes</h3>{story.scenes.map((item, index) => <button key={`${item.title}-${index}`} className={index === sceneIndex ? "scene-chip active" : "scene-chip"} onClick={() => onSelectScene(index)}><span>{String(index + 1).padStart(2, "0")}</span><strong>{item.title || `Scene ${index + 1}`}</strong><small>{item.image_filenames?.length || 0} images</small></button>)}</aside>
      <main className="scene-workbench"><div className="scene-kicker">{scene.title || `Scene ${sceneIndex + 1}`}</div><div className="shot-canvas">{scene.image_filenames?.[0] ? <img src={`/generated/${story.id}/${scene.image_filenames[0]}`} alt="" onError={(event) => { event.currentTarget.style.display = "none"; }}/> : <div><Image size={34}/><p>No approved scene artwork</p></div>}<span className="canvas-label">Primary visual beat</span></div><div className="editor-columns"><section><h3>Narration</h3><textarea className="editor-textarea narration-copy" value={narration} onChange={(event) => setSceneDraft((current) => ({ ...(current || scene), narration: event.target.value, narration_text: event.target.value }))} /><div className="audio-review">{scene.audio_filename ? <audio controls preload="metadata" src={`/generated/${story.id}/${scene.audio_filename}`} /> : <small>Narration audio is pending rebuild.</small>}<small>{scene.stale_outputs?.includes("audio") || scene.stale_outputs?.includes("subtitles") ? "Audio and subtitles need rebuilding after this edit." : `${scene.audio_duration ? scene.audio_duration.toFixed(1) : "--"}s aligned narration`}</small></div><div className="subtitle-inspector"><div className="subtitle-heading"><h3>Subtitle alignment</h3><small>{subtitleCues.length ? `${subtitleCues.length} Whisper cues` : "No aligned cues"}</small></div>{subtitleCues.length ? <>{subtitleCues.map((cue, index) => <div className="subtitle-cue" key={`${cue.start}-${index}`}><span>{cue.start.toFixed(1)}–{cue.end.toFixed(1)}s</span><strong>{cue.text}</strong></div>)}</> : <p>Regenerate the scene to align subtitles to the current audio fingerprint.</p>}</div></section><section><h3>Visual direction</h3><textarea className="editor-textarea prompt-copy" value={prompt} onChange={(event) => setSceneDraft((current) => ({ ...(current || scene), prompt: event.target.value }))} /></section></div><div className="editor-actions"><button className="create" disabled={busy || !draftChanged} onClick={() => onAction(async () => { const result = await api.updateScene(story.id, sceneIndex, { narration, prompt }); const rebuilt = await api.regenerateScene(story.id, sceneIndex); setSceneDraft(rebuilt.scene); return result; }, `Scene ${sceneIndex + 1} revision saved; audio, subtitles, and artwork rebuilt.`)}><RefreshCw size={15}/> Save and rebuild scene</button><button className="outline-button" disabled={busy} onClick={() => onAction(() => api.regenerateScene(story.id, sceneIndex), `Scene ${sceneIndex + 1} is regenerating its artwork and narration.`)}><RefreshCw size={15}/> Regenerate scene</button><button className="outline-button" disabled={busy} onClick={() => onAction(() => api.addSceneImage(story.id, sceneIndex), `One additional image has been requested for scene ${sceneIndex + 1}.`)}><Plus size={15}/> Add visual beat</button></div></main>
      <aside className="scene-inspector"><div className="inspector-title"><h3>Shot plan</h3><button className="micro-button" disabled={busy} title="Plan semantic shots" onClick={() => onAction(async () => { const result = await api.planSceneShots(story.id, sceneIndex); setShots(result.shots); setShotRevisions((current) => [result.revision, ...current]); }, `Stored semantic shot plan for scene ${sceneIndex + 1}.`)}><Plus size={13}/></button></div>{shots.length ? shots.map((shot) => <button draggable aria-grabbed={dragShotId === shot.id} className={selectedShot?.id === shot.id ? "shot-card selected" : "shot-card"} key={shot.id} onClick={() => selectShot(shot)} onKeyDown={(event) => { if (event.key === "ArrowUp") { event.preventDefault(); moveShotBy(shot.id, -1); } if (event.key === "ArrowDown") { event.preventDefault(); moveShotBy(shot.id, 1); } }} onDragStart={() => setDragShotId(shot.id)} onDragOver={(event) => event.preventDefault()} onDrop={() => reorderShot(shot.id)} title="Drag to reorder this shot, or use Arrow Up/Down"><span className="led green"/><strong>{String(shot.order).padStart(2, "0")} · {shot.shot_type}</strong><small>{shot.purpose} · {shot.duration_seconds.toFixed(1)}s</small></button>) : <div className="shot-card"><span className="led amber"/><strong>No semantic plan yet</strong><small>Use + to derive ordered visual beats from this scene's narration and direction.</small></div>}
        {shots.length > 0 && <div className="timeline-control"><button className="outline-button" disabled={busy} onClick={() => onAction(async () => { const result = await api.buildStoryShotTimeline(story.id); setTimelineShots(result.segments as TimelineShot[]); setTimelineStatus(`${result.segments.length} approved shots placed on the full narration timeline.`); }, "Built the approved visual timeline for the full story.")}>Build release timeline</button><button className="outline-button" disabled={busy || timelineShots.length === 0} onClick={() => onAction(() => api.renderStory(story.id), "Approved timeline render completed or was rejected by the evidence gate.")}>Render MP4</button><button className="outline-button" disabled={busy} onClick={() => onAction(() => api.exportPlex(story.id), "Plex export requested; the completion gate will report its result.")}>Export Plex</button>{timelineStatus && <small>{timelineStatus}</small>}</div>}
        {selectedShot && <div className="shot-edit"><label>Revise visual context<textarea value={shotContext} onChange={(event) => setShotContext(event.target.value)} /></label><button className="outline-button" disabled={busy || !shotContext.trim()} onClick={() => onAction(async () => { const result = await api.reviseSceneShot(story.id, sceneIndex, selectedShot.id, shotContext); setShots(result.shots); setShotRevisions((current) => [result.revision, ...current]); setSelectedShot(undefined); }, `Created a new revision for shot ${selectedShot.order}.`)}><RefreshCw size={14}/> Save shot revision</button><button className="outline-button" disabled={busy} onClick={() => onAction(() => api.generateSceneShot(story.id, sceneIndex, selectedShot.id), `GPU image job queued for shot ${selectedShot.order}.`)}><Image size={14}/> Generate this shot</button>{shotAssets.length > 0 && <CandidateGallery assets={shotAssets} busy={busy} onApprove={(asset) => onAction(async () => { await api.approveShotAsset(story.id, sceneIndex, selectedShot.id, asset.id); const result = await api.shotAssets(story.id, sceneIndex, selectedShot.id); setShotAssets(result.assets); }, "Approved this shot image candidate.")} />}</div>}{shotRevisions.length > 1 && <div className="revision-list"><b>Plan history</b>{shotRevisions.slice(1).map((revision) => <button key={revision} disabled={busy} onClick={() => onAction(async () => { const result = await api.restoreShotRevision(story.id, sceneIndex, revision); setShots(result.shots); setShotRevisions((current) => [result.revision, ...current]); setSelectedShot(undefined); }, `Restored plan revision ${revision} as a new current revision.`)}>Restore r{revision}</button>)}</div>}<h3>Continuity</h3><p>Changes stay contained to this scene. The release is marked stale until its media evidence is rebuilt.</p><h3>Evidence</h3><dl><div><dt>Images</dt><dd>{scene.image_filenames?.length || 0}</dd></div><div><dt>Duration</dt><dd>{scene.audio_duration ? `${scene.audio_duration.toFixed(1)}s` : "pending"}</dd></div></dl></aside>
    </div></> : <div className="empty-state"><LoaderCircle className="spin" size={30}/><p>Loading story workstation...</p><button className="outline-button" onClick={onClose}>Close</button></div>}{story && scene && timelineShots.length > 0 && <div className="timeline-rack"><header><span>Canonical visual timeline</span><span>{timelineShots.length} approved shots</span></header><div className="timeline-track">{timelineShots.map((segment) => <i key={segment.shot_id} style={{ left: `${segment.start / timelineDuration * 100}%`, width: `${Math.max(1, (segment.end - segment.start) / timelineDuration * 100)}%` }}><span>{segment.shot_id}</span></i>)}</div></div>}{story && scene && selectedShot && <button className="shot-lock-float" disabled={busy} onClick={() => onAction(async () => { const result = await api.lockSceneShot(story.id, sceneIndex, selectedShot.id, !shotLocked); setShotLocked(result.locked); }, `${shotLocked ? "Unlocked" : "Locked"} shot ${selectedShot.order}.`)}>{shotLocked ? "Unlock selected shot" : "Lock selected shot"}</button>}</section></div>;
}

function WorkerLane({ worker, jobs, busy, empty, onSpawn, onKill }: { worker?: Worker | ComfyWorker; jobs: ProductionJob[]; busy: boolean; empty?: boolean; onSpawn: () => void; onKill?: () => void }) {
  const runningJob = jobs.find((job) => job.status === "running") || jobs[0];
  const progress = Math.round((runningJob?.progress || 0) * 100);
  return <article className="worker-lane metal-panel"><div className="worker-title"><span className={empty ? "led amber" : "led green"}/><h2>{empty ? "Worker bay available" : workerLabel(worker!)}</h2><small>{empty ? "awaiting assignment" : "signal live"}</small></div><div className="lane-task"><span>Task</span><strong>{runningJob?.message || (empty ? "No worker in this lane" : "Standing by for a durable job")}</strong><small>Queue depth {jobs.filter((job) => ["queued", "running"].includes(job.status)).length}</small></div><div className="meter"><span>Progress</span><div className="progress-track"><i style={{width: `${progress}%`}}/></div><b>{progress}%</b><div className="level-meter">{Array.from({length: 22}, (_, index) => <i key={index} className={index < Math.max(6, Math.ceil(progress / 5)) ? "lit" : ""}/>)}</div></div><div className="lane-actions">{empty ? <button disabled={busy} onClick={onSpawn}><Plus size={17}/> Start GPU</button> : <><button disabled={busy} onClick={onSpawn} title="Start an additional worker"><Plus size={17}/></button>{onKill && <button disabled={busy} onClick={onKill} title="Stop this selected worker"><X size={17}/></button>}</>}</div></article>;
}
