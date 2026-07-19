import { useState } from "react";
import { ArrowDownUp, ChevronRight, Grid2X2, Image, List } from "lucide-react";
import type { Story } from "./api";

type CatalogProps = {
  stories: Story[];
  selectedStoryId?: string;
  onSelectStory: (story: Story) => void;
  onOpenStory: (story: Story) => void;
};

type SortMode = "date-desc" | "date-asc" | "state" | "alpha";

function storyDate(story: Story) {
  return Number(story.updated_at || story.created_at || 0);
}

function storyState(story: Story) {
  if (story.completion?.complete || story.status === "complete") return { label: "Complete", tone: "ready" };
  const missing = Array.isArray(story.completion?.missing) ? story.completion.missing : [];
  if (missing.some((item) => String(item).includes("story"))) return { label: "Needs story", tone: "attention" };
  if (story.status === "generating") return { label: "Generating", tone: "working" };
  return { label: "Needs finishing", tone: "attention" };
}

function storyCover(story: Story) {
  return story.cover_image_url || story.hero_image || story.scene_art_urls?.[0];
}

function dateLabel(story: Story) {
  const value = storyDate(story);
  return value ? new Date(value * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "Undated";
}

export function LibraryCatalog({ stories, selectedStoryId, onSelectStory, onOpenStory }: CatalogProps) {
  const [mode, setMode] = useState<"cards" | "list">("cards");
  const [sort, setSort] = useState<SortMode>("date-desc");
  const sorted = [...stories].sort((a, b) => {
    if (sort === "alpha") return a.title.localeCompare(b.title);
    if (sort === "state") return storyState(a).label.localeCompare(storyState(b).label) || a.title.localeCompare(b.title);
    return sort === "date-asc" ? storyDate(a) - storyDate(b) : storyDate(b) - storyDate(a);
  });

  return <div className="library-catalog">
    <div className="library-catalog-toolbar">
      <div><span className="eyebrow-label">Story collection</span><small>Artwork, canon, and production state in one place.</small></div>
      <div className="library-catalog-controls">
        <label><ArrowDownUp size={13}/><span className="sr-only">Sort stories</span><select value={sort} onChange={(event) => setSort(event.target.value as SortMode)}><option value="date-desc">Newest first</option><option value="date-asc">Oldest first</option><option value="state">State</option><option value="alpha">Alphabetical</option></select></label>
        <div className="catalog-view-toggle" role="group" aria-label="Catalog view"><button type="button" className={mode === "cards" ? "active" : ""} onClick={() => setMode("cards")} aria-label="Card view"><Grid2X2 size={14}/></button><button type="button" className={mode === "list" ? "active" : ""} onClick={() => setMode("list")} aria-label="List view"><List size={15}/></button></div>
      </div>
    </div>
    {sorted.length ? mode === "cards" ? <div className="story-card-grid">{sorted.map((story) => { const state = storyState(story); const cover = storyCover(story); return <article className={`story-card ${story.id === selectedStoryId ? "selected" : ""}`} key={story.id}><button type="button" className="story-card-select" onClick={() => onSelectStory(story)}><div className="story-card-art">{cover ? <img src={cover} alt=""/> : <Image size={28}/>}<span className={`story-card-state ${state.tone}`}>{state.label}</span></div><div className="story-card-copy"><h3>{story.title}</h3><p>{story.description || "A production waiting for its first editorial note."}</p><div><span>{story.scene_count || 0} scenes</span><span>{dateLabel(story)}</span></div></div></button><button type="button" className="story-card-open" onClick={() => onOpenStory(story)} aria-label={`Open ${story.title} details`} title="Open story details"><ChevronRight size={17}/></button></article>; })}</div> : <div className="story-catalog-list">{sorted.map((story) => { const state = storyState(story); const cover = storyCover(story); return <article className={`story-catalog-row ${story.id === selectedStoryId ? "selected" : ""}`} key={story.id}><button type="button" className="story-catalog-select" onClick={() => onSelectStory(story)}><span className="story-catalog-thumb">{cover ? <img src={cover} alt=""/> : <Image size={15}/>}</span><span className="story-catalog-title"><strong>{story.title}</strong><small>{story.description || "No synopsis recorded."}</small></span><span className={`story-card-state ${state.tone}`}>{state.label}</span><span>{story.scene_count || 0} scenes</span><span>{dateLabel(story)}</span></button><button type="button" className="story-catalog-open" onClick={() => onOpenStory(story)} aria-label={`Open ${story.title} details`} title="Open story details"><ChevronRight size={17}/></button></article>; })}</div> : <div className="library-catalog-empty"><Image size={25}/><div><strong>Your story collection is ready for its first world.</strong><small>Create a story to see its artwork, canon, and production evidence here.</small></div></div>}
  </div>;
}
