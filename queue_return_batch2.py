#!/usr/bin/env python3
"""Queue 'The Return' stories — batch of 5 (second half)."""
import json, sys, requests

BASE = "http://127.0.0.1:8765"

STORIES = [
    {
        "story_concept": "Private Elena Vasquez, 19, Concord infantrywoman, tracks Neanderthals through old-growth forest. Her HUD labels them as catalog numbers KN-0782 through KN-0787. At dawn they find the Neanderthals gathered around an ancient cedar. An old woman has her hand on the bark. She is weeping. Elena's HUD says THREAT ASSESSMENT: LOW. Her sergeant orders her to fire. She does not fire. The old woman looks at her. Elena's HUD glitches. For one second she sees a face instead of a number. Scarred. Tired. Silver eyes. The sound of someone coming home.",
        "style": "cinematic realism",
        "tone": "dramatic",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Chloe",
        "characters": "Private Elena Vasquez — 19, Concord infantrywoman, Mk.7 Ironhide armor, dark hair tied back.\nSergeant Okonkwo — 35, squad leader, professional, believes in the mission.\nThe Old Woman — Stone-Born elder, silver eyes, ceremonial scars, barefoot in the snow beside an ancient cedar."
    },
    {
        "story_concept": "In the Threshold shantytown, a three-year-old child named Ash sits in a tent and cries. Ash is the first human-Neanderthal hybrid — mother human, father Deep-Man. Ash's eyes are solid black. Ash can sense emotions like weather. Outside, a Concord retrieval team has come to claim the child for study. Neanderthal warriors and human volunteers form a ring around the tent. Ash's mother holds the child and sings a Deep-Man lullaby that means you are safe. Ash feels the fear of a hundred people outside. The world is very loud and no one will turn it down.",
        "style": "dark gothic",
        "tone": "emotional",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Mia",
        "characters": "Ash — 3 years old, hybrid child, solid black eyes, senses emotions, cries when surrounded by strong feeling.\nSarah — Ash's mother, 28, human, exhausted, fierce.\nDirector Elena Vasquez — 52, head of the Concord, authorized the retrieval from Geneva."
    },
    {
        "story_concept": "Nevarrah is dying. One million Neanderthals stand at the Gate Stones. The Stones can handle a hundred at a time. Nevarrah has weeks. Korrath Stone-Hand volunteers to power the Stones — channeling a rift burns years off the user's life. He kneels, presses his crystal hand to the surface. The rift opens. The people walk through. He does not stop. His hair whitens. His skin thins. His bones show through his flesh. On the third day Varn takes his place. Korrath collapses. He is 47. He looks 90. He refuses to go through. He will be the last.",
        "style": "dark gothic",
        "tone": "epic",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Dean",
        "characters": "Korrath Stone-Hand — 47 but aging rapidly, crystal stump glowing white-hot, kneeling at the Gate Stone.\nVarn — scarred veteran, white beard, taking Korrath's place at the Stone.\nThera — Korrath's daughter, 22, geopath, in the crowd. She can feel her father dying through the earth."
    },
    {
        "story_concept": "In a cave beneath the Threshold, the Warden — oldest living Neanderthal, keeper of the Deep Archive — sits across from Kael Weave-Born. The Warden has not spoken in 50 years. He carries a truth that could shatter both species. Kael asks why the Neanderthals really left Earth. The Warden says: We did not flee the cold. We fled the apes. Not because they were strong. Because they could not feel the Weave. They walked through our sacred places and felt nothing. The earth needed us. We left it alone for 40,000 years with creatures who could not hear it scream.",
        "style": "dark gothic",
        "tone": "dramatic",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Dean",
        "characters": "The Warden — age unknown, keeper of the Deep Archive, sitting in absolute darkness, wrapped in ancient cloth.\nKael Weave-Born — 29, healer, silver eyes, sitting across from the Warden in the dark.\nSelene — 300 years old, present but silent, listening from the shadows."
    },
    {
        "story_concept": "Three months after Neanderthal refugees arrive in the Pacific Northwest, the land begins to change. A Concord research team investigates a Weave bleed zone — grass three feet tall in December, trees with bark that glows at night, wolves that approach without fear. In the center, a Gate Stone buried for 40,000 years hums with energy. Flowers bloom in the snow. Dr. Aris Thorne places his hand on the stone. He feels nothing. He is human. The stone does not recognize him. But the wolves do. They watch. They are not afraid. They are waiting.",
        "style": "fantasy painterly",
        "tone": "mysterious",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Dean",
        "characters": "Dr. Aris Thorne — 39, Concord lead researcher, brilliant, morally broken by curiosity.\nPrivate Torres — 22, security escort, was at Wolf Creek, was healed by a Weave-Born, has not fired his weapon since.\nThe Wolves — present, watching, not afraid of the humans."
    }
]

def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        for i, s in enumerate(STORIES):
            print(f"  [{i+6}] {s['story_concept'][:60]}...")
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
