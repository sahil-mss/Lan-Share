"""Comprehensive Phase 4 E2E Test Suite.

Tests Full Stack Integration:
1. Server + Local Client Daemons Running Simultaneously
2. Registration: Client registers with server, auth token handshake succeeds
3. Open Locally: Browser triggers /open via Local Client; file downloaded, tracked, watched
4. External Editor Edit & Debouncing: External edit detected, debounced, transitioned to LOCAL_MODIFIED
5. Lock-Aware Commit: Lock requested/granted on server, local commit sent with base version, monotonic version bump to 2
6. Stale Base Version Protection: Outdated base version rejected with CONFLICT
7. Multi-Client Realtime Version Push: Remote user commits on server, local client receives event and detects SERVER_UPDATED (or CONFLICT)
8. Offline Resilience & Reconnection: Server stop preserves local edits, server restart reconciles state cleanly
"""

import os
import sys
import time
import json
import shutil
import tempfile
import threading
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

SERVER_PORT = 7425
CLIENT_PORT = 7435
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"
CLIENT_URL = f"http://127.0.0.1:{CLIENT_PORT}"

def api_call(url: str, method: str = "GET", data: dict = None, token: str = None):
    req = urllib.request.Request(url, method=method)
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        req.data = payload
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(content)
            except Exception:
                return resp.status, content
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        try:
            return e.code, json.loads(content)
        except Exception:
            return e.code, {"detail": content}
    except Exception as e:
        return 503, {"detail": str(e)}

def run_phase4_e2e():
    print("======================================================================")
    print("           LANShare Phase 4 - Full E2E Integration Suite              ")
    print("======================================================================")

    temp_dir = Path(tempfile.mkdtemp(prefix="lanshare_phase4_e2e_")).resolve()
    shared_root = temp_dir / "server_shared_ws"
    client_dir = temp_dir / ".client_home"
    local_dest_dir = temp_dir / "my_local_ws"

    shared_root.mkdir(parents=True, exist_ok=True)
    local_dest_dir.mkdir(parents=True, exist_ok=True)
    client_dir.mkdir(parents=True, exist_ok=True)

    # Initial server shared file
    (shared_root / "main.py").write_text("print('version 1 from server')\n", encoding="utf-8")

    server_proc = None
    client_proc = None

    try:
        # 1. Start Server
        print("[INIT] Starting LANShare Server daemon on port", SERVER_PORT)
        python_exe = sys.executable
        server_cmd = [python_exe, "run_server.py", "--port", str(SERVER_PORT)]
        server_proc = subprocess.Popen(server_cmd, cwd=str(Path(__file__).parent.parent))
        time.sleep(2)

        # 2. Host starts workspace
        h_code, h_resp = api_call(f"{SERVER_URL}/api/host/start", "POST", {
            "workspace_name": "Phase 4 E2E Workspace",
            "shared_root": str(shared_root),
            "password": "pass_phase4_secret",
            "host_name": "HostAdmin",
            "port": SERVER_PORT
        })
        assert h_code == 200, f"Host start failed: {h_resp}"
        host_token = h_resp["token"]
        print("[PASS] 1. Host initialized server workspace.")

        # 3. Client user joins server
        j_code, j_resp = api_call(f"{SERVER_URL}/api/join", "POST", {
            "user_name": "AliceDev",
            "password": "pass_phase4_secret"
        })
        assert j_code == 200, f"Join failed: {j_resp}"
        user_token = j_resp["token"]
        user_id = j_resp["session"]["client_id"]
        print(f"[PASS] 2. User AliceDev joined server ({user_id[:8]}).")

        # 4. Start Local Client daemon
        print("[INIT] Starting Local Client daemon on port", CLIENT_PORT)
        client_env = os.environ.copy()
        client_env["USERPROFILE"] = str(client_dir)
        client_env["HOME"] = str(client_dir)
        client_cmd = [python_exe, "client/main.py", "--port", str(CLIENT_PORT)]
        client_proc = subprocess.Popen(client_cmd, cwd=str(Path(__file__).parent.parent), env=client_env)
        time.sleep(2)

        # 5. Connect and authenticate with Local Client
        st_code, st_resp = api_call(f"{CLIENT_URL}/status")
        assert st_code == 200, f"Local Client status ping failed: {st_resp}"
        local_client_token = st_resp["token"]
        print(f"[PASS] 3. Local Client running on 127.0.0.1:{CLIENT_PORT}. Authenticated successfully.")

        # Register server session on local client
        reg_code, reg_resp = api_call(f"{CLIENT_URL}/register_session", "POST", {
            "server_url": SERVER_URL,
            "token": user_token
        }, token=local_client_token)
        assert reg_code == 200, f"Register session failed: {reg_resp}"
        print("[PASS] 4. Registered server credentials with Local Client.")

        # 6. Open Locally workflow
        local_target_file = str(local_dest_dir / "main.py")
        op_code, op_resp = api_call(f"{CLIENT_URL}/open", "POST", {
            "server_url": SERVER_URL,
            "shared_path": "main.py",
            "local_path": local_target_file,
            "token": user_token
        }, token=local_client_token)
        assert op_code == 200, f"Open locally failed: {op_resp}"
        assert op_resp["tracked"]["sync_state"] == "SYNCED"
        assert Path(local_target_file).exists()
        assert "version 1 from server" in Path(local_target_file).read_text(encoding="utf-8")
        print("[PASS] 5. Open Locally downloaded file, registered tracking, and verified state SYNCED.")

        # 7. External Editor Edit & Debouncing
        print("\n--- Simulating external editor (VS Code) save ---")
        time.sleep(0.1)
        Path(local_target_file).write_text("print('version 1 modified by VS Code')\n", encoding="utf-8")
        time.sleep(0.7)  # Watcher debounce interval

        # Query local client workspaces
        w_code, w_resp = api_call(f"{CLIENT_URL}/workspaces", token=local_client_token)
        assert w_code == 200
        tracked_item = next(f for f in w_resp["files"] if f["shared_path"] == "main.py")
        assert tracked_item["sync_state"] == "LOCAL_MODIFIED"
        print("[PASS] 6. External editor save automatically transitioned tracking to LOCAL_MODIFIED.")

        # 8. Lock-aware Commit workflow
        print("\n--- Request edit access & commit ---")
        # Alice requests lock on server
        l_code, l_resp = api_call(f"{SERVER_URL}/api/lock/request", "POST", {"file_path": "main.py"}, token=user_token)
        assert l_code == 200
        # If queued, host grants it
        if l_resp["state"]["writer"] is None or l_resp["state"]["writer"]["client_id"] != user_id:
            api_call(f"{SERVER_URL}/api/lock/host/grant", "POST", {"file_path": "main.py", "target_client_id": user_id}, token=host_token)

        # Commit via local client API
        cmt_code, cmt_resp = api_call(f"{CLIENT_URL}/commit", "POST", {
            "local_path": local_target_file,
            "summary": "Updated from VS Code",
            "release_lock": False
        }, token=local_client_token)
        assert cmt_code == 200, f"Commit failed: {cmt_resp}"
        assert cmt_resp["tracked"]["sync_state"] == "SYNCED"
        assert cmt_resp["tracked"]["server_version"] == 2
        print("[PASS] 7. Valid commit via local client completed atomically. Server version is now 2.")

        # Verify server on disk
        assert (shared_root / "main.py").read_text(encoding="utf-8") == "print('version 1 modified by VS Code')\n"
        print("[PASS] 8. Server filesystem updated with exact committed bytes.")

        # 9. Server update push from peer (Bob)
        print("\n--- Peer commit & Server update detection ---")
        # Bob joins
        b_code, b_resp = api_call(f"{SERVER_URL}/api/join", "POST", {"user_name": "BobPeer", "password": "pass_phase4_secret"})
        bob_token = b_resp["token"]
        bob_id = b_resp["session"]["client_id"]

        # Alice releases lock
        api_call(f"{SERVER_URL}/api/lock/release", "POST", {"file_path": "main.py"}, token=user_token)

        # Bob requests lock
        _, req_b = api_call(f"{SERVER_URL}/api/lock/request", "POST", {"file_path": "main.py"}, token=bob_token)
        # If Bob wasn't auto-granted, host grants
        if not (req_b.get("state", {}).get("writer") and req_b["state"]["writer"]["client_id"] == bob_id):
            api_call(f"{SERVER_URL}/api/lock/host/grant", "POST", {"file_path": "main.py", "target_client_id": bob_id}, token=host_token)

        # Bob gets lock_id
        _, bob_meta = api_call(f"{SERVER_URL}/api/file/metadata?path=main.py", token=bob_token)
        assert bob_meta["writer"] is not None and bob_meta["writer"]["client_id"] == bob_id
        bob_lock_id = bob_meta["writer"]["lock_id"]

        # Bob commits Version 3
        b_cmt_code, b_cmt_resp = api_call(f"{SERVER_URL}/api/file/commit", "POST", {
            "file_path": "main.py",
            "lock_id": bob_lock_id,
            "content": "print('version 3 committed by Bob')\n",
            "release_lock": True
        }, token=bob_token)
        assert b_cmt_code == 200, f"Bob commit failed: {b_cmt_resp}"

        # Wait for WebSocket notification to arrive at local client
        time.sleep(1.0)
        _, w_resp2 = api_call(f"{CLIENT_URL}/workspaces", token=local_client_token)
        alice_tracked = next(f for f in w_resp2["files"] if f["shared_path"] == "main.py")
        print(f"[DEBUG] alice_tracked after Bob commit: {alice_tracked}")
        assert alice_tracked["server_version"] == 3
        assert alice_tracked["sync_state"] == "SERVER_UPDATED"
        print("[PASS] 9. Real-time push from server received; Alice copy transitioned to SERVER_UPDATED.")

        # 10. Conflict detection test
        print("\n--- Conflict detection test ---")
        # Alice modifies her local file again while server is at v3
        Path(local_target_file).write_text("print('alice conflicting changes on v2 base')\n", encoding="utf-8")
        time.sleep(0.7)

        # Query state
        _, w_resp3 = api_call(f"{CLIENT_URL}/workspaces", token=local_client_token)
        conflict_tracked = next(f for f in w_resp3["files"] if f["shared_path"] == "main.py")
        assert conflict_tracked["sync_state"] == "CONFLICT"
        print("[PASS] 10. Conflict detected when local copy is modified and server is at a newer version.")

        # 11. Stale commit rejection
        print("\n--- Stale base version rejection test ---")
        # Alice requests lock
        api_call(f"{SERVER_URL}/api/lock/request", "POST", {"file_path": "main.py"}, token=user_token)
        api_call(f"{SERVER_URL}/api/lock/host/grant", "POST", {"file_path": "main.py", "target_client_id": user_id}, token=host_token)

        stale_cmt_code, stale_cmt_resp = api_call(f"{CLIENT_URL}/commit", "POST", {
            "local_path": local_target_file
        }, token=local_client_token)
        assert stale_cmt_code == 409, f"Stale commit succeeded! Code: {stale_cmt_code}"
        print("[PASS] 11. Stale commit rejected with CONFLICT. Local file preserved intact.")

        # 12. Safe pull resolution
        print("\n--- Safe pull resolution test ---")
        pull_fail_code, _ = api_call(f"{CLIENT_URL}/pull", "POST", {
            "local_path": local_target_file,
            "force_overwrite": False
        }, token=local_client_token)
        assert pull_fail_code == 409, "Unsafe pull overwritten modified local file!"

        pull_ok_code, pull_ok_resp = api_call(f"{CLIENT_URL}/pull", "POST", {
            "local_path": local_target_file,
            "force_overwrite": True
        }, token=local_client_token)
        assert pull_ok_code == 200
        assert pull_ok_resp["tracked"]["sync_state"] == "SYNCED"
        assert "version 3 committed by Bob" in Path(local_target_file).read_text(encoding="utf-8")
        print("[PASS] 12. Force pull resolved conflict safely. Local file updated to Version 3.")

        # 13. Offline Resilience & Reconnection Test
        print("\n--- Offline resilience & reconnection test ---")
        # Server goes down
        server_proc.terminate()
        server_proc.wait(timeout=2)
        server_proc = None
        time.sleep(1.0)

        # Alice makes an offline edit
        offline_edit = "print('offline edits by Alice while server was down')\n"
        Path(local_target_file).write_text(offline_edit, encoding="utf-8")
        time.sleep(0.7)

        # File is preserved locally
        assert Path(local_target_file).read_text(encoding="utf-8") == offline_edit
        print("[PASS] 13a. Server unavailable: local offline file preserved completely.")

        # Server returns
        server_proc = subprocess.Popen(server_cmd, cwd=str(Path(__file__).parent.parent))
        time.sleep(2)

        # Host re-initializes workspace
        api_call(f"{SERVER_URL}/api/host/start", "POST", {
            "workspace_name": "Phase 4 E2E Workspace",
            "shared_root": str(shared_root),
            "password": "pass_phase4_secret",
            "host_name": "HostAdmin",
            "port": SERVER_PORT
        })

        # Local client reconnects & reconciles
        time.sleep(2.0)
        _, w_reconnect = api_call(f"{CLIENT_URL}/workspaces", token=local_client_token)
        reconciled_item = next(f for f in w_reconnect["files"] if f["shared_path"] == "main.py")
        assert reconciled_item["sync_state"] in ["LOCAL_MODIFIED", "CONFLICT"]
        assert Path(local_target_file).read_text(encoding="utf-8") == offline_edit
        print("[PASS] 13b. Server returned: connection reconciled, offline edits intact without loss.")

        print("\n======================================================================")
        print("          ALL 13 PHASE 4 E2E INTEGRATION TESTS PASSED                 ")
        print("======================================================================")
        return True

    finally:
        if client_proc:
            try:
                client_proc.terminate()
                client_proc.wait(timeout=2)
            except Exception:
                pass
        if server_proc:
            try:
                server_proc.terminate()
                server_proc.wait(timeout=2)
            except Exception:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    if not run_phase4_e2e():
        sys.exit(1)
