import sqlite3
import json
import os
from pathlib import Path

def retry_and_complete():
    try:
        conn = sqlite3.connect('dev.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 1. Locate the story
        cursor.execute("SELECT id, title, plannedParts FROM Story WHERE title LIKE '%invisible%'")
        story = cursor.fetchone()
        if not story:
            print("Story 'i woke up invisible' not found.")
            return
            
        story_id = story['id']
        print(f"Working on Story: {story['title']} (ID: {story_id})")
        
        # 2. Reset failed jobs to 'queued'
        cursor.execute("UPDATE Job SET status = 'queued', errorText = NULL, attempts = 0 WHERE storyId = ? AND status = 'failed'", (story_id,))
        count = cursor.rowcount
        print(f"Reset {count} failed jobs to 'queued'.")
        
        # 3. Check for missing parts and queue them if needed
        cursor.execute("SELECT MAX(partNumber) as last_part FROM StoryPart WHERE storyId = ?", (story_id,))
        last_part = cursor.fetchone()['last_part'] or 0
        print(f"Last generated part: {last_part} / {story['plannedParts']}")
        
        if last_part < story['plannedParts']:
            next_part = last_part + 1
            job_id = f"{story_id}_part{next_part}"
            # Check if job already exists
            cursor.execute("SELECT id FROM Job WHERE id = ?", (job_id,))
            if not cursor.fetchone():
                print(f"Queueing job for missing Part {next_part}...")
                cursor.execute(
                    "INSERT INTO Job (id, storyId, partNumber, jobType, status, priority, createdAt) VALUES (?, ?, ?, ?, 'queued', ?, CURRENT_TIMESTAMP)",
                    (job_id, story_id, next_part, "generate_part", 6)
                )
        
        # 4. Final check for completion logic
        cursor.execute("SELECT COUNT(*) as count FROM Job WHERE storyId = ? AND status IN ('queued', 'running')", (story_id,))
        pending = cursor.fetchone()['count']
        
        if pending == 0 and last_part >= story['plannedParts']:
            print("No pending jobs and all parts generated. Marking story as 'complete'...")
            cursor.execute("UPDATE Story SET status = 'complete' WHERE id = ?", (story_id,))
        else:
            print(f"There are {pending} pending/running jobs. Story status remains 'generating'.")
            
        conn.commit()
        conn.close()
        print("Maintenance complete.")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    retry_and_complete()
