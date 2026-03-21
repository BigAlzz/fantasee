"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowRight, Sparkles, Wand2, X } from "lucide-react";

interface StoryCreationFlowProps {
  onCancel: () => void;
}

export default function StoryCreationFlow({ onCancel }: StoryCreationFlowProps) {
  const [step, setStep] = useState(1);
  const [formData, setFormData] = useState({
    genre: "",
    tonePack: "Grand Epic",
    plannedParts: 3,
    title: "",
    premise: "",
    imageMode: "cover_only",
    seriesType: "standalone",
  });

  const { data: genres } = useQuery({
    queryKey: ["genres"],
    queryFn: async () => {
      const res = await fetch("/api/genres");
      return res.json();
    },
  });

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: async () => {
      const res = await fetch("/api/settings");
      return res.json();
    },
  });

  const createStoryMutation = useMutation({
    mutationFn: async (data: any) => {
      // Include the selected model from settings in the creation request
      const storyData = {
        ...data,
        lmStudioModelId: settings?.lmStudioModelId,
      };
      const res = await fetch("/api/stories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(storyData),
      });
      return res.json();
    },
    onSuccess: (data) => {
      // Handle success - maybe redirect to the story page
      window.location.href = `/stories/${data.id}`;
    },
  });

  const nextStep = () => setStep((s) => s + 1);
  const prevStep = () => setStep((s) => s - 1);

  const handleSubmit = () => {
    createStoryMutation.mutate(formData);
  };

  return (
    <div className="bg-zinc-900/50 border border-zinc-800 rounded-3xl p-8 max-w-2xl mx-auto backdrop-blur-sm shadow-2xl">
      <div className="flex justify-between items-center mb-8">
        <h2 className="text-2xl font-bold text-zinc-100 flex items-center gap-2">
          <Sparkles className="text-amber-400" size={24} />
          Create New Adventure
        </h2>
        <button onClick={onCancel} className="text-zinc-500 hover:text-zinc-300">
          <X size={24} />
        </button>
      </div>

      <AnimatePresence mode="wait">
        {step === 1 && (
          <motion.div
            key="step1"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            className="space-y-6"
          >
            <div>
              <label className="block text-sm font-medium text-zinc-400 mb-4 uppercase tracking-widest">Select Genre</label>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {genres?.core.slice(0, 12).map((genre: string) => (
                  <button
                    key={genre}
                    onClick={() => setFormData({ ...formData, genre })}
                    className={`px-4 py-3 rounded-xl border text-sm transition-all ${
                      formData.genre === genre
                        ? "bg-zinc-100 border-zinc-100 text-zinc-950 shadow-lg shadow-zinc-100/10"
                        : "bg-zinc-900 border-zinc-800 text-zinc-400 hover:border-zinc-700"
                    }`}
                  >
                    {genre}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex justify-end pt-6">
              <button
                disabled={!formData.genre}
                onClick={nextStep}
                className="flex items-center gap-2 bg-zinc-100 text-zinc-950 px-6 py-2 rounded-full font-medium disabled:opacity-50 transition-all hover:bg-white"
              >
                Next Step <ArrowRight size={18} />
              </button>
            </div>
          </motion.div>
        )}

        {step === 2 && (
          <motion.div
            key="step2"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            className="space-y-6"
          >
            <div className="grid grid-cols-1 gap-6">
              <div>
                <label className="block text-sm font-medium text-zinc-400 mb-2 uppercase tracking-widest">Tone & Style</label>
                <select
                  value={formData.tonePack}
                  onChange={(e) => setFormData({ ...formData, tonePack: e.target.value })}
                  className="w-full bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
                >
                  <option>Grand Epic</option>
                  <option>Cozy Campfire</option>
                  <option>Dark Theatre</option>
                  <option>Dreamlike</option>
                  <option>Storybook</option>
                  <option>Academic</option>
                  <option>Journalistic</option>
                  <option>Sensual</option>
                  <option>Hardcore</option>
                  <option>Professional</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-zinc-400 mb-2 uppercase tracking-widest">Narrative Structure</label>
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { id: "standalone", label: "Standalone", icon: BookOpen },
                    { id: "trilogy", label: "Trilogy", icon: Library },
                    { id: "saga", label: "Continuous Saga", icon: Sparkles }
                  ].map((type) => (
                    <button
                      key={type.id}
                      onClick={() => setFormData({ 
                        ...formData, 
                        seriesType: type.id as any,
                        plannedParts: type.id === "saga" ? 999 : type.id === "trilogy" ? 12 : formData.plannedParts
                      })}
                      className={`flex flex-col items-center gap-2 p-3 rounded-xl border text-xs font-bold transition-all ${
                        formData.seriesType === type.id
                          ? "bg-zinc-100 border-zinc-100 text-zinc-950"
                          : "bg-zinc-900 border-zinc-800 text-zinc-400 hover:border-zinc-700"
                      }`}
                    >
                      <type.icon size={18} />
                      {type.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-zinc-400 mb-2 uppercase tracking-widest">
                  {formData.seriesType === "standalone" ? "Story Length (Parts)" : "Book 1 Length (Parts)"}
                </label>
                <select
                  value={formData.plannedParts}
                  onChange={(e) => setFormData({ ...formData, plannedParts: parseInt(e.target.value) })}
                  className="w-full bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
                >
                  <option value={3}>Short (3 Parts)</option>
                  <option value={6}>Standard (6 Parts)</option>
                  <option value={12}>Long (12 Parts)</option>
                  <option value={24}>Epic (24 Parts)</option>
                  {formData.seriesType === "saga" && <option value={999}>Unending (Continuous Branching)</option>}
                </select>
                {formData.plannedParts === 999 && (
                  <p className="mt-2 text-[10px] text-amber-400 italic">
                    Unending mode enables branching subplots and deep character arcs that evolve indefinitely.
                  </p>
                )}
              </div>
            </div>
            <div className="flex justify-between pt-6">
              <button
                onClick={prevStep}
                className="flex items-center gap-2 text-zinc-400 px-4 py-2 hover:text-zinc-200 transition-all"
              >
                <ArrowLeft size={18} /> Back
              </button>
              <button
                onClick={nextStep}
                className="flex items-center gap-2 bg-zinc-100 text-zinc-950 px-6 py-2 rounded-full font-medium hover:bg-white transition-all"
              >
                Next Step <ArrowRight size={18} />
              </button>
            </div>
          </motion.div>
        )}

        {step === 3 && (
          <motion.div
            key="step3"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            className="space-y-6"
          >
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-zinc-400 mb-2 uppercase tracking-widest">Title (Optional)</label>
                <input
                  type="text"
                  placeholder="Leave blank for AI to suggest titles"
                  value={formData.title}
                  onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                  className="w-full bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-zinc-400 mb-2 uppercase tracking-widest">Story Premise</label>
                <textarea
                  rows={4}
                  placeholder="What is this story about? Enter a few keywords or a full description..."
                  value={formData.premise}
                  onChange={(e) => setFormData({ ...formData, premise: e.target.value })}
                  className="w-full bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors resize-none"
                />
              </div>
            </div>
            <div className="flex justify-between pt-6">
              <button
                onClick={prevStep}
                className="flex items-center gap-2 text-zinc-400 px-4 py-2 hover:text-zinc-200 transition-all"
              >
                <ArrowLeft size={18} /> Back
              </button>
              <button
                disabled={createStoryMutation.isPending}
                onClick={handleSubmit}
                className="flex items-center gap-2 bg-zinc-100 text-zinc-950 px-8 py-3 rounded-full font-bold hover:bg-white transition-all shadow-xl shadow-white/10"
              >
                {createStoryMutation.isPending ? (
                  <div className="w-5 h-5 border-2 border-zinc-900 border-t-transparent rounded-full animate-spin" />
                ) : (
                  <>
                    {formData.title ? "Create Story" : "Generate Concepts"}
                    <Wand2 size={20} />
                  </>
                )}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
