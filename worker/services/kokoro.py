import httpx
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from services.db import db

class Kokoro:
    def __init__(self):
        self._current_endpoint_index = 0

    def _get_config(self):
        settings = db.get_settings()
        url_str = settings.get("kokoroUrl") or os.getenv("KOKORO_URL", "http://localhost:7860/")
        urls = [u.strip() for u in url_str.split(',') if u.strip()]
        return urls

    async def synthesize(self, text, voice_id, output_path, speed=1.0):
        urls = self._get_config()
        if not urls:
            raise Exception("No Kokoro URLs configured.")
            
        import asyncio
        last_exception = None
        
        # Try endpoints one by one (Load Balancing + Failover)
        for _ in range(len(urls)):
            selected_url = urls[self._current_endpoint_index % len(urls)]
            base_url = selected_url.rstrip('/')
            self._current_endpoint_index = (self._current_endpoint_index + 1) % len(urls)
            
            print(f"DEBUG: Media Handoff | Synthesizing on node: {base_url}")
            
            # Kokoro API often expects 'input' and 'voice'
            # Using the provided speed parameter for synthesis
            payload = {
                "input": text,
                "voice": voice_id,
                "speed": float(speed),
                "response_format": "wav"
            }
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                max_retries = 2
                retry_delay = 2
                
                for attempt in range(max_retries):
                    try:
                        response = await client.post(f"{base_url}/v1/audio/speech", json=payload)
                        
                        if response.status_code == 429:
                            print(f"DEBUG: Node {base_url} Rate Limited (429). Retrying...")
                            await asyncio.sleep(retry_delay)
                            continue

                        # If 'input' failed, try 'text'
                        if response.status_code == 422:
                            payload_alt = payload.copy()
                            if "input" in payload_alt:
                                payload_alt["text"] = payload_alt.pop("input")
                            response = await client.post(f"{base_url}/v1/audio/speech", json=payload_alt)
                        
                        response.raise_for_status()
                        
                        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                        with open(output_path, "wb") as f:
                            f.write(response.content)
                        return output_path
                    except Exception as e:
                        if attempt == max_retries - 1:
                            last_exception = e
                            break # Try next node
                        print(f"DEBUG: Node {base_url} transient error: {str(e)}. Retrying...")
                        await asyncio.sleep(retry_delay)
        
        raise Exception(f"All Kokoro nodes failed. Last error: {str(last_exception)}")

kokoro = Kokoro()
