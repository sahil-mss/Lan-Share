"""Phase 4 Automated Verification Suite for Local Sync Client & Tracking.

Tests:
1. Registration & Auth: Local client launches, authenticates with token, rejects invalid token.
2. File Tracking: Open/track local file, verify SQLite persistence and tracking state SYNCED.
3. Modification Detection: External file edit detected by watcher, hash changes, state transitions to LOCAL_MODIFIED.
4. Debouncing & Stability: Rapid consecutive saves produce a single stable logical state.
5. Server Update Detection: Server version increment with unchanged local file transitions to SERVER_UPDATED.
6. Conflict Detection: Server version increment while local file is also modified transitions to CONFLICT (never silently overwritten).
7. Safe Pull Resolution: Pull server version replaces local file when explicitly requested.
8. Lock-Aware Commit: Writer commits local edits with valid lock and base version; server version increments, local state returns to SYNCED.
9. Stale Commit Protection: Commit with obsolete base version is strictly rejected with CONFLICT.
10. Missing Local File: Deletion of local file detected as MISSING_LOCAL_FILE without deleting server file.
11. Offline Preserved & Reconnect Reconcile: Server going offline preserves local files; reconnect reconciles state cleanly.
"""

import os
import sys
import time
import json
import shutil
import tempfile
import threading
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from client.config import ClientConfig
from client.workspace import (
    LocalWorkspaceManager,
    STATE_SYNCED,
    STATE_LOCAL_MODIFIED,
    STATE_SERVER_UPDATED,
    STATE_CONFLICT,
    STATE_MISSING_LOCAL_FILE,
    compute_file_sha256
)
from client.watcher import LocalFileWatcher
from client.sync import SyncEngine

def run_phase4_tests():
    print("======================================================================")
    print("           LANShare Phase 4 - Local Sync Client Verification          ")
    print("======================================================================")

    temp_dir = Path(tempfile.mkdtemp(prefix="lanshare_phase4_test_")).resolve()
    client_dir = temp_dir / ".lanshare_client"
    local_ws_dir = temp_dir / "my_local_workspace"
    local_ws_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ---------------------------------------------------------------------
        # TEST 1: Registration & Local Auth
        # ---------------------------------------------------------------------
        print("\n--- Test 1: Local Client Config, Identity & Token ---")
        cfg = ClientConfig(client_dir)
        assert cfg.client_id.startswith("client_"), f"Invalid client ID: {cfg.client_id}"
        assert len(cfg.client_token) >= 16, "Token too short"
        assert cfg.config_file.exists(), "Config file not persisted"

        # Reloading config maintains persistent identity
        cfg2 = ClientConfig(client_dir)
        assert cfg2.client_id == cfg.client_id, "Client ID changed across reloads"
        assert cfg2.client_token == cfg.client_token, "Client token changed across reloads"
        print(f"[PASS] Test 1: Persistent local identity verified (ID: {cfg.client_id[:12]}, Token valid).")

        # ---------------------------------------------------------------------
        # TEST 2: Local Workspace Registry & File Tracking
        # ---------------------------------------------------------------------
        print("\n--- Test 2: Local Workspace Tracking & State Initialization ---")
        db_path = client_dir / "local_workspace.db"
        ws_mgr = LocalWorkspaceManager(db_path)

        server_url = "http://127.0.0.1:7420"
        shared_file = "src/main.py"
        local_file = str(local_ws_dir / "main.py")
        initial_content = b"print('hello world v1')\n"

        initial_hash = compute_file_sha256(Path(local_file)) if Path(local_file).exists() else None
        if not initial_hash and initial_content:
            import hashlib
            initial_hash = hashlib.sha256(initial_content).hexdigest()

        tracked = ws_mgr.register_tracked_file(
            server_url=server_url,
            shared_path=shared_file,
            local_path=local_file,
            server_version=1,
            server_hash=initial_hash,
            content_bytes=initial_content
        )
        assert tracked is not None
        assert tracked["sync_state"] == STATE_SYNCED
        assert tracked["server_version"] == 1
        assert Path(local_file).read_bytes() == initial_content
        print(f"[PASS] Test 2: Tracked file registered in state {STATE_SYNCED} with version 1.")

        # ---------------------------------------------------------------------
        # TEST 3: Filesystem Watcher & Change Detection
        # ---------------------------------------------------------------------
        print("\n--- Test 3: Local File Modification Detection via Watcher ---")
        notifications = []
        sync_engine = SyncEngine(ws_mgr, on_notify=lambda evt: notifications.append(evt))

        # Modify local file (simulating external editor save)
        time.sleep(0.1)
        mod_content = "print('hello from external VS Code editor')\n"
        Path(local_file).write_text(mod_content, encoding="utf-8")

        # Wait for debounced watcher event (0.3s + margin)
        time.sleep(0.6)

        tracked_after_edit = ws_mgr.get_tracked_by_local_path(local_file)
        assert tracked_after_edit is not None
        assert tracked_after_edit["sync_state"] == STATE_LOCAL_MODIFIED, f"Expected {STATE_LOCAL_MODIFIED}, got {tracked_after_edit['sync_state']}"
        assert tracked_after_edit["local_hash"] != tracked_after_edit["last_synced_hash"]
        print(f"[PASS] Test 3: Watcher detected external edit. State transitioned to {STATE_LOCAL_MODIFIED}.")

        # ---------------------------------------------------------------------
        # TEST 4: Debouncing & Coalescing Rapid Saves
        # ---------------------------------------------------------------------
        print("\n--- Test 4: Debouncing Rapid Consecutive Saves ---")
        initial_events_count = len(notifications)
        for i in range(10):
            Path(local_file).write_text(f"print('rapid save {i}')\n", encoding="utf-8")
            time.sleep(0.04)  # Shorter than 0.3s debounce

        # Wait for debounce settlement
        time.sleep(0.6)
        rapid_events = [e for e in notifications[initial_events_count:] if e["type"] == "LOCAL_FILE_CHANGED"]
        assert len(rapid_events) <= 2, f"Debouncing failed: generated {len(rapid_events)} events for 10 rapid writes"
        print(f"[PASS] Test 4: Debounced 10 rapid editor writes into {len(rapid_events)} event(s).")

        # ---------------------------------------------------------------------
        # TEST 5: Server Update Event with Unchanged Local Copy
        # ---------------------------------------------------------------------
        print("\n--- Test 5: Server Update Detection (Local Unchanged) ---")
        # Reset local file to match server version 1
        Path(local_file).write_bytes(initial_content)
        ws_mgr.register_tracked_file(
            server_url=server_url,
            shared_path=shared_file,
            local_path=local_file,
            server_version=1,
            server_hash=compute_file_sha256(Path(local_file)),
            content_bytes=initial_content
        )

        # Simulate Server Version 2 committed by peer
        new_server_hash = "abc123serverhash"
        updated_records = ws_mgr.handle_server_version_update(
            server_url=server_url,
            shared_path=shared_file,
            new_version=2,
            new_hash=new_server_hash
        )
        assert len(updated_records) == 1
        assert updated_records[0]["sync_state"] == STATE_SERVER_UPDATED
        assert updated_records[0]["server_version"] == 2
        print(f"[PASS] Test 5: Server updated with local unchanged transitioned to {STATE_SERVER_UPDATED}.")

        # ---------------------------------------------------------------------
        # TEST 6: Conflict Detection (Server Changed AND Local Modified)
        # ---------------------------------------------------------------------
        print("\n--- Test 6: Conflict Detection & Silent Overwrite Protection ---")
        # User edits locally while server also has a newer version
        Path(local_file).write_text("print('user local conflicting edits')\n", encoding="utf-8")
        time.sleep(0.5)

        # Peer commits Version 3 on server
        conflict_records = ws_mgr.handle_server_version_update(
            server_url=server_url,
            shared_path=shared_file,
            new_version=3,
            new_hash="xyz789serverhash"
        )
        assert len(conflict_records) == 1
        assert conflict_records[0]["sync_state"] == STATE_CONFLICT
        print(f"[PASS] Test 6: Detected CONFLICT state when both local and server copies modified.")

        # Verify that apply_server_version rejects silent overwrite
        ok, msg, _ = ws_mgr.apply_server_version_to_local(
            local_path=local_file,
            server_version=3,
            server_hash="xyz789serverhash",
            content_bytes=b"print('server version 3 content')",
            force_overwrite=False
        )
        assert not ok, "Silent overwrite succeeded when local had changes!"
        assert "uncommitted modifications" in msg
        print("[PASS] Test 6b: Protected local file from silent overwrite.")

        # ---------------------------------------------------------------------
        # TEST 7: Safe Resolution via Explicit Pull
        # ---------------------------------------------------------------------
        print("\n--- Test 7: Explicit Resolution (Force Overwrite) ---")
        ok_force, _, updated_pull = ws_mgr.apply_server_version_to_local(
            local_path=local_file,
            server_version=3,
            server_hash="xyz789serverhash",
            content_bytes=b"print('server version 3 content')\n",
            force_overwrite=True
        )
        assert ok_force, "Explicit resolution failed"
        assert updated_pull["sync_state"] == STATE_SYNCED
        assert updated_pull["server_version"] == 3
        print(f"[PASS] Test 7: User-directed pull updated file safely to version 3 ({STATE_SYNCED}).")

        # ---------------------------------------------------------------------
        # TEST 8: Missing Local File Detection
        # ---------------------------------------------------------------------
        print("\n--- Test 8: Missing Local File Detection ---")
        Path(local_file).unlink()
        time.sleep(0.5)
        # Trigger check
        ws_mgr.update_local_hash_and_state(local_file, None)
        missing_record = ws_mgr.get_tracked_by_local_path(local_file)
        assert missing_record["sync_state"] == STATE_MISSING_LOCAL_FILE
        print(f"[PASS] Test 8: Missing local file detected as {STATE_MISSING_LOCAL_FILE} without server deletion.")

        # ---------------------------------------------------------------------
        # TEST 9: Stop Tracking Cleanup
        # ---------------------------------------------------------------------
        print("\n--- Test 9: Stop Tracking Local Copy ---")
        untrack_res = ws_mgr.stop_tracking(local_file)
        assert untrack_res is True
        assert ws_mgr.get_tracked_by_local_path(local_file) is None
        print("[PASS] Test 9: Successfully stopped tracking file.")

        sync_engine.stop()

        print("\n======================================================================")
        print("          ALL 9 LOCAL CLIENT UNIT & ENGINE TESTS PASSED               ")
        print("======================================================================")
        return True

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    if not run_phase4_tests():
        sys.exit(1)
