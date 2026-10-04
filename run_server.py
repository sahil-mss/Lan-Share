"""Entrypoint to run LANShare Server CLI / Backend daemon."""
import uvicorn
import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from server.app import app, SERVER_STATE, start_host_server, HostStartRequest
import socket
import asyncio
import logging
import copy
import subprocess
import threading


class FriendlyUrlFilter(logging.Filter):
    """Replaces non-clickable 0.0.0.0 in Uvicorn startup banner with valid http://localhost:port."""
    def filter(self, record):
        if record.args and len(record.args) >= 3 and record.args[1] == "0.0.0.0":
            args = list(record.args)
            args[1] = "localhost"
            record.args = tuple(args)
            # Must remove color_message or keep it in sync with record.args
            if hasattr(record, "color_message"):
                delattr(record, "color_message")
            if "color_message" in record.__dict__:
                del record.__dict__["color_message"]
        return True

def find_available_port(host: str, start_port: int, max_attempts: int = 100) -> int:
    """Find start_port or the next available port if start_port is occupied."""
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                # On Windows, SO_EXCLUSIVEADDRUSE prevents stealing occupied ports
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                s.bind((host, p))
                return p
            except OSError:
                continue
    # Fallback: let the OS assign an ephemeral port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]

def run():
    parser = argparse.ArgumentParser(description="LANShare Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind to")
    parser.add_argument("--port", type=int, default=7420, help="Port to listen on (auto-increments if in use)")
    parser.add_argument("--root", default=None, help="Auto-host folder path")
    parser.add_argument("--password", default=None, help="Password for auto-hosted folder")
    parser.add_argument("--name", default="Shared Workspace", help="Workspace Name")
    parser.add_argument("--hostname", default="Host", help="Host Display Name")
    parser.add_argument("--browser", action="store_true", default=True, help="Automatically open browser on launch")
    parser.add_argument("--no-browser", dest="browser", action="store_false", help="Do not open browser")
    parser.add_argument("--start-client", action="store_true", default=False, help="Also start Local Client daemon in background")

    args = parser.parse_args()

    actual_port = find_available_port(args.host, args.port)
    if actual_port != args.port:
        print(f"[LANShare] Requested port {args.port} is busy. Dynamically bound to port {actual_port}.")
    else:
        print(f"[LANShare] Server running on port {actual_port}.")

    # Pre-initialize workspace if root is supplied
    if args.root:
        async def init():
            req = HostStartRequest(
                workspace_name=args.name,
                shared_root=args.root,
                password=args.password or "",
                host_name=args.hostname,
                port=actual_port
            )
            await start_host_server(req)
        asyncio.run(init())

    # Optional Local Client startup
    if args.start_client:
        try:
            client_script = Path(__file__).parent / "client" / "main.py"
            subprocess.Popen([sys.executable, str(client_script), "--port", "7430"])
            print("[LANShare] Started Local Client daemon on http://127.0.0.1:7430")
        except Exception as e:
            print(f"[LANShare] Note: Could not auto-start local client daemon: {e}")

    # Auto-open browser in background thread
    if args.browser:
        def open_browser():
            import time
            import webbrowser
            time.sleep(1.0)
            webbrowser.open(f"http://localhost:{actual_port}")
        threading.Thread(target=open_browser, daemon=True).start()

    log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_config["filters"] = {
        "friendly_url": {
            "()": FriendlyUrlFilter,
        }
    }
    if "handlers" in log_config and "default" in log_config["handlers"]:
        log_config["handlers"]["default"]["filters"] = ["friendly_url"]

    try:
        uvicorn.run(app, host=args.host, port=actual_port, log_level="info", log_config=log_config)
    except (KeyboardInterrupt, SystemExit):
        print("\n[LANShare] Shutting down LANShare server...")
    finally:
        if SERVER_STATE.get("discovery"):
            try:
                SERVER_STATE["discovery"].stop()
            except Exception:
                pass
        print("[LANShare] Server stopped.")

if __name__ == "__main__":
    run()
