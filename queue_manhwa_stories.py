#!/usr/bin/env python3
"""Queue 8 manhwa time-travel stories for batch generation."""
import json
import requests

BASE = "http://127.0.0.1:8765"

stories = [
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
        "num_scenes": 10,
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
            "A female aerospace engineer from 2025 is transported to a dying fantasy empire "
            "where airships rule the skies but are failing. She understands aerodynamics, "
            "materials science, and engine design. A roguish female sky-captain named Kira "
            "becomes her bodyguard as they race to rebuild the imperial fleet before enemy "
            "forces invade. The engineer must balance modern principles with medieval resources "
            "while uncovering a conspiracy sabotaging the fleet from within."
        ),
        "style": "manhwa",
        "tone": "manhwa",
        "num_scenes": 10,
        "images_per_scene": 2,
        "characters": (
            "Dr. Elena Voss -- a brilliant woman with dark auburn hair, green eyes behind "
            "thin-rimmed glasses, wearing a modified flight suit. "
            "Kira -- a fierce female sky-captain with tanned skin, wild black curls, a cocky "
            "grin, and dual pistols at her hips."
        ),
        "voice_preset": "Dean",
    },
    {
        "story_concept": (
            "A project manager for a defense contractor dies and is reborn as a slave in an "
            "ancient gladiatorial arena. Using modern project management, logistics optimization, "
            "and supply chain knowledge, he turns ragtag gladiators into an unstoppable team. "
            "A fierce female gladiator trainer named Sera helps him organize a rebellion that "
            "will shake the empire to its core."
        ),
        "style": "manhwa",
        "tone": "manhwa",
        "num_scenes": 10,
        "images_per_scene": 2,
        "characters": (
            "James Walker -- a broad-shouldered man with cropped brown hair and a strategist's "
            "calculating eyes, bearing arena scars. "
            "Sera -- a powerful female gladiator trainer with fiery red hair in braids, deep "
            "brown eyes, athletic build, and ritual scars on her arms."
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
        "num_scenes": 10,
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
        "num_scenes": 10,
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
        "num_scenes": 10,
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
        "num_scenes": 10,
        "images_per_scene": 2,
        "characters": (
            "Sergeant Kane -- a muscular man with a shaved head, dark skin, a jagged scar across "
            "his jaw, and tactical gear adapted to medieval materials. "
            "Vex -- a hauntingly beautiful female necromancer with ashen skin, pitch-black hair "
            "with white streaks, glowing pale eyes, and dark robes that shift like smoke."
        ),
        "voice_preset": "Dean",
    },
    {
        "story_concept": (
            "A civil engineer specializing in dam construction is transported to a drought-stricken "
            "desert kingdom where water is power. With knowledge of hydrology, aquifer mapping, "
            "and irrigation systems, she becomes the most valuable person in the kingdom. A "
            "charismatic female desert warrior named Zahra becomes her protector and political "
            "ally as they bring water to a dying land while outmaneuvering a rival kingdom "
            "secretly diverting the rivers."
        ),
        "style": "manhwa",
        "tone": "manhwa",
        "num_scenes": 10,
        "images_per_scene": 2,
        "characters": (
            "Engineer Maya -- a fit woman with sun-streaked brown hair, sharp hazel eyes, "
            "dust-stained work clothes, and a surveyor's compass at her hip. "
            "Zahra -- a powerful female desert warrior with bronze skin, thick braided black hair "
            "adorned with gold rings, fierce dark eyes, and flowing white combat robes."
        ),
        "voice_preset": "Dean",
    },
]

print(f"Queueing {len(stories)} stories...")
payload = {"items": stories}

try:
    r = requests.post(f"{BASE}/api/generate/queue", json=payload, timeout=30)
    print(f"Status: {r.status_code}")
    result = r.json()
    print(json.dumps(result, indent=2))
except Exception as e:
    print(f"Error: {e}")
