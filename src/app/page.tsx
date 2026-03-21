"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { 
  Settings, Plus, Library, BookOpen, 
  Trash2, Wand2, Activity, Play, Pause, Palette, ImageIcon, Download, Video, Maximize2
} from "lucide-react";
import { JobMonitor } from "@/components/JobMonitor";
import { motion, AnimatePresence } from "framer-motion";
import StoryCreationFlow from "@/components/StoryCreationFlow";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTheme } from "@/context/ThemeContext";

export default function Home() {
  const { theme, toggleTheme } = useTheme();
  const queryClient = useQueryClient();
  const [isCreating, setIsCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [isJobMonitorOpen, setIsJobMonitorOpen] = useState(false);
  const [showNav, setShowNav] = useState(true);
  const navTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Auto-hide navigation logic
  useEffect(() => {
    const handleMouseMove = () => {
      setShowNav(true);
      if (navTimerRef.current) clearTimeout(navTimerRef.current);
      
      // Don't hide if creating story or job monitor is open
      if (!isCreating && !isJobMonitorOpen) {
        navTimerRef.current = setTimeout(() => setShowNav(false), 3000);
      }
    };

    window.addEventListener("mousemove", handleMouseMove);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      if (navTimerRef.current) clearTimeout(navTimerRef.current);
    };
  }, [isCreating, isJobMonitorOpen]);

  const themeStyles = {
    dark: {
      container: "bg-zinc-950 text-zinc-100",
      headerTitle: "text-zinc-50",
      iconInactive: "bg-zinc-900 border-zinc-800 text-zinc-400 hover:text-zinc-100 hover:border-zinc-700",
      card: "bg-zinc-900 border-zinc-800 hover:border-zinc-700",
      subText: "text-zinc-400",
      emptyState: "border-zinc-800 bg-zinc-900/20",
    },
    sepia: {
      container: "bg-[#f4ecd8] text-[#5b4636]",
      headerTitle: "text-[#433426]",
      iconInactive: "bg-[#e8dfc4] border-[#5b4636]/10 text-[#5b4636]/50 hover:text-[#5b4636] hover:border-[#5b4636]/30",
      card: "bg-[#e8dfc4] border-[#5b4636]/10 hover:border-[#5b4636]/30",
      subText: "text-[#5b4636]/60",
      emptyState: "border-[#5b4636]/20 bg-[#e8dfc4]/50",
    },
    light: {
      container: "bg-white text-zinc-900",
      headerTitle: "text-black",
      iconInactive: "bg-zinc-50 border-zinc-200 text-zinc-400 hover:text-zinc-900 hover:border-zinc-300",
      card: "bg-white border-zinc-200 hover:border-zinc-300 shadow-sm hover:shadow-md",
      subText: "text-zinc-500",
      emptyState: "border-zinc-200 bg-zinc-50",
    }
  };

  const s = themeStyles[theme];

  // Audio state
  const [playingStoryId, setPlayingStoryId] = useState<string | null>(null);
  const [playingPartIndex, setPlayingPartIndex] = useState(0);
  const [videoOptionId, setVideoOptionId] = useState<string | null>(null);
  const [videoConfig, setVideoConfig] = useState({ aspectRatio: '16:9', resolution: '1080p' });
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const togglePlay = (e: React.MouseEvent, story: any) => {
    e.preventDefault();
    e.stopPropagation();

    if (playingStoryId === story.id) {
      // Pause
      if (audioRef.current) {
        audioRef.current.pause();
      }
      setPlayingStoryId(null);
    } else {
      // Play from current part index (or start)
      playPart(story, playingStoryId === story.id ? playingPartIndex : 0);
    }
  };

  const playPart = (story: any, index: number) => {
    const part = story.parts?.[index];
    if (!part?.mergedAudioPath) {
      if (index === 0) alert("Audio not ready for this story yet.");
      setPlayingStoryId(null);
      return;
    }

    if (audioRef.current) {
      audioRef.current.pause();
    }

    const audio = new Audio(part.mergedAudioPath);
    audio.onended = () => {
      if (index < story.parts.length - 1) {
        setPlayingPartIndex(index + 1);
        playPart(story, index + 1);
      } else {
        setPlayingStoryId(null);
        setPlayingPartIndex(0);
      }
    };
    audio.play();
    audioRef.current = audio;
    setPlayingStoryId(story.id);
    setPlayingPartIndex(index);
  };

  // Cleanup audio on unmount
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, []);

  const { data: stories, isLoading, error } = useQuery({
    queryKey: ["stories"],
    queryFn: async () => {
      const res = await fetch("/api/stories");
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.error || "Failed to fetch stories");
      }
      return res.json();
    },
    refetchInterval: 5000, // Poll for background generation updates
  });

  const { data: globalJobsData } = useQuery({
    queryKey: ["global-jobs"],
    queryFn: async () => {
      // We can use a special story ID or a new endpoint for global jobs
      // For now, let's fetch jobs for the most recently active stories or a global endpoint
      const res = await fetch("/api/jobs/global");
      return res.json();
    },
    refetchInterval: 3000,
    enabled: isJobMonitorOpen
  });

  const jobs = globalJobsData?.jobs || [];
  const isWorkerAlive = globalJobsData?.workerHeartbeat ? (() => {
    const hb = globalJobsData.workerHeartbeat;
    // Normalize SQLite timestamp (YYYY-MM-DD HH:MM:SS) to ISO for reliable parsing
    const hbIso = hb.includes(' ') && !hb.includes('T') ? hb.replace(' ', 'T') + 'Z' : hb;
    const hbTime = new Date(hbIso).getTime();
    const nowTime = new Date().getTime();
    // Allow for some clock skew or UTC vs Local mismatch
    return Math.abs(nowTime - hbTime) < 30000; // 30 second window
  })() : false;

  const deleteStoryMutation = useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(`/api/stories/${id}`, {
        method: "DELETE",
      });
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stories"] });
      setDeletingId(null);
    },
  });

  const handleDelete = (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (confirm("Are you sure you want to delete this story? This cannot be undone.")) {
      setDeletingId(id);
      deleteStoryMutation.mutate(id);
    }
  };

  const handleExportVideo = async (e: React.MouseEvent, storyId: string) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      const res = await fetch(`/api/stories/${storyId}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          jobType: "export_video",
          payloadJson: JSON.stringify(videoConfig)
        }),
      });
      if (res.ok) {
        setIsJobMonitorOpen(true);
        setVideoOptionId(null);
      }
    } catch (err) {
      console.error("Failed to queue video export:", err);
    }
  };

  const handleOpenSlideshow = (e: React.MouseEvent, storyId: string) => {
    e.preventDefault();
    e.stopPropagation();
    window.location.href = `/gallery?story=${storyId}&slideshow=true`;
  };

  return (
    <div className={`min-h-screen transition-colors duration-500 ${s.container}`}>
      <main className="container mx-auto px-4 py-8 max-w-6xl">
        {/* Job Monitor Sidebar */}
        <div className="fixed inset-y-0 right-0 z-[100] pointer-events-none">
          <AnimatePresence>
            {isJobMonitorOpen && (
              <motion.div
                initial={{ x: "100%" }}
                animate={{ x: 0 }}
                exit={{ x: "100%" }}
                transition={{ type: "spring", damping: 25, stiffness: 200 }}
                className="pointer-events-auto h-full"
              >
                <JobMonitor 
                  jobs={jobs} 
                  isWorkerAlive={isWorkerAlive} 
                  onClose={() => setIsJobMonitorOpen(false)} 
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <header className="flex justify-between items-center mb-12">
          <div>
            <h1 className={`text-4xl font-bold tracking-tighter transition-colors duration-500 ${s.headerTitle}`}>FANTASEE</h1>
            <p className={`mt-1 transition-colors duration-500 ${s.subText}`}>Cinematic Story Studio</p>
          </div>
          <AnimatePresence>
            {showNav && (
              <motion.div 
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4, ease: "easeOut" }}
                className="flex gap-4"
              >
                <button 
                  onClick={toggleTheme}
                  className={`p-2.5 rounded-full transition-all border ${s.iconInactive}`}
                  title="Change Theme"
                >
                  <Palette size={22} />
                </button>
                <button 
                  onClick={() => setIsJobMonitorOpen(true)}
                  className={`p-2.5 rounded-full transition-all border ${
                    isJobMonitorOpen ? 'bg-amber-400/10 text-amber-400 border-amber-400/20' : s.iconInactive
                  }`}
                  title="Task Monitor"
                >
                  <Activity size={22} />
                </button>
                <Link
                  href="/gallery"
                  className={`p-2.5 rounded-full transition-all border ${s.iconInactive}`}
                  title="Media Gallery"
                >
                  <ImageIcon size={22} />
                </Link>
                <Link
                  href="/settings"
                  className={`p-2.5 rounded-full transition-all border ${s.iconInactive}`}
                  title="Settings"
                >
                  <Settings size={22} />
                </Link>
                <button 
                  onClick={() => setIsCreating(true)}
                  className="flex items-center gap-2 bg-zinc-100 text-zinc-950 px-4 py-2 rounded-full font-medium hover:bg-zinc-200 transition-colors"
                >
                  <Plus size={20} />
                  New Story
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </header>

        {isCreating ? (
          <StoryCreationFlow onCancel={() => setIsCreating(false)} />
        ) : (
          <section>
            <div className={`flex items-center gap-2 mb-6 transition-colors duration-500 ${s.subText}`}>
              <Library size={20} />
              <h2 className="font-semibold uppercase tracking-widest text-sm">Your Library</h2>
            </div>

            {isLoading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {[1, 2, 3].map((i) => (
                  <div key={i} className={`h-64 rounded-2xl animate-pulse border ${s.card}`} />
                ))}
              </div>
            ) : error || stories?.length === 0 || !Array.isArray(stories) ? (
              <div className={`text-center py-24 rounded-3xl border-2 border-dashed transition-colors duration-500 ${s.emptyState}`}>
                <BookOpen className="mx-auto text-zinc-700 mb-4" size={48} />
                <h3 className="text-xl font-medium text-zinc-300">
                  {error ? "Error loading library" : stories?.length === 0 ? "No stories yet" : "Error loading library"}
                </h3>
                <p className={`mt-2 mb-8 ${s.subText}`}>
                  {error 
                    ? (error as Error).message
                    : stories?.length === 0 
                      ? "Start your first cinematic adventure today."
                      : "Check your server connection or try refreshing."}
                </p>
                {error || !Array.isArray(stories) ? (
                  <button 
                    onClick={() => queryClient.invalidateQueries({ queryKey: ["stories"] })}
                    className="bg-zinc-800 text-zinc-200 px-6 py-2 rounded-lg hover:bg-zinc-700 transition-colors"
                  >
                    Refresh Library
                  </button>
                ) : (
                  <button 
                    onClick={() => setIsCreating(true)}
                    className="bg-zinc-800 text-zinc-200 px-6 py-2 rounded-lg hover:bg-zinc-700 transition-colors"
                  >
                    Create Story
                  </button>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-6">
                {stories.map((story: any) => (
                  <Link 
                    key={story.id} 
                    href={`/stories/${story.id}`}
                    className={`group relative h-72 sm:h-80 rounded-2xl overflow-hidden border transition-all duration-500 ${s.card}`}
                  >
                    <div className="absolute inset-0 bg-gradient-to-t from-black via-black/40 to-transparent z-10" />
                    
                    {/* Hover Summary Overlay (Hidden on touch devices) */}
                    <div className="absolute inset-0 z-20 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none hidden md:block">
                      <div className="absolute inset-0 bg-black/80 backdrop-blur-sm p-6 flex flex-col justify-center">
                        <p className="text-zinc-400 text-[10px] uppercase tracking-widest mb-2 font-bold">Story Summary</p>
                        <p className="text-zinc-200 text-sm leading-relaxed line-clamp-6 italic">
                          {story.parts?.find((p: any) => p.summary)?.summary || "Generating the opening chapters of this epic tale..."}
                        </p>
                      </div>
                    </div>

                    {/* Top Bar Controls */}
                    <div className="absolute top-3 left-3 right-3 z-30 flex justify-between items-start">
                      <div className="flex flex-col gap-2">
                        <button
                          onClick={(e) => togglePlay(e, story)}
                          className={`p-3 rounded-full backdrop-blur-md border border-white/10 transition-all ${
                            playingStoryId === story.id 
                              ? 'bg-amber-400 text-zinc-950 border-amber-400 opacity-100' 
                              : 'bg-black/40 text-white/70 hover:text-white hover:bg-black/60 opacity-100 md:opacity-0 md:group-hover:opacity-100'
                          }`}
                          title={playingStoryId === story.id ? "Pause Story" : "Play Story"}
                        >
                          {playingStoryId === story.id ? (
                            <Pause size={18} fill="currentColor" />
                          ) : (
                            <Play size={18} fill="currentColor" className="ml-0.5" />
                          )}
                        </button>

                        {story.status === 'complete' && (
                          <button
                            onClick={(e) => handleOpenSlideshow(e, story.id)}
                            className="p-3 bg-black/40 hover:bg-zinc-100 hover:text-zinc-950 text-white/70 rounded-full backdrop-blur-md border border-white/10 transition-all opacity-100 md:opacity-0 md:group-hover:opacity-100"
                            title="View Slideshow"
                          >
                            <Maximize2 size={18} />
                          </button>
                        )}
                      </div>

                      <div className="flex flex-col gap-2">
                        {story.status === 'complete' && (
                          <div className="relative">
                            <button
                              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setVideoOptionId(videoOptionId === story.id ? null : story.id); }}
                              className={`p-2 rounded-full backdrop-blur-md border transition-all ${
                                videoOptionId === story.id 
                                  ? 'bg-amber-400 text-zinc-950 border-amber-400 opacity-100' 
                                  : 'bg-black/40 text-white/70 hover:text-white border-white/10 opacity-100 md:opacity-0 md:group-hover:opacity-100'
                              }`}
                              title="Export Slideshow Video"
                            >
                              <Video size={16} />
                            </button>
                            
                            <AnimatePresence>
                              {videoOptionId === story.id && (
                                <motion.div 
                                  initial={{ opacity: 0, scale: 0.9, x: -20 }}
                                  animate={{ opacity: 1, scale: 1, x: 0 }}
                                  exit={{ opacity: 0, scale: 0.9, x: -20 }}
                                  className="absolute top-0 right-full mr-2 p-3 bg-zinc-900/95 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl z-50 min-w-[160px]"
                                >
                                  <div className="space-y-3">
                                    <div>
                                      <span className="text-[9px] uppercase tracking-widest font-bold text-zinc-500 mb-1.5 block">Ratio</span>
                                      <div className="flex gap-1">
                                        <button 
                                          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setVideoConfig(c => ({...c, aspectRatio: '16:9'})); }}
                                          className={`flex-1 py-1 rounded text-[10px] font-bold border ${videoConfig.aspectRatio === '16:9' ? 'bg-amber-400 text-zinc-950 border-amber-400' : 'border-white/10 hover:bg-white/5'}`}
                                        >
                                          16:9
                                        </button>
                                        <button 
                                          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setVideoConfig(c => ({...c, aspectRatio: '9:16'})); }}
                                          className={`flex-1 py-1 rounded text-[10px] font-bold border ${videoConfig.aspectRatio === '9:16' ? 'bg-amber-400 text-zinc-950 border-amber-400' : 'border-white/10 hover:bg-white/5'}`}
                                        >
                                          9:16
                                        </button>
                                      </div>
                                    </div>
                                    <div>
                                      <span className="text-[9px] uppercase tracking-widest font-bold text-zinc-500 mb-1.5 block">Quality</span>
                                      <div className="flex gap-1">
                                        <button 
                                          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setVideoConfig(c => ({...c, resolution: '720p'})); }}
                                          className={`flex-1 py-1 rounded text-[10px] font-bold border ${videoConfig.resolution === '720p' ? 'bg-amber-400 text-zinc-950 border-amber-400' : 'border-white/10 hover:bg-white/5'}`}
                                        >
                                          720p
                                        </button>
                                        <button 
                                          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setVideoConfig(c => ({...c, resolution: '1080p'})); }}
                                          className={`flex-1 py-1 rounded text-[10px] font-bold border ${videoConfig.resolution === '1080p' ? 'bg-amber-400 text-zinc-950 border-amber-400' : 'border-white/10 hover:bg-white/5'}`}
                                        >
                                          1080p
                                        </button>
                                      </div>
                                    </div>
                                    <button 
                                      onClick={(e) => handleExportVideo(e, story.id)}
                                      className="w-full py-1.5 bg-zinc-100 text-zinc-950 rounded-lg font-bold text-[10px] hover:bg-white transition-colors"
                                    >
                                      Queue Video
                                    </button>
                                  </div>
                                </motion.div>
                              )}
                            </AnimatePresence>
                          </div>
                        )}
                        
                        {story.videoPath && (
                          <a
                            href={story.videoPath}
                            download={`${story.title}.mp4`}
                            onClick={(e) => e.stopPropagation()}
                            className="p-2 bg-black/40 hover:bg-emerald-500/80 text-white/70 hover:text-white rounded-full backdrop-blur-md border border-white/10 transition-all opacity-100 md:opacity-0 md:group-hover:opacity-100"
                            title="Download MP4 Video"
                          >
                            <Download size={16} />
                          </a>
                        )}

                        <button
                          onClick={(e) => handleDelete(e, story.id)}
                          disabled={deletingId === story.id}
                          className="p-2 bg-black/40 hover:bg-red-500/80 text-white/70 hover:text-white rounded-full backdrop-blur-md border border-white/10 transition-all opacity-100 md:opacity-0 md:group-hover:opacity-100"
                          title="Delete Story"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>

                    {/* Now Playing Status (Mobile Optimized) */}
                    {playingStoryId === story.id && (
                      <div className="absolute top-3 left-14 z-30 flex items-center gap-2 px-3 py-1.5 bg-amber-400/10 border border-amber-400/20 rounded-full backdrop-blur-md">
                        <div className="flex gap-1">
                          {[1, 2, 3].map(i => (
                            <motion.div
                              key={i}
                              animate={{ height: [4, 10, 4] }}
                              transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.2 }}
                              className="w-0.5 bg-amber-400"
                            />
                          ))}
                        </div>
                        <span className="text-[9px] font-bold text-amber-400 uppercase tracking-wider">
                          Playing Part {playingPartIndex + 1}
                        </span>
                      </div>
                    )}

                    {story.coverImagePath ? (
                      <img src={story.coverImagePath} alt={story.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" />
                    ) : (
                      <div className="w-full h-full bg-zinc-800 flex items-center justify-center">
                        <span className="text-zinc-600 font-serif text-lg">{story.genre}</span>
                      </div>
                    )}
                    
                    <div className="absolute bottom-0 left-0 right-0 p-4 sm:p-6 z-20">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="inline-block px-2 py-0.5 bg-zinc-800 text-zinc-400 text-[9px] sm:text-[10px] uppercase tracking-wider rounded">
                          {story.genre}
                        </span>
                        {story.series && (
                          <span className="inline-block px-2 py-0.5 bg-amber-400/10 text-amber-400 border border-amber-400/20 text-[9px] sm:text-[10px] uppercase tracking-wider rounded font-bold">
                            {story.series.title}
                          </span>
                        )}
                      </div>
                      <h3 className="text-lg sm:text-xl font-bold text-white group-hover:text-zinc-200 transition-colors line-clamp-2">{story.title}</h3>
                      <div className="flex items-center justify-between mt-3 text-xs text-zinc-500">
                        <span>{story._count?.parts || 0} / {story.plannedParts} Parts</span>
                        <span className={`capitalize px-2 py-0.5 rounded-full text-[10px] border ${
                          story.status === 'generating' 
                            ? 'bg-amber-400/10 text-amber-400 border-amber-400/20 animate-pulse' 
                            : story.status === 'complete'
                            ? 'bg-emerald-400/10 text-emerald-400 border-emerald-400/20'
                            : 'bg-zinc-950 text-zinc-500 border-zinc-800'
                        }`}>
                          {story.status === 'complete' ? 'Generated' : story.status}
                        </span>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </section>
        )}
      </main>

      <AnimatePresence>
        {isJobMonitorOpen && (
          <JobMonitor 
            isOpen={isJobMonitorOpen} 
            onClose={() => setIsJobMonitorOpen(false)} 
          />
        )}
      </AnimatePresence>

      <audio ref={audioRef} className="hidden" />
    </div>
  );
}
