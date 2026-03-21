"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { 
  Settings as SettingsIcon, 
  Server, 
  Bot, 
  Image as ImageIcon, 
  Key, 
  Globe, 
  Save, 
  ArrowLeft,
  Loader2,
  CheckCircle2,
  RefreshCw
} from "lucide-react";
import Link from "next/link";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [saveSuccess, setSaveSuccess] = useState(false);

  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: async () => {
      const res = await fetch("/api/settings");
      return res.json();
    },
  });

  const { data: modelsData, isLoading: modelsLoading, error: modelsError, refetch: refetchModels } = useQuery({
    queryKey: ["models"],
    queryFn: async () => {
      const res = await fetch("/api/models");
      if (!res.ok) throw new Error("Could not fetch models");
      return res.json();
    },
    enabled: !!settings?.lmStudioUrl,
    retry: false,
  });

  const { data: voices } = useQuery({
    queryKey: ["voices"],
    queryFn: async () => {
      const res = await fetch("/api/voices");
      return res.json();
    },
  });

  const updateSettingsMutation = useMutation({
    mutationFn: async (newSettings: any) => {
      const res = await fetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newSettings),
      });
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    },
  });

  const [localSettings, setLocalSettings] = useState<any>(null);

  useEffect(() => {
    if (settings) {
      setLocalSettings(settings);
    }
  }, [settings]);

  const handleSave = () => {
    updateSettingsMutation.mutate(localSettings);
  };

  if (settingsLoading || !localSettings) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
      </div>
    );
  }

  return (
    <main className="container mx-auto px-4 py-8 max-w-4xl">
      <header className="flex justify-between items-center mb-12">
        <div className="flex items-center gap-4">
          <Link href="/" className="p-2 hover:bg-zinc-900 rounded-full transition-colors">
            <ArrowLeft size={24} />
          </Link>
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-zinc-50 flex items-center gap-3">
              <SettingsIcon size={28} />
              Studio Settings
            </h1>
            <p className="text-zinc-400 mt-1">Configure your local AI models and API integrations</p>
          </div>
        </div>
        <button 
          onClick={handleSave}
          disabled={updateSettingsMutation.isPending}
          className="flex items-center gap-2 bg-zinc-100 text-zinc-950 px-6 py-2.5 rounded-full font-bold hover:bg-white transition-all shadow-lg shadow-white/5 disabled:opacity-50"
        >
          {updateSettingsMutation.isPending ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save size={20} />}
          {saveSuccess ? "Saved!" : "Save Changes"}
        </button>
      </header>

      <div className="grid grid-cols-1 gap-8">
        {/* LM Studio Configuration */}
        <section className="bg-zinc-900/40 border border-zinc-800 rounded-3xl p-8 backdrop-blur-sm">
          <h2 className="text-xl font-bold mb-6 flex items-center gap-2 text-zinc-200">
            <Bot className="text-blue-400" size={24} />
            LM Studio (LLM)
          </h2>
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-xs font-bold text-zinc-500 uppercase tracking-widest mb-2">Server URLs (Comma-separated)</label>
                <input 
                  type="text"
                  value={localSettings.lmStudioUrl || ""}
                  onChange={(e) => setLocalSettings({...localSettings, lmStudioUrl: e.target.value})}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
                  placeholder="http://172.23.48.1:3006/v1, http://localhost:3000/v1"
                />
                <p className="mt-2 text-[10px] text-zinc-500 italic">Add multiple URLs to distribute generation load across instances.</p>
              </div>
              <div>
                <label className="block text-xs font-bold text-zinc-500 uppercase tracking-widest mb-2">API Key (Optional)</label>
                <input 
                  type="password"
                  value={localSettings.lmStudioApiKey || ""}
                  onChange={(e) => setLocalSettings({...localSettings, lmStudioApiKey: e.target.value})}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
                  placeholder="Enter key if required"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-bold text-zinc-500 uppercase tracking-widest mb-2">Model IDs (Comma-separated)</label>
              <input 
                type="text"
                value={localSettings.lmStudioModelId || ""}
                onChange={(e) => setLocalSettings({...localSettings, lmStudioModelId: e.target.value})}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
                placeholder="hermes-2-pro-mistral-7b, llama-3-8b"
              />
              <p className="mt-2 text-[10px] text-zinc-500 italic">Optional: List multiple models to round-robin alongside URLs.</p>
            </div>
          </div>
        </section>

        {/* Kokoro Configuration */}
        <section className="bg-zinc-900/40 border border-zinc-800 rounded-3xl p-8 backdrop-blur-sm">
          <h2 className="text-xl font-bold mb-6 flex items-center gap-2 text-zinc-200">
            <Server className="text-green-400" size={24} />
            Kokoro TTS
          </h2>
          <div className="space-y-6">
            <div>
              <label className="block text-xs font-bold text-zinc-500 uppercase tracking-widest mb-2">Kokoro URLs (Comma-separated)</label>
              <input 
                type="text"
                value={localSettings.kokoroUrl || ""}
                onChange={(e) => setLocalSettings({...localSettings, kokoroUrl: e.target.value})}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
                placeholder="http://localhost:7860/, http://media-node:7860/"
              />
              <p className="mt-2 text-[10px] text-zinc-500 italic">Add multiple URLs to distribute audio synthesis load.</p>
            </div>
            <div>
              <label className="block text-xs font-bold text-zinc-500 uppercase tracking-widest mb-2">Default Narrator Voice</label>
              <select 
                value={localSettings.kokoroVoiceId || "af_heart"}
                onChange={(e) => setLocalSettings({...localSettings, kokoroVoiceId: e.target.value})}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
              >
                <option value="af_heart">af_heart (Default)</option>
                <option value="af_sky">af_sky</option>
                <option value="af_bella">af_bella</option>
                <option value="af_nicole">af_nicole</option>
                <option value="am_adam">am_adam</option>
                <option value="am_michael">am_michael</option>
                <option value="bf_alice">bf_alice</option>
                <option value="bf_emma">bf_emma</option>
                <option value="bm_george">bm_george</option>
                <option value="bm_lewis">bm_lewis</option>
              </select>
              <p className="mt-2 text-[10px] text-zinc-500 italic">Select the default voice used for narration segments.</p>
            </div>
          </div>
        </section>

        {/* Image Generation Configuration */}
        <section className="bg-zinc-900/40 border border-zinc-800 rounded-3xl p-8 backdrop-blur-sm">
          <h2 className="text-xl font-bold mb-6 flex items-center gap-2 text-zinc-200">
            <ImageIcon className="text-purple-400" size={24} />
            Image Generation & Assets
          </h2>
          <div className="space-y-6">
            <div>
              <label className="block text-xs font-bold text-zinc-500 uppercase tracking-widest mb-2">Provider</label>
              <select 
                value={localSettings.imageGenProvider}
                onChange={(e) => setLocalSettings({...localSettings, imageGenProvider: e.target.value})}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
              >
                <option value="off">Off (Disabled)</option>
                <option value="openai">OpenAI (DALL-E)</option>
                <option value="stable-diffusion">Stable Diffusion (Local)</option>
                <option value="unsplash">Unsplash (Clipart/Stock)</option>
              </select>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-xs font-bold text-zinc-500 uppercase tracking-widest mb-2">API Key / Access Key</label>
                <div className="relative">
                  <Key className="absolute left-4 top-1/2 -translate-y-1/2 text-zinc-600" size={18} />
                  <input 
                    type="password"
                    value={localSettings.imageGenApiKey || ""}
                    onChange={(e) => setLocalSettings({...localSettings, imageGenApiKey: e.target.value})}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-xl pl-12 pr-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
                    placeholder="Enter API key"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-bold text-zinc-500 uppercase tracking-widest mb-2">Unsplash Access Key</label>
                <div className="relative">
                  <Globe className="absolute left-4 top-1/2 -translate-y-1/2 text-zinc-600" size={18} />
                  <input 
                    type="password"
                    value={localSettings.unsplashAccessKey || ""}
                    onChange={(e) => setLocalSettings({...localSettings, unsplashAccessKey: e.target.value})}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-xl pl-12 pr-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
                    placeholder="Enter Access key"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-bold text-zinc-500 uppercase tracking-widest mb-2">Unsplash Secret Key</label>
                <div className="relative">
                  <Key className="absolute left-4 top-1/2 -translate-y-1/2 text-zinc-600" size={18} />
                  <input 
                    type="password"
                    value={localSettings.unsplashSecretKey || ""}
                    onChange={(e) => setLocalSettings({...localSettings, unsplashSecretKey: e.target.value})}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-xl pl-12 pr-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
                    placeholder="Enter Secret key"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-bold text-zinc-500 uppercase tracking-widest mb-2">Unsplash App ID</label>
                <input 
                  type="text"
                  value={localSettings.unsplashAppId || ""}
                  onChange={(e) => setLocalSettings({...localSettings, unsplashAppId: e.target.value})}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
                  placeholder="Enter App ID"
                />
              </div>
            </div>
          </div>
        </section>
      </div>

      {saveSuccess && (
        <div className="fixed bottom-8 right-8 animate-in fade-in slide-in-from-bottom-4">
          <div className="bg-green-500 text-white px-6 py-3 rounded-2xl shadow-xl flex items-center gap-3 font-bold">
            <CheckCircle2 size={24} />
            Settings saved successfully!
          </div>
        </div>
      )}
    </main>
  );
}
