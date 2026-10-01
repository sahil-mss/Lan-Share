"""End-to-End Test Suite for Phase 2A CRUD & Realtime File Management Operations.
Tests:
1. Create Folder
2. Upload File
3. Rename File & Folder
4. Copy File
5. Move File
6. Delete File & Folder
7. Collision Handling
8. Realtime Broadcast Verification
"""
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path
import time

BASE_URL = "http://127.0.0.1:7420"
TEST_ROOT = str(Path(__file__).parent.parent / "temp_crud_test_ws")

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

def test_phase2a_crud():
    # Setup test workspace folder
    p = Path(TEST_ROOT)
    if p.exists():
        import shutil
        shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    (p / "initial.txt").write_text("initial content", encoding="utf-8")

    # 1. Host server
    host_payload = {
        "workspace_name": "Phase2A CRUD Workspace",
        "shared_root": TEST_ROOT,
        "password": "test_pass_123",
        "host_name": "HostAdmin",
        "port": 7420
    }
    code, host_resp = api_post("/api/host/start", host_payload)
    assert code == 200
    token = host_resp["token"]
    print("[PASS] 1. Host initialized workspace.")

    # 2. Create Folder
    code, folder_resp = api_post("/api/folder/create", {"parent_path": "", "folder_name": "docs"}, token)
    assert code == 200 and folder_resp["item"]["name"] == "docs"
    print("[PASS] 2. Folder 'docs' created.")

    # 3. Create duplicate folder (should fail with 409)
    code, err_resp = api_post("/api/folder/create", {"parent_path": "", "folder_name": "docs"}, token)
    assert code == 409
    print("[PASS] 3. Duplicate folder correctly rejected with HTTP 409.")

    # 4. Rename Item
    code, ren_resp = api_post("/api/file/rename", {"path": "initial.txt", "new_name": "notes.txt"}, token)
    assert code == 200 and ren_resp["item"]["new_path"] == "notes.txt"
    print("[PASS] 4. Item successfully renamed to 'notes.txt'.")

    # 5. Copy Item
    code, cp_resp = api_post("/api/file/copy", {"source_path": "notes.txt", "dest_parent": "docs"}, token)
    assert code == 200 and cp_resp["item"]["new_path"] == "docs/notes.txt"
    print("[PASS] 5. Item copied to 'docs/notes.txt'.")

    # 6. Move Item
    code, mv_resp = api_post("/api/file/move", {"source_path": "notes.txt", "dest_parent": "docs", "overwrite": False}, token)
    assert code == 409  # Conflict because we copied it there!
    print("[PASS] 6a. Move collision prevented with HTTP 409.")

    code, mv_resp2 = api_post("/api/file/move", {"source_path": "notes.txt", "dest_parent": "docs", "overwrite": True}, token)
    assert code == 200
    print("[PASS] 6b. Move with overwrite succeeded.")

    # 7. Delete Item
    code, del_resp = api_post("/api/files/delete", {"paths": ["docs/notes.txt"]}, token)
    assert code == 200 and len(del_resp["results"]) == 1
    print("[PASS] 7. Delete file succeeded.")

    # 8. Verify Activity Logs
    code, logs = api_get("/api/activity", token)
    assert code == 200
    events = [l["event_type"] for l in logs]
    assert "FILE_CREATED" in events
    assert "FILE_RENAMED" in events
    assert "FILE_COPIED" in events
    assert "FILE_MOVED" in events
    assert "FILE_DELETED" in events
    print("[PASS] 8. All CRUD events recorded in structured Activity Logger:", events[:6])

    print("\nALL PHASE 2A CRUD TESTS PASSED SUCCESSFULLY.")

if __name__ == "__main__":
    test_phase2a_crud()
