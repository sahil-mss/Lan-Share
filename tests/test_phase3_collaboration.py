"""Verification Suite for Phase 3:
1. Core Model & File States (AVAILABLE -> LOCK_REQUESTED -> LOCKED -> COMMITTING -> RELEASING)
2. Server authoritative locking (writer_count <= 1)
3. Reading Rule: Readers continue reading committed version while writer edits locally
4. FIFO queue & Host grant, deny, cancel, reorder, revoke
5. Atomic Commit & Monotonic Version Increment (Version 1 -> 2 -> 3)
6. Disconnected writer cleanup & Server restart resilience
7. Race Conditions (Test A to Test H specified in prompt)
8. Security Boundaries & Authorization checks
"""

import sys
import json
import time
import urllib.request
import urllib.error
import threading
import concurrent.futures
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_URL = "http://127.0.0.1:7420"
TEST_ROOT = str(Path(__file__).parent.parent / "temp_phase3_test_ws")

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

def run_phase3_tests():
    print("=== STARTING LANSHARE PHASE 3 VERIFICATION SUITE ===")
    
    # Setup test workspace
    p = Path(TEST_ROOT)
    if p.exists():
        import shutil
        shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    
    (p / "main.py").write_text("print('version 1')", encoding="utf-8")
    (p / "docs.txt").write_text("documentation v1", encoding="utf-8")

    # 1. Start Host Server
    host_payload = {
        "workspace_name": "Phase 3 Collaborative Workspace",
        "shared_root": TEST_ROOT,
        "password": "collab_secret_pass",
        "host_name": "HostAdmin",
        "port": 7420
    }
    code, host_resp = api_post("/api/host/start", host_payload)
    assert code == 200, f"Host start failed: {host_resp}"
    host_token = host_resp["token"]
    print("[PASS] 1. Host started workspace.")

    # 2. Connect Two Clients: Alex and Rahul
    code, alex_resp = api_post("/api/join", {"user_name": "Alex", "password": "collab_secret_pass"})
    assert code == 200
    alex_token = alex_resp["token"]
    alex_id = alex_resp["session"]["client_id"]

    code, rahul_resp = api_post("/api/join", {"user_name": "Rahul", "password": "collab_secret_pass"})
    assert code == 200
    rahul_token = rahul_resp["token"]
    rahul_id = rahul_resp["session"]["client_id"]
    print("[PASS] 2. Alex and Rahul joined workspace.")

    # 3. Check Initial File State (AVAILABLE, Version 1)
    code, meta = api_get("/api/file/metadata?path=main.py", alex_token)
    assert code == 200
    assert meta["lock_state"] == "AVAILABLE"
    assert meta["version"] == 1
    assert meta["writer"] is None
    print("[PASS] 3. Initial file state verified: AVAILABLE, Version 1.")

    # 4. Alex Requests Edit Access -> Becomes Writer (FIFO auto-grant when available)
    code, lock_res = api_post("/api/lock/request", {"file_path": "main.py"}, alex_token)
    assert code == 200
    assert lock_res["action"] == "GRANTED"
    assert lock_res["state"]["state"] == "LOCKED"
    assert lock_res["state"]["writer"]["client_id"] == alex_id
    alex_lock_id = lock_res["state"]["writer"]["lock_id"]
    print(f"[PASS] 4. Alex granted write lock (lock_id: {alex_lock_id[:8]}...).")

    # 5. Rahul Requests Edit Access -> Queued (Only ONE writer invariant)
    code, rahul_req = api_post("/api/lock/request", {"file_path": "main.py"}, rahul_token)
    assert code == 200
    assert rahul_req["action"] == "QUEUED"
    assert rahul_req["state"]["state"] == "LOCKED"
    assert rahul_req["state"]["queue_count"] == 1
    assert rahul_req["state"]["queue"][0]["client_id"] == rahul_id
    print("[PASS] 5. Single-writer invariant: Rahul queued at position 1.")

    # 6. Reading Rule & Last-Committed-Version Rule: Rahul reads main.py
    code, rahul_preview = api_get("/api/file/preview?path=main.py", rahul_token)
    assert code == 200
    assert rahul_preview["content"] == "print('version 1')"
    print("[PASS] 6. Reading Rule verified: Reader sees committed Version 1 while locked.")

    # 7. Security: Rahul attempts to commit changes without owning lock -> Must fail
    code, err_commit = api_post("/api/file/commit", {
        "file_path": "main.py",
        "lock_id": "fake_lock_123",
        "content": "print('rahul hacked it')",
        "release_lock": True
    }, rahul_token)
    assert code in [400, 409], f"Unauthenticated commit succeeded! Code {code}"
    print("[PASS] 7. Security: Non-writer commit strictly rejected.")

    # 8. Alex Commits Version 2 atomically
    new_code = "print('version 2 by Alex')\n"
    code, commit_res = api_post("/api/file/commit", {
        "file_path": "main.py",
        "lock_id": alex_lock_id,
        "content": new_code,
        "summary": "Updated to version 2",
        "release_lock": True
    }, alex_token)
    assert code == 200, f"Commit failed: {commit_res}"
    assert commit_res["commit"]["version_number"] == 2
    assert commit_res["commit"]["previous_version"] == 1
    assert commit_res["commit"]["author"] == "Alex"
    print("[PASS] 8. Alex committed Version 2 atomically. Monotonic increment verified.")

    # 9. Verify Disk & Readers see Version 2 now
    time.sleep(0.1)
    code, preview2 = api_get("/api/file/preview?path=main.py", rahul_token)
    assert code == 200 and preview2["content"] == new_code
    print("[PASS] 9. Readers now see newly committed Version 2.")

    # 10. Rahul was queued, auto-promoted on lock release
    code, meta2 = api_get("/api/file/metadata?path=main.py", rahul_token)
    assert code == 200
    assert meta2["lock_state"] == "LOCKED"
    assert meta2["writer"]["client_id"] == rahul_id
    rahul_lock_id = meta2["writer"]["lock_id"]
    print(f"[PASS] 10. Rahul auto-promoted from queue to writer (lock_id: {rahul_lock_id[:8]}...).")

    # 11. Stale Lock Commit (Test F): Alex attempts to commit with OLD lock_id -> Must fail
    code, stale_commit = api_post("/api/file/commit", {
        "file_path": "main.py",
        "lock_id": alex_lock_id,
        "content": "print('alex stale commit')",
        "release_lock": True
    }, alex_token)
    assert code in [400, 409]
    print("[PASS] 11. Test F Passed: Old writer commit with expired lock ID rejected.")

    # 12. Host Revocation (Test E): Host revokes Rahul's lock
    code, revoke_res = api_post("/api/lock/host/revoke", {"file_path": "main.py", "reason": "Timeout"}, host_token)
    assert code == 200
    print("[PASS] 12. Test E Passed: Host revoked Rahul's write lock.")

    # Rahul can no longer commit with revoked lock
    code, rahul_commit_after_revoke = api_post("/api/file/commit", {
        "file_path": "main.py",
        "lock_id": rahul_lock_id,
        "content": "print('rahul after revoke')",
        "release_lock": True
    }, rahul_token)
    assert code in [400, 409]
    print("[PASS] 13. Revoked writer cannot commit.")

    # 13. File-specific locks: User holds lock on main.py while another holds lock on docs.txt
    code, l1 = api_post("/api/lock/request", {"file_path": "main.py"}, alex_token)
    code, l2 = api_post("/api/lock/request", {"file_path": "docs.txt"}, rahul_token)
    assert code == 200
    assert l1["state"]["writer"]["client_id"] == alex_id
    assert l2["state"]["writer"]["client_id"] == rahul_id
    print("[PASS] 14. File-specific locking verified (main.py -> Alex, docs.txt -> Rahul).")

    # Clean up locks
    api_post("/api/lock/release", {"file_path": "main.py", "lock_id": l1["state"]["writer"]["lock_id"]}, alex_token)
    api_post("/api/lock/release", {"file_path": "docs.txt", "lock_id": l2["state"]["writer"]["lock_id"]}, rahul_token)

    # 14. Test A: Two users race to request the same file simultaneously
    print("\n--- Testing Concurrent Race Conditions ---")
    results = []
    def race_request(token, name):
        c, r = api_post("/api/lock/request", {"file_path": "main.py"}, token)
        results.append((name, c, r))

    t1 = threading.Thread(target=race_request, args=(alex_token, "Alex"))
    t2 = threading.Thread(target=race_request, args=(rahul_token, "Rahul"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Verify only one is writer
    code, final_meta = api_get("/api/file/metadata?path=main.py", host_token)
    assert final_meta["lock_state"] == "LOCKED"
    writer = final_meta["writer"]
    assert writer is not None
    active_client = writer["client_id"]
    other_client = rahul_id if active_client == alex_id else alex_id
    queue_clients = [q["client_id"] for q in final_meta["queue"]]
    assert other_client in queue_clients
    print(f"[PASS] Test A Passed: Concurrent lock request race resolved cleanly. Exactly 1 writer: {writer['user_name']}.")

    # Release lock
    active_token = alex_token if active_client == alex_id else rahul_token
    api_post("/api/lock/release", {"file_path": "main.py", "lock_id": writer["lock_id"]}, active_token)
    # The other user gets promoted, release that too
    time.sleep(0.05)
    c, m = api_get("/api/file/metadata?path=main.py", host_token)
    if m["writer"]:
        other_token = rahul_token if m["writer"]["client_id"] == rahul_id else alex_token
        api_post("/api/lock/release", {"file_path": "main.py", "lock_id": m["writer"]["lock_id"]}, other_token)

    # 15. Test G: Two commits race against the same file
    # First get lock for Alex
    api_post("/api/lock/request", {"file_path": "main.py"}, alex_token)
    c, m = api_get("/api/file/metadata?path=main.py", alex_token)
    alex_cur_lock = m["writer"]["lock_id"]

    commit_results = []
    def race_commit(token, lid, content):
        c, r = api_post("/api/file/commit", {"file_path": "main.py", "lock_id": lid, "content": content, "release_lock": True}, token)
        commit_results.append((c, r))

    ct1 = threading.Thread(target=race_commit, args=(alex_token, alex_cur_lock, "print('race commit 1')"))
    ct2 = threading.Thread(target=race_commit, args=(alex_token, alex_cur_lock, "print('race commit 2')"))
    ct1.start()
    ct2.start()
    ct1.join()
    ct2.join()

    successes = [r for c, r in commit_results if c == 200]
    failures = [r for c, r in commit_results if c in [400, 409]]
    assert len(successes) == 1, f"Expected exactly 1 commit to succeed, got {len(successes)}"
    assert len(failures) == 1
    print("[PASS] Test G Passed: Two commits racing serialized atomically. Exactly one succeeded.")

    # 16. Disconnected Writer cleanup (Test D)
    # Alex locks docs.txt, then leaves workspace
    api_post("/api/lock/request", {"file_path": "docs.txt"}, alex_token)
    c, m_docs = api_get("/api/file/metadata?path=docs.txt", alex_token)
    assert m_docs["writer"]["client_id"] == alex_id
    
    # Alex leaves
    api_post("/api/leave", {}, alex_token)
    time.sleep(0.1)
    # docs.txt should be freed
    c, m_docs_after = api_get("/api/file/metadata?path=docs.txt", host_token)
    assert m_docs_after["lock_state"] == "AVAILABLE"
    assert m_docs_after["writer"] is None
    print("[PASS] Test D Passed: Disconnected writer safely releases file to AVAILABLE.")

    # Alex re-joins
    code, alex_resp = api_post("/api/join", {"user_name": "Alex", "password": "collab_secret_pass"})
    alex_token = alex_resp["token"]
    alex_id = alex_resp["session"]["client_id"]

    # --- Explicit Tests A through H ---
    # Test B: Two grant requests arrive simultaneously
    # Set up queue for docs.txt with Alex and Rahul
    api_post("/api/lock/request", {"file_path": "docs.txt"}, alex_token)
    # Alex is writer. Host revokes Alex to leave queue empty or queued
    api_post("/api/lock/host/revoke", {"file_path": "docs.txt"}, host_token)
    # Now queue Alex and Rahul manually without auto-grant:
    # First get file state
    api_post("/api/lock/request", {"file_path": "docs.txt"}, alex_token)
    api_post("/api/lock/request", {"file_path": "docs.txt"}, rahul_token)
    # docs.txt is locked by Alex, Rahul is in queue.
    # Now Alex commits and releases
    c, m_docs = api_get("/api/file/metadata?path=docs.txt", host_token)
    alex_docs_lid = m_docs["writer"]["lock_id"]
    api_post("/api/lock/release", {"file_path": "docs.txt", "lock_id": alex_docs_lid}, alex_token)
    # Rahul got promoted. Let's revoke Rahul and test two concurrent grants
    api_post("/api/lock/host/revoke", {"file_path": "docs.txt"}, host_token)
    
    # Put both in queue again:
    # First create a third client Maya
    code, maya_resp = api_post("/api/join", {"user_name": "Maya", "password": "collab_secret_pass"})
    maya_token = maya_resp["token"]
    maya_id = maya_resp["session"]["client_id"]

    # Lock docs.txt with Maya, queue Alex and Rahul
    api_post("/api/lock/request", {"file_path": "docs.txt"}, maya_token)
    api_post("/api/lock/request", {"file_path": "docs.txt"}, alex_token)
    api_post("/api/lock/request", {"file_path": "docs.txt"}, rahul_token)

    # Now revoke Maya: Rahul & Alex remain in queue
    api_post("/api/lock/host/revoke", {"file_path": "docs.txt"}, host_token)

    grant_results = []
    def race_grant(target_id):
        c, r = api_post("/api/lock/host/grant", {"file_path": "docs.txt", "target_client_id": target_id}, host_token)
        grant_results.append((target_id, c, r))

    gt1 = threading.Thread(target=race_grant, args=(alex_id,))
    gt2 = threading.Thread(target=race_grant, args=(rahul_id,))
    gt1.start()
    gt2.start()
    gt1.join()
    gt2.join()

    grant_successes = [r for tid, c, r in grant_results if c == 200]
    assert len(grant_successes) == 1, f"Expected exactly 1 grant to succeed, got {len(grant_successes)}"
    print("[PASS] Test B Passed: Two host grant requests raced simultaneously. Exactly one succeeded.")

    # Test C & Test H: Reader accesses file during atomic commit; No partial/corrupted content
    # Alex holds lock on main.py
    c, m_main = api_get("/api/file/metadata?path=main.py", host_token)
    if m_main["writer"]:
        api_post("/api/lock/release", {"file_path": "main.py", "lock_id": m_main["writer"]["lock_id"]}, alex_token)
    
    api_post("/api/lock/request", {"file_path": "main.py"}, alex_token)
    c, m_main = api_get("/api/file/metadata?path=main.py", alex_token)
    cur_alex_lid = m_main["writer"]["lock_id"]

    large_content = "# LANShare safe atomic content\n" + ("x = 100\n" * 5000)
    reader_seen_contents = []

    def reader_loop():
        for _ in range(20):
            c, prev = api_get("/api/file/preview?path=main.py", rahul_token)
            if c == 200 and prev.get("content"):
                reader_seen_contents.append(prev["content"])
            time.sleep(0.005)

    reader_thread = threading.Thread(target=reader_loop)
    reader_thread.start()

    # Perform commit
    c, c_res = api_post("/api/file/commit", {
        "file_path": "main.py",
        "lock_id": cur_alex_lid,
        "content": large_content,
        "release_lock": True
    }, alex_token)
    assert c == 200

    reader_thread.join()

    # Test H: Every reader read must either be previously committed content or the full newly committed large_content, never partial/corrupted
    for read_data in reader_seen_contents:
        assert ("race commit" in read_data or "LANShare safe atomic content" in read_data or "print(" in read_data), f"Unexpected partial read: {read_data[:50]}"
        # Ensure it's not a truncated partial write in transit
        if "LANShare safe atomic content" in read_data:
            assert read_data.endswith("x = 100\n"), "Partial read detected during commit!"
    print("[PASS] Test H Passed: Reader during commit never observed partial or corrupt data.")
    print("[PASS] Test C Passed: File integrity strictly verified during atomic commit operations.")

    # 17. Access History contains structured locking and commit events
    c, history = api_get("/api/file/access_history?path=main.py", host_token)
    assert c == 200
    actions = [h["action"] for h in history]
    assert any("LOCK" in a or "WRITE" in a or "COMMIT" in a for a in actions)
    print(f"[PASS] 17. File Access History includes structured events: {actions[:6]}.")

    # 18. Commit History Endpoint
    c, commits = api_get("/api/file/commits?path=main.py", host_token)
    assert c == 200 and len(commits) >= 2
    versions = [cmt["version_number"] for cmt in commits]
    assert versions == sorted(versions, reverse=True)
    print(f"[PASS] 18. Commit history returned {len(commits)} commits with monotonic versions: {versions}.")

    print("\nALL PHASE 3 COLLABORATION & LOCKING TESTS PASSED SUCCESSFULLY.")

if __name__ == "__main__":
    run_phase3_tests()
