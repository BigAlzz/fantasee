import sqlite3
import json

def check_story():
    try:
        conn = sqlite3.connect('dev.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Check Story
        cursor.execute("SELECT id, title, status FROM Story WHERE title LIKE '%invisible%'")
        stories = cursor.fetchall()
        print(f"Found {len(stories)} matching stories:")
        for s in stories:
            print(f"ID: {s['id']}, Title: {s['title']}, Status: {s['status']}")
            
            # Check Jobs for this story
            cursor.execute("SELECT id, jobType, status, attempts, errorText FROM Job WHERE storyId = ?", (s['id'],))
            jobs = cursor.fetchall()
            print(f"  Jobs ({len(jobs)}):")
            for j in jobs:
                print(f"    ID: {j['id']}, Type: {j['jobType']}, Status: {j['status']}, Attempts: {j['attempts']}, Error: {j['errorText']}")
            
            # Check Parts for this story
            cursor.execute("SELECT id, partNumber, status FROM StoryPart WHERE storyId = ?", (s['id'],))
            parts = cursor.fetchall()
            print(f"  Parts ({len(parts)}):")
            for p in parts:
                print(f"    Part {p['partNumber']} (ID: {p['id']}): {p['status']}")
                
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    check_story()
