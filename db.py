"""
Tiny SQLite persistence layer — conversations + messages.
No ORM, just stdlib sqlite3, so there's nothing extra to install.
"""
import os
import sqlite3
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "app_data.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'New chat',
            model TEXT NOT NULL,
            use_rag INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            sources TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()


def _now():
    return datetime.datetime.utcnow().isoformat()


def create_conversation(model, title="New chat", use_rag=False):
    conn = _conn()
    now = _now()
    cur = conn.execute(
        "INSERT INTO conversations (title, model, use_rag, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (title, model, int(use_rag), now, now),
    )
    conn.commit()
    conv_id = cur.lastrowid
    conn.close()
    return conv_id


def list_conversations():
    conn = _conn()
    rows = conn.execute(
        "SELECT id, title, model, use_rag, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversation(conv_id):
    conn = _conn()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_conversation(conv_id, **fields):
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [conv_id]
    conn = _conn()
    conn.execute(f"UPDATE conversations SET {cols} WHERE id = ?", values)
    conn.commit()
    conn.close()


def touch_conversation(conv_id):
    update_conversation(conv_id, updated_at=_now())


def delete_conversation(conv_id):
    conn = _conn()
    conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    conn.close()


def add_message(conv_id, role, content, sources=None):
    conn = _conn()
    now = _now()
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, sources, created_at) VALUES (?, ?, ?, ?, ?)",
        (conv_id, role, content, sources, now),
    )
    conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
    conn.commit()
    conn.close()


def get_messages(conv_id):
    conn = _conn()
    rows = conn.execute(
        "SELECT role, content, sources, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conv_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
