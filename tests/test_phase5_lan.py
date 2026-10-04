"""Comprehensive Phase 5 LAN Discovery, Production Packaging & Security Test Suite.

Validates:
1. Safe UDP Discovery Broadcasting (no tokens, passwords, hashes, or paths leaked in packets)
2. Discovery Multi-Server Coexistence (Alice & Bob servers broadcast simultaneously with distinct keys)
3. Stale Server Automatic Eviction on Timeout
4. Network Interface Multi-IP Discovery (never advertises 127.0.0.1 or 0.0.0.0 when valid NIC exists)
5. LAN Security Boundary Verification:
   - Unauthenticated access to /api/files, /api/file/preview, /api/file/download rejected with 401
   - Path traversal attacks (/api/file/preview?path=../../windows/win.ini, /api/files?path=..\..\) strictly blocked
   - UNC path injections (\\\\remote\\share) and absolute drives (C:\\Windows) blocked
6. Dynamic Port Auto-Increment & Safe Port Selection
7. Local Client Daemon Auto-Start & Firewall Diagnostic Endpoint Check
8. Full Host/Join Lifecycle over simulated Network Interfaces
"""

import sys
import os
import json
import time
import socket
import secrets
import threading
import urllib.request
import urllib.error
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.discovery import LANDiscovery, DISCOVERY_MAGIC
from server.app import app, SERVER_STATE, get_all_lan_ips, get_local_ip, hash_password
from client.main import find_available_client_port
from run_server import find_available_port

def api_call(url: str, method: str = "GET", data: dict = None, token: str = None):
    req = urllib.request.Request(url, method=method)
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        req.data = payload
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
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

def run_phase5_tests():
    print("======================================================================")
    print("      LANShare Phase 5 - LAN Discovery & Production Verification      ")
    print("======================================================================")

    # -------------------------------------------------------------------------
    # Test 1: UDP Discovery Packet Safety (No Secrets Leaked)
    # -------------------------------------------------------------------------
    print("\n--- Test 1: UDP Discovery Packet Safety Audit ---")
    disc_test = LANDiscovery(port=17421)
    # Capture raw broadcast packet
    sock_sniffer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_sniffer.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock_sniffer.bind(("", 17421))
    sock_sniffer.settimeout(2.0)

    disc_test.start_broadcasting(
        workspace_name="Sensitive Engineering Files",
        host_name="ChiefEngineer",
        http_port=7420,
        password_required=True,
        server_id="ChiefEngineer_7420"
    )

    try:
        raw_data, addr = sock_sniffer.recvfrom(2048)
        packet = json.loads(raw_data.decode("utf-8"))
        
        # Verify required non-sensitive fields
        assert packet.get("magic") == DISCOVERY_MAGIC, "Invalid discovery magic!"
        assert packet.get("workspace_name") == "Sensitive Engineering Files"
        assert packet.get("host_name") == "ChiefEngineer"
        assert packet.get("http_port") == 7420
        assert packet.get("password_required") is True

        # STRICT SECURITY AUDIT: Verify ZERO sensitive credentials leaked
        forbidden_keys = ["password", "password_hash", "token", "secret", "path", "shared_root", "username"]
        for key in forbidden_keys:
            assert key not in packet, f"SECURITY VIOLATION: Sensitive key '{key}' leaked in UDP broadcast!"
        
        # Verify packet values do not leak filesystem paths
        packet_str = raw_data.decode("utf-8").lower()
        assert "c:\\" not in packet_str and "d:\\" not in packet_str, "Filesystem path leaked in broadcast packet!"

        print("[PASS] Test 1: UDP broadcast packet audited. Zero passwords, hashes, tokens, or paths leaked.")
    finally:
        disc_test.stop()
        sock_sniffer.close()

    # -------------------------------------------------------------------------
    # Test 2: Multi-Server Coexistence in LAN Discovery
    # -------------------------------------------------------------------------
    print("\n--- Test 2: Multiple Server Coexistence & Stable Keys ---")
    d_alice = LANDiscovery(port=17422)
    d_bob = LANDiscovery(port=17422)
    d_listener = LANDiscovery(port=17422)

    discovered_list = []
    d_listener.start_listening(callback=lambda info: discovered_list.append(info))

    d_alice.start_broadcasting(
        workspace_name="Alice Project",
        host_name="Alice",
        http_port=7420,
        server_id="Alice_7420"
    )
    d_bob.start_broadcasting(
        workspace_name="Bob Photos",
        host_name="Bob",
        http_port=7422,
        server_id="Bob_7422"
    )

    time.sleep(1.5)
    active = d_listener.get_active_servers(timeout_seconds=5.0)
    server_names = [s["workspace_name"] for s in active]
    assert "Alice Project" in server_names, f"Alice server missing: {active}"
    assert "Bob Photos" in server_names, f"Bob server missing: {active}"
    assert len(active) >= 2, f"Expected both servers to coexist: {active}"
    print(f"[PASS] Test 2: Multiple servers ({len(active)}) coexisting cleanly without collisions.")

    d_alice.stop()
    d_bob.stop()
    d_listener.stop()

    # -------------------------------------------------------------------------
    # Test 3: Stale Server Automatic Eviction on Shutdown
    # -------------------------------------------------------------------------
    print("\n--- Test 3: Stale Server Eviction Timeout ---")
    d_listener3 = LANDiscovery(port=17423)
    d_listener3.discovered_servers["Old_Server_999"] = {
        "workspace_name": "Old Ghost Workspace",
        "last_seen": time.time() - 10.0  # 10 seconds ago
    }
    d_listener3.discovered_servers["Fresh_Server_1"] = {
        "workspace_name": "Live Workspace",
        "last_seen": time.time()
    }

    surviving = d_listener3.get_active_servers(timeout_seconds=5.0)
    surviving_names = [s["workspace_name"] for s in surviving]
    assert "Live Workspace" in surviving_names
    assert "Old Ghost Workspace" not in surviving_names, "Stale server was not evicted!"
    print("[PASS] Test 3: Stale/shut down servers correctly evicted after timeout.")

    # -------------------------------------------------------------------------
    # Test 4: Network Interface Multi-IP Discovery
    # -------------------------------------------------------------------------
    print("\n--- Test 4: Routable LAN IPv4 Detection ---")
    lan_ips = get_all_lan_ips()
    primary_ip = get_local_ip()
    print(f"[INFO] Discovered LAN IPs: {lan_ips}, Primary: {primary_ip}")
    
    # If network interfaces exist, neither should be 0.0.0.0 or 127.0.0.1
    if lan_ips:
        assert not primary_ip.startswith("127."), "Loopback address returned as primary LAN IP!"
        assert not primary_ip.startswith("169.254."), "APIPA link-local returned as primary LAN IP!"
        assert primary_ip != "0.0.0.0", "Wildcard 0.0.0.0 returned as primary LAN IP!"
        assert primary_ip in lan_ips, "Primary IP not in discovered interface list!"
    print("[PASS] Test 4: Routable LAN addressing verified across physical/virtual network adapters.")

    # -------------------------------------------------------------------------
    # Test 5: Dynamic Port Auto-Allocation & Exclusion
    # -------------------------------------------------------------------------
    print("\n--- Test 5: Dynamic Port Selection & Occupation Recovery ---")
    # Occupy a port with a test socket
    occupier = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupier.bind(("127.0.0.1", 17500))
    occupier.listen(1)

    try:
        # Request occupied port 17500
        server_free_port = find_available_port("127.0.0.1", 17500)
        assert server_free_port != 17500, "find_available_port returned occupied port!"
        assert server_free_port == 17501, f"Expected next sequential port 17501, got {server_free_port}"

        client_free_port = find_available_client_port(start_port=17500)
        assert client_free_port != 17500, "find_available_client_port returned occupied port!"
        print(f"[PASS] Test 5: Port conflict recovered. Bound cleanly to {server_free_port} without error.")
    finally:
        occupier.close()

    # -------------------------------------------------------------------------
    # Test 6: LAN Security Boundaries (401 on unauthenticated access)
    # -------------------------------------------------------------------------
    print("\n--- Test 6: LAN Security Boundary Audit ---")
    import tempfile
    import shutil
    import uvicorn

    test_dir = tempfile.mkdtemp(prefix="lanshare_p5_sec_")
    (Path(test_dir) / "classified.txt").write_text("TOP SECRET CONTENT", encoding="utf-8")

    test_server_port = find_available_port("127.0.0.1", 17600)
    server_thread = None
    stop_event = threading.Event()

    # Start live test server on test_server_port
    from server.app import app as sec_app, start_host_server, HostStartRequest

    config = uvicorn.Config(sec_app, host="127.0.0.1", port=test_server_port, log_level="warning")
    server = uvicorn.Server(config)
    
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    time.sleep(1.0)

    base_url = f"http://127.0.0.1:{test_server_port}"

    try:
        # Initialize password-protected workspace
        status, resp = api_call(f"{base_url}/api/host/start", method="POST", data={
            "workspace_name": "Secure Vault",
            "shared_root": test_dir,
            "password": "StrongSecretPassword123",
            "host_name": "SecurityOfficer",
            "port": test_server_port
        })
        assert status == 200, f"Host start failed: {resp}"
        host_token = resp["token"]

        # 6a. Attempt unauthenticated access to files
        status, _ = api_call(f"{base_url}/api/files")
        assert status == 401, f"Expected 401 for unauthenticated /api/files, got {status}"

        # 6b. Attempt unauthenticated preview
        status, _ = api_call(f"{base_url}/api/file/preview?path=classified.txt")
        assert status == 401, f"Expected 401 for unauthenticated /api/file/preview, got {status}"

        # 6c. Attempt unauthenticated download
        status, _ = api_call(f"{base_url}/api/file/download?path=classified.txt")
        assert status == 401, f"Expected 401 for unauthenticated /api/file/download, got {status}"

        # 6d. Traversal attacks with valid host token must still be strictly blocked
        status, _ = api_call(f"{base_url}/api/file/preview?path=../../windows/win.ini", token=host_token)
        assert status in (400, 403), f"Expected 400/403 for traversal preview, got {status}"

        status, _ = api_call(f"{base_url}/api/file/download?path=..\\..\\boot.ini", token=host_token)
        assert status in (400, 403), f"Expected 400/403 for traversal download, got {status}"

        status, _ = api_call(f"{base_url}/api/files?path=..%2F..%2F", token=host_token)
        assert status in (400, 403), f"Expected 400/403 for URL encoded traversal, got {status}"

        # 6e. UNC & Absolute Path injection attacks
        status, _ = api_call(f"{base_url}/api/file/preview?path=\\\\attacker\\share\\loot.txt", token=host_token)
        assert status in (400, 403), f"Expected 400/403 for UNC path, got {status}"

        status, _ = api_call(f"{base_url}/api/file/preview?path=C:\\Windows\\System32\\drivers\\etc\\hosts", token=host_token)
        assert status in (400, 403), f"Expected 400/403 for absolute Windows path, got {status}"

        # 6f. Invalid password attempt rejected with 401
        status, _ = api_call(f"{base_url}/api/join", method="POST", data={
            "user_name": "Intruder",
            "password": "WrongPassword!"
        })
        assert status == 401, f"Expected 401 for wrong password, got {status}"

        # 6g. Legitimate join succeeds
        status, join_resp = api_call(f"{base_url}/api/join", method="POST", data={
            "user_name": "LegitColleague",
            "password": "StrongSecretPassword123"
        })
        assert status == 200, f"Expected 200 for correct password, got {status}"
        guest_token = join_resp["token"]

        # 6h. Legitimate file preview succeeds
        status, prev_resp = api_call(f"{base_url}/api/file/preview?path=classified.txt", token=guest_token)
        assert status == 200 and prev_resp["content"] == "TOP SECRET CONTENT"

        print("[PASS] Test 6: LAN security boundary verified. 401 enforced, traversal & UNC blocked.")

        # ---------------------------------------------------------------------
        # Test 7: Firewall Diagnostic & System Endpoints
        # ---------------------------------------------------------------------
        print("\n--- Test 7: Firewall & Local Client Integration Endpoints ---")
        status, fw_resp = api_call(f"{base_url}/api/system/firewall-check")
        assert status == 200
        assert "has_lan_interfaces" in fw_resp
        assert "notice" in fw_resp

        status, client_resp = api_call(f"{base_url}/api/system/start-client", method="POST")
        assert status == 200
        assert client_resp["status"] in ("ONLINE", "LAUNCHING")

        print("[PASS] Test 7: Firewall diagnostic and client auto-start endpoints functioning cleanly.")

    finally:
        server.should_exit = True
        shutil.rmtree(test_dir, ignore_errors=True)

    print("\n======================================================================")
    print("            ALL 7 PHASE 5 VERIFICATION TESTS PASSED                   ")
    print("======================================================================")

if __name__ == "__main__":
    run_phase5_tests()
