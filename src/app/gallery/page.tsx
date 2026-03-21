"use client";

import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { 
  ArrowLeft, Image as ImageIcon, Search, Trash2, 
  ExternalLink, RefreshCw, Play, Pause, X, 
  ChevronLeft, ChevronRight, Maximize2, BookOpen, SkipBack, SkipForward
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, useEffect, useRef, Suspense } from "react";
import { useTheme } from "@/context/ThemeContext";

function GalleryContent() {
  const { theme } = useTheme();
  const searchParams = useSearchParams();
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

  // Handle URL Params
  useEffect(() => {
    const storyId = searchParams.get('story');
    const startSlideshow = searchParams.get('slideshow') === 'true';
    
    if (storyId) {
      setSelectedStoryId(storyId);
      if (startSlideshow) {
        setIsSlideshowOpen(true);
      }
    }
  }, [searchParams]);

  const handleCleanup = async () => {
    if (!confirm("Are you sure you want to remove duplicate images from your library?")) return;
    const res = await fetch("/api/gallery", { method: "DELETE" });
    const result = await res.json();
    alert(`Cleaned up ${result.cleanedCount} duplicates!`);
    refetch();
  };

  const images = data?.images || [];
  const completedStories = data?.stories || [];
  
  // Filtering logic: prioritize selected story ID if present, otherwise use search query
  const filteredImages = images.filter((img: any) => {
    if (selectedStoryId && img.storyId === selectedStoryId) return true;
    if (selectedStoryId && !searchQuery) return false; // If story selected but not searching, only show that story
    
    const query = searchQuery.toLowerCase();
    return img.promptText?.toLowerCase().includes(query) ||
           img.story?.title?.toLowerCase().includes(query);
  });

  // Slideshow timer
  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (isSlideshowOpen && !isPlayingAudio) {
      timer = setInterval(() => {
        setCurrentSlideIndex(prev => (prev + 1) % (filteredImages.length || 1));
      }, 10000); // 10 seconds per slide
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
              <h1 className={`text-3xl sm:text-4xl font-bold tracking-tighter ${s.header}`}>Media Gallery</h1>
              <p className={`text-xs sm:text-sm ${s.subText}`}>Cinematic thumbnails & listen-along studio</p>
            </div>
          </div>

          <AnimatePresence>
            {showNav && (
              <motion.div 
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4, ease: "easeOut" }}
                className="flex flex-wrap items-center gap-3 w-full lg:w-auto"
              >
                {/* Story Selector */}
                <div className="flex items-center gap-2 bg-black/5 dark:bg-white/5 rounded-xl p-1 px-3 border border-current/10 flex-1 sm:flex-initial">
                  <BookOpen size={14} className="text-zinc-500" />
                  <select 
                    value={selectedStoryId || ""}
                    onChange={(e) => {
                      setSelectedStoryId(e.target.value);
                      setIsPlayingAudio(false);
                      setCurrentPartIndex(0);
                    }}
                    className={`bg-transparent text-[10px] sm:text-xs font-bold focus:outline-none py-2 flex-1 ${s.select}`}
                  >
                    <option value="">All Stories</option>
                    {completedStories.map((story: any) => (
                      <option key={story.id} value={story.id}>{story.title}</option>
                    ))}
                  </select>
                  {selectedStoryId && (
                    <button 
                      onClick={toggleAudio}
                      className={`p-1.5 rounded-lg transition-all ${isPlayingAudio ? 'bg-amber-400 text-zinc-950' : 'bg-zinc-800 text-white'}`}
                    >
                      {isPlayingAudio ? <Pause size={12} fill="currentColor" /> : <Play size={12} fill="currentColor" className="ml-0.5" />}
                    </button>
                  )}
                </div>

                <div className="flex items-center gap-2 w-full sm:w-auto">
                  <button 
                    onClick={handleCleanup}
                    className={`flex-1 sm:flex-initial flex items-center justify-center gap-2 px-4 py-2 rounded-xl border text-xs font-bold transition-all ${s.card}`}
                    title="Remove Duplicate Images"
                  >
                    <RefreshCw size={14} />
                    <span className="sm:hidden lg:inline">Clean</span>
                  </button>
                  
                  <button 
                    onClick={() => {
                      if (filteredImages.length > 0) {
                        setIsSlideshowOpen(true);
                        setCurrentSlideIndex(0);
                      }
                    }}
                    className="flex-1 sm:flex-initial flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-zinc-100 text-zinc-950 text-xs font-bold hover:bg-white transition-all shadow-lg shadow-zinc-100/10"
                  >
                    <Play size={14} fill="currentColor" />
                    Slideshow
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </header>

        {/* Search Bar */}
        <div className="relative mb-8">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-zinc-500" size={18} />
          <input 
            type="text"
            placeholder="Search scenes or stories..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={`w-full pl-12 pr-4 py-3 rounded-2xl border outline-none transition-all ${s.input}`}
          />
        </div>

        {isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {[1, 2, 3, 4, 5, 6, 7, 8].map(i => (
              <div key={i} className={`aspect-square rounded-2xl animate-pulse border ${s.card}`} />
            ))}
          </div>
        ) : filteredImages.length === 0 ? (
          <div className="text-center py-24">
            <ImageIcon className="mx-auto text-zinc-700 mb-4" size={48} />
            <h3 className="text-xl font-medium text-zinc-500">No images found</h3>
            <p className={s.subText}>Try a different search or generate more stories.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {filteredImages.map((img: any, index: number) => (
              <motion.div 
                key={img.id}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: index * 0.05 }}
                className={`group relative aspect-square rounded-2xl overflow-hidden border cursor-pointer ${s.card}`}
                onClick={() => {
                  setCurrentSlideIndex(index);
                  setIsSlideshowOpen(true);
                }}
              >
                <img 
                  src={img.filePath} 
                  alt={img.promptText}
                  className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-500"
                />
                <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-4">
                  <p className="text-[10px] font-bold text-amber-400 uppercase tracking-widest mb-1">{img.story?.title || 'Standalone'}</p>
                  <p className="text-white text-xs line-clamp-2 italic">"{img.promptText}"</p>
                </div>
              </motion.div>
            ))}
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
            className="fixed inset-0 z-[200] bg-black flex items-center justify-center"
          >
            <div className="absolute inset-0">
              <AnimatePresence mode="wait">
                <motion.img 
                  key={filteredImages[currentSlideIndex]?.id}
                  src={filteredImages[currentSlideIndex]?.filePath}
                  initial={{ opacity: 0, scale: 1.1 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ duration: 1.5, ease: "easeOut" }}
                  className="w-full h-full object-cover"
                />
              </AnimatePresence>
              <div className="absolute inset-0 bg-gradient-to-t from-black via-transparent to-black/40" />
            </div>

            {/* Slideshow Controls */}
            <div className={`absolute inset-0 flex flex-col justify-between p-4 sm:p-8 transition-opacity duration-500 ${showNav ? 'opacity-100' : 'opacity-0'}`}>
              <header className="flex justify-between items-start">
                <div className="space-y-1">
                  <h2 className="text-xl sm:text-2xl font-bold text-white tracking-tight drop-shadow-lg">
                    {filteredImages[currentSlideIndex]?.story?.title || 'Fantasee Gallery'}
                  </h2>
                  <p className="text-xs sm:text-sm text-zinc-300 italic max-w-2xl line-clamp-2 drop-shadow-md">
                    "{filteredImages[currentSlideIndex]?.promptText}"
                  </p>
                </div>
                <button 
                  onClick={() => setIsSlideshowOpen(false)}
                  className="p-2 sm:p-3 bg-white/10 hover:bg-white/20 text-white rounded-full backdrop-blur-md transition-all"
                >
                  <X size={24} />
                </button>
              </header>

              <div className="flex items-center justify-between pointer-events-none">
                <button 
                  onClick={(e) => {
                    e.stopPropagation();
                    setCurrentSlideIndex(prev => (prev - 1 + filteredImages.length) % filteredImages.length);
                  }}
                  className="p-3 sm:p-4 bg-white/5 hover:bg-white/10 text-white rounded-full backdrop-blur-md transition-all pointer-events-auto"
                >
                  <ChevronLeft size={32} />
                </button>
                
                <div className="flex items-center gap-4 sm:gap-6 pointer-events-auto">
                  {selectedStoryId && (
                    <div className="flex items-center gap-3 bg-black/40 backdrop-blur-xl border border-white/10 rounded-full p-1.5 sm:p-2 px-4 sm:px-6">
                      <button onClick={toggleAudio} className="p-2 text-white hover:text-amber-400 transition-colors">
                        {isPlayingAudio ? <Pause size={24} fill="currentColor" /> : <Play size={24} fill="currentColor" className="ml-1" />}
                      </button>
                      <div className="h-4 w-px bg-white/10" />
                      <span className="text-[10px] sm:text-xs font-bold uppercase tracking-widest text-zinc-400">
                        {isPlayingAudio ? `Part ${currentPartIndex + 1}` : 'Paused'}
                      </span>
                    </div>
                  )}
                </div>

                <button 
                  onClick={(e) => {
                    e.stopPropagation();
                    setCurrentSlideIndex(prev => (prev + 1) % filteredImages.length);
                  }}
                  className="p-3 sm:p-4 bg-white/5 hover:bg-white/10 text-white rounded-full backdrop-blur-md transition-all pointer-events-auto"
                >
                  <ChevronRight size={32} />
                </button>
              </div>

              <footer className="flex justify-center gap-2 overflow-x-auto pb-4 no-scrollbar">
                {filteredImages.length < 20 && filteredImages.map((_, i) => (
                  <button 
                    key={i}
                    onClick={() => setCurrentSlideIndex(i)}
                    className={`w-1.5 h-1.5 rounded-full transition-all ${i === currentSlideIndex ? 'bg-amber-400 w-6' : 'bg-white/20'}`}
                  />
                ))}
              </footer>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function GalleryPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-zinc-950 flex items-center justify-center text-zinc-500">Loading Gallery...</div>}>
      <GalleryContent />
    </Suspense>
  );
}
