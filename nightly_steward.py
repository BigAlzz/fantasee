#!/usr/bin/env python3
"""Nightly steward — regenerate ALL stories through the Fantasee API.
Non-destructive, uses API only. Keeps the pipeline busy overnight.
"""

import json, os, sys, time, requests
from pathlib import Path

BASE = "http://127.0.0.1:8765"
STORIES_ROOT = Path("/c/dev/fantasee/stories")

# ── Fresh story concepts from The Return world bible ───────────────

FRESH_STORIES = [
    {
        "story_concept": "The First Walk. Selene, a 300-year-old Neanderthal elder, must sing open a Gate Stone to save 50,000 refugees from a dying world. The song will kill her. Her grandson Kael carries her litter. The Gate Stone is cold. The Weave is thin. Selene opens her mouth and begins to sing.",
        "style": "dark gothic",
        "num_scenes": 10,
        "tone": "epic",
        "characters": "Selene — 300 years old, white-haired, silver eyes, carried on a wooden litter. Kael — 29, Selene's grandson, lean, pale silver eyes, healer's hands.",
    },
    {
        "story_concept": "The Turning. Korrath Stone-Hand leads a Neanderthal war party into a frozen forest at dawn. A Concord patrol in powered armor blocks their path. Korrath undergoes The Turning — bones shift, skin grays, eyes go white, he grows to eight feet of living stone. The Concord soldiers fire plasma rifles. The bolts hit his stone-skin and glow white-hot. He shatters their weapons. He stands over them and says: Go home. Tell them the earth remembers.",
        "style": "cinematic realism",
        "num_scenes": 10,
        "tone": "dark",
        "characters": "Korrath Stone-Hand — 47, broadest Neanderthal, gray-umber skin, missing left hand replaced by a jagged crystal stump. Varn — his second-in-command, scarred veteran. Sergeant Okafor — Concord squad leader, Mk.7 Ironhide armor.",
    },
    {
        "story_concept": "The Bone Singer. Yenna, a 19-year-old Deep-Man, walks across a Concord internment camp at midnight. She hears the voices of 300 dead buried beneath the concrete. A child asks for its mother. A warrior sings a battle hymn. A woman weeps. Yenna kneels and places her pale hand flat on the ground. She is the Whisper — the voice of the Deep-Men council. She is 19 and has not slept without nightmares since she was seven.",
        "style": "dark gothic",
        "num_scenes": 10,
        "tone": "dark",
        "characters": "Yenna — 19, Deep-Man, pale translucent skin, large solid-black eyes, wraps herself in dark leather, permanently burnt from surface exposure.",
    },
    {
        "story_concept": "The Healer's Gambit. Kael, a Weave-Born healer, walks through the aftermath of the Battle of Wolf Creek. 57 Neanderthals lie dead. 23 humans lie wounded. Kael is unarmed. He begins with the humans. He kneels beside a soldier with a shattered leg, places his hand on the wound, and the flesh knits back together. He heals every human before touching a single Neanderthal corpse. Healing each human costs him a month of his own life. He heals 13. He does not regret it.",
        "style": "fantasy painterly",
        "num_scenes": 10,
        "tone": "emotional",
        "characters": "Kael Weave-Born — 29, lean, pale silver eyes, simple robes of woven fungal fiber, healer's hands. Captain Marcus Cole — 44, Concord commander, powered armor splattered with mud and blood.",
    },
    {
        "story_concept": "The Collector's Fire. In a cave beneath the Threshold shantytown, a nameless Neanderthal sits surrounded by disassembled human technology. He has built a battery that stores Weave energy. It hums. It glows purple. If he releases it, it could end the energy crisis or start a war. He turns it over in scarred hands, listening to humans and Neanderthals trading above. He has not spoken to anyone in six months.",
        "style": "cinematic realism",
        "num_scenes": 10,
        "tone": "suspenseful",
        "characters": "The Collector — age unknown, gaunt, wild hair, fingers stained with grease. Broker — human middleman, expensive coat, no loyalty except to money. Dace — former Stone-Born warrior, runs a salvage operation.",
    },
    {
        "story_concept": "The Soldier's HUD. Private Elena Vasquez, 19, Concord infantrywoman, tracks Neanderthals through old-growth forest. Her HUD labels them as catalog numbers KN-0782 through KN-0787. At dawn she finds them gathered around an ancient cedar. An old woman has her hand on the bark. She is weeping. Elena's HUD says THREAT ASSESSMENT: LOW. She does not fire. The old woman looks at her. Elena's HUD glitches. She sees a face instead of a number. The sound of someone coming home after a very long time.",
        "style": "cinematic realism",
        "num_scenes": 10,
        "tone": "dramatic",
        "characters": "Private Elena Vasquez — 19, Concord infantrywoman, Mk.7 Ironhide armor. Sergeant Okonkwo — 35, squad leader. The Old Woman — Stone-Born elder, silver eyes, ceremonial scars, barefoot in the snow.",
    },
    {
        "story_concept": "Ash. In the Threshold shantytown, a three-year-old hybrid child named Ash sits in a tent and cries. Ash has solid black eyes, can see in the dark, and senses emotions like weather. Outside, a Concord retrieval team has come to claim the child for study. Neanderthal warriors and human volunteers form a ring around the tent. Ash's mother holds the child and sings a Deep-Man lullaby. The child feels the fear of a hundred people outside and cannot make it stop.",
        "style": "dark gothic",
        "num_scenes": 10,
        "tone": "emotional",
        "characters": "Ash — 3 years old, hybrid child, solid black eyes, senses emotions. Sarah — Ash's mother, 28, human, exhausted, fierce. Director Elena Vasquez — 52, head of the Concord, authorized the retrieval.",
    },
    {
        "story_concept": "The Last Crossing. Nevarrah is dying. One million Neanderthals stand at the Gate Stones. The Stones can handle a hundred at a time. Nevarrah has weeks. Korrath Stone-Hand volunteers to power the Stones — channeling a rift burns years off the user's life. He kneels, presses his crystal hand to the surface. The people walk through. His hair whitens. His skin thins. On the third day Varn takes his place. Korrath collapses. He is 47. He looks 90. He will be the last.",
        "style": "dark gothic",
        "num_scenes": 10,
        "tone": "epic",
        "characters": "Korrath Stone-Hand — 47 but aging rapidly, crystal stump glowing white-hot. Varn — scarred veteran, white beard. Thera — Korrath's daughter, 22, geopath, in the crowd fleeing through the gate.",
    },
    {
        "story_concept": "The Warden's Truth. In a cave beneath the Threshold, the oldest living Neanderthal sits across from Kael Weave-Born. The Warden has not spoken in 50 years. He carries a truth that could shatter both species. Kael asks why the Neanderthals really left Earth. The Warden says: We did not flee the cold. We fled the apes. They walked through our sacred places and felt nothing. The earth needed us. We left it alone for 40,000 years with creatures who could not hear it scream.",
        "style": "dark gothic",
        "num_scenes": 10,
        "tone": "dramatic",
        "characters": "The Warden — age unknown, sitting in absolute darkness, wrapped in ancient cloth. Kael Weave-Born — 29, healer, silver eyes. Selene — 300 years old, listening from the shadows.",
    },
    {
        "story_concept": "The Land Wakes. Three months after Neanderthal refugees arrive in the Pacific Northwest, the land begins to change. Grass grows three feet tall in December. Trees glow at night. Wolves approach without fear. In the center, a Gate Stone buried for 40,000 years hums with energy. Dr. Aris Thorne places his hand on the stone. He feels nothing. He is human. The stone does not recognize him. But the wolves do. They wait.",
        "style": "fantasy painterly",
        "num_scenes": 10,
        "tone": "mysterious",
        "characters": "Dr. Aris Thorne — 39, Concord lead researcher, brilliant, morally broken by curiosity. Private Torres — 22, security escort, was healed by a Weave-Born and has not fired his weapon since.",
    },
]

# ── Helper functions ──────────────────────────────────────────────

def api_get(path):
    r = requests.get(f"{BASE}{path}", timeout=15)
    return r.json() if r.status_code == 200 else None

def api_post(path, data=None):
    r = requests.post(f"{BASE}{path}", json=data or {}, timeout=15)
    return r.json() if r.status_code == 200 else {"error": r.text}

def get_tasks():
    d = api_get("/api/generate/tasks")
    if not d:
        return []
    return d if isinstance(d, list) else d.get("tasks", [])

def count_status(tasks):
    from collections import Counter
    return Counter(t.get("status", "?") for t in tasks)

def log(msg):
    t = time.strftime("%H:%M:%S")
    print(f"[{t}] {msg}", flush=True)


# ── Main loop ─────────────────────────────────────────────────────

def main():
    log("🌙 Nightly Steward starting up")
    log(f"   ComfyUI: {requests.get('http://127.0.0.1:8188/system_stats', timeout=5).status_code}")
    log(f"   Server:  {requests.get(f'{BASE}/api/stories', timeout=5).status_code}")

    round_num = 0
    max_rounds = 120  # ~10 hours at 5-min intervals
    stories_queued = []

    while round_num < max_rounds:
        round_num += 1
        tasks = get_tasks()
        counts = count_status(tasks)
        running = sum(1 for t in tasks if t.get("status") in ("running", "queued"))

        log(f"Round {round_num}/{max_rounds} — "
            f"running:{counts.get('running',0)} queued:{counts.get('queued',0)} "
            f"done:{counts.get('done',0)} error:{counts.get('error',0)} "
            f"total:{len(tasks)}")

        # ── Phase 1: Queue fresh stories if we haven't yet ───────
        if not stories_queued:
            log(f"📦 Queueing {len(FRESH_STORIES)} fresh stories from The Return bible...")
            # Queue in batches of 5 (API limit)
            for i in range(0, len(FRESH_STORIES), 5):
                batch = FRESH_STORIES[i:i+5]
                result = api_post("/api/generate/queue", {"items": batch})
                if "queue_id" in result:
                    log(f"   Batch {i//5+1} queued — {result['queue_id']}")
                    stories_queued.append(result["queue_id"])
                elif "task_id" in result:
                    log(f"   Batch {i//5+1} queued — {result['task_id']}")
                    stories_queued.append(result["task_id"])
                else:
                    log(f"   Batch {i//5+1} result: {result}")
                    if "already" in str(result):
                        log("   (maintenance already running — will queue later)")
                        stories_queued.append("already-running")
                        break
            log(f"   Queued {len(stories_queued)} batches")
            if "already-running" in stories_queued:
                log("   ⏳ Waiting for current maintenance to finish before re-queuing...")
                stories_queued = []  # Reset so we try again next round

        # ── Phase 2: Check if everything is done ─────────────────
        if stories_queued and running == 0:
            log("✅ All tasks complete!")
            log(f"   Done: {counts.get('done',0)} | Error: {counts.get('error',0)}")

            # If there are errors, retry errored tasks
            if counts.get("error", 0) > 0:
                log("   Some tasks errored — checking if retryable...")
                # Check individual story files
                for sdir in sorted(STORIES_ROOT.iterdir()):
                    if sdir.name == ".trash":
                        continue
                    jfile = list(sdir.glob("*.json"))
                    if jfile:
                        with open(jfile[0]) as f:
                            data = json.load(f)
                        scenes = len(data.get("scenes", []))
                        imgs = sum(len(s.get("image_filenames", [])) for s in data.get("scenes", []))
                        if scenes == 0 or imgs == 0:
                            log(f"   ⚠️  {sdir.name} — {scenes} scenes, {imgs} images — needs work")
                log("   Manual retry may be needed for errored stories")
            break

        # ── Phase 3: Wait ────────────────────────────────────────
        if running > 0:
            log(f"   ⏳ {running} active — sleeping 60s...")
            time.sleep(60)
        else:
            log("   ⏳ No active tasks — sleeping 30s before re-check...")
            time.sleep(30)

    log("🌙 Nightly Steward finished")
    log(f"   Completed {round_num} rounds over ~{round_num * 0.5} hours")

if __name__ == "__main__":
    main()
