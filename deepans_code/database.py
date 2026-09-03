"""
SQLite database module for DeepanCode.
Provides conversation persistence, history, and export.
"""

import os
import json
import time
import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

logger = logging.getLogger("deepans_code.database")

DB_DIR = Path.home() / ".deepans-code"
DB_FILE = DB_DIR / "conversations.db"


def _escape_like(query: str) -> str:
    """Escape LIKE wildcards so search is literal, not pattern-based."""
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Database:
    """SQLite database for conversation persistence (lazy init)."""

    def __init__(self, db_path=None):
        p = Path(db_path) if db_path else DB_FILE
        self.db_path = p
        self._initialized = False

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            from deepans_code.permissions import restrict_dir
            restrict_dir(self.db_path.parent)
        except OSError as e:
            logger.error(f"Could not create DB directory: {e}")
            raise
        self._init_db()
        self._initialized = True

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA busy_timeout=30000;")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT DEFAULT 'Untitled',
                    created_at REAL,
                    updated_at REAL,
                    model TEXT,
                    provider TEXT,
                    mode TEXT,
                    message_count INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER,
                    role TEXT,
                    content TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT,
                    timestamp REAL,
                    tokens_used INTEGER DEFAULT 0,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
                CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(conversation_id, timestamp);
            """)
            conn.commit()
        finally:
            conn.close()
        from deepans_code.permissions import restrict_file
        restrict_file(self.db_path)

    @contextmanager
    def _connect(self):
        self._ensure_init()
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_conversation(self, title="Untitled", model="", provider="", mode="") -> int:
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO conversations (title, created_at, updated_at, model, provider, mode) VALUES (?, ?, ?, ?, ?, ?)",
                (title, now, now, model, provider, mode)
            )
            return cursor.lastrowid

    def save_message(self, conversation_id: int, role: str, content: str,
                     tool_calls=None, tool_call_id=None, tokens_used=0) -> int:
        now = time.time()
        tc_json = json.dumps(tool_calls) if tool_calls else None
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, tool_calls, tool_call_id, timestamp, tokens_used) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (conversation_id, role, content, tc_json, tool_call_id, now, tokens_used)
            )
            conn.execute(
                "UPDATE conversations SET updated_at=?, message_count=message_count+1, total_tokens=total_tokens+? WHERE id=?",
                (now, tokens_used, conversation_id)
            )
            return cursor.lastrowid

    def get_conversations(self, limit=50) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_conversation(self, conv_id: int) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
            return dict(row) if row else None

    def get_messages(self, conversation_id: int, limit: int = 500, offset: int = 0) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY timestamp, id LIMIT ? OFFSET ?",
                (conversation_id, limit, offset),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if d.get("tool_calls"):
                    try:
                        d["tool_calls"] = json.loads(d["tool_calls"])
                    except (json.JSONDecodeError, ValueError, TypeError) as e:
                        logger.warning(f"Skipping corrupt tool_calls JSON: {e}")
                        d["tool_calls"] = None
                result.append(d)
            return result

    def delete_conversation(self, conv_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
            conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))

    def export_conversation(self, conv_id: int, fmt="markdown") -> str:
        conv = self.get_conversation(conv_id)
        if not conv:
            return "Conversation not found"
        messages = self.get_messages(conv_id)
        if fmt == "json":
            return json.dumps({"conversation": conv, "messages": messages}, indent=2)
        lines = [f"# {conv.get('title', 'Untitled')}", f"Model: {conv.get('model', 'N/A')}", ""]
        for msg in messages:
            role = msg.get("role", "unknown")
            if not isinstance(role, str):
                role = "unknown"
            content = (msg.get("content", "") or "")[:20000]
            if role == "system":
                continue
            lines.append(f"## {role.title()}")
            lines.append(content)
            if msg.get("tool_calls"):
                lines.append("\n**Tool calls:**")
                for tc in (msg["tool_calls"] if isinstance(msg["tool_calls"], list) else []):
                    if isinstance(tc, dict) and "function" in tc:
                        lines.append(f"- `{tc['function'].get('name', '')}`")
            lines.append("")
        return "\n".join(lines)

    def search_messages(self, query: str, limit=20) -> List[Dict]:
        if not isinstance(query, str):
            query = "" if query is None else str(query)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT m.*, c.title as conv_title FROM messages m "
                "JOIN conversations c ON m.conversation_id=c.id "
                "WHERE m.content LIKE ? ESCAPE '\\' ORDER BY m.timestamp DESC LIMIT ?",
                (f"%{_escape_like(query)}%", limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self) -> Dict:
        with self._connect() as conn:
            conv_count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            total_tokens = conn.execute("SELECT COALESCE(SUM(total_tokens), 0) FROM conversations").fetchone()[0]
            return {"conversations": conv_count, "messages": msg_count, "total_tokens": total_tokens}


# Lazy singleton: no filesystem I/O at import time. Use get_db() in new
# code; `db` is kept as a lazy proxy for backwards compatibility.
_db_instance: Optional["Database"] = None


def get_db(db_path=None) -> "Database":
    global _db_instance
    if _db_instance is None or db_path is not None:
        inst = Database(db_path=db_path)
        if db_path is None:
            _db_instance = inst
        return inst
    return _db_instance


class _LazyDatabaseProxy:
    def _real(self) -> "Database":
        return get_db()

    def __getattr__(self, name):
        return getattr(self._real(), name)


db = _LazyDatabaseProxy()  # type: ignore
