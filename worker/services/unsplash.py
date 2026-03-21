import httpx
import os
import logging
from pathlib import Path
from services.db import db

logger = logging.getLogger(__name__)

class Unsplash:
    def __init__(self):
        pass

    def _get_config(self):
        settings = db.get_settings()
        access_key = settings.get("unsplashAccessKey") or os.getenv("UNSPLASH_ACCESS_KEY")
        return access_key

    async def search_and_download(self, query, output_path, orientation="landscape"):
        access_key = self._get_config()
        if not access_key:
            logger.error("Unsplash Access Key not found in settings or environment")
            return None

        import asyncio
        max_retries = 3
        retry_delay = 5
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(max_retries):
                try:
                    # 1. Search for a cinematic image
                    search_url = "https://api.unsplash.com/search/photos"
                    params = {
                        "query": f"cinematic {query}",
                        "orientation": orientation,
                        "per_page": 1,
                        "client_id": access_key
                    }
                    
                    response = await client.get(search_url, params=params)
                    
                    if response.status_code == 403:
                        logger.error(f"Unsplash Rate Limited (403). Waiting {retry_delay}s... (Attempt {attempt+1}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue

                    response.raise_for_status()
                    data = response.json()
                    
                    if not data["results"]:
                        logger.warning(f"No Unsplash results for query: {query}")
                        return None
                    
                    image_url = data["results"][0]["urls"]["regular"]
                    
                    # 2. Download the image
                    img_response = await client.get(image_url)
                    img_response.raise_for_status()
                    
                    # Ensure directory exists
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    
                    with open(output_path, "wb") as f:
                        f.write(img_response.content)
                    
                    logger.info(f"Successfully downloaded Unsplash image for '{query}' to {output_path}")
                    return output_path
                    
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Unsplash Error after {max_retries} attempts: {str(e)}")
                        return None
                    logger.warning(f"Unsplash Error (Attempt {attempt+1}/{max_retries}): {str(e)}. Retrying...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2

unsplash = Unsplash()
