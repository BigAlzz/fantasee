import httpx
import os
import json
from dotenv import load_dotenv

load_dotenv()

from services.db import db

class LMStudio:
    def __init__(self):
        self._current_endpoint_index = 0

    def _get_config(self):
        settings = db.get_settings()
        # LM Link handles remote devices via localhost automatically.
        # v0.4.0+ recommends using the native v1 REST API at /api/v1
        url = settings.get("lmStudioUrl") or os.getenv("LM_STUDIO_URL", "http://localhost:1234/api/v1")
        api_key = settings.get("lmStudioApiKey") or os.getenv("LM_STUDIO_API_KEY", "")
        model_id = settings.get("lmStudioModelId") # LM Link will use preferred device for this model
        return url, api_key, model_id

    async def generate_json(self, prompt, system_prompt="You are a creative writer that outputs valid JSON only."):
        url, api_key, model_id = self._get_config()
        base_url = url.rstrip('/')
        
        # Detect API Version: v0.4.0+ Native API uses /api/v1/chat
        # The docs recommend using the native v1 REST API.
        is_native_api = "/api/v1" in base_url
        chat_endpoint = f"{base_url}/chat" if is_native_api else f"{base_url}/chat/completions"
        
        # LOGGING: LM Link routing
        print(f"DEBUG: LM Link | Routing via: {base_url} | Model: {model_id or 'Auto'}")
        
        try:
            # Optimization for small models
            use_json_mode = True
            if model_id and ("nano" in model_id.lower() or "4b" in model_id.lower() or "3b" in model_id.lower()):
                use_json_mode = False

            payload = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7
            }
            
            if use_json_mode:
                payload["response_format"] = {"type": "json_object"}
            
            if model_id:
                payload["model"] = model_id

            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            
            import asyncio
            async with httpx.AsyncClient(timeout=120.0) as client:
                max_retries = 3
                retry_delay = 2
                
                for attempt in range(max_retries):
                    try:
                        response = await client.post(chat_endpoint, json=payload, headers=headers)
                        
                        if response.status_code == 400:
                            resp_json = response.json()
                            if "response_format" in str(resp_json.get("error", "")):
                                payload["response_format"] = {"type": "text"}
                                response = await client.post(chat_endpoint, json=payload, headers=headers)
                        
                        response.raise_for_status()
                        result = response.json()
                        content = result["choices"][0]["message"]["content"]
                        
                        # Clean up content
                        content = content.strip()
                        if content.startswith("```json"):
                            content = content.replace("```json", "").replace("```", "").strip()
                        elif content.startswith("```"):
                            content = content.replace("```", "").strip()
                            
                        return {
                            "data": json.loads(content),
                            "node": "LM Link (Auto)"
                        }
                    except Exception as e:
                        if attempt == max_retries - 1: raise
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
        except Exception as e:
            print(f"ERROR: LM Link failed: {str(e)}")
            raise


lm_studio = LMStudio()
