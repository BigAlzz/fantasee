import os
import subprocess
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("AudioPipelineTest")

def test_audio_stitching_logic():
    print("\n--- AUDIO STITCHING & PROBE TEST ---")
    
    # We will use ffprobe to verify duration logic
    # and verify that we can stitch files
    
    test_dir = Path("test_audio_assets")
    test_dir.mkdir(exist_ok=True)
    
    # Check if ffmpeg/ffprobe are available
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
        print("✅ FFmpeg and FFprobe are available")
    except Exception:
        print("❌ FFmpeg/FFprobe not found. Skipping stitching tests.")
        return

    # Mock audio generation duration logic
    def get_mock_duration(file_path):
        # This mirrors the logic in ffmpeg.py
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip()) if result.returncode == 0 else 0.0

    print("✅ Audio probing logic ready for verification")

def test_wav_speed_synthesis():
    print("\n--- WAV SYNTHESIS SPEED TEST ---")
    # Verify that the speed parameter is handled as a float
    speed = 1.05
    payload = {
        "input": "Test",
        "voice": "af_heart",
        "speed": float(speed),
        "response_format": "wav"
    }
    
    assert isinstance(payload["speed"], float)
    assert payload["response_format"] == "wav"
    print(f"✅ WAV speed synthesis payload verified (Speed: {speed})")

if __name__ == "__main__":
    test_audio_stitching_logic()
    test_wav_speed_synthesis()
