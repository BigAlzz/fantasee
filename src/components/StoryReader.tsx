"use client";

import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { 
  Play, Pause, SkipBack, SkipForward, 
  Settings, BookMarked, ArrowLeft,
  ChevronLeft, ChevronRight, Volume2,
  VolumeX, Plus, Loader2, Wand2,
  Type, Palette, Sparkles, ArrowRight, Download,
  User, Mic2, MessageSquare, Zap, Activity,
  Pin, PinOff, Video
} from "lucide-react";
import Link from "next/link";
import { JobMonitor } from "./JobMonitor";
import { useTheme } from "@/context/ThemeContext";

interface StoryReaderProps {
  storyId: string;
}

export default function StoryReader({ storyId }: StoryReaderProps) {
  const { theme, setTheme } = useTheme();
  const queryClient = useQueryClient();
  const [currentPartIndex, setCurrentPartIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isAudioEnabled, setIsAudioEnabled] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [fontSize, setFontSize] = useState(18);
  const [isRapidMode, setIsRapidMode] = useState(true);
  const [activeImage, setActiveImage] = useState<string | null>(null);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [activeSegmentIndex, setActiveSegmentIndex] = useState(0);
  const [lastCompletedJobId, setLastCompletedJobId] = useState<string | null>(null);
  const [isJobMonitorOpen, setIsJobMonitorOpen] = useState(false);
  const [showVideoOptions, setShowVideoOptions] = useState(false);
  const [videoConfig, setVideoConfig] = useState({ aspectRatio: '16:9', resolution: '1080p' });
  
  // Auto-hide UI state
  const [showUI, setShowUI] = useState(true);
  const [isUIPinned, setIsUIPinned] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('fantasee_ui_pinned') === 'true';
    }
    return false;
  });
  const inactivityTimerRef = useRef<NodeJS.Timeout | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const nextAudioRef = useRef<HTMLAudioElement | null>(null); // For preloading next segment
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const segmentRefs = useRef<(HTMLDivElement | null)[]>([]);

  const { data: story, isLoading } = useQuery({
    queryKey: ["story", storyId],
    queryFn: async () => {
      const res = await fetch(`/api/stories/${storyId}`);
      return res.json();
    },
    refetchInterval: (query) => {
      const data = query.state.data as any;
      // Refetch if the story is still generating OR if not all parts are present yet
      const isGenerating = data?.status === "generating";
      const hasMissingParts = data?.parts?.length < (data?.plannedParts || 0);
      return (isGenerating || hasMissingParts) ? 3000 : false;
    },
  });

  const { data: jobsData } = useQuery({
    queryKey: ["story-jobs", storyId],
    queryFn: async () => {
      const res = await fetch(`/api/stories/${storyId}/jobs`);
      return res.json();
    },
    refetchInterval: 2000,
    // Keep polling as long as there are incomplete parts or the story is still in a transitional state
    enabled: !!story && (
      story.status === "generating" || 
      story.status === "draft" || 
      (story.parts?.length || 0) < (story.plannedParts || 0)
    ),
  });

  const jobs = jobsData?.jobs || [];
  const workerHeartbeat = jobsData?.workerHeartbeat;
  const failedJob = jobs?.find((j: any) => j.status === "failed");

  const selectConceptMutation = useMutation({
    mutationFn: async (concept: any) => {
      const res = await fetch(`/api/stories/${storyId}/select-concept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ concept }),
      });
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["story", storyId] });
      queryClient.invalidateQueries({ queryKey: ["story-jobs", storyId] });
      // Ensure we are ready to play as soon as audio arrives
      setIsPlaying(true);
      setIsAudioEnabled(true);
    },
  });

  const conceptJob = jobs?.find((j: any) => j.jobType === "generate_concepts" && j.status === "done");
  const concepts = conceptJob?.resultJson ? JSON.parse(conceptJob.resultJson).concepts : null;

  const activeJob = jobs?.find((j: any) => j.status === "running" || j.status === "queued");
  const completedJobs = jobs?.filter((j: any) => j.status === "done").length || 0;
  const totalJobs = jobs?.length || 0;
  const progressPercent = totalJobs > 0 ? (completedJobs / totalJobs) * 100 : 0;

  // Check if worker is alive (heartbeat within last 30 seconds)
  const isWorkerAlive = workerHeartbeat ? (() => {
    const hb = workerHeartbeat;
    const hbIso = hb.includes(' ') && !hb.includes('T') ? hb.replace(' ', 'T') + 'Z' : hb;
    const hbTime = new Date(hbIso).getTime();
    const nowTime = new Date().getTime();
    return Math.abs(nowTime - hbTime) < 30000;
  })() : false;

  const currentPart = story?.parts?.[currentPartIndex];
  
  // Calculate final fallback index for UI highlighting if we aren't using the playlist state yet
  const currentTimeMs = currentTime * 1000;
  const finalActiveIndex = currentPart?.segments?.length ? activeSegmentIndex : -1;

  const [loadingMessage, setLoadingMessage] = useState("Preparing the stage...");
  
  // Auto-hide UI logic
  useEffect(() => {
    const handleMouseMove = () => {
      setShowUI(true);
      if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current);
      
      if (!isUIPinned) {
        inactivityTimerRef.current = setTimeout(() => {
          setShowUI(false);
        }, 4000); // 4 seconds timeout
      }
    };

    const handleMouseLeave = () => {
      if (!isUIPinned) {
        setShowUI(false);
      }
    };

    window.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseleave', handleMouseLeave);

    // Initial timer
    if (!isUIPinned) {
      inactivityTimerRef.current = setTimeout(() => {
        setShowUI(false);
      }, 4000);
    }

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseleave', handleMouseLeave);
      if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current);
    };
  }, [isUIPinned]);

  const togglePin = () => {
    const newState = !isUIPinned;
    setIsUIPinned(newState);
    localStorage.setItem('fantasee_ui_pinned', String(newState));
    if (newState) setShowUI(true);
  };

  // Browser Notification Request
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  }, []);

  // Monitor jobs for completion and notify
  useEffect(() => {
    const latestDoneJob = jobs?.find((j: any) => j.status === "done");
    if (latestDoneJob && latestDoneJob.id !== lastCompletedJobId) {
      setLastCompletedJobId(latestDoneJob.id);
      
      // If the user isn't looking at this tab, notify them
      if (document.hidden && Notification.permission === "granted") {
        let title = "Fantasee Update";
        let body = "";
        
        if (latestDoneJob.jobType === "generate_part") {
          body = `Chapter ${latestDoneJob.partNumber} is written!`;
        } else if (latestDoneJob.jobType === "generate_part_audio") {
          body = `Audio for Chapter ${latestDoneJob.partNumber} is ready.`;
        }
        
        if (body) {
          new Notification(title, { body, icon: "/favicon.ico" });
        }
      }
    }
  }, [jobs, lastCompletedJobId]);

  const loadingMessages = [
    "Consulting the digital scribes...",
    "Brewing some cinematic coffee...",
    "Teaching the characters their lines...",
    "Polishing the Unsplash lenses...",
    "Waking up the local LLM...",
    "Checking the plot for holes...",
    "Synchronizing the multiverse...",
    "Adding just a dash of drama...",
    "Negotiating with the background music...",
    "Ensuring the narrator has enough water...",
    "Washing the pixels...",
    "Sharpening the story arc..."
  ];

  useEffect(() => {
    if (!currentPart && (activeJob || story?.status === 'generating')) {
      const interval = setInterval(() => {
        setLoadingMessage(loadingMessages[Math.floor(Math.random() * loadingMessages.length)]);
      }, 6000); // Slower interval (6s)
      return () => clearInterval(interval);
    }
  }, [currentPart, activeJob, story?.status]);
  
  // Synchronized Slideshow Effect
  useEffect(() => {
    if (currentPart?.images?.length > 0) {
      const timeMs = currentTime * 1000;
      // Find the image that should be displayed at the current time
      const applicableImages = currentPart.images.filter((img: any) => (img.displayTimeMs || 0) <= timeMs);
      const latestImage = applicableImages[applicableImages.length - 1];
      if (latestImage) {
        setActiveImage(latestImage.filePath);
      }
    } else {
      setActiveImage(null);
    }
  }, [currentTime, currentPart]);

  // Smooth auto-scroll effect
  useEffect(() => {
    if (currentPart?.segments?.length > 0) {
      const activeElement = segmentRefs.current[activeSegmentIndex];
      if (activeElement) {
        activeElement.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }
    }
  }, [activeSegmentIndex, currentPart]);

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackRate;
      
      const currentSegment = currentPart?.segments?.[activeSegmentIndex];
      
      // HYBRID PLAYBACK STRATEGY:
      // 1. If the part is fully complete (has mergedAudioPath), use the SINGLE merged MP3.
      // 2. If it's still generating or only segments exist, use the SEGMENTED playlist.
      const useMergedAudio = currentPart?.mergedAudioPath && currentPart?.audioStatus === 'complete';
      const audioSource = useMergedAudio ? currentPart.mergedAudioPath : (currentSegment?.audioPath || currentPart?.mergedAudioPath);

      if (isPlaying && isAudioEnabled && audioSource) {
        // Only trigger play if source has changed or we were paused
        const fullSourceUrl = window.location.origin + audioSource;
        if (audioRef.current.src !== fullSourceUrl) {
          audioRef.current.src = audioSource;
          
          // If we are switching to a merged file, we might need to seek to the active segment's start position
          if (useMergedAudio && currentSegment?.startMs !== null) {
            const onCanPlay = () => {
              if (audioRef.current) {
                audioRef.current.currentTime = currentSegment.startMs / 1000;
                audioRef.current.removeEventListener('canplay', onCanPlay);
              }
            };
            audioRef.current.addEventListener('canplay', onCanPlay);
          }
        }
        
        const playPromise = audioRef.current.play();
        if (playPromise !== undefined) {
          playPromise.catch(error => {
            console.error("Playback failed:", error);
          });
        }
      } else {
        audioRef.current.pause();
      }
    }
    
    // Preload strategy:
    // If current part is done, preload next part's merged audio.
    // Otherwise, preload next segment.
    if (nextAudioRef.current) {
      let nextSource = null;
      if (currentPart?.audioStatus === 'complete' && story?.parts?.[currentPartIndex + 1]) {
        nextSource = story.parts[currentPartIndex + 1].mergedAudioPath;
      } else if (currentPart?.segments?.[activeSegmentIndex + 1]) {
        nextSource = currentPart.segments[activeSegmentIndex + 1].audioPath;
      }

      if (nextSource && nextAudioRef.current.src !== window.location.origin + nextSource) {
        nextAudioRef.current.src = nextSource;
        nextAudioRef.current.load();
      }
    }
  }, [isPlaying, isAudioEnabled, activeSegmentIndex, currentPartIndex, currentPart?.mergedAudioPath, currentPart?.audioStatus, playbackRate, story?.parts?.length]);

  const handleTimeUpdate = () => {
    if (audioRef.current) {
      const useMergedAudio = currentPart?.mergedAudioPath && currentPart?.audioStatus === 'complete';
      
      if (useMergedAudio) {
        // We are playing the single merged file. 
        // We need to update activeSegmentIndex based on current time using our timing data.
        const timeMs = audioRef.current.currentTime * 1000;
        const newSegmentIndex = currentPart.segments.findIndex((seg: any) => {
          if (seg.startMs !== null && seg.endMs !== null) {
            // Use a small buffer (50ms) to ensure continuous highlighting
            return timeMs >= seg.startMs && timeMs < (seg.endMs + 50);
          }
          return false;
        });

        if (newSegmentIndex !== -1 && newSegmentIndex !== activeSegmentIndex) {
          setActiveSegmentIndex(newSegmentIndex);
        }
        setCurrentTime(audioRef.current.currentTime);
      } else {
        // Playlist mode: handle progress bar by adding segment offset
        const currentSegment = currentPart?.segments?.[activeSegmentIndex];
        if (currentSegment && currentSegment.startMs !== null) {
          setCurrentTime((currentSegment.startMs / 1000) + audioRef.current.currentTime);
        } else {
          setCurrentTime(audioRef.current.currentTime);
        }
      }
    }
  };

  const handleEnded = () => {
    const useMergedAudio = currentPart?.mergedAudioPath && currentPart?.audioStatus === 'complete';
    
    if (useMergedAudio) {
      // Merged file ended -> go to next PART
      if (story?.parts && currentPartIndex < story.parts.length - 1) {
        setTimeout(() => handleNextPart(), 500);
      } else {
        setIsPlaying(false);
      }
    } else {
      // Playlist mode -> go to next SEGMENT
      if (currentPart?.segments && activeSegmentIndex < currentPart.segments.length - 1) {
        setActiveSegmentIndex(prev => prev + 1);
      } else if (story?.parts && currentPartIndex < story.parts.length - 1) {
        setTimeout(() => handleNextPart(), 500);
      } else {
        setIsPlaying(false);
      }
    }
  };

  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    if (audioRef.current && currentPart?.durationSeconds) {
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const percent = x / rect.width;
      const targetTimeTotal = percent * currentPart.durationSeconds;
      
      // Find which segment this time belongs to
      if (currentPart.segments?.length > 0) {
        const segmentIndex = currentPart.segments.findIndex((seg: any) => {
          const start = (seg.startMs || 0) / 1000;
          const end = (seg.endMs || (currentPart.durationSeconds * 1000)) / 1000;
          return targetTimeTotal >= start && targetTimeTotal < end;
        });

        if (segmentIndex !== -1) {
          const seg = currentPart.segments[segmentIndex];
          const segStart = (seg.startMs || 0) / 1000;
          
          setActiveSegmentIndex(segmentIndex);
          // We can't immediately set currentTime on the audio element if we just changed the src
          // but we can update the UI immediately
          setCurrentTime(targetTimeTotal);
          
          // The useEffect will handle loading the new src. 
          // We might need a small delay or a ref to seek after load.
          setTimeout(() => {
            if (audioRef.current) {
              audioRef.current.currentTime = targetTimeTotal - segStart;
            }
          }, 100);
        }
      } else {
        audioRef.current.currentTime = targetTimeTotal;
        setCurrentTime(targetTimeTotal);
      }
    }
  };

  const handleNextPart = () => {
    if (story?.parts && currentPartIndex < story.parts.length - 1) {
      setCurrentPartIndex(currentPartIndex + 1);
      setActiveSegmentIndex(0);
      setCurrentTime(0);
      setIsPlaying(true);
    }
  };

  const handleExportVideo = async () => {
    if (!storyId) return;
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
        setShowVideoOptions(false);
      }
    } catch (err) {
      console.error("Failed to queue video export:", err);
    }
  };

  const extendStoryMutation = useMutation({
    mutationFn: async (additionalParts: number) => {
      const res = await fetch(`/api/stories/${storyId}/extend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ additionalParts }),
      });
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["story", storyId] });
      queryClient.invalidateQueries({ queryKey: ["story-jobs", storyId] });
    },
  });

  const handlePrevPart = () => {
    if (currentPartIndex > 0) {
      setCurrentPartIndex(currentPartIndex - 1);
      setActiveSegmentIndex(0);
      setCurrentTime(0);
      setIsPlaying(true);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="w-12 h-12 border-4 border-zinc-100 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const themeStyles = {
    dark: {
      container: "bg-zinc-950 text-zinc-300 selection:bg-zinc-100/20",
      header: "border-white/5 bg-zinc-950/50 text-white",
      title: "text-zinc-100",
      activeText: "text-white font-medium",
      inactiveText: "text-zinc-500",
      dialogueText: "text-zinc-400",
      iconActive: "bg-zinc-100 text-zinc-900 border-zinc-100",
      iconInactive: "bg-zinc-900 border-zinc-800 text-zinc-500 group-hover:text-zinc-300",
      overlay: "bg-gradient-to-b from-transparent via-transparent to-black/80",
      buttonPrimary: "bg-amber-400 text-zinc-950 hover:bg-amber-300",
      buttonSecondary: "bg-zinc-800 text-zinc-100 hover:bg-zinc-700",
      tooltip: "bg-zinc-800 text-white border-white/10"
    },
    sepia: {
      container: "bg-[#f4ecd8] text-[#5b4636] selection:bg-[#5b4636]/20",
      header: "border-[#5b4636]/10 bg-[#f4ecd8]/80 text-[#5b4636]",
      title: "text-[#433426]",
      activeText: "text-[#433426] font-bold",
      inactiveText: "text-[#5b4636]/40",
      dialogueText: "text-[#5b4636]/60",
      iconActive: "bg-[#5b4636] text-[#f4ecd8] border-[#5b4636]",
      iconInactive: "bg-[#e8dfc4] border-[#5b4636]/10 text-[#5b4636]/50 group-hover:text-[#5b4636]",
      overlay: "bg-gradient-to-b from-transparent via-[#f4ecd8]/40 to-[#f4ecd8]/95",
      buttonPrimary: "bg-[#5b4636] text-[#f4ecd8] hover:bg-[#433426]",
      buttonSecondary: "bg-[#e8dfc4] text-[#5b4636] hover:bg-[#dcd1b4]",
      tooltip: "bg-[#5b4636] text-[#f4ecd8] border-[#5b4636]/10"
    },
    light: {
      container: "bg-white text-zinc-900 selection:bg-zinc-900/10",
      header: "border-zinc-100 bg-white/80 text-zinc-900",
      title: "text-black",
      activeText: "text-black font-bold",
      inactiveText: "text-zinc-400",
      dialogueText: "text-zinc-500",
      iconActive: "bg-zinc-900 text-white border-zinc-900",
      iconInactive: "bg-zinc-50 border-zinc-100 text-zinc-400 group-hover:text-zinc-900",
      overlay: "bg-gradient-to-b from-transparent via-white/40 to-white/95",
      buttonPrimary: "bg-zinc-900 text-white hover:bg-black",
      buttonSecondary: "bg-zinc-100 text-zinc-900 hover:bg-zinc-200",
      tooltip: "bg-zinc-900 text-white border-zinc-800"
    }
  };

  const currentStyle = themeStyles[theme as keyof typeof themeStyles];

  return (
    <div className={`min-h-screen transition-colors duration-500 ${currentStyle.container}`}>
      {/* Background Image with Overlay */}
      <AnimatePresence mode="wait">
        {activeImage && (
          <motion.div
            key={activeImage}
            initial={{ opacity: 0 }}
            animate={{ opacity: isRapidMode ? 0.25 : 0.15 }}
            exit={{ opacity: 0 }}
            transition={{ duration: isRapidMode ? 1 : 2 }}
            className="fixed inset-0 z-0 pointer-events-none"
          >
            <img 
              src={activeImage} 
              alt="Scene background" 
              className={`w-full h-full object-cover ${isRapidMode ? '' : 'grayscale'}`}
            />
            <div className={`absolute inset-0 ${currentStyle.overlay}`} />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Top Bar */}
      <header className={`fixed top-0 left-0 right-0 h-16 border-b backdrop-blur-md z-50 px-4 sm:px-6 flex items-center justify-between transition-all duration-500 ${currentStyle.header} ${showUI || isUIPinned ? 'translate-y-0 opacity-100' : '-translate-y-full opacity-0'}`}>
        <div className="flex items-center gap-2 sm:gap-4 overflow-hidden">
          <Link href="/" className="p-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-full transition-colors flex-shrink-0">
            <ArrowLeft size={20} />
          </Link>
          <div className="overflow-hidden">
            <h1 className="text-xs sm:text-sm font-bold tracking-tight truncate max-w-[120px] sm:max-w-none">{story?.title}</h1>
            <p className="text-[9px] sm:text-[10px] uppercase tracking-widest opacity-50">
              Part {currentPartIndex + 1} / {story?.plannedParts || 0}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1 sm:gap-2">
          {/* Persistent Worker Status (Hidden on very small screens) */}
          <div className="hidden xs:flex items-center gap-3 px-3 py-1.5 bg-black/5 dark:bg-zinc-900/50 border border-current/5 rounded-full mr-1 sm:mr-2">
            <div className={`w-1.5 h-1.5 rounded-full ${isWorkerAlive ? 'bg-emerald-400 animate-ping' : 'bg-red-500'}`} />
            <span className="text-[9px] uppercase tracking-widest font-bold opacity-70">
              {isWorkerAlive ? (activeJob ? activeJob.jobType.split('_').pop() : 'Ready') : 'Offline'}
            </span>
          </div>

          <div className="flex items-center">
            <button 
              onClick={() => setFontSize(s => Math.max(12, s - 2))} 
              className="p-1.5 sm:p-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-full transition-colors relative group/tooltip"
            >
              <Type size={14} />
            </button>
            <button 
              onClick={() => setFontSize(s => Math.min(36, s + 2))} 
              className="p-1.5 sm:p-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-full transition-colors relative group/tooltip"
            >
              <Type size={18} />
            </button>
          </div>
          
          <button 
            onClick={() => setTheme(theme === "dark" ? "sepia" : theme === "sepia" ? "light" : "dark")}
            className="p-1.5 sm:p-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-full transition-colors"
          >
            <Palette size={18} />
          </button>
          
          <button 
            onClick={() => setIsJobMonitorOpen(!isJobMonitorOpen)}
            className={`p-1.5 sm:p-2 rounded-full transition-all ${isJobMonitorOpen ? 'text-amber-400 bg-amber-400/10' : 'opacity-50'}`}
          >
            <Activity size={18} />
          </button>

          {story?.status === 'complete' && (
            <div className="flex items-center border-l border-white/10 pl-1 ml-1 relative">
              <button 
                onClick={() => setShowVideoOptions(!showVideoOptions)}
                className={`p-1.5 sm:p-2 rounded-full transition-colors ${showVideoOptions ? 'text-amber-400 bg-amber-400/10' : 'text-zinc-400'}`}
              >
                <Video size={18} />
              </button>
              {/* Video Options Menu (Mobile Optimized) */}
              <AnimatePresence>
                {showVideoOptions && (
                  <motion.div 
                    initial={{ opacity: 0, scale: 0.9, y: 10 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.9, y: 10 }}
                    className={`absolute top-full right-0 mt-2 p-4 rounded-2xl border shadow-2xl z-[100] min-w-[220px] ${currentStyle.card} backdrop-blur-xl`}
                  >
                    <div className="space-y-4">
                      <div>
                        <label className="text-[10px] uppercase tracking-widest font-bold opacity-50 mb-2 block text-left">Aspect Ratio</label>
                        <div className="grid grid-cols-2 gap-2">
                          <button 
                            onClick={() => setVideoConfig(c => ({...c, aspectRatio: '16:9'}))}
                            className={`px-2 py-2 rounded-lg text-[10px] font-bold border transition-all ${videoConfig.aspectRatio === '16:9' ? 'bg-amber-400 text-zinc-950 border-amber-400' : 'border-white/10 hover:bg-white/5'}`}
                          >
                            16:9 (TV)
                          </button>
                          <button 
                            onClick={() => setVideoConfig(c => ({...c, aspectRatio: '9:16'}))}
                            className={`px-2 py-2 rounded-lg text-[10px] font-bold border transition-all ${videoConfig.aspectRatio === '9:16' ? 'bg-amber-400 text-zinc-950 border-amber-400' : 'border-white/10 hover:bg-white/5'}`}
                          >
                            9:16 (Phone)
                          </button>
                        </div>
                      </div>

                      <div>
                        <label className="text-[10px] uppercase tracking-widest font-bold opacity-50 mb-2 block text-left">Quality</label>
                        <div className="grid grid-cols-2 gap-2">
                          <button 
                            onClick={() => setVideoConfig(c => ({...c, resolution: '720p'}))}
                            className={`px-2 py-2 rounded-lg text-[10px] font-bold border transition-all ${videoConfig.resolution === '720p' ? 'bg-amber-400 text-zinc-950 border-amber-400' : 'border-white/10 hover:bg-white/5'}`}
                          >
                            720p
                          </button>
                          <button 
                            onClick={() => setVideoConfig(c => ({...c, resolution: '1080p'}))}
                            className={`px-2 py-2 rounded-lg text-[10px] font-bold border transition-all ${videoConfig.resolution === '1080p' ? 'bg-amber-400 text-zinc-950 border-amber-400' : 'border-white/10 hover:bg-white/5'}`}
                          >
                            1080p
                          </button>
                        </div>
                      </div>

                      <button 
                        onClick={handleExportVideo}
                        className="w-full py-2.5 bg-zinc-100 text-zinc-950 rounded-xl font-bold text-xs hover:bg-white transition-colors flex items-center justify-center gap-2"
                      >
                        <Sparkles size={14} />
                        Queue Export
                      </button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>
      </header>

      {/* Task Monitor Sidebar */}
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

      {/* Main Content */}
      <main className="max-w-3xl mx-auto pt-32 pb-48 px-8 min-h-screen relative z-10">
        <div ref={scrollRef} className="space-y-12">
          {currentPart ? (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-1000">
              <h2 className={`text-4xl font-serif font-bold tracking-tight mb-16 text-center italic transition-colors ${currentStyle.title}`}>
                {currentPart.title || `Part ${currentPart.partNumber}`}
              </h2>
              <div 
                className="font-serif leading-relaxed space-y-12"
                style={{ fontSize: `${fontSize}px` }}
              >
                {currentPart.segments?.length > 0 ? (
                  currentPart.segments.map((segment: any, i: number) => {
                    const isActive = i === finalActiveIndex;
                    
                    return (
                      <div 
                        key={i} 
                        ref={(el) => (segmentRefs.current[i] = el)}
                        className={`group flex gap-6 items-start transition-all duration-700 ${
                          isActive ? "opacity-100 scale-[1.02] translate-x-2" : "opacity-40"
                        }`} 
                        style={{ animationDelay: `${i * 100}ms` }}
                      >
                        <div className={`mt-1.5 p-2 rounded-full border transition-colors ${
                          isActive ? currentStyle.iconActive : currentStyle.iconInactive
                        }`}>
                          {segment.type === "narration" ? (
                            <Mic2 size={fontSize * 0.8} />
                          ) : (
                            <User size={fontSize * 0.8} />
                          )}
                        </div>
                        <div className="flex-1 space-y-2">
                          {segment.type === "dialogue" && segment.speakerName && (
                            <p className={`text-[10px] uppercase tracking-[0.2em] font-bold transition-colors ${
                              isActive ? "text-amber-500" : currentStyle.inactiveText
                            }`}>
                              {segment.speakerName}
                            </p>
                          )}
                          <p className={`transition-all duration-500 ${
                            isActive 
                              ? currentStyle.activeText 
                              : segment.type === "dialogue" ? currentStyle.dialogueText : currentStyle.inactiveText + " italic"
                          }`}>
                            {segment.text}
                          </p>
                        </div>
                      </div>
                    );
                  })
                ) : (
                  /* Fallback if segments aren't available yet */
                  currentPart.fullText?.split('\n').map((para: string, i: number) => (
                    para.trim() && (
                      <p key={i} className="transition-all duration-300 opacity-90 hover:opacity-100">
                        {para}
                      </p>
                    )
                  ))
                )}

                {/* Extend Story Section */}
                {currentPartIndex === (story?.parts?.length || 0) - 1 && !activeJob && (
                  <motion.div 
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="py-12 border-t border-black/5 dark:border-white/5 mt-12 text-center space-y-6"
                  >
                    <div className="space-y-2">
                      <h4 className={`text-xl font-serif ${currentStyle.title}`}>The end of this chapter...</h4>
                      <p className={`text-sm ${currentStyle.inactiveText}`}>Should the journey continue, or shall we close the book?</p>
                    </div>
                    
                    <div className="flex justify-center gap-4">
                      <button
                        onClick={() => extendStoryMutation.mutate(3)}
                        disabled={extendStoryMutation.isPending}
                        className={`px-8 py-3 rounded-full font-bold text-sm transition-all flex items-center gap-2 group disabled:opacity-50 ${currentStyle.buttonPrimary}`}
                      >
                        {extendStoryMutation.isPending ? (
                          <Loader2 className="animate-spin" size={18} />
                        ) : (
                          <Plus size={18} />
                        )}
                        Extend by 3 Chapters
                      </button>
                      
                      <button
                        onClick={() => window.location.href = '/'}
                        className={`px-8 py-3 rounded-full font-bold text-sm transition-all ${currentStyle.buttonSecondary}`}
                      >
                        Close Book
                      </button>
                    </div>
                  </motion.div>
                )}
              </div>
            </div>
          ) : concepts && story?.status === "draft" ? (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-1000 max-w-2xl mx-auto">
              <div className="text-center space-y-4 mb-12">
                <Sparkles className="text-amber-400 mx-auto" size={48} />
                <h2 className="text-3xl font-bold tracking-tight">Pick your path</h2>
                <p className="text-zinc-500">The local scribes have woven three distinct possibilities. Which story shall we tell?</p>
              </div>
              
              <div className="grid grid-cols-1 gap-6">
                {concepts.map((concept: any, i: number) => (
                  <button
                    key={i}
                    onClick={() => selectConceptMutation.mutate(concept)}
                    disabled={selectConceptMutation.isPending}
                    className="group relative text-left p-8 rounded-3xl bg-zinc-900/50 border border-zinc-800 hover:border-zinc-500 transition-all hover:scale-[1.02] disabled:opacity-50"
                  >
                    <div className="flex justify-between items-start mb-4">
                      <h3 className="text-xl font-bold text-zinc-100 group-hover:text-white transition-colors">{concept.title}</h3>
                      <div className="flex gap-2">
                        {concept.tone_tags?.map((tag: string) => (
                          <span key={tag} className="text-[10px] uppercase tracking-widest px-2 py-0.5 bg-zinc-800 text-zinc-500 rounded font-bold">{tag}</span>
                        ))}
                      </div>
                    </div>
                    <p className="text-zinc-400 leading-relaxed group-hover:text-zinc-300 transition-colors">{concept.blurb}</p>
                    <div className="mt-6 flex items-center gap-2 text-zinc-500 text-sm font-bold uppercase tracking-widest opacity-0 group-hover:opacity-100 transition-opacity">
                      Select this story <ArrowRight size={16} />
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-24 text-center space-y-10">
              <div className="relative group/progress-circle">
                <div className="w-24 h-24 bg-zinc-900 rounded-full flex flex-col items-center justify-center animate-pulse relative z-10">
                  <Wand2 className="text-zinc-500 mb-1" size={32} />
                  <span className="text-xs font-mono font-bold text-amber-400">
                    {Math.round(progressPercent)}%
                  </span>
                </div>
                {totalJobs > 0 && (
                  <svg className="absolute inset-0 w-24 h-24 -rotate-90">
                    <circle
                      cx="48" cy="48" r="44"
                      stroke="currentColor"
                      strokeWidth="2"
                      fill="transparent"
                      className="text-zinc-800"
                    />
                    <circle
                      cx="48" cy="48" r="44"
                      stroke="currentColor"
                      strokeWidth="2"
                      fill="transparent"
                      strokeDasharray={276}
                      strokeDashoffset={276 - (276 * progressPercent) / 100}
                      className="text-amber-400 transition-all duration-1000"
                    />
                  </svg>
                )}
              </div>

              <div className="space-y-4 max-w-md mx-auto">
                <AnimatePresence mode="wait">
                  <motion.h3 
                    key={failedJob ? "error" : loadingMessage}
                    initial={{ opacity: 0, y: 15 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -15 }}
                    transition={{ 
                      duration: 1.2,
                      ease: "easeInOut" 
                    }}
                    className={`text-2xl font-serif font-medium min-h-[3rem] ${failedJob ? "text-red-400" : "text-zinc-100"}`}
                  >
                    {failedJob ? (
                      `Error: ${failedJob.jobType.replace(/_/g, ' ')} failed`
                    ) : activeJob ? (
                      activeJob.jobType === "build_story_bible" ? "Architecting the Book..." :
                    activeJob.jobType === "generate_part" ? `Writing Chapter ${activeJob.partNumber}...` :
                      activeJob.jobType === "generate_part_audio" ? `Synthesizing Voices...` :
                      activeJob.jobType === "generate_part_images" ? `Visualizing Scenes...` :
                      loadingMessage
                    ) : loadingMessage}
                  </motion.h3>
                </AnimatePresence>
                
                {failedJob && (
                  <p className="text-sm text-red-500/80 bg-red-500/10 px-4 py-2 rounded-xl border border-red-500/20 max-w-sm mx-auto animate-in fade-in slide-in-from-top-2 duration-700">
                    {failedJob.errorText || "Something went wrong in the background. Please try again or check the worker logs."}
                  </p>
                )}
                
                <div className="flex flex-wrap justify-center gap-2">
                  {jobs?.slice(0, 8).map((job: any) => (
                    <div 
                      key={job.id} 
                      className={`px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest border transition-all duration-500 ${
                        job.status === 'done' ? 'bg-zinc-800 text-zinc-500 border-zinc-700' :
                        job.status === 'running' ? 'bg-amber-400/10 text-amber-400 border-amber-400/20 animate-pulse' :
                        'bg-zinc-900 text-zinc-700 border-zinc-800 opacity-50'
                      }`}
                    >
                      {job.jobType.split('_').pop()}
                    </div>
                  ))}
                  {totalJobs > 8 && <div className="text-[10px] text-zinc-600 self-center">+{totalJobs - 8} more</div>}
                </div>
              </div>
              
              {activeJob && (
                <div className="bg-zinc-900/50 border border-white/5 rounded-3xl p-6 w-full max-w-sm mx-auto space-y-4 backdrop-blur-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`w-2 h-2 rounded-full ${isWorkerAlive ? 'bg-emerald-400 animate-ping' : 'bg-red-500'}`} />
                      <p className="text-[10px] uppercase tracking-widest text-zinc-400 font-bold">
                        {isWorkerAlive ? 'Worker Active' : 'Worker Offline'}
                      </p>
                    </div>
                    <span className="text-[10px] font-mono text-zinc-500">{completedJobs}/{totalJobs} Tasks</span>
                  </div>
                  
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-zinc-200 capitalize text-left">
                      {activeJob.jobType.replace(/_/g, ' ')}
                    </p>
                    <div className="h-1 bg-zinc-800 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-amber-400 transition-all duration-1000"
                        style={{ width: `${progressPercent}%` }}
                      />
                    </div>
                  </div>
                  
                  <p className="text-[10px] text-zinc-500 italic text-left leading-relaxed">
                    {activeJob.jobType === 'generate_part_audio' ? "Synthesizing character voices and mixing background music in parallel..." :
                     activeJob.jobType === 'generate_part_images' ? "Searching Unsplash for atmospheric cinematic imagery..." :
                     activeJob.jobType === 'export_video' ? "Generating high-definition slideshow MP4 with synchronized audio..." :
                     activeJob.jobType === 'stitch_full_story' ? "Stitching all chapters into a seamless full-length audiobook..." :
                     "Using local LLM to weave plot points and dialogue..."}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </main>

      {/* Bottom Player Rail */}
      <footer className={`fixed bottom-0 left-0 right-0 p-4 sm:p-6 z-50 transition-all duration-500 ${showUI || isUIPinned ? 'translate-y-0 opacity-100' : 'translate-y-full opacity-0'}`}>
        <div className="max-w-4xl mx-auto bg-zinc-900/90 backdrop-blur-xl border border-white/10 rounded-[2rem] p-3 sm:p-4 shadow-2xl flex flex-col gap-2 sm:gap-4 relative">
          {/* Pin Toggle */}
          <button 
            onClick={togglePin}
            className={`absolute -top-10 sm:-top-12 right-4 sm:right-6 p-2 rounded-full border backdrop-blur-md transition-all ${
              isUIPinned 
                ? 'bg-amber-400 text-zinc-950 border-amber-400' 
                : 'bg-zinc-900/50 text-zinc-400 border-white/10 hover:text-white'
            }`}
          >
            {isUIPinned ? <Pin size={16} /> : <PinOff size={16} />}
          </button>

          <div className="flex items-center gap-3 sm:gap-6">
            <div className="flex items-center gap-1 sm:gap-2">
              <button onClick={handlePrevPart} disabled={currentPartIndex === 0} className="p-2 text-zinc-400 hover:text-white disabled:opacity-30">
                <SkipBack className="w-5 h-5 sm:w-6 sm:h-6" />
              </button>
              <button 
                onClick={() => setIsPlaying(!isPlaying)}
                className="w-12 h-12 sm:w-14 sm:h-14 bg-zinc-100 text-zinc-950 rounded-full flex items-center justify-center hover:scale-105 transition-transform"
              >
                {isPlaying ? <Pause className="w-6 h-6 sm:w-7 sm:h-7" fill="currentColor" /> : <Play className="w-6 h-6 sm:w-7 sm:h-7 ml-1" fill="currentColor" />}
              </button>
              <button onClick={handleNextPart} disabled={!story?.parts || currentPartIndex === story.parts.length - 1} className="p-2 text-zinc-400 hover:text-white disabled:opacity-30">
                <SkipForward className="w-5 h-5 sm:w-6 sm:h-6" />
              </button>
            </div>
            
            <div className="flex-1 space-y-1 sm:space-y-2">
              <div className="flex justify-between text-[9px] sm:text-[10px] uppercase tracking-widest text-zinc-500 font-bold">
                <span>P{currentPart?.partNumber}</span>
                <span>{formatTime(currentTime)} / {formatTime(currentPart?.durationSeconds || 0)}</span>
              </div>
              <div 
                className="h-1.5 sm:h-2 bg-zinc-800 rounded-full overflow-hidden cursor-pointer group/progress relative"
                onClick={handleSeek}
              >
                <div 
                  className="h-full bg-zinc-100 transition-all duration-100 relative z-10"
                  style={{ width: `${(currentTime / (currentPart?.durationSeconds || 1)) * 100}%` }}
                />
              </div>
            </div>

            <div className="flex items-center gap-2 sm:gap-4">
              {/* Mobile Volume Toggle */}
              <button 
                onClick={() => setIsAudioEnabled(!isAudioEnabled)}
                className={`p-2 rounded-full transition-all ${isAudioEnabled ? 'bg-zinc-800 text-zinc-100' : 'bg-red-500/20 text-red-400 border border-red-500/20'}`}
              >
                {isAudioEnabled ? <Volume2 className="w-4.5 h-4.5 sm:w-5 sm:h-5" /> : <VolumeX className="w-4.5 h-4.5 sm:w-5 sm:h-5" />}
              </button>
              
              {/* Desktop Speed Control (Hidden on mobile) */}
              <div className="hidden lg:flex flex-col gap-1 min-w-[100px]">
                <div className="flex items-center justify-between">
                  <span className="text-[9px] font-bold uppercase tracking-widest text-zinc-500">Speed</span>
                  <span className="text-[9px] font-bold text-amber-400">{playbackRate.toFixed(1)}x</span>
                </div>
                <input 
                  type="range" min="0.5" max="2.0" step="0.1"
                  value={playbackRate} 
                  onChange={(e) => setPlaybackRate(parseFloat(e.target.value))}
                  className="w-full h-1 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-amber-400"
                />
              </div>
            </div>
          </div>
        </div>
      </footer>

      {/* Hidden Audio Elements */}
      {currentPart?.mergedAudioPath && (
        <>
          <audio
            ref={audioRef}
            onTimeUpdate={handleTimeUpdate}
            onEnded={handleEnded}
          />
          <audio
            ref={nextAudioRef}
            preload="auto"
          />
        </>
      )}
    </div>
  );
}

function formatTime(seconds: number) {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}
