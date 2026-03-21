import sqlite3
import json
import os

def query_jobs():
    db_path = "dev.db"
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("--- INCOMPLETE JOBS ---")
    cursor.execute("SELECT id, storyId, partNumber, jobType, status, errorText FROM Job WHERE status != 'done' ORDER BY createdAt DESC LIMIT 20")
    rows = cursor.fetchall()
    for row in rows:
        print(dict(row))
        
    print("\n--- RECENT COMPLETED JOBS ---")
    cursor.execute("SELECT id, storyId, partNumber, jobType, status FROM Job WHERE status = 'done' ORDER BY finishedAt DESC LIMIT 10")
    rows = cursor.fetchall()
    for row in rows:
        print(dict(row))
        
    conn.close()

if __name__ == "__main__":
    query_jobs()
