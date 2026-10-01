"""Entrypoint to run LANShare Server CLI / Backend daemon."""
import uvicorn
import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.app import app, SERVER_STATE, start_host_server, HostStartRequest
import asyncio

def run():
    parser = argparse.ArgumentParser(description="LANShare Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind to")
    parser.add_argument("--port", type=int, default=7420, help="Port to listen on")
    parser.add_argument("--root", default=None, help="Auto-host folder path")
    parser.add_argument("--password", default=None, help="Password for auto-hosted folder")
    parser.add_argument("--name", default="Shared Workspace", help="Workspace Name")
    parser.add_argument("--hostname", default="Host", help="Host Display Name")

    args = parser.parse_args()

    # Pre-initialize workspace if args are supplied
    if args.root and args.password:
        async def init():
            req = HostStartRequest(
                workspace_name=args.name,
                shared_root=args.root,
                password=args.password,
                host_name=args.hostname,
                port=args.port
            )
            await start_host_server(req)
        asyncio.run(init())

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")

if __name__ == "__main__":
    run()
