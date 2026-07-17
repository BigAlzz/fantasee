#!/usr/bin/env python3
"""Queue all 'The Return' stories into Fantasee.

Usage:
    python queue_the_return.py              # queue all 10
    python queue_the_return.py 1 3 5        # queue specific stories by number
    python queue_the_return.py --dry-run    # print without submitting
"""

import json
import sys
import requests

BASE = "http://127.0.0.1:8765"

STORIES = [
    {
        "story_concept": "A Neanderthal elder named Selene, 300 years old, carried on a litter by two students, arrives at a Gate Stone on a dying world. She has not walked in 200 years. She sang the First Crossing — the ritual that brought her people from Earth to Nevarrah — and it broke her spine. Now she must sing again. The world is ending. 50,000 refugees stand behind her. The Gate Stone is cold. The Weave is thin. She opens her mouth and begins to sing. The song costs her everything she has left. The rift opens. The people walk through. She does not follow. She remains on the dying world, alone, singing the gate open until the last child is through. Then the song stops. The gate closes. The world goes quiet.",
        "style": "dark gothic",
        "tone": "epic",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Milo",
        "characters": "Selene — 300 years old, carried on a wooden litter, white-haired, silver eyes, robes of woven fungal fiber. She has not stood unaided in two centuries. Her voice is the only part of her that still works perfectly.\nKael — 29, Selene's grandson, lean, pale silver eyes, healer's hands. He carries the front of her litter. He knows she will not survive the singing.\nMira — 34, rift-walker, dark hair cropped short, haunted eyes. She reads the threads of fate. She has seen this moment in eight possible futures. In seven, Selene dies."
    },
    {
        "story_concept": "A Stone-Born war party of six encounters a Concord patrol in a frozen forest at dawn. The Concord soldiers have powered armor, plasma rifles, and Tethers. The Stone-Born have stone weapons and The Turning. Korrath Stone-Hand, missing his left hand, fused with a crystal stump, kneels and presses his palm to the frozen earth. The land recognizes him. His bones shift. His skin grays. His eyes go white. He grows to eight feet. The Concord soldiers fire. The plasma bolts hit his stone-skin and glow white-hot. He does not slow down. He walks through their fire like a man walking through rain. He does not kill them. He shatters their weapons with his crystal hand. He stands over the fallen soldiers, breathing steam, eight feet of living stone, and he speaks in a language older than civilization. He says: Go home. Tell them the earth remembers.",
        "style": "cinematic realism",
        "tone": "dark",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Dean",
        "characters": "Korrath Stone-Hand — 47, broadest of all Neanderthals, heavy brow ridge, gray-umber skin, ceremonial facial scars, long braided hair with stone beads. Missing left hand — replaced by a jagged crystal stump that pulses with Weave energy.\nVarn — Korrath's second-in-command, scarred veteran, white beard, remembers Earth from before the Crossing.\nSergeant Okafor — Concord squad leader, 30s, professional, wearing Mk.7 Ironhide powered armor. His HUD labels the Neanderthals as catalog numbers."
    },
    {
        "story_concept": "Yenna, a 19-year-old Deep-Man, walks across a Concord internment camp at midnight. She is the youngest Bone Singer in history — she can hear the voices of the dead buried beneath the earth. The camp was built on a Neanderthal mass grave from the first skirmish. 300 dead lie under the concrete. Yenna hears all of them. A child is asking for its mother. An old warrior is singing a battle hymn. A woman is weeping. Yenna kneels on the concrete, places her pale hand flat, and listens. She is the Whisper — the voice of the Deep-Men council. She speaks for the dead because no one else will. She carries their grief in silence. She is 19 years old and she has not slept without nightmares since she was seven.",
        "style": "dark gothic",
        "tone": "dark",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Milo",
        "characters": "Yenna — 19, Deep-Man, pale white skin almost translucent, large solid-black eyes, lanky and thin, wraps herself in dark leather. Her skin is permanently burnt from surface exposure. She volunteered as the Whisper because she wanted to see the sun.\nGren — 27, Deep-Man scout, smoked goggles, full-body leather wrap, eerie fluid movement. He is the first of his kind to walk on Earth's surface without pain.\nThe Warden — age unknown, the last keeper of the Deep Archive. He remembers the First Crossing. He carries the history of three worlds."
    },
    {
        "story_concept": "A Weave-Born healer named Kael walks through the aftermath of the Battle of Wolf Creek. 57 Neanderthals lie dead. 23 humans lie dead or wounded. Kael is unarmed. He wears simple robes. He begins with the humans. He kneels beside a Concord soldier with a shattered leg, places his hand on the wound, and the flesh knits itself back together. The soldier stares at him in horror. Kael moves to the next wounded human. And the next. He heals every human on the battlefield before he touches a single Neanderthal corpse. The Concord soldiers watch in silence. Some of them are crying. One of them asks why. Kael says: Because you are alive and they are not. The living come first. He does not tell them that healing each human costs him a month of his own life. He heals 13 humans that day. He loses 13 months. He does not regret it.",
        "style": "fantasy painterly",
        "tone": "emotional",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Milo",
        "characters": "Kael Weave-Born — 29, lean, pale silver eyes, simple robes of woven fungal fiber, healer's hands stained with herb residue. He crossed in the first wave. He set up a clinic in a human refugee camp.\nCaptain Marcus Cole — 44, Concord rapid-response commander, powered armor splattered with mud and blood. His soldiers were outnumbered and outmaneuvered. The Neanderthals spared them.\nPrivate Torres — 22, first deployment, plasma rifle shaking in his hands. He watched a Neanderthal warrior walk through his squad's fire like it was nothing."
    },
    {
        "story_concept": "In a cave beneath the Threshold shantytown, a nameless Neanderthal called The Collector sits surrounded by disassembled human technology. Phones, watches, circuit boards, batteries, screens. He has been taking them apart for a year, trying to understand how they work without magic. He has figured out electricity. He has figured out circuits. He has built a battery that stores not chemical energy but Weave energy — a device that should not exist, bridging two species' understanding of reality. He holds it in his hand. It hums. It glows faintly purple. If he releases this design, it could end the energy crisis on both sides. Or it could start a war over the technology. He sits in his cave, turning the device over in his scarred hands, and listens to the sounds of the Threshold above — humans and Neanderthals arguing, trading, laughing, living. He has not spoken to another person in six months. He is afraid of what he has built.",
        "style": "cinematic realism",
        "tone": "suspenseful",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Dean",
        "characters": "The Collector — age unknown, Scattered Neanderthal, gaunt, wild hair, fingers stained with grease and Weave-residue. He was a hunter on Nevarrah. He has become an engineer on Earth.\nBroker — human, middle-aged, expensive coat, no loyalty except to money. He trades Neanderthal goods to wealthy collectors.\nDace — former Stone-Born warrior, deserted after the first battle. He runs a salvage operation in the Threshold."
    },
    {
        "story_concept": "Private First Class Elena Vasquez, a 19-year-old Concord infantrywoman on her first deployment to the Pacific Northwest frontier. Her squad is tracking a Stone-Born hunting party through old-growth forest. Her HUD labels the contacts as KN-0782 through KN-0787. Catalog numbers. Not names. The squad moves in formation. Railguns charged. Tethers ready. They make contact at dawn. The Neanderthals are not hunting. They are gathered around a tree — an ancient cedar, thousands of years old. One of them, an old woman, has her hand on the bark. She is weeping. Elena's HUD flashes: CONTACT. THREAT ASSESSMENT: LOW. She does not fire. Her sergeant orders her to fire. She does not fire. The old woman looks at her. Elena's HUD glitches. For one second, she sees a face instead of a catalog number. Scarred. Tired. The eyes are silver. The old woman speaks. Elena doesn't understand the words. But she understands the tone. It is the sound of someone coming home after a very long time.",
        "style": "cinematic realism",
        "tone": "dramatic",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Chloe",
        "characters": "Private Elena Vasquez — 19, Concord infantrywoman, Mk.7 Ironhide armor, dark hair tied back, eyes that haven't seen combat yet. She joined because civilian life offered nothing.\nSergeant Okonkwo — 35, squad leader, professional, believes in the mission. He has killed Neanderthals before. He sleeps fine.\nThe Old Woman — Stone-Born elder, name unknown, silver eyes, ceremonial scars, standing barefoot in the snow beside a tree that predates human civilization."
    },
    {
        "story_concept": "In the Threshold shantytown, a three-year-old child named Ash sits in a tent and cries. Ash is the first human-Neanderthal hybrid — mother is human, father is a Deep-Man. Ash's eyes are solid black. Ash can see in the dark. Ash can sense emotions — every emotion within a hundred meters presses against the child's mind like weather. Right now, the weather is a storm. Outside, a Concord retrieval team has arrived to claim the child for study. The Threshold has refused. Neanderthal warriors and human volunteers form a ring around the tent. Inside, Ash's mother holds the child and sings a lullaby she learned from the child's father — a Deep-Man melody that means you are safe. Ash doesn't feel safe. Ash feels the fear of the hundred people outside. The child doesn't know why everyone is afraid. The child only knows that the world is very loud and no one will turn it down.",
        "style": "dark gothic",
        "tone": "emotional",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Mia",
        "characters": "Ash — 3 years old, hybrid child, solid black eyes, can see in the dark, senses emotions. Cries when surrounded by strong feeling.\nSarah — Ash's mother, 28, human, exhausted, fierce, holding her child in a tent while the world argues about who owns him.\nDirector Elena Vasquez — 52, head of the Concord, on a secure line from Geneva. She has authorized the retrieval. She believes she is protecting the child."
    },
    {
        "story_concept": "Nevarrah is dying. The Wound has consumed half the continent. The sky is black with ash. One million Neanderthals stand at the Gate Stones — the last ones still functional. The Stones can handle a hundred at a time. A hundred every hour. The math is brutal: it will take 417 days to move everyone. Nevarrah has weeks. Korrath Stone-Hand volunteers to power the Stones. He knows the cost. Channeling a rift for a hundred people burns years off the user's life. Channeling continuously for days will kill him. He kneels at the first Stone. He presses his crystal hand to the surface. The rift opens. The first hundred walk through. He does not stop. The rift stays open. The people keep walking. His hair whitens. His skin thins. His bones become visible beneath his flesh. He is burning alive from the inside. The people walk through. He does not stop. On the third day, Varn takes his place. Korrath collapses. He is 47 years old. He looks 90. He is still alive. He refuses to go through the rift. He says he will be the last. He always planned to be the last.",
        "style": "dark gothic",
        "tone": "epic",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Dean",
        "characters": "Korrath Stone-Hand — 47 but aging rapidly, crystal stump glowing white-hot, kneeling at the Gate Stone as his life burns away.\nVarn — scarred veteran, white beard, taking Korrath's place at the Stone when his commander collapses. He has followed Korrath for 30 years.\nThera — Korrath's daughter, 22, geopath, standing in the crowd of refugees waiting to cross. She can feel her father dying through the earth."
    },
    {
        "story_concept": "In a cave beneath the Threshold, the Warden — the oldest living Neanderthal, keeper of the Deep Archive — sits across from Kael Weave-Born. The Warden has not spoken in 50 years. He has seen all three worlds: the old Earth, Nevarrah in its glory, and the new Earth. He carries a truth that could shatter both species' understanding of their history. Kael has come to ask why the Neanderthals really left Earth. The Warden is dying. He has decided to speak. He says: We did not flee the cold. We fled the apes. Not because they were strong. Because they were many. And because they did not fear the Weave. They could not feel it. They walked through our sacred places and felt nothing. They buried their dead in our burial grounds and the earth did not recognize them. We left because we realized that a world that cannot feel the Weave is a world that does not need us. We were wrong. The earth needed us. It has been waiting. And now we have returned, and the earth is awake, and it is angry. Kael asks what the earth is angry about. The Warden says: About the 40,000 years we left it alone with creatures who could not hear it scream.",
        "style": "dark gothic",
        "tone": "dramatic",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Dean",
        "characters": "The Warden — age unknown, the last keeper of the Deep Archive, sitting in absolute darkness, wrapped in ancient cloth. He was present for the First Crossing.\nKael Weave-Born — 29, healer, silver eyes, sitting across from the Warden in the dark. He came seeking knowledge.\nSelene — 300 years old, present but silent, listening from the shadows. She was there too. She knows the truth."
    },
    {
        "story_concept": "Three months after the first Neanderthal refugees arrive in the Pacific Northwest, the land begins to change. A Concord research team is sent to investigate a Weave bleed zone — an area where Neanderthal presence has saturated the soil with residual Weave energy. Dr. Aris Thorne leads the team. What they find: grass growing three feet tall in December. Trees with bark that glows faintly at night. A river that runs clearer than any water on Earth. Wolves that approach the camp without fear. And in the center of the zone, a stone — a Gate Stone, buried for 40,000 years, now humming with energy. The earth around it is warm. Flowers are blooming in the snow. Thorne places his hand on the stone. He feels nothing. He is human. The stone does not recognize him. But the wolves do. They watch him. They are not afraid. They are waiting.",
        "style": "fantasy painterly",
        "tone": "mysterious",
        "num_scenes": 10,
        "images_per_scene": 5,
        "voice_preset": "Dean",
        "characters": "Dr. Aris Thorne — 39, Concord lead researcher, brilliant, morally broken by curiosity. He sees the Weave bleed zone not as a miracle but as a resource.\nPrivate Torres — 22, assigned as Thorne's security escort. He was at Wolf Creek. He was healed by a Weave-Born. He has not fired his weapon since.\nThe Wolves — not characters in the traditional sense, but present. They watch. They wait. They are not afraid of the humans."
    }
]

def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")

    if args:
        indices = [int(a) - 1 for a in args]
    else:
        indices = list(range(len(STORIES)))

    titles = [
        "The First Walk",
        "The Turning",
        "The Bone Singer",
        "The Healer's Gambit",
        "The Collector's Fire",
        "The Soldier's HUD",
        "Ash",
        "The Last Crossing",
        "The Warden's Truth",
        "The Land Wakes",
    ]

    queue_items = []
    for i in indices:
        if 0 <= i < len(STORIES):
            queue_items.append(STORIES[i])
            print(f"  [{i+1}] {titles[i]}")

    if dry_run:
        print(f"\nDry run — {len(queue_items)} stories would be queued.")
        for item in queue_items:
            print(f"  concept: {item['story_concept'][:80]}...")
        return

    print(f"\nQueueing {len(queue_items)} stories to {BASE}...")
    resp = requests.post(f"{BASE}/api/generate/queue", json={"items": queue_items}, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        print(f"OK — queue_id: {data.get('queue_id', '?')}")
        print(f"  {len(queue_items)} stories queued for generation.")
    else:
        print(f"ERROR {resp.status_code}: {resp.text}")

if __name__ == "__main__":
    main()
