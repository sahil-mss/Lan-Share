"""E2E Test Suite for LANShare Phase 3 File Locking & Collaboration System.

Covers Tests 1 through 12 required by LANShare Phase 3 Specification:
- Test 1: Two simultaneous requests -> both recorded in queue, no duplicate writer.
- Test 2: Host grants A -> A is writer, B is queued.
- Test 3: B cannot commit -> COMMIT_REJECTED.
- Test 4: A commits -> Version increments monotonically, lock remains with A.
- Test 5: Reader during commit -> sees previous committed version until commit succeeds.
- Test 6: A releases -> lock removed (state AVAILABLE).
- Test 7: Host grants B -> B is writer.
- Test 8: Host revokes B -> B cannot commit afterward.
- Test 9: Old lock ID -> commit with expired/revoked lock rejected.
- Test 10: Two files -> A owns file1, B owns file2 simultaneously.
- Test 11: Disconnect -> writer disconnects, verify safe recovery / grace period release.
- Test 12: Server restart -> commits survive in SQLite, active locks do not resurrect.
"""

import sys
import json
import time
import urllib.request
import urllib.error
import threading
import subprocess
import shutil
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_URL = "http://127.0.0.1:7420"
TEST_ROOT = str(Path(__file__).parent.parent / "temp_phase3_e2e_ws")

def api_post(endpoint, data, token=None):
    url = f"{BASE_URL}{endpoint}"
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"detail": body}

def api_get(endpoint, token=None):
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"detail": body}

def run_tests():
    print("======================================================================")
    print("             LANShare Phase 3 - Tests 1 to 12 E2E Suite               ")
    print("======================================================================")

    # Clean and setup test workspace
    p = Path(TEST_ROOT)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)

    # Initial test files
    (p / "main.py").write_text("print('version 1')\n", encoding="utf-8")
    (p / "notes.txt").write_text("notes initial content\n", encoding="utf-8")

    # Start workspace
    host_payload = {
        "workspace_name": "Phase 3 E2E Workspace",
        "shared_root": TEST_ROOT,
        "password": "collab_secret_pass",
        "host_name": "HostOwner",
        "port": 7420
    }
    code, host_resp = api_post("/api/host/start", host_payload)
    assert code == 200, f"Host start failed: {host_resp}"
    host_token = host_resp["token"]
    print("[INIT] Host started workspace successfully.")

    # Connect client A and client B
    code, a_resp = api_post("/api/join", {"user_name": "Alice", "password": "collab_secret_pass"})
    assert code == 200
    token_a = a_resp["token"]
    id_a = a_resp["session"]["client_id"]

    code, b_resp = api_post("/api/join", {"user_name": "Bob", "password": "collab_secret_pass"})
    assert code == 200
    token_b = b_resp["token"]
    id_b = b_resp["session"]["client_id"]
    print(f"[INIT] Alice ({id_a[:8]}) and Bob ({id_b[:8]}) joined.")

    # -------------------------------------------------------------------------
    # TEST 1: Two simultaneous requests -> both recorded in queue, no duplicate writer
    # -------------------------------------------------------------------------
    print("\n--- Test 1: Two simultaneous requests ---")
    # First, let's verify file state is AVAILABLE
    code, meta = api_get("/api/file/metadata?path=main.py", host_token)
    assert code == 200 and meta["lock_state"] == "AVAILABLE"

    # Send requests from Alice and Bob concurrently
    req_res = []
    def do_request(tok, name):
        c, r = api_post("/api/lock/request", {"file_path": "main.py"}, tok)
        req_res.append((name, c, r))

    t1 = threading.Thread(target=do_request, args=(token_a, "Alice"))
    t2 = threading.Thread(target=do_request, args=(token_b, "Bob"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    code, meta1 = api_get("/api/file/metadata?path=main.py", host_token)
    assert code == 200
    # Invariant: active_writer_count <= 1
    # Exactly one is writer, other is in queue (or both in queue if auto-grant is disabled)
    has_writer = meta1["writer"] is not None
    queue_len = len(meta1["queue"])
    total_active = (1 if has_writer else 0) + queue_len
    assert total_active == 2, f"Expected 2 total records (writer + queue), got {total_active}"
    if has_writer:
        assert queue_len == 1, "Only 1 client can be writer; remaining must be queued."
    print(f"[PASS] Test 1: Invariant verified. Active writer count: {1 if has_writer else 0}, Queued: {queue_len}.")

    # -------------------------------------------------------------------------
    # TEST 2: Host grants A -> A is writer, B is queued
    # -------------------------------------------------------------------------
    print("\n--- Test 2: Host grants A -> A is writer, B is queued ---")
    # If A is already writer from auto-grant, verify B is queued. If not, host explicitly grants A.
    if not (meta1["writer"] and meta1["writer"]["client_id"] == id_a):
        # Revoke or reset to grant A
        if meta1["writer"]:
            api_post("/api/lock/host/revoke", {"file_path": "main.py"}, host_token)
            # Re-queue Alice and Bob
            api_post("/api/lock/request", {"file_path": "main.py"}, token_a)
            api_post("/api/lock/request", {"file_path": "main.py"}, token_b)
        code, grant_res = api_post("/api/lock/host/grant", {"file_path": "main.py", "target_client_id": id_a}, host_token)
        assert code == 200

    code, meta2 = api_get("/api/file/metadata?path=main.py", host_token)
    assert meta2["lock_state"] == "LOCKED"
    assert meta2["writer"]["client_id"] == id_a
    lock_id_a = meta2["writer"]["lock_id"]
    queue_client_ids = [q["client_id"] for q in meta2["queue"]]
    assert id_b in queue_client_ids
    print(f"[PASS] Test 2: Alice is verified writer (lock_id: {lock_id_a[:8]}), Bob is queued.")

    # -------------------------------------------------------------------------
    # TEST 3: B cannot commit -> COMMIT_REJECTED
    # -------------------------------------------------------------------------
    print("\n--- Test 3: Non-writer B cannot commit ---")
    code, rej_res = api_post("/api/file/commit", {
        "file_path": "main.py",
        "lock_id": "fake_lock_id_from_b",
        "content": "print('bob should fail')",
        "release_lock": False
    }, token_b)
    assert code in [400, 409], f"Bob commit should fail, got status {code}"
    print("[PASS] Test 3: Bob's commit was strictly rejected (COMMIT_REJECTED).")

    # -------------------------------------------------------------------------
    # TEST 4: A commits -> Version increments monotonically, lock remains with A
    # -------------------------------------------------------------------------
    print("\n--- Test 4: A commits -> Version increments monotonically, lock remains with A ---")
    code, commit_a_res = api_post("/api/file/commit", {
        "file_path": "main.py",
        "lock_id": lock_id_a,
        "content": "print('version 2 by Alice')\n",
        "summary": "Alice first commit",
        "release_lock": False  # lock remains with writer
    }, token_a)
    assert code == 200, f"Alice commit failed: {commit_a_res}"
    assert commit_a_res["commit"]["version_number"] == 2, f"Expected 2, got {commit_a_res['commit']['version_number']}"
    assert commit_a_res["commit"]["previous_version"] == 1
    assert commit_a_res["commit"]["author"] == "Alice"
    assert commit_a_res["commit"]["lock_released"] is False

    # Check file state: Alice still holds the lock!
    code, meta4 = api_get("/api/file/metadata?path=main.py", host_token)
    assert meta4["lock_state"] == "LOCKED"
    assert meta4["writer"]["client_id"] == id_a
    assert meta4["version"] == 2
    print(f"[PASS] Test 4: Committed version 2 monotonically. Alice retains write lock for further edits.")

    # -------------------------------------------------------------------------
    # TEST 5: Reader during commit -> sees previous committed version until commit succeeds
    # -------------------------------------------------------------------------
    print("\n--- Test 5: Reader during commit sees previous committed version ---")
    # We will do a second commit from Alice, while Bob continuously reads preview
    large_v3_content = "# Version 3 Commit\n" + ("data_row = 12345\n" * 3000)
    seen_contents = []

    def reader_check():
        for _ in range(25):
            c, prev = api_get("/api/file/preview?path=main.py", token_b)
            if c == 200 and prev.get("content"):
                seen_contents.append(prev["content"])
            time.sleep(0.005)

    r_thread = threading.Thread(target=reader_check)
    r_thread.start()

    code, commit_v3 = api_post("/api/file/commit", {
        "file_path": "main.py",
        "lock_id": lock_id_a,
        "content": large_v3_content,
        "summary": "Alice second commit v3",
        "release_lock": False
    }, token_a)
    assert code == 200

    r_thread.join()

    # Every read in seen_contents must either be Version 2 or the complete Version 3
    for content in seen_contents:
        assert ("version 2 by Alice" in content or "data_row = 12345" in content), f"Partial / corrupt read: {content[:40]}"
        if "data_row = 12345" in content:
            assert content.endswith("data_row = 12345\n"), "Truncated uncommitted or incomplete write read!"
    print("[PASS] Test 5: Readers saw valid committed version throughout commit process; no partial reads.")

    # -------------------------------------------------------------------------
    # TEST 6: A releases -> lock removed (state AVAILABLE)
    # -------------------------------------------------------------------------
    print("\n--- Test 6: A releases -> lock removed ---")
    # First, let's remove Bob from queue temporarily to verify clean AVAILABLE state
    api_post("/api/lock/cancel", {"file_path": "main.py"}, token_b)

    code, rel_res = api_post("/api/lock/release", {
        "file_path": "main.py",
        "lock_id": lock_id_a
    }, token_a)
    assert code == 200

    code, meta6 = api_get("/api/file/metadata?path=main.py", host_token)
    assert meta6["lock_state"] == "AVAILABLE"
    assert meta6["writer"] is None
    print("[PASS] Test 6: Lock released by Alice. State transitioned to AVAILABLE.")

    # -------------------------------------------------------------------------
    # TEST 7: Host grants B -> B is writer
    # -------------------------------------------------------------------------
    print("\n--- Test 7: Host grants B -> B is writer ---")
    # Bob requests edit access
    api_post("/api/lock/request", {"file_path": "main.py"}, token_b)
    # Host grants Bob (or Bob was granted)
    code, meta7_pre = api_get("/api/file/metadata?path=main.py", host_token)
    if not (meta7_pre["writer"] and meta7_pre["writer"]["client_id"] == id_b):
        api_post("/api/lock/host/grant", {"file_path": "main.py", "target_client_id": id_b}, host_token)

    code, meta7 = api_get("/api/file/metadata?path=main.py", host_token)
    assert meta7["lock_state"] == "LOCKED"
    assert meta7["writer"]["client_id"] == id_b
    lock_id_b = meta7["writer"]["lock_id"]
    print(f"[PASS] Test 7: Bob is granted write lock (lock_id: {lock_id_b[:8]}).")

    # -------------------------------------------------------------------------
    # TEST 8: Host revokes B -> B cannot commit afterward
    # -------------------------------------------------------------------------
    print("\n--- Test 8: Host revokes B -> B cannot commit afterward ---")
    code, rev_res = api_post("/api/lock/host/revoke", {
        "file_path": "main.py",
        "reason": "Host needed to revoke"
    }, host_token)
    assert code == 200

    # Bob attempts to commit with revoked lock
    code, rev_commit = api_post("/api/file/commit", {
        "file_path": "main.py",
        "lock_id": lock_id_b,
        "content": "print('bob commits after revoke')",
        "release_lock": False
    }, token_b)
    assert code in [400, 409], f"Bob committed after revocation! Code: {code}"
    print("[PASS] Test 8: Host successfully revoked Bob; subsequent commit strictly rejected.")

    # -------------------------------------------------------------------------
    # TEST 9: Old lock ID -> commit with expired/revoked lock rejected
    # -------------------------------------------------------------------------
    print("\n--- Test 9: Stale/Old lock ID rejected ---")
    # Alice attempts to commit using her old lock_id_a from previous lock session
    code, old_lid_commit = api_post("/api/file/commit", {
        "file_path": "main.py",
        "lock_id": lock_id_a,
        "content": "print('alice stale lock commit')",
        "release_lock": False
    }, token_a)
    assert code in [400, 409], f"Old lock ID commit accepted! Code: {code}"
    print("[PASS] Test 9: Old/stale lock ID commit rejected by server.")

    # -------------------------------------------------------------------------
    # TEST 10: Two files -> A owns file1, B owns file2 simultaneously
    # -------------------------------------------------------------------------
    print("\n--- Test 10: Two files -> Alice owns main.py, Bob owns notes.txt simultaneously ---")
    code, l_main = api_post("/api/lock/request", {"file_path": "main.py"}, token_a)
    assert code == 200
    code, l_notes = api_post("/api/lock/request", {"file_path": "notes.txt"}, token_b)
    assert code == 200

    # Host grants access to Alice for main.py and Bob for notes.txt
    api_post("/api/lock/host/grant", {"file_path": "main.py", "target_client_id": id_a}, host_token)
    api_post("/api/lock/host/grant", {"file_path": "notes.txt", "target_client_id": id_b}, host_token)

    code, m_main = api_get("/api/file/metadata?path=main.py", host_token)
    code, m_notes = api_get("/api/file/metadata?path=notes.txt", host_token)
    assert m_main["writer"] is not None and m_main["writer"]["client_id"] == id_a
    assert m_notes["writer"] is not None and m_notes["writer"]["client_id"] == id_b
    print(f"[PASS] Test 10: Independent per-file locking verified (main.py -> Alice, notes.txt -> Bob).")

    # Clean up locks
    api_post("/api/lock/release", {"file_path": "main.py", "lock_id": m_main["writer"]["lock_id"]}, token_a)
    api_post("/api/lock/release", {"file_path": "notes.txt", "lock_id": m_notes["writer"]["lock_id"]}, token_b)

    # -------------------------------------------------------------------------
    # TEST 11: Disconnect -> writer disconnects, verify safe recovery / grace period
    # -------------------------------------------------------------------------
    print("\n--- Test 11: Disconnect handling and safe lock recovery ---")
    # Alice locks notes.txt
    api_post("/api/lock/request", {"file_path": "notes.txt"}, token_a)
    api_post("/api/lock/host/grant", {"file_path": "notes.txt", "target_client_id": id_a}, host_token)
    code, m_disc = api_get("/api/file/metadata?path=notes.txt", host_token)
    assert m_disc["writer"] is not None and m_disc["writer"]["client_id"] == id_a

    # Alice disconnects (leaves)
    api_post("/api/leave", {}, token_a)
    time.sleep(0.15)

    code, m_after_disc = api_get("/api/file/metadata?path=notes.txt", host_token)
    assert m_after_disc["lock_state"] == "AVAILABLE"
    assert m_after_disc["writer"] is None
    print("[PASS] Test 11: Writer disconnection cleanly released file back to AVAILABLE.")

    # -------------------------------------------------------------------------
    # TEST 12: Server restart -> commits survive in SQLite, active locks do not resurrect
    # -------------------------------------------------------------------------
    print("\n--- Test 12: Server restart resilience ---")
    # First, let's verify sqlite DB on disk directly
    db_file = Path(TEST_ROOT) / ".lanshare" / "lanshare.db"
    assert db_file.exists(), "Persistent database file not found!"

    import sqlite3
    with sqlite3.connect(str(db_file)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT version_number, author, summary FROM file_commits WHERE file_path = 'main.py' ORDER BY version_number ASC")
        rows = cursor.fetchall()
        assert len(rows) >= 2, f"Expected at least 2 recorded commits, got {len(rows)}"
        print(f"[DB] Verified {len(rows)} commits stored persistently in SQLite: {rows}")

        # Check file_versions table
        cursor.execute("SELECT current_version, last_author FROM file_versions WHERE file_path = 'main.py'")
        v_row = cursor.fetchone()
        assert v_row is not None and v_row[0] >= 3, f"Expected version >= 3, got {v_row}"
        print(f"[DB] Verified file_versions record: version={v_row[0]}, author={v_row[1]}")

    # Re-initialize FileLockManager directly against same db to simulate server reboot
    from server.locking import FileLockManager
    from server.filesystem import FileSystemManager
    fs = FileSystemManager(TEST_ROOT)
    rebooted_lock_mgr = FileLockManager(db_file, fs)

    # Check file state on rebooted lock manager
    state_after_reboot = rebooted_lock_mgr.get_file_state("main.py")
    assert state_after_reboot["version"] >= 3, "Committed version lost after reboot!"
    assert state_after_reboot["state"] == "AVAILABLE", "Stale in-memory lock resurrected after reboot!"
    assert state_after_reboot["writer"] is None, "Writer present after reboot!"
    assert state_after_reboot["queue_count"] == 0, "Queue resurrected after reboot!"

    commits_after_reboot = rebooted_lock_mgr.get_commit_history("main.py")
    assert len(commits_after_reboot) >= 2, "Commit history lost after reboot!"
    print(f"[PASS] Test 12: Server restart simulated. Commits and version numbers survived in SQLite; stale in-memory locks did NOT resurrect.")

    print("\n======================================================================")
    print("      ALL 12 PHASE 3 TESTS (TEST 1 - TEST 12) PASSED SUCCESSFULLY     ")
    print("======================================================================")

if __name__ == "__main__":
    run_tests()
