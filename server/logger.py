"""Activity Logger and Event Store for LANShare.
Maintains structured server-side event logs, access tracking, and broadcast payloads.
"""
import sqlite3
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

class ActivityLogger:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    file_path TEXT,
                    details TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS access_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    user_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    action TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS local_copies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL,
                    shared_path TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    version_hash TEXT,
                    synced_at REAL NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log (timestamp DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_access_file_ts ON access_history (file_path, timestamp DESC);")
            conn.commit()

    def log_event(self, event_type: str, user_name: str, client_id: str, file_path: Optional[str] = None, details: Optional[str] = None) -> Dict[str, Any]:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO activity_log (timestamp, event_type, user_name, client_id, file_path, details)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (now, event_type, user_name, client_id, file_path, details))
            event_id = cursor.lastrowid

            lock_and_file_events = [
                "FILE_OPENED", "FILE_PREVIEWED", "FILE_DOWNLOADED", "FILE_COPIED",
                "FILE_CREATED", "FILE_RENAMED", "FILE_MOVED", "FILE_DELETED", "FILE_UPLOADED",
                "WRITE_REQUESTED", "WRITE_GRANTED", "WRITE_DENIED", "WRITE_CANCELLED",
                "LOCK_CREATED", "LOCK_REVOKED", "LOCK_RELEASED",
                "COMMIT_STARTED", "COMMIT_CREATED", "COMMIT_REJECTED"
            ]
            if file_path and event_type in lock_and_file_events:
                cursor.execute("""
                    INSERT INTO access_history (timestamp, user_name, file_path, action)
                    VALUES (?, ?, ?, ?)
                """, (now, user_name, file_path, event_type))

            conn.commit()

        return {
            "id": event_id,
            "timestamp": now,
            "event_type": event_type,
            "user_name": user_name,
            "client_id": client_id,
            "file_path": file_path,
            "details": details
        }

    def get_recent_activity(self, limit: int = 50) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, timestamp, event_type, user_name, client_id, file_path, details
                FROM activity_log
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_file_access_history(self, file_path: str, limit: int = 30) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, user_name, file_path, action
                FROM access_history
                WHERE file_path = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (file_path, limit))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def record_local_copy(self, client_id: str, shared_path: str, local_path: str, version_hash: Optional[str]) -> None:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO local_copies (client_id, shared_path, local_path, version_hash, synced_at)
                VALUES (?, ?, ?, ?, ?)
            """, (client_id, shared_path, local_path, version_hash, now))
            conn.commit()
