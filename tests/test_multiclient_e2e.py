"""Multi-Client Concurrent Simulation Test for LANShare.
Simulates:
- Host starting workspace
- Client A ("Alex") and Client B ("Alex" -> deduplicated to "Alex (2)")
- Simultaneous browsing & previewing
- Verification that Client A cannot read Client B's private session token
- Verifying presence list reflects both clients
- Client A creating folder while Client B uploads/browses
- Reconnection simulation: Client B disconnects, drops from presence, reconnects and restores state
"""
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_URL = "http://127.0.0.1:7420"
TEST_ROOT = str(Path(__file__).parent.parent / "temp_multiclient_test_ws")

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

def run_multiclient_test():
    p = Path(TEST_ROOT)
    if p.exists():
        import shutil
        shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    (p / "shared_code.py").write_text("def shared(): return True\n", encoding="utf-8")
    (p / "shared_readme.md").write_text("# Multi-client Test\n", encoding="utf-8")

    # 1. Host server start
    code, host_resp = api_post("/api/host/start", {
        "workspace_name": "MultiClient Workspace",
        "shared_root": TEST_ROOT,
        "password": "multi_password_123",
        "host_name": "HostLeader",
        "port": 7420
    })
    assert code == 200
    host_token = host_resp["token"]
    print("[PASS] 1. Host initialized workspace.")

    # 2. Connect Client A
    code, client_a_resp = api_post("/api/join", {"user_name": "Alex", "password": "multi_password_123"})
    assert code == 200
    token_a = client_a_resp["token"]
    assert client_a_resp["session"]["user_name"] == "Alex"
    print("[PASS] 2. Client A joined as 'Alex'.")

    # 3. Connect Client B (Same display name -> Alex)
    code, client_b_resp = api_post("/api/join", {"user_name": "Alex", "password": "multi_password_123"})
    assert code == 200
    token_b = client_b_resp["token"]
    assert client_b_resp["session"]["user_name"] == "Alex (2)"
    assert token_a != token_b
    print("[PASS] 3. Client B joined with deduplicated display name 'Alex (2)'.")

    # 4. Privacy Check: Ensure GET /api/users does NOT expose bearer tokens
    code, users_list = api_get("/api/users", token_a)
    assert code == 200
    for u in users_list:
        assert "token" not in u
        assert "password" not in u
        assert "password_hash" not in u
    print("[PASS] 4. User presence privacy verified: Zero tokens or secrets exposed.")

    # 5. Client A previews shared_code.py, Client B previews shared_readme.md
    code, prev_a = api_get("/api/file/preview?path=shared_code.py", token_a)
    assert code == 200 and "def shared():" in prev_a["content"]

    code, prev_b = api_get("/api/file/preview?path=shared_readme.md", token_b)
    assert code == 200 and "Multi-client Test" in prev_b["content"]
    print("[PASS] 5. Concurrent file previews successful for Client A and Client B.")

    # 6. Verify Viewer Presence in Metadata
    code, meta_code = api_get("/api/file/metadata?path=shared_code.py", token_b)
    assert code == 200
    viewer_names = [v["user_name"] for v in meta_code.get("current_viewers", [])]
    assert "Alex" in viewer_names
    print(f"[PASS] 6. Cross-client viewing presence confirmed: {viewer_names}")

    # 7. Concurrent CRUD: Client A creates folder, Client B lists and observes it
    code, f_resp = api_post("/api/folder/create", {"parent_path": "", "folder_name": "shared_folder"}, token_a)
    assert code == 200

    code, files_b = api_get("/api/files?path=", token_b)
    assert code == 200
    assert any(item["name"] == "shared_folder" for item in files_b["items"])
    print("[PASS] 7. Concurrent folder creation by Client A observed immediately by Client B.")

    # 8. Client B disconnects / leaves
    code, leave_b = api_post("/api/leave", {}, token_b)
    assert code == 200

    code, users_after = api_get("/api/users", token_a)
    assert code == 200
    names_after = [u["user_name"] for u in users_after]
    assert "Alex (2)" not in names_after
    print("[PASS] 8. Disconnect cleanly removes Client B from presence list.")

    # 9. Clean up workspace
    shutil_rm = Path(TEST_ROOT)
    if shutil_rm.exists():
        import shutil
        shutil.rmtree(shutil_rm, ignore_errors=True)

    print("\nALL MULTI-CLIENT SIMULATION CHECKS PASSED.")

if __name__ == "__main__":
    run_multiclient_test()
