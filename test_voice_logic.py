import json
import logging
from pathlib import Path
import asyncio

# Setup minimal logging for the test
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("VoiceTest")

class MockDB:
    def __init__(self):
        self.characters = [
            {"name": "Eldrin the Wise", "voiceId": "am_adam"},
            {"name": "Lyra", "voiceId": "af_bella"}
        ]
        self.narrator_voice = "af_heart"

    def get_char_voice_map(self):
        return {c['name'].lower().strip(): c['voiceId'] for c in self.characters}

def test_voice_matching(speaker_raw, char_voice_map, narrator_voice):
    speaker_norm = speaker_raw.lower().strip()
    voice = narrator_voice
    match_type = "None (Narrator)"

    # 1. Exact Match
    if speaker_norm in char_voice_map:
        voice = char_voice_map[speaker_norm]
        match_type = "Exact"
    else:
        # 2. Advanced Fuzzy Match (Substring/Word overlap)
        found_fuzzy = False
        speaker_words = set(speaker_norm.split())
        
        for char_name_norm, char_voice in char_voice_map.items():
            char_words = set(char_name_norm.split())
            # Check if names are subsets OR if they share significant words
            if (char_name_norm in speaker_norm or speaker_norm in char_name_norm or 
                len(speaker_words.intersection(char_words)) > 0):
                voice = char_voice
                found_fuzzy = True
                match_type = f"Fuzzy (Matched '{char_name_norm}')"
                break
    
    return voice, match_type

def run_suite():
    db = MockDB()
    char_map = db.get_char_voice_map()
    narrator = db.narrator_voice

    test_cases = [
        ("Eldrin the Wise", "am_adam"),  # Exact
        ("Eldrin", "am_adam"),           # Fuzzy (Substring)
        ("Lyra", "af_bella"),            # Exact
        ("Narrator", "af_heart"),        # Fallback
        ("King Eldrin", "am_adam"),      # Fuzzy (Substring)
        ("Stranger", "af_heart"),        # Unknown
    ]

    print("\n--- MULTI-VOICE MATCHING TEST SUITE ---")
    print(f"Narrator Voice: {narrator}")
    print(f"Character Map: {char_map}\n")

    passed = 0
    for speaker, expected in test_cases:
        actual, mtype = test_voice_matching(speaker, char_map, narrator)
        status = "✅ PASS" if actual == expected else "❌ FAIL"
        if actual == expected: passed += 1
        print(f"{status} | Input: '{speaker:15}' | Result: {actual:10} | Type: {mtype}")

    print(f"\nResults: {passed}/{len(test_cases)} passed.")

if __name__ == "__main__":
    run_suite()
