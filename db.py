import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    photo_file_id TEXT,
    buttons_json TEXT NOT NULL DEFAULT '[]',
    button_columns INTEGER NOT NULL DEFAULT 2,
    schedule_type TEXT NOT NULL DEFAULT 'once',
    schedule_time TEXT NOT NULL,
    weekdays TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

class DB:
    def __init__(self, path: str):
        self.path = path
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def create_post(self, **kwargs):
        keys = ",".join(kwargs.keys())
        placeholders = ",".join("?" for _ in kwargs)
        values = list(kwargs.values())
        with self.connect() as con:
            cur = con.execute(
                f"INSERT INTO posts ({keys}) VALUES ({placeholders})",
                values
            )
            return cur.lastrowid

    def list_posts(self):
        with self.connect() as con:
            return con.execute("SELECT * FROM posts ORDER BY id DESC").fetchall()

    def get_post(self, post_id):
        with self.connect() as con:
            return con.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()

    def toggle_post(self, post_id):
        with self.connect() as con:
            row = con.execute("SELECT enabled FROM posts WHERE id=?", (post_id,)).fetchone()
            if not row:
                return None
            new_value = 0 if row["enabled"] else 1
            con.execute("UPDATE posts SET enabled=? WHERE id=?", (new_value, post_id))
            return new_value

    def delete_post(self, post_id):
        with self.connect() as con:
            con.execute("DELETE FROM posts WHERE id=?", (post_id,))
