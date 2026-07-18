import { useEffect, useMemo, useState } from "react";
import { BookOpen, ChevronLeft, Image, Pencil, Play, RefreshCw, Star, Trash2, Users, Wrench, X } from "lucide-react";
import { api, type Story, type StoryDetail } from "./api";

type StoryDetailsProps = {
  story: Story;
  onBack: () => void;
  onOpenEditor: () => void;
  onPlay: () => void;
  onDeleted: () => void;
};

type LoreBlock = { title: string; body: string };
type CharacterCard = { name: string; role: string; details: string; voice?: string; style?: string };

function parseLore(text: string): LoreBlock[] {
  return text.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean).map((block) => {
    const lines = block.split("\n");
    const heading = lines.shift() || "World context";
    const separator = heading.indexOf(":");
    return { title: separator > 0 ? heading.slice(0, separator) : heading, body: [separator > 0 ? heading.slice(separator + 1).trim() : "", ...lines].filter(Boolean).join("\n") };
  });
}

function parseCharacters(lore: LoreBlock[], assignments: string): CharacterCard[] {
  const fromLore = lore.find((block) => block.title.toLowerCase().includes("character"));
  const cards: CharacterCard[] = (fromLore?.body || "").split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const match = line.match(/^(.+?)\s*\(([^)]+)\)\s*\|\s*(.*)$/);
    if (!match) return { name: line.split("|")[0].trim(), role: "Story character", details: line };
    return { name: match[1].trim(), role: match[2].trim(), details: match[3].trim() };
  });
  try {
    const voiceRows = JSON.parse(assignments || "[]") as Array<{ name?: string; voice?: string; style?: string }>;
    voiceRows.forEach((voiceRow) => {
      const card = cards.find((item) => item.name === voiceRow.name);
      if (card) { card.voice = voiceRow.voice; card.style = voiceRow.style; }
      else if (voiceRow.name) cards.push({ name: voiceRow.name, role: "Assigned character", details: "Voice assignment recorded in the production brief.", voice: voiceRow.voice, style: voiceRow.style });
    });
  } catch {
    // Older manifests may contain plain-text voice assignments.
  }
  return cards;
}

function ratingValue(story: StoryDetail) {
  const reviewScore = story.review?.overall_score;
  const raw = story.critic_rating ?? story.rating ?? reviewScore;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : undefined;
}

function statusLabel(story: StoryDetail) {
  if (story.completion?.complete || story.status === "complete") return "Complete";
  if (story.status === "generating") return "Generating";
  const missing = Array.isArray(story.completion?.missing) ? story.completion.missing.length : 0;
  return missing ? `${missing} completion gaps` : "Needs editorial pass";
}

function mediaUrl(value: string | undefined, storyId: string) {
  if (!value) return undefined;
  if (/^(https?:|data:|\/)/.test(value)) return value;
  return `/generated/${storyId}/${value.replace(/^\.\//, "")}`;
}

export function StoryDetails({ story, onBack, onOpenEditor, onPlay, onDeleted }: StoryDetailsProps) {
  const [detail, setDetail] = useState<StoryDetail>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [editingDirection, setEditingDirection] = useState(false);
  const [directionBusy, setDirectionBusy] = useState(false);
  const [directionMessage, setDirectionMessage] = useState<string>();
  const [operationBusy, setOperationBusy] = useState(false);
  const [operationMessage, setOperationMessage] = useState<string>();
  const [zoomedImage, setZoomedImage] = useState<{ url: string; alt: string }>();
  const [direction, setDirection] = useState({ story_concept: story.story_concept || story.description || "", style: story.style || "", tone: story.tone || "", voice_preset: story.voice_preset || "Dean" });

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(undefined);
    void api.story(story.id).then((result) => { if (active) setDetail(result); }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "Story details could not be loaded."); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [story.id]);

  useEffect(() => {
    const current = detail || story;
    setDirection({ story_concept: current.story_concept || current.description || "", style: current.style || "", tone: current.tone || "", voice_preset: current.voice_preset || "Dean" });
  }, [detail, story]);

  const saveDirection = async () => {
    setDirectionBusy(true);
    setDirectionMessage(undefined);
    try {
      await api.updateStoryBrief(story.id, direction);
      setDetail(await api.story(story.id));
      setEditingDirection(false);
      setDirectionMessage("Story direction saved. Rebuild the story when you are ready to apply it to the script and outcome.");
    } catch (reason) {
      setDirectionMessage(reason instanceof Error ? reason.message : "Story direction could not be saved.");
    } finally {
      setDirectionBusy(false);
    }
  };

  const rebuildStory = async () => {
    if (!window.confirm("Rebuild this story from the saved direction? The current production will be backed up before regeneration.")) return;
    setDirectionBusy(true);
    setOperationMessage(undefined);
    try {
      const result = await api.regenerateStory(story.id, true);
      const message = `${result.message} The new script, scenes, narration, and artwork will replace the current draft after the backup is secured.`;
      setDirectionMessage(message);
      setOperationMessage(message);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Story rebuild could not be started.";
      setDirectionMessage(message);
      setOperationMessage(message);
    } finally {
      setDirectionBusy(false);
    }
  };

  const repairStory = async () => {
    setOperationBusy(true);
    setOperationMessage(undefined);
    try {
      const result = await api.repairStory(story.id);
      setOperationMessage(`${result.message} The repair task is now in the production queue.`);
    } catch (reason) {
      setOperationMessage(reason instanceof Error ? reason.message : "Repair could not be started.");
    } finally {
      setOperationBusy(false);
    }
  };

  const retryCardArt = async () => {
    setOperationBusy(true);
    setOperationMessage(undefined);
    try {
      const result = await api.generateStoryThumbnail(story.id);
      setDetail((current) => current ? { ...current, story_thumbnail: result.filename } : current);
      setOperationMessage("Card artwork generated and linked to this story.");
    } catch (reason) {
      setOperationMessage(reason instanceof Error ? reason.message : "Card artwork could not be generated. Check that a GPU worker is online, then retry.");
    } finally {
      setOperationBusy(false);
    }
  };

  const deleteStory = async () => {
    if (!window.confirm(`Permanently delete ${story.title} and every generated asset? This cannot be undone.`)) return;
    setOperationBusy(true);
    setOperationMessage(undefined);
    try {
      const result = await api.deleteStory(story.id);
      setOperationMessage(result.message || "Story deletion started.");
      onDeleted();
    } catch (reason) {
      setOperationMessage(reason instanceof Error ? reason.message : "Story deletion could not be started.");
    } finally {
      setOperationBusy(false);
    }
  };

  const scanContext = async () => {
    setOperationBusy(true);
    setOperationMessage(undefined);
    try {
      const result = await api.scanStoryContext(story.id, true);
      setDetail(result.manifest);
      setOperationMessage(`Scanned ${result.summary.scenes} scene${result.summary.scenes === 1 ? "" : "s"} and recovered ${result.summary.characters} named character${result.summary.characters === 1 ? "" : "s"}. Review the saved canon below before rebuilding.`);
    } catch (reason) {
      setOperationMessage(reason instanceof Error ? reason.message : "Story context could not be recovered.");
    } finally {
      setOperationBusy(false);
    }
  };

  const source = detail || ({ ...story, scenes: [] } as StoryDetail);
  const lore = useMemo(() => parseLore(source.world_context || ""), [source.world_context]);
  const characters = useMemo(() => parseCharacters(lore, source.voice_assignments || ""), [lore, source.voice_assignments]);
  const images = Array.from(new Set((source.scenes || []).flatMap((scene) => (scene.image_urls || []).map((image) => mediaUrl(image, source.id)).filter((image): image is string => Boolean(image))))).slice(0, 12);
  const contextMissing = !lore.length || !characters.length;
  const rating = ratingValue(source);
  const cover = mediaUrl(source.cover_image_url || source.hero_image, source.id) || images[0];

  return <div className="story-details-page">
    <div className="story-details-topbar"><button type="button" className="outline-button" onClick={onBack}><ChevronLeft size={15}/> Back to library</button><span className="eyebrow-label">Story details</span><span className={`story-details-status ${source.status === "complete" ? "ready" : "attention"}`}>{statusLabel(source)}</span></div>
    {loading && <div className="story-details-loading"><span className="led amber"/> Reading the story manifest and canon...</div>}
    {error && <div className="story-details-loading"><span className="led red"/> {error}</div>}
    <section className="story-details-hero"><div className="story-details-cover">{cover ? <img src={cover} alt=""/> : <Image size={38}/>}</div><div className="story-details-hero-copy"><span className="eyebrow-label">Origin story</span><h1>{source.title}</h1><p>{source.description || "No synopsis has been recorded for this story yet."}</p><div className="story-details-actions"><button type="button" className="create" onClick={onOpenEditor}><Pencil size={15}/> Edit scenes and narration</button><button type="button" className="outline-button" onClick={() => setEditingDirection((current) => !current)}><BookOpen size={15}/> {editingDirection ? "Close story direction" : "Edit story direction"}</button><button type="button" className="outline-button" disabled={operationBusy || directionBusy} onClick={() => void repairStory()}><Wrench size={15}/> Repair missing assets</button><button type="button" className="outline-button" disabled={operationBusy || directionBusy} onClick={() => void rebuildStory()}><RefreshCw size={15}/> Re-run full generation</button><button type="button" className="outline-button" disabled={operationBusy || directionBusy} onClick={() => void retryCardArt()}><Image size={15}/> Retry card art</button><button type="button" className="outline-button" disabled={!source.completion?.full_video_ok} onClick={onPlay}><Play size={15}/> Play release</button><button type="button" className="danger" disabled={operationBusy || directionBusy} onClick={() => void deleteStory()}><Trash2 size={15}/> Delete story and assets</button></div>{operationMessage && <p className="story-details-operation-message">{operationMessage}</p>}</div><div className="story-details-rating"><span><Star size={16}/>{rating ? `${rating}/10` : "Unrated"}</span><small>Creative review</small></div></section>
    {editingDirection && <section className="story-details-panel story-direction-editor"><div className="story-details-heading"><div><span className="eyebrow-label">Story-level revision</span><h2>Change the direction</h2></div><small>Save, then rebuild to change the generated outcome.</small></div><label><span>Story concept</span><textarea value={direction.story_concept} onChange={(event) => setDirection({ ...direction, story_concept: event.target.value })}/></label><div className="story-direction-grid"><label><span>Visual language</span><input value={direction.style} onChange={(event) => setDirection({ ...direction, style: event.target.value })}/></label><label><span>Tone</span><input value={direction.tone} onChange={(event) => setDirection({ ...direction, tone: event.target.value })}/></label><label><span>Narrator</span><input value={direction.voice_preset} onChange={(event) => setDirection({ ...direction, voice_preset: event.target.value })}/></label></div><div className="story-direction-actions"><button type="button" className="outline-button" disabled={directionBusy} onClick={() => void saveDirection()}>Save direction</button><button type="button" className="create" disabled={directionBusy} onClick={() => void rebuildStory()}>Save and rebuild story</button>{directionMessage && <small>{directionMessage}</small>}</div></section>}
    <div className="story-details-meta"><span><strong>{source.scene_count || source.scenes.length}</strong> scenes</span><span><strong>{source.images_per_scene || "-"}</strong> visual beats</span><span><strong>{source.voice_preset || "Studio default"}</strong> narrator</span><span><strong>{source.style || "Unspecified"}</strong> visual language</span><span><strong>{source.tone || "Unspecified"}</strong> tone</span></div>
    <div className="story-details-grid">
      <section className="story-details-panel lore-panel"><div className="story-details-heading"><div><span className="eyebrow-label">Canon and context</span><h2>World knowledge</h2></div><div className="story-context-actions"><button type="button" className="outline-button" disabled={operationBusy} onClick={() => void scanContext()}><RefreshCw size={14}/> {contextMissing ? "Scan story context" : "Refresh context"}</button><BookOpen size={19}/></div></div>{lore.length ? <div className="lore-blocks">{lore.filter((block) => !block.title.toLowerCase().includes("character")).map((block) => <article key={block.title}><h3>{block.title}</h3><p>{block.body}</p></article>)}</div> : <p className="story-details-empty">This story has no saved world context yet. Scan the existing scenes to create an editable canon seed.</p>}</section>
      <section className="story-details-panel character-panel"><div className="story-details-heading"><div><span className="eyebrow-label">Cast and performance</span><h2>Characters</h2></div><Users size={19}/></div>{characters.length ? <div className="story-character-detail-grid">{characters.map((character) => <article className="story-character-detail" key={character.name}><div className="story-character-avatar">{character.name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase()}</div><div><h3>{character.name}</h3><span>{character.role}</span><p>{character.details}</p>{character.voice && <small>{character.voice}{character.style ? ` - ${character.style}` : ""}</small>}</div></article>)}</div> : <p className="story-details-empty">No character sheets were attached to this production.</p>}</section>
    </div>
    <section className="story-details-panel gallery-panel"><div className="story-details-heading"><div><span className="eyebrow-label">Generated assets</span><h2>Story artwork</h2></div><small>{images.length} linked images · click to view at 100%</small></div>{images.length ? <div className="story-details-gallery">{images.map((image, index) => { const alt = `${source.title} scene ${index + 1}`; return <button type="button" className="story-art-thumb" key={image} onClick={() => setZoomedImage({ url: image, alt })}><img src={image} alt={alt} onError={(event) => { event.currentTarget.style.display = "none"; event.currentTarget.parentElement?.classList.add("broken"); }}/></button>; })}</div> : <p className="story-details-empty">Artwork will appear here as scene images are approved.</p>}</section>
    <section className="story-details-panel metadata-panel"><div className="story-details-heading"><div><span className="eyebrow-label">Production record</span><h2>Configuration and evidence</h2></div></div><div className="story-metadata-grid"><div><span>State</span><strong>{statusLabel(source)}</strong></div><div><span>Voice model</span><strong>{source.voice_preset || "Studio default"}</strong></div><div><span>Narration style</span><strong>{source.narration_style || "Studio default"}</strong></div><div><span>Created</span><strong>{source.created_at ? new Date(Number(source.created_at) * 1000).toLocaleDateString() : "Unknown"}</strong></div><div><span>Story ID</span><strong>{source.id}</strong></div><div><span>Completion</span><strong>{source.completion?.complete ? "Verified" : "Evidence pending"}</strong></div></div></section>
    {zoomedImage && <div className="story-art-lightbox" role="dialog" aria-modal="true" aria-label="Full-size story artwork" onClick={() => setZoomedImage(undefined)}><div className="story-art-lightbox-inner" onClick={(event) => event.stopPropagation()}><div className="story-art-lightbox-bar"><span>100% preview</span><button type="button" className="icon-button" aria-label="Close artwork preview" onClick={() => setZoomedImage(undefined)}><X size={18}/></button></div><img src={zoomedImage.url} alt={zoomedImage.alt}/></div></div>}
  </div>;
}
