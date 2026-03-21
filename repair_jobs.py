import sqlite3
import os
from pathlib import Path

db_path = str(Path("E:\Dev\Fantasee1\dev.db").resolve())
print(f"Repairing database at: {db_path}")

try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. Reset all failed jobs to queued
    cursor.execute("UPDATE Job SET status = 'queued', attempts = 0 WHERE status = 'failed'")
    print(f"Reset {cursor.rowcount} failed jobs to 'queued'.")
    
    # 2. Reset all running jobs to queued (in case they are stuck)
    cursor.execute("UPDATE Job SET status = 'queued' WHERE status = 'running'")
    print(f"Reset {cursor.rowcount} stuck 'running' jobs to 'queued'.")
    
    # 3. For any story marked 'generating' that has NO active or queued jobs, queue the next part
    cursor.execute("SELECT id, title, plannedParts FROM Story WHERE status = 'generating'")
    generating_stories = cursor.fetchall()
    
    for story in generating_stories:
        story_id = story['id']
        # Check if there are any pending/running jobs for this story
        cursor.execute("SELECT COUNT(*) as count FROM Job WHERE storyId = ? AND status IN ('queued', 'running', 'pending')", (story_id,))
        pending_count = cursor.fetchone()['count']
        
        if pending_count == 0:
            # Find the last generated part number
            cursor.execute("SELECT MAX(partNumber) as last_part FROM StoryPart WHERE storyId = ?", (story_id,))
            last_part = cursor.fetchone()['last_part'] or 0
            next_part = last_part + 1
            
            if next_part <= story['plannedParts']:
                job_id = f"{story_id}_part{next_part}_repair"
                print(f"Queuing repair job for story '{story['title']}' (Part {next_part})")
                cursor.execute(
                    "INSERT OR IGNORE INTO Job (id, storyId, partNumber, jobType, status, priority, createdAt) VALUES (?, ?, ?, 'generate_part', 'queued', 10, CURRENT_TIMESTAMP)",
                    (job_id, story_id, next_part)
                )
    
    conn.commit()
    conn.close()
    print("\nREPAIR COMPLETE. The Task Monitor should now show activity.")
except Exception as e:
    print(f"Error: {e}")
