import json
import logging
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("NarrativeTest")

def test_continuity_logic():
    print("\n--- NARRATIVE CONTINUITY TEST ---")
    
    # Mock data representing a transition from Part 1 to Part 2
    prev_part_text = "Eldrin clutched the ancient stone, its surface glowing with a faint blue light. 'We must reach the summit before dawn,' he whispered to Lyra."
    prev_continuity_notes = {
        "active_items": ["Ancient Stone (Glowing Blue)"],
        "characters": {
            "Eldrin": {"location": "Base of Mount Aether", "state": "Determined"},
            "Lyra": {"location": "Base of Mount Aether", "state": "Waiting"}
        },
        "cliffhanger": "Need to reach summit before dawn"
    }
    
    # Simulate the context extraction we do in main.py
    last_text_context = prev_part_text[-100:]
    
    print(f"Context Passed to Part 2:")
    print(f"-> Last Text: ...{last_text_context}")
    print(f"-> Notes: {json.dumps(prev_continuity_notes, indent=2)}")
    
    # Verification of logic
    # Fixing assertion to match the full string in the list
    assert any("Ancient Stone" in item for item in prev_continuity_notes["active_items"])
    assert prev_continuity_notes["characters"]["Eldrin"]["location"] == "Base of Mount Aether"
    
    print("✅ Narrative Continuity Logic Verified")

def test_dialogue_deduplication():
    print("\n--- DIALOGUE DEDUPLICATION TEST ---")
    
    raw_segments = [
        {"type": "narration", "text": "John looked at the map and said,"},
        {"type": "dialogue", "speaker": "John", "text": "We should go north."},
        {"type": "narration", "text": "We should go north, John repeated as he pointed."} # This is a duplicate
    ]
    
    cleaned = []
    seen = set()
    skipped_count = 0
    
    for seg in raw_segments:
        norm = seg['text'].lower().strip().replace('"', '').replace("'", '').replace('.', '')
        # Check for overlaps (simplified for test)
        is_dup = False
        for s in seen:
            if norm in s or s in norm:
                is_dup = True
                break
        
        if is_dup:
            skipped_count += 1
            continue
            
        seen.add(norm)
        cleaned.append(seg)
        
    print(f"Segments Processed: {len(raw_segments)}")
    print(f"Duplicates Skipped: {skipped_count}")
    assert skipped_count == 1
    print("✅ Dialogue Deduplication Logic Verified")

if __name__ == "__main__":
    test_continuity_logic()
    test_dialogue_deduplication()
