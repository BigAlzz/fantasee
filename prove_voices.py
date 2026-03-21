import httpx
import json
import os

url = "http://localhost:7860/v1/audio/speech"

# Narrator Voice
payload1 = {
    "input": "This is the narrator speaking in a calm female voice. I am using the heart voice model.",
    "voice": "af_heart",
    "response_format": "mp3"
}

# Character Voice
payload2 = {
    "input": "And I am a different character! I have a deeper, energetic male voice. Can you hear the difference?",
    "voice": "am_adam",
    "response_format": "mp3"
}

try:
    print("Requesting Narrator (af_heart)...")
    r1 = httpx.post(url, json=payload1, timeout=60)
    if r1.status_code == 200:
        with open("test_voice_1_narrator.mp3", "wb") as f:
            f.write(r1.content)
        print("✅ Saved test_voice_1_narrator.mp3")
    else:
        print(f"❌ Failed Narrator: {r1.status_code} - {r1.text}")

    print("\nRequesting Character (am_adam)...")
    r2 = httpx.post(url, json=payload2, timeout=60)
    if r2.status_code == 200:
        with open("test_voice_2_character.mp3", "wb") as f:
            f.write(r2.content)
        print("✅ Saved test_voice_2_character.mp3")
    else:
        print(f"❌ Failed Character: {r2.status_code} - {r2.text}")

    print("\nPROOFS CREATED. Please check the project root for these two files.")
except Exception as e:
    print(f"Error: {e}")
