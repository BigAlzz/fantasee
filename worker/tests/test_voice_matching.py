import pytest
import sys
import os

# Add the worker directory to sys.path to import match_voice
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import match_voice

def test_match_voice_exact():
    char_voice_map = {
        "king eldrin": {"voiceId": "am_adam", "voiceSpeed": 1.1},
        "maya": {"voiceId": "af_bella", "voiceSpeed": 1.0}
    }
    voice, speed, log = match_voice("King Eldrin", char_voice_map, "af_heart", 1.0)
    assert voice == "am_adam"
    assert speed == 1.1
    assert "Exact Match" in log

def test_match_voice_fuzzy_substring():
    char_voice_map = {
        "king eldrin": {"voiceId": "am_adam", "voiceSpeed": 1.1}
    }
    # Speaker name contains the character name
    voice, speed, log = match_voice("Eldrin", char_voice_map, "af_heart", 1.0)
    assert voice == "am_adam"
    assert "Fuzzy Match" in log

def test_match_voice_fuzzy_overlap():
    char_voice_map = {
        "king eldrin": {"voiceId": "am_adam", "voiceSpeed": 1.1}
    }
    # Speaker name has word overlap
    voice, speed, log = match_voice("The King spoke", char_voice_map, "af_heart", 1.0)
    assert voice == "am_adam"
    assert "Fuzzy Match" in log

def test_match_voice_fallback():
    char_voice_map = {
        "maya": {"voiceId": "af_bella", "voiceSpeed": 1.0}
    }
    # Unknown speaker
    voice, speed, log = match_voice("Stranger", char_voice_map, "af_heart", 0.9)
    assert voice == "af_heart"
    assert speed == 0.9
    assert "UNKNOWN SPEAKER" in log

def test_match_voice_narration():
    char_voice_map = {"maya": {"voiceId": "af_bella", "voiceSpeed": 1.0}}
    # Empty speaker (narration)
    voice, speed, log = match_voice(None, char_voice_map, "af_heart", 1.0)
    assert voice == "af_heart"
    assert "Narration" in log
