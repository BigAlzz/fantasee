import time
import json
import logging
import asyncio
import os
import sys
from pathlib import Path
from services.db import db
from services.lm_studio import lm_studio
from services.kokoro import kokoro
from services.ffmpeg import ffmpeg
from services.unsplash import unsplash

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Windows-compatible locking
def acquire_lock():
    lock_file = "worker.lock"
    if os.name == 'nt':
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            return fd, lock_file
        except OSError:
            print("ERROR: Another worker instance is already running.")
            sys.exit(1)
    else:
        import fcntl
        f = open(lock_file, 'w')
        try:
            fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f, lock_file
        except IOError:
            print("ERROR: Another worker instance is already running.")
            sys.exit(1)

def release_lock(lock_data):
    fd, lock_file = lock_data
    if os.name == 'nt':
        os.close(fd)
        if os.path.exists(lock_file):
            os.remove(lock_file)
    else:
        fd.close()
        if os.path.exists(lock_file):
            os.remove(lock_file)

async def handle_generate_concepts(job):
    payload = json.loads(job['payloadJson'])
    genre = payload.get('genre')
    subgenre = payload.get('subgenre', '')
    tone = payload.get('tonePack', '')
    premise = payload.get('premise', '')
    
    prompt = f"""
    Generate 3 distinct story concepts for a {genre} story.
    Subgenre: {subgenre}
    Tone: {tone}
    User Premise: {premise}
    
    Return a JSON object with a 'concepts' array. Each concept should have:
    - title: A catchy title
    - blurb: A 2-sentence description
    - tone_tags: An array of 3 descriptive tags
    
    IMPORTANT: Return ONLY valid JSON.
    """
    
    try:
        res = await lm_studio.generate_json(prompt)
        return res["data"]
    except Exception as e:
        logger.error(f"Concept generation failed: {str(e)}")
        # Ultimate fallback if LM Studio is really struggling
        return {
            "concepts": [
                {
                    "title": f"A {genre} Tale",
                    "blurb": f"A mysterious journey in the world of {subgenre or genre}.",
                    "tone_tags": ["mysterious", "cinematic", "local"]
                },
                {
                    "title": f"Shadows of {genre}",
                    "blurb": f"An unexpected turn of events in a {tone or 'dark'} setting.",
                    "tone_tags": ["dark", "atmospheric", "engaging"]
                },
                {
                    "title": f"The {genre} Chronicles",
                    "blurb": f"Exploring the depths of {premise or 'the unknown'}.",
                    "tone_tags": ["epic", "narrative", "detailed"]
                }
            ]
        }

async def handle_build_story_bible(job):
    story_id = job['storyId']
    payload = json.loads(job['payloadJson'])
    concept = payload.get('concept', {})
    planned_parts = payload.get('plannedParts', 3)
    
    # Check if story belongs to a series
    series_info = ""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT s.seriesId, ser.title, ser.overarchingPlotJson FROM Story s LEFT JOIN Series ser ON s.seriesId = ser.id WHERE s.id = ?", (story_id,))
        row = cursor.fetchone()
        if row and row['seriesId']:
            series_info = f"\nSeries Title: {row['title']}\nOverarching Series Plot: {row['overarchingPlotJson']}"

    prompt = f"""
    Create a highly concise Story Book Guide for a new story.{series_info}
    Title: {concept.get('title')}
    Premise: {concept.get('blurb')}
    Planned Parts: {planned_parts}
    
    [AUTHORING GOALS]
    - If part of a series, ensure this book contributes to the overarching plot.
    - Define clear narrative goals for this specific volume.
    
    Return a JSON object with:
    - world_rules: 3 short key rules (max 15 words each)
    - plot_arc: Short summary of the {planned_parts} parts (max 2 sentences per part)
    - ending_plan: Concise conclusion (max 1 sentence)
    - characters: 2-3 main characters (name, role, traits)
    """
    
    res = await lm_studio.generate_json(prompt)
    bible_data = res["data"]
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        # Save Story Bible
        cursor.execute(
            "INSERT INTO StoryBible (id, storyId, worldRulesJson, plotArcJson, endingPlanJson, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (str(Path(story_id).name + "_bible"), story_id, json.dumps(bible_data['world_rules']), json.dumps(bible_data['plot_arc']), json.dumps(bible_data['ending_plan']))
        )
        # Save Characters
        for char in bible_data.get('characters', []):
            cursor.execute(
                "INSERT INTO Character (id, storyId, name, role, traitsJson, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (str(Path(story_id).name + "_" + char['name']), story_id, char['name'], char['role'], json.dumps(char.get('traits', [])))
            )
        # Queue first part
        cursor.execute(
            "INSERT INTO Job (id, storyId, partNumber, jobType, status, priority, createdAt) VALUES (?, ?, ?, ?, 'queued', ?, CURRENT_TIMESTAMP)",
            (str(Path(story_id).name + "_part1"), story_id, 1, "generate_part", 8)
        )
        conn.commit()
    
    return {"status": "bible_created"}

async def handle_generate_part(job):
    story_id = job['storyId']
    part_num = job['partNumber']
    
    # Get context
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Story WHERE id = ?", (story_id,))
        story = cursor.fetchone()
        cursor.execute("SELECT * FROM StoryBible WHERE storyId = ?", (story_id,))
        bible = cursor.fetchone()
        cursor.execute("SELECT name, role, traitsJson FROM Character WHERE storyId = ?", (story_id,))
        characters = cursor.fetchall()
        
        # Get all previous summaries for high-level continuity - LIMIT TO LAST 5
        cursor.execute("SELECT partNumber, summary FROM StoryPart WHERE storyId = ? AND partNumber < ? ORDER BY partNumber DESC LIMIT 5", (story_id, part_num))
        prev_parts_meta = cursor.fetchall()
        # Reverse to get them in ascending order
        prev_parts_meta.reverse()
        
        # Get the EXACT previous part for seamless narrative flow
        prev_part_full = None
        if part_num > 1:
            cursor.execute("SELECT fullText, continuityNotesJson FROM StoryPart WHERE storyId = ? AND partNumber = ?", (story_id, part_num - 1))
            prev_part_full = cursor.fetchone()
    
    summaries = [f"Part {p['partNumber']}: {p['summary']}" for p in prev_parts_meta]
    char_details = [f"{c['name']} ({c['role']}): {c['traitsJson']}" for c in characters]
    char_names = [c['name'] for c in characters]
    
    # Reduced context size to avoid LM Studio context overflow
    last_text_context = prev_part_full['fullText'][-800:] if prev_part_full and prev_part_full['fullText'] else "This is the start of the story."
    last_continuity_notes = prev_part_full['continuityNotesJson'] if prev_part_full and prev_part_full['continuityNotesJson'] else "{}"

    # Debug print to check the types of variables being used in f-string
    logger.info(f"F-string context: part_num={part_num}, title_type={type(story['title'])}")

    prompt = f"""
    Generate a long, cinematic, and professional Part {int(part_num)} of the story "{str(story['title'])}".
    
    [AUTHORING DIRECTIVE]
    - Use advanced narrative techniques: Show, Don't Tell.
    - Vary sentence structure for rhythmic prose.
    - Employ internal monologues and sensory details (smell, touch, atmosphere).
    - Maintain strict character voices and consistent tone.
    - [GOAL-DRIVEN DEVELOPMENT]: Ensure every part moves the plot toward its volume goal or the series' overarching mystery.
    - If this is an 'Unending' story (planned_parts > 50) or part of a series, introduce branching subplots, foreshadowing, and slow-burn character growth.
    
    Story Context (History & World):
    World Rules: {str(bible['worldRulesJson'])}
    Plot Arc: {str(bible['plotArcJson'])}
    Previous Summaries: {json.dumps(summaries)}
    
    Characters (Maintain Consistency):
    {json.dumps(char_details)}
    
    Immediate Narrative Context (Flow from here):
    "{last_text_context}"
    
    Active Continuity State:
    {last_continuity_notes}
    
    Requirements:
    - title: A compelling and evocative title.
    - summary: A punchy, 1-sentence hook of this part.
    - full_text: Write an immersive, high-quality narrative (approx 600-900 words). 
      CRITICAL: Ensure the tone, character voices, and plot flow SEAMLESSLY from the 'Immediate Narrative Context'.
    - segments: YOU MUST SPLIT THE ENTIRE 'full_text' INTO SMALLER AUDIO SEGMENTS.
      Each segment should be {{"type": "narration"|"dialogue", "speaker": "Name", "text": "..."}}.
      The concatenation of all segment 'text' fields MUST EQUAL the 'full_text' exactly.
      CRITICAL DEDUPLICATION RULES:
      1. DO NOT REPEAT sentences between segments.
      2. If a character speaks, the 'dialogue' segment should contain ONLY their spoken words.
      3. The surrounding 'narration' segments should NOT repeat what is in the 'dialogue' segment.
      4. For 'dialogue' segments, use one of the names from {json.dumps(char_names)}.
      5. For 'narration' segments, leave 'speaker' as null or "Narrator".
    - continuity_notes: A detailed state-tracking object (character locations, active items, unresolved cliffhangers, emotional states, current subplots).
    - visual_cues: Array of 6-8 cinematic scene descriptions for AI image generation.
    - music_mood: A detailed description for the background score (e.g., 'haunting cello with low synth drone').
    - background_ambiance: Environmental soundscape details.
    
    CRITICAL: Return ONLY valid JSON.
    """
    
    res = await lm_studio.generate_json(prompt)
    part_data = res["data"]
    node_url = res.get("node", "local")
    
    # POST-PROCESSING: Clean and Deduplicate Segments
    # Ensure segments are trimmed and don't repeat content due to LLM formatting
    raw_segments = part_data.get('segments', [])
    cleaned_segments = []
    seen_text = set()
    
    for seg in raw_segments:
        text = seg.get('text', '').strip()
        if not text:
            continue
            
        # Basic normalization for deduplication check
        norm_text = text.lower().replace('"', '').replace("'", '').strip()
        
        # If we see exact duplicate text within the same part, skip it
        if norm_text in seen_text:
            logger.warning(f"DEDUPLICATION: Skipping repeated segment text: '{text[:50]}...'")
            continue
            
        seen_text.add(norm_text)
        seg['text'] = text # Use the original trimmed text
        cleaned_segments.append(seg)
    
    # Update part_data with cleaned segments
    part_data['segments'] = cleaned_segments

    with db.get_connection() as conn:
        cursor = conn.cursor()
        # IMMEDIATELY SAVE THE PART AND SEGMENTS
        part_id = str(Path(story_id).name + "_p" + str(part_num))
        cursor.execute(
            "INSERT INTO StoryPart (id, storyId, partNumber, title, summary, fullText, continuityNotesJson, status, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?, ?, 'complete', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (part_id, story_id, part_num, part_data['title'], part_data['summary'], part_data['full_text'], json.dumps(part_data.get('continuity_notes', {})))
        )
        
        for i, seg in enumerate(part_data.get('segments', [])):
            cursor.execute(
                "INSERT INTO StoryPartSegment (id, storyPartId, segmentOrder, type, speakerName, text, createdAt) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (part_id + "_s" + str(i), part_id, i, seg['type'], seg.get('speaker'), seg['text'])
            )
        
        # Queue Audio Job with music mood
        cursor.execute(
            "INSERT INTO Job (id, storyId, partNumber, jobType, status, priority, payloadJson, createdAt) VALUES (?, ?, ?, ?, 'queued', ?, ?, CURRENT_TIMESTAMP)",
            (part_id + "_audio", story_id, part_num, "generate_part_audio", 7, json.dumps({"music_mood": part_data.get('music_mood', 'cinematic ambiance')}))
        )

        # Queue Image Jobs
        visual_cues = part_data.get('visual_cues', [])
        if not visual_cues:
            # Fallback if no visual cues generated
            visual_cues = [{"keywords": "cinematic atmosphere", "timestamp_percent": 0}]
            
        for i, cue in enumerate(visual_cues):
            cursor.execute(
                "INSERT INTO Job (id, storyId, partNumber, jobType, status, priority, payloadJson, createdAt) VALUES (?, ?, ?, ?, 'queued', ?, ?, CURRENT_TIMESTAMP)",
                (part_id + "_img_" + str(i), story_id, part_num, "generate_part_images", 7, json.dumps({
                    "keywords": cue['keywords'], 
                    "timestamp_percent": cue['timestamp_percent'],
                    "mood": cue.get('mood', 'cinematic'),
                    "focal_point": cue.get('focal_point', 'center')
                }))
            )
        
        # Queue next part if needed
        if part_num < story['plannedParts']:
            cursor.execute(
                "INSERT INTO Job (id, storyId, partNumber, jobType, status, priority, createdAt) VALUES (?, ?, ?, ?, 'queued', ?, CURRENT_TIMESTAMP)",
                (str(Path(story_id).name + "_part" + str(part_num+1)), story_id, part_num + 1, "generate_part", 6)
            )
            
        conn.commit()
    
    return {
        "status": "part_generated", 
        "part_number": part_num,
        "node": node_url
    }

# Advanced Voice Matching with Token Overlap
def match_voice(speaker_raw, char_voice_map, narrator_voice, narrator_speed):
    speaker_norm = (speaker_raw or "").strip().lower()
    if not speaker_norm:
        return narrator_voice, narrator_speed, "Narration (Default)"

    # 1. Exact Match
    if speaker_norm in char_voice_map:
        return char_voice_map[speaker_norm]['voiceId'], char_voice_map[speaker_norm]['voiceSpeed'], f"Exact Match ('{speaker_raw}')"

    # 2. Advanced Fuzzy Match (Substring/Word overlap)
    speaker_words = set(speaker_norm.split())
    for char_name_norm, char_data in char_voice_map.items():
        char_words = set(char_name_norm.split())
        # Check if names are subsets OR if they share significant words
        if (char_name_norm in speaker_norm or speaker_norm in char_name_norm or 
            len(speaker_words.intersection(char_words)) > 0):
            return char_data['voiceId'], char_data['voiceSpeed'], f"Fuzzy Match ('{speaker_raw}' -> '{char_name_norm}')"

    return narrator_voice, narrator_speed, f"UNKNOWN SPEAKER ('{speaker_raw}') - Fallback to Narrator"

async def handle_generate_part_audio(job):
    story_id = job['storyId']
    part_num = job['partNumber']
    payload = json.loads(job['payloadJson'] or '{}')
    music_mood = payload.get('music_mood')
    
    settings = db.get_settings()
    default_voice = settings.get("kokoroVoiceId") or "af_heart"

    # Define a list of available Kokoro voices for characters
    # These are commonly supported voices
    available_voices = [
        "af_bella", "af_nicole", "af_sarah", "af_sky",
        "am_adam", "am_fenrir", "am_puck", "am_michael"
    ]

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM StoryPart WHERE storyId = ? AND partNumber = ?", (story_id, part_num))
        part = cursor.fetchone()
        cursor.execute("SELECT * FROM StoryPartSegment WHERE storyPartId = ? ORDER BY segmentOrder ASC", (part['id'],))
        segments = cursor.fetchall()
        cursor.execute("SELECT narratorVoiceId, narratorVoiceSpeed FROM Story WHERE id = ?", (story_id,))
        story_row = cursor.fetchone()
        
        # Get characters to assign voices
        cursor.execute("SELECT name, voiceId, voiceSpeed FROM Character WHERE storyId = ?", (story_id,))
        characters = cursor.fetchall()
        
        # Ensure we have characters. If not, maybe create some from segments if they appear?
        if not characters:
            logger.warning(f"No characters found in DB for story {story_id}. Checking segments for potential speakers...")
            speakers = set(s['speakerName'] for s in segments if s['type'] == 'dialogue' and s['speakerName'])
            for name in speakers:
                cursor.execute(
                    "INSERT INTO Character (id, storyId, name, role, voiceSpeed, createdAt, updatedAt) VALUES (?, ?, ?, ?, 1.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (f"{story_id}_{name}", story_id, name, "Secondary Character")
                )
            conn.commit()
            cursor.execute("SELECT name, voiceId, voiceSpeed FROM Character WHERE storyId = ?", (story_id,))
            characters = cursor.fetchall()

        # Use normalized (lowercase) names for mapping
        char_voice_map = {c['name'].lower().strip(): {"voiceId": c['voiceId'], "voiceSpeed": c['voiceSpeed']} for c in characters}
        
        # Proactively check segments for any speakers NOT in our character map
        unknown_speakers = set()
        for seg in segments:
            if seg['type'] == 'dialogue' and seg['speakerName']:
                speaker_norm = seg['speakerName'].lower().strip()
                if speaker_norm not in char_voice_map:
                    # Check fuzzy match before declaring unknown
                    found_fuzzy = False
                    for char_name_norm in char_voice_map.keys():
                        if char_name_norm in speaker_norm or speaker_norm in char_name_norm:
                            found_fuzzy = True
                            break
                    if not found_fuzzy:
                        unknown_speakers.add(seg['speakerName'].strip())

        if unknown_speakers:
            logger.info(f"AUDIT: Found {len(unknown_speakers)} unknown speakers in segments. Adding to Character table: {unknown_speakers}")
            for name in unknown_speakers:
                char_id = f"{story_id}_{name.replace(' ', '_')}"
                cursor.execute(
                    "INSERT OR IGNORE INTO Character (id, storyId, name, role, voiceSpeed, createdAt, updatedAt) VALUES (?, ?, ?, ?, 1.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (char_id, story_id, name, "Supporting Character")
                )
            conn.commit()
            # Refresh characters and map
            cursor.execute("SELECT name, voiceId, voiceSpeed FROM Character WHERE storyId = ?", (story_id,))
            characters = cursor.fetchall()
            char_voice_map = {c['name'].lower().strip(): {"voiceId": c['voiceId'], "voiceSpeed": c['voiceSpeed']} for c in characters}

        # Log existing mapping for debug
        logger.info(f"AUDIT: Story {story_id} Character Voice Mapping: {char_voice_map}")
        
        # Assign voices to characters if they don't have one
        assigned_voices = set(v['voiceId'] for v in char_voice_map.values() if v['voiceId'])
        narr_voice = story_row['narratorVoiceId'] or default_voice
        narr_speed = story_row['narratorVoiceSpeed'] or 1.0
        assigned_voices.add(narr_voice)
        
        for char in characters:
            name_norm = char['name'].lower().strip()
            if not char_voice_map[name_norm]['voiceId']:
                # Pick a voice that isn't the narrator voice and ideally not already used
                available_for_char = [v for v in available_voices if v != narr_voice]
                unused_voices = [v for v in available_for_char if v not in assigned_voices]
                
                chosen_voice = unused_voices[0] if unused_voices else (available_for_char[0] if available_for_char else default_voice)
                char_voice_map[name_norm]['voiceId'] = chosen_voice
                assigned_voices.add(chosen_voice)
                
                logger.info(f"AUDIT: Assigning NEW voice {chosen_voice} to character {char['name']}")
                # Update character in DB
                cursor.execute("UPDATE Character SET voiceId = ? WHERE storyId = ? AND name = ?", (chosen_voice, story_id, char['name']))
        conn.commit()
        
    narrator_voice = story_row['narratorVoiceId'] or default_voice
    narrator_speed = story_row['narratorVoiceSpeed'] or 1.0
    
    # Correct path for local dev - public/data/...
    output_dir = Path(f"public/data/stories/{story_id}/parts/{part_num}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Process segments in parallel for faster TTS
    async def synthesize_segment(seg):
        seg_order = seg['segmentOrder']
        # Switching to .wav for faster raw synthesis, but converting to .mp3 immediately
        wav_path_disk = output_dir / f"seg_{seg_order}.wav"
        mp3_path_disk = output_dir / f"seg_{seg_order}.mp3"
        seg_path_web = f"/data/stories/{story_id}/parts/{part_num}/seg_{seg_order}.mp3"
        
        voice, speed, match_log = match_voice(
            seg['speakerName'] if seg['type'] == 'dialogue' else None,
            char_voice_map,
            narrator_voice,
            narrator_speed
        )
        
        logger.info(f"AUDIT | Segment {seg_order} | {match_log} | Voice: {voice} | Speed: {speed}")
            
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE StoryPartSegment SET voiceId = ?, audioPath = ? WHERE id = ?", 
                (voice, seg_path_web, seg['id'])
            )
            conn.commit()

        # 1. Synthesize to RAW WAV
        await kokoro.synthesize(seg['text'], voice, str(wav_path_disk), speed=speed)
        
        # 2. Convert to high-quality MP3 immediately
        ffmpeg.convert_to_mp3(str(wav_path_disk), str(mp3_path_disk))
        
        # 3. Cleanup WAV
        if os.path.exists(wav_path_disk):
            os.remove(wav_path_disk)
            
        return str(mp3_path_disk)

    # Launch all synthesis tasks simultaneously
    logger.info(f"Starting parallel synthesis for {len(segments)} segments...")
    segment_files = await asyncio.gather(*[synthesize_segment(seg) for seg in segments])
    
    # After parallel synthesis, we need to calculate and update timing
    # ffmpeg.stitch_audio uses the same order as segment_files
    current_ms = 0
    with db.get_connection() as conn:
        cursor = conn.cursor()
        for i, seg in enumerate(segments):
            seg_path = segment_files[i]
            duration_s = ffmpeg.get_duration(seg_path)
            # IMPORTANT: Round duration_s up to the nearest 0.1s to prevent gaps
            duration_ms = int((duration_s + 0.05) * 1000)
            
            start_ms = current_ms
            end_ms = current_ms + duration_ms
            
            cursor.execute(
                "UPDATE StoryPartSegment SET startMs = ?, endMs = ? WHERE id = ?",
                (start_ms, end_ms, seg['id'])
            )
            current_ms = end_ms
        conn.commit()

    speech_path = output_dir / "speech.mp3"
    # Merging the high-quality .wav segments into a single .mp3 for distribution/car playback
    ffmpeg.stitch_audio(segment_files, str(speech_path))
    
    # Background Music Selection (Basic implementation - can be expanded)
    # We'll look for music files in public/assets/music
    music_dir = Path("public/assets/music")
    music_file = None
    if music_mood and music_dir.exists():
        # Try to find a file that matches the mood keywords
        music_files = list(music_dir.glob("*.mp3"))
        if music_files:
            # For now, just pick the first one or one matching keywords if available
            # In a real app, you might have a map or search logic
            music_file = music_files[0] 

    merged_path = output_dir / "merged.mp3"
    if music_file:
        ffmpeg.add_background_music(speech_path, music_file, str(merged_path))
    else:
        # Fallback to just speech if no music found
        import shutil
        shutil.copy2(speech_path, merged_path)
    
    # Get duration using ffprobe
    duration_seconds = int(ffmpeg.get_duration(merged_path))
    if duration_seconds == 0:
        # Fallback estimation if ffprobe fails: ~15 chars per second
        total_chars = sum(len(seg['text']) for seg in segments)
        duration_seconds = max(1, total_chars // 15)

    # Serve from web path - relative to public/
    web_path = f"/data/stories/{story_id}/parts/{part_num}/merged.mp3"
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE StoryPart SET mergedAudioPath = ?, audioStatus = 'complete', durationSeconds = ? WHERE id = ?",
            (web_path, duration_seconds, part['id'])
        )
        conn.commit()
        
    return {"status": "audio_generated", "path": web_path}

async def handle_generate_part_images(job):
    story_id = job['storyId']
    part_num = job['partNumber']
    payload = json.loads(job['payloadJson'])
    keywords = payload.get('keywords', 'cinematic atmosphere')
    timestamp_percent = payload.get('timestamp_percent', 0)
    
    # Get part info for timing
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, durationSeconds FROM StoryPart WHERE storyId = ? AND partNumber = ?", (story_id, part_num))
        part = cursor.fetchone()
    
    display_time_ms = 0
    if part and part['durationSeconds']:
        display_time_ms = int((timestamp_percent / 100.0) * part['durationSeconds'] * 1000)

    output_dir = Path(f"public/data/stories/{story_id}/parts/{part_num}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. CHECK LOCAL CACHE FIRST
    # Sanitize keywords for filename
    safe_keywords = "".join([c if c.isalnum() else "_" for c in keywords.lower()]).strip("_")
    filename = f"cached_{safe_keywords}.jpg"
    cache_dir = Path("public/data/cache/images")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / filename
    
    web_path = None
    img_path = None

    if cache_path.exists():
        logger.info(f"CACHE HIT: Reusing existing image for '{keywords}'")
        import shutil
        story_img_path = output_dir / f"scene_{str(job['id']).split('_')[-1]}.jpg"
        shutil.copy2(cache_path, story_img_path)
        web_path = f"/data/stories/{story_id}/parts/{part_num}/{story_img_path.name}"
        img_path = str(story_img_path)
    else:
        # 2. DOWNLOAD FROM UNSPLASH
        img_id = str(job['id']).split('_')[-1]
        filename_unique = f"scene_{img_id}.jpg"
        output_path = output_dir / filename_unique
        
        img_path = await unsplash.search_and_download(keywords, str(output_path))
        if img_path:
            # Save to cache for future reuse
            import shutil
            shutil.copy2(img_path, cache_path)
            web_path = f"/data/stories/{story_id}/parts/{part_num}/{filename_unique}"

    # 3. FALLBACK: If download fails, try to reuse an existing image for this story first
    if not img_path:
        logger.warning(f"Image download failed for '{keywords}'. Searching for fallback image...")
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # Try to find any image from the same story first
            cursor.execute("SELECT filePath FROM Image WHERE storyId = ? ORDER BY createdAt DESC LIMIT 1", (story_id,))
            row = cursor.fetchone()
            if not row:
                # If no image for this story, find any image from any story
                cursor.execute("SELECT filePath FROM Image ORDER BY createdAt DESC LIMIT 1")
                row = cursor.fetchone()
            
            if row:
                web_path = row['filePath']
                logger.info(f"Using fallback image: {web_path}")
                img_path = "fallback" 
            else:
                return {"status": "image_failed"}

    if img_path:
        # web_path was already set in the cache hit or download success blocks
        # Only fallback needs special handling for the database entry
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # 1. Save to Image table
            cursor.execute(
                "INSERT INTO Image (id, storyId, storyPartId, imageType, promptText, filePath, displayTimeMs, createdAt) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (str(job['id']), story_id, part['id'] if part else None, "scene", keywords, web_path, display_time_ms)
            )
            # 2. Update StoryPart imageStatus
            cursor.execute(
                "UPDATE StoryPart SET imageStatus = 'complete' WHERE storyId = ? AND partNumber = ?",
                (story_id, part_num)
            )
            # 3. If it's part 1 and first image, set as cover
            cursor.execute("SELECT coverImagePath FROM Story WHERE id = ?", (story_id,))
            story_row = cursor.fetchone()
            if story_row and not story_row['coverImagePath'] and part_num == 1:
                cursor.execute("UPDATE Story SET coverImagePath = ? WHERE id = ?", (web_path, story_id))
            
            conn.commit()
        return {"status": "image_generated", "path": web_path}
    
    return {"status": "image_failed"}

async def handle_stitch_full_story(job):
    story_id = job['storyId']
    output_dir = Path(f"public/data/stories/{story_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT mergedAudioPath FROM StoryPart WHERE storyId = ? AND audioStatus = 'complete' ORDER BY partNumber ASC", (story_id,))
        rows = cursor.fetchall()
    
    if not rows:
        return {"status": "error", "message": "No complete audio parts found to stitch."}
        
    audio_files = [str(Path("public") / row['mergedAudioPath'].lstrip('/')) for row in rows]
    full_audio_path = output_dir / "full_audiobook.mp3"
    
    logger.info(f"STITCHING FULL STORY: {story_id} ({len(audio_files)} parts)")
    ffmpeg.stitch_audio(audio_files, str(full_audio_path))
    
    web_path = f"/data/stories/{story_id}/full_audiobook.mp3"
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE Story SET fullAudioPath = ? WHERE id = ?", (web_path, story_id))
        conn.commit()
        
    return {"status": "complete", "path": web_path}

async def handle_export_video(job):
    story_id = job['storyId']
    payload = json.loads(job['payloadJson']) if job['payloadJson'] else {}
    
    aspect_ratio = payload.get('aspectRatio', '16:9') # '16:9' or '9:16'
    resolution = payload.get('resolution', '1080p') # '720p' or '1080p'
    
    # Calculate target dimensions
    if aspect_ratio == '9:16':
        width = 720 if resolution == '720p' else 1080
        height = 1280 if resolution == '720p' else 1920
    else: # 16:9
        width = 1280 if resolution == '720p' else 1920
        height = 720 if resolution == '720p' else 1080

    output_dir = Path(f"public/data/stories/{story_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        # 1. Get full audiobook path
        cursor.execute("SELECT fullAudioPath FROM Story WHERE id = ?", (story_id,))
        story_row = cursor.fetchone()
        if not story_row or not story_row['fullAudioPath']:
            return {"status": "error", "message": "Full audiobook not found. Please stitch first."}
        
        audio_path = Path("public") / story_row['fullAudioPath'].lstrip('/')
        if not audio_path.exists():
            return {"status": "error", "message": f"Audio file not found at {audio_path}"}

        # 2. Get all segments with images and their durations
        # We need (image_path, duration_ms)
        # Note: Some segments might not have images, we'll use the last available image
        cursor.execute("""
            SELECT s.id, s.startMs, s.endMs, i.filePath as imagePath
            FROM StoryPartSegment s
            LEFT JOIN Image i ON s.id = i.segmentId
            WHERE s.storyId = ?
            ORDER BY s.startMs ASC
        """, (story_id,))
        segments = cursor.fetchall()

    if not segments:
        return {"status": "error", "message": "No segments found for this story."}

    image_durations = []
    last_valid_image = None
    
    # First, find the first valid image to use as a starter if needed
    for seg in segments:
        if seg['imagePath']:
            last_valid_image = Path("public") / seg['imagePath'].lstrip('/')
            break
            
    if not last_valid_image:
        return {"status": "error", "message": "No images found for this story. Cannot create video."}

    for seg in segments:
        duration_ms = (seg['endMs'] or 0) - (seg['startMs'] or 0)
        if duration_ms <= 0: continue
        
        current_image = Path("public") / seg['imagePath'].lstrip('/') if seg['imagePath'] else last_valid_image
        if not current_image.exists():
            current_image = last_valid_image
        else:
            last_valid_image = current_image
            
        image_durations.append((str(current_image), duration_ms))

    # Filename includes resolution and aspect ratio to prevent overwriting different versions
    res_tag = "720p" if resolution == "720p" else "1080p"
    ar_tag = "portrait" if aspect_ratio == "9:16" else "landscape"
    video_filename = f"story_{ar_tag}_{res_tag}.mp4"
    video_path = output_dir / video_filename
    
    logger.info(f"EXPORTING VIDEO: {story_id} ({width}x{height}, {len(image_durations)} scenes)")
    
    try:
        ffmpeg.create_slideshow_video(image_durations, str(audio_path), str(video_path), width=width, height=height)
        web_path = f"/data/stories/{story_id}/{video_filename}"
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE Story SET videoPath = ? WHERE id = ?", (web_path, story_id))
            conn.commit()
            
        return {"status": "complete", "path": web_path}
    except Exception as e:
        logger.error(f"Video export failed: {str(e)}")
        return {"status": "error", "message": str(e)}

async def heartbeat_loop():
    """Separate loop to update heartbeat every 5 seconds, regardless of job processing."""
    while True:
        try:
            db.update_heartbeat()
        except Exception as e:
            logger.error(f"Heartbeat update failed: {str(e)}")
        await asyncio.sleep(5)

async def process_job(job):
    job_id = job['id']
    with db.get_connection() as conn:
        cursor = conn.cursor()
        # Mark as running
        cursor.execute(
            "UPDATE Job SET status = 'running', startedAt = CURRENT_TIMESTAMP, attempts = attempts + 1 WHERE id = ?",
            (job_id,)
        )
        conn.commit()
        
        logger.info(f"Starting job {job_id} ({job['jobType']})")
        
        try:
            result = None
            if job['jobType'] == 'generate_concepts':
                result = await handle_generate_concepts(job)
            elif job['jobType'] == 'build_story_bible':
                result = await handle_build_story_bible(job)
            elif job['jobType'] == 'generate_part':
                result = await handle_generate_part(job)
            elif job['jobType'] == 'generate_part_audio':
                result = await handle_generate_part_audio(job)
            elif job['jobType'] == 'generate_part_images':
                result = await handle_generate_part_images(job)
            elif job['jobType'] == 'stitch_full_story':
                result = await handle_stitch_full_story(job)
            elif job['jobType'] == 'export_video':
                result = await handle_export_video(job)
            
            # Mark as done
            cursor.execute(
                "UPDATE Job SET status = 'done', finishedAt = CURRENT_TIMESTAMP, resultJson = ? WHERE id = ?",
                (json.dumps(result) if result else None, job_id)
            )
            
            # If this was build_story_bible or generate_part, update story status
            if job['jobType'] in ['build_story_bible', 'generate_part']:
                cursor.execute(
                    "UPDATE Story SET status = 'generating' WHERE id = ?",
                    (job['storyId'],)
                )
            
            conn.commit()
            logger.info(f"Finished job {job_id}")

            # Check if the entire story is complete
            try:
                with db.get_connection() as conn2:
                    cursor2 = conn2.cursor()
                    story_id = job['storyId']
                    
                    # Check if any jobs are still pending/running for this story
                    cursor2.execute(
                        "SELECT COUNT(*) as count FROM Job WHERE storyId = ? AND status IN ('queued', 'running', 'pending')", 
                        (story_id,)
                    )
                    pending_jobs = cursor2.fetchone()['count']
                    
                    if pending_jobs == 0:
                        # Check if all planned parts exist
                        cursor2.execute("SELECT plannedParts FROM Story WHERE id = ?", (story_id,))
                        story_row = cursor2.fetchone()
                        
                        cursor2.execute("SELECT COUNT(*) as count FROM StoryPart WHERE storyId = ?", (story_id,))
                        actual_parts = cursor2.fetchone()['count']
                        
                        if story_row and actual_parts >= story_row['plannedParts']:
                            logger.info(f"STORY COMPLETE: All {actual_parts} parts generated for {story_id}. Queueing full audiobook stitch...")
                            cursor2.execute("UPDATE Story SET status = 'complete' WHERE id = ?", (story_id,))
                            
                            # Queue the full stitch job
                            cursor2.execute(
                                "INSERT INTO Job (id, storyId, jobType, status, priority, createdAt) VALUES (?, ?, ?, 'queued', ?, CURRENT_TIMESTAMP)",
                                (f"{story_id}_full_stitch", story_id, "stitch_full_story", 9)
                            )
                            
                            # SERIES LOGIC: Queue next book if applicable
                            cursor2.execute("SELECT seriesId, seriesOrder, genre, tonePack FROM Story WHERE id = ?", (story_id,))
                            s_row = cursor2.fetchone()
                            if s_row and s_row['seriesId']:
                                cursor2.execute("SELECT title, description FROM Series WHERE id = ?", (s_row['seriesId'],))
                                ser_row = cursor2.fetchone()
                                
                                next_order = (s_row['seriesOrder'] or 1) + 1
                                # If trilogy, stop at 3. If saga, keep going.
                                # For now, we'll assume anything with a seriesId wants to continue if not finished.
                                if next_order <= 3 or "saga" in (ser_row['description'] or "").lower():
                                    import uuid
                                    next_story_id = str(uuid.uuid4())
                                    next_title = f"{ser_row['title']} - Volume {next_order}"
                                    
                                    logger.info(f"SERIES AUTO-QUEUE: Creating next volume '{next_title}'...")
                                    
                                    cursor2.execute(
                                        "INSERT INTO Story (id, title, genre, tonePack, description, plannedParts, status, seriesId, seriesOrder, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                                        (next_story_id, next_title, s_row['genre'], s_row['tonePack'], ser_row['description'], story_row['plannedParts'], s_row['seriesId'], next_order)
                                    )
                                    
                                    # Queue concepts for the next book
                                    payload = {
                                        "concept": {
                                            "title": next_title,
                                            "blurb": f"The continuation of the series {ser_row['title']}. Volume {next_order}."
                                        },
                                        "plannedParts": story_row['plannedParts']
                                    }
                                    cursor2.execute(
                                        "INSERT INTO Job (id, storyId, jobType, status, priority, payloadJson, createdAt) VALUES (?, ?, ?, 'queued', ?, ?, CURRENT_TIMESTAMP)",
                                        (f"{next_story_id}_concepts", next_story_id, "generate_concepts", 10, json.dumps(payload))
                                    )
                            
                            conn2.commit()
            except Exception as e:
                logger.error(f"Error checking story completion: {str(e)}")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {str(e)}")
            cursor.execute(
                "UPDATE Job SET status = 'failed', errorText = ?, finishedAt = CURRENT_TIMESTAMP WHERE id = ?",
                (str(e), job_id)
            )
            conn.commit()

async def run_worker():
    # 1. Startup: Reset stuck jobs
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE Job SET status = 'queued' WHERE status = 'running'")
            count = cursor.rowcount
            if count > 0:
                logger.info(f"Reset {count} stuck jobs to 'queued' status.")
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to reset stuck jobs: {str(e)}")

    # Worker state
    semaphore = asyncio.Semaphore(4) # Allow up to 4 parallel jobs
    
    async def worker_loop():
        logger.info("Worker started, polling for jobs...")
        while True:
            async with semaphore:
                try:
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT * FROM Job WHERE status = 'queued' ORDER BY priority DESC, createdAt ASC LIMIT 1"
                        )
                        job = cursor.fetchone()
                        
                    if job:
                        asyncio.create_task(process_job_safe(job))
                    else:
                        await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Worker Loop Error: {str(e)}")
                    await asyncio.sleep(5)

    async def process_job_safe(job):
        try:
            await process_job(job)
        except Exception as e:
            logger.error(f"Critical error processing job {job['id']}: {str(e)}")

    # Start the heartbeat and worker loop
    await asyncio.gather(
        heartbeat_loop(),
        worker_loop()
    )

if __name__ == "__main__":
    lock_data = acquire_lock()
    try:
        asyncio.run(run_worker())
    finally:
        release_lock(lock_data)
