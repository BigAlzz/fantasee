"""
Batch Generate All Fantasee Stories
====================================
Generates all 4 stories sequentially with real-time progress.
Each: 10 scenes, 3 images/scene, TTS, subtitles.
"""
import subprocess
import sys
import os
import time
from datetime import datetime

os.environ["PYTHONUNBUFFERED"] = "1"

STORIES = [
    {
        "concept": "A dragon rider discovers her emerald dragon is sick with a fever that leaches color from its scales. She must find the forgotten healing shrine in the mountains where ancient power is said to cure any ailment. The journey is dangerous — through corrupted forests, past hostile dragon hunters, and up treacherous mountain paths where the wind itself tries to turn her back.",
        "style": "fantasy painterly",
        "tone": "dramatic",
        "voice": "dramatic_male",
    },
    {
        "concept": "Commander Aldric makes his final stand at the fortress of Ravenhold as an overwhelming army of darkness closes in. With only a handful of loyal soldiers, crumbling walls, and his own tactical genius, he must hold the line long enough for reinforcements to arrive — if they come at all. The siege tests the limits of courage, sacrifice, and what one man will give for his people.",
        "style": "fantasy painterly",
        "tone": "dramatic",
        "voice": "deep_narrator",
    },
    {
        "concept": "A dragon rider watches in horror as a creeping blight tarnishes her dragon's once-majestic wings like spoiled silver. The only hope lies in a sacred shrine high in the mountain peaks, where a cure may sleep in stone and silence. She must guide her fading companion through howling storms, across crumbling bridges, and past creatures that feed on dying magic.",
        "style": "fantasy painterly",
        "tone": "dramatic",
        "voice": "british_male",
    },
    {
        "concept": "Kael, a young dragon rider, watches helplessly as Skyreath's mighty wings falter and fire dims to embers. The cold sickness — a plague spoken of only in whispered legends — has found its ancient mark. Now with Skyreath's labored breaths warming her neck, Kael must trace forgotten paths into storm-shrouded peaks, seeking a shrine whose crumbling stones hold the last remedy against extinction.",
        "style": "fantasy painterly",
        "tone": "dramatic",
        "voice": "dramatic_male",
    },
]

def main():
    print(f"{'='*60}", flush=True)
    print(f"  Fantasee Batch Generation — {datetime.now():%Y-%m-%d %H:%M}", flush=True)
    print(f"  {len(STORIES)} stories × 10 scenes × 3 images each", flush=True)
    print(f"{'='*60}", flush=True)
    
    results = []
    for i, story in enumerate(STORIES):
        num = i + 1
        print(f"\n{'─'*60}", flush=True)
        print(f"  Story {num}/{len(STORIES)} — Voice: {story['voice']}", flush=True)
        print(f"  Concept: {story['concept'][:80]}...", flush=True)
        print(f"{'─'*60}", flush=True)
        
        start = time.time()
        
        cmd = [
            sys.executable, "-u", "generate_story.py",
            "--concept", story["concept"],
            "--scenes", "10",
            "--images-per-scene", "3",
            "--style", story["style"],
            "--tone", story["tone"],
            "--voice", story["voice"],
        ]
        
        # Stream output in real time
        proc = subprocess.Popen(
            cmd,
            cwd="C:/dev/fantasee",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
        )
        
        story_id = "unknown"
        for line in proc.stdout:
            line = line.rstrip()
            print(line, flush=True)
            # Extract story ID from progress messages
            if "id:" in line and story_id == "unknown":
                parts = line.split("id:")
                if len(parts) > 1:
                    story_id = parts[-1].strip().strip('"').strip("'").strip(")")
        
        proc.wait()
        elapsed = time.time() - start
        
        if proc.returncode == 0:
            print(f"\n  ✅ DONE in {elapsed/60:.1f} min — id: {story_id}", flush=True)
            results.append({"status": "ok", "id": story_id, "time": elapsed})
        else:
            print(f"\n  ❌ FAILED in {elapsed/60:.1f} min (exit code {proc.returncode})", flush=True)
            results.append({"status": "error", "error": f"exit code {proc.returncode}"})
    
    print(f"\n{'='*60}", flush=True)
    print(f"  BATCH COMPLETE — {datetime.now():%Y-%m-%d %H:%M}", flush=True)
    print(f"{'='*60}", flush=True)
    for r in results:
        if r["status"] == "ok":
            print(f"  ✅ {r['id']} ({r['time']/60:.1f} min)", flush=True)
        else:
            print(f"  ❌ {r.get('error', 'unknown')}", flush=True)
    
    total_time = sum(r.get("time", 0) for r in results)
    print(f"\n  Total time: {total_time/60:.1f} min", flush=True)

if __name__ == "__main__":
    main()
