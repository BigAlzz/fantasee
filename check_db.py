import sqlite3
import os
from pathlib import Path

db_path = str(Path("E:\Dev\Fantasee1\dev.db").resolve())
print(f"Checking database at: {db_path}")

try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check Settings
    cursor.execute("SELECT * FROM Settings WHERE id = 'global'")
    row = cursor.fetchone()
    if row:
        print(f"Settings: {dict(row)}")
    else:
        print("No global settings found.")
        
    # Check recent Jobs
    cursor.execute("SELECT id, jobType, status, createdAt FROM Job ORDER BY createdAt DESC LIMIT 10")
    jobs = cursor.fetchall()
    print(f"\nRecent Jobs ({len(jobs)}):")
    for job in jobs:
        print(dict(job))
        
    conn.close()
except Exception as e:
    print(f"Error: {e}")
