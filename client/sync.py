"""Synchronization Engine for LANShare Local Client.

Coordinates:
- Local Workspace tracking
- File Watcher events
- Server Transport communication & Realtime events
- Conflict detection and Safe Resolution
- Lock-aware commits and stale-version protection
"""

import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable

from client.workspace import (
    LocalWorkspaceManager,
    STATE_SYNCED,
    STATE_LOCAL_MODIFIED,
    STATE_SERVER_UPDATED,
    STATE_CONFLICT,
    STATE_LOCK_REQUIRED,
    STATE_LOCKED_BY_ME,
    STATE_LOCKED_BY_OTHER,
    STATE_OFFLINE,
    STATE_MISSING_LOCAL_FILE,
    compute_file_sha256
)
from client.watcher import LocalFileWatcher
from client.transport import ServerTransport

class SyncEngine:
    def __init__(
        self,
        workspace_mgr: LocalWorkspaceManager,
        on_notify: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        self.workspace_mgr = workspace_mgr
        self.on_notify = on_notify or (lambda event: None)
        self.transports: Dict[str, ServerTransport] = {}
        self.watcher = LocalFileWatcher(on_change_callback=self._handle_local_file_change)
        self._init_watcher()

    def _init_watcher(self):
        # Populate watcher with all currently tracked local files
        files = self.workspace_mgr.list_tracked_files()
        for f in files:
            p = f["local_path"]
            if os.path.exists(p):
                self.watcher.watch_file(p)
        self.watcher.start()

    def get_transport(self, server_url: str, token: Optional[str] = None) -> ServerTransport:
        norm = server_url.rstrip("/")
        if norm not in self.transports:
            transport = ServerTransport(
                server_url=norm,
                token=token,
                on_event_callback=lambda evt: self._handle_server_event(norm, evt),
                on_status_change=lambda connected: self._handle_connectivity_change(norm, connected)
            )
            transport.start_realtime_listener()
            self.transports[norm] = transport
        else:
            if token:
                self.transports[norm].set_token(token)
        return self.transports[norm]

    def _handle_local_file_change(self, local_path: str, new_hash: Optional[str]):
        """Triggered by file watcher when local file is modified, deleted, or replaced."""
        updated = self.workspace_mgr.update_local_hash_and_state(local_path, new_hash)
        if updated:
            self.on_notify({
                "type": "LOCAL_FILE_CHANGED",
                "file": updated
            })

    def _handle_connectivity_change(self, server_url: str, is_connected: bool):
        if not is_connected:
            self.on_notify({
                "type": "SERVER_OFFLINE",
                "server_url": server_url
            })
        else:
            # Reconnection: reconcile tracked files with server
            self.reconcile_with_server(server_url)

    def _handle_server_event(self, server_url: str, event: Dict[str, Any]):
        evt_type = event.get("type")
        payload = event.get("payload", {})

        if evt_type == "FILE_COMMITTED":
            shared_path = payload.get("file_path")
            new_version = payload.get("version")
            new_hash = payload.get("content_hash")
            author = payload.get("author")

            if shared_path and new_version:
                updated_list = self.workspace_mgr.handle_server_version_update(
                    server_url=server_url,
                    shared_path=shared_path,
                    new_version=new_version,
                    new_hash=new_hash
                )
                for item in updated_list:
                    self.on_notify({
                        "type": "SERVER_VERSION_CHANGED",
                        "file": item,
                        "author": author,
                        "new_version": new_version
                    })

        elif evt_type == "LOCK_STATE_CHANGED":
            shared_path = payload.get("file_path")
            self.on_notify({
                "type": "LOCK_STATE_CHANGED",
                "shared_path": shared_path,
                "lock_info": payload
            })

    def reconcile_with_server(self, server_url: str):
        """Reconciles local files against server metadata upon reconnect."""
        norm_server = server_url.rstrip("/")
        transport = self.transports.get(norm_server)
        if not transport:
            return

        tracked_files = self.workspace_mgr.list_tracked_files(norm_server)
        for tf in tracked_files:
            shared_path = tf["shared_path"]
            code, meta = transport.api_get(f"/api/file/metadata?path={shared_path}")
            if code == 200 and isinstance(meta, dict):
                server_ver = meta.get("version", 1)
                server_h = meta.get("hash")
                if server_ver > tf["server_version"] or server_h != tf["server_hash"]:
                    self.workspace_mgr.handle_server_version_update(
                        server_url=norm_server,
                        shared_path=shared_path,
                        new_version=server_ver,
                        new_hash=server_h
                    )

    def track_and_download(
        self,
        server_url: str,
        shared_path: str,
        local_path: str,
        token: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Downloads file from server, registers for local tracking, and starts watching it."""
        norm_server = server_url.rstrip("/")
        transport = self.get_transport(norm_server, token)

        # 1. Fetch metadata
        code, meta = transport.api_get(f"/api/file/metadata?path={shared_path}")
        if code != 200 or not isinstance(meta, dict):
            return False, f"Failed to get file metadata: {meta}", None

        server_ver = meta.get("version", 1)
        server_hash = meta.get("hash")

        # 2. Download content
        ok, content_bytes, err = transport.download_file(shared_path)
        if not ok or content_bytes is None:
            return False, f"Failed to download file: {err}", None

        # 3. Register tracked copy & write to disk
        tracked = self.workspace_mgr.register_tracked_file(
            server_url=norm_server,
            shared_path=shared_path,
            local_path=local_path,
            server_version=server_ver,
            server_hash=server_hash,
            content_bytes=content_bytes
        )

        # 4. Watch local file
        self.watcher.watch_file(local_path)

        # 5. Inform server of tracked local copy
        try:
            transport.api_post("/api/file/track_local_copy", {
                "shared_path": shared_path,
                "local_path": local_path,
                "version_hash": server_hash
            })
        except Exception:
            pass

        return True, "TRACKED", tracked

    def pull_server_version(
        self,
        local_path: str,
        force_overwrite: bool = False
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Pulls latest version from server into local file with strict conflict protection."""
        tracked = self.workspace_mgr.get_tracked_by_local_path(local_path)
        if not tracked:
            return False, "File is not tracked.", None

        server_url = tracked["server_url"]
        shared_path = tracked["shared_path"]
        transport = self.transports.get(server_url)
        if not transport:
            transport = self.get_transport(server_url)

        # Get server metadata
        code, meta = transport.api_get(f"/api/file/metadata?path={shared_path}")
        if code != 200 or not isinstance(meta, dict):
            return False, f"Server metadata check failed: {meta}", tracked

        server_ver = meta.get("version", tracked["server_version"])
        server_hash = meta.get("hash")

        # Download content
        ok, content_bytes, err = transport.download_file(shared_path)
        if not ok or content_bytes is None:
            return False, f"Download failed: {err}", tracked

        # Apply to local
        success, msg, updated = self.workspace_mgr.apply_server_version_to_local(
            local_path=local_path,
            server_version=server_ver,
            server_hash=server_hash,
            content_bytes=content_bytes,
            force_overwrite=force_overwrite
        )

        return success, msg, updated

    def commit_local_file(
        self,
        local_path: str,
        summary: Optional[str] = None,
        release_lock: bool = False
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Lock-aware commit of local modifications to server with base-version validation."""
        tracked = self.workspace_mgr.get_tracked_by_local_path(local_path)
        if not tracked:
            return False, "File is not tracked.", None

        local_p = Path(local_path)
        if not local_p.exists():
            return False, "Local file does not exist on disk.", tracked

        # Read current local content
        try:
            content_str = local_p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return False, "Binary file commits are currently not supported via text transport.", tracked
        except Exception as e:
            return False, f"Failed to read local file: {e}", tracked

        server_url = tracked["server_url"]
        shared_path = tracked["shared_path"]
        transport = self.transports.get(server_url)
        if not transport:
            transport = self.get_transport(server_url)

        # Verify active lock on server
        code, meta = transport.api_get(f"/api/file/metadata?path={shared_path}")
        if code != 200 or not isinstance(meta, dict):
            return False, f"Failed to verify file state on server: {meta}", tracked

        writer_info = meta.get("writer")
        if not writer_info:
            return False, "COMMIT_REJECTED: File has no active write lock. Request edit access first.", tracked

        lock_id = writer_info.get("lock_id")
        current_server_version = meta.get("version", 1)

        # Stale version check: client base_version must match server version
        local_base_version = tracked.get("base_version", tracked["server_version"])
        if local_base_version != current_server_version:
            # Mark CONFLICT
            self.workspace_mgr.handle_server_version_update(
                server_url, shared_path, current_server_version, meta.get("hash")
            )
            return False, f"CONFLICT: Server is at version {current_server_version}, but your local base is version {local_base_version}.", tracked

        # Execute commit
        commit_payload = {
            "file_path": shared_path,
            "lock_id": lock_id,
            "content": content_str,
            "summary": summary or f"Committed from local external editor ({Path(local_path).name})",
            "release_lock": release_lock,
            "base_version": local_base_version
        }

        c_code, c_resp = transport.api_post("/api/file/commit", commit_payload)
        if c_code != 200:
            err_msg = c_resp.get("detail") if isinstance(c_resp, dict) else str(c_resp)
            return False, f"Server rejected commit: {err_msg}", tracked

        new_version = c_resp["commit"]["version_number"]
        new_hash = c_resp["commit"]["content_hash"]

        # Update local tracking record to SYNCED
        updated = self.workspace_mgr.mark_committed_synced(local_path, new_version, new_hash)
        return True, "COMMITTED", updated

    def stop(self):
        self.watcher.stop()
        for t in self.transports.values():
            t.stop_realtime_listener()
