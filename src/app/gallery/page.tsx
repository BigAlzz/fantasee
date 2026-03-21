"use client";

import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { 
  ArrowLeft, Image as ImageIcon, Search, Trash2, 
  ExternalLink, RefreshCw, Play, Pause, X, 
  ChevronLeft, ChevronRight, Maximize2, BookOpen
} from "lucide-react";
import Link from "next/link";
import { useState, useEffect, useRef } from "react";
import { useTheme } from "@/context/ThemeContext";

export default function GalleryPage() {
  const { theme } = useTheme();
  const [searchQuery, setSearchQuery] = useState("");
  const [isSlideshowOpen, setIsSlideshowOpen] = useState(false);
  const [currentSlideIndex, setCurrentSlideIndex] = useState(0);
  const [showNav, setShowNav] = useState(true);
  const navTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Auto-hide navigation logic
  useEffect(() => {
    const handleMouseMove = () => {
      setShowNav(true);
      if (navTimerRef.current) clearTimeout(navTimerRef.current);
      
      // Hide UI after 3 seconds of inactivity
      navTimerRef.current = setTimeout(() => setShowNav(false), 3000);
    };

    window.addEventListener("mousemove", handleMouseMove);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      if (navTimerRef.current) clearTimeout(navTimerRef.current);
    };
  }, []);

  // Audio state for listen-along
  const [selectedStoryId, setSelectedStoryId] = useState<string | null>(null);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [currentPartIndex, setCurrentPartIndex] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["gallery"],
    queryFn: async () => {
      const res = await fetch("/api/gallery");
      return res.json();
    }
  });

  const handleCleanup = async () => {
    if (!confirm("Are you sure you want to remove duplicate images from your library?")) return;
    const res = await fetch("/api/gallery", { method: "DELETE" });
    const result = await res.json();
    alert(`Cleaned up ${result.cleanedCount} duplicates!`);
    refetch();
  };

  const images = data?.images || [];
  const completedStories = data?.stories || [];
  const filteredImages = images.filter((img: any) => 
    img.promptText?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    img.story?.title?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Slideshow timer
  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (isSlideshowOpen && !isPlayingAudio) { // If audio playing, maybe sync or let it run
      timer = setInterval(() => {
        setCurrentSlideIndex(prev => (prev + 1) % (filteredImages.length || 1));
      }, 15000); // 15 seconds per slide
    }
    return () => clearInterval(timer);
  }, [isSlideshowOpen, filteredImages.length, isPlayingAudio]);

  // Audio player logic
  const toggleAudio = () => {
    if (!selectedStoryId) return;
    
    if (isPlayingAudio) {
      audioRef.current?.pause();
      setIsPlayingAudio(false);
    } else {
      const story = completedStories.find((s: any) => s.id === selectedStoryId);
      if (story) playStoryPart(story, currentPartIndex);
    }
  };

  const playStoryPart = (story: any, index: number) => {
    const part = story.parts?.[index];
    if (!part?.mergedAudioPath) {
      setIsPlayingAudio(false);
      return;
    }

    if (audioRef.current) audioRef.current.pause();
    
    const audio = new Audio(part.mergedAudioPath);
    audio.onended = () => {
      if (index < story.parts.length - 1) {
        setCurrentPartIndex(index + 1);
        playStoryPart(story, index + 1);
      } else {
        setIsPlayingAudio(false);
        setCurrentPartIndex(0);
      }
    };
    audio.play();
    audioRef.current = audio;
    setIsPlayingAudio(true);
    setCurrentPartIndex(index);
  };

  useEffect(() => {
    return () => {
      audioRef.current?.pause();
      audioRef.current = null;
    };
  }, []);

  const themeStyles = {
    dark: {
      container: "bg-zinc-950 text-zinc-100",
      card: "bg-zinc-900 border-zinc-800 hover:border-zinc-700",
      input: "bg-zinc-900 border-zinc-800 text-white focus:border-zinc-600",
      subText: "text-zinc-500",
      header: "text-zinc-50",
      select: "bg-zinc-900 border-zinc-800 text-zinc-200"
    },
    sepia: {
      container: "bg-[#f4ecd8] text-[#5b4636]",
      card: "bg-[#e8dfc4] border-[#5b4636]/10 hover:border-[#5b4636]/30",
      input: "bg-[#e8dfc4] border-[#5b4636]/20 text-[#433426] focus:border-[#5b4636]/40",
      subText: "text-[#5b4636]/60",
      header: "text-[#433426]",
      select: "bg-[#e8dfc4] border-[#5b4636]/20 text-[#433426]"
    },
    light: {
      container: "bg-white text-zinc-900",
      card: "bg-white border-zinc-200 hover:border-zinc-300 shadow-sm",
      input: "bg-zinc-50 border-zinc-200 text-zinc-900 focus:border-zinc-300",
      subText: "text-zinc-500",
      header: "text-black",
      select: "bg-zinc-50 border-zinc-200 text-zinc-900"
    }
  };

  const s = themeStyles[theme as keyof typeof themeStyles];

  return (
    <div className={`min-h-screen transition-colors duration-500 ${s.container}`}>
      <main className="container mx-auto px-4 py-8 max-w-6xl">
        <header className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6 mb-12">
          <div className="flex items-center gap-4">
            <Link href="/" className={`p-2.5 rounded-full border transition-all ${s.card}`}>
              <ArrowLeft size={20} />
            </Link>
            <div>
              <h1 className={`text-4xl font-bold tracking-tighter ${s.header}`}>Media Gallery</h1>
              <p className={s.subText}>Cinematic thumbnails & listen-along studio</p>
            </div>
          </div>

          <AnimatePresence>
            {showNav && (
              <motion.div 
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4, ease: "easeOut" }}
                className="flex flex-wrap items-center gap-4 w-full lg:w-auto"
              >
                {/* Story Selector */}
                <div className="flex items-center gap-3 bg-black/5 dark:bg-white/5 rounded-xl p-1 px-3 border border-current/10">
                  <BookOpen size={16} className="text-zinc-500" />
                  <select 
                    value={selectedStoryId || ""}
                    onChange={(e) => {
                      setSelectedStoryId(e.target.value);
                      setIsPlayingAudio(false);
                      setCurrentPartIndex(0);
                    }}
                    className={`bg-transparent text-xs font-bold focus:outline-none py-2 ${s.select}`}
                  >
                    <option value="">Listen to story...</option>
                    {completedStories.map((story: any) => (
                      <option key={story.id} value={story.id}>{story.title}</option>
                    ))}
                  </select>
                  {selectedStoryId && (
                    <button 
                      onClick={toggleAudio}
                      className={`p-2 rounded-lg transition-all ${isPlayingAudio ? 'bg-amber-400 text-zinc-950' : 'bg-zinc-800 text-white'}`}
                    >
                      {isPlayingAudio ? <Pause size={14} fill="currentColor" /> : <Play size={14} fill="currentColor" className="ml-0.5" />}
                    </button>
                  )}
                </div>

                <div className="relative flex-1 lg:w-64">
                  <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-zinc-500" size={18} />
                  <input 
                    type="text"
                    placeholder="Search keywords..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className={`w-full pl-12 pr-4 py-2.5 rounded-xl border focus:outline-none transition-all ${s.input}`}
                  />
                </div>
                
                <button 
                  onClick={() => setIsSlideshowOpen(true)}
                  className="flex items-center gap-2 px-4 py-2.5 bg-amber-400 text-zinc-950 rounded-xl font-bold text-sm hover:bg-amber-300 transition-all shadow-lg shadow-amber-400/10"
                >
                  <Maximize2 size={18} />
                  Slideshow
                </button>

                <button 
                  onClick={() => refetch()}
                  className={`p-2.5 rounded-xl border transition-all ${s.card}`}
                  title="Refresh Gallery"
                >
                  <RefreshCw size={20} />
                </button>
                <button 
                  onClick={handleCleanup}
                  className={`p-2.5 rounded-xl border border-red-500/20 text-red-400 hover:bg-red-500/10 transition-all ${s.card}`}
                  title="Cleanup Duplicates"
                >
                  <Trash2 size={20} />
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </header>

        {isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {[1, 2, 3, 4, 5, 6, 7, 8].map(i => (
              <div key={i} className={`aspect-video rounded-xl animate-pulse ${s.card}`} />
            ))}
          </div>
        ) : filteredImages.length === 0 ? (
          <div className="text-center py-24">
            <ImageIcon className="mx-auto text-zinc-700 mb-4 opacity-20" size={64} />
            <h3 className="text-xl font-medium text-zinc-400">No media found</h3>
            <p className={s.subText}>Try a different search or generate more stories.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            <AnimatePresence mode="popLayout">
              {filteredImages.map((img: any) => (
                <motion.div
                  key={img.id}
                  layout
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.9 }}
                  className={`group relative aspect-video rounded-xl overflow-hidden border transition-all ${s.card}`}
                >
                  <img 
                    src={img.filePath} 
                    alt={img.promptText} 
                    className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                  />
                  
                  {/* Overlay */}
                  <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity p-4 flex flex-col justify-end">
                    <p className="text-[10px] text-amber-400 font-bold uppercase tracking-widest mb-1 truncate">
                      {img.promptText}
                    </p>
                    <p className="text-[9px] text-zinc-300 font-medium truncate mb-2">
                      From: {img.story?.title}
                    </p>
                    <div className="flex gap-2">
                      <Link 
                        href={`/stories/${img.storyId}`}
                        className="p-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-white transition-colors"
                        title="View Story"
                      >
                        <ExternalLink size={14} />
                      </Link>
                      <button 
                        className="p-1.5 bg-red-500/20 hover:bg-red-500/40 rounded-lg text-red-400 transition-colors"
                        title="Delete from cache"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </main>

      {/* Fullscreen Slideshow Overlay */}
      <AnimatePresence>
        {isSlideshowOpen && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[200] bg-black flex flex-col"
          >
            <AnimatePresence>
              {showNav && (
                <motion.button 
                  initial={{ opacity: 0, y: -20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  onClick={() => setIsSlideshowOpen(false)}
                  className="absolute top-6 right-6 p-3 bg-white/10 hover:bg-white/20 rounded-full text-white z-[210] transition-all"
                >
                  <X size={24} />
                </motion.button>
              )}
            </AnimatePresence>

            <div className="flex-1 relative flex items-center justify-center overflow-hidden">
              <AnimatePresence mode="wait">
                <motion.div
                  key={currentSlideIndex}
                  initial={{ opacity: 0, scale: 1.1 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ duration: 1.5, ease: "easeInOut" }}
                  className="absolute inset-0"
                >
                  <img 
                    src={filteredImages[currentSlideIndex]?.filePath} 
                    alt="Slideshow"
                    className="w-full h-full object-cover"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent" />
                </motion.div>
              </AnimatePresence>

              {/* Slide Controls */}
              <AnimatePresence>
                {showNav && (
                  <>
                    <motion.button 
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -20 }}
                      onClick={() => setCurrentSlideIndex(prev => (prev - 1 + filteredImages.length) % filteredImages.length)}
                      className="absolute left-6 p-4 bg-white/5 hover:bg-white/10 rounded-full text-white/50 hover:text-white transition-all z-[210]"
                    >
                      <ChevronLeft size={32} />
                    </motion.button>
                    <motion.button 
                      initial={{ opacity: 0, x: 20 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: 20 }}
                      onClick={() => setCurrentSlideIndex(prev => (prev + 1) % filteredImages.length)}
                      className="absolute right-6 p-4 bg-white/5 hover:bg-white/10 rounded-full text-white/50 hover:text-white transition-all z-[210]"
                    >
                      <ChevronRight size={32} />
                    </motion.button>
                  </>
                )}
              </AnimatePresence>
            </div>

            {/* Slide Info & Audio Integration */}
            <AnimatePresence>
              {showNav && (
                <motion.div 
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 20 }}
                  className="p-12 bg-black/40 backdrop-blur-md border-t border-white/5"
                >
                  <div className="max-w-4xl mx-auto flex justify-between items-end">
                    <div>
                      <p className="text-amber-400 text-xs font-bold uppercase tracking-[0.2em] mb-2">Cinematic Gallery</p>
                      <h2 className="text-3xl font-bold text-white tracking-tight">
                        {filteredImages[currentSlideIndex]?.promptText}
                      </h2>
                      <p className="text-zinc-400 mt-2 italic">
                        Origin: {filteredImages[currentSlideIndex]?.story?.title}
                      </p>
                    </div>
                    
                    {selectedStoryId && (
                      <div className="flex items-center gap-6 bg-white/5 rounded-2xl p-4 border border-white/10">
                        <div className="text-right">
                          <p className="text-[10px] text-zinc-500 uppercase font-bold tracking-widest">Listening To</p>
                          <p className="text-sm font-medium text-white">{completedStories.find((s:any)=>s.id === selectedStoryId)?.title}</p>
                        </div>
                        <button 
                          onClick={toggleAudio}
                          className={`w-12 h-12 rounded-full flex items-center justify-center transition-all ${isPlayingAudio ? 'bg-amber-400 text-zinc-950' : 'bg-white text-zinc-950 hover:scale-105'}`}
                        >
                          {isPlayingAudio ? <Pause size={24} fill="currentColor" /> : <Play size={24} fill="currentColor" className="ml-1" />}
                        </button>
                      </div>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
