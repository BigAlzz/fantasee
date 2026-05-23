"""Launch the Story Viewer Netflix-style browser."""
import subprocess
import sys
import webbrowser
from pathlib import Path

SERVER = Path(__file__).parent / "server.py"

print("=" * 60)
print("  Story Viewer — Netflix-style browser")
print("  http://127.0.0.1:8765")
print("=" * 60)

# Open browser after a short delay
webbrowser.open("http://127.0.0.1:8765")

# Run the server
result = subprocess.run(
    [sys.executable, str(SERVER)],
    cwd=SERVER.parent,
)
sys.exit(result.returncode)
