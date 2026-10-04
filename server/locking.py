"""LANShare Locking and Collaboration Management Engine.
Authoritative server-side coordinator for:
- File Lock States (AVAILABLE, LOCK_REQUESTED, LOCKED, COMMITTING, RELEASING)
- Strict Single-Writer Invariant (writer_count <= 1 per file)
- Write Request Queues (FIFO by default, Host Grant / Deny / Cancel / Reorder)
- Base Version & Atomic Commit Engine (monotonically increasing version numbers)
- Safe Commit Validation & Content Hashing
- Writer Disconnect / Stale Lock Abandonment
- Server Restart Resilience (transient locks cleared on boot, commits persistent in DB)
"""

import os
import time
import uuid
import hashlib
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# Supported File Lock States
STATE_AVAILABLE = "AVAILABLE"
STATE_LOCK_REQUESTED = "LOCK_REQUESTED"
STATE_LOCKED = "LOCKED"
STATE_COMMITTING = "COMMITTING"
STATE_RELEASING = "RELEASING"

class LockSecurityError(Exception):
    """Raised when an unauthorized actor attempts lock operations."""
    pass

class CommitValidationError(Exception):
    """Raised when commit prerequisites fail."""
    pass

class FileLockManager:
    """Server-authoritative file lock and version manager."""

    def __init__(self, db_path: Path, fs_manager, auto_grant: bool = False, lock_grace_period: float = 30.0):
        self.db_path = db_path
        self.fs = fs_manager
        self.auto_grant = auto_grant
        self.lock_grace_period = lock_grace_period
        self._lock = threading.RLock()

        # In-memory transient lock and queue structures
        # Canonical file path -> Active Lock Dict:
        # {
        #   "lock_id": str,
        #   "file_path": str,
        #   "writer_client_id": str,
        #   "writer_user_name": str,
        #   "base_version": int,
        #   "created_at": float,
        #   "last_seen": float,
        #   "disconnected_at": Optional[float],
        #   "state": str
        # }
        self._active_locks: Dict[str, Dict[str, Any]] = {}

        # Canonical file path -> List of Request Dicts:
        # [
        #   {
        #     "request_id": str,
        #     "client_id": str,
        #     "user_name": str,
        #     "file_path": str,
        #     "base_version": int,
        #     "requested_at": float
        #   }
        # ]
        self._request_queues: Dict[str, List[Dict[str, Any]]] = {}

        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            # File versions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_versions (
                    file_path TEXT PRIMARY KEY,
                    current_version INTEGER NOT NULL DEFAULT 1,
                    last_hash TEXT,
                    last_author TEXT,
                    updated_at REAL NOT NULL
                )
            """)
            # Commits history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_commits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    commit_id TEXT NOT NULL UNIQUE,
                    file_path TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    previous_version INTEGER NOT NULL,
                    author TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    summary TEXT,
                    timestamp REAL NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_commits_file_ts ON file_commits (file_path, timestamp DESC);")
            conn.commit()

    def normalize_path(self, rel_path: str) -> str:
        """Returns standard forward-slash normalized relative path."""
        p = rel_path.replace("\\", "/").strip()
        while p.startswith("/"):
            p = p[1:]
        return p

    def get_file_version_info(self, file_path: str) -> Dict[str, Any]:
        """Gets or initializes committed version info for a file."""
        norm_path = self.normalize_path(file_path)
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT file_path, current_version, last_hash, last_author, updated_at
                    FROM file_versions
                    WHERE file_path = ?
                """, (norm_path,))
                row = cursor.fetchone()
                if row:
                    return dict(row)

                # Initialize from disk if file exists
                try:
                    target = self.fs.resolve_safe_path(norm_path)
                    if target.is_file():
                        content = target.read_bytes()
                        content_hash = hashlib.sha256(content).hexdigest()
                        now = time.time()
                        cursor.execute("""
                            INSERT INTO file_versions (file_path, current_version, last_hash, last_author, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                        """, (norm_path, 1, content_hash, "Initial", now))
                        conn.commit()
                        return {
                            "file_path": norm_path,
                            "current_version": 1,
                            "last_hash": content_hash,
                            "last_author": "Initial",
                            "updated_at": now
                        }
                except Exception:
                    pass

                return {
                    "file_path": norm_path,
                    "current_version": 1,
                    "last_hash": None,
                    "last_author": None,
                    "updated_at": time.time()
                }

    def get_file_state(self, file_path: str) -> Dict[str, Any]:
        """Returns the complete lock, queue, and version state for a file."""
        norm_path = self.normalize_path(file_path)
        with self._lock:
            ver_info = self.get_file_version_info(norm_path)
            active_lock = self._active_locks.get(norm_path)
            queue = self._request_queues.get(norm_path, [])

            if active_lock:
                state = active_lock.get("state", STATE_LOCKED)
                writer = {
                    "client_id": active_lock["writer_client_id"],
                    "user_name": active_lock["writer_user_name"],
                    "lock_id": active_lock["lock_id"],
                    "base_version": active_lock["base_version"],
                    "created_at": active_lock["created_at"],
                    "last_seen": active_lock.get("last_seen", active_lock["created_at"])
                }
            elif len(queue) > 0:
                state = STATE_LOCK_REQUESTED
                writer = None
            else:
                state = STATE_AVAILABLE
                writer = None

            # Enrich queue with 1-based position
            formatted_queue = []
            for idx, req in enumerate(queue):
                formatted_queue.append({
                    "position": idx + 1,
                    "request_id": req["request_id"],
                    "client_id": req["client_id"],
                    "user_name": req["user_name"],
                    "file_path": req["file_path"],
                    "base_version": req["base_version"],
                    "requested_at": req["requested_at"]
                })

            return {
                "file_path": norm_path,
                "state": state,
                "version": ver_info["current_version"],
                "last_hash": ver_info["last_hash"],
                "last_author": ver_info["last_author"],
                "updated_at": ver_info["updated_at"],
                "writer": writer,
                "queue": formatted_queue,
                "queue_count": len(formatted_queue)
            }

    def request_write_access(self, file_path: str, client_id: str, user_name: str, is_host: bool = False, auto_grant_if_available: Optional[bool] = None) -> Tuple[bool, str, Dict[str, Any]]:
        """A user requests edit access to a file."""
        if auto_grant_if_available is None:
            auto_grant_if_available = self.auto_grant
        norm_path = self.normalize_path(file_path)
        with self._lock:
            target = self.fs.resolve_safe_path(norm_path)
            if not target.is_file():
                return False, f"Target '{norm_path}' is not a regular file.", {}

            ver_info = self.get_file_version_info(norm_path)
            current_ver = ver_info["current_version"]

            # If already writer, return current lock and clear disconnected status
            active_lock = self._active_locks.get(norm_path)
            if active_lock and active_lock["writer_client_id"] == client_id:
                active_lock["last_seen"] = time.time()
                active_lock["disconnected_at"] = None
                return True, "ALREADY_OWNER", self.get_file_state(norm_path)

            queue = self._request_queues.setdefault(norm_path, [])

            # Check if already in queue
            for req in queue:
                if req["client_id"] == client_id:
                    return True, "ALREADY_QUEUED", self.get_file_state(norm_path)

            req_obj = {
                "request_id": f"req_{uuid.uuid4().hex[:10]}",
                "client_id": client_id,
                "user_name": user_name,
                "file_path": norm_path,
                "base_version": current_ver,
                "requested_at": time.time()
            }
            queue.append(req_obj)

            # If no active lock and auto-grant enabled (FIFO), grant immediately
            if not active_lock and auto_grant_if_available and queue[0]["client_id"] == client_id:
                queue.pop(0)
                lock_id = f"lock_{uuid.uuid4().hex[:12]}"
                new_lock = {
                    "lock_id": lock_id,
                    "file_path": norm_path,
                    "writer_client_id": client_id,
                    "writer_user_name": user_name,
                    "base_version": current_ver,
                    "created_at": time.time(),
                    "last_seen": time.time(),
                    "state": STATE_LOCKED
                }
                self._active_locks[norm_path] = new_lock
                return True, "GRANTED", self.get_file_state(norm_path)

            return True, "QUEUED", self.get_file_state(norm_path)

    def cancel_write_request(self, file_path: str, client_id: str) -> Tuple[bool, str, Dict[str, Any]]:
        """A user cancels their own pending queue request."""
        norm_path = self.normalize_path(file_path)
        with self._lock:
            queue = self._request_queues.get(norm_path, [])
            initial_len = len(queue)
            self._request_queues[norm_path] = [r for r in queue if r["client_id"] != client_id]
            if len(self._request_queues[norm_path]) < initial_len:
                return True, "CANCELLED", self.get_file_state(norm_path)
            return False, "Request not found in queue.", self.get_file_state(norm_path)

    def host_grant(self, file_path: str, target_client_id: Optional[str] = None) -> Tuple[bool, str, Dict[str, Any]]:
        """Host explicitly grants write access to the next eligible user or specific target in queue."""
        norm_path = self.normalize_path(file_path)
        with self._lock:
            active_lock = self._active_locks.get(norm_path)
            if active_lock:
                return False, f"File is currently locked by {active_lock['writer_user_name']}. Must release or revoke first.", self.get_file_state(norm_path)

            queue = self._request_queues.get(norm_path, [])
            if not queue:
                return False, "Queue is empty. No pending write requests to grant.", self.get_file_state(norm_path)

            selected_req = None
            if target_client_id:
                for idx, r in enumerate(queue):
                    if r["client_id"] == target_client_id:
                        selected_req = queue.pop(idx)
                        break
                if not selected_req:
                    return False, f"Client {target_client_id} not found in queue.", self.get_file_state(norm_path)
            else:
                selected_req = queue.pop(0)

            ver_info = self.get_file_version_info(norm_path)
            lock_id = f"lock_{uuid.uuid4().hex[:12]}"
            new_lock = {
                "lock_id": lock_id,
                "file_path": norm_path,
                "writer_client_id": selected_req["client_id"],
                "writer_user_name": selected_req["user_name"],
                "base_version": ver_info["current_version"],
                "created_at": time.time(),
                "last_seen": time.time(),
                "state": STATE_LOCKED
            }
            self._active_locks[norm_path] = new_lock
            return True, "GRANTED", self.get_file_state(norm_path)

    def host_deny(self, file_path: str, client_id: str) -> Tuple[bool, str, Dict[str, Any], Optional[str]]:
        """Host explicitly denies and removes a user from the queue."""
        norm_path = self.normalize_path(file_path)
        with self._lock:
            queue = self._request_queues.get(norm_path, [])
            user_name = None
            found_idx = -1
            for idx, r in enumerate(queue):
                if r["client_id"] == client_id:
                    found_idx = idx
                    user_name = r["user_name"]
                    break

            if found_idx != -1:
                queue.pop(found_idx)
                return True, "DENIED", self.get_file_state(norm_path), user_name
            return False, "Client not found in queue.", self.get_file_state(norm_path), None

    def host_reorder_queue(self, file_path: str, client_id: str, direction: str) -> Tuple[bool, str, Dict[str, Any]]:
        """Host moves a queue item 'up' or 'down'."""
        norm_path = self.normalize_path(file_path)
        with self._lock:
            queue = self._request_queues.get(norm_path, [])
            idx = -1
            for i, r in enumerate(queue):
                if r["client_id"] == client_id:
                    idx = i
                    break

            if idx == -1:
                return False, "Client not found in queue.", self.get_file_state(norm_path)

            if direction == "up" and idx > 0:
                queue[idx - 1], queue[idx] = queue[idx], queue[idx - 1]
                return True, "REORDERED", self.get_file_state(norm_path)
            elif direction == "down" and idx < len(queue) - 1:
                queue[idx + 1], queue[idx] = queue[idx], queue[idx + 1]
                return True, "REORDERED", self.get_file_state(norm_path)

            return False, "Cannot move item in specified direction.", self.get_file_state(norm_path)

    def host_revoke(self, file_path: str) -> Tuple[bool, str, Dict[str, Any], Optional[Dict[str, Any]]]:
        """Host revokes the active writer's lock."""
        norm_path = self.normalize_path(file_path)
        with self._lock:
            active_lock = self._active_locks.pop(norm_path, None)
            if not active_lock:
                return False, "File is not currently locked.", self.get_file_state(norm_path), None

            return True, "REVOKED", self.get_file_state(norm_path), active_lock

    def release_lock(self, file_path: str, client_id: str, lock_id: Optional[str] = None) -> Tuple[bool, str, Dict[str, Any], Optional[Dict[str, Any]]]:
        """Writer voluntarily releases their lock."""
        norm_path = self.normalize_path(file_path)
        with self._lock:
            active_lock = self._active_locks.get(norm_path)
            if not active_lock:
                return False, "File is not currently locked.", self.get_file_state(norm_path), None

            if active_lock["writer_client_id"] != client_id:
                return False, "You are not the active writer of this file.", self.get_file_state(norm_path), None

            if lock_id and active_lock["lock_id"] != lock_id:
                return False, "Invalid or expired lock ID.", self.get_file_state(norm_path), None

            released_lock = self._active_locks.pop(norm_path)
            return True, "RELEASED", self.get_file_state(norm_path), released_lock

    def auto_promote_next_writer(self, file_path: str) -> Optional[Dict[str, Any]]:
        """If file is AVAILABLE and queue has pending requests, grants to top of FIFO queue."""
        norm_path = self.normalize_path(file_path)
        with self._lock:
            if norm_path in self._active_locks:
                return None
            queue = self._request_queues.get(norm_path, [])
            if not queue:
                return None

            next_req = queue.pop(0)
            ver_info = self.get_file_version_info(norm_path)
            lock_id = f"lock_{uuid.uuid4().hex[:12]}"
            new_lock = {
                "lock_id": lock_id,
                "file_path": norm_path,
                "writer_client_id": next_req["client_id"],
                "writer_user_name": next_req["user_name"],
                "base_version": ver_info["current_version"],
                "created_at": time.time(),
                "last_seen": time.time(),
                "state": STATE_LOCKED
            }
            self._active_locks[norm_path] = new_lock
            return new_lock

    def validate_and_commit(
        self,
        file_path: str,
        client_id: str,
        lock_id: str,
        content_bytes: bytes,
        author: str,
        summary: Optional[str] = None,
        release_lock_after: bool = False,
        base_version: Optional[int] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates lock, base version, calculates hash, atomically writes file,
        increments version number monotonically, records commit in DB, and optionally releases lock.
        """
        norm_path = self.normalize_path(file_path)
        with self._lock:
            # 1. Check lock existence and ownership
            active_lock = self._active_locks.get(norm_path)
            if not active_lock:
                return False, "COMMIT_REJECTED: No active write lock held on file.", {}

            if active_lock["writer_client_id"] != client_id:
                return False, "COMMIT_REJECTED: Client does not own the active lock.", {}

            if active_lock["lock_id"] != lock_id:
                return False, "COMMIT_REJECTED: Lock ID mismatch or stale lock.", {}

            # 2. Check target file existence inside jail
            try:
                target = self.fs.resolve_safe_path(norm_path)
                if not target.is_file():
                    return False, f"COMMIT_REJECTED: File '{norm_path}' no longer exists on disk.", {}
            except Exception as e:
                return False, f"COMMIT_REJECTED: Path security or filesystem error: {str(e)}", {}

            # 3. Base version validation
            ver_info = self.get_file_version_info(norm_path)
            current_ver = ver_info["current_version"]
            if base_version is not None and base_version != current_ver:
                return False, f"COMMIT_REJECTED: Stale base version {base_version} (server is at {current_ver}).", {}

            # Mark state as COMMITTING
            active_lock["state"] = STATE_COMMITTING

            next_ver = current_ver + 1

            # 4. Server-side hash calculation
            content_hash = hashlib.sha256(content_bytes).hexdigest()
            file_size = len(content_bytes)
            commit_id = f"cmt_{uuid.uuid4().hex[:12]}"
            now = time.time()

            # 5. Atomic File System Write: write to .tmp in same directory, flush, atomic os.replace
            target_dir = target.parent
            temp_file = target_dir / f".tmp_{commit_id}_{target.name}"
            try:
                with open(temp_file, "wb") as f:
                    f.write(content_bytes)
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic replace
                os.replace(str(temp_file), str(target))
            except Exception as e:
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass
                active_lock["state"] = STATE_LOCKED
                return False, f"COMMIT_REJECTED: Atomic write failed: {str(e)}", {}

            # 6. Update SQLite persistent tables atomically
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO file_commits (commit_id, file_path, version_number, previous_version, author, client_id, content_hash, file_size, summary, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (commit_id, norm_path, next_ver, current_ver, author, client_id, content_hash, file_size, summary or f"Committed version {next_ver}", now))

                    cursor.execute("""
                        INSERT INTO file_versions (file_path, current_version, last_hash, last_author, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(file_path) DO UPDATE SET
                            current_version = excluded.current_version,
                            last_hash = excluded.last_hash,
                            last_author = excluded.last_author,
                            updated_at = excluded.updated_at
                    """, (norm_path, next_ver, content_hash, author, now))
                    conn.commit()
            except Exception as e:
                # DB error
                active_lock["state"] = STATE_LOCKED
                return False, f"COMMIT_REJECTED: Failed to record commit metadata: {str(e)}", {}

            # 7. Release lock if requested
            if release_lock_after:
                self._active_locks.pop(norm_path, None)
            else:
                active_lock["base_version"] = next_ver
                active_lock["state"] = STATE_LOCKED

            commit_result = {
                "commit_id": commit_id,
                "file_path": norm_path,
                "version_number": next_ver,
                "previous_version": current_ver,
                "author": author,
                "client_id": client_id,
                "content_hash": content_hash,
                "file_size": file_size,
                "summary": summary,
                "timestamp": now,
                "lock_released": release_lock_after
            }

            return True, "COMMIT_ACCEPTED", commit_result

    def handle_client_disconnect(self, client_id: str, immediate_release: bool = False) -> List[Tuple[str, Dict[str, Any]]]:
        """
        When a client disconnects, clean up their queue requests.
        For active writer locks: mark lock with disconnected_at timestamp for grace period
        or release immediately if requested.
        """
        affected = []
        now = time.time()
        with self._lock:
            # 1. Remove from all queues
            for file_path, queue in list(self._request_queues.items()):
                new_q = [r for r in queue if r["client_id"] != client_id]
                if len(new_q) != len(queue):
                    self._request_queues[file_path] = new_q
                    affected.append((file_path, self.get_file_state(file_path)))

            # 2. Mark active lock with disconnected_at or release immediately
            for file_path, active_lock in list(self._active_locks.items()):
                if active_lock["writer_client_id"] == client_id:
                    if immediate_release or self.lock_grace_period <= 0:
                        self._active_locks.pop(file_path, None)
                    else:
                        active_lock["disconnected_at"] = now
                    affected.append((file_path, self.get_file_state(file_path)))

        return affected

    def cleanup_expired_locks(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Checks for locks whose disconnected grace period has expired, and releases them."""
        affected = []
        now = time.time()
        with self._lock:
            for file_path, active_lock in list(self._active_locks.items()):
                disc_at = active_lock.get("disconnected_at")
                if disc_at is not None and (now - disc_at) >= self.lock_grace_period:
                    self._active_locks.pop(file_path, None)
                    affected.append((file_path, self.get_file_state(file_path)))
        return affected

    def get_commit_history(self, file_path: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Returns commit logs for a file."""
        norm_path = self.normalize_path(file_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT commit_id, file_path, version_number, previous_version, author, client_id, content_hash, file_size, summary, timestamp
                FROM file_commits
                WHERE file_path = ?
                ORDER BY version_number DESC
                LIMIT ?
            """, (norm_path, limit))
            return [dict(r) for r in cursor.fetchall()]

    def get_all_active_locks(self) -> Dict[str, Dict[str, Any]]:
        """Returns all currently active locks across workspace."""
        with self._lock:
            return {p: self.get_file_state(p) for p in self._active_locks}
