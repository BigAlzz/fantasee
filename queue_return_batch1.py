#!/usr/bin/env python3
"""Queue 'The Return' stories — batch of 5 (first half)."""
import json, sys, requests

BASE = "http://127.0.0.1:8765"

STORIES = [
    {
        "story_concept": "Selene, a 300-year-old Neanderthal elder, must sing open a Gate Stone to save 50,000 refugees from a dying world. The song will kill her. Her grandson Kael carries her litter. The rift-walker Mira has seen this moment in eight possible futures — in seven, Selene dies. The Gate Stone is cold. The Weave is thin. Selene opens her mouth and begins to sing.",
        "style": "dark gothic",
        "tone": "epic",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Milo",
        "characters": "Selene — 300 years old, white-haired, silver eyes, carried on a wooden litter, robes of woven fungal fiber. She has not walked in two centuries.\nKael — 29, Selene's grandson, lean, pale silver eyes, healer's hands. He carries the front of her litter.\nMira — 34, rift-walker, dark hair cropped short, haunted eyes. She reads the threads of fate."
    },
    {
        "story_concept": "Korrath Stone-Hand leads a Neanderthal war party into a frozen forest at dawn. A Concord patrol in powered armor blocks their path. Korrath kneels, presses his crystal stump to the earth, and undergoes The Turning — bones shift, skin grays, eyes go white, he grows to eight feet of living stone. The Concord soldiers fire plasma rifles. The bolts hit his stone-skin and glow white-hot. He does not slow down. He shatters their weapons. He stands over them and says: Go home. Tell them the earth remembers.",
        "style": "cinematic realism",
        "tone": "dark",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Dean",
        "characters": "Korrath Stone-Hand — 47, broadest Neanderthal, heavy brow ridge, gray-umber skin, ceremonial facial scars, long braided hair. Missing left hand replaced by a jagged crystal stump.\nVarn — Korrath's second-in-command, scarred veteran, white beard.\nSergeant Okafor — Concord squad leader, 30s, professional, Mk.7 Ironhide powered armor."
    },
    {
        "story_concept": "Yenna, a 19-year-old Deep-Man, walks across a Concord internment camp at midnight. She is the youngest Bone Singer — she hears the voices of the dead buried beneath the earth. The camp was built on a Neanderthal mass grave. 300 dead lie under the concrete. A child asks for its mother. A warrior sings a battle hymn. A woman weeps. Yenna kneels, places her pale hand flat, and listens. She is the Whisper — the voice of the Deep-Men council. She is 19 and has not slept without nightmares since she was seven.",
        "style": "dark gothic",
        "tone": "dark",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Milo",
        "characters": "Yenna — 19, Deep-Man, pale white skin almost translucent, large solid-black eyes, lanky, wraps herself in dark leather. Permanently burnt from surface exposure.\nGren — 27, Deep-Man scout, smoked goggles, full-body leather wrap, eerie fluid movement.\nThe Warden — age unknown, last keeper of the Deep Archive. Remembers the First Crossing."
    },
    {
        "story_concept": "Kael, a Weave-Born healer, walks through the aftermath of the Battle of Wolf Creek. 57 Neanderthals lie dead. 23 humans lie wounded. Kael is unarmed. He begins with the humans. He kneels beside a soldier with a shattered leg, places his hand on the wound, and the flesh knits back together. He heals every human before touching a single Neanderthal corpse. A soldier asks why. Kael says: Because you are alive and they are not. The living come first. Healing each human costs him a month of his own life. He heals 13. He does not regret it.",
        "style": "fantasy painterly",
        "tone": "emotional",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Milo",
        "characters": "Kael Weave-Born — 29, lean, pale silver eyes, simple robes of woven fungal fiber, healer's hands.\nCaptain Marcus Cole — 44, Concord commander, powered armor splattered with mud and blood.\nPrivate Torres — 22, first deployment, plasma rifle shaking in his hands."
    },
    {
        "story_concept": "In a cave beneath the Threshold shantytown, a nameless Neanderthal called The Collector sits surrounded by disassembled human technology. He has figured out electricity. He has built a battery that stores Weave energy — a device bridging two species' understanding of reality. It hums. It glows purple. If he releases it, it could end the energy crisis or start a war. He turns it over in scarred hands, listening to humans and Neanderthals trading above. He has not spoken to anyone in six months. He is afraid of what he has built.",
        "style": "cinematic realism",
        "tone": "suspenseful",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Dean",
        "characters": "The Collector — age unknown, Scattered Neanderthal, gaunt, wild hair, fingers stained with grease.\nBroker — human, middle-aged, expensive coat, no loyalty except to money.\nDace — former Stone-Born warrior, deserted after the first battle, runs a salvage operation."
    }
]

def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        for i, s in enumerate(STORIES):
            print(f"  [{i+1}] {s['story_concept'][:60]}...")
        return

    print(f"Queueing {len(STORIES)} stories to {BASE}...")
    resp = requests.post(f"{BASE}/api/generate/queue", json={"items": STORIES}, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        print(f"OK — queue_id: {data.get('queue_id', '?')}")
    else:
        print(f"ERROR {resp.status_code}: {resp.text}")

if __name__ == "__main__":
    main()
