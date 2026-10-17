import sqlite3

DB_FILE = "citations.db"

def migrate_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 1. Ensure the folders table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # 2. Check if folder_id column exists in citations table
    cursor.execute("PRAGMA table_info(citations)")
    columns = [column[1] for column in cursor.fetchall()]

    if "folder_id" not in columns:
        print("Adding 'folder_id' column to existing 'citations' table...")
        cursor.execute("ALTER TABLE citations ADD COLUMN folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL")
        print("Schema updated successfully!")
    else:
        print("Database schema is already up to date.")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate_database()