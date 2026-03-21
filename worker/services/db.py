import sqlite3
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

class Database:
    def __init__(self):
        # Database path is relative to the root of the project
        # Assuming worker is in root/worker/
        db_path = os.getenv("DATABASE_URL", "file:./prisma/dev.db").replace("file:", "")
        # Resolve to absolute path
        self.db_path = str(Path(db_path).resolve())
        print(f"Connecting to database at: {self.db_path}")
        self._ensure_columns()

    def _ensure_columns(self):
        """Ensure the necessary columns for reading speed and other features exist in the DB."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Check and add voiceSpeed to Character
                cursor.execute("PRAGMA table_info(Character)")
                cols = [c[1] for c in cursor.fetchall()]
                if 'voiceSpeed' not in cols:
                    print("Adding voiceSpeed column to Character table...")
                    cursor.execute("ALTER TABLE Character ADD COLUMN voiceSpeed REAL DEFAULT 1.0")
                
                # Check and add narratorVoiceSpeed to Story
                cursor.execute("PRAGMA table_info(Story)")
                cols = [c[1] for c in cursor.fetchall()]
                if 'narratorVoiceSpeed' not in cols:
                    print("Adding narratorVoiceSpeed column to Story table...")
                    cursor.execute("ALTER TABLE Story ADD COLUMN narratorVoiceSpeed REAL DEFAULT 1.0")
                
                conn.commit()
        except Exception as e:
            print(f"Migration error: {str(e)}")

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_queued_job(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM Job WHERE status = 'queued' ORDER BY priority DESC, createdAt ASC LIMIT 1"
            )
            return cursor.fetchone()

    def update_job_status(self, job_id, status, result_json=None, error_text=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status == 'running':
                cursor.execute(
                    "UPDATE Job SET status = ?, startedAt = CURRENT_TIMESTAMP, attempts = attempts + 1 WHERE id = ?",
                    (status, job_id)
                )
            elif status in ['done', 'failed']:
                cursor.execute(
                    "UPDATE Job SET status = ?, finishedAt = CURRENT_TIMESTAMP, resultJson = ?, errorText = ? WHERE id = ?",
                    (status, result_json, error_text, job_id)
                )
            conn.commit()

    def get_settings(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM Settings WHERE id = 'global'")
            row = cursor.fetchone()
            if row:
                return dict(row)
            return {
                "kokoroUrl": "http://localhost:7860/",
                "lmStudioUrl": "http://172.23.48.1:3006/v1",
                "lmStudioApiKey": os.getenv("LM_STUDIO_API_KEY", ""),
                "lmStudioModelId": None
            }

    def update_heartbeat(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Ensure global settings exist
            cursor.execute("INSERT OR IGNORE INTO Settings (id, updatedAt) VALUES ('global', CURRENT_TIMESTAMP)")
            cursor.execute("UPDATE Settings SET workerHeartbeat = CURRENT_TIMESTAMP, updatedAt = CURRENT_TIMESTAMP WHERE id = 'global'")
            conn.commit()

db = Database()
