#!/usr/bin/env python3
"""
Retry the 5 failed manhwa stories using a 5-scene-first + extend-by-5 approach.
This avoids the token limit issue where MiMo can't fit 10 scenes of long manhwa
narration in a single 4096-token response.
"""
import json
import requests
import time
import sys

BASE = "http://127.0.0.1:8765"

# The 5 failed concepts (from the original queue)
stories_5 = [
    {
        "story_concept": (
            "A modern military engineer dies in a drone strike and wakes up as a disgraced "
            "knight in a medieval kingdom on the brink of collapse. Armed with knowledge of "
            "fortification design, ballistics, supply chain logistics, and modern military "
            "strategy, he must rebuild a broken army while navigating court intrigue. His "
            "tactical genius attracts the attention of a beautiful but deadly female spymaster "
            "named Lyra who becomes his closest ally. Together they face barbarian hordes, "
            "corrupt nobles, and a failing harvest while secretly planning a revolution in "
            "military technology."
        ),
        "style": "manhwa",
        "tone": "manhwa",
        "num_scenes": 5,
        "images_per_scene": 2,
        "characters": (
            "Marcus -- a tall, scarred modern military engineer reborn as a medieval knight "
            "with short black hair and intense grey eyes. "
            "Lyra -- a striking female spymaster with silver-white hair, sharp green eyes, "
            "and a lithe combat-ready build, always in dark fitted leather."
        ),
        "voice_preset": "Dean",
    },
    {
        "story_concept": (
            "A female cybersecurity expert from the NSA is pulled into a medieval world where "
            "an ancient magical kingdom is being destroyed by a sentient dark network -- a "
            "corrupted magical grid that spreads like a computer virus through ley lines. She "
            "must apply network security principles and system architecture to fight an enemy "
            "operating like a distributed AI threat. Her partner is Zara, a mysterious mage "
            "with cybernetic-like magical implants."
        ),
        "style": "manhwa",
        "tone": "manhwa",
        "num_scenes": 5,
        "images_per_scene": 2,
        "characters": (
            "Agent Nexus (Keira) -- a lean woman with short platinum-blonde undercut, piercing "
            "blue eyes, and a tactical bodysuit integrated with magical circuits. "
            "Zara -- an enigmatic female mage with long dark violet hair, glowing amber eyes, "
            "and crystalline magical implants along her neck and collarbone."
        ),
        "voice_preset": "Dean",
    },
    {
        "story_concept": (
            "A naval warfare strategist from the US Pacific Fleet is transported to a world of "
            "island nations locked in perpetual maritime war. With knowledge of modern naval "
            "tactics, ship construction, and ocean navigation, he transforms a fishing village's "
            "boats into a devastating naval force. A female pirate queen named Captain Maren "
            "becomes his ally as they take on the tyrannical Admiralty keeping nations in darkness."
        ),
        "style": "manhwa",
        "tone": "manhwa",
        "num_scenes": 5,
        "images_per_scene": 2,
        "characters": (
            "Commander Daniel Drake -- a weathered man with salt-and-pepper stubble, steel-blue "
            "eyes, and a naval officer's bearing. "
            "Captain Maren -- a voluptuous female pirate with sun-bronzed skin, wild sea-green "
            "hair streaked with gold, heterochromatic eyes (one blue, one gold), and a captain's coat."
        ),
        "voice_preset": "Dean",
    },
    {
        "story_concept": (
            "A pharmaceutical researcher is reborn in a plague-ridden fantasy world where disease "
            "wipes out entire cities. Her modern knowledge of microbiology, epidemiology, and "
            "vaccine development gives her an edge no one else has. A female healer-priestess "
            "named Amara becomes her devoted companion as they race to develop cures while "
            "battling a fanatical religious order that sees disease as divine punishment."
        ),
        "style": "manhwa",
        "tone": "manhwa",
        "num_scenes": 5,
        "images_per_scene": 2,
        "characters": (
            "Dr. Sarah Chen -- an East Asian woman with shoulder-length black hair, warm brown "
            "eyes, and a calm determined expression, in a modified healer's robe. "
            "Amara -- a tall female priestess-healer with golden-brown skin, flowing white hair, "
            "deep violet eyes, and sacred medical tattoos along her forearms."
        ),
        "voice_preset": "Dean",
    },
    {
        "story_concept": (
            "A special forces combat engineer wakes up in a medieval kingdom besieged by undead "
            "hordes rising from ancient cursed battlefields. His knowledge of explosives, "
            "demolition, and military engineering is the kingdom's last hope. A female necromancer "
            "turned rogue named Vex -- darkly beautiful with death-magic -- becomes his unlikely "
            "partner as they venture into cursed lands to destroy the source of the undead plague."
        ),
        "style": "manhwa",
        "tone": "manhwa",
        "num_scenes": 5,
        "images_per_scene": 2,
        "characters": (
            "Sergeant Kane -- a muscular man with a shaved head, dark skin, a jagged scar across "
            "his jaw, and tactical gear adapted to medieval materials. "
            "Vex -- a hauntingly beautiful female necromancer with ashen skin, pitch-black hair "
            "with white streaks, glowing pale eyes, and dark robes that shift like smoke."
        ),
        "voice_preset": "Dean",
    },
]

# Step 1: Generate 5-scene versions
print("=== Step 1: Generating 5-scene stories ===")
queue_payload = {"items": stories_5}
r = requests.post(f"{BASE}/api/generate/queue", json=queue_payload, timeout=30)
qdata = r.json()
queue_id = qdata["queue_id"]
print(f"Queue {queue_id}: {qdata['message']}")

# Step 2: Wait for queue to finish
print("\n=== Step 2: Waiting for generation... (checking every 30s)")
while True:
    time.sleep(30)
    try:
        qr = requests.get(f"{BASE}/api/generate/tasks/{queue_id}", timeout=10).json()
        status = qr.get("status", "unknown")
        progress = qr.get("progress", 0)
        message = qr.get("message", "")
        print(f"  Queue: {status} ({progress*100:.0f}%) — {message}")
        if status in ("done", "error"):
            break
    except Exception as e:
        print(f"  Poll error: {e}")

# Step 3: Find generated stories and extend each by 5
print("\n=== Step 3: Extending each story by 5 scenes ===")
stories_r = requests.get(f"{BASE}/api/stories", timeout=10).json()
manhwa_stories = [s for s in stories_r["stories"] if "manhwa" in s.get("tags", []) and s["scene_count"] >= 5]

for s in manhwa_stories:
    sid = s["id"]
    sc = s["scene_count"]
    if sc >= 10:
        print(f"  {sid}: already has {sc} scenes, skipping")
        continue
    print(f"  {sid}: has {sc} scenes, extending by 5...")
    try:
        er = requests.post(
            f"{BASE}/api/stories/{sid}/extend",
            json={"scenes": 5, "images_per_scene": 2},
            timeout=600,
        )
        if er.ok:
            data = er.json()
            print(f"    Extended: +{data.get('new_scenes_added',0)} scenes, total: {data.get('total_scenes',0)}")
        else:
            print(f"    Extend failed: {er.status_code} {er.text[:200]}")
    except Exception as e:
        print(f"    Extend error: {e}")

# Step 4: Render + export to Plex
print("\n=== Step 4: Render + Plex export ===")
stories_r = requests.get(f"{BASE}/api/stories", timeout=10).json()
for s in stories_r["stories"]:
    if "manhwa" not in s.get("tags", []):
        continue
    sid = s["id"]
    sc = s["scene_count"]
    if sc < 5:
        print(f"  {sid}: only {sc} scenes, skipping")
        continue

    # Render
    import subprocess
    print(f"  Rendering {sid} ({sc} scenes)...")
    try:
        proc = subprocess.run(
            [sys.executable, "render_video.py", sid],
            capture_output=True, text=True, timeout=600,
            cwd="C:/dev/fantasee",
        )
        if proc.returncode != 0:
            print(f"    Render FAILED: {(proc.stderr or '')[-200:]}")
            continue
        print(f"    Render OK")
    except Exception as e:
        print(f"    Render error: {e}")
        continue

    # Export to Plex
    print(f"  Exporting {sid} to Plex...")
    try:
        er = requests.post(f"{BASE}/api/stories/{sid}/export-plex", json={}, timeout=600)
        if er.ok:
            export_tid = er.json().get("task_id", "")
            for _ in range(120):
                time.sleep(5)
                et = requests.get(f"{BASE}/api/generate/tasks/{export_tid}", timeout=5).json()
                if et.get("status") == "done":
                    print(f"    Plex OK!")
                    break
                elif et.get("status") == "error":
                    print(f"    Plex FAILED: {et.get('message','')[:200]}")
                    break
    except Exception as e:
        print(f"    Export error: {e}")

print("\n=== ALL DONE ===")
stories_r = requests.get(f"{BASE}/api/stories", timeout=10).json()
manhwa = [s for s in stories_r["stories"] if "manhwa" in s.get("tags", [])]
print(f"Total manhwa stories: {len(manhwa)}")
for s in manhwa:
    print(f"  {s['id']}: {s['title']} ({s['scene_count']} scenes)")
