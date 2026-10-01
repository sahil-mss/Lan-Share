"""LAN Discovery Service for LANShare.
Broadcasts UDP presence announcements across the local subnet and listens for other LAN workspaces.
Works purely over the LAN without external dependencies.
"""
import socket
import json
import threading
import time
from typing import Dict, Any, Callable, Optional

DISCOVERY_PORT = 7421
DISCOVERY_MAGIC = "LANSHARE_DISCOVER_v1"

class LANDiscovery:
    def __init__(self, port: int = DISCOVERY_PORT):
        self.port = port
        self.running = False
        self.broadcaster_thread: Optional[threading.Thread] = None
        self.listener_thread: Optional[threading.Thread] = None
        self.discovered_servers: Dict[str, Dict[str, Any]] = {}
        self.on_server_discovered: Optional[Callable[[Dict[str, Any]], None]] = None

    def start_broadcasting(self, workspace_name: str, host_name: str, http_port: int):
        self.running = True
        
        def broadcast_loop():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(1.0)
            
            payload = {
                "magic": DISCOVERY_MAGIC,
                "workspace_name": workspace_name,
                "host_name": host_name,
                "http_port": http_port,
                "timestamp": time.time()
            }
            
            while self.running:
                try:
                    data = json.dumps(payload).encode("utf-8")
                    sock.sendto(data, ("<broadcast>", self.port))
                except Exception:
                    pass
                time.sleep(2.5)
            sock.close()

        self.broadcaster_thread = threading.Thread(target=broadcast_loop, daemon=True)
        self.broadcaster_thread.start()

    def start_listening(self, callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.running = True
        self.on_server_discovered = callback

        def listen_loop():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("", self.port))
            except Exception:
                return

            sock.settimeout(2.0)

            while self.running:
                try:
                    data, addr = sock.recvfrom(2048)
                    ip = addr[0]
                    obj = json.loads(data.decode("utf-8"))
                    if obj.get("magic") == DISCOVERY_MAGIC:
                        server_key = f"{ip}:{obj.get('http_port')}"
                        server_info = {
                            "key": server_key,
                            "ip": ip,
                            "http_port": obj.get("http_port"),
                            "address": f"http://{ip}:{obj.get('http_port')}",
                            "workspace_name": obj.get("workspace_name"),
                            "host_name": obj.get("host_name"),
                            "last_seen": time.time()
                        }
                        self.discovered_servers[server_key] = server_info
                        if self.on_server_discovered:
                            self.on_server_discovered(server_info)
                except socket.timeout:
                    continue
                except Exception:
                    continue
            sock.close()

        self.listener_thread = threading.Thread(target=listen_loop, daemon=True)
        self.listener_thread.start()

    def get_active_servers(self, timeout_seconds: float = 6.0) -> list:
        now = time.time()
        # Clean stale servers
        active = []
        for k, v in list(self.discovered_servers.items()):
            if now - v["last_seen"] <= timeout_seconds:
                active.append(v)
            else:
                self.discovered_servers.pop(k, None)
        return active

    def stop(self):
        self.running = False
