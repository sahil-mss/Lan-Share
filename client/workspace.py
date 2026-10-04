"""Local Workspace and Tracked Files Manager.

Maintains local tracking state:
- Workspace configurations
- Tracked files registry
- Synchronization state machine
- Hash and version computation
"""

import os
import time
import json
import sqlite3
import hashlib
import secrets
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Sync States (Phase 21 state model)
STATE_SYNCED = "SYNCED"
STATE_LOCAL_MODIFIED = "LOCAL_MODIFIED"
STATE_SERVER_UPDATED = "SERVER_UPDATED"
STATE_CONFLICT = "CONFLICT"
STATE_LOCK_REQUIRED = "LOCK_REQUIRED"
STATE_LOCKED_BY_ME = "LOCKED_BY_ME"
STATE_LOCKED_BY_OTHER = "LOCKED_BY_OTHER"
STATE_OFFLINE = "OFFLINE"
STATE_MISSING_LOCAL_FILE = "MISSING_LOCAL_FILE"

def compute_file_sha256(path: Path) -> Optional[str]:
    """Computes SHA-256 of file on disk safely."""
    try:
        if not path.is_file():
            return None
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None

def compute_bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

class LocalWorkspaceManager:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracked_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_url TEXT NOT NULL,
                    shared_path TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    base_version INTEGER NOT NULL DEFAULT 1,
                    server_version INTEGER NOT NULL DEFAULT 1,
                    server_hash TEXT,
                    last_synced_hash TEXT,
                    local_hash TEXT,
                    lock_id TEXT,
                    lock_owner TEXT,
                    last_synced_at REAL NOT NULL,
                    last_checked_at REAL NOT NULL,
                    sync_state TEXT NOT NULL DEFAULT 'SYNCED',
                    conflict_server_hash TEXT,
                    conflict_server_version INTEGER,
                    UNIQUE(server_url, shared_path, local_path)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracked_local ON tracked_files(local_path);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracked_server ON tracked_files(server_url, shared_path);")
            conn.commit()

    def register_tracked_file(
        self,
        server_url: str,
        shared_path: str,
        local_path: str,
        server_version: int,
        server_hash: Optional[str],
        content_bytes: Optional[bytes] = None
    ) -> Dict[str, Any]:
        """Registers or updates a local tracked file."""
        norm_server = server_url.rstrip("/")
        norm_shared = shared_path.replace("\\", "/").strip().lstrip("/")
        norm_local = str(Path(local_path).resolve())
        local_p = Path(norm_local)

        # If content provided, ensure local directory and file exist
        if content_bytes is not None:
            local_p.parent.mkdir(parents=True, exist_ok=True)
            with open(local_p, "wb") as f:
                f.write(content_bytes)

        cur_local_hash = compute_file_sha256(local_p)
        now = time.time()

        initial_state = STATE_SYNCED if cur_local_hash == server_hash else STATE_LOCAL_MODIFIED
        if not local_p.exists():
            initial_state = STATE_MISSING_LOCAL_FILE

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tracked_files (
                    server_url, shared_path, local_path, base_version, server_version,
                    server_hash, last_synced_hash, local_hash, last_synced_at,
                    last_checked_at, sync_state
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_url, shared_path, local_path) DO UPDATE SET
                    base_version = excluded.base_version,
                    server_version = excluded.server_version,
                    server_hash = excluded.server_hash,
                    last_synced_hash = excluded.last_synced_hash,
                    local_hash = excluded.local_hash,
                    last_synced_at = excluded.last_synced_at,
                    last_checked_at = excluded.last_checked_at,
                    sync_state = excluded.sync_state
            """, (
                norm_server, norm_shared, norm_local, server_version, server_version,
                server_hash, server_hash, cur_local_hash, now,
                now, initial_state
            ))
            conn.commit()

        return self.get_tracked_file(norm_server, norm_shared, norm_local)

    def get_tracked_file(self, server_url: str, shared_path: str, local_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        norm_server = server_url.rstrip("/")
        norm_shared = shared_path.replace("\\", "/").strip().lstrip("/")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if local_path:
                norm_local = str(Path(local_path).resolve())
                cursor.execute("""
                    SELECT * FROM tracked_files
                    WHERE server_url = ? AND shared_path = ? AND local_path = ?
                """, (norm_server, norm_shared, norm_local))
            else:
                cursor.execute("""
                    SELECT * FROM tracked_files
                    WHERE server_url = ? AND shared_path = ?
                    ORDER BY last_synced_at DESC LIMIT 1
                """, (norm_server, norm_shared))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_tracked_by_local_path(self, local_path: str) -> Optional[Dict[str, Any]]:
        norm_local = str(Path(local_path).resolve())
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM tracked_files
                WHERE local_path = ?
            """, (norm_local,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_tracked_files(self, server_url: Optional[str] = None) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if server_url:
                norm_server = server_url.rstrip("/")
                cursor.execute("SELECT * FROM tracked_files WHERE server_url = ? ORDER BY shared_path ASC", (norm_server,))
            else:
                cursor.execute("SELECT * FROM tracked_files ORDER BY shared_path ASC")
            return [dict(r) for r in cursor.fetchall()]

    def update_local_hash_and_state(self, local_path: str, new_hash: Optional[str]) -> Optional[Dict[str, Any]]:
        """Recalculates state based on local file change."""
        tracked = self.get_tracked_by_local_path(local_path)
        if not tracked:
            return None

        local_p = Path(local_path)
        now = time.time()
        
        if not local_p.exists():
            new_state = STATE_MISSING_LOCAL_FILE
        else:
            local_changed = (new_hash != tracked["last_synced_hash"])
            server_changed = (tracked["server_hash"] != tracked["last_synced_hash"])

            if local_changed and server_changed:
                new_state = STATE_CONFLICT
            elif local_changed:
                new_state = STATE_LOCAL_MODIFIED
            elif server_changed:
                new_state = STATE_SERVER_UPDATED
            else:
                new_state = STATE_SYNCED

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tracked_files
                SET local_hash = ?, sync_state = ?, last_checked_at = ?
                WHERE id = ?
            """, (new_hash, new_state, now, tracked["id"]))
            conn.commit()

        return self.get_tracked_by_local_path(local_path)

    def handle_server_version_update(
        self,
        server_url: str,
        shared_path: str,
        new_version: int,
        new_hash: str
    ) -> List[Dict[str, Any]]:
        """Handles server-pushed version change across all local copies of this shared path."""
        norm_server = server_url.rstrip("/")
        norm_shared = shared_path.replace("\\", "/").strip().lstrip("/")
        updated_records = []

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM tracked_files
                WHERE server_url = ? AND shared_path = ?
            """, (norm_server, norm_shared))
            records = [dict(r) for r in cursor.fetchall()]

        now = time.time()
        for r in records:
            local_p = Path(r["local_path"])
            cur_local_hash = compute_file_sha256(local_p)
            
            if not local_p.exists():
                new_state = STATE_MISSING_LOCAL_FILE
            else:
                local_modified = (cur_local_hash != r["last_synced_hash"])
                if local_modified:
                    # User changed local file AND server changed = CONFLICT!
                    new_state = STATE_CONFLICT
                else:
                    new_state = STATE_SERVER_UPDATED

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE tracked_files
                    SET server_version = ?, server_hash = ?, local_hash = ?,
                        sync_state = ?, conflict_server_hash = ?,
                        conflict_server_version = ?, last_checked_at = ?
                    WHERE id = ?
                """, (
                    new_version, new_hash, cur_local_hash,
                    new_state, new_hash if new_state == STATE_CONFLICT else None,
                    new_version if new_state == STATE_CONFLICT else None, now,
                    r["id"]
                ))
                conn.commit()
            
            updated_records.append(self.get_tracked_by_local_path(r["local_path"]))

        return updated_records

    def apply_server_version_to_local(
        self,
        local_path: str,
        server_version: int,
        server_hash: str,
        content_bytes: bytes,
        force_overwrite: bool = False
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Safely updates local file with server version. Never silenty overwrites modified files without force."""
        tracked = self.get_tracked_by_local_path(local_path)
        if not tracked:
            return False, "File is not tracked.", None

        local_p = Path(local_path)
        cur_hash = compute_file_sha256(local_p)
        is_modified = cur_hash and (cur_hash != tracked["last_synced_hash"])

        if is_modified and not force_overwrite:
            return False, "Local file contains uncommitted modifications. Overwrite rejected.", tracked

        # Write safely using atomic temporary file
        temp_file = local_p.parent / f".tmp_{secrets.token_hex(6)}_{local_p.name}"
        try:
            local_p.parent.mkdir(parents=True, exist_ok=True)
            with open(temp_file, "wb") as f:
                f.write(content_bytes)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(temp_file), str(local_p))
        except Exception as e:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            return False, f"Failed to write local file: {e}", tracked

        new_local_hash = compute_file_sha256(local_p)
        now = time.time()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tracked_files
                SET base_version = ?, server_version = ?, server_hash = ?, last_synced_hash = ?,
                    local_hash = ?, sync_state = ?, conflict_server_hash = NULL,
                    conflict_server_version = NULL, last_synced_at = ?, last_checked_at = ?
                WHERE id = ?
            """, (
                server_version, server_version, server_hash, new_local_hash,
                new_local_hash, STATE_SYNCED, now, now, tracked["id"]
            ))
            conn.commit()

        return True, "UPDATED", self.get_tracked_by_local_path(local_path)

    def mark_committed_synced(
        self,
        local_path: str,
        new_version: int,
        new_hash: str
    ) -> Optional[Dict[str, Any]]:
        """Called after successful commit to server."""
        tracked = self.get_tracked_by_local_path(local_path)
        if not tracked:
            return None

        # Verify actual hash on disk to prevent line-ending or encoding mismatch
        local_p = Path(local_path)
        disk_hash = compute_file_sha256(local_p) or new_hash

        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tracked_files
                SET base_version = ?, server_version = ?, server_hash = ?, last_synced_hash = ?,
                    local_hash = ?, sync_state = ?, last_synced_at = ?, last_checked_at = ?
                WHERE id = ?
            """, (
                new_version, new_version, new_hash, disk_hash,
                disk_hash, STATE_SYNCED, now, now, tracked["id"]
            ))
            conn.commit()

        return self.get_tracked_by_local_path(local_path)

    def stop_tracking(self, local_path: str) -> bool:
        norm_local = str(Path(local_path).resolve())
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tracked_files WHERE local_path = ?", (norm_local,))
            conn.commit()
            return cursor.rowcount > 0
