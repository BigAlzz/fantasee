"use client";

import { motion, AnimatePresence } from "framer-motion";
import { 
  Activity, CheckCircle2, Clock, History, 
  AlertCircle, ChevronRight, Server, Play, 
  Loader2, X, RotateCcw, Check
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { useState } from "react";

interface Job {
  id: string;
  jobType: string;
  status: string;
  partNumber?: number;
  createdAt: string;
  updatedAt: string;
  error?: string | null;
  resultJson?: string | null;
}

interface JobMonitorProps {
  jobs: Job[];
  isWorkerAlive: boolean;
  onClose?: () => void;
}

export function JobMonitor({ jobs, isWorkerAlive, onClose }: JobMonitorProps) {
  const [isRetrying, setIsRetrying] = useState(false);
  const [retrySuccess, setRetrySuccess] = useState(false);

  const activeJobs = jobs.filter(j => j.status === 'processing' || j.status === 'running');
  const queuedJobs = jobs.filter(j => j.status === 'pending' || j.status === 'queued');
  const completedJobs = jobs.filter(j => j.status === 'done' || j.status === 'failed').slice(0, 10);
  const failedJobsCount = jobs.filter(j => j.status === 'failed').length;
  
  // Check for potential multiple workers based on heartbeat frequency or active jobs
  const hasMultipleWorkersWarning = jobs.some(j => j.status === 'running' && j.error?.includes('Another worker'));

  const handleRetryAll = async () => {
    setIsRetrying(true);
    try {
      const res = await fetch('/api/jobs/retry-all', { method: 'POST' });
      if (res.ok) {
        setRetrySuccess(true);
        setTimeout(() => setRetrySuccess(false), 3000);
      }
    } catch (error) {
      console.error("Retry failed:", error);
    } finally {
      setIsRetrying(false);
    }
  };

  const getJobNode = (job: Job) => {
    try {
      if (job.resultJson) {
        const result = JSON.parse(job.resultJson);
        if (result.node) {
          return result.node.replace('http://', '').replace('https://', '').split(':')[0];
        }
      }
    } catch (e) {}
    return null;
  };

  const getJobLabel = (type: string) => {
    switch(type) {
      case 'generate_part': return 'Writing Story';
      case 'generate_part_audio': return 'Synthesizing Voices';
      case 'generate_part_images': return 'Visualizing Scenes';
      case 'generate_concepts': return 'Architecting Story';
      case 'build_story_bible': return 'Structuring World';
      case 'export_video': return 'Exporting Video';
      case 'stitch_full_story': return 'Assembling Audiobook';
      default: return type.replace(/_/g, ' ');
    }
  };

  const StatusIcon = ({ status }: { status: string }) => {
    switch(status) {
      case 'running':
      case 'processing': return <Loader2 className="animate-spin text-amber-400" size={16} />;
      case 'pending': 
      case 'queued': return <Clock className="text-zinc-500" size={16} />;
      case 'done': return <CheckCircle2 className="text-emerald-400" size={16} />;
      case 'failed': return <AlertCircle className="text-red-400" size={16} />;
      default: return null;
    }
  };

  const safeFormatDistance = (dateStr: string) => {
    try {
      if (!dateStr) return "recently";
      
      // Handle SQLite format if it's not a standard ISO string
      // SQLite: YYYY-MM-DD HH:MM:SS
      // Standard ISO: YYYY-MM-DDTHH:MM:SS.SSSZ
      let normalizedDateStr = dateStr;
      if (dateStr.includes(' ') && !dateStr.includes('T')) {
        normalizedDateStr = dateStr.replace(' ', 'T') + 'Z'; // Assume UTC
      }

      const date = new Date(normalizedDateStr);
      if (isNaN(date.getTime())) return "recently";
      
      const distance = formatDistanceToNow(date, { addSuffix: true });
      // If it says "in the future" (due to clock skew), just say "just now"
      if (distance.includes('in about') || distance.includes('in ')) return "just now";
      
      return distance;
    } catch (e) {
      return "recently";
    }
  };

  return (
    <div className="flex flex-col h-full bg-zinc-950 border-l border-white/5 w-80 md:w-96 shadow-2xl">
      <header className="p-6 border-b border-white/5 flex items-center justify-between bg-zinc-900/50">
        <div className="flex items-center gap-3">
          <Activity size={20} className="text-amber-400" />
          <h3 className="font-bold text-sm tracking-tight text-white">Task Monitor</h3>
        </div>
        <button 
          onClick={onClose}
          className="p-2 hover:bg-white/5 rounded-full transition-colors text-zinc-400"
        >
          <X size={20} />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto p-6 space-y-8 custom-scrollbar">
        {/* Worker Status */}
        <section className="space-y-3">
          <div className="flex items-center justify-between text-[10px] uppercase tracking-widest font-bold text-zinc-500">
            <span>System Status</span>
            <span className={isWorkerAlive ? "text-emerald-400" : "text-red-400"}>
              {isWorkerAlive ? "Online" : "Offline"}
            </span>
          </div>
          <div className="p-4 bg-zinc-900 rounded-xl border border-white/5 flex items-center gap-4">
            <div className={`p-2 rounded-lg ${isWorkerAlive ? 'bg-emerald-400/10 text-emerald-400' : 'bg-red-400/10 text-red-400'}`}>
              <Server size={20} />
            </div>
            <div>
              <p className="text-xs font-bold text-zinc-100">Local Compute Node</p>
              <p className="text-[10px] text-zinc-500">
                {isWorkerAlive ? "Ready for generation" : "Check worker/main.py logs"}
              </p>
            </div>
          </div>
          {hasMultipleWorkersWarning && (
            <div className="p-3 bg-red-400/10 rounded-lg border border-red-400/20 text-[10px] text-red-400 font-medium animate-pulse flex items-center gap-2">
              <AlertCircle size={14} />
              Multiple worker instances detected!
            </div>
          )}
        </section>

        {/* Active & Queued Tasks */}
        <section className="space-y-4">
          <div className="flex items-center justify-between text-[10px] uppercase tracking-widest font-bold text-zinc-500">
            <span>Active Queue ({activeJobs.length + queuedJobs.length})</span>
            {failedJobsCount > 0 && (
              <button
                onClick={handleRetryAll}
                disabled={isRetrying}
                className={`flex items-center gap-1.5 px-2 py-1 rounded-md transition-all border ${
                  retrySuccess 
                    ? 'bg-emerald-400/10 border-emerald-400/20 text-emerald-400' 
                    : 'bg-amber-400/10 border-amber-400/20 text-amber-400 hover:bg-amber-400/20'
                } disabled:opacity-50`}
              >
                {isRetrying ? (
                  <Loader2 size={10} className="animate-spin" />
                ) : retrySuccess ? (
                  <Check size={10} />
                ) : (
                  <RotateCcw size={10} />
                )}
                <span className="text-[9px] font-bold uppercase tracking-wider">
                  {retrySuccess ? 'Queued' : `Retry ${failedJobsCount} Failed`}
                </span>
              </button>
            )}
          </div>
          
          {(activeJobs.length + queuedJobs.length) === 0 ? (
            <div className="py-8 text-center border border-dashed border-white/5 rounded-xl">
              <p className="text-[10px] text-zinc-600 uppercase tracking-widest">No active tasks</p>
            </div>
          ) : (
            <div className="space-y-2">
              {[...activeJobs, ...queuedJobs].map((job) => (
                <div key={job.id} className="p-3 bg-zinc-900/50 rounded-lg border border-white/5 flex items-center justify-between group">
                  <div className="flex items-center gap-3">
                    <StatusIcon status={job.status} />
                    <div>
                      <p className="text-xs font-medium text-zinc-200">{getJobLabel(job.jobType)}</p>
                      <p className="text-[10px] text-zinc-500">Part {job.partNumber || '-'}</p>
                    </div>
                  </div>
                  <span className="text-[9px] text-zinc-600 opacity-0 group-hover:opacity-100 transition-opacity">
                    {safeFormatDistance(job.createdAt)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* History */}
        <section className="space-y-4">
          <div className="flex items-center justify-between text-[10px] uppercase tracking-widest font-bold text-zinc-500">
            <span>Execution History</span>
            <History size={14} />
          </div>
          
          <div className="space-y-2">
            {completedJobs.map((job) => (
              <div key={job.id} className="p-3 bg-zinc-950 rounded-lg border border-white/5 flex items-center justify-between group hover:bg-zinc-900 transition-colors">
                <div className="flex items-center gap-3">
                  <StatusIcon status={job.status} />
                    <div>
                      <p className={`text-xs ${job.status === 'failed' ? 'text-red-400' : 'text-zinc-400'}`}>
                        {getJobLabel(job.jobType)}
                      </p>
                      <div className="flex items-center gap-2">
                        <p className="text-[10px] text-zinc-600">
                          {job.status === 'done' ? 'Completed' : 'Failed'} • Part {job.partNumber || '-'}
                        </p>
                        {getJobNode(job) && (
                          <span className="text-[8px] px-1 py-0 bg-blue-500/10 text-blue-400 rounded border border-blue-500/20">
                            {getJobNode(job)}
                          </span>
                        )}
                      </div>
                    </div>
                </div>
                <span className="text-[9px] text-zinc-700">
                  {safeFormatDistance(job.updatedAt)}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <footer className="p-6 border-t border-white/5 bg-zinc-900/30">
        <div className="p-4 rounded-xl bg-amber-400/5 border border-amber-400/10">
          <div className="flex items-center gap-2 mb-1">
            <AlertCircle size={14} className="text-amber-400" />
            <p className="text-[10px] font-bold text-amber-400 uppercase tracking-widest">Worker Performance</p>
          </div>
          <p className="text-[10px] text-zinc-500 leading-relaxed">
            Generation speed depends on your local GPU/CPU. Keep the worker terminal open for real-time logs.
          </p>
        </div>
      </footer>
    </div>
  );
}
